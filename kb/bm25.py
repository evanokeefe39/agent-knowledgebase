"""BM25 lexical retrieval over the unified knowledge-base corpus via SQLite FTS5.

Storage decision (ORCHESTRATOR-APPROVED): file-backed hybrid. BM25 runs on
SQLite FTS5 (real BM25 scoring, ``sqlite3`` is built into the stdlib); dense
vectors live in a separate sqlite-vec file (see kb/dense.py). pgvector remains
the documented Postgres production path, but no Postgres instance exists on
this machine, so nothing is provisioned here.

Contract (shared with kb/dense.py and kb/hybrid.py):
    retrieve(question, top_k=10) -> list[post_id]           # ranked, best first
    retrieve_scored(question, top_k=10) -> list[(post_id, score)]

FTS5's bm25() returns lower-is-better (negated matches), so scores here are
negated to make higher=better, consistent with the dense scorer.

Index text per post = concatenation of: summary, workflow_steps, tips,
concepts (terms + explanations), transcript, tools_apps, tags, and resources
(names + purpose). Post ids are used verbatim from the record's ``post_id``
field (may be "{domain}:{post_id}" for cross-domain collisions).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_CORPUS = "data/kb/kb-posts-all.json"
DEFAULT_DB = "data/kb/bm25.db"
_SCHEMA = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS posts USING fts5("
    "post_id UNINDEXED, text, tokenize='porter unicode61')"
)



def _post_text(record: dict) -> str:
    """Build the index text for one corpus record.

    Concatenates summary + workflow_steps + tips + concepts(terms+explanations)
    + transcript + tools_apps + tags + resources(names+purpose).
    """
    parts: list[str] = [record.get("summary") or "", record.get("transcript") or ""]
    parts.extend(record.get("workflow_steps") or [])
    parts.extend(record.get("tips") or [])
    for c in record.get("concepts") or []:
        if isinstance(c, dict):
            parts.append(str(c.get("term") or ""))
            parts.append(str(c.get("explanation") or ""))
        else:
            parts.append(str(c))
    parts.extend(str(t) for t in record.get("tools_apps") or [])
    parts.extend(str(t) for t in record.get("tags") or [])
    for r in record.get("resources") or []:
        if isinstance(r, dict):
            parts.append(str(r.get("name") or ""))
            parts.append(str(r.get("purpose") or ""))
        else:
            parts.append(str(r))
    return " ".join(p for p in parts if p)


def build_index(corpus: str | Path = DEFAULT_CORPUS, db_path: str | Path = DEFAULT_DB) -> int:
    """Build the FTS5 BM25 index from the unified corpus JSON.

    Creates (or rebuilds, idempotently via DROP+CREATE) the SQLite database at
    ``db_path`` with an FTS5 ``posts`` virtual table holding one row per post
    (docid, post_id, text). Returns the number of documents indexed.
    """
    corpus = Path(corpus)
    db_path = Path(db_path)
    records = json.loads(corpus.read_text(encoding="utf-8"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS posts")
        conn.execute(_SCHEMA)
        rows = [(r["post_id"], _post_text(r)) for r in records]
        conn.executemany("INSERT INTO posts(post_id, text) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _open_db(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Open the BM25 index database, raising a clear error if not built yet."""
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"BM25 index {db_path} not found; run build_index() or `python -m kb.bm25 --build` first"
        )
    return sqlite3.connect(db_path)


def _match_query(question: str) -> str:
    """Escape a raw question into a safe FTS5 MATCH expression.

    Strips FTS5 syntax characters (quotes, dashes, parens, operators) so MATCH
    cannot error, then joins remaining tokens with AND.
    """
    for ch in '"\'()^:*{}[]':
        question = question.replace(ch, " ")
    tokens = [t for t in question.replace("-", " ").split() if t]
    if not tokens:
        return '""'  # matches nothing; caller handles empty results
    return " AND ".join(f'"{t}"' for t in tokens)


def retrieve_scored(
    question: str, top_k: int = 10, db_path: str | Path = DEFAULT_DB
) -> list[tuple[str, float]]:
    """Retrieve the top_k posts for a question as (post_id, score) pairs.

    Queries the FTS5 table with the question tokens (AND across tokens; falls
    back to OR when AND yields no hits), ranked by bm25(). FTS5's bm25() is
    lower-is-better, so scores are negated: higher = better. Returns [] when
    nothing matches.
    """
    conn = _open_db(db_path)
    try:
        cur = conn.cursor()
        results: list[tuple[str, float]] = []
        for match in (_match_query(question), _match_query(question).replace(" AND ", " OR ")):
            cur.execute(
                "SELECT post_id, -bm25(posts) FROM posts WHERE posts MATCH ? "
                "ORDER BY bm25(posts) LIMIT ?",
                (match, top_k),
            )
            results = [(pid, float(s)) for pid, s in cur.fetchall()]
            if results:
                break
        return results
    finally:
        conn.close()


def retrieve(
    question: str, top_k: int = 10, db_path: str | Path = DEFAULT_DB
) -> list[str]:
    """Retrieve the top_k ranked post_ids for a question (best first)."""
    return [pid for pid, _ in retrieve_scored(question, top_k, db_path)]


def _main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``python -m kb.bm25 [--corpus PATH] [--db PATH] --summary``."""
    ap = argparse.ArgumentParser(description="BM25 FTS5 index over the KB corpus")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--build", action="store_true", help="(re)build the index")
    ap.add_argument("--summary", action="store_true", help="build + print index stats and sample queries")
    ap.add_argument("--query", help="run one query and print scored results")
    args = ap.parse_args(argv)

    if args.summary or args.build:
        n = build_index(args.corpus, args.db)
        print(f"built index: {args.db} (n_docs={n})")
    if args.summary:
        shortcodes = {
            r["post_id"]: r.get("shortcode") or r["post_id"]
            for r in json.loads(Path(args.corpus).read_text(encoding="utf-8"))
        }
        sample_queries = ["font pairing", "AI image editing", "Instagram growth"]
        for q in sample_queries:
            print(f"\nquery: {q!r}")
            for pid, score in retrieve_scored(q, top_k=5, db_path=args.db):
                print(f"  {score:8.4f}  {pid}  (shortcode: {shortcodes.get(pid, '?')})")
    if args.query:
        print(f"query: {args.query!r}")
        for pid, score in retrieve_scored(args.query, top_k=10, db_path=args.db):
            print(f"  {score:8.4f}  {pid}")
    if not (args.summary or args.build or args.query):
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
