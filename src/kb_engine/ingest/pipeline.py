"""IngestPipeline (plan §6.1): ``SourceAdapter -> Mapper -> DedupePolicy``
per declared source, deterministic + idempotent by ``content_hash``.

Guarantees:
  * Per-source processing: adding or removing a source touches no other
    source or engine code — each source's result depends only on its own
    declaration + inputs.
  * Idempotency: a record whose ``content_hash`` is unchanged since the
    previous run (tracked in the pipeline's state, seeded from the caller's
    existing ``{id: content_hash}`` map) is SKIPPED — never re-billed.
  * Envelope failures are NEVER silently dropped: per the declared
    ``missing.envelope_failure`` policy they become typed gaps or abort the
    pipeline. Type mismatches follow the same policy.
  * Optional-attribute absence -> ``None`` + per-field coverage stats.
  * A declared ``dedupe.namespace`` prefixes record ids for that source
    (``f"{namespace}:{id}"``), keeping cross-source id collisions distinct.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from kb_engine.config import CorpusConfig
from kb_engine.core.records import CanonicalRecord
from kb_engine.ingest.adapters import make_adapter
from kb_engine.ingest.dedupe import DedupeError, RecordDedupe
from kb_engine.ingest.mappers import EnvelopeFailure, MappingError, RecordMapper

__all__ = ["Gap", "IngestResult", "PipelineError", "IngestPipeline"]


class PipelineError(RuntimeError):
    """Abort policy fired, or the pipeline declaration is invalid."""


@dataclass(frozen=True)
class Gap:
    """One surfaced envelope/mapping failure (abstention coverage input)."""

    source: str
    index: int
    reason: str
    detail: str


@dataclass
class IngestResult:
    """Typed per-source result."""

    source: str
    added: list[CanonicalRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    # field name -> count of non-None values among successfully mapped items
    coverage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestPipeline:
    """Runs the declared sources of one corpus through the ingest seam."""

    corpus: CorpusConfig
    adapters: Mapping[str, Any] | None = None
    # Existing state: {record_id: content_hash} from a previous ingest —
    # a record whose hash is unchanged is skipped, never re-billed.
    existing: Mapping[str, str] = field(default_factory=dict)

    def run(self, source: str | None = None) -> list[IngestResult]:
        sources = (
            (spec for spec in self.corpus.sources if spec.name == source)
            if source is not None
            else iter(self.corpus.sources)
        )
        selected = list(sources)
        if source is not None and not selected:
            raise PipelineError(f"unknown source {source!r} for corpus "
                                f"'{self.corpus.name}'")
        return [self.run_source(spec.name) for spec in selected]

    def run_source(self, source: str) -> IngestResult:
        spec = next(
            (s for s in self.corpus.sources if s.name == source), None
        )
        if spec is None:
            raise PipelineError(f"unknown source {source!r} for corpus "
                                f"'{self.corpus.name}'")

        adapter = make_adapter(spec, self.adapters)
        mapper = RecordMapper(self.corpus, spec)
        try:
            dedupe = RecordDedupe(spec.dedupe)
        except DedupeError as exc:
            raise PipelineError(
                f"source '{spec.name}': invalid dedupe declaration: {exc}"
            ) from None
        fail_policy = spec.missing.get("envelope_failure", "gap")
        namespace = spec.dedupe.get("namespace")

        result = IngestResult(source=spec.name, gaps=self._gaps)
        records: list[CanonicalRecord] = []
        for index, raw in enumerate(adapter.load()):
            try:
                record = mapper.map(raw)
            except EnvelopeFailure as exc:
                self._failure(fail_policy, Gap(
                    source=spec.name, index=index,
                    reason=exc.reason, detail=exc.detail,
                ))
                continue
            except (MappingError,) as exc:
                self._failure(fail_policy, Gap(
                    source=spec.name, index=index,
                    reason="mapping_error", detail=str(exc),
                ))
                continue
            if namespace:
                record = replace(record, id=f"{namespace}:{record.id}")
            records.append(record)
            for name, value in record.fields.items():
                if value is not None:
                    result.coverage[name] = result.coverage.get(name, 0) + 1

        for record in dedupe.apply(records):
            if self._state.get(record.id) == record.content_hash:
                result.skipped.append(record.id)
            else:
                result.added.append(record)
                self._state[record.id] = record.content_hash
        return result

    def _failure(self, policy: str, gap: Gap) -> None:
        if policy == "abort":
            raise PipelineError(
                f"source '{gap.source}', item #{gap.index}: {gap.reason}: "
                f"{gap.detail}"
            )
        if policy != "gap":
            raise PipelineError(
                f"source '{gap.source}': unknown missing.envelope_failure "
                f"policy {policy!r} (gap | abort)"
            )
        self._gaps.append(gap)

    # Mutable per-run state lives off the frozen dataclass fields so the
    # declared configuration stays immutable/reusable across runs.
    @property
    def _state(self) -> dict[str, str]:
        return self.__dict__.setdefault("_state", dict(self.existing))

    @property
    def _gaps(self) -> list[Gap]:
        return self.__dict__.setdefault("_gaps", [])


def ingest(
    corpus: CorpusConfig,
    existing: Mapping[str, str] | None = None,
    adapters: Mapping[str, Any] | None = None,
) -> list[IngestResult]:
    """Convenience one-shot run over every declared source."""
    return IngestPipeline(corpus, adapters, existing or {}).run()


def iter_records(results: Iterable[IngestResult]) -> Iterable[CanonicalRecord]:
    for result in results:
        yield from result.added
