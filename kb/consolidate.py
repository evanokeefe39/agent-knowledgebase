"""Merge the UI/UX and creator-growth corpora into one canonical KbPost corpus.

Reads:
  data/uiux/kb-posts.json                      (list of KbPost dicts, domain="uiux")
  data/step-neg1/creator-growth-knowledge.json ({count, records[]}, raw creator-growth records)

Writes:
  data/kb/kb-posts-all.json             (merged JSON array of KbPost records)
  data/kb/kb-posts-all.manifest.json    ({schema_version, domains, total, by_domain, merged_at})

post_id collisions across domains are disambiguated as "{domain}:{post_id}"
for the colliding subset only.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kb.schema import (
    KBPOST_FIELDS,
    SCHEMA_VERSION,
    empty_kbpost,
    validate_kbpost,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

UIUX_PATH = REPO_ROOT / "data" / "uiux" / "kb-posts.json"
CREATOR_GROWTH_PATH = (
    REPO_ROOT / "data" / "step-neg1" / "creator-growth-knowledge.json"
)
OUTPUT_PATH = REPO_ROOT / "data" / "kb" / "kb-posts-all.json"
MANIFEST_PATH = REPO_ROOT / "data" / "kb" / "kb-posts-all.manifest.json"

CREATOR_GROWTH_DOMAIN = "creator-growth"
CANONICAL_DOMAINS = ("uiux", CREATOR_GROWTH_DOMAIN)
CREATOR_GROWTH_SNAPSHOT_ID = "step-neg1-20260831"
CREATOR_GROWTH_SOURCE_PATH = "data/step-neg1/creator-growth-knowledge.json"
CREATOR_GROWTH_EXTRACTOR_MODEL = "gemini-3.1-flash-lite"

def validate_merged(rec: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a merged record against the KbPost v1 contract."""
    return validate_kbpost(rec)


def load_uiux() -> list[dict[str, Any]]:
    with open(UIUX_PATH, encoding="utf-8") as f:
        records = json.load(f)
    for rec in records:
        rec.setdefault("domain", "uiux")
    return records


def map_creator_growth(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a raw creator-growth record onto the full KBPOST_FIELDS contract."""
    rec = empty_kbpost(
        post_id=str(raw["post_id"]),
        shortcode=str(raw.get("shortcode", "")),
        owner=str(raw.get("owner", "")),
        domain=CREATOR_GROWTH_DOMAIN,
    )
    for field in KBPOST_FIELDS:
        if field in raw:
            rec[field] = raw[field]
    rec["domain"] = CREATOR_GROWTH_DOMAIN
    rec["provenance"] = {
        "source_post_id": str(raw["post_id"]),
        "media_ref": None,
        "extractor_model": CREATOR_GROWTH_EXTRACTOR_MODEL,
        "confidence": None,
        "extracted_at": None,
    }
    rec["ingestion"] = {
        "snapshot_id": CREATOR_GROWTH_SNAPSHOT_ID,
        "imported_at": None,
        "source_path": CREATOR_GROWTH_SOURCE_PATH,
    }
    rec["extraction_status"] = "ok"
    rec["is_promo"] = None
    rec["media_files"] = []
    rec["media_count"] = 0
    return rec


def load_creator_growth() -> list[dict[str, Any]]:
    with open(CREATOR_GROWTH_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    return [map_creator_growth(raw) for raw in payload["records"]]


def disambiguate_collisions(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rewrite post_id as "{domain}:{post_id}" only for cross-domain collisions.

    A collision is a post_id shared by records with different domains.
    Same-domain duplicates are left untouched (reported separately is out of
    scope; source corpora are expected unique per domain).
    """
    by_id: dict[str, set[str]] = {}
    for rec in records:
        by_id.setdefault(str(rec["post_id"]), set()).add(rec["domain"])

    colliding_ids = {
        pid for pid, domains in by_id.items() if len(domains) > 1
    }
    if not colliding_ids:
        return records, []

    for rec in records:
        if str(rec["post_id"]) in colliding_ids:
            rec["post_id"] = f"{rec['domain']}:{rec['post_id']}"
    return records, sorted(colliding_ids)


def consolidate() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge, disambiguate, and validate. Returns (kept, report)."""
    merged = load_uiux() + load_creator_growth()
    merged, collisions = disambiguate_collisions(merged)

    kept: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for rec in merged:
        ok, errors = validate_merged(rec)
        if ok:
            kept.append(rec)
        else:
            failures.append({"post_id": rec.get("post_id"), "errors": errors})

    by_domain: dict[str, int] = {d: 0 for d in CANONICAL_DOMAINS}
    for rec in kept:
        by_domain[rec["domain"]] = by_domain.get(rec["domain"], 0) + 1

    report = {
        "total": len(kept),
        "by_domain": by_domain,
        "collisions": collisions,
        "collisions_handled": len(collisions),
        "validation_failures": failures,
        "failed_count": len(failures),
    }
    return kept, report


def write_outputs(records: list[dict[str, Any]], report: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "domains": list(CANONICAL_DOMAINS),
        "total": report["total"],
        "by_domain": report["by_domain"],
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def load_merged() -> list[dict[str, Any]]:
    """Load the merged corpus, rebuilding it from source if missing."""
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    records, _report = consolidate()
    write_outputs(records, _report)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary", action="store_true", help="print merge summary"
    )
    args = parser.parse_args()

    records, report = consolidate()
    write_outputs(records, report)

    if args.summary:
        print(f"total: {report['total']}")
        for domain, count in report["by_domain"].items():
            print(f"  {domain}: {count}")
        print(f"collisions handled: {report['collisions_handled']}")
        if report["collisions"]:
            print(f"  colliding ids: {', '.join(report['collisions'])}")
        print(f"validation failures: {report['failed_count']}")
        for failure in report["validation_failures"]:
            print(f"  {failure['post_id']}: {'; '.join(failure['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
