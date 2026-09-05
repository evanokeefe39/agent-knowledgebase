"""Typed record envelope (plan §3/§6.1): the thin universal shape every
input must satisfy. No corpus-specific fields — rich attributes live in the
per-corpus declared schema (``fields`` bag)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kb_engine.core.provenance import Provenance


@dataclass(frozen=True)
class CanonicalRecord:
    """Canonical corpus record: the ingest output and index/serve input.

    Envelope contract (§6.1 — MUST hold for every record):
      * ``id`` — stable record identity within the corpus;
      * ``content_hash`` — over hash-able mapped fields; ingest is
        deterministic + idempotent by it (rebuilds never re-bill);
      * ``provenance`` — source / media_ref / timestamp (never silently
        dropped);
      * ``fields`` — declared per-corpus schema fields (never referenced
        by engine code by name).
    """

    id: str
    content_hash: str
    provenance: Provenance
    fields: dict[str, Any] = field(default_factory=dict)
