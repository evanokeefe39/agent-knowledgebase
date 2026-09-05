"""Serve tier (plan §6.5): structured search/get over one corpus.

* :func:`serve` — retriever results through the QueryParams envelope into a
  result envelope ``{hits, total_matched, cursor?, abstained,
  abstention_reason}`` with provenance on every hit.
* :func:`get` — record fetch by id with provenance.
* Abstention is a FIRST-CLASS typed result (``insufficient_evidence``) keyed
  on DERIVED signals only — content-token coverage of the top hit and the
  relative top-1/top-2 margin — never a raw retriever score (BM25/dense/RRF
  scales are incomparable; plan §12).
* Pagination is an opaque cursor carrying the index version + a query
  fingerprint; a cursor minted by an older index version (or a different
  query) is rejected with :class:`StaleCursorError`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field as dc_field
from typing import Any, Mapping

from kb_engine.config import CorpusConfig
from kb_engine.core.contracts import RankedHit
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord

from kb_engine.serve.params import (
    QueryFilter,
    QueryParams,
    SortKey,
    _is_list_field,
    _matches,
)
DEFAULT_MAX_TOP_K = 100
DEFAULT_MIN_COVERAGE = 0.6
DEFAULT_MARGIN_RATIO = 0.15

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)

# Minimal English stopword set for content-token derivation (tokens that
# carry content; stopwords never count toward coverage).
_STOPWORDS: frozenset[str] = frozenset(
    """a an and are as at be but by for from has have how i in is it its of on
    or that the this to was what when where which who why will with you your
    do does did can could should would""".split()
)


class ServeError(RuntimeError):
    """Base error for the serve tier."""


class ModeError(ServeError):
    """Requested mode is not a declared retrieval strategy for the corpus."""


class StaleCursorError(ServeError):
    """Cursor was minted by an older index version (or a different query)."""


class RecordStoreRequired(ServeError):
    """Filters/sort/abstention were requested without a record store."""


# ---- serve config ------------------------------------------------------------


@dataclass(frozen=True)
class ServeConfig:
    """Server policy derived from the corpus declaration (never caller
    knobs): declared strategies, ``max_top_k``, defaults, abstention."""

    strategies: tuple[str, ...]
    default_mode: str
    max_top_k: int
    default_top_k: int
    min_coverage: float
    margin_ratio: float
    index_version: str

    @classmethod
    def from_corpus(cls, corpus: CorpusConfig) -> "ServeConfig":
        raw = corpus.raw
        index = raw.get("index") or {}
        retrieval = index.get("retrieval") or {}
        strategies = retrieval.get("strategies") or {}
        serve = raw.get("serve") or {}
        defaults = serve.get("defaults") or {}
        abstention = serve.get("abstention") or {}
        default_mode = defaults.get("mode") or retrieval.get("default")
        return cls(
            strategies=tuple(strategies.keys()),
            default_mode=default_mode,
            max_top_k=int(retrieval.get("max_top_k", DEFAULT_MAX_TOP_K)),
            default_top_k=int(defaults.get("top_k", 10)),
            min_coverage=float(abstention.get("min_coverage", DEFAULT_MIN_COVERAGE)),
            margin_ratio=float(abstention.get("margin_ratio", DEFAULT_MARGIN_RATIO)),
            index_version=str(index.get("schema_version", "0")),
        )


# ---- result shapes -----------------------------------------------------------


@dataclass(frozen=True)
class ServeHit:
    """One result hit: RankedHit-like, plus rank + provenance (plan §6.5:
    provenance on every hit)."""

    record_id: str
    score: float
    rank: int
    provenance: Provenance
    fields: Mapping[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """Result envelope. ``cursor`` is present only when more pages exist."""

    hits: tuple[ServeHit, ...]
    total_matched: int
    abstained: bool
    abstention_reason: str | None = None
    abstention_detail: Mapping[str, Any] | None = None
    cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "hits": [
                {
                    "record_id": h.record_id,
                    "score": h.score,
                    "rank": h.rank,
                    "provenance": {
                        "source": h.provenance.source,
                        "media_ref": h.provenance.media_ref,
                        "timestamp": h.provenance.timestamp,
                        "extractor": h.provenance.extractor,
                        "confidence": h.provenance.confidence,
                    },
                }
                for h in self.hits
            ],
            "total_matched": self.total_matched,
            "abstained": self.abstained,
        }
        if self.abstention_reason is not None:
            out["abstention_reason"] = self.abstention_reason
        if self.abstention_detail is not None:
            out["abstention_detail"] = dict(self.abstention_detail)
        if self.cursor is not None:
            out["cursor"] = self.cursor
        return out


@dataclass(frozen=True)
class GetResult:
    """One record with provenance (serve/get seam)."""

    record_id: str
    fields: Mapping[str, Any]
    provenance: Provenance


# ---- cursor ------------------------------------------------------------------
# Opaque token: base64url(JSON {iv, fp, o}) + checksum. Offset-based ONLY
# inside the server over the already-ranked candidate window; the caller
# never sees an offset (offset breaks under re-ranking).


def _fingerprint(params: QueryParams) -> str:
    payload = json.dumps(
        {
            "q": params.query,
            "c": params.corpus,
            "m": params.mode,
            "k": params.top_k,
            "f": [(f.field, f.op, f.value) for f in params.filters],
            "s": [(s.field, s.order) for s in params.sort],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _encode_cursor(index_version: str, fingerprint: str, offset: int) -> str:
    payload = json.dumps({"iv": index_version, "fp": fingerprint, "o": offset})
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return token + "." + hashlib.sha256(token.encode("ascii")).hexdigest()[:8]


def _decode_cursor(cursor: str, index_version: str, fingerprint: str) -> int:
    token, _, checksum = cursor.rpartition(".")
    if not token or not checksum or hashlib.sha256(token.encode("ascii")).hexdigest()[:8] != checksum:
        raise StaleCursorError("cursor is malformed or corrupted")
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.encode("ascii")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise StaleCursorError("cursor is malformed") from exc
    if not isinstance(payload, dict) or not {"iv", "fp", "o"} <= payload.keys():
        raise StaleCursorError("cursor is malformed")
    if payload["iv"] != index_version:
        raise StaleCursorError(
            f"cursor was minted by index version '{payload['iv']}' but the "
            f"current index version is '{index_version}'"
        )
    if payload["fp"] != fingerprint:
        raise StaleCursorError("cursor does not belong to this query")
    return int(payload["o"])


# ---- derived abstention signals ----------------------------------------------


def content_tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens minus stopwords (the query's
    content-bearing tokens)."""
    norm = unicodedata.normalize("NFKC", text).casefold()
    return [t for t in _TOKEN_RE.findall(norm) if t not in _STOPWORDS]


def _search_text(record: CanonicalRecord, corpus: CorpusConfig) -> str:
    parts: list[str] = []
    for name, spec in corpus.fields.items():
        if "search" in spec.roles:
            value = record.fields.get(name)
            if isinstance(value, list):
                parts.extend(str(v) for v in value)
            elif value is not None:
                parts.append(str(value))
    return " ".join(parts)


def coverage_ratio(tokens: list[str], top_record: CanonicalRecord | None,
                   corpus: CorpusConfig) -> float:
    """Fraction of the query's content tokens covered by the top hit's
    search-role text. Empty token set -> fully covered (nothing to demand)."""
    if not tokens:
        return 1.0
    if top_record is None:
        return 0.0
    haystack = set(content_tokens(_search_text(top_record, corpus)))
    covered = sum(1 for t in tokens if t in haystack)
    return covered / len(tokens)


def relative_margin(scores: list[float]) -> float:
    """Relative margin between top-1 and top-2: ``(s1 - s2) / |s1|``.
    With fewer than two hits there is nothing to compare -> margin satisfied
    (1.0). Never a raw score: a scale-free ratio only."""
    if len(scores) < 2:
        return 1.0
    s1, s2 = scores[0], scores[1]
    denom = abs(s1)
    if denom == 0.0:
        return 0.0
    return (s1 - s2) / denom


# ---- filtering + sorting -----------------------------------------------------

def _sort_value(hit: RankedHit, key: SortKey,
                records: Mapping[str, CanonicalRecord]) -> Any:
    if key.field == "_score":
        return hit.score
    record = records.get(hit.record_id)
    return None if record is None else record.fields.get(key.field)


def _apply_filters(
    hits: list[RankedHit],
    params: QueryParams,
    records: Mapping[str, CanonicalRecord],
    corpus: CorpusConfig,
) -> list[RankedHit]:
    if not params.filters:
        return hits
    out: list[RankedHit] = []
    for hit in hits:
        record = records.get(hit.record_id)
        if record is None:
            continue
        if all(
            _matches(record.fields.get(f.field), f, _is_list_field(corpus, f.field))
            for f in params.filters
        ):
            out.append(hit)
    return out


def _apply_sort(
    hits: list[RankedHit],
    params: QueryParams,
    records: Mapping[str, CanonicalRecord],
) -> list[RankedHit]:
    if not params.sort:
        return hits
    # Deterministic: apply declared keys last-to-first with Python's stable
    # sort, then record_id as the final tiebreaker. None sorts last.
    out = sorted(hits, key=lambda h: h.record_id)
    for key in reversed(params.sort):
        out.sort(
            key=lambda h, k=key: _SortVal(_sort_value(h, k, records), k.order),
        )
    return out


class _SortVal:
    """Sortable wrapper: None sorts last regardless of direction; desc
    inverts the comparison (with a str fallback for mixed types)."""

    __slots__ = ("value", "desc", "is_none")

    def __init__(self, value: Any, order: str) -> None:
        self.value = value
        self.desc = order == "desc"
        self.is_none = value is None

    def __lt__(self, other: "_SortVal") -> bool:
        if self.is_none != other.is_none:
            return other.is_none  # None last in both directions
        if self.is_none:
            return False
        a, b = self.value, other.value
        try:
            return a > b if self.desc else a < b
        except TypeError:
            sa, sb = str(a), str(b)
            return sa > sb if self.desc else sa < sb



# ---- serve -------------------------------------------------------------------


def _resolve_mode(params: QueryParams, cfg: ServeConfig) -> str:
    mode = params.mode or cfg.default_mode
    if mode not in cfg.strategies:
        raise ModeError(
            f"mode '{mode}' is not a declared retrieval strategy for this "
            f"corpus; declared strategies: {list(cfg.strategies)}"
        )
    return mode


def serve(
    corpus: CorpusConfig,
    retriever: Any,
    params: QueryParams,
    records: Mapping[str, CanonicalRecord] | None = None,
    config: ServeConfig | None = None,
) -> SearchResult:
    """Serve one search over ``corpus``.

    ``records`` is the record store (id -> CanonicalRecord) required for
    filters, sort and abstention — retrieval supplies order + identity only.
    """
    cfg = config or ServeConfig.from_corpus(corpus)
    _resolve_mode(params, cfg)  # validate declared strategies (incl. fallback)
    if (params.filters or params.sort) and records is None:
        raise RecordStoreRequired(
            "filters/sort require a record store; pass records={id: CanonicalRecord}"
        )
    top_k = min(params.top_k or cfg.default_top_k, cfg.max_top_k)

    offset = 0
    if params.cursor is not None:
        offset = _decode_cursor(params.cursor, cfg.index_version, _fingerprint(params))

    # Candidate window: the server cap (never caller-controlled beyond it).
    candidates = list(retriever.search(params.query, cfg.max_top_k))
    if records is not None:
        candidates = _apply_filters(candidates, params, records, corpus)
    candidates = _apply_sort(candidates, params, records or {})
    total_matched = len(candidates)

    # Abstention: derived signals over the ranked (pre-pagination) window.
    abstained = False
    reason: str | None = None
    detail: dict[str, Any] | None = None
    if records is not None:
        tokens = content_tokens(params.query or "")
        top_record = records.get(candidates[0].record_id) if candidates else None
        coverage = coverage_ratio(tokens, top_record, corpus)
        margin = relative_margin([h.score for h in candidates])
        detail = {"coverage": round(coverage, 4), "margin": round(margin, 4),
                  "min_coverage": cfg.min_coverage, "margin_ratio": cfg.margin_ratio}
        if not candidates or coverage < cfg.min_coverage or margin < cfg.margin_ratio:
            abstained = True
            reason = "insufficient_evidence"

    page = candidates[offset : offset + top_k]
    hits = tuple(
        ServeHit(
            record_id=hit.record_id,
            score=hit.score,
            rank=i,
            provenance=records[hit.record_id].provenance
            if records is not None and hit.record_id in records
            else Provenance(source="", media_ref=""),
            fields=dict(records[hit.record_id].fields)
            if records is not None and hit.record_id in records
            else {},
        )
        for i, hit in enumerate(page, start=offset + 1)
    )

    next_offset = offset + top_k
    cursor = (
        _encode_cursor(cfg.index_version, _fingerprint(params), next_offset)
        if next_offset < total_matched
        else None
    )
    return SearchResult(
        hits=hits,
        total_matched=total_matched,
        abstained=abstained,
        abstention_reason=reason,
        abstention_detail=detail,
        cursor=cursor,
    )


def get(
    record_id: str, records: Mapping[str, CanonicalRecord]
) -> GetResult | None:
    """Fetch one record by id with provenance; ``None`` when unknown."""
    record = records.get(record_id)
    if record is None:
        return None
    return GetResult(
        record_id=record.id, fields=dict(record.fields), provenance=record.provenance
    )
