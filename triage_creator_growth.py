#!/usr/bin/env python3
"""Step -1 triage: find posts about creator growth / social content practice.

Reads the scrape-ig-saved-list corpus (post metadata + analysis.json where
present) and scores each post for "content creator growth / social content
practice" signal, producing a narrowed, ranked list for deep AI extraction.

This is a cheap lexical/dictionary triage — NOT an LLM pass. It exists to
shrink the corpus before spending money on extraction. An LLM can refine it.

Usage:
    python triage_creator_growth.py \
        --data-dir ../scrape-ig-saved-list/data/ingest \
        --out data/step-neg1/creator-growth-candidates.json

Inputs:
    <data-dir>/<dataset>/<post_id>/post_metadata.json   (caption, ownerUsername)
    <data-dir>/<dataset>/<post_id>/analysis.json        (domains, tips, summary, ...)
    plus ../scrape-ig-saved-list/data/exports/results.jsonl (rich analysis)

Output:
    --out JSON: ranked candidates with signal score + matched signals + fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Keywords/phrases signalling creator growth, audience building, social content
# practice, monetization of content. Grouped for interpretability.
GROWTH_SIGNALS = [
    # audience / growth
    "grow", "growth", "creator", "audience", "follow", "follower", "reach",
    "impressions", "viral", "algorithm", "save rate", "engagement", "hook",
    "retention", "niche", "target audience",
    # content practice
    "content strategy", "content marketing", "content creation", "content ideas",
    "reel strategy", "carousel strategy", "posting", "captions", "hashtag",
    "batching", "repurpos", "content pillars", "a/b test", "analytics", "insights",
    "social media", "social strategy", "video strategy",
    # monetization / business
    "monetiz", "earn", "income", "revenue", "sponsor", "affiliate", "brand deal",
    "newsletter", "landing page", "funnel", "lead gen", "lead generation",
    "email list", "cta", "call to action", "personal brand", "side hustle",
    "business", "agency", "freelanc", "client",
    # platforms
    "linkedin", "youtube", "tiktok", "twitter", "threads",
]

STRONG_THRESHOLD = 4   # >=4 distinct signals -> strong candidate
MEDIUM_THRESHOLD = 2   # 2-3 -> medium


def load_posts(data_dir: Path, results_jsonl: Path | None) -> list[dict]:
    """Load every post with its caption + (where present) rich analysis."""
    posts: dict[str, dict] = {}

    def add(pid: str, fields: dict):
        posts.setdefault(pid, {"post_id": pid, "media_files": [], "analysis": {}})
        posts[pid].update({k: v for k, v in fields.items() if v not in (None, "")})

    # per-post metadata + analysis.json
    for md in data_dir.rglob("post_metadata.json"):
        try:
            m = json.loads(md.read_text(encoding="utf-8"))
        except Exception:
            continue
        pid = str(m.get("id") or m.get("shortCode") or md.parent.name)
        add(pid, {
            "post_id": pid,
            "shortcode": m.get("shortCode"),
            "url": m.get("url"),
            "caption": m.get("caption"),
            "owner": m.get("ownerUsername"),
        })
        an = md.parent / "analysis.json"
        if an.exists():
            try:
                posts[pid]["analysis"] = json.loads(an.read_text(encoding="utf-8"))
            except Exception:
                pass

    # rich analysis export (has summaries, tips, transcripts)
    if results_jsonl and results_jsonl.exists():
        for line in results_jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            pid = str(r.get("post_id"))
            if pid:
                posts.setdefault(pid, {"post_id": pid, "analysis": {}})
                posts[pid]["analysis"] = r.get("analysis", {})
                posts[pid].setdefault("shortcode", r.get("shortcode"))
                posts[pid].setdefault("url", r.get("url"))
                posts[pid].setdefault("caption", r.get("caption"))

    return list(posts.values())


def text_blob(post: dict) -> str:
    """Concatenate all text signals from a post, lowercased."""
    a = post.get("analysis", {})
    parts = [post.get("caption", "") or ""]
    for k in ("summary", "transcript"):
        v = a.get(k)
        if v:
            parts.append(str(v))
    for k in ("tags", "concepts", "tips", "workflow_steps", "tools_apps"):
        v = a.get(k)
        if v:
            parts.append(" ".join(
                str(x) if isinstance(x, str) else json.dumps(x) for x in v
            ))
    return " ".join(parts).lower()


def score(post: dict) -> tuple[int, list[str]]:
    blob = text_blob(post)
    return len(set(s for s in GROWTH_SIGNALS if s in blob))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="../scrape-ig-saved-list/data/ingest")
    ap.add_argument("--results-jsonl",
                    default="../scrape-ig-saved-list/data/exports/results.jsonl")
    ap.add_argument("--out", default="data/step-neg1/creator-growth-candidates.json")
    ap.add_argument("--threshold", type=int, default=MEDIUM_THRESHOLD)
    args = ap.parse_args()

    posts = load_posts(Path(args.data_dir), Path(args.results_jsonl))
    print(f"loaded {len(posts)} posts")

    scored = []
    for p in posts:
        n = score(p)
        if n >= args.threshold:
            scored.append({**p, "signal_score": n})

    scored.sort(key=lambda x: x["signal_score"], reverse=True)

    strong = [p for p in scored if p["signal_score"] >= STRONG_THRESHOLD]
    medium = [p for p in scored if MEDIUM_THRESHOLD <= p["signal_score"] < STRONG_THRESHOLD]

    print(f"  strong candidates (>=4 signals): {len(strong)}")
    print(f"  medium (2-3):                     {len(medium)}")

    out = {
        "activity": "step-neg1-creator-growth-triage",
        "method": "lexical/dictionary triage over captions + analysis.json (no LLM)",
        "threshold": args.threshold,
        "strong_count": len(strong),
        "medium_count": len(medium),
        "strong": strong,
        "medium": medium,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {args.out}")

    # compact console summary
    print("\nTop 12 strong candidates:")
    for p in strong[:12]:
        a = p["analysis"]
        dom = ",".join(a.get("domains", [])[:3]) if a else ""
        print(f"  [{p['signal_score']}] {p.get('shortcode','?')} | {a.get('content_type','?') if a else '?'} | {dom} | {(p.get('caption') or '')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
