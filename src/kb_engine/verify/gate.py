"""Regression gate (plan §6.4): compare an eval run against the committed baseline.

GATE RULE: an eval run is only comparable to the baseline when the four-corner
tuple ``(schema_version, index_version, eval_set_version, embedder_version)``
MATCHES. On mismatch the gate ABORTS (drift) — it never compares across
tuples. When the tuple matches, the gate FAILS if any of recall@5 / recall@10
/ nDCG@10 / MRR drops below the baseline by more than ``regression_threshold``
(absolute, default 0.02). Abstention is report-only and never gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from kb_engine.verify.baseline import Baseline

GATED_METRICS = ("recall@5", "recall@10", "ndcg@10", "mrr")
DEFAULT_REGRESSION_THRESHOLD = 0.02

DECISION_PASS = "pass"
DECISION_FAIL = "fail"
DECISION_ABORT = "abort"

FOUR_CORNER_NAMES = ("schema_version", "index_version", "eval_set_version", "embedder_version")


@dataclass(frozen=True)
class FourCorner:
    """The current run's corner of the version tuple."""

    schema_version: str
    index_version: str
    eval_set_version: str
    embedder_version: Mapping[str, Any]


@dataclass
class GateResult:
    decision: str  # pass | fail | abort
    tuple: dict[str, Any]  # the CURRENT run's four-corner tuple
    per_metric: dict[str, dict[str, float]]  # metric -> {baseline, current, delta}
    baseline_path: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "tuple": self.tuple,
            "per_metric": self.per_metric,
            "baseline_path": self.baseline_path,
            "reason": self.reason,
        }


def gate_decision(current: FourCorner, baseline: Baseline) -> tuple[str, str]:
    """Tuple comparison only: ``('abort', reason)`` on drift, else ``('pass', '')``."""
    bc = baseline.four_corner()
    drifted = [
        corner for corner in FOUR_CORNER_NAMES if bc[corner] != getattr(current, corner)
    ]
    if drifted:
        details = "; ".join(
            f"{c}: baseline={bc[c]!r} run={getattr(current, c)!r}" for c in drifted
        )
        return DECISION_ABORT, f"four-corner tuple mismatch (drift) on {details}"
    return DECISION_PASS, ""


def run_gate(
    current: FourCorner,
    metrics: Mapping[str, float],
    baseline: Baseline,
    *,
    baseline_path: str = "",
    regression_threshold: float = DEFAULT_REGRESSION_THRESHOLD,
) -> GateResult:
    """Compare run ``metrics`` against ``baseline`` under the gate rule."""
    tuple_dict = {
        "schema_version": current.schema_version,
        "index_version": current.index_version,
        "eval_set_version": current.eval_set_version,
        "embedder_version": dict(current.embedder_version),
    }
    decision, reason = gate_decision(current, baseline)
    if decision == DECISION_ABORT:
        return GateResult(
            decision=DECISION_ABORT,
            tuple=tuple_dict,
            per_metric={},
            baseline_path=baseline_path,
            reason=reason,
        )

    per_metric: dict[str, dict[str, float]] = {}
    failures: list[str] = []
    for metric in GATED_METRICS:
        base = float(baseline.metrics[metric])
        cur = float(metrics.get(metric, 0.0))
        delta = cur - base  # negative = regression
        per_metric[metric] = {"baseline": base, "current": cur, "delta": delta}
        if delta < -regression_threshold:
            failures.append(
                f"{metric}: {cur:.4f} vs baseline {base:.4f} (delta {delta:+.4f} "
                f"beyond -{regression_threshold})"
            )
    if failures:
        return GateResult(
            decision=DECISION_FAIL,
            tuple=tuple_dict,
            per_metric=per_metric,
            baseline_path=baseline_path,
            reason="regression: " + "; ".join(failures),
        )
    return GateResult(
        decision=DECISION_PASS,
        tuple=tuple_dict,
        per_metric=per_metric,
        baseline_path=baseline_path,
    )
