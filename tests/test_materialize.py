"""Build-5 materializer tests (docs/productization-build.md, Build-5 story).

Hermetic: no network, no live corpus state — fixtures under
tests/fixtures/materialize/ mirror the uiux declared fields but are
self-contained. Freshness is exercised with injected clocks, never sleeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kb_engine.config import load
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord
from kb_engine.materialize import (
    FilterError,
    MaterializeError,
    StaleViewError,
    ViewConfigError,
    ViewManager,
    View,
    materialize,
    parse_views,
)

FIXTURES = Path(__file__).parent / "fixtures" / "materialize"
T0 = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)


def _corpus():
    cfg = load(FIXTURES / "config.yaml")
    assert cfg.errors == {}, cfg.errors
    return cfg.corpus("materialize-corpus")


def _rec(
    rid: str,
    owner: str,
    *,
    value_score: int | None = 7,
    is_educational: bool = True,
    extraction_status: str = "ok",
    tools: list[str] | None = None,
    domains: list[str] | None = None,
    content_type: str = "reel",
) -> CanonicalRecord:
    return CanonicalRecord(
        id=rid,
        content_hash=f"hash-{rid}",
        provenance=Provenance(
            source="scrape-ig-saved-list",
            media_ref=f"ds/{rid}",
            timestamp="2026-09-01T00:00:00+00:00",
        ),
        fields={
            "post_id": rid,
            "owner": owner,
            "content_type": content_type,
            "value_score": value_score,
            "is_educational": is_educational,
            "extraction_status": extraction_status,
            "tools_apps": tools or [],
            "domains": domains or [],
            "summary": f"summary {rid}",
        },
    )


def _records() -> list[CanonicalRecord]:
    return [
        _rec("r1", "alice", value_score=8, tools=["Figma", "Sketch"],
             domains=["usability"]),
        _rec("r2", "alice", value_score=6, is_educational=False,
             tools=["Figma"], domains=["usability", "visual"]),
        _rec("r3", "bob", value_score=10, tools=["Figma", "Blender"],
             extraction_status="pending"),
        _rec("r4", "carol", value_score=9, tools=[], content_type="carousel"),
    ]


def _views() -> dict[str, View]:
    return {v.name: v for v in parse_views(_corpus())}


def _clock_at(state: dict):
    def clock() -> datetime:
        return state["now"]

    return clock


# ---- Parsing / fail-fast validation ------------------------------------------


def test_views_parse_from_corpus_declaration():
    views = _views()
    assert set(views) == {
        "top_creators", "tools", "by_domain", "by_owner_and_type",
        "seeded_owners", "high_value_owners",
    }
    tc = views["top_creators"]
    assert tc.group_by == ("owner",)
    assert [m.name for m in tc.metrics] == [
        "post_count", "avg_value_score", "educational_share"
    ]
    assert tc.freshness == timedelta(hours=24)
    assert tc.schema_version == "1"


def test_corpus_without_materialize_block_declares_no_views(tmp_path):
    (tmp_path / "corpora").mkdir()
    (tmp_path / "corpora" / "bare.yaml").write_text(
        "schema:\n  schema_version: '1'\n  id_field: post_id\n"
        "  fields:\n    post_id: { type: string }\n"
        "    owner: { type: string, role: [facet] }\n"
        "sources: []\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        "engine:\n  corpora_dir: corpora\n", encoding="utf-8"
    )
    corpus = load(tmp_path / "config.yaml").corpus("bare")
    assert parse_views(corpus) == []


def test_mean_over_non_aggregable_field_fails_fast():
    corpus = _corpus()
    views = corpus.raw["materialize"]["views"]

    # malformed metric spec string
    views.append({"name": "bad", "group_by": ["owner"],
                  "metrics": [{"x": "mean(summary"}], "freshness": "1h"})
    with pytest.raises(ViewConfigError, match="invalid|mean"):
        parse_views(corpus)
    views.pop()

    # mean over a text field -> fail fast
    views.append({"name": "bad", "group_by": ["owner"],
                  "metrics": [{"x": "mean(summary)"}], "freshness": "1h"})
    with pytest.raises(ViewConfigError, match="not aggregable"):
        parse_views(corpus)
    views.pop()

    # mean over an undeclared field -> fail fast
    views.append({"name": "bad", "group_by": ["owner"],
                  "metrics": [{"x": "mean(no_such_field)"}], "freshness": "1h"})
    with pytest.raises(ViewConfigError, match="undeclared"):
        parse_views(corpus)
    views.pop()


def test_group_by_non_facet_field_fails_fast():
    corpus = _corpus()
    corpus.raw["materialize"]["views"].append(
        {"name": "bad", "group_by": ["value_score"],
         "metrics": [{"n": "count"}], "freshness": "1h"}
    )
    with pytest.raises(ViewConfigError, match="lacks role 'facet'"):
        parse_views(corpus)


def test_unknown_filter_op_fails_fast():
    corpus = _corpus()
    corpus.raw["materialize"]["views"].append(
        {"name": "bad", "group_by": ["owner"],
         "metrics": [{"n": "count"}],
         "filters": {"owner": {"op": "regex", "value": "x"}},
         "freshness": "1h"}
    )
    with pytest.raises(ViewConfigError, match="op.*unknown"):
        parse_views(corpus)


# ---- Group-by / count / avg ----------------------------------------------------


def test_group_by_count_and_avg_correct():
    rows = materialize(_views()["top_creators"], _records(), now=T0)
    by_owner = {r["owner"]: r for r in rows}
    # r3 is filtered out (extraction_status=pending)
    assert by_owner["alice"]["post_count"] == 2
    assert by_owner["alice"]["avg_value_score"] == 7.0
    assert by_owner["carol"]["post_count"] == 1
    assert by_owner["carol"]["avg_value_score"] == 9.0
    assert "bob" not in by_owner
    # deterministic order: sorted by group key
    assert [r["owner"] for r in rows] == ["alice", "carol"]


def test_multi_field_group_by():
    rows = materialize(_views()["by_owner_and_type"], _records(), now=T0)
    keys = {(r["owner"], r["content_type"]) for r in rows}
    # no filters on this view: bob (reel, pending) is included
    assert keys == {("alice", "reel"), ("bob", "reel"), ("carol", "carousel")}

# ---- List facet unnest ---------------------------------------------------------


def test_list_facet_unnests_per_value():
    rows = materialize(_views()["tools"], _records(), now=T0)
    counts = {r["tools_apps"]: r["post_count"] for r in rows}
    # r1: Figma+Sketch, r2: Figma, r3: Figma+Blender — all counted (no filter
    # on this view); r4 has empty tools -> contributes one None-keyed row.
    assert counts == {"Figma": 3, "Sketch": 1, "Blender": 1, None: 1}


def test_mean_bool_is_share():
    rows = materialize(_views()["top_creators"], _records(), now=T0)
    alice = next(r for r in rows if r["owner"] == "alice")
    # r1 educational=True, r2 educational=False -> share 0.5
    assert alice["educational_share"] == 0.5


# ---- Filters -------------------------------------------------------------------


def test_filter_gte_applied():
    rows = materialize(_views()["high_value_owners"], _records(), now=T0)
    counts = {r["owner"]: r["post_count"] for r in rows}
    # value_score >= 8: r1(8), r3(10), r4(9) — no status filter on this view
    assert counts == {"alice": 1, "bob": 1, "carol": 1}


def test_filter_shorthand_scalar_is_eq_list_is_in():
    base = _views()["top_creators"]

    # scalar shorthand -> eq
    v = View(name="v", corpus=base.corpus, group_by=("owner",),
             metrics=base.metrics, filters={"extraction_status": "ok"},
             freshness=base.freshness)
    rows = materialize(v, _records(), now=T0)
    assert {r["owner"] for r in rows} == {"alice", "carol"}

    # list shorthand -> in
    v2 = View(name="v2", corpus=base.corpus, group_by=("owner",),
              metrics=base.metrics, filters={"owner": ["alice", "bob"]},
              freshness=base.freshness)
    rows2 = materialize(v2, _records(), now=T0)
    assert {r["owner"] for r in rows2} == {"alice", "bob"}


def test_unknown_filter_field_clear_error_at_materialize():
    base = _views()["top_creators"]
    view = View(name="badfield", corpus=base.corpus, group_by=("owner",),
                metrics=(), filters={"not_a_field": "x"},
                freshness=timedelta(hours=1))
    with pytest.raises(FilterError, match="undeclared field 'not_a_field'"):
        materialize(view, _records(), now=T0)


def test_unknown_filter_op_clear_error_at_materialize():
    base = _views()["top_creators"]
    view = View(name="badop", corpus=base.corpus, group_by=("owner",),
                metrics=(),
                filters={"owner": {"op": "contains", "value": "a"}},
                freshness=timedelta(hours=1))
    with pytest.raises(FilterError, match="op 'contains' unknown"):
        materialize(view, _records(), now=T0)


# ---- Empty groups --------------------------------------------------------------


def test_empty_group_emits_zero_count_row():
    rows = materialize(_views()["seeded_owners"], _records(), now=T0)
    counts = {r["owner"]: r["post_count"] for r in rows}
    # ghost_owner matches no record -> zero-count row, never absent
    assert counts == {"alice": 2, "ghost_owner": 0}
    ghost = next(r for r in rows if r["owner"] == "ghost_owner")
    assert ghost["provenance"] == []
    assert ghost.get("avg_value_score") is None


def test_no_records_yields_no_rows_for_unseeded_view():
    assert materialize(_views()["tools"], [], now=T0) == []


# ---- Row envelope: provenance + materialized_at + schema_version ---------------


def test_rows_carry_provenance_materialized_at_schema_version():
    rows = materialize(_views()["top_creators"], _records(), now=T0)
    alice = next(r for r in rows if r["owner"] == "alice")
    assert alice["materialized_at"] == T0.isoformat()
    assert alice["schema_version"] == "1"
    prov = alice["provenance"]
    assert [p["record_id"] for p in prov] == ["r1", "r2"]
    assert all(p["source"] == "scrape-ig-saved-list" for p in prov)
    assert prov[0]["media_ref"] == "ds/r1"
    assert prov[0]["timestamp"] == "2026-09-01T00:00:00+00:00"


def test_field_bag_records_accepted():
    bag = {
        "id": "b1",
        "provenance": {"source": "manual", "media_ref": "", "timestamp": None},
        "owner": "dave",
        "extraction_status": "ok",
        "value_score": 5,
        "is_educational": True,
    }
    rows = materialize(_views()["top_creators"], [bag], now=T0)
    assert rows[0]["post_count"] == 1
    assert rows[0]["provenance"][0] == {
        "record_id": "b1", "source": "manual", "media_ref": "", "timestamp": None,
    }


def test_bad_record_type_is_explicit_error():
    with pytest.raises(MaterializeError, match="neither a CanonicalRecord"):
        materialize(_views()["tools"], ["not-a-record"], now=T0)


# ---- Manager: freshness / serve / refresh --------------------------------------


def test_manager_serves_fresh_view():
    state = {"now": T0}
    mgr = ViewManager(_corpus(), _records(), clock=_clock_at(state))
    rows = mgr.serve("top_creators")
    assert {r["owner"] for r in rows} == {"alice", "carol"}
    state["now"] = T0 + timedelta(hours=23)
    assert mgr.serve("top_creators") is not None


def test_stale_view_refuses_to_serve_until_refresh():
    state = {"now": T0}
    mgr = ViewManager(_corpus(), _records(), clock=_clock_at(state))
    assert mgr.serve("top_creators")
    state["now"] = T0 + timedelta(hours=25)
    with pytest.raises(StaleViewError, match="stale.*refresh required"):
        mgr.serve("top_creators")
    # refresh() clears staleness (records default to the last-refreshed set)
    new_rows = mgr.refresh()
    assert all(
        r["materialized_at"] == state["now"].isoformat() for r in new_rows
    )
    assert mgr.serve("top_creators")


def test_never_materialized_view_refuses():
    mgr = ViewManager(_corpus())
    with pytest.raises(StaleViewError, match="never been materialized"):
        mgr.serve("top_creators")


def test_per_view_freshness_override():
    corpus = _corpus()
    corpus.raw["materialize"]["views"].append(
        {"name": "twitchy", "group_by": ["owner"], "metrics": [{"n": "count"}],
         "freshness": "30m"}
    )
    state = {"now": T0}
    mgr = ViewManager(corpus, _records(), clock=_clock_at(state))
    mgr.refresh()
    state["now"] = T0 + timedelta(minutes=31)
    with pytest.raises(StaleViewError):
        mgr.serve("twitchy")
    # corpus-default view still fresh at 31m
    assert mgr.serve("top_creators")


def test_refresh_unknown_view_is_keyerror():
    state = {"now": T0}
    mgr = ViewManager(_corpus(), _records(), clock=_clock_at(state))
    with pytest.raises(KeyError, match="not declared"):
        mgr.refresh(view="nope")
