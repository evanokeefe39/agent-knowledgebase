# Agent Knowledge Base — POC Architecture

**Status:** Proposed architecture for the POC (research-backed; not yet implemented).
**Date:** 2026-08-31

This is the concrete architecture the POC will build — thin, grounded in the 2026
research in `docs/research/`, and refined by the expert panel (`docs/expert-panel.md`)
plus your packaging and media-embedding decisions.

---

## Design thesis

Build a **thin query facade over stores you already own**, with routing delegated
to the agent rather than a learned server-side router. Do not build a "RAG
platform." The risk is overbuilding — not feasibility.

## System diagram

```
Coding agent (oh-my-pi / Claude Code / Cursor)
   │  Agent Skill (SKILL.md, progressive disclosure) + optional MCP adapter
   ▼
KB service (thin, FastAPI) — the ONLY thing this repo builds
   · /schema  → capability manifest (stores, contents, example queries, cost class)
   · /search  → hybrid retrieval (BM25 + dense → RRF → rerank)
   · /query   → guarded text-to-SQL over curated gold views (SELECT-only, read-only)
   · /post    → point lookup / provenance
   └──┐         ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
      │         │ DuckDB   │   │ pgvector │   │ media-   │   │ raw bytes│
      │         │ gold     │   │ +BM25    │   │ meta idx │   │ (R2,     │
      │         │ views    │   │ (one     │   │ (slides, │   │ content- │
      │         │ (guarded │   │ text per │   │ frames,  │   │ addressed│
      │         │ SQL)     │   │ post)    │   │ CTA flags│   │ signed   │
      │         └──────────┘   └──────────┘   └──────────┘   │ URLs)    │
      │                                                  └──────────┘
   ◄── snapshot ingestion (scrape repo) + read-only gold consumer (datalake)
```

## Core decisions

### 1. Packaging — skill-first, MCP optional
The KB is a self-contained **Agent Skill** (`SKILL.md` + a CLI that calls the same
REST service). No live server required for the agent; progressive disclosure (~100
tokens to load the skill; body only on trigger). **MCP is an optional adapter**
added only if a second consumer or live data appears. Rationale: the KB serves
*snapshot* data to a *coding* agent — the filesystem-native skill pattern fits
better than a protocol server, is self-contained and robust, and matches the
coding-agent philosophy.

### 2. Retrieval — hybrid, not vector-only
**BM25 + dense embeddings → RRF → cross-encoder rerank** over a **single unified
index**. Each post's extracted text (`analysis.json` fields + transcript +
captions) is chunked **by field, not by size** — `tips`, `workflow_steps`,
`resources`, `concepts` are already atomic units; index them with provenance
`(post_id, field)`. Carousel slide text and video-frame metadata live in the same
index with a `media=true` flag.

### 3. Embeddings — one multimodal model
**Gemini Embedding 2** (batch API), truncated to **768-dim** (MRL).
- **Text** (all 809 posts): transcript + caption + analysis fields. Transcript is
  the primary retrieval surface (Gemini video embedding ignores audio).
- **Visual** (~50-post subset): per-slide / per-keyframe embeddings for carousel
  slides and reel frames.
- **Cost:** < $1 (images) + ~$10.50 (all video, batch). Negligible — the dominant
  cost is the Gemini *extraction* already running.
- Alternative: **Voyage multimodal-3.5** if an eval shows visual-doc retrieval needs
  it (strongest independent 2026 benchmark; free tier covers the corpus).

### 4. Structured tier — guarded text-to-SQL
A curated **semantic layer** (3–5 read-only gold views: creators SCD2, posts,
domains, tools) is the *only* text-to-SQL entry point. SELECT-only on a read-only
replica; SQL guards (parse, not regex; deny mutation functions); row caps;
statement timeouts; abstention on low confidence. Text-to-SQL works here because
the schema is small and clean — the case where it stays strong (85–95%+).

### 5. Routing — the agent decides, not the server
Expose **`/schema`** (a capability manifest describing each store, its contents,
example queries). The agent reads it once and routes itself — testable and what
agents are good at. **No learned federated router** (experimental in 2026).
The SKILL.md encodes heuristics: "metrics/aggregations → /query; 'how do I do X'
→ /search; visual content → /search media=true; creator identity → /post."

### 6. Integration — KB is a derived consumer, never a second writer
- **From `scrape-ig-saved-list`:** consume a **snapshot export** (versioned
  JSONL/Parquet of `{post_id, creator, media_ref, analysis fields, scrape
  timestamp}`); ingest idempotently by `post_id` + content hash.
- **From `datalake`:** register as a **read-only gold consumer** (DuckDB views,
  the Gemini-worker pattern for new extraction, R2 bytes + cache conventions).
- Upstream repos own extraction; the KB owns indexing/search/serving. One-directional.

### 7. Guardrails (non-negotiable before any agent touches it)
- Read-only, hard-guaranteed — the service has no write path at all.
- Every extracted entity carries provenance `{source_post_id, media_ref,
  extractor_model, confidence}`; no field without provenance is queryable.
- Abstention is a first-class result (`insufficient_evidence`).
- Only records passing confidence thresholds are indexed as asserted facts;
  sub-threshold queried as flagged raw metadata.
- Rate/cost caps on any lazy extraction (batch only, queue not synchronous).

## Build order

1. **Write the eval + gold set first** (25–50 questions, graded relevance 2/1/0,
   expected store) — it gates everything.
2. **E3 — text-to-SQL probe** (~1 day): cheapest, most likely to kill or confirm.
3. **E1 — extraction-quality probe** on 20 posts: the silent-wrongness gate; check
   if existing `analysis.json` already clears it.
4. **Embedding spike** — 50-post visual subset + gold set → Recall@5/MRR; strong →
   index the whole corpus once in batch (never double-index).
5. **Vertical slice** — index all 809 (already extracted, ~free); A/B: same
   questions with vs. without the KB, rubric-scored by a fresh-context judge.
6. **Kill criteria hold:** if agents don't query it or it doesn't beat baseline,
   stop — the honest POC answer is worth more than an overbuilt KB.

## Spike / experiment summary

| Spike | What it proves | Pass signal |
|---|---|---|
| E1 media extraction | Extraction is trustworthy (no fabricated resources) | ≥85% precision / ≥70% recall on high-value fields |
| E2 retrieval | Hybrid beats single-method | Hybrid wins ≥60%; top-3 contains answer ≥80% |
| E3 text-to-SQL | Guarded SQL is safe+useful on our schema | ≥8/10 correct with semantic layer |
| E4 routing | Agent picks the right store from tool descriptions | ≥80% correct store picks |
| Embedding spike | One multimodal model suffices | Strong Recall@5/MRR on 50-post gold set |

## Out of scope (for the POC)

GraphRAG / multi-hop graph indexing · learned federated router · self-hosted open
embeddings · full-scale video transcript derivation · incremental ingestion ·
Web UI · multi-user · Postgres migration (SQLite/DuckDB + local vector store is
enough for 809 docs).

## Re-evaluation triggers — when to revisit hybrid fusion / Postgres

The M4 ablation (2026-09-01, `docs/uiux-build-plan.md`) established the baseline:
on the 24-question gold set, **dense** is the strongest single channel
(R@5=0.972, R@10=1.0), **hybrid (RRF)** matches dense at R@10/MRR but is slightly
*lower* at R@5 (0.917), and **BM25** is weakest (R@5=0.781). Hybrid's win-rate vs
dense is **0.0%** — dense beats or ties hybrid on every gold question.

**The architecture is driven by channel overlap, not corpus size.** "185 vs
100k vectors" is not itself the trigger for Postgres/pgvector — the gap is about
whether lexical and semantic retrieval still overlap, not about raw scale. Fusion
earns its complexity only when the two channels serve *distinct, non-overlapping*
slices of the corpus.

**Re-run the gold ablation on each material corpus expansion** (cheap —
`kb/dense.py` is idempotent/incremental, so new posts embed without a full
re-embed; `uv run python -m kb.hybrid --ablation`). Re-evaluate fusion and the
file-backed-vs-Postgres decision when any of these fire:

1. **Hybrid's win-rate vs dense crosses the ≥60% bar** (currently 0.0%). Until
   hybrid wins a slice dense alone misses, RRF adds complexity, not value.
2. **Lexical-miss rate rises** — the count of gold questions where *dense is
   correct but BM25 misses*. This is the failure mode fusion exists to rescue;
   when it is non-trivial and dense's hits are not already in hybrid's top-10,
   fusion has a reason to exist.
3. **Per-domain results diverge** — run the gate split by domain (uiux vs
   creator-growth). Divergence (one domain turning paraphrase-heavy, the other
   lexical) is the real architecture pressure point and the honest way to catch
   trigger 1 emerging.

Until a trigger fires, the file-backed stack (SQLite FTS5 + sqlite-vec) stands;
pgvector/Postgres stays the documented production migration path, not a build
target. Every gate is version-keyed
`(schema_version, index_version, eval_set_version)`, so a re-run is attributable
to exactly what changed in the corpus.
