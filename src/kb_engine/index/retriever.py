"""Retrievers (plan §6.2/§5-LSP): one ``Retriever → RankedHit[]`` contract.

* :class:`BM25Retriever`  — lexical via the FTS5 backend.
* :class:`DenseRetriever` — vector similarity via an injected vector
  backend + :class:`Embedder` (DIP: the retriever never calls an API).
* :class:`HybridRetriever` — Reciprocal Rank Fusion over the two, ``k``
  configurable; falls back to BM25-only when the dense channel is
  unavailable (no embedder/backend, or a dense failure).

LSP fix (§5): bm25/dense/hybrid all return ``RankedHit[]`` — record-level
(best chunk per record preserved as ``chunk_id``), best-first. Consumers
depend on ORDER + IDENTITY only, never absolute score (BM25 is unbounded,
cosine is [-1, 1], RRF is a rank sum).

``rerank`` ships as a DISABLED seam (:class:`RerankConfig`, ``enabled: False``
+ ``{strategy, top_n}`` shape) — not a live feature this pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from kb_engine.core.contracts import RankedHit
from kb_engine.index.backends import BM25FTS5Backend, VectorBackend
from kb_engine.index.embedder import Embedder

DEFAULT_RRF_K = 60  # legacy kb/hybrid.py RRF_K


# ---- RRF ---------------------------------------------------------------------


def reciprocal_rank_fusion(
    *ranked_lists: list[RankedHit], k: int = DEFAULT_RRF_K
) -> list[RankedHit]:
    """Standard RRF: ``score = sum 1/(k + rank)`` over each ranked list
    (rank is 1-based; ``k`` smooths the head — legacy ``RRF_K = 60``).

    A record may occupy several ranks in one list (chunk-level hits); only
    its BEST (first) rank in each list contributes — RRF fuses records.

    Ties break deterministically on record_id; the fused score is a rank
    sum, comparable to nothing — order is the contract."""
    scores: dict[str, float] = {}
    chunk_by_record: dict[str, str | None] = {}
    for hits in ranked_lists:
        seen: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.record_id in seen:
                continue
            seen.add(hit.record_id)
            scores[hit.record_id] = scores.get(hit.record_id, 0.0) + 1.0 / (k + rank)
            chunk_by_record.setdefault(hit.record_id, hit.chunk_id)
    ordered = sorted(scores, key=lambda r: (-scores[r], r))
    return [
        RankedHit(record_id=r, score=scores[r], chunk_id=chunk_by_record.get(r))
        for r in ordered
    ]


def _best_per_record(hits: list[RankedHit]) -> list[RankedHit]:
    """Collapse chunk-level hits to record level: keep each record's best
    (first) hit; the chunk_id of that best chunk is preserved."""
    seen: set[str] = set()
    out: list[RankedHit] = []
    for hit in hits:
        if hit.record_id not in seen:
            seen.add(hit.record_id)
            out.append(hit)
    return out


# ---- Retrievers --------------------------------------------------------------


class BM25Retriever:
    """Lexical retrieval over a :class:`BM25FTS5Backend`."""

    def __init__(self, backend: BM25FTS5Backend) -> None:
        self.backend = backend

    def search(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[RankedHit]:
        """Return up to ``top_k`` record-level hits, best-first."""
        return _best_per_record(
            [
                RankedHit(record_id=h.record_id, score=h.score, chunk_id=h.chunk_id)
                for h in self.backend.retrieve(query, top_k, filters)
            ]
        )


class DenseRetriever:
    """Dense retrieval: embed the query, KNN over the vector backend."""

    def __init__(self, backend: VectorBackend, embedder: Embedder) -> None:
        self.backend = backend
        self.embedder = embedder

    def search(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[RankedHit]:
        qvec = self.embedder.embed_query(query)
        return _best_per_record(
            [
                RankedHit(record_id=h.record_id, score=h.score, chunk_id=h.chunk_id)
                for h in self.backend.retrieve_vectors(qvec, top_k, filters)
            ]
        )


class DenseUnavailable(Exception):
    """Raised by a dense probe: the dense channel cannot serve (no backend,
    no embedder, or an embedder/backend failure) — hybrid falls back."""


class HybridRetriever:
    """RRF fusion of BM25 + dense, ``k`` configurable (default 60).

    If no dense retriever is injected, or probing it raises, the hybrid
    degrades to BM25-only — retrieval never fails because one channel is
    down (legacy ``kb/hybrid.py`` fallback behavior, contract-ized)."""

    def __init__(
        self,
        bm25: BM25Retriever,
        dense: DenseRetriever | None = None,
        k: int = DEFAULT_RRF_K,
    ) -> None:
        self.bm25 = bm25
        self.dense = dense
        self.k = k

    def search(
        self, query: str, top_k: int, filters: Mapping[str, Any] | None = None
    ) -> list[RankedHit]:
        bm25_hits = self.bm25.search(query, top_k, filters)
        if self.dense is None:
            return bm25_hits
        try:
            dense_hits = self.dense.search(query, top_k, filters)
        except Exception:  # noqa: BLE001 - dense down ⇒ BM25 fallback, never fail
            return bm25_hits
        return reciprocal_rank_fusion(bm25_hits, dense_hits, k=self.k)[:top_k]


# ---- Rerank: DISABLED seam (plan §12 — ship disabled, gate on a trigger) -----


class RerankError(RuntimeError):
    """Raised when a disabled rerank seam is activated."""


@dataclass(frozen=True)
class RerankConfig:
    """Declared rerank seam (``corpora/<name>.yaml`` → ``index.retrieval
    .rerank``). Ships DISABLED: enabling later is a config change, not a
    contract change. Shape: ``{enabled, strategy, top_n}`` — no strategy is
    implemented this pass; ``apply_rerank`` refuses any live use."""

    enabled: bool = False
    strategy: str | None = None
    top_n: int | None = None


def apply_rerank(config: RerankConfig, hits: list[RankedHit]) -> list[RankedHit]:
    """Rerank seam stub. With the shipped default (``enabled: False``) hits
    pass through untouched. No strategy is registered; enabling without an
    implementation raises :class:`RerankError` — the seam is declared, not
    a live feature."""
    if not config.enabled:
        return hits
    raise RerankError(
        f"rerank is a disabled seam (strategy={config.strategy!r}): no reranker "
        "is implemented this pass; enabling requires a registered strategy"
    )
