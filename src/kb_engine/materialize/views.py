"""View declaration parsing (plan §6.3): ``View = {name, group_by, metrics,
filters, freshness}`` from a corpus's ``materialize`` block.

The parser validates against the corpus's declared schema ONLY via types +
roles (plan §6.6) — zero field-name references in engine code:

  * ``group_by`` fields MUST have role ``facet`` (list-valued facets unnest
    per value).
  * ``metrics``: ``count`` needs no field; ``mean(field)`` requires a declared
    ``int``/``float`` field (role ``metric``) OR a ``bool`` field — mean over
    bool is the documented share convention, so a bool field is a legal mean
    input while a string field is a config error (fail fast, Build-5 edge
    case "metric over a non-metric-role field").
  * ``filters``: fields MUST have role ``filter``/``facet`` (term match) or
    ``metric`` (range ops per §6.6); op ``gte``/``lte``/``between``
    additionally require a numeric (metric) field.
  * ``freshness``: corpus-level ``materialize.freshness`` default, per-view
    override; ``"<n><s|m|h|d>"`` -> timedelta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from kb_engine.config import CorpusConfig

VALID_FILTER_OPS: frozenset[str] = frozenset({"eq", "in", "gte", "lte", "between"})

_FRESHNESS_RE = re.compile(r"^(\d+)\s*([smhd])$")
_MEAN_RE = re.compile(r"^mean\(([A-Za-z_][A-Za-z0-9_]*)\)$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class ViewConfigError(Exception):
    """A corpus's ``materialize`` block failed validation (fail fast)."""


def parse_freshness(value: Any) -> timedelta:
    """Parse ``"<n><s|m|h|d>"`` into a :class:`~datetime.timedelta`."""
    if isinstance(value, timedelta):
        return value
    m = _FRESHNESS_RE.match(value.strip()) if isinstance(value, str) else None
    if not m:
        raise ViewConfigError(
            f"invalid freshness {value!r}: expected '<n><s|m|h|d>' (e.g. '24h')"
        )
    return timedelta(seconds=int(m.group(1)) * _UNIT_SECONDS[m.group(2)])


@dataclass(frozen=True)
class Metric:
    """One declared metric: ``count`` (records in group) or ``mean`` over a
    declared numeric/bool field (bool -> share of True)."""

    name: str
    kind: str  # "count" | "mean"
    field: str | None = None


@dataclass(frozen=True)
class View:
    """A parsed, schema-validated view. ``corpus`` back-links the declaring
    :class:`~kb_engine.config.CorpusConfig` so ``materialize()`` can validate
    filters and stamp ``schema_version`` without re-parsing."""

    name: str
    corpus: CorpusConfig
    group_by: tuple[str, ...]
    metrics: tuple[Metric, ...]
    filters: Mapping[str, Any]
    freshness: timedelta

    @property
    def schema_version(self) -> str:
        return self.corpus.schema_version


def _parse_metrics(
    corpus: CorpusConfig, view_name: str, raw: Any
) -> tuple[Metric, ...]:
    if not isinstance(raw, list) or not raw:
        raise ViewConfigError(
            f"view '{view_name}': 'metrics' must be a non-empty list"
        )
    metrics: list[Metric] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, Mapping) or len(entry) != 1:
            raise ViewConfigError(
                f"view '{view_name}': metrics[{i}] must be a single-key mapping "
                "like {post_count: count} or {avg_value_score: mean(value_score)}"
            )
        (mname, mspec) = next(iter(entry.items()))
        if not isinstance(mname, str) or not mname:
            raise ViewConfigError(f"view '{view_name}': metrics[{i}] name invalid")
        if mspec == "count":
            metrics.append(Metric(mname, "count"))
            continue
        m = _MEAN_RE.match(mspec.strip()) if isinstance(mspec, str) else None
        if not m:
            raise ViewConfigError(
                f"view '{view_name}': metrics[{i}] spec {mspec!r} invalid — expected "
                "'count' or 'mean(<field>)'"
            )
        field = m.group(1)
        spec = corpus.field(field)
        if spec is None:
            raise ViewConfigError(
                f"view '{view_name}': mean over undeclared field '{field}'"
            )
        if spec.type not in {"int", "float", "bool"}:
            raise ViewConfigError(
                f"view '{view_name}': metric over field '{field}' of type "
                f"'{spec.type}' is not aggregable (int/float required; bool "
                "mean = share); config-load fail fast"
            )
        metrics.append(Metric(mname, "mean", field))
    return tuple(metrics)


def _validate_filters(corpus: CorpusConfig, view_name: str, filters: Any) -> None:
    if not isinstance(filters, Mapping):
        raise ViewConfigError(f"view '{view_name}': 'filters' must be a mapping")
    for field, spec in filters.items():
        fs = corpus.field(field)
        if fs is None:
            raise ViewConfigError(
                f"view '{view_name}': filter on undeclared field '{field}'"
            )
        if not ({"filter", "facet", "metric"} & set(fs.roles)):
            raise ViewConfigError(
                f"view '{view_name}': filter field '{field}' lacks role "
                "filter/facet/metric (declared roles: " + ", ".join(fs.roles) + ")"
            )
        # Shorthand forms normalize at materialize time (scalar=eq, list=in);
        # here only explicit op mappings are validated.
        if isinstance(spec, Mapping):
            op = spec.get("op")
            if op not in VALID_FILTER_OPS:
                raise ViewConfigError(
                    f"view '{view_name}': filter '{field}' op {op!r} unknown — "
                    f"ops: {sorted(VALID_FILTER_OPS)}"
                )
            if op in {"gte", "lte", "between"} and fs.type not in {"int", "float"}:
                raise ViewConfigError(
                    f"view '{view_name}': op '{op}' on field '{field}' of type "
                    f"'{fs.type}' requires a numeric (metric) field"
                )


def _validate_group_by(
    corpus: CorpusConfig, view_name: str, group_by: Any
) -> tuple[str, ...]:
    if not isinstance(group_by, list) or not group_by:
        raise ViewConfigError(
            f"view '{view_name}': 'group_by' must be a non-empty list of facet fields"
        )
    for field in group_by:
        fs = corpus.field(field)
        if fs is None:
            raise ViewConfigError(
                f"view '{view_name}': group_by on undeclared field '{field}'"
            )
        if "facet" not in fs.roles:
            raise ViewConfigError(
                f"view '{view_name}': group_by field '{field}' lacks role 'facet'"
            )
    return tuple(group_by)


def parse_views(corpus: CorpusConfig) -> list[View]:
    """Parse + validate every declared view of ``corpus``'s ``materialize``
    block. A corpus with no ``materialize`` block declares no views (empty
    list — not an error)."""
    block = corpus.raw.get("materialize")
    if block is None:
        return []
    if not isinstance(block, Mapping):
        raise ViewConfigError("'materialize' must be a mapping")

    default_freshness = block.get("freshness")
    views_raw = block.get("views", [])
    if not isinstance(views_raw, list):
        raise ViewConfigError("'materialize.views' must be a list")

    views: list[View] = []
    for i, raw in enumerate(views_raw):
        if not isinstance(raw, Mapping):
            raise ViewConfigError(f"views[{i}] must be a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ViewConfigError(f"views[{i}]: 'name' must be a non-empty string")
        freshness_value = raw.get("freshness", default_freshness)
        if freshness_value is None:
            raise ViewConfigError(
                f"view '{name}': no freshness declared (per-view or "
                "'materialize.freshness' default)"
            )
        filters = raw.get("filters") or {}
        _validate_filters(corpus, name, filters)
        views.append(
            View(
                name=name,
                corpus=corpus,
                group_by=_validate_group_by(corpus, name, raw.get("group_by")),
                metrics=_parse_metrics(corpus, name, raw.get("metrics")),
                filters=filters,
                freshness=parse_freshness(freshness_value),
            )
        )
    return views
