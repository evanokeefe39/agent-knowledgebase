"""Verify stage tests (Build-6, plan §6.4/§9). Hermetic: no API, no network;
the retriever is a hand-built fake; baselines/reports go to tmp_path."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kb_engine.verify.baseline import load_baseline, make_baseline, write_baseline
from kb_engine.verify.evaluator import (
    EvalQuestion,
    evaluate,
    load_gold_set,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from kb_engine.verify.gate import FourCorner, run_gate

FIXTURES = Path(__file__).parent / "fixtures" / "verify"


class FakeRetriever:
    """Deterministic injected retriever: query -> fixed ranked ids."""

    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers

    def search(self, query: str, top_k: int) -> list[str]:
        return self.answers.get(query, [])[:top_k]


def q(qid: str, text: str, expected: list[str], mode: str = "search") -> EvalQuestion:
    return EvalQuestion(question_id=qid, question=text, mode=mode, difficulty="easy",
                        expected=expected)


# ---- Metrics: hand-checked tiny case ----------------------------------------

RANKED = ["d", "a", "e", "b", "f", "g", "h", "i", "j", "k"]
EXPECTED = ["a", "b", "c"]


def test_recall_at_k():
    # a at rank 2, b at rank 4, c missed -> 2/3 in top 5 and top 10
    assert recall_at_k(RANKED, EXPECTED, 5) == pytest.approx(2 / 3)
    assert recall_at_k(RANKED, EXPECTED, 10) == pytest.approx(2 / 3)
    assert recall_at_k(["z"], EXPECTED, 5) == 0.0


def test_ndcg_at_10_hand_checked():
    # relevant at ranks 2 and 4 (binary): DCG = 1/log2(3) + 1/log2(5)
    # IDCG (3 expected, k=10) = 1 + 1/log2(3) + 1/log2(4)
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(RANKED, EXPECTED, 10) == pytest.approx(dcg / idcg)
    assert ndcg_at_k(["a", "b", "c"], EXPECTED, 10) == pytest.approx(1.0)


def test_mrr():
    assert mrr(RANKED, EXPECTED) == pytest.approx(0.5)
    assert mrr(["c", "a"], EXPECTED) == pytest.approx(1.0)
    assert mrr(["x", "y"], EXPECTED) == 0.0


# ---- Evaluator ----------------------------------------------------------------


def test_evaluate_search_abstain_answer(tmp_path):
    gold = [
        q("q1", "find a", ["a"]),
        q("q2", "find b", ["b", "c"]),
        q("q3", "junk query", [], mode="abstain"),
        q("q4", "opinion question", [], mode="answer"),
    ]
    retriever = FakeRetriever({
        "find a": ["a", "x", "y", "z", "w"],
        "find b": ["b", "x", "y", "z", "w", "v", "u", "t", "s", "c"],
        "junk query": [],
        "opinion question": ["a"],  # answer mode is NEVER forced to miss
    })
    run = evaluate(gold, retriever, corpus="test")
    # aggregates span search questions only (q3 abstain, q4 answer excluded)
    assert run.metrics["recall@5"] == pytest.approx((1.0 + 0.5) / 2)
    # q2: b at rank 1, c at rank 10
    q2_ndcg = (1 + 1 / math.log2(11)) / (1 + 1 / math.log2(3))
    assert run.metrics["ndcg@10"] == pytest.approx((1.0 + q2_ndcg) / 2)
    # abstention rate: 1 of 1 abstain question returned nothing
    assert run.abstention_rate == pytest.approx(1.0)
    by_id = {r.question_id: r for r in run.per_question}
    assert by_id["q3"].abstained is True
    assert by_id["q4"].scored is False
    assert by_id["q1"].scored is True


def test_load_gold_set_fixture_modes():
    gold = load_gold_set(FIXTURES / "gold-mini.json")
    assert {g.mode for g in gold} == {"search", "abstain", "answer"}
    assert gold[0].expected == ["a", "b"]


def test_id_map_normalizes_shortcodes():
    gold = [q("q1", "find a", ["SC-1"])]
    retriever = FakeRetriever({"find a": ["rec-1"]})
    run = evaluate(gold, retriever, id_map={"SC-1": "rec-1"})
    assert run.metrics["recall@5"] == 1.0


# ---- Baseline -----------------------------------------------------------------

BASELINE_KW = dict(
    index_version="1",
    eval_set_version="v1",
    embedder_version={"provider": "gemini", "model": "gemini-embedding-001", "dims": 3072},
    corpus="uiux",
    metrics={"recall@5": 0.9722222222222222, "recall@10": 1.0,
             "ndcg@10": 0.9306082922090443, "mrr": 0.9305555555555555},
)


def test_baseline_roundtrip(tmp_path):
    b = make_baseline(**BASELINE_KW)
    p = write_baseline(b, tmp_path / "baselines" / "uiux-baseline.json")
    loaded = load_baseline(p)
    assert loaded.four_corner() == b.four_corner()
    assert loaded.metrics == b.metrics
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1"
    assert raw["embedder_version"]["dims"] == 3072


def test_baseline_missing_metric_rejected(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"schema_version": "1", "index_version": "1",
                             "eval_set_version": "v1",
                             "embedder_version": {"provider": "g", "model": "m", "dims": 3},
                             "corpus": "x", "metrics": {"recall@5": 1.0},
                             "generated_at": "now"}), encoding="utf-8")
    with pytest.raises(ValueError, match="metrics missing"):
        load_baseline(p)


# ---- Gate ---------------------------------------------------------------------


def corner(**overrides) -> FourCorner:
    kw = dict(schema_version="1", index_version="1", eval_set_version="v1",
              embedder_version={"provider": "gemini", "model": "gemini-embedding-001",
                                "dims": 3072})
    kw.update(overrides)
    return FourCorner(**kw)


def make_test_baseline():
    return make_baseline(**BASELINE_KW)


def test_gate_pass_within_tolerance(tmp_path):
    b = make_test_baseline()
    metrics = {k: v - 0.01 for k, v in b.metrics.items()}  # within 0.02 tolerance
    result = run_gate(corner(), metrics, b, baseline_path="b.json")
    assert result.decision == "pass"
    assert set(result.per_metric) == {"recall@5", "recall@10", "ndcg@10", "mrr"}
    assert result.per_metric["recall@5"]["delta"] == pytest.approx(-0.01)


def test_gate_fail_on_regression(tmp_path):
    b = make_test_baseline()
    metrics = dict(b.metrics)
    metrics["recall@5"] = b.metrics["recall@5"] - 0.05  # drop > 0.02
    result = run_gate(corner(), metrics, b)
    assert result.decision == "fail"
    assert "recall@5" in result.reason
    # other metrics reported with deltas even when failing
    assert result.per_metric["mrr"]["delta"] == pytest.approx(0.0)


def test_gate_abort_on_tuple_mismatch(tmp_path):
    b = make_test_baseline()
    ok_metrics = dict(b.metrics)
    # embedder drift: corpus config declares 002/768, baseline is 001/3072
    result = run_gate(corner(embedder_version={"provider": "gemini",
                                               "model": "gemini-embedding-2", "dims": 768}),
                      ok_metrics, b)
    assert result.decision == "abort"
    assert result.per_metric == {}  # NEVER compares across tuples
    # index-version drift also aborts
    result = run_gate(corner(index_version="2"), ok_metrics, b)
    assert result.decision == "abort"
    assert "index_version" in result.reason


def test_gate_report_writing(tmp_path):
    # committed baseline -> gate -> report file on disk
    b = make_test_baseline()
    bp = write_baseline(b, tmp_path / "b.json")
    assert load_baseline(bp).metrics == b.metrics
    result = run_gate(corner(), dict(b.metrics), b, baseline_path=str(bp))
    report = {"report": "quality-gate", "gate": result.to_dict(),
              "generated_at": "2026-09-05T00:00:00+00:00"}
    out = tmp_path / "artifacts" / "verify"
    out.mkdir(parents=True)
    (out / "gate.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    loaded = json.loads((out / "gate.json").read_text(encoding="utf-8"))
    assert loaded["gate"]["decision"] == "pass"
    assert loaded["gate"]["baseline_path"] == str(bp)
