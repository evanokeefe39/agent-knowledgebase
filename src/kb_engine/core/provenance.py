"""Provenance invariant (plan §3/§6.1, §13 "must not change"): every record
and every hit carries provenance — never silently dropped."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provenance:
    """Provenance envelope carried by every canonical record and chunk.

    * ``source`` — declared source name / provenance source id;
    * ``media_ref`` — adapter-provided pointer into the raw byte cache
      (where the payload physically lives; empty string when the input is
      natively textual);
    * ``timestamp`` — record timestamp, from the declared
      ``timestamp_field``;
    * ``extractor`` / ``confidence`` — optional enrichment provenance,
      recorded from data (e.g. extractor model + its confidence), so a
      downstream consumer can weigh the value.
    """

    source: str
    media_ref: str
    timestamp: str | None = None
    extractor: str | None = None
    confidence: float | None = None
