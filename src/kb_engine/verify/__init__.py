"""Verify stage (plan §6.4): evaluator + baseline + regression gate.

Reports are keyed by the four-corner version tuple
``(schema_version, index_version, eval_set_version, embedder_version)`` so a
regression is attributable to exactly what changed. Deterministic + offline:
scoring never makes an API call (the embedder/retriever is injected upstream).
"""

from kb_engine.verify.baseline import Baseline, load_baseline, write_baseline
from kb_engine.verify.evaluator import (
    EvalQuestion,
    EvalRun,
    evaluate,
    load_gold_set,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from kb_engine.verify.gate import (
    GATED_METRICS,
    FourCorner,
    GateResult,
    gate_decision,
    run_gate,
)

__all__ = [
    "Baseline",
    "EvalQuestion",
    "EvalRun",
    "FourCorner",
    "GATED_METRICS",
    "GateResult",
    "evaluate",
    "gate_decision",
    "load_baseline",
    "load_gold_set",
    "mrr",
    "ndcg_at_k",
    "recall_at_k",
    "run_gate",
    "write_baseline",
]
