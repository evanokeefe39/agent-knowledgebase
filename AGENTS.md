# Agent Knowledge Base — Agent Operating Context

This repo is operated by coding agents (Claude Code, oh-my-pi). Keep this file
current — agents read it on every session.

## Status

Research / discovery. No implementation yet. The deliverable is
`docs/` — requirements, 2026 research, and a proposed architecture.

## Key rules

- **No implementation plans yet.** This is a research/design repo. Do not start
  building the KB without an explicit user go-ahead.
- Never use `pip`. Use `uv` for Python package management.
- Work on `feat/*`, `fix/*`, `chore/*`, `docs/*` branches; squash-merge to `main`
  via PR. Never push directly to `main`.
- Conventional commits only: `type(scope): summary`.
- Keep `main` linear (squash merges). Protected branch: review + CI required.
- Never use PowerShell.

## Repo purpose (one paragraph)

An agent-queryable knowledge base for a domain (UI/UX & design first), derived
from social media (Instagram saved posts), articles, docs, and tabular data, and
exposed to coding agents as a tool/skill/plugin. The POC is **content/knowledge**,
distinct from the datalake's **creator-analysis** focus, though it consumes from
both source repos. Grounded in 2026 research: hybrid retrieval (BM25+dense+RRF),
guarded text-to-SQL over curated views, a single multimodal embedding model, and
skill-first packaging with optional MCP.

## What NOT to do (boundaries)

- **Do not modify `~/repos/scrape-ig-saved-list` or `~/repos/datalake`** from
  this repo. The KB is a derived consumer of both; it reads snapshots/views, it
  never writes into them.
- Do not fabricate research findings. All `docs/` claims carry citations; verify
  before asserting.
- Do not commit `.env`, credentials, media bytes, or large generated artifacts.
- Do not treat saved-post knowledge as truth about the world beyond the corpus —
  the KB is scoped to the curated library.

## Key source repos (read-only context)

| Repo | What the KB takes from it |
|---|---|
| `~/repos/scrape-ig-saved-list` | `analysis.json` (extracted resources/steps/tips/CTAs/transcripts), Apify metadata + media, snapshot export contract |
| `~/repos/datalake` | Gold-layer views (creators SCD2, post metrics, domains), Gemini enrichment-worker pattern, R2 media bytes + cache conventions |

## Architecture (proposed) — see `docs/architecture.md`

Thin FastAPI facade over stores you already own: `/schema` (capability manifest),
`/search` (hybrid BM25+dense+RRF+rerank), `/query` (guarded text-to-SQL over
curated gold views), `/post` (provenance). Packaged as an Agent Skill
(`SKILL.md` + CLI), MCP optional. Single multimodal embedding model (Gemini
Embedding 2, batch, 768-dim). Agent routes itself from the manifest; no learned
router.

## Current design decisions (2026-08-31)

- **Skill-first packaging** (not MCP-primary): snapshot data + coding agent →
  filesystem-native skill + CLI; MCP as optional adapter.
- **Hybrid retrieval** is the production default; vector-only is a baseline liability.
- **Both** media extract-once and embeddings (text primary; per-slide/keyframe
  visual for the ~50-post visual subset).
- **One multimodal embedding model** — Gemini Embedding 2; A/B only if a spike
  underdelivers; never double-index (index whole corpus once).
- **Guarded text-to-SQL** over a curated semantic layer; abstention first-class.
- **20-post spike is the extraction quality gate**, not the demo corpus — index
  all 809 for the value demonstration.

## Open questions (tracked in `docs/RESEARCH.md` §6)

Source-selection reliability · silent-wrongness / verifiability · extraction
tiering pre-filter · KB↔source data contract · embedding model churn ·
video-volume economics · gated-resource resolution.

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-08-31 | Skill-first packaging, MCP optional | Snapshot KB + coding agent → filesystem skill fits better than a protocol server; no live server needed; progressive disclosure |
| 2026-08-31 | Hybrid retrieval (BM25+dense+RRF) | 2026 production default; vector-only is a baseline liability |
| 2026-08-31 | Both media extract-once + embeddings | Media value is text-in-image + visual; neither alone suffices |
| 2026-08-31 | Single multimodal embedding model (Gemini Embedding 2) | Only 2026 product with batch-discounted unified text+image+video; in-stack; sub-$1 corpus cost |
| 2026-08-31 | Guarded text-to-SQL over curated views | Works on clean small schema; guardrails mandatory before any agent |
| 2026-08-31 | 20-post slice = quality gate; full 809 for demo | Full corpus already extracted at ~zero cost; 20 is the correctness gate only |
