"""QueryParams envelope + explicit-op filter validation (plan §6.5).

The envelope is generic: engine code references NO corpus field name — every
filter/sort field is validated against the corpus's DECLARED roles
(``filter`` / ``facet`` / ``metric`` / ``sort``). Unknown field OR unknown op
-> a clear typed error, never silent.

Ops (locked vocabulary): ``eq`` | ``in`` | ``gte`` | ``lte`` | ``between``.
Shorthand in the raw envelope: a scalar value means ``eq``, a list value
means ``in``. Explicit form: ``{"op": ..., "value": ...}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from kb_engine.config import CorpusConfig

OPS: tuple[str, ...] = ("eq", "in", "gte", "lte", "between")

# Which ops each filter-capable declared role admits (plan §6.6).
_ROLE_OPS: dict[str, frozenset[str]] = {
    "filter": frozenset({"eq", "in"}),
    "facet": frozenset({"eq", "in"}),
    "metric": frozenset({"eq", "gte", "lte", "between"}),
}

# Roles whose fields may appear in ``sort`` (plan §6.5) plus ``_score``.
_SORT_ROLES: frozenset[str] = frozenset({"filter", "facet", "metric", "sort"})

_ORDERS: tuple[str, ...] = ("asc", "desc")

_LIST_TYPES: frozenset[str] = frozenset({"list[text]", "list[string]"})


class QueryParamsError(ValueError):
    """Invalid query params: unknown field, unknown op, bad shape/order."""


@dataclass(frozen=True)
class QueryFilter:
    """One explicit-op filter on one declared field."""

    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class SortKey:
    field: str
    order: str  # asc | desc


@dataclass(frozen=True)
class QueryParams:
    """Serve query envelope: ``{query, corpus?, mode, top_k, cursor?,
    filters, sort?}`` (plan §6.5). Build via :meth:`from_raw`, which
    validates everything against the corpus declaration."""

    query: str
    mode: str
    top_k: int
    corpus: str | None = None
    cursor: str | None = None
    filters: tuple[QueryFilter, ...] = ()
    sort: tuple[SortKey, ...] = ()

    def filters_for(self, field: str) -> tuple[QueryFilter, ...]:
        return tuple(f for f in self.filters if f.field == field)


# ---- validation --------------------------------------------------------------


def _field_roles(corpus: CorpusConfig, name: str) -> tuple[str, ...]:
    spec = corpus.field(name)
    return spec.roles if spec is not None else ()


def _op_allowed(corpus: CorpusConfig, name: str, op: str) -> bool:
    roles = _field_roles(corpus, name)
    return any(op in _ROLE_OPS.get(r, frozenset()) for r in roles)


def _parse_filter(
    corpus: CorpusConfig, name: str, raw: Any
) -> QueryFilter:
    """Validate one raw filter entry (shorthand or explicit) for ``name``."""

    def err(problem: str) -> QueryParamsError:
        return QueryParamsError(f"filter '{name}': {problem}")

    spec = corpus.field(name)
    if spec is None:
        raise QueryParamsError(
            f"filter field '{name}' is not declared in corpus '{corpus.name}'"
        )
    if not _op_allowed(corpus, name, "__probe__") and not any(
        r in _ROLE_OPS for r in spec.roles
    ):
        raise QueryParamsError(
            f"filter field '{name}' has roles {list(spec.roles) or ['(none)']}; "
            "filtering requires a filter-capable role (filter/facet/metric) "
            f"in corpus '{corpus.name}'"
        )

    if isinstance(raw, Mapping):
        op = raw.get("op")
        value = raw.get("value")
        if op is None:
            raise err("explicit form requires 'op' and 'value'")
    else:
        # Shorthand: scalar = eq, list = in.
        op = "in" if isinstance(raw, list) else "eq"
        value = raw

    if op not in OPS:
        raise err(
            f"unknown op '{op}'; ops are one of {list(OPS)}"
        )
    if not _op_allowed(corpus, name, op):
        allowed = sorted(
            {o for r in spec.roles for o in _ROLE_OPS.get(r, frozenset())}
        )
        raise err(
            f"op '{op}' is not valid for field '{name}' (type {spec.type}, "
            f"roles {list(spec.roles)}); allowed ops: {allowed}"
        )

    # Op x value-shape validation.
    if op == "in":
        if not isinstance(value, list) or not value:
            raise err("op 'in' requires a non-empty list value")
    elif op == "between":
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 2
            or not all(isinstance(v, (int, float)) for v in value)
        ):
            raise err("op 'between' requires a [low, high] numeric pair")
    else:  # eq | gte | lte
        if isinstance(value, dict) or (
            isinstance(value, list) and not _is_list_field(corpus, name)
        ):
            raise err(f"op '{op}' requires a scalar value, not {type(value).__name__}")
    return QueryFilter(field=name, op=op, value=value)


def parse_filters(corpus: CorpusConfig, raw: Any) -> tuple[QueryFilter, ...]:
    """Parse + validate the raw ``filters`` mapping against the corpus."""
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise QueryParamsError("'filters' must be a mapping of field -> filter")
    out = []
    for name, spec in raw.items():
        if not isinstance(name, str) or not name:
            raise QueryParamsError("'filters' keys must be non-empty field names")
        out.append(_parse_filter(corpus, name, spec))
    return tuple(out)


def parse_sort(corpus: CorpusConfig, raw: Any) -> tuple[SortKey, ...]:
    """Parse + validate ``sort`` (``[{field, order}]``) against the corpus.

    Only declared filter/facet/metric/sort fields plus the pseudo-field
    ``_score`` are sortable (plan §6.5)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise QueryParamsError("'sort' must be a list of {field, order} entries")
    out: list[SortKey] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, Mapping) or "field" not in entry:
            raise QueryParamsError(f"sort[{i}]: expected a {{field, order}} mapping")
        field = entry["field"]
        order = entry.get("order", "desc")
        if not isinstance(field, str) or not field:
            raise QueryParamsError(f"sort[{i}]: 'field' must be a non-empty string")
        if order not in _ORDERS:
            raise QueryParamsError(
                f"sort[{i}]: order must be one of {list(_ORDERS)}, got '{order}'"
            )
        if field == "_score":
            out.append(SortKey(field=field, order=order))
            continue
        spec = corpus.field(field)
        if spec is None:
            raise QueryParamsError(
                f"sort field '{field}' is not declared in corpus '{corpus.name}'"
            )
        if not (_SORT_ROLES & set(spec.roles)):
            raise QueryParamsError(
                f"sort field '{field}' has roles {list(spec.roles) or ['(none)']}; "
                "sorting requires a declared filter/facet/metric/sort role "
                f"in corpus '{corpus.name}'"
            )
        out.append(SortKey(field=field, order=order))
    return tuple(out)


def _is_list_field(corpus: CorpusConfig, name: str) -> bool:
    spec = corpus.field(name)
    return spec is not None and spec.type in _LIST_TYPES


def _matches(record_value: Any, f: QueryFilter, list_field: bool) -> bool:
    """Apply one filter to a record field value. ``None`` matches nothing."""
    if record_value is None:
        return False
    if f.op == "eq":
        # Distinguished semantics on list fields: eq = whole-list equality.
        if list_field:
            return isinstance(record_value, list) and record_value == f.value
        return not isinstance(record_value, list) and record_value == f.value
    if f.op == "in":
        # in = membership; on list fields, any-element overlap (unnest).
        if list_field:
            return isinstance(record_value, list) and bool(
                set(record_value) & set(f.value)
            )
        return record_value in f.value
    if f.op == "gte":
        return record_value >= f.value
    if f.op == "lte":
        return record_value <= f.value
    if f.op == "between":
        low, high = f.value
        return low <= record_value <= high
    raise QueryParamsError(f"unknown op '{f.op}'")  # unreachable; OPS is locked
