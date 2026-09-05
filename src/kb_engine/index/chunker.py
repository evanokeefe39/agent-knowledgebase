"""Chunker — ONE contract for building searchable chunks (plan §6.2, Build-4).

Replaces the three divergent legacy index-text builders (``kb/dense.py
index_text``, ``kb/bm25.py _post_text``, ``kb/query.py _searchable_text``).

A chunk is a provenance-carrying retrieval unit over the corpus-DECLARED
``role=search`` fields (or the explicit ``index.chunker.fields`` override).
Engine code references no field name — the field list comes from the corpus
contract.

Modes (``corpora/<name>.yaml`` → ``index.chunker.mode``):
  * ``by_field`` — one chunk per search field (list fields joined with
    newlines, mirroring legacy behavior);
  * ``by_size``  — search text concatenated per field, then split into
    ``max_chars`` windows with ``overlap`` characters of carry-over.

Every chunk carries ``(record_id, field, chunk_idx)`` identity plus the full
record :class:`~kb_engine.core.Provenance` envelope (never silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from kb_engine.config import CorpusConfig, FieldSpec
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord

DEFAULT_MAX_CHARS = 2000
DEFAULT_OVERLAP = 200


@dataclass(frozen=True)
class Chunk:
    """One retrieval unit produced by the Chunker.

    ``record_id`` + ``field`` + ``chunk_idx`` are the chunk provenance
    triple; ``provenance`` carries the record's full source envelope and
    ``media_ref`` mirrors ``provenance.media_ref`` (the pointer into the raw
    byte cache) for convenience. ``metadata`` holds declared filter/facet
    field values so backends can apply ``filters`` without re-reading the
    corpus.
    """

    record_id: str
    chunk_field: str
    chunk_idx: int
    text: str
    provenance: Provenance
    media_ref: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        """Stable chunk identity: ``{record_id}::{field}::{chunk_idx}``."""
        return f"{self.record_id}::{self.chunk_field}::{self.chunk_idx}"


def _as_chunks(value: Any) -> list[str]:
    """Flatten one field value to text parts: scalars → [str], lists → items."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(_as_chunks(item))
        return parts
    return [str(value)]


class Chunker:
    """Record → Chunk[] over the declared searchable fields.

    Construct directly with an explicit ``fields`` list, or from a corpus
    contract via :meth:`from_corpus` (which defaults to every field declared
    ``role=search``).
    """

    def __init__(
        self,
        fields: Sequence[str],
        *,
        mode: str = "by_field",
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap: int = DEFAULT_OVERLAP,
        metadata_fields: Sequence[str] = (),
    ) -> None:
        if mode not in ("by_field", "by_size"):
            raise ValueError(
                f"unknown chunker mode {mode!r}; expected 'by_field' or 'by_size'"
            )
        if not fields:
            raise ValueError("chunker requires at least one searchable field")
        if overlap >= max_chars:
            raise ValueError("overlap must be smaller than max_chars")
        self.fields = tuple(fields)
        self.mode = mode
        self.max_chars = max_chars
        self.overlap = overlap
        self.metadata_fields = tuple(metadata_fields)

    @classmethod
    def from_corpus(cls, corpus: CorpusConfig) -> Chunker:
        """Build a Chunker from the corpus contract's ``index.chunker`` block.

        Default fields = every schema field declared ``role=search``; an
        explicit ``fields`` list in the declaration overrides. Declared
        filter/facet fields become chunk ``metadata`` for backend filtering.
        """
        raw = corpus.raw.get("index", {}).get("chunker", {})
        mode = raw.get("mode", "by_field")
        declared = raw.get("fields")
        if declared:
            fields = list(declared)
        else:
            fields = [
                name
                for name, spec in corpus.fields.items()
                if spec.roles and "search" in spec.roles
            ]
        metadata_fields = [
            name
            for name, spec in corpus.fields.items()
            if spec.roles and any(r in spec.roles for r in ("filter", "facet"))
        ]
        return cls(
            fields,
            mode=mode,
            max_chars=int(raw.get("max_chars", DEFAULT_MAX_CHARS)),
            overlap=int(raw.get("overlap", DEFAULT_OVERLAP)),
            metadata_fields=metadata_fields,
        )

    # ---- Chunking ----------------------------------------------------------

    def chunk(self, record: CanonicalRecord) -> list[Chunk]:
        """Split one canonical record into provenance-carrying chunks."""
        metadata = {
            name: record.fields.get(name)
            for name in self.metadata_fields
            if name in record.fields
        }
        chunks: list[Chunk] = []
        for field_name in self.fields:
            value = record.fields.get(field_name)
            parts = _as_chunks(value)
            if not parts:
                continue  # absent/empty search field yields no chunk
            text = "\n".join(parts)
            if self.mode == "by_field":
                chunks.append(self._mk(record, field_name, len(chunks), text, metadata))
            else:
                chunks.extend(
                    self._mk_by_size(record, field_name, len(chunks), text, metadata)
                )
        return chunks

    def chunk_all(
        self, records: Iterable[CanonicalRecord]
    ) -> list[Chunk]:
        """Chunk a sequence of records in order (deterministic)."""
        out: list[Chunk] = []
        for record in records:
            out.extend(self.chunk(record))
        return out

    # ---- helpers -----------------------------------------------------------

    def _mk(
        self,
        record: CanonicalRecord,
        field_name: str,
        idx: int,
        text: str,
        metadata: Mapping[str, Any],
    ) -> Chunk:
        return Chunk(
            record_id=record.id,
            chunk_field=field_name,
            chunk_idx=idx,
            text=text,
            provenance=record.provenance,
            media_ref=record.provenance.media_ref,
            metadata=metadata,
        )

    def _mk_by_size(
        self,
        record: CanonicalRecord,
        field_name: str,
        start_idx: int,
        text: str,
        metadata: Mapping[str, Any],
    ) -> list[Chunk]:
        windows: list[str] = []
        step = self.max_chars - self.overlap
        for start in range(0, len(text), step):
            windows.append(text[start : start + self.max_chars])
            if start + self.max_chars >= len(text):
                break
        return [
            self._mk(record, field_name, start_idx + i, w, metadata)
            for i, w in enumerate(windows)
        ]
