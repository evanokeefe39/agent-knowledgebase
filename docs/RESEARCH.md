# Agent Knowledge Base — POC Requirements & Research Document

**Status:** Research / discovery. No implementation plan.
**Date:** 2026-08-31
**Repo:** `agent-knowledgebase` (this repo)
**Related source repos:** `~/repos/scrape-ig-saved-list`, `~/repos/datalake`

---

## 1. Intent

Build an **agent-queryable knowledge base** — a domain- and sub-domain-oriented
knowledge layer (e.g. UI/UX & design as the first domain) derived from social
media content, articles, docs, tabular data, and essentially any structured,
semi-structured, or unstructured data. The KB is exposed to coding agents
(oh-my-pi, Claude Code, Cursor, etc.) through a **REST API with a CLI/Web
client**, packaged as a **tool / skill / plugin** for those agents.

The motivation: agents are good at decomposing broad, poorly-defined questions
into sub-queries, steps, and investigations, and at asking the user clarifying
questions. This KB gives them a grounded, queryable knowledge surface so they do
**less guesswork** — and it complements whatever other tools the agent has
access to. The agent makes contextual decisions about which data is relevant
given a result set.

This POC is **explicitly about content/knowledge**, distinct from the datalake's
focus on **creator analysis**. The two are related: the KB may consume from both
the scrape pipeline and the datalake, but its purpose is queryable knowledge,
not creator analytics.

**What this document is:** a requirements + research artifact. It captures the
idea, the behavioral requirements we think we need, the existing assets, the
research threads we must investigate, the 2026 technology landscape, and the
open questions. It is **not** an implementation spec.

---

## 2. Requirements (draft, non-committal)

### 2.1 Functional

- **Multi-format ingestion:** consume structured (tables, JSON), semi-structured
  (docs, transcripts, analysis payloads), and unstructured (media-derived text,
  captions, articles) data.
- **Media as first-class input:** carousel images (listicles are text-in-image),
  videos (transcript + on-screen/visual context), and their metadata. Extract
  reusable knowledge, not just captions.
- **Federated/hybrid search:** query across structured (SQL), unstructured
  (vector + lexical), and media-derived metadata; the agent should be able to
  decide which store(s) to query and consolidate evidence.
- **Agent-facing interface:** REST API + CLI/Web, packaged as a tool/skill/plugin
  (e.g. MCP server + Agent Skill) usable by coding harnesses.
- **Clarity workflow:** support agent decomposition of broad questions into
  sub-queries and investigations, surfacing uncertainty to the user.

### 2.2 Non-functional

- **Cost control:** media extraction and embeddings must be tiered so the
  expensive vision pass is reserved for high-value items (research: ~$0.002/min
  image/video on Gemini Flash; total POC envelope < $100 one-time, < $50/mo).
- **Verifiability / guardrails:** silent-wrongness (plausible-but-wrong answers)
  is the top reliability risk. SQL guards, read-only surface, quality gates, and
  abstention on low confidence are mandatory before any agent is pointed at it.
- **Model/version discipline:** derived data is versioned (schema + model +
  prompt hash) so a model upgrade re-extracts without re-scraping.
- **Raw-media retention:** keep original bytes; extraction/embeddings are
  regenerable, never chained such that re-indexing requires re-scraping.

### 2.3 Out of scope (for this POC)

- Creator analytics (that's the datalake).
- Production hosting / multi-machine / cloud warehouse.
- A final technology commitment.

---

## 3. Context — existing assets

### 3.1 `~/repos/scrape-ig-saved-list`

Apify `instagram-scraper` pipeline that scrapes saved Instagram posts:

- **557 distinct creator profiles / 809 posts** across two saved-list datasets.
- Rich metadata + media: videos, carousel images. **Media holds most of the
  value** — listicles render as carousel images (text-in-image); videos carry
  narration + on-screen visual aids.
- **`quick_analyze.py` already extracts structured knowledge per post** via
  Gemini (`gemini-3.1-flash-lite`, schema v2) into `analysis.json`:
  - `is_educational`, `value_score` (1-5), `content_type`, `summary`, `domains`
  - `resources[{name,url,type,purpose}]` (reads URLs off slides)
  - `workflow_steps[]`, `tips[]`, `concepts[]`, `tools_apps[]`, `tags[]`
  - `gated_content` + `gated_trigger` (CTA/gate detection)
  - `transcript` (video: speech + interleaved scene notes; carousel: ordered
    `[slide N]` text)
  - `MAX_SLIDES=12`, archive of old analysis versions (`data/archive/`)
- Media downloader (`download_media.py`) with parallel downloads, resume, input
  overrides.

**Key gap for the KB:** `analysis.json` is the *extraction* output. It is not yet
indexed for retrieval, not exposed via any query interface, and embeddings are
not computed.

### 3.2 `~/repos/datalake`

Medallion lakehouse (bronze/silver/gold Parquet + DuckDB + SQLite):

- Apify → bronze Parquet; silver dedup; async Gemini enrichment worker (batch
  queue, per-item backoff, dead-letter); serving views.
- `creators` + `profiles` tables (SCD2) — a person/brand owns 1..N profiles.
- Media byte cache (scrape-time; CDN URLs die in ~4-5 days).
- Focused on **creator analysis** (quality, rising, outliers, domain coverage).
- **Current gap (per its AGENTS.md):** `ig_posts_slv` hardcodes
  `media_files = "[]"` / `media_count = 0`, so media never reaches Gemini —
  gold enrichment is text-only today.

### 3.3 Relationship

The KB is a distinct **content/knowledge layer**. It will likely **consume** from
both: post metadata/media + analysis from the scrape repo, and profile/creator
structure + a consumption path from the datalake. The exact boundary is an open
architecture question (see §6).

---

## 4. Research threads (what we must investigate)

Each thread below is a live research area. The per-thread research memos live in
`docs/research/`. These are the questions that determine what's possible.

### 4.1 Search method for unstructured data (2026)

**Thread: Is vector RAG still best, or are there more mature approaches?**

Findings (see `docs/research/kb-search-state-of-art.md`):
- Plain vector RAG is a **baseline liability**. **Hybrid search (BM25 + dense +
  RRF, with a cross-encoder reranker)** is the 2026 production default — it's
  "the single highest-impact retrieval upgrade."
- **GraphRAG / knowledge graphs** help only for multi-hop relational questions;
  can *underperform* vanilla RAG on single-hop QA. Use selectively, defer.
- **Agentic/iterative RAG** is maturing.
- **SQL-over-unstructured** (structured RAG) is a rising pattern.
- **Text-to-SQL** is mature for small/clean schemas (our DuckDB/SQLite tier)
  but "performance cliffs" on complex schemas. Viable only behind a curated
  semantic layer + guardrails.

### 4.2 Media extraction vs embedding (the deep dive)

**Thread: for media, is it better to extract structured info once, embed/vectorize the media, or both?**

Findings (see `docs/research/media-extraction.md`):
- **Both.** Extract structured text ONCE with a native multimodal LLM (cheap —
  ~fraction of a cent/post), AND emit per-slide/key-frame visual embeddings.
  Never choose text-only extraction as the sole path where layout/visual is the
  primary value carrier (listicles in carousel slides).
- Multimodal VLMs have largely absorbed OCR for clean carousel text.
- Apify does **not** provide transcripts — derive from the `.mp4` (Gemini native
  video, or local Whisper for speech-only).
- Video needs transcript + key-frame/on-screen-text extraction for full value.
- CTA/gated-content detection is **reliable as a structured field** (mostly
  lexical); can't resolve the gated payload itself (only the trigger).

### 4.3 Existing solutions & costs

**Thread: what's aligned (not 100%), and what does it cost?**

Findings (see `docs/research/costs-and-solutions.md`):
- **LlamaIndex** is the best framework fit (ingestion/retrieval-first, tables +
  text + metadata). LangGraph for heavy agent orchestration.
- Vector stores: **pgvector on existing Postgres ≈ $0 marginal**; Qdrant/Pinecone
  add $30-120/mo; Pinecone has a $50/mo floor (overkill for 809 posts).
- **Build-on-thin-layer beats turnkey**: no off-the-shelf platform handles the
  bespoke media path. DIY extraction + indexing + thin MCP/REST facade.
- Media bytes → **Cloudflare R2** (free egress). Derived data → versioned.
- **Cost envelope: < $100 one-time, < $50/mo** for the POC at this scale.

### 4.4 Agent integration & packaging

**Thread: how do we expose the KB to coding agents?**

Findings (see `docs/research/kb-search-state-of-art.md` §4):
- **MCP** is the de-facto standard (Linux-Foundation-governed; adopted across
  Anthropic/OpenAI/Google/Microsoft). This is the REST/CLI-to-agent bridge.
- **Anthropic Agent Skills (SKILL.md)** is the progressive-disclosure
  instruction format; rides on top of an MCP server.
- Multi-agent orchestration: prefer sub-agent-per-store with an orchestrator.

---

## 5. 2026 Technology Landscape (summary)

| Capability | Mature 🟢 | Maturing 🟡 | Experimental 🔴 |
|---|---|---|---|
| Hybrid retrieval (BM25+dense+RRF) | 🟢 production default | | |
| Cross-encoder rerank | 🟢 | | |
| Text-to-SQL (clean schema, guarded) | 🟢 | | |
| Text-to-SQL (complex schema) | | 🟡 (cliffs) | |
| Agentic RAG / query routing | | 🟡 | |
| Federated heterogeneous-store routing | | | 🔴 (OmniRetrieval/SQuARE) |
| GraphRAG (selective) | | 🟡 | |
| MCP server packaging | 🟢 | | |
| Agent Skills (SKILL.md) | 🟢 | | |
| Multimodal media extraction (VLMs) | 🟢 | | |
| Multimodal embeddings | 🟢 | | |

**Synthesis:** hybrid retrieval over media-derived text (🟢), a curated-view
text-to-SQL tier over the lake (🟢), and MCP + Agent Skills packaging (🟢) form a
low-risk core. The federated router (🔴/🟡) is where the interesting open problem
lives; start with OmniRetrieval-style long-context source selection over a small
registered catalog.

---

## 6. Open Questions (must be resolved before implementation)

1. **Source-selection reliability:** how does the agent decide which store to
   query (media text vs lake tables vs analysis metadata)? Router accuracy at
   scale is unsolved; tractable for a small hand-registered catalog.
2. **Silent-wrongness:** how do we make answers verifiable / abstain-on-low-
   confidence? This is the top reliability risk for autonomous agents.
3. **Extraction tiering:** what's the right cheap pre-filter to route posts to
   the expensive vision pass without losing high-value content?
4. **Data contract between the KB and the two source repos:** what does the KB
   consume from each, and where does the boundary sit?
5. **Embedding model churn:** which text + multimodal embedding models to lock
   in, knowing re-indexing is the hidden re-cost?
6. **Video volume economics:** is video worth a Tier 2 / batch API at our scale,
   or is triage-first sufficient?
7. **Gated-resource resolution:** can/should the KB capture gated payloads, or
   only triggers + intent (unresolvable without the account owner doing the DM)?

---

## 7. Definition of Done for the POC (draft)

The POC is "done" when it can demonstrate, end-to-end and cheaply:
- A small slice of real media (e.g. 20 posts) runs through: media extraction →
  structured text + embeddings → indexed.
- A coding agent asks a broad domain question and the KB returns grounded,
  evidence-linked answers (hybrid retrieval working on real data).
- A text-to-SQL path answers a structured question against the lake with
  guardrails, on the POC's own schema.
- The whole thing is packaged as an MCP server + Agent Skill consumable by at
  least one harness (oh-my-pi or Claude Code).
- Cost is measured and under budget.

**Expert-panel refinement of the above (success criteria, kill criteria, scope,
and the exact docs to prepare before building) is in [`docs/expert-panel.md`](expert-panel.md).**

---

## 8. Research memo index

- `docs/research/kb-search-state-of-art.md` — 2026 search tech landscape
- `docs/research/media-extraction.md` — media extract-vs-embed deep dive
- `docs/research/media-embeddings.md` — 2026 image/video embedding models, costs,
  model-selection & spike method
- `docs/research/costs-and-solutions.md` — existing solutions + costs
