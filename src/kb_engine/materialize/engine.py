"""Generic group-by/count/avg materialization engine (plan §6.3).

``materialize(view, records) -> rows``: filters records with the view's
declared filters, groups (unnesting list facets per value), computes declared
metrics, and stamps every row with the contributing records' provenance, the
materialization timestamp (UTC ISO-8601) and the corpus ``schema_version``.

Row ordering is deterministic: rows are sorted by group key.

Empty-group convention: when a ``group_by`` field also carries an ``in``
filter, every declared filter value seeds a row even when no record matches
(a zero-count row with ``None`` means) — empty groups are emitted, never
silently absent. A record with an empty/missing list facet still contributes
one row keyed on ``None``.

Records may be ``CanonicalRecord[]`` (the ingest output) or plain field bags
carrying ``id`` + ``provenance`` — the engine reads declared fields, never
field names.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from kb_engine.core.records import CanonicalRecord
from kb_engine.materialize.views import Metric, View

_NUMERIC = (int, float)


class MaterializeError(Exception):
    """Base error for materialization failures (always explicit)."""


class FilterError(MaterializeError):
    """A filter referenced an unknown field or used an unknown op."""


class StaleViewError(MaterializeError):
    """A view was served past its declared freshness; refresh required."""


def _normalize_filter(field: str, spec: Any) -> tuple[str, Any]:
    """``{op, value}`` mapping, scalar shorthand (=eq) or list shorthand
    (=in) -> ``(op, value)``."""
    if isinstance(spec, Mapping):
        op = spec.get("op")
        if op not in ("eq", "in", "gte", "lte", "between"):
            raise FilterError(
                f"filter '{field}': op {op!r} unknown — ops: "
                "eq, in, gte, lte, between"
            )
        return op, spec.get("value")
    if isinstance(spec, list):
        return "in", spec
    return "eq", spec


def _get(record: Mapping[str, Any], field: str) -> Any:
    """Read a declared field: ``CanonicalRecord.fields`` bag or plain
    mapping key."""
    if isinstance(record, CanonicalRecord):
        return record.fields.get(field)
    return record.get(field)


def _matches(value: Any, op: str, fvalue: Any) -> bool:
    if value is None:
        return False
    if op == "eq":
        # Facet semantics: eq against a list-valued field matches membership.
        if isinstance(value, list):
            return fvalue in value
        return value == fvalue
    if op == "in":
        wanted = fvalue if isinstance(fvalue, list) else [fvalue]
        if isinstance(value, list):
            return bool(set(value) & set(wanted))
        return value in wanted
    if op in ("gte", "lte", "between"):
        if isinstance(value, list):
            return any(_matches(v, op, fvalue) for v in value)
        if not isinstance(value, _NUMERIC) or isinstance(value, bool):
            return False
        if op == "gte":
            return value >= fvalue
        if op == "lte":
            return value <= fvalue
        lo, hi = fvalue
        return lo <= value <= hi
    raise FilterError(f"op {op!r} unknown")  # unreachable; defensive


def _apply_filters(
    view: View, records: list[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    out = records
    for field, spec in view.filters.items():
        if view.corpus.field(field) is None:
            raise FilterError(
                f"view '{view.name}': filter on undeclared field '{field}'"
            )
        op, fvalue = _normalize_filter(field, spec)
        out = [r for r in out if _matches(_get(r, field), op, fvalue)]
    return out


def _expand(
    record: Mapping[str, Any], group_by: tuple[str, ...]
) -> Iterable[tuple[Any, ...]]:
    """Yield one group tuple per unnested list-facet value (cartesian across
    multiple list fields); empty/missing list -> a single ``None`` slot."""
    per_field: list[list[Any]] = []
    for field in group_by:
        value = _get(record, field)
        if isinstance(value, list):
            per_field.append(value if value else [None])
        else:
            per_field.append([value])
    return itertools.product(*per_field)


def _metric_value(metric: Metric, group_records: list[Mapping[str, Any]]) -> Any:
    if metric.kind == "count":
        return len(group_records)
    values = [
        v
        for v in (_get(r, metric.field) for r in group_records)
        if v is not None
    ]
    if not values:
        return None
    # mean(bool) = share of True (documented convention, plan §6.3): bools
    # coerce via float() to 1.0/0.0, so the plain mean IS the share.
    total = sum(float(v) if isinstance(v, bool) else v for v in values)
    return total / len(values)


def _provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, CanonicalRecord):
        prov = record.provenance
        return {
            "record_id": record.id,
            "source": prov.source,
            "media_ref": prov.media_ref,
            "timestamp": prov.timestamp,
        }
    provenance = record.get("provenance") or {}
    return {
        "record_id": record.get("id"),
        "source": provenance.get("source"),
        "media_ref": provenance.get("media_ref"),
        "timestamp": provenance.get("timestamp"),
    }


def _records(records: Iterable[Any]) -> list[Mapping[str, Any]]:
    """Accept ``CanonicalRecord[]`` (or plain field bags with ``id`` +
    ``provenance``)."""
    out: list[Mapping[str, Any]] = []
    for r in records:
        if isinstance(r, (CanonicalRecord, Mapping)):
            out.append(r)
        else:
            raise MaterializeError(
                f"record of type {type(r).__name__} is neither a CanonicalRecord "
                "nor a field bag mapping"
            )
    return out


def materialize(
    view: View, records: Iterable[Any], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Materialize ``view`` over ``records`` -> deterministic sorted rows.

    Every row: the group-by field values, one key per declared metric,
    ``provenance`` (per contributing record: record_id/source/media_ref/
    timestamp), ``materialized_at`` (UTC ISO-8601) and ``schema_version``.
    """
    recs = _records(records)
    filtered = _apply_filters(view, recs)

    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for r in filtered:
        for key in _expand(r, view.group_by):
            groups.setdefault(key, []).append(r)

    # Empty-group seeding: an `in` filter on a group_by field declares the
    # candidate values — seed zero rows for values no record matched.
    for field in view.group_by:
        spec = view.filters.get(field)
        if spec is None:
            continue
        op, fvalue = _normalize_filter(field, spec)
        if op == "in" and isinstance(fvalue, list):
            for v in fvalue:
                groups.setdefault((v,), [])

    materialized_at = (now or datetime.now(UTC)).isoformat()
    rows: list[dict[str, Any]] = []
    for key in sorted(groups, key=lambda k: tuple(str(v) for v in k)):
        group_records = groups[key]
        row: dict[str, Any] = dict(zip(view.group_by, key))
        for metric in view.metrics:
            row[metric.name] = _metric_value(metric, group_records)
        row["provenance"] = [_provenance(r) for r in group_records]
        row["materialized_at"] = materialized_at
        row["schema_version"] = view.schema_version
        rows.append(row)
    return rows
