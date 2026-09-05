"""View manager (plan §6.3): refresh + serve-with-freshness-check.

A :class:`ViewManager` holds materialized views for one corpus. ``refresh``
re-materializes one or all views and stamps the materialization time;
``serve`` refuses a view older than its declared freshness with
:class:`StaleViewError` — the consumer must refresh first. A ``clock``
callable is injectable so freshness is testable hermetically (default: UTC
now).
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping
from datetime import UTC, datetime
from kb_engine.config import CorpusConfig
from kb_engine.materialize.engine import StaleViewError, materialize
from kb_engine.materialize.views import View, parse_views

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ViewManager:
    """Materialize + serve declared views of one corpus with freshness
    enforcement."""

    def __init__(
        self,
        corpus: CorpusConfig,
        records: Iterable[Any] = (),
        *,
        clock: Clock | None = None,
    ) -> None:
        self.corpus = corpus
        self.views: dict[str, View] = {v.name: v for v in parse_views(corpus)}
        self._clock: Clock = clock or _utc_now
        self._rows: dict[str, list[dict[str, Any]]] = {}
        self._materialized: dict[str, datetime] = {}
        self._last_records: list[Any] = list(records)
        if records:
            self.refresh(records=records)

    def refresh(
        self,
        records: Iterable[Any] | None = None,
        *,
        view: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """(Re-)materialize ``view`` (or every declared view) over
        ``records``; returns the refreshed rows."""
        names = [view] if view is not None else sorted(self.views)
        if view is not None and view not in self.views:
            raise KeyError(
                f"view '{view}' is not declared by corpus '{self.corpus.name}'"
            )
        recs = list(records) if records is not None else self._last_records
        self._last_records = recs
        stamp = now or self._clock()
        rows: list[dict[str, Any]] = []
        for name in names:
            fresh = materialize(self.views[name], recs, now=stamp)
            self._rows[name] = fresh
            self._materialized[name] = stamp
            rows.extend(fresh)
        return rows

    def serve(
        self, view: str, *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return the materialized rows of ``view`` if fresh; raise
        :class:`StaleViewError` when the view's age exceeds its declared
        freshness (refuse to serve) — call :meth:`refresh` first."""
        if view not in self.views:
            raise KeyError(
                f"view '{view}' is not declared by corpus '{self.corpus.name}'"
            )
        if view not in self._materialized:
            raise StaleViewError(
                f"view '{view}' has never been materialized; refresh required"
            )
        at = now or self._clock()
        age = at - self._materialized[view]
        if age > self.views[view].freshness:
            raise StaleViewError(
                f"view '{view}' is stale: age {age} exceeds declared freshness "
                f"{self.views[view].freshness}; refresh required"
            )
        return self._rows[view]

    def status(self, *, now: datetime | None = None) -> Mapping[str, Any]:
        """Per-view state snapshot: materialized_at, age, freshness, stale."""
        at = now or self._clock()
        out: dict[str, Any] = {}
        for name, v in self.views.items():
            if name not in self._materialized:
                out[name] = {
                    "materialized_at": None,
                    "age": None,
                    "freshness": v.freshness,
                    "stale": True,
                }
                continue
            age = at - self._materialized[name]
            out[name] = {
                "materialized_at": self._materialized[name].isoformat(),
                "age": age,
            }
        return out


from datetime import UTC  # noqa: E402  (used by _utc_now; kept near use)
