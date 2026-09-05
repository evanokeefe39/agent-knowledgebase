#!/usr/bin/env python3
"""Data-2 migration runner: build the canonical UIUX corpus manifest.

Migrates the UIUX corpus declared in ``corpora/uiux.yaml`` to a pinned
canonical manifest via the generic ingest engine (plan §6.1, §8;
docs/productization-build.md Data-2).

Composition:
  1. RE-INGEST the real scrape source (``IgSavedAdapter`` ->
     ``RecordMapper`` -> ``RecordDedupe`` -> ``IngestPipeline``), configured
     entirely from the corpus declaration. The scrape location comes from
     the declared ``location`` (``${SCRAPE_REPO}/data/uiux``) with the
     ``SCRAPE_REPO`` environment override — no absolute path is hardcoded.
  2. PORT legacy canonical records (``data/uiux/kb-posts.json``, the
     86-record reference) for posts with no raw scrape dirs (35 HAR-only
     shortcode-id posts + any scraped-but-unanalysed pending post) through
     the same ``RecordMapper`` from synthetic flat raw items. Ported records
     that cannot satisfy the thin envelope (pending extraction, no
     retrievable text unit, no media_ref) are surfaced in the migration
     report as ``envelope_gaps`` and pinned with the engine's own
     ``content_hash`` — never silently dropped (plan §6.1, §7).
  3. RECONCILE against the reference: every reference id must appear, and
     every ingested/ported id must be in the reference; any drift fails the
     run with evidence.

Outputs (deterministic; idempotent — a re-run over unchanged inputs
rewrites nothing):
  user_data/canonical/uiux/corpus.json   CanonicalRecord fields + provenance
  user_data/canonical/uiux/manifest.json {schema_version, snapshot_id,
                                          records: [{id, content_hash}]}
  user_data/canonical/uiux/migration_report.json

Usage:
  SCRAPE_REPO=<path> uv run python scripts/migrate_uiux.py
  SCRAPE_REPO=<path> uv run python scripts/migrate_uiux.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from kb_engine.config import Config, load
from kb_engine.core.records import CanonicalRecord
from kb_engine.core.provenance import Provenance
from kb_engine.ingest.adapters import flatten_concepts, flatten_resources
from kb_engine.ingest.pipeline import IngestPipeline
from kb_engine.ingest.mappers import (
    EnvelopeFailure,
    MappingError,
    RecordMapper,
    content_hash,
)

# Declared schema field names pulled from the legacy canonical reference.
# Kept as data so the runner references the corpus declaration, not the
# legacy schema: fields are taken from corpus.fields, this list only orders
# the legacy-record keys by their declared counterparts.
DECLARED_FIELDS = (
    "post_id", "shortcode", "url", "owner", "content_type", "domains",
    "is_educational", "value_score", "gated_content", "gated_trigger",
    "summary", "transcript", "workflow_steps", "tips", "caption", "concepts",
    "tools_apps", "resources", "resources_text", "tags", "media_files",
    "extraction_status", "is_promo",
)


def _dump(path: Path, payload: Any) -> bool:
    """Write deterministic JSON; return True only if bytes changed."""
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _synthetic_raw(record: dict[str, Any]) -> dict[str, Any]:
    """Shape a legacy canonical record as a flat raw item for the mapper."""
    metadata = {
        "id": record["post_id"],
        "shortCode": record.get("shortcode"),
        "ownerUsername": record.get("owner"),
        "caption": record.get("caption"),
        "hashtags": record.get("tags"),
    }
    analysis = {
        "summary": record.get("summary"),
        "transcript": record.get("transcript"),
        "workflow_steps": record.get("workflow_steps"),
        "tips": record.get("tips"),
        "concepts": flatten_concepts(record.get("concepts")),
        "tools_apps": record.get("tools_apps"),
        "value_score": record.get("value_score"),
        "content_type": record.get("content_type"),
        "domains": record.get("domains"),
        "is_educational": record.get("is_educational"),
        "gated_content": record.get("gated_content"),
        "gated_trigger": record.get("gated_trigger"),
        "is_promo": record.get("is_promo"),
        "analysed_at": record.get("provenance", {}).get("extracted_at"),
    }
    # Null optional attributes are omitted (absence -> None + coverage stat);
    # a present-but-null value would hit fail-fast transforms (coerce_*).
    metadata = {k: v for k, v in metadata.items() if v is not None}
    analysis = {k: v for k, v in analysis.items() if v is not None}
    raw: dict[str, Any] = {
        "metadata": metadata,
        "analysis": analysis,
        "media": record.get("media_files") or [],
        "dataset_post_dir": record.get("provenance", {}).get("media_ref") or "",
        "extraction_status": record.get("extraction_status") or "pending",
    }
    resources = record.get("resources")
    if isinstance(resources, list):
        raw["resources"] = resources
        raw["resources_text"] = flatten_resources(resources)
    return raw


def _fields_from_legacy(record: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in DECLARED_FIELDS:
        value = record.get(name)
        if name == "concepts":
            value = flatten_concepts(value)
        elif name == "resources_text":
            value = flatten_resources(record.get("resources"))
        fields[name] = value
    return fields


def _direct_record(record: dict[str, Any], corpus: Any) -> CanonicalRecord:
    """Port a legacy record the envelope gate rejects, using engine
    primitives only (never silently dropped; surfaced in the report)."""
    fields = _fields_from_legacy(record)
    prov = record.get("provenance", {})
    return CanonicalRecord(
        id=str(record["post_id"]),
        content_hash=content_hash(fields, corpus.refresh_hash_fields),
        provenance=Provenance(
            source=corpus.sources[0].provenance.source,
            media_ref=str(prov.get("media_ref") or ""),
            timestamp=str(prov.get("extracted_at") or "") or None,
            extractor=str(prov.get("extractor_model") or "") or None,
            confidence=prov.get("confidence"),
        ),
        fields=fields,
    )


def migrate(
    config_path: str | Path = "config.yaml",
    corpus_name: str = "uiux",
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the migration; returns the migration report (also written)."""
    config: Config = load(config_path)
    corpus = config.corpus(corpus_name)
    if corpus is None:
        raise SystemExit(f"corpus '{corpus_name}' not declared under config")
    if len(corpus.sources) != 1:
        raise SystemExit(
            f"corpus '{corpus_name}': expected exactly one declared source, "
            f"got {len(corpus.sources)}"
        )
    spec = corpus.sources[0]
    repo_root = Path(config_path).resolve().parent
    out = Path(out_dir) if out_dir else repo_root / "user_data" / "canonical" / corpus_name
    out.mkdir(parents=True, exist_ok=True)

    # ---- reference: the 86-record legacy canonical --------------------------
    reference_path = repo_root / "data" / "uiux" / "kb-posts.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    ref_by_id = {str(r["post_id"]): r for r in reference}
    ref_order = [str(r["post_id"]) for r in reference]

    # ---- idempotency state --------------------------------------------------
    manifest_path = out / "manifest.json"
    corpus_path = out / "corpus.json"
    existing: dict[str, str] = {}
    prev_by_id: dict[str, dict[str, Any]] = {}
    if manifest_path.is_file() and corpus_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing = {r["id"]: r["content_hash"] for r in previous.get("records", [])}
        prev_by_id = {
            r["id"]: r for r in json.loads(corpus_path.read_text(encoding="utf-8"))
        }

    def _entry(rec: CanonicalRecord) -> dict[str, Any]:
        return {
            "id": rec.id,
            "content_hash": rec.content_hash,
            "provenance": {
                "source": rec.provenance.source,
                "media_ref": rec.provenance.media_ref,
                "timestamp": rec.provenance.timestamp,
                "extractor": rec.provenance.extractor,
                "confidence": rec.provenance.confidence,
            },
            "fields": rec.fields,
        }

    # ---- 1. re-ingest the real scrape source --------------------------------
    pipeline = IngestPipeline(corpus, existing=existing)
    result = pipeline.run(spec.name)[0]
    entries: dict[str, dict[str, Any]] = {r.id: _entry(r) for r in result.added}
    reingested_ids = sorted(entries)
    unchanged_ids = sorted(set(result.skipped) & set(existing))
    for rid in result.skipped:
        if rid not in entries:
            if rid not in prev_by_id:
                raise SystemExit(
                    f"record {rid} unchanged but missing from previous "
                    "corpus.json; delete the canonical outputs and re-run"
                )
            entries[rid] = prev_by_id[rid]  # carried forward verbatim

    # ---- 2. port legacy records with no successful raw ingest ---------------
    mapper = RecordMapper(corpus, spec)
    ported: dict[str, CanonicalRecord] = {}
    envelope_gaps: list[dict[str, str]] = []
    port_failures: list[dict[str, str]] = []
    for rid in ref_order:
        if rid in entries:
            continue
        raw = _synthetic_raw(ref_by_id[rid])
        try:
            entries[rid] = _entry(mapper.map(raw))
        except EnvelopeFailure as exc:
            envelope_gaps.append({"id": rid, "reason": exc.reason,
                                  "detail": exc.detail})
            entries[rid] = _entry(_direct_record(ref_by_id[rid], corpus))
        except MappingError as exc:
            port_failures.append({"id": rid, "detail": str(exc)})

    if port_failures:
        raise SystemExit(
            "legacy port failed declared-schema validation (not forced):\n"
            + "\n".join(f"  {f['id']}: {f['detail']}" for f in port_failures)
        )

    # ---- 3. reconcile against the reference (never silently drop) ----------
    final_ids = set(entries)
    missing = sorted(set(ref_order) - final_ids)
    extra = sorted(final_ids - set(ref_order))
    if missing or extra:
        raise SystemExit(
            f"reconciliation drift vs {reference_path.name}: "
            f"missing={missing} extra={extra}"
        )
    if len(final_ids) != len(reference):
        raise SystemExit(
            f"record count {len(final_ids)} != reference {len(reference)} "
            "(duplicate ids?)"
        )

    # ---- 4. deterministic outputs (reference order) -------------------------
    ordered = [entries[r] for r in ref_order]

    corpus_payload = ordered
    manifest_payload = {
        "schema_version": corpus.schema_version,
        "snapshot_id": spec.snapshot,
        "records": [
            {"id": rec["id"], "content_hash": rec["content_hash"]}
            for rec in ordered
        ],
    }

    corpus_changed = _dump(out / "corpus.json", corpus_payload)
    manifest_changed = _dump(manifest_path, manifest_payload)
    report = {
        "corpus": corpus_name,
        "schema_version": corpus.schema_version,
        "snapshot_id": spec.snapshot,
        "reference_records": len(reference),
        "reingested_from_raw": len(reingested_ids),
        "unchanged_since_last_run": len(unchanged_ids),
        "ported_from_legacy": len(ref_order) - len(reingested_ids) - len(unchanged_ids),
        "ported_envelope_gaps": envelope_gaps,
        "source_gaps": [
            {"source": g.source, "index": g.index, "reason": g.reason,
             "detail": g.detail}
            for g in result.gaps
        ],
        "coverage_gap_reasons": sorted({g.reason for g in result.gaps}),
        "outputs_changed": {"corpus.json": corpus_changed,
                            "manifest.json": manifest_changed},
    }
    _dump(out / "migration_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--corpus", default="uiux")
    parser.add_argument(
        "--check", action="store_true",
        help="verify idempotency: a re-run must rewrite nothing",
    )
    args = parser.parse_args(argv)
    report = migrate(args.config, args.corpus)
    if args.check:
        changed = report["outputs_changed"]
        if any(changed.values()):
            print(f"FAIL: outputs changed on re-run: {changed}", file=sys.stderr)
            return 1
        print("OK: re-run unchanged (idempotent, no re-ingest)")
    print(
        f"corpus={report['corpus']} records={report['reference_records']} "
        f"reingested={report['reingested_from_raw']} "
        f"ported={report['ported_from_legacy']} "
        f"envelope_gaps={len(report['ported_envelope_gaps'])} "
        f"source_gaps={len(report['source_gaps'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
