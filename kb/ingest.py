"""Ingest the UI/UX corpus into canonical KbPost v1 records.

Builds data/uiux/kb-posts.json by joining two READ-ONLY sources:
  * this repo's thin metadata: data/uiux/posts.json + profiles.json
  * the scrape repo's rich corpus: scrape-ig-saved-list/data/uiux/<dataset>/<post_id>/

Usage:
    uv run python -m kb.ingest
    uv run python -m kb.ingest --summary
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kb.schema import build_provenance, empty_kbpost

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_JSON = REPO_ROOT / "data" / "uiux" / "posts.json"
PROFILES_JSON = REPO_ROOT / "data" / "uiux" / "profiles.json"
OUTPUT_PATH = REPO_ROOT / "data" / "uiux" / "kb-posts.json"
SCRAPE_ROOT = Path("C:/Users/evano/repos/scrape-ig-saved-list") / "data" / "uiux"

DEFAULT_EXTRACTOR_MODEL = "gemini-3.1-flash-lite"


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_metadata_index(
    posts_path: Path = POSTS_JSON, profiles_path: Path = PROFILES_JSON
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Read the thin metadata files.

    Returns (posts, profiles) where posts maps shortcode ->
    {shortcode, url, type, username} and profiles maps username -> post_count.
    """
    posts_doc = _read_json(posts_path)
    posts: dict[str, dict[str, Any]] = {}
    for entry in posts_doc.get("posts", []):
        posts[entry["shortcode"]] = {
            "shortcode": entry["shortcode"],
            "url": entry["url"],
            "type": entry.get("type"),
            "username": entry.get("username") or "",
        }
    profiles_doc = _read_json(profiles_path)
    profiles: dict[str, int] = {
        p["username"]: p.get("post_count", 0) for p in profiles_doc.get("profiles", [])
    }
    return posts, profiles


def discover_scrape_posts(
    scrape_root: Path = SCRAPE_ROOT,
) -> dict[str, dict[str, Any]]:
    """Walk scrape_root/<dataset>/<post_id>/ for dirs with post_metadata.json.

    Returns dict post_id -> {metadata, analysis, media_files, path, dataset}
    where `path` is the post dir and `dataset` the dataset dir name
    (both used for provenance/ingestion).
    """
    discovered: dict[str, dict[str, Any]] = {}
    if not scrape_root.is_dir():
        return discovered
    for metadata_path in sorted(scrape_root.glob("*/*/post_metadata.json")):
        post_dir = metadata_path.parent
        raw_metadata = _read_json(metadata_path)
        post_id = str(raw_metadata.get("id") or post_dir.name)
        analysis: dict[str, Any] | None = None
        analysis_path = post_dir / "analysis.json"
        if analysis_path.is_file():
            try:
                analysis = _read_json(analysis_path)
            except (json.JSONDecodeError, OSError):
                analysis = None
        media_files = sorted(
            p.name
            for p in post_dir.iterdir()
            if p.is_file() and p.name not in ("post_metadata.json", "analysis.json")
        )
        discovered[post_id] = {
            "metadata": raw_metadata,
            "analysis": analysis,
            "media_files": media_files,
            "path": post_dir,
            "dataset": post_dir.parent.name,
        }
    return discovered


def _apply_analysis(rec: dict[str, Any], entry: dict[str, Any]) -> None:
    """Merge a scrape post's metadata/analysis/media into a KbPost record."""
    metadata = entry["metadata"]
    analysis_doc = entry["analysis"]
    analysis = (analysis_doc or {}).get("analysis") or {}
    post_dir: Path = entry["path"]
    media_ref = f"{entry['dataset']}/{post_dir.name}"

    rec["post_id"] = str(metadata.get("id") or post_dir.name)
    rec["shortcode"] = str(metadata.get("shortCode") or rec["shortcode"])
    rec["owner"] = rec["owner"] or (metadata.get("ownerUsername") or "")
    rec["media_files"] = list(entry["media_files"])
    rec["media_count"] = len(rec["media_files"])

    if analysis_doc and analysis:
        rec["extraction_status"] = "ok"
        rec["is_educational"] = analysis.get("is_educational")
        rec["value_score"] = analysis.get("value_score")
        rec["content_type"] = analysis.get("content_type") or "other"
        rec["domains"] = list(analysis.get("domains") or [])
        rec["summary"] = analysis.get("summary") or ""
        rec["resources"] = list(analysis.get("resources") or [])
        rec["workflow_steps"] = list(analysis.get("workflow_steps") or [])
        rec["tips"] = list(analysis.get("tips") or [])
        rec["concepts"] = list(analysis.get("concepts") or [])
        rec["tools_apps"] = list(analysis.get("tools_apps") or [])
        rec["gated_content"] = analysis.get("gated_content")
        rec["gated_trigger"] = analysis.get("gated_trigger") or ""
        rec["transcript"] = analysis.get("transcript") or ""
        rec["tags"] = list(analysis.get("tags") or [])
        rec["provenance"] = build_provenance(
            source_post_id=rec["post_id"],
            media_ref=media_ref,
            extractor_model=analysis.get("extractor_model") or DEFAULT_EXTRACTOR_MODEL,
            confidence=analysis.get("confidence"),
            extracted_at=(analysis_doc or {}).get("analysed_at"),
        )
    else:
        rec["provenance"] = build_provenance(
            source_post_id=rec["post_id"], media_ref=media_ref
        )

    # Hashtags: analysis tags first, else metadata hashtags (metadata-derived,
    # so also valid for pending records).
    if not rec["tags"]:
        rec["tags"] = list(metadata.get("hashtags") or [])


def build_uiux_corpus(
    metadata_index: dict[str, dict[str, Any]],
    scrape_posts: dict[str, dict[str, Any]],
    snapshot_id: str = "",
) -> list[dict[str, Any]]:
    """Build the canonical corpus: union of posts.json entries and scrape dirs.

    Records are keyed by post_id when available, else shortcode. posts.json
    order is preserved; scrape-only posts (if any) are appended sorted.
    """
    imported_at = _utc_now()
    records: dict[str, dict[str, Any]] = {}

    # Seed one pending record per posts.json entry.
    for shortcode, meta in metadata_index.items():
        rec = empty_kbpost(post_id=shortcode, shortcode=shortcode, owner=meta["username"])
        rec["url"] = meta["url"] or rec["url"]
        rec["provenance"] = build_provenance(source_post_id=shortcode)
        rec["ingestion"] = {
            "snapshot_id": snapshot_id,
            "imported_at": imported_at,
            "source_path": str(POSTS_JSON),
        }
        records[shortcode] = rec

    # Attach rich scrape data by shortcode, collecting post_ids for keying.
    key_by_shortcode: dict[str, str] = {}
    scrape_by_shortcode: dict[str, dict[str, Any]] = {}
    for entry in scrape_posts.values():
        shortcode = str((entry["metadata"] or {}).get("shortCode") or "")
        if shortcode:
            key_by_shortcode[shortcode] = str(entry["metadata"].get("id") or shortcode)
            scrape_by_shortcode[shortcode] = entry

    for shortcode, rec in list(records.items()):
        entry = scrape_by_shortcode.get(shortcode)
        if entry is not None:
            _apply_analysis(rec, entry)
            rec["ingestion"] = {
                "snapshot_id": snapshot_id or entry["dataset"],
                "imported_at": imported_at,
                "source_path": str(entry["path"]),
            }
            post_id = key_by_shortcode[shortcode]
            if post_id != shortcode:
                records.pop(shortcode, None)
                records[post_id] = rec

    # Scrape posts with no posts.json counterpart.
    for post_id, entry in scrape_posts.items():
        shortcode = str((entry["metadata"] or {}).get("shortCode") or post_id)
        if shortcode in metadata_index:
            continue
        rec = empty_kbpost(post_id=post_id, shortcode=shortcode, owner="")
        rec["ingestion"] = {
            "snapshot_id": entry["dataset"],
            "imported_at": imported_at,
            "source_path": str(entry["path"]),
        }
        _apply_analysis(rec, entry)
        records.setdefault(post_id, rec)

    return list(records.values())


def summarize(records: list[dict[str, Any]]) -> str:
    """Coverage stats: total, with_analysis, pending, domains histogram."""
    with_analysis = sum(1 for r in records if r["extraction_status"] == "ok")
    pending = sum(1 for r in records if r["extraction_status"] == "pending")
    failed = sum(1 for r in records if r["extraction_status"] == "failed")
    partial = sum(1 for r in records if r["extraction_status"] == "partial")
    domain_counts: Counter[str] = Counter()
    for r in records:
        domain_counts.update(r["domains"])
    lines = [
        f"total={len(records)}",
        f"with_analysis={with_analysis}",
        f"pending={pending}",
        f"partial={partial}",
        f"failed={failed}",
        "domains:",
    ]
    for domain, count in sorted(domain_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {domain}: {count}")
    return "\n".join(lines)


def write_corpus(records: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the UI/UX KbPost corpus.")
    parser.add_argument(
        "--summary", action="store_true", help="print coverage stats after ingest"
    )
    args = parser.parse_args(argv)

    posts_doc = _read_json(POSTS_JSON)
    snapshot_id = f"har-{posts_doc.get('captured', 'unknown')}"
    metadata_index, _profiles = load_metadata_index()
    scrape_posts = discover_scrape_posts()
    records = build_uiux_corpus(metadata_index, scrape_posts, snapshot_id=snapshot_id)
    write_corpus(records)

    if args.summary:
        print(summarize(records))
    else:
        print(f"wrote {len(records)} records to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
