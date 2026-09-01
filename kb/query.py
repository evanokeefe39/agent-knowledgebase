"""kb_query surface: search, retrieval, and grounded answering over the KB corpus.

Three modes:
  - search: keyword/field-scoped ranking over corpus records.
  - get_post: exact lookup by post_id or shortcode.
  - answer: deterministic, grounded synthesis over top search hits with abstention.

CLI:
  python -m kb.query --search "landing page tips" --domain ui_ux
  python -m kb.query --get <post_id>
  python -m kb.query --answer "how do I structure onboarding?"
  python -m kb.query --summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_CORPUS_PATH = "data/uiux/kb-posts.json"

_STOPWORDS = {
    "a", "an", "the", "what", "does", "do", "is", "are", "was", "were",
    "about", "say", "says", "corpus", "posts", "post", "cover", "covers",
    "me", "it", "to", "for", "of", "in", "on", "with", "tell",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Fields concatenated into the searchable text blob. "caption" is honored if a
# record ever carries one; otherwise summary serves as the caption-like text.
_TEXT_FIELDS = ("summary", "workflow_steps", "tips", "transcript", "caption", "tags", "concepts")


def load_corpus(path: str | Path = DEFAULT_CORPUS_PATH) -> list[dict]:
    """Load the KB corpus (list of KbPost dicts) from a JSON file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("posts", data.get("records", []))
    return list(data)


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens from text."""
    return _TOKEN_RE.findall(text.lower())


def _field_text(record: dict, field: str) -> str:
    """Flatten a record field (str, list of str, or missing) into text."""
    val = record.get(field)
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (list, tuple)):
        return " ".join(str(item) for item in val)
    return str(val)


def _searchable_text(record: dict) -> str:
    """Concatenate searchable fields into one lowercase text blob."""
    return " ".join(_field_text(record, f) for f in _TEXT_FIELDS)


def _token_field_matches(record: dict, token: str) -> set[str]:
    """Return the set of searchable fields in which a token appears."""
    fields: set[str] = set()
    for f in _TEXT_FIELDS:
        if token in _tokenize(_field_text(record, f)):
            fields.add(f)
    return fields


def _as_bool(val) -> bool:
    """Coerce corpus scalar ('True'/'False'/bool/None) to bool."""
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() == "true"


def _as_float(val) -> float | None:
    """Coerce corpus scalar to float, or None when missing/unparseable."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def search(
    records: list[dict],
    query: str,
    domains: list[str] | None = None,
    content_type: str | None = None,
    owner: str | None = None,
    tools: list[str] | None = None,
    gated: bool | None = None,
    value_score_min: float | None = None,
    top_k: int = 20,
) -> list[dict]:
    """Keyword/field-scoped search over KB records.

    Matches query tokens against the concatenated searchable text
    (summary + workflow_steps + tips + transcript + caption + tags + concepts).
    Pending records still match via these fields. Optional filters:
    domains (any-of list), content_type (exact), owner (exact), tools
    (any-of against tools_apps), gated (gated_content bool),
    value_score_min (minimum value_score). Score = number of distinct
    query tokens matched anywhere. Returns up to top_k results sorted by
    score desc, each {post_id, shortcode, url, owner, score, rank,
    matched_fields}.
    """
    tokens = sorted(set(_tokenize(query)) - _STOPWORDS)
    if not tokens:
        return []

    domain_filter = [d.lower() for d in domains] if domains else None
    tool_filter = [t.lower() for t in tools] if tools else None

    scored: list[tuple[int, dict, set[str]]] = []
    for rec in records:
        if domain_filter:
            rec_domains = [str(d).lower() for d in (rec.get("domains") or [])]
            rec_domains.append(str(rec.get("domain") or "").lower())
            if not any(d in rec_domains for d in domain_filter):
                continue
        if content_type is not None and str(rec.get("content_type") or "") != content_type:
            continue
        if owner is not None and str(rec.get("owner") or "") != owner:
            continue
        if tool_filter:
            rec_tools = [str(t).lower() for t in (rec.get("tools_apps") or [])]
            if not any(t in rec_tools for t in tool_filter):
                continue
        if gated is not None and _as_bool(rec.get("gated_content")) != gated:
            continue
        if value_score_min is not None:
            vs = _as_float(rec.get("value_score"))
            if vs is None or vs < value_score_min:
                continue

        blob = _searchable_text(rec)
        matched_fields: set[str] = set()
        matched = 0
        for tok in tokens:
            fields = _token_field_matches(rec, tok)
            if fields or tok in blob:
                matched += 1
                matched_fields |= fields
        if matched:
            scored.append((matched, rec, matched_fields))

    scored.sort(key=lambda t: (-t[0], str(t[1].get("post_id") or "")))
    results = []
    for rank, (score, rec, fields) in enumerate(scored[:top_k], start=1):
        results.append(
            {
                "post_id": rec.get("post_id"),
                "shortcode": rec.get("shortcode"),
                "url": rec.get("url"),
                "owner": rec.get("owner"),
                "score": score,
                "rank": rank,
                "matched_fields": sorted(fields),
            }
        )
    return results


def get_post(records: list[dict], post_id: str | None = None, shortcode: str | None = None) -> dict | None:
    """Return the full record matching post_id (preferred) or shortcode, else None."""
    if post_id:
        for rec in records:
            if rec.get("post_id") == post_id:
                return rec
    if shortcode:
        for rec in records:
            if rec.get("shortcode") == shortcode:
                return rec
    return None


def answer(
    records: list[dict],
    question: str,
    top_k: int = 5,
    max_tokens: int | None = None,
    min_score: int = 2,
    min_coverage: float = 0.6,
) -> dict:
    """Grounded, deterministic answer over the top-k search hits.

    Returns {answer, sources, abstained, abstention_reason}. Abstains with
    reason "insufficient_evidence" when search finds no matches, when the
    top hit's score (distinct query tokens matched) is below min_score, or
    when the top hit covers too small a fraction of the query's content
    tokens (below min_coverage) — e.g. a question about "Figma enterprise
    pricing tiers" must not be answered from a post that merely mentions
    "pricing tiers". Otherwise synthesizes a concise summary citing the top
    sources by owner/shortcode and surfaces gated_content/gated_trigger
    when any source is gated.
    max_tokens optionally truncates the answer string by whitespace tokens.
    """
    hits = search(records, question, top_k=top_k)
    sources = [
        {
            "post_id": h["post_id"],
            "shortcode": h["shortcode"],
            "url": h["url"],
            "owner": h["owner"],
            "score": h["score"],
        }
        for h in hits
    ]
    query_tokens = sorted(set(_tokenize(question)) - _STOPWORDS)
    coverage = (hits[0]["score"] / len(query_tokens)) if hits and query_tokens else 0.0
    if not hits or hits[0]["score"] < min_score or coverage < min_coverage:
        return {
            "answer": "",
            "sources": [],
            "abstained": True,
            "abstention_reason": "insufficient_evidence",
        }
    full = [get_post(records, post_id=h["post_id"]) or {} for h in hits]

    # Collect concrete evidence lines: tips, workflow steps, then summary.
    lines: list[str] = []
    for rec in full:
        for tip in rec.get("tips") or []:
            text = tip if isinstance(tip, str) else " ".join(str(v) for v in (tip.values() if isinstance(tip, dict) else tip))
            if text.strip():
                lines.append(text.strip())
        for step in rec.get("workflow_steps") or []:
            text = step if isinstance(step, str) else " ".join(str(v) for v in (step.values() if isinstance(step, dict) else step))
            if text.strip():
                lines.append(text.strip())

    # Gated-source caveat.
    gated_note = ""
    gated_rec = next((r for r in full if _as_bool(r.get("gated_content"))), None)
    if gated_rec is not None:
        trigger = str(gated_rec.get("gated_trigger") or "").strip()
        gated_note = (
            f" Note: source @{gated_rec.get('owner')} ({gated_rec.get('shortcode')}) is gated content"
            + (f" — access via: {trigger}." if trigger else ".")
        )

    summary_parts = [
        f"Based on {len(hits)} source(s): "
        + ", ".join(f"@{h['owner']} ({h['shortcode']})" for h in hits)
        + "."
    ]
    if lines:
        summary_parts.append("Key points: " + " ".join(lines[:5]))
    else:
        for rec in full:
            s = str(rec.get("summary") or "").strip()
            if s:
                summary_parts.append(s)
                break
    summary_parts.append(gated_note.strip())

    answer_text = " ".join(p for p in summary_parts if p)
    if max_tokens is not None and max_tokens > 0:
        answer_text = " ".join(answer_text.split()[:max_tokens])

    return {
        "answer": answer_text,
        "sources": sources,
        "abstained": False,
        "abstention_reason": None,
    }


def summary(records: list[dict]) -> dict:
    """Corpus coverage stats: extraction status, domains, types, gating, owners."""
    status = Counter(str(r.get("extraction_status") or "unknown") for r in records)
    domains = Counter(
        str(d).lower() for r in records for d in (list(r.get("domains") or []) + [r.get("domain")]) if d
    )
    types = Counter(str(r.get("content_type") or "unknown") for r in records)
    gated = sum(1 for r in records if _as_bool(r.get("gated_content")))
    scored = [r for r in records if _as_float(r.get("value_score")) is not None]
    return {
        "total": len(records),
        "extraction_status": dict(status),
        "domains": dict(domains.most_common()),
        "content_types": dict(types.most_common()),
        "gated_count": gated,
        "with_value_score": len(scored),
        "unique_owners": len({str(r.get("owner") or "") for r in records}),
    }


def _main(argv: list[str] | None = None) -> int:
    """CLI entry point for the three query modes plus corpus summary."""
    # Windows consoles/pipes may not be UTF-8 by default.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(prog="kb.query", description="Query the UI/UX knowledge base.")
    parser.add_argument("--search", metavar="QUERY", help="keyword search")
    parser.add_argument("--get", metavar="POST_ID", help="fetch one record by post_id (or shortcode)")
    parser.add_argument("--answer", metavar="QUESTION", help="grounded answer synthesis")
    parser.add_argument("--summary", action="store_true", help="print corpus coverage stats")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS_PATH, help="path to kb-posts.json")
    parser.add_argument("--domain", action="append", help="filter by domain (repeatable)")
    parser.add_argument("--content-type", help="filter by content_type")
    parser.add_argument("--owner", help="filter by owner")
    parser.add_argument("--tools", action="append", help="filter by tool/app (repeatable)")
    parser.add_argument("--gated", choices=["true", "false"], help="filter by gated_content")
    parser.add_argument("--value-score-min", type=float, help="minimum value_score")
    parser.add_argument("--top-k", type=int, default=None, help="max results (search, default 20) / sources (answer, default 5)")
    args = parser.parse_args(argv)

    records = load_corpus(args.corpus)

    if args.summary:
        print(json.dumps(summary(records), indent=2, ensure_ascii=False))
        return 0

    if args.search:
        results = search(
            records,
            args.search,
            domains=args.domain,
            content_type=args.content_type,
            owner=args.owner,
            tools=args.tools,
            gated=None if args.gated is None else args.gated == "true",
            value_score_min=args.value_score_min,
            top_k=20 if args.top_k is None else args.top_k,
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    if args.get:
        rec = get_post(records, post_id=args.get) or get_post(records, shortcode=args.get)
        if rec is None:
            print(json.dumps({"error": f"no record for {args.get!r}"}))
            return 1
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0

    if args.answer:
        result = answer(records, args.answer, top_k=5 if args.top_k is None else args.top_k)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(_main())