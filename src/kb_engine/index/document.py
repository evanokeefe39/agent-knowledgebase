"""Document-level dense embedding (M4 parity): ONE vector per record.

Legacy ``kb/dense.py`` (the M4 baseline) embedded a single document blob per
post — ``index_text`` concatenated summary + workflow_steps + tips +
concepts(term: explanation) + transcript + tools_apps + tags + resources
("name — purpose") with newlines — so dense similarity compared whole
records. The chunk-level dense path (``DenseRetriever`` over by_field
chunks, best-chunk-per-record) is a *different* granularity and does not
reproduce M4 ranking even with identical field content.

This module restores that granularity against the canonical contract:

* :func:`document_text` — one text blob per :class:`CanonicalRecord` over
  the corpus-DECLARED ``role=search`` fields in declared order, flattened
  and joined the legacy way (``\\n``-joined, stripped; legacy dict
  conventions for term/explanation and name/purpose entries).
* :class:`DocumentDenseRetriever` — embeds ONE vector per record, stores
  ``record_id -> vector`` in a :class:`VectorBackend` as a single
  ``__document__`` chunk, and retrieves by cosine over record vectors.
  Same LSP contract as every retriever: ``search`` → ``RankedHit[]``,
  best-first (identity is record-level by construction).

Embedding cost/idempotency is unchanged: the embed cache is keyed by
``(text_hash, model, dims)`` and ``document_text`` is deterministic per
record, so a re-run over unchanged content re-bills zero (wrap the inner
embedder in :class:`CachedEmbedder` at wiring time — the document text IS
the cache-key text).
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from kb_engine.config import CorpusConfig
from kb_engine.core.contracts import RankedHit
from kb_engine.core.records import CanonicalRecord
from kb_engine.index.backends import VectorBackend
from kb_engine.index.chunker import Chunk
from kb_engine.index.embedder import Embedder

DOCUMENT_CHUNK_FIELD = "__document__"


def _legacy_parts(value: Any) -> list[str]:
    """Flatten one field value to legacy ``index_text`` conventions.

    * str/scalar → itself (empty/None dropped);
    * list/tuple → flattened items in order;
    * dict with ``term`` → ``"{term}: {explanation}"`` (bare term if no
      explanation) — legacy concepts entries;
    * other dict with ``name``/``purpose`` → ``"{name} — {purpose}"`` —
      legacy resources entries;
    * any other dict → space-joined truthy values (legacy ``_flat``).
    """
    if value is None:
        return []
    if isinstance(value, dict):
        term = value.get("term")
        if term:
            expl = value.get("explanation")
            return [f"{term}: {expl}" if expl else str(term)]
        name = value.get("name") or ""
        purpose = value.get("purpose") or ""
        if name or purpose:
            return [f"{name} — {purpose}".strip(" —")]
        vals = [str(v) for v in value.values() if v]
        return [" ".join(vals)] if vals else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(_legacy_parts(item))
        return out
    text = str(value)
    return [text] if text else []


def search_fields(corpus: CorpusConfig) -> list[str]:
    """Declared ``role=search`` field names in declaration order."""
    return [
        name
        for name, spec in corpus.fields.items()
        if spec.roles and "search" in spec.roles
    ]


def filter_fields(corpus: CorpusConfig) -> list[str]:
    """Declared filter/facet field names (backend filter metadata)."""
    return [
        name
        for name, spec in corpus.fields.items()
        if spec.roles and any(r in spec.roles for r in ("filter", "facet"))
    ]


def document_text(record: CanonicalRecord, fields: Sequence[str]) -> str:
    """One indexable document blob per record, in the legacy join style.

    Concatenates the declared searchable fields in the given (declaration)
    order, flattening lists and applying legacy dict conventions, joined
    with ``\\n`` and stripped — mirroring ``kb/dense.py:index_text``.
    """
    parts: list[str] = []
    for field_name in fields:
        parts.extend(_legacy_parts(record.fields.get(field_name)))
    return "\n".join(p for p in parts if p).strip()


class DocumentDenseRetriever:
    """Dense retrieval at DOCUMENT granularity: one vector per record.

    ``build`` embeds ``document_text`` once per record and stores it in the
    vector backend as a single chunk per record (chunk_field
    ``__document__``). ``search`` embeds the query and ranks record vectors
    by cosine — same ``RankedHit[]`` LSP contract as ``DenseRetriever``.
    """

    def __init__(
        self,
        backend: VectorBackend,
        embedder: Embedder,
        fields: Sequence[str],
        metadata_fields: Sequence[str] = (),
    ) -> None:
        if not fields:
            raise ValueError("document dense retriever requires searchable fields")
        self.backend = backend
        self.embedder = embedder
        self.fields = tuple(fields)
        self.metadata_fields = tuple(metadata_fields)

    @classmethod
    def from_corpus(
        cls, corpus: CorpusConfig, backend: VectorBackend, embedder: Embedder
    ) -> "DocumentDenseRetriever":
        """Build from the corpus contract: declared search fields in order;
        declared filter/facet fields become backend filter metadata."""
        return cls(
            backend,
            embedder,
            search_fields(corpus),
            metadata_fields=filter_fields(corpus),
        )

    def build(self, records: Iterable[CanonicalRecord]) -> int:
        """Embed + index one vector per record; returns records stored.

        Idempotent per record id (the backend replaces on the same chunk
        id); the embed cache keys on the document text itself, so
        unchanged content re-bills zero.
        """
        records = list(records)
        texts = [document_text(r, self.fields) for r in records]
        vectors = self.embedder.embed_documents(texts)
        chunks = []
        for record, text, vec in zip(records, texts, vectors):
            metadata = {
                name: record.fields.get(name)
                for name in self.metadata_fields
                if name in record.fields
            }
            chunks.append(
                (
                    Chunk(
                        record_id=record.id,
                        chunk_field=DOCUMENT_CHUNK_FIELD,
                        chunk_idx=0,
                        text=text,
                        provenance=record.provenance,
                        metadata=metadata,
                    ),
                    vec,
                )
            )
        return self.backend.add_vectors(chunks)

    def search(
        self, query: str, top_k: int, filters: dict[str, Any] | None = None
    ) -> list[RankedHit]:
        """Rank record vectors by cosine against the query embedding."""
        qvec = self.embedder.embed_query(query)
        return [
            RankedHit(record_id=h.record_id, score=h.score, chunk_id=h.chunk_id)
            for h in self.backend.retrieve_vectors(qvec, top_k, filters)
        ]
