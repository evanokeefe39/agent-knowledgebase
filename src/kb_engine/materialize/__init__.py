"""Declarative materializer (plan §6.3, Build-5): generic group-by/count/avg
view engine replacing the bespoke ``kb/gold.py`` views.

Contract:
  * ``View = {name, group_by, metrics, filters, freshness}`` parsed from the
    corpus declaration's ``materialize`` block (never hardcoded field names —
    the engine reads declared types + roles only).
  * Every output row carries record-level provenance of its contributing
    records, ``materialized_at`` (UTC ISO-8601) and the corpus
    ``schema_version``.
  * List facets unnest per value (one row per value).
  * ``mean(bool)`` = share of ``True`` values (documented convention).
  * ``filters`` are explicit ops (``{op, value}``; shorthand scalar=eq,
    list=in) validated against declared filter/facet fields — unknown field
    OR op is a clear error, never silent.
  * Views refuse to serve past their declared freshness
    (:class:`StaleViewError`) until :meth:`ViewManager.refresh` re-materializes.
"""

from __future__ import annotations

from kb_engine.materialize.engine import (
    FilterError,
    MaterializeError,
    StaleViewError,
    materialize,
)
from kb_engine.materialize.manager import ViewManager
from kb_engine.materialize.views import View, ViewConfigError, parse_views

__all__ = [
    "FilterError",
    "MaterializeError",
    "StaleViewError",
    "View",
    "ViewConfigError",
    "ViewManager",
    "materialize",
    "parse_views",
]
