"""Dense retrieval over the unified corpus via Gemini embeddings, file-backed with sqlite-vec.

Storage decision (orchestrator-approved): file-backed hybrid stack. BM25 lives in
SQLite FTS5 and dense vectors live in sqlite-vec (both plain files under data/kb/),
so the whole retrieval layer needs no server. pgvector is the documented Postgres
production path, but no Postgres instance exists on this machine and installing one
is out of scope; sqlite-vec 0.1.9 gives equivalent kNN semantics for this corpus size.

Contract (shared with kb/bm25.py and kb/hybrid.py):
    retrieve(question, top_k=10) -> list[post_id]           (ranked)
    retrieve_scored(question, top_k=10) -> list[(post_id, score)]  (cosine similarity)

CLI:
    uv run python -m kb.dense --summary    # n_vectors + sample retrieve
    uv run python -m kb.dense --build      # (re)build/refresh the vector store
"""

from __future__ import annotations

import argparse
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
# GEMINI_API_KEY is read from THIS repo's .env (see .env.example). For
# backward-compat during the transition, fall back to the sibling scrape repo's
# .env only if the key is not already set here. Never hardcoded.
load_dotenv(REPO_ROOT / ".env")
load_dotenv("C:/Users/evano/repos/scrape-ig-saved-list/.env", override=False)

DB_PATH = REPO_ROOT / "data" / "kb" / "dense.db"
EMBED_MODEL = "gemini-embedding-001"
BATCH_SIZE = 40  # Gemini embedding API limit is 100 texts/request; stay comfortably under.
MAX_RETRIES = 12
DIMS = 3072  # gemini-embedding-001 default output dimensionality


class DenseRetrievalError(RuntimeError):
    """Raised when embeddings are unavailable (missing API key or failed API call)."""


def _client() -> genai.Client:
    """Create a Gemini client, raising a clear error if no API key is configured."""
    import os

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise DenseRetrievalError(
            "GEMINI_API_KEY not set (expected in this repo's .env — see .env.example)"
        )
    return genai.Client(api_key=key)


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


def _embed_batch(client: genai.Client, texts: list[str]) -> list[list[float]]:
    """Embed one batch of texts with retry/backoff on rate limits and transient errors.

    On 429s the server-supplied "retry in Xs" hint is honored (plus margin), since the
    free-tier quota is shared and strict per-minute."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.models.embed_content(model=EMBED_MODEL, contents=texts)
            return [list(e.values) for e in resp.embeddings]
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


def _vec_to_blob(vec: list[float]) -> bytes:
    """Pack a float32 vector as little-endian bytes for sqlite-vec storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def build(overwrite: bool = False) -> int:
    """Embed all corpus posts (skipping post_ids already in the DB) and store them.

    Idempotent by post_id: re-runs embed only new posts. Posts whose index text is
    empty are skipped and logged. Returns the number of vectors newly stored."""
    records = load_merged()
    texts = {rec["post_id"]: index_text(rec) for rec in records}
    empty = [pid for pid, t in texts.items() if not t.strip()]
    for pid in empty:
        texts.pop(pid)
    if empty:
        print(f"dense: skipping {len(empty)} empty-text posts: {empty}", file=sys.stderr)


    import sqlite3

    import sqlite_vec

    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS posts USING vec0("
        "post_id TEXT PRIMARY KEY, vec FLOAT[" + str(DIMS) + "])"
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

    client = _client()
    stored = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        pids = [pid for pid, _ in batch]
        vecs = _embed_batch(client, [t for _, t in batch])
        conn.executemany(
            "INSERT OR REPLACE INTO posts(post_id, vec) VALUES (?, ?)",
            [(pid, _vec_to_blob(v)) for pid, v in zip(pids, vecs)],
        )
        conn.commit()
        stored += len(pids)
        print(f"dense: embedded {stored}/{len(todo)} posts", file=sys.stderr)
        if i + BATCH_SIZE < len(todo):
            time.sleep(5)  # pace under the shared global per-minute embedding quota
    print(f"dense: stored {stored} new vectors in {DB_PATH}")
    return stored


def _connect():
    """Open the sqlite-vec database with the extension loaded."""
    import sqlite3

    import sqlite_vec

    if not DB_PATH.exists():
        raise DenseRetrievalError(
            f"vector store missing at {DB_PATH}; run `uv run python -m kb.dense --build` first"
        )
    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def retrieve_scored(question: str, top_k: int = 10) -> list[tuple[str, float]]:
    """Embed the question and return the top_k (post_id, cosine_similarity) pairs, ranked."""
    client = _client()
    conn = _connect()
    try:
        [qv] = _embed_batch(client, [question])
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


def retrieve(question: str, top_k: int = 10) -> list[str]:
    """Return the top_k ranked post_ids for a question via dense cosine similarity."""
    return [pid for pid, _score in retrieve_scored(question, top_k=top_k)]


def main() -> int:
    """CLI entry: --build (re)builds the vector store; --summary prints stats + a sample retrieve."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="embed new posts and store vectors")
    parser.add_argument("--summary", action="store_true", help="print n_vectors, model, sample retrieve")
    parser.add_argument("--overwrite", action="store_true", help="re-embed all posts even if cached")
    args = parser.parse_args()

    try:
        if args.build or args.overwrite:
            build(overwrite=args.overwrite)
        if not args.summary:
            return 0

        conn = _connect()
        n = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        conn.close()
        print(f"model={EMBED_MODEL}")
        print(f"n_vectors={n}")
        try:
            hits = retrieve("font pairing", top_k=5)
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
