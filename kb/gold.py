"""Structured-tier gold views over the UI/UX KbPost corpus.

Read-only views with per-row provenance (source_post_id). Nothing here
mutates the source corpus at data/uiux/kb-posts.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "data" / "uiux" / "kb-posts.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "gold"

GOLD_VERSION = "1"


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def snapshot_id(records: list[dict[str, Any]]) -> str:
    ids = {r.get("ingestion", {}).get("snapshot_id") for r in records}
    ids.discard(None)
    return "+".join(sorted(str(i) for i in ids)) or "unknown"


def _norm_tools(rec: dict[str, Any]) -> list[str]:
    """Tool names may be strings or {name: ...} dicts; normalize to strings."""
    out: list[str] = []
    for t in rec.get("tools_apps") or []:
        if isinstance(t, str):
            name = t.strip()
        elif isinstance(t, dict):
            name = str(t.get("name") or "").strip()
        else:
            name = ""
        if name:
            out.append(name)
    return out


def _norm_domains(rec: dict[str, Any]) -> list[str]:
    return [d for d in (rec.get("domains") or []) if d]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def gold_posts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One curated row per corpus post."""
    return [
        {
            "post_id": r["post_id"],
            "shortcode": r.get("shortcode"),
            "url": r.get("url"),
            "owner": r.get("owner"),
            "content_type": r.get("content_type"),
            "value_score": r.get("value_score"),
            "is_educational": r.get("is_educational"),
            "is_promo": r.get("is_promo"),
            "domains": list(_norm_domains(r)),
            "tools_apps": _norm_tools(r),
            "gated_content": r.get("gated_content"),
            "source_post_id": r.get("provenance", {}).get("source_post_id", r["post_id"]),
            "extraction_status": r.get("extraction_status"),
        }
        for r in records
    ]


def gold_creators(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        owner = r.get("owner") or "unknown"
        by_owner.setdefault(owner, []).append(r)

    rows = []
    for owner, posts in by_owner.items():
        scores = [p.get("value_score") for p in posts if isinstance(p.get("value_score"), (int, float))]
        tool_counter: Counter[str] = Counter()
        for p in posts:
            tool_counter.update(_norm_tools(p))
        rows.append(
            {
                "username": owner,
                "post_count": len(posts),
                "domains": sorted({d for p in posts for d in _norm_domains(p)}),
                "avg_value_score": round(sum(scores) / len(scores), 4) if scores else None,
                "top_tools": [t for t, _ in tool_counter.most_common(10)],
                "source_post_ids": sorted(p["post_id"] for p in posts),
            }
        )
    rows.sort(key=lambda x: (-x["post_count"], x["username"]))
    return rows


def gold_tools(records: list[dict[str, Any]], max_examples: int = 5) -> list[dict[str, Any]]:
    mentions: dict[str, dict[str, Any]] = {}
    for r in records:
        for name in _norm_tools(r):
            entry = mentions.setdefault(
                name, {"domains": set(), "post_ids": [], "count": 0}
            )
            entry["count"] += 1
            entry["domains"].update(_norm_domains(r))
            if r["post_id"] not in entry["post_ids"]:
                entry["post_ids"].append(r["post_id"])

    rows = []
    for name, entry in mentions.items():
        rows.append(
            {
                "name": name,
                "mention_count": entry["count"],
                "used_in_domains": sorted(entry["domains"]),
                "example_post_ids": sorted(entry["post_ids"])[:max_examples],
            }
        )
    rows.sort(key=lambda x: (-x["mention_count"], x["name"]))
    return rows


def gold_domains(
    records: list[dict[str, Any]],
    max_creators: int = 5,
    max_representative: int = 5,
) -> list[dict[str, Any]]:
    """One row per distinct domain value across posts."""
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        for d in _norm_domains(r):
            by_domain.setdefault(d, []).append(r)

    rows = []
    for domain, posts in by_domain.items():
        owner_counts: Counter[str] = Counter(p.get("owner") or "unknown" for p in posts)
        top_creators = [
            {"username": owner, "post_count": n}
            for owner, n in owner_counts.most_common(max_creators)
        ]
        rows.append(
            {
                "domain": domain,
                "post_count": len(posts),
                "top_creators": top_creators,
                "representative_post_ids": sorted(
                    p["post_id"] for p in posts
                )[:max_representative],
            }
        )
    rows.sort(key=lambda x: (-x["post_count"], x["domain"]))
    return rows


def _ordered_desc(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

# ---------------------------------------------------------------------------
def tool_frequency(records: list[dict[str, Any]]) -> dict[str, int]:
    return _ordered_desc(
        Counter(t for r in records for t in _norm_tools(r))
    )


def domain_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return _ordered_desc(
        Counter(d for r in records for d in _norm_domains(r))
    )


def gated_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Histogram of the gated_content value (bool/None coerced to string)."""
    def key(v: Any) -> str:
        if v is None:
            return "null"
        return str(bool(v)) if isinstance(v, bool) else str(v)

    return _ordered_desc(Counter(key(r.get("gated_content")) for r in records))


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------

VIEWS = {
    "posts": gold_posts,
    "creators": gold_creators,
    "tools": gold_tools,
    "domains": gold_domains,
}


def materialize(
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    corpus_path: Path = CORPUS_PATH,
) -> dict[str, Any]:
    records = load_corpus(corpus_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = snapshot_id(records)
    materialized_at = datetime.now(timezone.utc).isoformat()

    manifest = []
    for view_name, fn in VIEWS.items():
        rows = fn(records)
        path = out_dir / f"uiux_{view_name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
            f.write("\n")
        manifest.append(
            {
                "view_name": view_name,
                "version": GOLD_VERSION,
                "materialized_at": materialized_at,
                "source_snapshot_id": snap,
                "row_count": len(rows),
            }
        )

    manifest_path = out_dir / "uiux_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"output_dir": out_dir, "manifest": manifest}


def summary(records: list[dict[str, Any]]) -> str:
    lines = [f"corpus: {len(records)} posts (snapshot {snapshot_id(records)})"]
    for view_name, fn in VIEWS.items():
        lines.append(f"{view_name}: {len(fn(records))} rows")
    lines.append("")
    lines.append("tool frequency (top 15):")
    for name, n in list(tool_frequency(records).items())[:15]:
        lines.append(f"  {name}: {n}")
    lines.append("")
    lines.append("domain counts:")
    for name, n in domain_counts(records).items():
        lines.append(f"  {name}: {n}")
    lines.append("")
    lines.append("gated content counts:")
    for name, n in gated_counts(records).items():
        lines.append(f"  {name}: {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI/UX gold views over the KbPost corpus.")
    parser.add_argument(
        "--summary", action="store_true", help="print per-view row counts and aggregations"
    )
    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="materialization output directory"
    )
    args = parser.parse_args(argv)

    records = load_corpus()
    if args.summary:
        print(summary(records))
    if args.output_dir:
        result = materialize(args.output_dir)
        print(f"materialized {len(result['manifest'])} views to {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
