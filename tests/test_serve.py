"""Build-7 tests: serve tier (plan §6.5).

Hermetic: no live API anywhere — a scripted fake retriever, fixture corpus
declaration + records under ``tests/fixtures/serve/``. Covers: explicit-op
filters (unknown field AND unknown op -> typed error), eq vs in on list
fields, sort restriction to declared roles + ``_score``, cursor pagination +
total_matched (stale-index cursor rejected), abstention via derived
coverage/margin signals only, mode validation against declared strategies,
top_k capped by server max_top_k, get(record_id) provenance, generic CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_engine.config import _load_yaml, _parse_corpus
from kb_engine.core.contracts import RankedHit
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord
from kb_engine.serve import (
    ModeError,
    QueryParams,
    QueryParamsError,
    RecordStoreRequired,
    StaleCursorError,
    ServeConfig,
    get,
    parse_filters,
    parse_sort,
    serve,
)

FIXTURES = Path(__file__).parent / "fixtures" / "serve"
CORPUS_PATH = FIXTURES / "corpus.yaml"


# ---- helpers -----------------------------------------------------------------


def load_corpus(index_version: str | None = None):
    raw = _load_yaml(CORPUS_PATH)
    if index_version is not None:
        raw["index"]["schema_version"] = index_version
    return _parse_corpus("serve-test", CORPUS_PATH, raw)


def load_records() -> dict[str, CanonicalRecord]:
    raw = json.loads((FIXTURES / "records.json").read_text(encoding="utf-8"))["records"]
    return {
        item["id"]: CanonicalRecord(
            id=item["id"],
            content_hash=item["content_hash"],
            provenance=Provenance(**item["provenance"]),
            fields=item["fields"],
        )
        for item in raw
    }


class FakeRetriever:
    """Scripted retriever: yields the scripted hit list for any query,
    truncating to top_k (order + identity are the contract)."""

    def __init__(self, hits: list[RankedHit]) -> None:
        self.hits = hits
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    def search(self, query: str, top_k: int) -> list[RankedHit]:
        self.last_query = query
        self.last_top_k = top_k
        return list(self.hits[:top_k])


def all_hits() -> list[RankedHit]:
    """Deterministic hit list over every fixture record (best-first)."""
    return [
        RankedHit(record_id=f"r{i}", score=1.0 - i * 0.1)
        for i in range(1, 7)
    ]


def params(corpus, query="design", *, mode="", top_k=6, filters=None,
           sort=None, cursor=None) -> QueryParams:
    return QueryParams(
        query=query,
        corpus=corpus.name,
        mode=mode,
        top_k=top_k,
        cursor=cursor,
        filters=parse_filters(corpus, filters) if filters is not None else (),
        sort=parse_sort(corpus, sort) if sort is not None else (),
    )


# ---- explicit-op filters -----------------------------------------------------


def test_explicit_ops_and_shorthand():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())

    # Explicit in-op on a list facet: any-element overlap (unnest).
    res = serve(corpus, retriever, params(corpus, filters={
        "tools_apps": {"op": "in", "value": ["figma"]},
    }), records=records)
    assert [h.record_id for h in res.hits] == ["r1", "r2", "r6"]
    assert res.total_matched == 3

    # Shorthand list == in; scalar == eq.
    shorthand = serve(corpus, retriever, params(corpus, filters={
        "tools_apps": ["figma"], "owner": "alice",
    }), records=records)
    assert [h.record_id for h in shorthand.hits] == ["r1"]

    # Metric range ops.
    gte = serve(corpus, retriever, params(corpus, filters={
        "value_score": {"op": "gte", "value": 7},
    }), records=records)
    assert [h.record_id for h in gte.hits] == ["r1", "r2", "r5"]

    between = serve(corpus, retriever, params(corpus, filters={
        "value_score": {"op": "between", "value": [5, 7]},
    }), records=records)
    assert [h.record_id for h in between.hits] == ["r2", "r3", "r6"]


def test_eq_vs_in_on_list_field_distinguished():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())

    # in: field CONTAINS any of the values (r1 has figma+sketch).
    contains = serve(corpus, retriever, params(corpus, filters={
        "tools_apps": {"op": "in", "value": ["figma"]},
    }), records=records)
    assert [h.record_id for h in contains.hits] == ["r1", "r2", "r6"]

    # eq on a list field: WHOLE-LIST equality only — r1 (figma+sketch) and
    # r6 (figma+zeplin) do NOT equal ["figma"]; only r2 does.
    exact = serve(corpus, retriever, params(corpus, filters={
        "tools_apps": {"op": "eq", "value": ["figma"]},
    }), records=records)
    assert [h.record_id for h in exact.hits] == ["r2"]


def test_unknown_field_and_unknown_op_error():
    corpus = load_corpus()
    with pytest.raises(QueryParamsError, match="not declared"):
        parse_filters(corpus, {"nonsense_field": "x"})
    with pytest.raises(QueryParamsError, match="unknown op"):
        parse_filters(corpus, {"owner": {"op": "regex", "value": "a.*"}})


def test_op_role_compatibility_errors():
    corpus = load_corpus()
    # gte is metric-only: owner is a string filter/facet.
    with pytest.raises(QueryParamsError, match="op 'gte' is not valid"):
        parse_filters(corpus, {"owner": {"op": "gte", "value": "a"}})
    # eq on a role-less field is rejected.
    with pytest.raises(QueryParamsError, match="filter-capable role"):
        parse_filters(corpus, {"hidden": "secret"})
    # in requires a list value; eq rejects a list.
    with pytest.raises(QueryParamsError, match="'in' requires"):
        parse_filters(corpus, {"owner": {"op": "in", "value": "alice"}})
    with pytest.raises(QueryParamsError, match="scalar"):
        parse_filters(corpus, {"owner": {"op": "eq", "value": ["alice"]}})
    # between requires a numeric pair.
    with pytest.raises(QueryParamsError, match="between"):
        parse_filters(corpus, {"value_score": {"op": "between", "value": ["a", "b"]}})


def test_sort_restriction():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())
    res = serve(corpus, retriever, params(corpus, top_k=6, sort=[
        {"field": "value_score", "order": "desc"},
    ]), records=records)
    assert [h.record_id for h in res.hits] == ["r1", "r5", "r2", "r6", "r3", "r4"]
    assert [h.rank for h in res.hits] == [1, 2, 3, 4, 5, 6]

    # Role-less and undeclared fields are NOT sortable; _score is allowed.
    with pytest.raises(QueryParamsError, match="sorting requires"):
        parse_sort(corpus, [{"field": "hidden", "order": "asc"}])
    with pytest.raises(QueryParamsError, match="not declared"):
        parse_sort(corpus, [{"field": "nope", "order": "asc"}])
    ok = parse_sort(corpus, [{"field": "_score", "order": "desc"}])
    assert ok[0].field == "_score"
    with pytest.raises(QueryParamsError, match="order must be"):
        parse_sort(corpus, [{"field": "owner", "order": "sideways"}])

    by_score = serve(corpus, retriever, params(corpus, top_k=6, sort=[
        {"field": "_score", "order": "desc"},
    ]), records=records)
    assert [h.record_id for h in by_score.hits] == [h.record_id for h in all_hits()][:6]


def test_filters_or_sort_without_store_rejected():
    corpus = load_corpus()
    with pytest.raises(RecordStoreRequired):
        serve(corpus, FakeRetriever(all_hits()), params(corpus, filters={"owner": "alice"}))
    # No filters/sort: provenance-less serving still works, no abstention.
    res = serve(corpus, FakeRetriever(all_hits()), params(corpus))
    assert res.abstained is False
    assert res.hits[0].provenance.source == ""


# ---- cursor pagination + total_matched ---------------------------------------


def test_cursor_pagination_and_total_matched():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())
    p = params(corpus, filters={"value_score": {"op": "gte", "value": 3}}, top_k=2)

    page1 = serve(corpus, retriever, p, records=records)
    assert page1.total_matched == 6  # all fixture scores >= 3
    assert [h.record_id for h in page1.hits] == ["r1", "r2"]
    assert [h.rank for h in page1.hits] == [1, 2]
    assert page1.cursor is not None

    page2 = serve(corpus, retriever, params(
        corpus, filters={"value_score": {"op": "gte", "value": 3}}, top_k=2,
        cursor=page1.cursor,
    ), records=records)
    assert [h.record_id for h in page2.hits] == ["r3", "r4"]
    assert [h.rank for h in page2.hits] == [3, 4]
    assert page2.total_matched == 6
    assert page2.cursor is not None

    page3 = serve(corpus, retriever, params(
        corpus, filters={"value_score": {"op": "gte", "value": 3}}, top_k=2,
        cursor=page2.cursor,
    ), records=records)
    assert [h.record_id for h in page3.hits] == ["r5", "r6"]
    assert page3.cursor is None  # no more pages


def test_cursor_rejected_from_older_index_version():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())
    page1 = serve(corpus, retriever, params(corpus, top_k=2), records=records)
    assert page1.cursor is not None

    # Same query, but the index has since been rebuilt at a new version.
    newer = load_corpus(index_version="8")
    with pytest.raises(StaleCursorError, match="index version"):
        serve(newer, retriever, params(newer, top_k=2, cursor=page1.cursor),
              records=records)

    # Tampered/corrupt cursors are rejected too.
    with pytest.raises(StaleCursorError):
        serve(corpus, retriever, params(corpus, top_k=2, cursor=page1.cursor[:-2] + "zz"),
              records=records)

    # A cursor from a DIFFERENT query is rejected.
    with pytest.raises(StaleCursorError, match="query"):
        serve(corpus, retriever, params(corpus, query="other", top_k=2,
                                        cursor=page1.cursor), records=records)



def test_mode_validation_and_fallback():
    corpus = load_corpus()
    records = load_records()
    retriever = FakeRetriever(all_hits())

    with pytest.raises(ModeError, match="not a declared retrieval strategy"):
        serve(corpus, retriever, params(corpus, mode="vector-plus"), records=records)

    # Every declared strategy is accepted. (No filters: total_matched is the
    # candidate-window match count; max_top_k=10 covers all 6 records.)
    for mode in ("bm25", "dense", "hybrid"):
        res = serve(corpus, retriever, params(corpus, mode=mode), records=records)
        assert res.total_matched == 6

    # Empty mode falls back to serve.defaults.mode (dense here).
    res = serve(corpus, retriever, params(corpus, mode=""), records=records)
    assert res.total_matched == 6

def test_top_k_capped_by_server_policy():
    corpus = load_corpus()
    retriever = FakeRetriever(all_hits())
    cfg = ServeConfig.from_corpus(corpus)
    assert cfg.max_top_k == 10
    res = serve(corpus, retriever, params(corpus, top_k=999), records=load_records())
    assert len(res.hits) == 6  # only 6 records exist; cap is 10
    assert retriever.last_top_k == 10  # candidate window is the cap, never 999


# ---- abstention (derived signals only) ---------------------------------------


def test_abstention_coverage_and_margin():
    corpus = load_corpus()
    records = load_records()
    # r2 first: its search text ("onboarding checklist patterns for new
    # users") covers every content token of the test query.
    retriever = FakeRetriever([
        RankedHit(record_id="r2", score=0.9),
        RankedHit(record_id="r1", score=0.5),
    ])
    good = serve(corpus, retriever, params(corpus, query="onboarding checklist users"),
                 records=records)
    assert good.abstained is False
    assert good.abstention_detail["coverage"] == 1.0

    # Coverage failure: the query's content tokens are nowhere in the top
    # hit's search text -> insufficient_evidence.
    poor = serve(corpus, retriever, params(corpus, query="quantum blockchain toaster"),
                 records=records)
    assert poor.abstained is True
    assert poor.abstention_reason == "insufficient_evidence"
    assert poor.abstention_detail["coverage"] < 0.6

    # Margin failure: top-2 nearly as strong as top-1 -> abstain even though
    # coverage is complete (only the RELATIVE gap matters, not the scale).
    flat = FakeRetriever([
        RankedHit(record_id="r2", score=1.0),
        RankedHit(record_id="r1", score=0.999),
    ])
    tight = serve(corpus, flat, params(corpus, query="onboarding checklist users"),
                  records=records)
    assert tight.abstained is True
    assert tight.abstention_detail["margin"] < 0.15
    assert tight.abstention_detail["coverage"] == 1.0

    # No hits at all -> abstain.
    empty = serve(corpus, FakeRetriever([]), params(corpus, query="anything"), records=records)
    assert empty.abstained is True
    assert empty.abstention_reason == "insufficient_evidence"
    assert empty.total_matched == 0


def test_abstention_never_uses_raw_score():
    corpus = load_corpus()
    records = load_records()
    # r2 first (covers the query tokens). One retriever reports BM25-scale
    # (unbounded) scores, another cosine-scale — SAME ranked order and
    # same RELATIVE gap -> identical abstention, proving the decision is
    # scale-free (never a raw score).
    bm25_scale = FakeRetriever([
        RankedHit(record_id="r2", score=4821.5),
        RankedHit(record_id="r1", score=3616.125),  # 25% relative gap
    ])
    cosine_scale = FakeRetriever([
        RankedHit(record_id="r2", score=0.98),
        RankedHit(record_id="r1", score=0.735),     # same 25% relative gap
    ])
    a = serve(corpus, bm25_scale, params(corpus, query="onboarding checklist users"),
              records=records)
    b = serve(corpus, cosine_scale, params(corpus, query="onboarding checklist users"),
              records=records)
    assert a.abstained is False and b.abstained is False
    assert a.abstention_detail["coverage"] == b.abstention_detail["coverage"] == 1.0
    assert a.abstention_detail["margin"] == pytest.approx(b.abstention_detail["margin"])


# ---- get(record_id) ----------------------------------------------------------


def test_get_returns_record_with_provenance():
    records = load_records()
    got = get("r6", records)
    assert got is not None
    assert got.record_id == "r6"
    assert got.provenance.source == "src-c"
    assert got.provenance.media_ref == "m/6"
    assert got.provenance.extractor == "fake-model"
    assert got.provenance.confidence == pytest.approx(0.9)
    assert got.fields["tools_apps"] == ["figma", "zeplin"]
    assert get("missing", records) is None


# ---- generic CLI -------------------------------------------------------------


def test_cli_help_has_no_hardcoded_corpus_flags(capsys):
    from kb_engine.serve.cli import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    for banned in ("--tools", "--owner", "--gated", "--value-score"):
        assert banned not in help_text
    # --help path exits cleanly.
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


def test_cli_schema_and_error_envelopes(capsys):
    from kb_engine.serve.cli import main

    rc = main(["--schema", "--config", str(FIXTURES / "config.yaml"),
               "--corpus", "serve-test"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["corpus"] == "serve-test"
    assert out["fields"]["tools_apps"] == {"type": "list[string]",
                                           "roles": ["filter", "facet"]}

    # Unknown mode over the fixture config -> typed error envelope, exit 2.
    rc = main(["--search", "x", "--config", str(FIXTURES / "config.yaml"),
               "--corpus", "serve-test", "--mode", "magic"])
    captured = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "error" in captured

    # --params JSON with a bad filter -> clear error, exit 2.
    rc = main(["--search", "x", "--config", str(FIXTURES / "config.yaml"),
               "--corpus", "serve-test",
               "--params", json.dumps({"filters": {"nope": "v"}})])
    captured = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert "not declared" in captured["error"]
