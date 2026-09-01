"""Dense retrieval over the unified corpus via pluggable embedding providers, file-backed with sqlite-vec.

Provider abstraction (Phase A): every provider exposes
    name (str, e.g. "gemini" / "voyage")
    model (str)
    dims (int)
    embed(texts: list[str], input_type: str) -> list[list[float]]
with shared 429/retry backoff and batch pacing. The active provider is chosen
by the KB_EMBED_PROVIDER env var (default "gemini") or the CLI --provider flag
(--provider gemini|voyage), which takes precedence.

Providers:
    gemini  gemini-embedding-001, 3072 dims (default; unchanged behavior)
    voyage  voyage-3, 1024 dims (opt-in)

Storage decision (orchestrator-approved): file-backed hybrid stack. BM25 lives in
SQLite FTS5 and dense vectors live in sqlite-vec (both plain files under data/kb/),
so the whole retrieval layer needs no server. pgvector is the documented Postgres
production path, but no Postgres instance exists on this machine and installing one
is out of scope; sqlite-vec 0.1.9 gives equivalent kNN semantics for this corpus size.

Per-provider storage: because vector dimensionality differs (3072 vs 1024), vectors
MUST NOT mix in one vec0 table. Each provider gets its own DB file:
    gemini  -> data/kb/dense.db          (existing, 160 Gemini 3072-dim vectors)
    voyage  -> data/kb/dense-voyage.db   (built by `--provider voyage --build`)
No migration is performed; the existing Gemini DB stays exactly as-is.

Contract (shared with kb/bm25.py and kb/hybrid.py):
    retrieve(question, top_k=10) -> list[post_id]           (ranked)
    retrieve_scored(question, top_k=10) -> list[(post_id, score)]  (cosine similarity)

CLI:
    uv run python -m kb.dense --summary                        # active provider stats + sample retrieve
    uv run python -m kb.dense --build                          # build/refresh for the active provider
    uv run python -m kb.dense --provider voyage --summary      # inspect the Voyage store
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai

from kb.consolidate import load_merged

REPO_ROOT = Path(__file__).resolve().parent.parent
# GEMINI_API_KEY / VOYAGE_API_KEY are read from THIS repo's .env (see .env.example). For
# backward-compat during the transition, fall back to the sibling scrape repo's
# .env only if the key is not already set here. Never hardcoded.
load_dotenv(REPO_ROOT / ".env")
load_dotenv("C:/Users/evano/repos/scrape-ig-saved-list/.env", override=False)

# Active provider selection: --provider CLI flag overrides; env KB_EMBED_PROVIDER
# is the fallback; "gemini" is the default.
PROVIDER_ENV_VAR = "KB_EMBED_PROVIDER"

# Module-level aliases retained for backward compatibility; they describe the
# DEFAULT (gemini) provider. Per-provider values live on the provider objects.
DB_PATH = REPO_ROOT / "data" / "kb" / "dense.db"
EMBED_MODEL = "gemini-embedding-001"
BATCH_SIZE = 40  # Gemini embedding API limit is 100 texts/request; stay comfortably under.
MAX_RETRIES = 12
DIMS = 3072  # gemini-embedding-001 default output dimensionality


class DenseRetrievalError(RuntimeError):
    """Raised when embeddings are unavailable (missing API key or failed API call)."""


def _api_key(var: str) -> str:
    """Read an API key from the environment, raising a clear error if absent."""
    key = os.environ.get(var, "").strip()
    if not key:
        raise DenseRetrievalError(
            f"{var} not set (expected in this repo's .env — see .env.example)"
        )
    return key


class GeminiProvider:
    """gemini-embedding-001, 3072 dims; the default provider (existing behavior)."""

    name = "gemini"
    model = "gemini-embedding-001"
    dims = 3072
    batch_size = BATCH_SIZE
    db_path = REPO_ROOT / "data" / "kb" / "dense.db"

    def __init__(self) -> None:
        self._client = genai.Client(api_key=_api_key("GEMINI_API_KEY"))

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Embed texts via Gemini; input_type is accepted for contract parity and ignored."""
        resp = self._client.models.embed_content(model=self.model, contents=texts)
        return [list(e.values) for e in resp.embeddings]


class VoyageProvider:
    """voyage-3, 1024 dims; opt-in via KB_EMBED_PROVIDER=voyage or --provider voyage."""

    name = "voyage"
    model = "voyage-3"
    dims = 1024
    batch_size = BATCH_SIZE  # voyageai accepts up to 128 texts/request; same pacing
    db_path = REPO_ROOT / "data" / "kb" / "dense-voyage.db"

    def __init__(self) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=_api_key("VOYAGE_API_KEY"))

    def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Embed texts via Voyage (input_type: 'document' or 'query')."""
        r = self._client.embed(texts=texts, model=self.model, input_type=input_type)
        return [list(e) for e in r.embeddings]


PROVIDERS: dict[str, type] = {
    GeminiProvider.name: GeminiProvider,
    VoyageProvider.name: VoyageProvider,
}


def _provider(name: str | None = None):
    """Instantiate the selected embedding provider.

    `name` (CLI --provider) wins; otherwise KB_EMBED_PROVIDER; otherwise "gemini".
    """
    selected = (name or os.environ.get(PROVIDER_ENV_VAR, "") or "gemini").strip().lower()
    cls = PROVIDERS.get(selected)
    if cls is None:
        raise DenseRetrievalError(
            f"unknown provider {selected!r} (known: {', '.join(sorted(PROVIDERS))})"
        )
    return cls()


def index_text(rec: dict[str, Any]) -> str:
    """Build the indexable text blob for one post: summary + workflow_steps + tips +
    concepts(terms+explanations) + transcript + tools_apps + tags + resources(names+purpose)."""
    parts: list[str] = [rec.get("summary") or ""]

    def _flat(items: Any) -> list[str]:
        """Normalize a field that may hold strings or dicts into strings."""
        out = []
        for it in items or []:
            if isinstance(it, dict):
                out.append(" ".join(str(v) for v in it.values() if v))
            elif it:
                out.append(str(it))
        return out

    parts += _flat(rec.get("workflow_steps"))
    parts += _flat(rec.get("tips"))
    for c in rec.get("concepts") or []:
        term = c.get("term") if isinstance(c, dict) else None
        expl = c.get("explanation") if isinstance(c, dict) else None
        if term:
            parts.append(f"{term}: {expl}" if expl else str(term))
    parts.append(rec.get("transcript") or "")
    parts += _flat(rec.get("tools_apps"))
    parts += _flat(rec.get("tags"))
    for r in rec.get("resources") or []:
        if isinstance(r, dict):
            name = r.get("name") or ""
            purpose = r.get("purpose") or ""
            if name or purpose:
                parts.append(f"{name} — {purpose}".strip(" —"))
    return "\n".join(p for p in parts if p).strip()


def _embed_with_retry(provider, texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed one batch with retry/backoff on rate limits and transient errors.

    On 429s the server-supplied "retry in Xs" hint is honored (plus margin), since the
    free-tier quota is shared and strict per-minute."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return provider.embed(texts, input_type=input_type)
        except Exception as err:  # noqa: BLE001 - API errors vary; backoff uniformly
            last_err = err
            msg = str(err)
            # Honor the API's suggested retry delay (429/ResourceExhausted carry a
            # "retry in Xs" / RetryDelay hint) exactly plus a small margin; fall back
            # to exponential backoff clamped to 10-30s when no hint is present.
            wait = min(30, max(10, 2**attempt))
            m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
            if not m:
                m = re.search(r"retry(?:delay|Delay)?[\"': =]+(\d+(?:\.\d+)?)", msg)
            if m:
                wait = int(float(m.group(1))) + 2
            print(f"dense: embed attempt {attempt + 1}/{MAX_RETRIES} failed ({msg.splitlines()[0][:160]}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise DenseRetrievalError(f"embedding failed after {MAX_RETRIES} retries: {last_err}") from last_err


def _embed_batch(provider, texts: list[str]) -> list[list[float]]:
    """Backward-compatible alias: embed one document batch with retry/backoff."""
    return _embed_with_retry(provider, texts, input_type="document")


def _vec_to_blob(vec: list[float]) -> bytes:
    """Pack a float32 vector as little-endian bytes for sqlite-vec storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def build(overwrite: bool = False, provider_name: str | None = None) -> int:
    """Embed all corpus posts (skipping post_ids already in the DB) and store them.

    Idempotent by post_id: re-runs embed only new posts. Posts whose index text is
    empty are skipped and logged. Returns the number of vectors newly stored.
    Vectors go to the selected provider's own DB file (never mixed across providers)."""
    import sqlite3

    import sqlite_vec

    provider = _provider(provider_name)
    records = load_merged()
    texts = {rec["post_id"]: index_text(rec) for rec in records}
    empty = [pid for pid, t in texts.items() if not t.strip()]
    for pid in empty:
        texts.pop(pid)
    if empty:
        print(f"dense: skipping {len(empty)} empty-text posts: {empty}", file=sys.stderr)

    db_path = provider.db_path
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS posts USING vec0("
        "post_id TEXT PRIMARY KEY, vec FLOAT[" + str(provider.dims) + "])"
    )
    conn.commit()

    have = {pid for (pid,) in conn.execute("SELECT post_id FROM posts")}
    if overwrite:
        conn.execute("DELETE FROM posts")
        conn.commit()
        have = set()
    todo = [(pid, t) for pid, t in texts.items() if pid not in have]

    if not todo:
        print(f"dense: nothing to embed ({len(have)} vectors already present)")
        return 0

    stored = 0
    batch_size = provider.batch_size
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        pids = [pid for pid, _ in batch]
        vecs = _embed_with_retry(provider, [t for _, t in batch])
        conn.executemany(
            "INSERT OR REPLACE INTO posts(post_id, vec) VALUES (?, ?)",
            [(pid, _vec_to_blob(v)) for pid, v in zip(pids, vecs)],
        )
        conn.commit()
        stored += len(pids)
        print(f"dense: embedded {stored}/{len(todo)} posts", file=sys.stderr)
        if i + batch_size < len(todo):
            time.sleep(5)  # pace under the shared global per-minute embedding quota
    print(f"dense: stored {stored} new vectors in {db_path}")
    return stored


def _connect(provider_name: str | None = None):
    """Open the selected provider's sqlite-vec database with the extension loaded."""
    import sqlite3

    import sqlite_vec

    db_path = _provider(provider_name).db_path
    if not db_path.exists():
        raise DenseRetrievalError(
            f"vector store missing at {db_path}; run `uv run python -m kb.dense --build` first"
        )
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def retrieve_scored(question: str, top_k: int = 10, provider_name: str | None = None) -> list[tuple[str, float]]:
    """Embed the question and return the top_k (post_id, cosine_similarity) pairs, ranked."""
    provider = _provider(provider_name)
    conn = _connect(provider_name)
    try:
        [qv] = _embed_with_retry(provider, [question], input_type="query")
        rows = conn.execute(
            """
            SELECT post_id, distance
            FROM posts
            WHERE vec MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (_vec_to_blob(qv), top_k),
        ).fetchall()
    finally:
        conn.close()
    return [(pid, 1.0 - dist) for pid, dist in rows]  # sqlite-vec default metric = cosine distance


def retrieve(question: str, top_k: int = 10, provider_name: str | None = None) -> list[str]:
    """Return the top_k ranked post_ids for a question via dense cosine similarity."""
    return [pid for pid, _score in retrieve_scored(question, top_k=top_k, provider_name=provider_name)]


def main() -> int:
    """CLI entry: --build (re)builds the vector store; --summary prints stats + a sample retrieve."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="embed new posts and store vectors")
    parser.add_argument("--summary", action="store_true", help="print n_vectors, model, sample retrieve")
    parser.add_argument("--overwrite", action="store_true", help="re-embed all posts even if cached")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        default=None,
        help=f"embedding provider (default: ${PROVIDER_ENV_VAR} or gemini)",
    )
    args = parser.parse_args()

    try:
        provider = _provider(args.provider)
        if args.build or args.overwrite:
            build(overwrite=args.overwrite, provider_name=args.provider)
        if not args.summary:
            return 0

        print(f"provider={provider.name}")
        print(f"model={provider.model}")
        try:
            conn = _connect(args.provider)
            n = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            conn.close()
        except DenseRetrievalError as err:
            print(f"WARNING: {err}")
            return 0
        print(f"n_vectors={n}")
        try:
            hits = retrieve("font pairing", top_k=5, provider_name=args.provider)
            print("sample retrieve('font pairing'):")
            for pid in hits:
                print(f"  {pid}")
        except DenseRetrievalError as err:
            print(f"WARNING: sample retrieve failed: {err}")
        return 0
    except DenseRetrievalError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
