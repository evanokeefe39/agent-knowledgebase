"""Numeric eval harness for the UI/UX knowledge base (M3).

Metrics: Recall@k, nDCG@k, MRR over a gold question set; abstention rate for
unanswerable questions. Run with::

    uv run python -m kb.eval --run         # full suite + report file
    uv run python -m kb.eval --gold-stats  # gold-set composition
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from kb.schema import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "data" / "uiux" / "kb-posts.json"
GOLD_SET_PATH = REPO_ROOT / "data" / "eval" / "gold-set-v1.json"
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"

EVAL_SET_VERSION = "v1"
TOP_K_RECALL = (5, 10)
NDCG_K = 10


# ---------------------------------------------------------------------------
# Loading


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    """Load the canonical KbPost corpus from kb-posts.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_gold_set(path: Path = GOLD_SET_PATH) -> list[dict[str, Any]]:
    """Load the gold question set."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Retrieval metrics


def recall_at_k(gold: list[str], retrieved_ids: list[str], k: int) -> float:
    """Fraction of gold post_ids present in the top-k retrieved ids.

    Empty gold sets score 1.0 (nothing to retrieve).
    """
    if not gold:
        return 1.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for g in gold if g in top_k)
    return hits / len(gold)


def ndcg_at_k(gold: list[str], retrieved: list[str], k: int) -> float:
    """Binary-relevance nDCG@k: gold ids are relevant, others are not."""
    if not gold:
        return 1.0
    gold_set = set(gold)
    rel = [1.0 if pid in gold_set else 0.0 for pid in retrieved[:k]]
    if not any(rel):
        return 0.0
    discounts = np.log2(np.arange(2, len(rel) + 2))
    dcg = float(np.sum(rel / discounts))
    ideal = sorted(rel, reverse=True)
    idcg = float(np.sum(np.array(ideal) / discounts))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(retrieved_list: list[str], gold: set[str] | list[str]) -> float:
    """Reciprocal rank of the first relevant id in retrieved_list; 0.0 if none."""
    gold_set = set(gold)
    for rank, pid in enumerate(retrieved_list, start=1):
        if pid in gold_set:
            return 1.0 / rank
    return 0.0


# ---------------------------------------------------------------------------
# Suite runners


def _normalize_retrieved(result: Any) -> list[str]:
    """Coerce a retriever result (ids or records/strings) to a list of post_ids."""
    if result is None:
        return []
    out: list[str] = []
    for item in result:
        if isinstance(item, dict):
            pid = item.get("post_id") or item.get("shortcode")
            if pid:
                out.append(str(pid))
        elif isinstance(item, str):
            out.append(item)
    return out


def run_retrieval_eval(
    corpus: list[dict[str, Any]],
    gold_set: list[dict[str, Any]],
    retriever_fn: Callable[[str], Any],
) -> dict[str, Any]:
    """Score retrieval metrics over the gold set.

    retriever_fn(question) -> list of post_ids (or records with post_id).
    Returns recall@5, recall@10, ndcg@10, mrr plus per-question details.
    """
    alias: dict[str, str] = {}  # post_id or shortcode -> canonical post_id
    for r in corpus:
        pid = str(r.get("post_id") or r.get("shortcode"))
        alias[pid] = pid
        if r.get("shortcode"):
            alias[str(r["shortcode"])] = pid
    rows: list[dict[str, Any]] = []
    recalls5: list[float] = []
    recalls10: list[float] = []
    ndcgs: list[float] = []
    mrrs: list[float] = []

    for q in gold_set:
        if q.get("mode") == "abstain":
            continue  # retrieval metrics apply to search/answer questions only
        gold_ids = [alias.get(g, g) for g in q["expected_post_ids"]]
        gold_set_ids = set(gold_ids)
        missing = [g for g in gold_ids if g not in alias.values()]
        retrieved = [alias.get(pid, pid) for pid in _normalize_retrieved(retriever_fn(q["question"]))]
        r5 = recall_at_k(gold_ids, retrieved, 5)
        r10 = recall_at_k(gold_ids, retrieved, 10)
        n10 = ndcg_at_k(gold_ids, retrieved, NDCG_K)
        m = mrr(retrieved, gold_set_ids)
        rows.append(
            {
                "question_id": q["question_id"],
                "mode": q["mode"],
                "difficulty": q.get("difficulty"),
                "retrieved_top5": retrieved[:5],
                "recall@5": r5,
                "recall@10": r10,
                "ndcg@10": n10,
                "mrr": m,
                "invalid_gold_ids": missing,
            }
        )
        recalls5.append(r5)
        recalls10.append(r10)
        ndcgs.append(n10)
        mrrs.append(m)

    n = len(rows)
    return {
        "recall@5": float(np.mean(recalls5)) if n else 0.0,
        "recall@10": float(np.mean(recalls10)) if n else 0.0,
        "ndcg@10": float(np.mean(ndcgs)) if n else 0.0,
        "mrr": float(np.mean(mrrs)) if n else 0.0,
        "n_questions": n,
        "per_question": rows,
    }


def abstention_rate(
    gold_set: list[dict[str, Any]], answer_fn: Callable[[str], Any]
) -> dict[str, Any]:
    """Fraction of mode=abstain questions where answer_fn abstains.

    answer_fn(question) may return a bool, or a dict containing an
    "abstained" key. Unanswerable-by-construction results count as abstained.
    """
    abstain_qs = [q for q in gold_set if q.get("mode") == "abstain"]
    if not abstain_qs:
        return {"abstention_rate": 0.0, "n_abstain_questions": 0, "per_question": []}
    rows = []
    hits = 0
    for q in abstain_qs:
        try:
            ans = answer_fn(q["question"])
        except Exception as exc:  # noqa: BLE001 - harness must not crash on an answer fn
            rows.append({"question_id": q["question_id"], "abstained": False, "error": str(exc)})
            continue
        if isinstance(ans, dict):
            abstained = bool(ans.get("abstained", False))
        elif ans is None:
            abstained = True
        else:
            abstained = bool(ans)
        rows.append({"question_id": q["question_id"], "abstained": abstained})
        hits += 1 if abstained else 0
    return {
        "abstention_rate": hits / len(abstain_qs),
        "n_abstain_questions": len(abstain_qs),
        "per_question": rows,
    }



def run_eval_suite(
    answer_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run the full eval: retrieval metrics via kb.query.search + abstention.

    Writes a timestamped report to data/eval/runs/{timestamp}.json keyed by
    (schema_version, eval_set_version) and returns the report dict.
    """
    from kb.query import search  # lazy: query module is a sibling deliverable

    corpus = load_corpus()
    gold_set = load_gold_set()

    def retriever(question: str) -> list[str]:
        return [str(r["post_id"]) for r in search(corpus, question, top_k=10)]

    retrieval = run_retrieval_eval(corpus, gold_set, retriever)
    if answer_fn is None:

        def answer_fn(question: str) -> dict[str, Any]:
            # Real pipeline: kb.query.answer over the loaded corpus (lazy
            # import to avoid circular dependency with kb.query).
            from kb.query import answer, load_corpus

            return answer(load_corpus(), question)

    abstain = abstention_rate(gold_set, answer_fn)

    report = {
        "schema_version": SCHEMA_VERSION,
        "eval_set_version": EVAL_SET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_size": len(corpus),
        "n_gold_questions": len(gold_set),
        "retrieval": {k: v for k, v in retrieval.items() if k != "per_question"},
        "abstention": {k: v for k, v in abstain.items() if k != "per_question"},
        "per_question": retrieval["per_question"],
        "abstention_detail": abstain["per_question"],
    }

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RUNS_DIR / f"{stamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    report["report_path"] = str(out_path)
    return report


def gold_stats(gold_set: list[dict[str, Any]]) -> str:
    """Human-readable gold-set composition: counts by mode/difficulty/domain."""
    from collections import Counter

    modes = Counter(q.get("mode") for q in gold_set)
    diffs = Counter(q.get("difficulty") for q in gold_set)
    domains = Counter(q.get("domain_hint") for q in gold_set)
    n_gold_ids = sum(len(q["expected_post_ids"]) for q in gold_set)
    lines = [
        f"Gold set: {len(gold_set)} questions, {n_gold_ids} expected post references",
        f"  modes:     {dict(modes)}",
        f"  difficulty:{dict(diffs)}",
        f"  domains:   {dict(domains)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: --run (full suite + report) or --gold-stats (composition)."""
    parser = argparse.ArgumentParser(description="KB numeric eval harness.")
    parser.add_argument("--run", action="store_true", help="run the eval suite and write a report")
    parser.add_argument("--gold-stats", action="store_true", help="print gold-set composition")
    args = parser.parse_args(argv)

    if not (args.run or args.gold_stats):
        parser.print_help()
        return 1

    if args.gold_stats:
        print(gold_stats(load_gold_set()))

    if args.run:
        report = run_eval_suite()
        r = report["retrieval"]
        a = report["abstention"]
        print(f"\nEval set: {report['eval_set_version']} | corpus: {report['corpus_size']} posts")
        print(f"  Recall@5:  {r['recall@5']:.3f}")
        print(f"  Recall@10: {r['recall@10']:.3f}")
        print(f"  nDCG@10:   {r['ndcg@10']:.3f}")
        print(f"  MRR:       {r['mrr']:.3f}")
        print(f"  Abstention rate: {a['abstention_rate']:.3f} ({a['n_abstain_questions']} abstain questions)")
        print(f"Report written: {report['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())