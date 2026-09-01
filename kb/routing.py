"""Domain routing over the unified KbPost corpus.

Thin layer on top of kb.query: load the merged corpus (both domains),
scope it to one domain or all, and route free-text questions to a
suggested domain via lightweight keyword heuristics. The actual
search/answer work is delegated to kb.query.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

MERGED_PATH = REPO_ROOT / "data" / "kb" / "kb-posts-all.json"

CANONICAL_DOMAINS = ("uiux", "creator-growth")

# Keywords per domain; matched on token boundaries so e.g. "ui" does not
# fire inside "fruit". Hyphenated keywords (e.g. "content-strategy")
# match either as one hyphenated token or via all their parts.
UIUX_KEYWORDS = [
    "ui",
    "ux",
    "design",
    "figma",
    "canva",
    "layout",
    "font",
    "typography",
    "color",
    "aesthetic",
]
CREATOR_GROWTH_KEYWORDS = [
    "creator",
    "growth",
    "followers",
    "monetize",
    "audience",
    "content-strategy",
    "brand-grow",
]
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "uiux": UIUX_KEYWORDS,
    "creator-growth": CREATOR_GROWTH_KEYWORDS,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TOKEN_HYPHEN_RE = re.compile(r"[a-z0-9-]+")


def load_all() -> list[dict[str, Any]]:
    """Load the unified merged corpus (all domains) as a list of KbPost dicts.

    Prefers data/kb/kb-posts-all.json; if it is missing, falls back to
    building the merge in memory via kb.consolidate (load_merged() when
    available, consolidate() otherwise).
    """
    if MERGED_PATH.exists():
        with open(MERGED_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return list(data)

    from kb import consolidate

    loader = getattr(consolidate, "load_merged", None)
    if loader is not None:
        return list(loader())
    records, _report = consolidate.consolidate()
    return records


def scope(
    records: list[dict[str, Any]],
    domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter records by their `domain` field.

    domains=None or empty keeps everything; otherwise keeps records whose
    `domain` is in the list (case-insensitive). Order is preserved.
    """
    if not domains:
        return list(records)
    wanted = {str(d).lower() for d in domains}
    return [rec for rec in records if str(rec.get("domain") or "").lower() in wanted]


def _keyword_hits(question: str, keywords: list[str]) -> list[str]:
    """Return the keywords matched in question (token-boundary aware)."""
    words = set(_TOKEN_RE.findall(question.lower()))
    hyphenated = set(_TOKEN_HYPHEN_RE.findall(question.lower()))
    matched = []
    for kw in keywords:
        if kw in hyphenated:
            matched.append(kw)
            continue
        parts = [p for p in kw.replace("-", " ").split() if p]
        if all(p in words for p in parts):
            matched.append(kw)
    return matched


def route(question: str) -> dict[str, Any]:
    """Heuristic domain suggestion for a free-text question.

    Returns {suggested_domain, matched_keywords}. Suggested domain is
    "uiux" or "creator-growth" when exactly that group's keywords match
    (uiux wins ties), otherwise "all". matched_keywords lists the
    keywords that fired for the suggestion ("all" -> empty list).
    """
    hits = {domain: _keyword_hits(question, kws) for domain, kws in DOMAIN_KEYWORDS.items()}
    if hits["uiux"]:
        suggested, matched = "uiux", hits["uiux"]
    elif hits["creator-growth"]:
        suggested, matched = "creator-growth", hits["creator-growth"]
    else:
        suggested, matched = "all", []
    return {"suggested_domain": suggested, "matched_keywords": matched}


def query(
    question: str,
    domains: list[str] | None = None,
    mode: str = "answer",
    **kwargs: Any,
) -> dict[str, Any]:
    """One-call convenience: scope the corpus, then search/answer it.

    domains=None/empty -> all domains. mode="answer" (default) delegates
    to kb.query.answer and returns its result plus a `scope` field;
    mode="search" delegates to kb.query.search and returns
    {"results": [...], "scope": {...}}. Remaining kwargs pass through to
    the underlying kb.query function.
    """
    # Imported here to avoid circular imports.
    from kb import query as kb_query

    records = load_all()
    scoped = scope(records, domains)
    scope_meta = {"domains": list(domains) if domains else None, "n_records": len(scoped)}
    if mode == "search":
        results = kb_query.search(scoped, question, **kwargs)
        return {"results": results, "scope": scope_meta}
    if mode != "answer":
        raise ValueError(f"unknown mode: {mode!r} (expected 'answer' or 'search')")
    result = kb_query.answer(scoped, question, **kwargs)
    result["scope"] = scope_meta
    return result


def _main(argv: list[str] | None = None) -> int:
    """CLI: corpus summary, routing suggestion, or scoped query."""
    # Windows consoles/pipes may not be UTF-8 by default.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(prog="kb.routing", description=__doc__)
    parser.add_argument("--summary", action="store_true", help="print total + per-domain record counts")
    parser.add_argument("--route", metavar="QUESTION", help="print the domain routing suggestion")
    parser.add_argument("--query", metavar="QUESTION", help="scoped kb.query answer over the merged corpus")
    parser.add_argument("--domains", action="append", help="restrict --query to a domain (repeatable)")
    parser.add_argument("--search", action="store_true", help="with --query: return search hits instead of an answer")
    args = parser.parse_args(argv)

    if args.summary:
        records = load_all()
        counts = Counter(str(rec.get("domain") or "") for rec in records)
        print(json.dumps({"total": len(records), "domains": dict(counts)}, indent=2, ensure_ascii=False))
        return 0

    if args.route:
        print(json.dumps(route(args.route), indent=2, ensure_ascii=False))
        return 0

    if args.query:
        result = query(args.query, domains=args.domains, mode="search" if args.search else "answer")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
