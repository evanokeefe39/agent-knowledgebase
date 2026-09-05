"""Index backends (plan §6.2): pluggable stores behind one protocol.

* :class:`BM25FTS5Backend` — lexical BM25 over SQLite FTS5 (stdlib only,
  fully functional, file- or memory-backed).
* :class:`SQLiteVecBackend` — vector store over sqlite-vec (installed via
  ``uv add sqlite-vec``; zero-shot KNN cosine distance).
* :class:`InMemoryVectorBackend` — cosine brute force, hermetic fallback
  used by tests (no extension loading).

Indexes are DERIVED + always rebuildable from the canonical corpus (§13):
backends accept :class:`~kb_engine.index.chunker.Chunk` batches and are
trivially clearable/rebuilt.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from kb_engine.index.chunker import Chunk

_FTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    field       TEXT NOT NULL,
    text        TEXT NOT NULL,
    media_ref   TEXT,
    metadata    TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    text,
    record_id UNINDEXED,
    field UNINDEXED,
    chunk_id UNINDEXED,
    media_ref UNINDEXED,
    metadata UNINDEXED
);
"""


@dataclass(frozen=True)
class Hit:
    """One backend hit: identity + strategy-relative score.

    Consumers depend on ranked order + identity only — absolute scores are
    NOT comparable across backends (BM25 is unbounded, cosine is [-1, 1],
    RRF is a rank sum)."""
    record_id: str
    score: float
    chunk_id: str


@runtime_checkable
class IndexBackend(Protocol):
    """Store + retrieve protocol shared by lexical and vector backends."""

    def add(self, chunks: Iterable[Chunk]) -> int:
        """Index chunks; returns the number stored. Idempotent per chunk_id
        (re-adding an unchanged chunk replaces it, never duplicates)."""
        ...

    def retrieve(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:
        """Return up to ``top_k`` hits best-first. ``filters`` restricts on
        chunk metadata (declared filter/facet fields): each entry matches by
        equality; list-valued metadata matches by containment."""
        ...

    def clear(self) -> None:
        """Drop all indexed chunks (indexes are derived, rebuildable)."""
        ...


@runtime_checkable
class VectorBackend(IndexBackend, Protocol):
    """Index backend that also accepts precomputed vectors (dense seam).

    Dense indexing pairs each chunk with one embedding vector produced by
    the injected :class:`~kb_engine.index.embedder.Embedder` — the backend
    itself never calls an API (DIP)."""

    def add_vectors(
        self,
        vectors: Iterable[tuple[Chunk, list[float]]],
    ) -> int:
        """Index (chunk, embedding) pairs; returns the number stored."""
        ...


# ---- BM25 over SQLite FTS5 ---------------------------------------------------



def _metadata_matches(metadata_json: str, filters: Mapping[str, Any]) -> bool:
    metadata = json.loads(metadata_json) if metadata_json else {}
    for key, expected in filters.items():
        actual = metadata.get(key)
        if isinstance(actual, list):
            wanted = expected if isinstance(expected, list) else [expected]
            if not any(w in actual for w in wanted):
                return False
        elif actual != expected:
            return False
    return True


class BM25FTS5Backend:
    """Lexical backend over SQLite FTS5 (stdlib; BM25 ranking built in).

    ``db_path=":memory:"`` (default) keeps the index in-process; a file path
    persists it. Scores are FTS5 ``bm25()`` values negated so that — like
    every backend — higher is better.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_FTS_SCHEMA)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_record ON chunks(record_id)")

    def add(self, chunks: Iterable[Chunk]) -> int:
        n = 0
        with self.conn:
            for chunk in chunks:
                meta = json.dumps(dict(chunk.metadata), sort_keys=True)
                # FTS5 virtual tables have no INSERT OR REPLACE semantics:
                # delete the chunk first so rebuilds stay idempotent.
                self.conn.execute(
                    "DELETE FROM fts_chunks WHERE chunk_id = ?", (chunk.chunk_id,)
                )
                self.conn.execute(
                    "DELETE FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
                )
                self.conn.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                    (chunk.chunk_id, chunk.record_id, chunk.chunk_field, chunk.text, chunk.media_ref, meta),
                )
                self.conn.execute(
                    "INSERT INTO fts_chunks(record_id, field, chunk_id, media_ref, metadata, text) VALUES (?,?,?,?,?,?)",
                    (chunk.record_id, chunk.chunk_field, chunk.chunk_id, chunk.media_ref, meta, chunk.text),
                )
                n += 1
        return n

    def retrieve(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:
        tokens = query.split()
        if not tokens or top_k <= 0:
            return []
        fetch = top_k * 5 if filters else top_k  # over-fetch so filters can trim

        def _query(match_expr: str) -> list[tuple[str, str, float, str]]:
            return self.conn.execute(
                """
                SELECT record_id, chunk_id, bm25(fts_chunks) AS score, metadata
                FROM fts_chunks WHERE fts_chunks MATCH ? ORDER BY score LIMIT ?
                """,
                (match_expr, fetch),
            ).fetchall()

        quoted = ['"' + t.replace('"', '""') + '"' for t in tokens]
        # Precision first: all tokens (AND). Recall fallback: any token (OR).
        rows = _query(" AND ".join(quoted))
        if not rows:
            rows = _query(" OR ".join(quoted))

        hits: list[Hit] = []
        for record_id, chunk_id, score, meta in rows:
            if filters and not _metadata_matches(meta, filters):
                continue
            hits.append(Hit(record_id=record_id, score=-score, chunk_id=chunk_id))
            if len(hits) >= top_k:
                break
        return hits

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM fts_chunks")

    def close(self) -> None:
        self.conn.close()


# ---- Vector backends ---------------------------------------------------------


def _vec_to_blob(vec: list[float]) -> bytes:
    """Pack a float vector as little-endian float32 bytes (sqlite-vec)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(x * x for x in b) ** 0.5
    if da == 0.0 or db == 0.0:
        return 0.0
    return num / (da * db)


class InMemoryVectorBackend:
    """Hermetic brute-force cosine vector store (tests / small corpora).

    Fully functional against the :class:`VectorBackend` protocol; no
    extension loading, no IO beyond process memory.
    """

    def __init__(self) -> None:
        self._vectors: dict[str, tuple[Chunk, list[float]]] = {}

    def add(self, chunks: Iterable[Chunk]) -> int:  # pragma: no cover - lexical only
        raise NotImplementedError(
            "InMemoryVectorBackend is a vector store: use add_vectors()"
        )

    def add_vectors(
        self, vectors: Iterable[tuple[Chunk, list[float]]]
    ) -> int:
        n = 0
        for chunk, vec in vectors:
            self._vectors[chunk.chunk_id] = (chunk, list(vec))
            n += 1
        return n

    def retrieve(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:  # pragma: no cover - vector only
        raise NotImplementedError(
            "InMemoryVectorBackend is a vector store: use retrieve_vectors()"
        )

    def retrieve_vectors(
        self, query_vec: list[float], top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:
        scored = [
            (chunk, _cosine(query_vec, vec))
            for chunk, vec in self._vectors.values()
            if not filters or _metadata_matches(json.dumps(dict(chunk.metadata), sort_keys=True), filters)
        ]
        scored.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return [
            Hit(record_id=c.record_id, score=s, chunk_id=c.chunk_id)
            for c, s in scored[:top_k]
        ]

    def clear(self) -> None:
        self._vectors.clear()


class SQLiteVecBackend:
    """Vector store over sqlite-vec (``uv add sqlite-vec``; KNN cosine).

    Stores chunk text/metadata in a plain table and embeddings in a
    ``vec0`` virtual table keyed by chunk_id. Scores are
    ``1 - cosine_distance`` (higher is better)."""

    def __init__(self, db_path: str | Path = ":memory:", dims: int = 768) -> None:
        import sqlite_vec  # installed via `uv add sqlite-vec`

        self.dims = dims
        self.conn = sqlite3.connect(str(db_path))
        # stdlib sqlite3 blocks loadable extensions unless explicitly enabled
        if hasattr(self.conn, "enable_load_extension"):
            self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        if hasattr(self.conn, "enable_load_extension"):
            self.conn.enable_load_extension(False)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id  TEXT PRIMARY KEY,
                record_id TEXT NOT NULL,
                field     TEXT NOT NULL,
                text      TEXT NOT NULL,
                media_ref TEXT,
                metadata  TEXT
            );
            """
        )
        self.conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                chunk_id TEXT PRIMARY KEY,
                embedding float[{dims}]
            );
            """
        )

    def add(self, chunks: Iterable[Chunk]) -> int:  # pragma: no cover
        raise NotImplementedError("SQLiteVecBackend is a vector store: use add_vectors()")

    def add_vectors(
        self, vectors: Iterable[tuple[Chunk, list[float]]]
    ) -> int:
        n = 0
        with self.conn:
            for chunk, vec in vectors:
                if len(vec) != self.dims:
                    raise ValueError(
                        f"embedding dims {len(vec)} != declared dims {self.dims}"
                    )
                meta = json.dumps(dict(chunk.metadata), sort_keys=True)
                self.conn.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?)",
                    (chunk.chunk_id, chunk.record_id, chunk.chunk_field, chunk.text, chunk.media_ref, meta),
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO vec_chunks(chunk_id, embedding) VALUES (?,?)",
                    (chunk.chunk_id, _vec_to_blob(vec)),
                )
                n += 1
        return n

    def retrieve(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:  # pragma: no cover
        raise NotImplementedError(
            "SQLiteVecBackend is a vector store: use retrieve_vectors()"
        )

    def retrieve_vectors(
        self, query_vec: list[float], top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[Hit]:
        if top_k <= 0 or len(query_vec) != self.dims:
            return []
        fetch = top_k * 5 if filters else top_k
        rows = self.conn.execute(
            """
            SELECT c.record_id, c.chunk_id, v.distance, c.metadata
            FROM vec_chunks v JOIN chunks c ON c.chunk_id = v.chunk_id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_vec_to_blob(query_vec), fetch),
        ).fetchall()
        hits: list[Hit] = []
        for record_id, chunk_id, distance, meta in rows:
            if filters and not _metadata_matches(meta, filters):
                continue
            hits.append(Hit(record_id=record_id, score=1.0 - distance, chunk_id=chunk_id))
            if len(hits) >= top_k:
                break
        return hits

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM chunks")
            self.conn.execute("DELETE FROM vec_chunks")

    def close(self) -> None:
        self.conn.close()
