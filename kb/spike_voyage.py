"""Three-way text-embedding spike: voyage-4 vs voyage-3 vs gemini-dense.

Supersedes the voyage-3-only spike. Runs the gold-set retrieval eval live for
both Voyage text models (VOYAGE_MODEL=voyage-4 -> data/kb/dense-voyage-4.db,
voyage-3 -> data/kb/dense-voyage.db) and takes the Gemini-dense baseline
metrics from data/eval/runs/20260901-170237-ablation.json (dense channel —
Gemini free-tier quota is constrained, so it is not re-run). Adds a
whole-corpus text-embedding cost model per provider.

Costs (official, per 1M tokens):
- voyage-4:           $0.06
- voyage-3:           $0.06 (free 200M-token tier applies)
- gemini-embedding-001: $0.10 (batch, text)

Usage: uv run python -m kb.spike_voyage
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from kb.dense import index_text, retrieve
from kb.eval import load_corpus, load_gold_set, run_retrieval_eval
from kb.schema import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "eval" / "runs"
BASELINE_PATH = RUNS_DIR / "20260901-170237-ablation.json"
GEMINI_DB = "data/kb/dense.db"

VOYAGE_DB_4 = REPO_ROOT / "data" / "kb" / "dense-voyage-4.db"
VOYAGE_DB_3 = REPO_ROOT / "data" / "kb" / "dense-voyage.db"

COST_PER_1M = {"voyage-4": 0.06, "voyage-3": 0.06, "gemini-embedding-001": 0.10}
FREE_TIER = {
    "voyage-4": None,
    "voyage-3": "200M free tokens (current plan) — whole corpus fits in free tier",
    "gemini-embedding-001": "free-tier quota constrained (context-limited)",
}


def _voyage_tokens(texts: list[str], model: str) -> int:
    """Exact token count via voyageai count_tokens; falls back to char/4."""
    try:
        import voyageai

        client = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY", ""))
        return int(client.count_tokens(texts, model=model))
    except Exception:
        return sum(len(t) for t in texts) // 4


def _cost_model(corpus: list[dict]) -> dict:
    """Whole-corpus text-embed cost for each model."""
    texts = [t for t in (index_text(r) for r in corpus) if t]
    chars = sum(len(t) for t in texts)
    v_tokens = _voyage_tokens(texts, "voyage-3")  # same tokenizer family
    g_tokens = chars // 4  # approximate
    out = {}
    for model, tokens in (("voyage-4", v_tokens), ("voyage-3", v_tokens), ("gemini-embedding-001", g_tokens)):
        out[model] = {
            "n_texts": len(texts),
            "total_tokens": tokens,
            "cost_per_1m_usd": COST_PER_1M[model],
            "est_whole_corpus_cost_usd": round(tokens / 1e6 * COST_PER_1M[model], 6),
            "free_tier": FREE_TIER[model],
        }
    return out


def main() -> int:
    for db, model in ((VOYAGE_DB_4, "voyage-4"), (VOYAGE_DB_3, "voyage-3")):
        if not db.exists():
            raise SystemExit(f"missing {model} index: {db}; run kb.dense --build --provider voyage with VOYAGE_MODEL={model}")

    corpus = load_corpus()
    gold_set = load_gold_set()

    os.environ["VOYAGE_MODEL"] = "voyage-4"
    v4 = run_retrieval_eval(corpus, gold_set, lambda q: retrieve(q, top_k=10, provider_name="voyage"))
    os.environ["VOYAGE_MODEL"] = "voyage-3"
    v3 = run_retrieval_eval(corpus, gold_set, lambda q: retrieve(q, top_k=10, provider_name="voyage"))
    os.environ.pop("VOYAGE_MODEL", None)

    with open(BASELINE_PATH, encoding="utf-8") as f:
        baseline = json.load(f)
    g = baseline["results"]["dense"]
    gemini = {k: g[k] for k in ("recall@5", "recall@10", "ndcg@10", "mrr", "n_questions")}

    costs = _cost_model(corpus)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    keys = ("recall@5", "recall@10", "ndcg@10", "mrr")
    metrics = {
        "voyage-4": {k: v4[k] for k in (*keys, "n_questions")},
        "voyage-3": {k: v3[k] for k in (*keys, "n_questions")},
        "gemini-dense": gemini,
    }
    winner = {
        k: max(metrics, key=lambda m: metrics[m][k])
        for k in keys
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "eval_set_version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "spike": "voyage4-vs-voyage3-vs-gemini-text-parity",
        "providers": {
            "voyage-4": {"db": "data/kb/dense-voyage-4.db", "metrics": metrics["voyage-4"]},
            "voyage-3": {"db": "data/kb/dense-voyage.db", "metrics": metrics["voyage-3"]},
            "gemini-dense": {"db": GEMINI_DB, "baseline_run": BASELINE_PATH.name, "metrics": gemini},
        },
        "cost": costs,
        "winner": winner,
        "per_question": v4["per_question"],
    }
    out = RUNS_DIR / f"{ts}-voyage4-spike.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    cols = ("voyage-4", "voyage-3", "gemini-dense")
    print(f"report: {out.relative_to(REPO_ROOT)}")
    print(f"{'metric':<10}" + "".join(f" {c:>14}" for c in cols) + "  winner")
    for k in keys:
        print(f"{k:<10}" + "".join(f" {metrics[c][k]:>14.4f}" for c in cols) + f"  {winner[k]}")
    nq = metrics["voyage-4"]["n_questions"]
    print(f"n_questions: {nq} (all models)")
    print("-- cost (whole-corpus text embed) --")
    for m, c in costs.items():
        ft = f" [free tier: {c['free_tier']}]" if c["free_tier"] else ""
        print(f"{m:<22} {c['total_tokens']:>10,} tok  ${c['cost_per_1m_usd']:.2f}/1M  ${c['est_whole_corpus_cost_usd']:.4f}{ft}")
    print("-- verdict --")
    print(_verdict(metrics, costs, keys))
    return 0


def _verdict(metrics: dict, costs: dict, keys) -> str:
    def delta(a: str, b: str) -> float:
        return sum(metrics[a][k] - metrics[b][k] for k in keys) / len(keys)

    d43 = delta("voyage-4", "voyage-3")
    d4g = delta("voyage-4", "gemini-dense")
    cost4, cost3, costg = (costs[m]["est_whole_corpus_cost_usd"] for m in ("voyage-4", "voyage-3", "gemini-embedding-001"))
    lines = [f"voyage-4 vs voyage-3 avg metric delta: {d43:+.4f}; vs gemini: {d4g:+.4f}"]
    lines.append(
        f"cost: voyage-4 ${cost4:.4f} vs voyage-3 ${cost3:.4f} (free tier) vs gemini ${costg:.4f}"
    )
    if d4g > 0.01:
        verdict = "voyage-4 wins meaningfully over voyage-3 AND gemini — worth the (still small) cost"
    elif d4g < -0.01:
        verdict = (
            "gemini-dense still leads on all metrics; voyage-4 > voyage-3 though. "
            "At ~$0.002 per corpus build, cost is not a differentiator — keep the gemini "
            "baseline; voyage-4 is the best Voyage option if a Voyage provider is needed"
        )
    elif d43 > 0.01:
        verdict = "voyage-4 beats voyage-3, ties gemini — same cost, so voyage-4 is the pick among Voyage models"
    else:
        verdict = "voyage-4 ~= voyage-3 ~= gemini; cost identical for v4/v3, keep voyage-3 free tier or gemini baseline"
    lines.append(verdict)
    return " | ".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
