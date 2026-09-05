"""Core contracts (plan §5/§6.1): Protocol stubs for the ingest seam.

LSP fix from the coupling audit: lexical/dense/hybrid retrievers all return
``RankedHits[]``; consumers depend on ORDER + IDENTITY only, never absolute
score (BM25/dense/RRF scores are incomparable scales).

Stub stage: signatures + docstrings only. The old ``kb/`` code is NOT wired
here; Build-3+ implement these against the Data-1 contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from kb_engine.core.records import CanonicalRecord


@dataclass(frozen=True)
class RankedHit:
    """One retrieval hit. ``score`` is strategy-relative and NOT comparable
    across strategies — consumers must rely on the ranked order only."""

    record_id: str
    score: float
    chunk_id: str | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    """Yields raw items for one declared source (the sole OCP extension
    point for novel formats — plan §5). Implementations do IO; core never
    does."""

    def load(self) -> Iterable[Mapping[str, Any]]:
        """Yield raw source items in the adapter's native shape."""
        ...


@runtime_checkable
class Mapper(Protocol):
    """Declared mapping -> canonical record; stamps provenance +
    content_hash per the corpus contract. Pure transformation."""

    def map(self, raw: Mapping[str, Any]) -> CanonicalRecord:
        """Map one raw item to a :class:`CanonicalRecord`."""
        ...


@runtime_checkable
class DedupePolicy(Protocol):
    """Declared key + policy + deterministic order (keep_first | newest |
    highest_confidence | version_append)."""

    def apply(self, records: Iterable[CanonicalRecord]) -> list[CanonicalRecord]:
        """Return deduplicated records in deterministic order."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """One retrieval strategy (lexical/dense/hybrid — swappable, §5 LSP).

    Contract: return hits ranked best-first; callers depend on order +
    identity, never on the absolute score value.
    """

    def search(self, query: str, top_k: int) -> list[RankedHit]:
        """Return up to ``top_k`` hits, best-first."""
        ...
