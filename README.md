# agent-knowledgebase — POC

Research and design for an **agent-queryable knowledge base** built from
social media content, articles, docs, tabular data, and any structured /
semi-structured / unstructured data — exposed to coding agents (Claude Code,
oh-my-pi, Cursor, etc.) via a REST API + CLI/Web, packaged as a tool / skill /
plugin.

**Status: research / discovery only. No implementation plan yet.**

## Repo map

- `docs/RESEARCH.md` — the main structured document: idea, requirements,
  research threads, 2026 tech landscape, existing solutions, costs, and the
  media extraction-vs-embedding deep dive.
- `docs/expert-panel.md` — recommendations from a panel of experts (PM,
  architect, staff engineer, ML engineer) on how to explore/validate the idea
  and what docs to prepare for the POC.

## Related source repos

This POC builds on and references two existing projects:

- **`~/repos/scrape-ig-saved-list`** — Apify `instagram-scraper` pipeline that
  extracts saved Instagram posts (rich metadata + media: videos, carousel
  images). Media holds most of the value (listicles in carousel images; video
  transcripts + visual aids). 557 distinct profiles / 809 posts. Includes a
  Gemini-based analysis pipeline (`quick_analyze.py`) that already extracts
  structured knowledge (resources/URLs, workflow steps, tips, concepts,
  gated-content/CTA detection) per post into `analysis.json`.
- **`~/repos/datalake`** — medallion lakehouse (bronze/silver/gold Parquet +
  DuckDB + SQLite) with Gemini enrichment, async batch worker, media byte
  cache, and a `creators`/`profiles` (SCD2) model. Focused on **creator
  analysis**. This POC's KB is a distinct layer oriented at **content /
  knowledge** (not just creators), and will likely consume from both.

## How to use this repo

Read `docs/RESEARCH.md` for the full picture. It is intentionally a
requirements-and-research artifact, not an implementation spec — it captures
the idea, open questions, technology landscape, and the research threads we
must investigate before committing to any technology.
