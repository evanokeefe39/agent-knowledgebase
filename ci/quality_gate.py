"""CI quality gate (plan §9, Build-6): rebuild-from-canonical -> eval -> gate.

Documented CI entry. Owns the full loop per corpus:

  (a) build an index from the canonical corpus records (user_data/canonical/
      <corpus>/corpus.json) via the Build-4 chunker/retriever;
  (b) run the evaluator (§6.4) over the committed gold set;
  (c) gate the run against the committed baseline (ABORT on four-corner
      tuple drift, FAIL on regression > threshold, PASS otherwise);
  (d) write a JSON report to artifacts/verify/.

The embedder is injectable/configurable so PARITY can align the serving
embedder to the baseline embedder (the committed corpus config currently
declares gemini-embedding-2/768 while the M4-measured baseline is
gemini-embedding-001/3072 — a known later-wave reconcile).

Usage::

    uv run python ci/quality_gate.py --corpus uiux            \\
        --gold-set user_data/gold/uiux-v1.json                \\
        --baseline user_data/baselines/uiux-baseline.json     \\
        --index-version 1 --embedder fake                     \\
        [--canonical user_data/canonical/uiux/corpus.json]    \\
        [--retriever dense|bm25|hybrid] [--out-dir artifacts/verify]

Exit codes: 0 pass, 1 fail (regression), 2 abort (tuple drift), 3 setup error.
Hermetic mode: ``--embedder fake`` builds a deterministic offline embedder and
never touches the network; scoring itself NEVER makes API calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kb_engine.config import load as load_config  # noqa: E402
from kb_engine.core.provenance import Provenance  # noqa: E402
from kb_engine.core.records import CanonicalRecord  # noqa: E402
from kb_engine.index.backends import BM25FTS5Backend, InMemoryVectorBackend  # noqa: E402
from kb_engine.index.chunker import Chunker  # noqa: E402
from kb_engine.index.embedder import FakeEmbedder, GeminiEmbedder  # noqa: E402
from kb_engine.index.retriever import BM25Retriever, DenseRetriever  # noqa: E402
from kb_engine.verify.baseline import load_baseline  # noqa: E402
from kb_engine.verify.evaluator import evaluate, load_gold_set  # noqa: E402
from kb_engine.verify.gate import FourCorner, run_gate  # noqa: E402

EXIT_PASS, EXIT_FAIL, EXIT_ABORT, EXIT_ERROR = 0, 1, 2, 3


def build_embedder(name: str, *, model: str | None, dims: int | None) -> Any:
    """Embedder factory — the PARITY seam. ``fake`` is fully offline."""
    if name == "fake":
        return FakeEmbedder(dims=dims or 16)
    if name == "gemini":
        kwargs: dict[str, Any] = {}
        if model:
            kwargs["model"] = model
        if dims:
            kwargs["dims"] = dims
        return GeminiEmbedder(**kwargs)
    raise ValueError(f"unknown embedder {name!r}; expected 'fake' or 'gemini'")


def load_canonical_records(path: str | Path) -> list[CanonicalRecord]:
    """Canonical corpus.json (ingest output shape) -> CanonicalRecord list."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"canonical corpus must be a JSON array: {path}")
    records: list[CanonicalRecord] = []
    for item in raw:
        prov = item.get("provenance") or {}
        records.append(
            CanonicalRecord(
                id=str(item["id"]),
                content_hash=str(item.get("content_hash", "")),
                provenance=Provenance(
                    source=str(prov.get("source", "canonical")),
                    media_ref=str(prov.get("media_ref", "")),
                    timestamp=prov.get("timestamp"),
                    extractor=prov.get("extractor"),
                    confidence=prov.get("confidence"),
                ),
                fields=dict(item.get("fields", {})),
            )
        )
    return records


def build_retriever(
    records: list[CanonicalRecord],
    chunker: Chunker,
    *,
    retriever_name: str,
    embedder: Any,
    dims: int,
) -> Any:
    """Chunk + index the canonical records; return the requested retriever."""
    chunks = [c for rec in records for c in chunker.chunk(rec)]
    bm25_backend = BM25FTS5Backend(":memory:")
    bm25_backend.add(chunks)
    if retriever_name == "bm25":
        return BM25Retriever(bm25_backend)
    vec_backend = InMemoryVectorBackend()
    vec_backend.add_vectors(
        (c, embedder.embed_documents([c.text])[0]) for c in chunks
    )
    dense = DenseRetriever(vec_backend, embedder)
    return dense


def run_quality_gate(
    *,
    corpus_name: str,
    config_path: str | Path = REPO_ROOT / "config.yaml",
    canonical: str | Path | None = None,
    gold_set: str | Path | None = None,
    baseline_path: str | Path | None = None,
    index_version: str | None = None,
    embedder_name: str = "fake",
    embedder_model: str | None = None,
    dims: int | None = None,
    retriever_name: str = "dense",
    out_dir: str | Path = REPO_ROOT / "artifacts" / "verify",
) -> tuple[int, dict[str, Any]]:
    """Full per-corpus loop; returns (exit_code, report dict)."""
    cfg = load_config(config_path)
    corpus = cfg.corpus(corpus_name)
    if corpus is None:
        raise ValueError(f"corpus {corpus_name!r} not declared under {cfg.corpora_dir}")

    vcfg = corpus.raw.get("verify", {})
    canonical = Path(canonical or cfg.user_data_dir / "canonical" / corpus_name / "corpus.json")
    gold_set = Path(gold_set or vcfg.get("gold_set") or
                    cfg.user_data_dir / "gold" / f"{corpus_name}-v1.json")
    baseline_path = Path(baseline_path or vcfg.get("baseline") or
                         cfg.user_data_dir / "baselines" / f"{corpus_name}-baseline.json")
    index_version = index_version or str(corpus.raw.get("index", {}).get("schema_version", "1"))
    ev = vcfg.get("embedder_version", {})
    cli_dims = dims  # explicit --dims only; corpus default belongs to the real embedder

    # (a) rebuild the index from canonical records (proves rebuildability).
    records = load_canonical_records(canonical)
    chunker = Chunker.from_corpus(corpus)
    embedder = build_embedder(embedder_name, model=embedder_model, dims=cli_dims)
    retriever = build_retriever(
        records, chunker,
        retriever_name=retriever_name, embedder=embedder,
        dims=getattr(embedder, "dims", dims or 16),
    )

    # (b) evaluate.
    gold = load_gold_set(gold_set)
    run = evaluate(gold, retriever, corpus=corpus_name)

    # (c) gate vs the committed baseline.
    baseline = load_baseline(baseline_path)
    schema_version = str(corpus.raw.get("schema", {}).get("schema_version", "1"))
    version = getattr(embedder, "version", None) or {
        "provider": embedder_name,
        "model": getattr(embedder, "model", embedder_name),
        "dims": getattr(embedder, "dims", dims or 0),
    }
    current = FourCorner(
        schema_version=schema_version,
        index_version=index_version,
        eval_set_version=str(vcfg.get("eval_set_version", "v1")),
        embedder_version=dict(version),
    )
    gate_threshold = float(
        vcfg.get("gate", {}).get(
            "regression_threshold", cfg.verify.get("regression_threshold", 0.02)
        )
    )
    result = run_gate(
        current, run.metrics, baseline,
        baseline_path=str(baseline_path),
        regression_threshold=gate_threshold,
    )

    # (d) report to artifacts/verify/.
    report = {
        "report": "quality-gate",
        "corpus": corpus_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "eval": {k: v for k, v in run.to_dict().items() if k != "per_question"},
        "gate": result.to_dict(),
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = out / f"{stamp}-{corpus_name}-gate.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    code = {"pass": EXIT_PASS, "fail": EXIT_FAIL, "abort": EXIT_ABORT}.get(
        result.decision, EXIT_ERROR
    )
    return code, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ci/quality_gate.py",
        description="Per-corpus CI quality gate: rebuild-from-canonical -> eval -> gate.",
    )
    ap.add_argument("--corpus", required=True, help="corpus name (corpora/<name>.yaml)")
    ap.add_argument("--config", default=str(REPO_ROOT / "config.yaml"))
    ap.add_argument("--canonical", help="canonical corpus.json (default user_data/canonical/<corpus>/corpus.json)")
    ap.add_argument("--gold-set", help="committed gold set path")
    ap.add_argument("--baseline", help="committed baseline path")
    ap.add_argument("--index-version", help="override index_version (PARITY reconcile)")
    ap.add_argument("--embedder", default="fake", choices=["fake", "gemini"],
                    help="injectable embedder; PARITY aligns this to the baseline embedder")
    ap.add_argument("--embedder-model", help="override embedder model id")
    ap.add_argument("--dims", type=int, help="override embedding dims")
    ap.add_argument("--retriever", default="dense", choices=["dense", "bm25"])
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "artifacts" / "verify"))
    args = ap.parse_args(argv)
    try:
        code, report = run_quality_gate(
            corpus_name=args.corpus,
            config_path=args.config,
            canonical=args.canonical,
            gold_set=args.gold_set,
            baseline_path=args.baseline,
            index_version=args.index_version,
            embedder_name=args.embedder,
            embedder_model=args.embedder_model,
            dims=args.dims,
            retriever_name=args.retriever,
            out_dir=args.out_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CI entry reports setup errors cleanly
        print(f"quality-gate: setup error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    gate = report["gate"]
    print(f"quality-gate[{args.corpus}]: decision={gate['decision']} reason={gate['reason']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
