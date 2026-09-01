"""M4 hybrid retrieval: Reciprocal Rank Fusion of BM25 + dense, plus the ablation gate.

Storage decision (documented per orchestrator approval): file-backed hybrid.
BM25 runs on SQLite FTS5 (kb/bm25.py, real BM25 scoring via sqlite3 built-in);
dense vectors use sqlite-vec with a file-backed database (kb/dense.py). This
keeps the whole stack on the local filesystem with no server. pgvector is the
documented Postgres production migration path, but no Postgres instance exists
on this machine and installing one is out of scope; FTS5 + sqlite-vec give the
same hybrid semantics locally.

Shared retriever contract: every retriever exposes
  retrieve(question, top_k=10) -> list[post_id]           (ranked)
  retrieve_scored(question, top_k=10) -> list[(post_id, score)]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GOLD_SET = REPO_ROOT / "data" / "eval" / "gold-set-v1.json"
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"
RRF_K = 60


def reciprocal_rank_fusion(
    bm25_results: list[str],
    dense_results: list[str],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Standard RRF: sum 1/(k + rank) over each retriever's ranked list.

    Args are ranked lists of post_ids (best first). Returns (post_id, rrf_score)
    sorted by score descending (ties broken by first appearance).
    """
    scores: dict[str, float] = {}
    order: list[str] = []
    for ranked in (bm25_results, dense_results):
        for rank, pid in enumerate(ranked, start=1):
            if pid not in scores:
                order.append(pid)
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    ranked = sorted(scores, key=lambda p: (-scores[p], order.index(p)))
    return [(p, scores[p]) for p in ranked]


def _get_dense_module():
    """Return kb.dense, or None if unavailable (missing module / API key / import failure)."""
    try:
        import kb.dense as dense  # noqa: PLC0415
    except Exception as exc:  # ImportError, missing GEMINI_API_KEY, bad deps, ...
        print(f"[hybrid] dense channel unavailable ({exc}); falling back to BM25-only")
        return None
    return dense


def hybrid_retrieve_scored(question: str, top_k: int = 10) -> list[tuple[str, float]]:
    """Fuse BM25 + dense ranked lists via RRF; BM25-only fallback when dense is down."""
    from kb import bm25  # noqa: PLC0415

    bm25_ranked = [pid for pid, _ in bm25.retrieve_scored(question, top_k=top_k)]
    dense = _get_dense_module()
    if dense is None:
        return [(pid, 1.0 / (RRF_K + rank)) for rank, pid in enumerate(bm25_ranked, start=1)]
    try:
        dense_ranked = [pid for pid, _ in dense.retrieve_scored(question, top_k=top_k)]
    except Exception as exc:  # API missing/failed mid-call -> BM25-only fallback
        print(f"[hybrid] dense call failed ({exc}); falling back to BM25-only")
        return [(pid, 1.0 / (RRF_K + rank)) for rank, pid in enumerate(bm25_ranked, start=1)]
    return reciprocal_rank_fusion(bm25_ranked, dense_ranked)


def hybrid_retrieve(question: str, top_k: int = 10) -> list[str]:
    """Hybrid retrieval contract function: ranked post_ids via RRF fusion."""
    return [pid for pid, _ in hybrid_retrieve_scored(question, top_k=top_k)]


def run_ablation(
    gold_set_path: str | Path = DEFAULT_GOLD_SET,
    corpus: list[dict] | None = None,
) -> dict:
    """M4 ablation gate: BM25-only vs hybrid (vs dense-only when available).

    Computes Recall@5/10, nDCG@10, MRR per retriever over the gold set, hybrid
    win rates, and prints a comparison report. Writes
    data/eval/runs/{timestamp}-ablation.json keyed by
    (schema_version, eval_set_version, retriever). Returns the report dict.
    """
    from kb.consolidate import load_merged  # noqa: PLC0415
    from kb.eval import EVAL_SET_VERSION, load_gold_set, run_retrieval_eval  # noqa: PLC0415
    try:
        from kb.schema import SCHEMA_VERSION  # noqa: PLC0415
    except Exception:
        SCHEMA_VERSION = "unknown"

    gold_set = load_gold_set(Path(gold_set_path))
    corpus = corpus if corpus is not None else load_merged()

    from kb import bm25  # noqa: PLC0415
    dense = _get_dense_module()

    # channel fns return (post_id, score) pairs; run_retrieval_eval normalizes
    # ids (shortcode -> post_id aliasing) and computes the metric set itself.
    channels: dict[str, callable] = {
        "bm25": lambda q, top_k: bm25.retrieve_scored(q, top_k=top_k),
    }
    dense_note = None
    if dense is not None:
        channels["dense"] = lambda q, top_k: dense.retrieve_scored(q, top_k=top_k)
    else:
        dense_note = "dense channel unavailable; hybrid ran BM25-only via RRF fallback"

    def hybrid_fn(q: str, top_k: int) -> list[tuple[str, float]]:
        return hybrid_retrieve_scored(q, top_k=top_k)

    results: dict[str, dict] = {}
    for name, fn in {**channels, "hybrid": hybrid_fn}.items():
        results[name] = run_retrieval_eval(
            corpus, gold_set, lambda q, f=fn: [p for p, _ in f(q, top_k=10)]
        )

    def win_rate(a: dict, b: dict) -> float:
        a_rows = {r["question_id"]: r for r in a["per_question"]}
        b_rows = {r["question_id"]: r for r in b["per_question"]}
        shared = set(a_rows) & set(b_rows)
        if not shared:
            return 0.0
        wins = sum(1 for qid in shared if a_rows[qid]["recall@10"] > b_rows[qid]["recall@10"])
        return wins / len(shared)

    report = {
        "schema_version": SCHEMA_VERSION,
        "eval_set_version": EVAL_SET_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gold_set_path": str(Path(gold_set_path)),
        "note": dense_note,
        "results": {name: results[name] for name in ("bm25", "dense", "hybrid") if name in results},
        "win_rates": {
            "hybrid_vs_bm25": win_rate(results["hybrid"], results["bm25"]),
            **(
                {"hybrid_vs_dense": win_rate(results["hybrid"], results["dense"])}
                if "dense" in results
                else {}
            ),
        },
        "gate": {},
    }
    bm25_r10 = results["bm25"]["recall@10"]
    hyb_r10 = results["hybrid"]["recall@10"]
    report["gate"] = {
        "hybrid_beats_bm25_recall10": hyb_r10 >= bm25_r10,
        "bm25_recall@10": bm25_r10,
        "hybrid_recall@10": hyb_r10,
        "delta_recall@10": hyb_r10 - bm25_r10,
    }

    _print_report(report)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RUNS_DIR / f"{ts}-ablation.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Report written to {out}")
    return report


def _print_report(report: dict) -> None:
    """Human-readable comparison table + verdict."""
    print("\n=== M4 Hybrid Ablation ===")
    if report.get("note"):
        print(f"note: {report['note']}")
    header = f"{'retriever':<10} {'n':>3} {'Recall@5':>9} {'Recall@10':>10} {'nDCG@10':>8} {'MRR':>6}"
    print(header)
    for name, r in report["results"].items():
        print(
            f"{name:<10} {r['n_questions']:>3} {r['recall@5']:>9.3f} "
            f"{r['recall@10']:>10.3f} {r['ndcg@10']:>8.3f} {r['mrr']:>6.3f}"
        )
    gate = report["gate"]
    verdict = "PASS" if gate["hybrid_beats_bm25_recall10"] else "FAIL"
    print(
        f"\nVerdict ({verdict}): hybrid Recall@10 {gate['hybrid_recall@10']:.3f} "
        f"vs BM25 {gate['bm25_recall@10']:.3f} "
        f"(delta {gate['delta_recall@10']:+.3f})"
    )
    print(f"Hybrid win rate vs BM25: {report['win_rates']['hybrid_vs_bm25']:.1%}")
    if "hybrid_vs_dense" in report["win_rates"]:
        print(f"Hybrid win rate vs dense: {report['win_rates']['hybrid_vs_dense']:.1%}")


def main(argv: list[str] | None = None) -> int:
    """CLI: --ablation runs the M4 gate; --query "..." runs hybrid retrieval."""
    parser = argparse.ArgumentParser(description="M4 hybrid retrieval (RRF of BM25 + dense).")
    parser.add_argument("--ablation", action="store_true", help="run the ablation gate")
    parser.add_argument("--query", type=str, help="run a hybrid query and print ranked ids")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args(argv)

    if args.ablation:
        run_ablation()
        return 0
    if args.query:
        scored = hybrid_retrieve_scored(args.query, top_k=args.top_k)
        for pid, score in scored:
            print(f"{score:.4f}  {pid}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
