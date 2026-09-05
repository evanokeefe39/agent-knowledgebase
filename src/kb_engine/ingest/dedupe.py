"""DedupePolicy (plan §6.1): declared key + policy + deterministic order.

Policies over the declared dedupe key (``record.fields`` values):
  * ``keep_first``          — first occurrence wins;
  * ``newest``              — max ``provenance.timestamp`` (None lowest);
  * ``highest_confidence``  — max ``provenance.confidence`` (None lowest);
  * ``version_append``      — keep ALL versions; later duplicates get
    ``{id}#v2``, ``{id}#v3``, ... (first keeps the bare id).

Order is always deterministic: duplicates resolve in arrival order, which
is the ``source_declaration`` order — the declared ``order`` must be
exactly that (a missing/unknown declared order is a config error).
Input order is never mutated; output preserves first-occurrence order.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from kb_engine.core.records import CanonicalRecord

__all__ = ["DedupeError", "RecordDedupe"]

_POLICIES = frozenset(
    {"keep_first", "newest", "highest_confidence", "version_append"}
)


class DedupeError(ValueError):
    """Invalid dedupe declaration (missing order, unknown policy, ...)."""


class RecordDedupe:
    """Implements the ``DedupePolicy`` protocol for one declared source."""

    def __init__(self, spec: Mapping[str, Any]) -> None:
        key = spec.get("key")
        if not key or not isinstance(key, list):
            raise DedupeError("dedupe.key must be a non-empty list of field names")
        order = spec.get("order")
        if order != "source_declaration":
            raise DedupeError(
                f"dedupe.order must be 'source_declaration' (deterministic); "
                f"got {order!r} — a missing declared order is a config error"
            )
        policy = spec.get("policy", "keep_first")
        if policy not in _POLICIES:
            raise DedupeError(
                f"unknown dedupe policy {policy!r} "
                f"(declared: {', '.join(sorted(_POLICIES))})"
            )
        self.key_fields: tuple[str, ...] = tuple(key)
        self.policy: str = policy

    def _key(self, record: CanonicalRecord) -> tuple[Any, ...]:
        return tuple(record.fields.get(name) for name in self.key_fields)

    def apply(self, records: Iterable[CanonicalRecord]) -> list[CanonicalRecord]:
        kept: list[CanonicalRecord] = []
        seen: dict[tuple[Any, ...], list[CanonicalRecord]] = {}
        for record in records:
            key = self._key(record)
            group = seen.get(key)
            if group is None:
                seen[key] = [record]
                kept.append(record)
                continue
            group.append(record)
            if self.policy == "version_append":
                # Keep every version; later duplicates get a stable suffix.
                kept.append(_versioned(record, len(group)))
                continue
            winner = group[0]
            if self.policy == "newest":
                if (record.provenance.timestamp or "") > (
                    winner.provenance.timestamp or ""
                ):
                    winner = record
            elif self.policy == "highest_confidence":
                if (record.provenance.confidence or 0.0) > (
                    winner.provenance.confidence or 0.0
                ):
                    winner = record
            if winner is not group[0]:
                # Replace the previously kept occurrence in place so output
                # order stays first-occurrence-deterministic.
                index = next(i for i, r in enumerate(kept) if r is group[0])
                kept[index] = winner
                group[0] = winner
        return kept


def _versioned(record: CanonicalRecord, occurrence: int) -> CanonicalRecord:
    """Append a stable version suffix for non-first duplicates."""
    suffix = f"#v{occurrence}"
    return CanonicalRecord(
        id=f"{record.id}{suffix}",
        content_hash=record.content_hash,
        provenance=record.provenance,
        fields=dict(record.fields),
    )
