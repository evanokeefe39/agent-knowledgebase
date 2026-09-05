"""Baseline file (SHARED schema): the committed four-corner + metrics anchor.

A gate input — NEVER under artifacts/. Loaded/written via
:meth:`load_baseline` / :meth:`write_baseline`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"

#: The four-corner version tuple fields, in canonical order.
FOUR_CORNERS = ("schema_version", "index_version", "eval_set_version", "embedder_version")


@dataclass
class Baseline:
    """Committed eval baseline keyed by the four-corner version tuple."""

    schema_version: str
    index_version: str
    eval_set_version: str
    embedder_version: dict[str, Any]  # {provider, model, dims}
    corpus: str
    metrics: dict[str, float]  # recall@5, recall@10, ndcg@10, mrr
    generated_at: str

    def four_corner(self) -> dict[str, Any]:
        """The identity corner of the tuple (embedder is compared as a value)."""
        return {
            "schema_version": self.schema_version,
            "index_version": self.index_version,
            "eval_set_version": self.eval_set_version,
            "embedder_version": dict(self.embedder_version),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "index_version": self.index_version,
            "eval_set_version": self.eval_set_version,
            "embedder_version": dict(self.embedder_version),
            "corpus": self.corpus,
            "metrics": dict(self.metrics),
            "generated_at": self.generated_at,
        }


def make_baseline(
    *,
    index_version: str,
    eval_set_version: str,
    embedder_version: dict[str, Any],
    corpus: str,
    metrics: dict[str, float],
    schema_version: str = SCHEMA_VERSION,
) -> Baseline:
    """Construct a baseline stamped with the current UTC time."""
    return Baseline(
        schema_version=schema_version,
        index_version=index_version,
        eval_set_version=eval_set_version,
        embedder_version=dict(embedder_version),
        corpus=corpus,
        metrics=dict(metrics),
        generated_at=datetime.now(UTC).isoformat(),
    )


def load_baseline(path: str | Path) -> Baseline:
    """Load and validate a committed baseline file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in (*FOUR_CORNERS, "corpus", "metrics", "generated_at") if k not in raw]
    if missing:
        raise ValueError(f"baseline {path}: missing fields {missing}")
    for metric in ("recall@5", "recall@10", "ndcg@10", "mrr"):
        if metric not in raw["metrics"]:
            raise ValueError(f"baseline {path}: metrics missing {metric!r}")
    return Baseline(
        schema_version=str(raw["schema_version"]),
        index_version=str(raw["index_version"]),
        eval_set_version=str(raw["eval_set_version"]),
        embedder_version=dict(raw["embedder_version"]),
        corpus=str(raw["corpus"]),
        metrics={k: float(v) for k, v in raw["metrics"].items()},
        generated_at=str(raw["generated_at"]),
    )


def write_baseline(baseline: Baseline, path: str | Path) -> Path:
    """Write a baseline file (creating parent dirs); returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(baseline), indent=2) + "\n", encoding="utf-8")
    return p
