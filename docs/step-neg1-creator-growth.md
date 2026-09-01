# Step −1: Creator-Growth Triage (quick value)

**Branch:** `feat/step-neg1-creator-growth-triage`
**Purpose:** find the posts in the saved corpus that are about **content creator
growth / social content practice**, so we can start extracting value from them
immediately — before any full POC infrastructure is built.

## Method

Cheap **lexical/dictionary triage** (no LLM spend) over the full corpus:

- Scans every post's caption + `analysis.json` fields (summary, transcript, tips,
  workflow_steps, concepts, tags, tools_apps) for ~70 growth/social-practice
  keyword signals (audience, monetization, content strategy, platforms, etc.).
- Scores each post by **number of distinct signals** present.
- Tiers: **strong** (≥4 signals), **medium** (2–3), below threshold (ignored).

This is a *pre-filter*: it shrinks the corpus cheaply before any paid AI
extraction. An LLM pass can refine the ranking later.

## Results (2026-08-31)

| Tier | Posts | Est. tokens (full dump) |
|---|---|---|
| Strong (≥4 signals) | **94** | ~60K |
| Strong + Medium (≥2) | **328** | ~161K |
| Full analyzed corpus | 309 | ~225K |

**The 1M-context hypothesis holds.** The strong subset (~60K tokens) fits in a
1M-token window with ~94% headroom; even the strong+medium set (~161K tokens)
fits comfortably. This means we can **stuff the entire narrowed corpus into one
context window** and ask questions directly — no retrieval/RAG infrastructure
needed for step −1.

## Outputs

- `triage_creator_growth.py` — reproducible triage script (point at the scrape
  repo's `data/ingest` + `results.jsonl`).
- `data/step-neg1/creator-growth-candidates.json` — the ranked list:
  - `strong[]`: 94 posts (high-confidence creator-growth / social-practice)
  - `medium[]`: 234 posts (probable)
  - each entry: `shortcode`, `url`, `owner`, `caption`, `signal_score`, and
    `analysis` (where present)

## How to use it

1. The **94 strong candidates** are the immediate extraction target — deep AI
   extraction (resources, workflow steps, tips, gated-content/CTA) on just these.
2. Roughly **39/94** already have rich `analysis.json`; the rest are caption-only
   and would need extraction.
3. Entire narrowed set fits one 1M context window → can be answered directly by a
   coding agent without building the hybrid-search/text-to-SQL stack from the POC
   architecture.

## Note

This is intentionally a **step −1 hack for immediate value**, not the full POC.
The POC architecture (`docs/architecture.md`) remains the target for scale; this
gets value flowing now.
