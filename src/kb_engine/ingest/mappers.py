"""Mapper (plan §6.1): declared mapping -> :class:`CanonicalRecord`.

Given a corpus :class:`~kb_engine.config.SourceSpec` (``mapping`` entries:
target field -> ``{from, transform, ...}``), the declared schema fields
(:class:`~kb_engine.config.FieldSpec` type/roles), the provenance spec, and
``refresh_hash_fields``, produce one ``CanonicalRecord`` per raw item.

Resolution rules:
  * ``from`` is a dotted path into the raw item (``metadata.id``); integer
    segments index lists. A bare path that misses in the raw item falls back
    to already-mapped fields (a mapping target may reference an earlier
    target, e.g. ``url`` from ``shortcode``).
  * Absent optional path -> field is ``None`` + a coverage stat — never a
    failure. Transform only runs on present values.
  * The mapped value is validated against the declared field TYPE; a
    mismatch raises :class:`MappingError` (pipeline surfaces it per the
    declared ``missing.envelope_failure`` policy).

Envelope enforcement (plan §3/§6.1): a raw item missing ``id`` (the declared
``id_field``), with no mapped content at all, or with NO non-empty
``search``-role text field AND no ``media_ref`` is an ENVELOPE FAILURE ->
:class:`EnvelopeFailure` (typed gap; surfaced, never silently dropped).

Adapter-provided fields: a raw key that names a declared schema field but
has no mapping entry (e.g. ``extraction_status``) is copied verbatim by the
adapter and injected by the mapper after the declared mapping — type
validated like any mapped field. Bespoke derivation lives in the adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from kb_engine.config import CorpusConfig, SourceSpec
from kb_engine.core.records import CanonicalRecord
from kb_engine.core.provenance import Provenance
from kb_engine.ingest.transforms import TransformError, apply_transform

__all__ = ["MappingError", "EnvelopeFailure", "RecordMapper", "content_hash"]


class MappingError(ValueError):
    """A mapped value failed type validation against the declared schema."""


class EnvelopeFailure(Exception):
    """The raw item cannot satisfy the thin envelope (plan §6.1).

    Never a silent drop: the pipeline converts this to a coverage gap or
    aborts, per the declared ``missing.envelope_failure`` policy.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"envelope failure [{reason}]: {detail}")


def _resolve_path(item: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """Resolve a dotted path; integer segments index lists."""
    node: Any = item
    for part in path.split("."):
        if isinstance(node, Mapping):
            if part not in node:
                return False, None
            node = node[part]
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return False, None
        else:
            return False, None
    return True, node


def _is_search_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_is_search_text(v) for v in value)
    return value is not None


def _check_type(value: Any, ftype: str, field: str, source: str) -> None:
    """Validate a mapped value against the declared type (fail, never coerce)."""
    if value is None:
        return
    where = f"source '{source}', field '{field}'"

    def err(got: str) -> MappingError:
        return MappingError(f"{where}: expected {ftype}, got {got}")

    if ftype in ("text", "string", "url", "datetime", "date"):
        if not isinstance(value, str):
            raise err(type(value).__name__)
    elif ftype in ("list[text]", "list[string]"):
        if not isinstance(value, list):
            raise err(type(value).__name__)
        for element in value:
            if not isinstance(element, str):
                raise err(f"list element {type(element).__name__}")
    elif ftype == "list[object]":
        if not isinstance(value, list):
            raise err(type(value).__name__)
    elif ftype == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise err(type(value).__name__)
    elif ftype == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise err(type(value).__name__)
    elif ftype == "bool":
        if not isinstance(value, bool):
            raise err(type(value).__name__)
    elif ftype == "object":
        pass  # passthrough: stored verbatim, never validated
    else:
        raise MappingError(f"{where}: unknown declared type {ftype!r}")


def content_hash(fields: Mapping[str, Any], refresh_fields: tuple[str, ...]) -> str:
    """Deterministic content hash over ``refresh_fields`` (empty => all
    non-None mapped fields). Canonical JSON: sorted keys, compact."""
    if refresh_fields:
        payload = {name: fields[name] for name in sorted(refresh_fields)}
    else:
        payload = {k: v for k, v in fields.items() if v is not None}
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordMapper:
    """Implements the ``Mapper`` protocol for one declared source."""

    corpus: CorpusConfig
    source: SourceSpec

    def map(self, raw: Mapping[str, Any]) -> CanonicalRecord:
        fields: dict[str, Any] = {}
        mapping = self.source.mapping

        # Declared mapping, in declaration order (later entries may reference
        # earlier targets, e.g. `url` built from `shortcode`).
        for target, entry in mapping.items():
            present, value = _resolve_path(raw, entry["from"])
            if not present:
                # Fall back to an already-mapped field with the same path
                # name (e.g. `url` built over the mapped `shortcode`).
                value = fields.get(entry["from"])
                present = value is not None
            if not present:
                fields[target] = None  # optional absence -> None + coverage stat
                continue
            transform = entry.get("transform", "identity")
            try:
                value = apply_transform(transform, value, entry)
            except TransformError as exc:
                raise MappingError(
                    f"source '{self.source.name}', field '{target}': {exc}"
                ) from None
            fields[target] = value

        # Adapter-provided fields: declared schema fields with no mapping
        # entry that the adapter stamped into the raw item.
        for name, spec in self.corpus.fields.items():
            if name in mapping or name in fields:
                continue
            present, value = _resolve_path(raw, name)
            if present:
                fields[name] = value
                _check_type(value, spec.type, name, self.source.name)

        for name, value in fields.items():
            spec = self.corpus.field(name)
            if spec is not None:
                _check_type(value, spec.type, name, self.source.name)

        # ---- id ----
        id_field = self.corpus.id_field
        record_id = fields.get(id_field)
        if not record_id or (isinstance(record_id, str) and not record_id.strip()):
            raise EnvelopeFailure(
                "missing_id",
                f"source '{self.source.name}': id field '{id_field}' is missing/empty",
            )

        # ---- provenance ----
        prov_spec = self.source.provenance
        _, media_ref = _resolve_path(raw, prov_spec.media_ref)
        _, timestamp = _resolve_path(raw, prov_spec.timestamp_field)
        extractor = None
        if prov_spec.extractor_field:
            _, extractor = _resolve_path(raw, prov_spec.extractor_field)
        confidence = None
        if prov_spec.confidence_field:
            _, confidence = _resolve_path(raw, prov_spec.confidence_field)
        provenance = Provenance(
            source=prov_spec.source,
            media_ref=str(media_ref) if media_ref not in (None, "") else "",
            timestamp=str(timestamp) if timestamp not in (None, "") else None,
            extractor=str(extractor) if extractor not in (None, "") else None,
            confidence=float(confidence) if confidence is not None else None,
        )

        # ---- envelope: >=1 retrievable text unit (search text OR media) ----
        has_search_text = any(
            _is_search_text(value)
            for name, value in fields.items()
            if (spec := self.corpus.field(name)) is not None
            and "search" in spec.roles
        )
        if not has_search_text and not provenance.media_ref:
            raise EnvelopeFailure(
                "no_retrievable_text",
                f"source '{self.source.name}': no non-empty search-role field "
                f"and no media_ref (id candidate: {record_id!r})",
            )
        if all(value is None for value in fields.values()):
            raise EnvelopeFailure(
                "no_content",
                f"source '{self.source.name}': no mapped content",
            )

        return CanonicalRecord(
            id=str(record_id),
            content_hash=content_hash(fields, self.corpus.refresh_hash_fields),
            provenance=provenance,
            fields=fields,
        )
