"""Regression tests for the parity-engine defects (docs/parity-report.md).

D2: evaluator.evaluate() must extract ``RankedHit.record_id`` from real
dataclass hits instead of str()-ing them (dataclass retrievers scored 0.0).
D1: the quality gate must map gold shortcodes onto canonical numeric record
ids via the declared ``shortcode`` schema field. Hermetic: no API/network.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "ci"))

from kb_engine.core.contracts import RankedHit  # noqa: E402
from kb_engine.core.provenance import Provenance  # noqa: E402
from kb_engine.core.records import CanonicalRecord  # noqa: E402
from kb_engine.verify.evaluator import EvalQuestion, evaluate  # noqa: E402
from quality_gate import build_id_map  # noqa: E402


class RankedHitRetriever:
    """Retriever returning real RankedHit objects (numeric canonical ids)."""

    def __init__(self, answers: dict[str, list[RankedHit]]):
        self.answers = answers

    def search(self, query: str, top_k: int) -> list[RankedHit]:
        return self.answers.get(query, [])[:top_k]


def q(qid: str, text: str, expected: list[str]) -> EvalQuestion:
    return EvalQuestion(question_id=qid, question=text, mode="search",
                        difficulty="easy", expected=expected)


def _rec(rid: str, shortcode: str) -> CanonicalRecord:
    return CanonicalRecord(
        id=rid, content_hash="h",
        provenance=Provenance(source="s", media_ref="m"),
        fields={"shortcode": shortcode},
    )


# ---- D2: dataclass RankedHit hits must score (non-zero) ----------------------


def test_evaluator_scores_real_ranked_hits():
    retriever = RankedHitRetriever({
        "find a": [
            RankedHit(record_id="1", score=0.9),
            RankedHit(record_id="2", score=0.5),
        ],
    })
    gold = [q("q1", "find a", ["1"])]
    run = evaluate(gold, retriever, corpus="t")
    assert run.metrics["recall@5"] == 1.0
    assert run.metrics["mrr"] == 1.0
    assert run.metrics["ndcg@10"] == 1.0


def test_evaluator_ranked_hit_rank_ordering_respected():
    retriever = RankedHitRetriever({
        "find a": [RankedHit(record_id="x", score=0.9),
                   RankedHit(record_id="1", score=0.4)],
    })
    run = evaluate([q("q1", "find a", ["1"])], RankedHitRetriever(
        retriever.answers), corpus="t")
    assert run.metrics["mrr"] == 0.5  # relevant at rank 2


def test_evaluator_still_accepts_plain_string_hits():
    class StrRetriever:
        def search(self, query: str, top_k: int) -> list[str]:
            return ["1", "x"]

    run = evaluate([q("q1", "find a", ["1"])], StrRetriever(), corpus="t")
    assert run.metrics["recall@5"] == 1.0


# ---- D1: shortcode gold over mixed numeric/shortcode-id corpus ---------------


def test_build_id_map_shortcodes_and_ids():
    records = [_rec("101", "sc-abc"), _rec("102", "sc-xyz")]
    id_map = build_id_map(records)
    assert id_map["sc-abc"] == "101"
    assert id_map["sc-xyz"] == "102"
    assert id_map["101"] == "101"  # raw numeric ids still resolve
    assert id_map["102"] == "102"


def test_gold_shortcodes_score_over_numeric_id_corpus():
    # Gold references shortcodes; the retriever returns numeric canonical ids.
    retriever = RankedHitRetriever({
        "find a": [RankedHit(record_id="999", score=0.9),
                   RankedHit(record_id="101", score=0.5)],
        "find b": [RankedHit(record_id="102", score=0.9)],
    })
    gold = [q("q1", "find a", ["sc-abc"]), q("q2", "find b", ["sc-xyz"])]
    id_map = build_id_map([_rec("101", "sc-abc"), _rec("102", "sc-xyz")])
    run = evaluate(gold, retriever, corpus="t", id_map=id_map)
    assert run.metrics["recall@5"] == 1.0
    assert run.metrics["recall@10"] == 1.0
    # q1: relevant at rank 2 -> 0.5; q2: rank 1 -> 1.0
    assert run.metrics["mrr"] == 0.75


def test_gold_numeric_ids_unaffected_by_id_map():
    retriever = RankedHitRetriever({
        "find a": [RankedHit(record_id="101", score=0.9)],
    })
    id_map = build_id_map([_rec("101", "sc-abc")])
    run = evaluate([q("q1", "find a", ["101"])], retriever,
                   corpus="t", id_map=id_map)
    assert run.metrics["recall@5"] == 1.0
