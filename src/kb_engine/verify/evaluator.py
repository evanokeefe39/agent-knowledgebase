"""Evaluator (plan §6.4): run a gold set against a retriever.

Computes Recall@5/10, nDCG@10 (binary relevance) and MRR per question plus
aggregates. Gold modes (SHARED schema):

* ``search``   — scored into the retrieval metric aggregates.
* ``abstain``  — retrieval should return nothing; the abstention rate is
  REPORT-ONLY in v1 (never gated).
* ``answer``   — unanswerable-by-retrieval; recorded but excluded from the
  metric aggregates (never forced to score a retrieval miss).

Hermetic by construction: the retriever is injected (protocol-compatible with
``kb_engine.core.contracts.Retriever`` — ``search(query, top_k) -> hits``);
scoring makes no API calls.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

TOP_K = 10  # recall@5/@10 + nDCG@10 are all computed within the top 10

GOLD_MODES = ("search", "abstain", "answer")


@runtime_checkable
class SearchFn(Protocol):
    """Minimal retrieval surface the evaluator depends on (DIP)."""

    def search(self, query: str, top_k: int) -> list[Any]: ...


# ---- Metrics ----------------------------------------------------------------


def recall_at_k(ranked_ids: list[str], expected: list[str], k: int) -> float:
    """Fraction of expected ids present in the top ``k`` ranked ids."""
    if not expected:
        return 0.0
    hits = set(ranked_ids[:k]) & set(expected)
    return len(hits) / len(expected)


def ndcg_at_k(ranked_ids: list[str], expected: list[str], k: int) -> float:
    """Binary-relevance nDCG@k."""
    if not expected:
        return 0.0
    relevant = set(expected)
    dcg = sum(
        1.0 / math.log2(pos + 2)
        for pos, rid in enumerate(ranked_ids[:k])
        if rid in relevant
    )
    ideal = [1.0] * min(len(expected), k)
    idcg = sum(rel / math.log2(pos + 2) for pos, rel in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def mrr(ranked_ids: list[str], expected: list[str]) -> float:
    """Reciprocal rank of the first relevant id (0.0 when none found)."""
    relevant = set(expected)
    for pos, rid in enumerate(ranked_ids):
        if rid in relevant:
            return 1.0 / (pos + 1)
    return 0.0


# ---- Gold set ---------------------------------------------------------------


@dataclass(frozen=True)
class EvalQuestion:
    """One gold question (SHARED schema: ids may be shortcodes or record ids)."""

    question_id: str
    question: str
    mode: str
    difficulty: str
    expected: list[str]


def load_gold_set(path: str | Path) -> list[EvalQuestion]:
    """Load a gold set file. ``expected_post_ids``/``expected`` = shortcodes-or-ids."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"gold set must be a JSON array: {path}")
    out: list[EvalQuestion] = []
    for item in raw:
        mode = item.get("mode", "search")
        if mode not in GOLD_MODES:
            raise ValueError(f"question {item.get('question_id')!r}: unknown mode {mode!r}")
        expected = item.get("expected", item.get("expected_post_ids", []))
        out.append(
            EvalQuestion(
                question_id=str(item["question_id"]),
                question=str(item["question"]),
                mode=mode,
                difficulty=str(item.get("difficulty", "medium")),
                expected=[str(e) for e in expected],
            )
        )
    return out


# ---- Evaluation -------------------------------------------------------------


@dataclass
class QuestionResult:
    question_id: str
    mode: str
    ranked_ids: list[str]
    expected: list[str]
    recall_at_5: float
    recall_at_10: float
    ndcg_at_10: float
    mrr: float
    abstained: bool
    scored: bool  # False for mode=answer (excluded from aggregates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "mode": self.mode,
            "expected": self.expected,
            "ranked_ids": self.ranked_ids,
            "recall@5": self.recall_at_5,
            "recall@10": self.recall_at_10,
            "ndcg@10": self.ndcg_at_10,
            "mrr": self.mrr,
            "abstained": self.abstained,
            "scored": self.scored,
        }


@dataclass
class EvalRun:
    corpus: str
    per_question: list[QuestionResult] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    abstention_rate: float | None = None  # report-only; None when no abstain qs

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "questions": len(self.per_question),
            "metrics": dict(self.metrics),
            "abstention_rate": self.abstention_rate,
            "per_question": [q.to_dict() for q in self.per_question],
        }


def _hit_id(hit: Any) -> str:
    """Extract the record identity from a ranked hit (RankedHit or plain str)."""
    if isinstance(hit, str):
        return hit
    return str(getattr(hit, "record_id", hit))


def evaluate(
    gold: list[EvalQuestion],
    retriever: SearchFn,
    *,
    corpus: str = "",
    top_k: int = TOP_K,
    id_map: Mapping[str, str] | None = None,
) -> EvalRun:
    """Run the gold set through ``retriever`` and compute per-question + aggregate
    metrics. ``id_map`` optionally normalizes gold ids (e.g. shortcodes) to
    retriever record ids; matching falls back to the raw id when unmapped.

    Aggregates span ``search`` questions only; ``abstain`` feeds the
    report-only abstention rate; ``answer`` is recorded unscored."""
    run = EvalRun(corpus=corpus)
    abstinents = 0
    abstained_count = 0
    for q in gold:
        ranked = [_hit_id(h) for h in retriever.search(q.question, top_k)]
        expected = [
            id_map.get(e, e) if id_map is not None else e for e in q.expected
        ]
        scored = q.mode == "search"
        abstained = q.mode == "abstain" and not ranked
        if q.mode == "abstain":
            abstinents += 1
            abstained_count += int(abstained)
        run.per_question.append(
            QuestionResult(
                question_id=q.question_id,
                mode=q.mode,
                ranked_ids=ranked,
                expected=expected,
                recall_at_5=recall_at_k(ranked, expected, 5),
                recall_at_10=recall_at_k(ranked, expected, 10),
                ndcg_at_10=ndcg_at_k(ranked, expected, 10),
                mrr=mrr(ranked, expected),
                abstained=abstained,
                scored=scored,
            )
        )
    scored_results = [q for q in run.per_question if q.scored]
    if scored_results:
        n = len(scored_results)
        run.metrics = {
            "recall@5": sum(q.recall_at_5 for q in scored_results) / n,
            "recall@10": sum(q.recall_at_10 for q in scored_results) / n,
            "ndcg@10": sum(q.ndcg_at_10 for q in scored_results) / n,
            "mrr": sum(q.mrr for q in scored_results) / n,
        }
    run.abstention_rate = (
        abstained_count / abstinents if abstinents else None
    )
    return run
