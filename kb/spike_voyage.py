"""Voyage vs Gemini-dense text-parity spike (issue #3, phase B).

Assumes data/kb/dense-voyage.db exists (built via
`uv run python -m kb.dense --build --provider voyage`). Runs the gold-set
retrieval eval for the Voyage dense channel and writes
data/eval/runs/{timestamp}-voyage-spike.json with the M4 Gemini-dense
baseline side by side.

Usage: uv run python -m kb.spike_voyage
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kb.dense import retrieve
from kb.eval import load_corpus, load_gold_set, run_retrieval_eval
from kb.schema import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"
BASELINE_PATH = RUNS_DIR / "20260901-170237-ablation.json"
BASELINE_DB = "data/kb/dense.db"
VOYAGE_DB = REPO_ROOT / "data" / "kb" / "dense-voyage.db"


def main() -> int:
    if not VOYAGE_DB.exists():
        raise SystemExit(f"missing voyage index: {VOYAGE_DB}; run kb.dense --build --provider voyage first")

    corpus = load_corpus()
    gold_set = load_gold_set()
    voyage = run_retrieval_eval(corpus, gold_set, lambda q: retrieve(q, top_k=10, provider_name="voyage"))

    with open(BASELINE_PATH, encoding="utf-8") as f:
        baseline = json.load(f)
    gemini = baseline["results"]["dense"]
    gemini_metrics = {k: gemini[k] for k in ("recall@5", "recall@10", "ndcg@10", "mrr", "n_questions")}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    keys = ("recall@5", "recall@10", "ndcg@10", "mrr")
    report = {
        "schema_version": SCHEMA_VERSION,
        "eval_set_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spike": "voyage-vs-gemini-text-parity",
        "providers": {
            "voyage": {
                "model": "voyage-3",
                "db": "data/kb/dense-voyage.db",
                "metrics": {k: voyage[k] for k in (*keys, "n_questions")},
            },
            "gemini-dense": {
                "model": "gemini",
                "db": BASELINE_DB,
                "baseline_run": BASELINE_PATH.name,
                "metrics": gemini_metrics,
            },
        },
        "winner": {
            k: ("voyage" if voyage[k] > gemini[k] else "gemini-dense" if gemini[k] > voyage[k] else "tie")
            for k in keys
        },
        "per_question": voyage["per_question"],
    }
    out = RUNS_DIR / f"{ts}-voyage-spike.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"report: {out.relative_to(REPO_ROOT)}")
    print(f"{'metric':<10} {'voyage-3':>10} {'gemini-dense':>14}  winner")
    for k in keys:
        v, g = voyage[k], gemini[k]
        w = "voyage" if v > g else "gemini-dense" if g > v else "tie"
        print(f"{k:<10} {v:>10.4f} {g:>14.4f}  {w}")
    print(f"n_questions: {voyage['n_questions']}")
    parity = all(voyage[k] >= gemini[k] - 0.01 for k in keys)
    print(f"text parity (voyage within ~1pt or better on all metrics): {'YES' if parity else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
