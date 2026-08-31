# Expert Panel — Approach Validation & POC Readiness

**Panel:** Product Manager · Solution Architect · Staff Engineer · ML Engineer
**Date:** 2026-08-31 · **Inputs:** `docs/RESEARCH.md` + three research memos in `docs/research/`

---

## Panel verdict (unanimous)

**Green-light the POC — but build the smallest instrument that can fail, judge it
honestly, and let kill-criteria do their job.** The unanimous view across all four
roles:

- **Feasibility is not the risk.** Hybrid RAG is a solved production default; MCP
  + Agent Skills packaging is mature; text-to-SQL works on our small clean schema.
- **The real risks are:** (1) agents don't actually query the KB, (2) media
  extraction silent-wrongness (agents quote fabricated resources), (3) text-to-SQL
  exposed unguarded, and (4) scope creep toward a "platform."
- **Overbuilding is the danger.** The POC should be: snapshot in → one hybrid index
  + semantic layer → MCP facade with a capability manifest → agent routes. Defer
  federated routers, graph layers, and media-search UIs until evidence demands them.
- **The single highest-value POC output is a logged query distribution** + a
  gold-set eval harness written before any code.

---

## 1. PM brief — value proof, scope, and success criteria

### Core need / jobs-to-be-done
The real need is **fewer wrong guesses and fewer clarifying questions when
delegating ambiguous tasks to agents** — not "a knowledge base" itself.

**Agent (primary user):** decompose fuzzy requests into sub-queries; ground
recommendations in the user's actual evidence (real posts/workflows/tools); decide
where to look (SQL vs vector vs media) without hand-holding.
**Human:** reuse the curated library as an asset; trust-but-verify every claim to a
source post; zero new workflow (sits on top of Apify + datalake).

**Killer question:** *Does giving the agent structured + hybrid-search access to
this library measurably change answer quality on broad questions vs. baseline?*

### Smallest scope that proves value
1. One `kb_query` tool (modes: `search` hybrid, `structured` SQL over gold views, `get_post`) as an MCP server + SKILL.md.
2. A **curated benchmark of ~10 broad questions written before building** (expected evidence + rubric answers).
3. Hybrid search + rerank over all 809 posts' existing `analysis.json` (zero incremental cost).
4. The "both" media decision on a **~50-post visual subset** (two-tier extraction).
5. **A/B**: same questions answered with vs without the KB, rubric-scored by a fresh-context judge.

Deferred: GraphRAG, federated-router frameworks, full-scale visual extraction,
video transcripts at scale, incremental ingestion, Web UI, Postgres migration
(SQLite/DuckDB + local vector store is fine for 809 docs).

### Success criteria (binary)
1. Fresh agent session discovers + calls `kb_query` with zero setup. Y/N
2. Agent issues ≥2 distinct KB queries on ≥8/10 benchmark questions *without prompting*. Y/N
3. Expected source posts appear in top-5 for ≥8/10 questions. Y/N
4. **Rubric-scored KB answers beat no-KB on ≥7/10 questions** (the money criterion). Y/N
5. Every claim cites a post/row ID; ≥18/20 spot-checked citations resolve. Y/N
6. End-to-end ≤ $50 incremental; per-query ≤ $0.05. Y/N
7. Slide-level extraction measurably helps on ≥2 questions where text-only fails. Y/N (may be partial but must be measured)

**Kill criteria:** if criterion 2 or 4 fails after one round of tool-description/
prompt iteration, the product hypothesis is wrong — stop.

### Risks
**Show-stoppers:** agents don't naturally query the KB (test first with a stub);
corpus too thin for broad questions (narrow positioning to personalized questions
if so); mushy evaluation (fix: write rubrics first, fresh-context judge).
**Mitigable:** media extraction variance (two-tier); mode-routing confusion
(collapse modes, decision-rule descriptions); SQL guards; extraction cost overrun
(Batch API −50%, spend ceiling); packaging drift (pin versions).

---

## 2. Architect brief — target architecture concept

**Thesis:** Don't build a "RAG system." Build a **thin query facade over stores you
already own**, with a contract that makes routing the agent's job, not the server's.

### Components
```
Agents (Claude Code / omp / Cursor) — MCP client · SKILL.md · CLI fallback
  └── REST (search / lookup / schema / sql-read) + MCP
KB Facade (single service):
  · Query API: intent-tagged endpoints (semantic, keyword, sql, media, entity)
  · Hybrid retriever: BM25 + dense → RRF → cross-encoder rerank
  · Semantic layer: table/column docs, entity registry, value catalogs
    (the ONLY text-to-SQL entry point)
  · Source router hints: static per-store capability manifest, NOT a learned router
  └── DuckDB/SQLite (gold views, read-only guarded SQL)
    · pgvector+BM25 (chunks+doc metadata, one text per post)
    · media-meta index (post → slides → OCR/captions/embeddings)
    · raw bytes (R2, content-addressed, CDN URLs)
```

### Where data lives
- **Structured analytics** (creators SCD2, metrics, value_score, domains) → gold Parquet → DuckDB views (read-only, semantic layer + guards).
- **Unstructured text** (analysis.json fields, transcripts, articles) → chunked into Postgres (pgvector dense + tsvector BM25 in one table). **Chunk by field, not by size** — `tips`, `workflow_steps`, `resources`, `concepts` are already atomic units; index them with provenance `(post_id, field)`.
- **Media-derived metadata** → one row per slide/keyframe (extracted text, OCR, CTA flags, visual embedding), in the same hybrid index with a `media=true` flag.
- **Raw media bytes** → R2, content-addressed, immutable. KB never re-processes bytes; returns signed URLs.
- **Entity graph** → SQLite/Postgres relations, NOT a graph DB. 809 posts doesn't justify GraphRAG; agent does multi-hop via repeated structured queries.

### Routing (opinionated)
**Do NOT build a learned router.** Expose a **capability manifest endpoint**
(`/schema`) describing each store (contents, example queries, latency/cost class).
The LLM agent reads it once and routes itself — that's what agents are good at, and
it's testable. One `search(query, stores=[...])` endpoint with per-store adapters;
structured SQL is a **separate explicitly-invoked `/query` endpoint**, never
auto-fallback. The SKILL.md encodes routing heuristics ("metrics → /query;
'how do I do X' → search; media → search media=true; creator identity → lookup").

### Decisions to validate (with cheap tests)
1. Field-level chunking beats naive chunking (20 questions, top-5 hit rate).
2. Agent-as-router beats server-router (manifest + 10 ambiguous questions; log picks).
3. Guarded text-to-SQL over DuckDB safe+useful (20 nl→SQL; <80% accuracy → template library).
4. Media metadata belongs in the same index (query visual content with `media=true`).
5. One unified corpus vs per-domain namespaces (single index + domain filter).
6. Gated-content/transcript signals add retrieval value (A/B).
7. MCP sufficient surface (don't build REST+CLI speculatively).

### Integration with source repos
**Contract principle: the KB is a derived consumer, never a second writer.** Upstream
repos own extraction; KB owns indexing/search/serving. One-directional flows.

- **From `scrape-ig-saved-list`:** consume `results.jsonl`, per-post `analysis.json`
  (the crown jewel), Apify media (as R2 upload source). Boundary = a **snapshot
  export** (deterministic, versioned JSONL/Parquet of `{post_id, creator,
  media_ref, analysis fields, scrape timestamp}`). KB ingests idempotently
  (upsert by post_id + content hash).
- **From `datalake`:** consume gold Parquet/serving views, reuse the Gemini
  enrichment-worker pattern for new extraction, R2 media bytes + cache conventions,
  DuckDB catalog as the read endpoint. KB registers as a **gold consumer**
  (read-only); media-derived metadata written to a KB-owned versioned schema.
- **Anti-pattern to refuse:** two repos both writing derived analysis.

---

## 3. Staff engineer brief — experiments, risks, vertical slice

**Verdict:** green-light, but design every experiment to fail loudly. Risks are
silent-wrongness, the media pipeline becoming a money pit, and unguarded text-to-SQL.

### Highest-leverage experiments
- **E1 Media extraction quality (biggest unknown):** 20 diverse posts → full
  extraction → hand-review ground truth → score precision/recall per field.
  **Pass:** ≥85% precision, ≥70% recall on high-value fields; every false positive
  detectable. **Fail:** agents would quote fabricated resources (silent-wrongness kill
  switch). <$5 with two-tier. *Secondary: does existing `analysis.json` already clear
  this bar?*
- **E2 Retrieval quality:** write 25 real questions NOW → score hybrid vs BM25-only vs
  dense-only on 20 posts. **Pass:** hybrid wins ≥60%, top-3 contains answer ≥80%.
  **Fail signal:** if BM25-only ≈ hybrid, skip vector infra entirely. *Critical: if
  you can't write 25 questions worth asking, the KB has no user.*
- **E3 Text-to-SQL (cheapest, run first):** point Claude Code at existing DuckDB gold
  views + schema docs; ask 10 tabular questions. **Pass:** ≥8/10 with curated semantic
  layer. **Fail:** >2 silent wrongs → text-to-SQL dies; use pre-written parameterized
  queries. *Make SCD2 temporal queries a named test case.*
- **E4 Federated routing — don't build it, simulate it:** hand-label which store
  answers each of 25 questions; let the agent choose from tool descriptions; compare.
  **Pass:** ≥80% correct store choice. Fix tool descriptions, not a router.

### Risks & de-risking
- **Silent wrongness** → every extracted entity carries provenance
  `{source_post_id, media_ref, extractor_model, confidence}`; no field without
  provenance is queryable. *Most important design decision.*
- **Schema drift** → version every record at ingest (`ingest_version`,
  `extraction_version`, `source_format`); data contract is a gate.
- **Model versioning** → E1 eval set is the regression suite; re-run on every
  extractor/model change; pin model IDs in config.
- **Media expiry** → extraction reads from byte cache only, never live URLs;
  content-hash (not URL) is media identity; re-scrape budget for new posts only.
- **Re-indexing cost** → content-hash upstream; re-index changed hashes only.
- **Scope creep** → kill criterion: if not answering end-to-end within <$100, hand
  agents direct DuckDB + analysis JSONs instead.

### First vertical slice (all-or-nothing)
20 posts, one domain, end to end:
```
media cache → two-tier extraction → (text + structured + per-slide embeddings)
  → one hybrid index + DuckDB gold views
  → thin MCP server (kb_search, kb_sql, kb_media_meta)
  → SKILL.md → answered against the 25-question eval
```
**Proves:** (1) extraction is trustworthy; (2) an agent with no prior context
decomposes + hits the right store; (3) answers carry provenance; (4) cost <$100.

### Guardrails (before any agent touches it)
1. **Read-only, hard-guaranteed** — MCP server has no write path at all.
2. **SQL guards** — curated semantic layer only; single SELECT-only statement
   (parsed, not regex'd), row caps, timeout, denylist on mutation functions; log every query.
3. **Abstention is first-class** — tools return `{answer, confidence,
   provenance[]}` plus explicit `insufficient_evidence`; SKILL.md tells the agent to
   say "KB has nothing" rather than extrapolate.
4. **Quality gate on the index** — only records passing confidence thresholds are
   indexed as asserted facts; sub-threshold queried as flagged raw metadata.
5. **Rate/cost caps** on lazily-triggered extraction (batch only, queue not sync).
6. **Scope note in SKILL.md** — saved-post knowledge, not truth about anything else.

### Docs before building
Data contract (canonical `KbPost` schema — the gate doc) · eval set spec (25
questions, regression suite, written first) · probe-results format (JSON per
experiment) · store catalog/routing table (becomes SKILL.md) · cost model (per
component) · ADR of what we're NOT building.

**Sequencing:** E3 (~1 day) → E1 (~1 day) → eval spec → vertical slice → E2/E4.

---

## 4. ML engineer brief — extraction vs embed, evaluation, versioning

### Extract-vs-embed: BOTH, sequenced
- **Extraction** (multimodal LLM → structured JSON) answers facts/steps/CTAs/gated-
  content (SQL + BM25 tier). **Visual embeddings** answer perceptual similarity
  ("posts that look like this layout").
- **Sequencing:** (0) captions/tags/analysis.json already done; (1) cheap text
  extraction over all 809 posts via **Batch API (<$2)**; (2) per-slide/keyframe
  Tier-2 pass only where layout IS the payload, gated on `content_type`/`value_score`
  (est. 30–50% of corpus); (3) visual embeddings last, only for Tier-2 posts — cut
  them if the demo never routes there.
- **Cost control:** Batch API, tier gating, cache key `(media_hash, model_id,
  prompt_id)` so identical inputs are never re-billed.

### Evaluate on the POC's own data (the performance-cliff fix)
Build a **gold set** of 50–100 hand-authored questions over the 809-post corpus,
stratified by: lookup (tests BM25/SQL), semantic (tests dense), multi-hop/structural
(tests text-to-SQL), media-grounded (tests visual), plus 5–10 **unanswerables**
(tests refusal/calibration). Each question: gold post IDs with graded relevance
(2/1/0), expected answer snippet, expected winning store (routing ground truth).

**Metrics:** Recall@5/10 headline, nDCG@10, MRR for lookups, per-tier routing
accuracy, hallucination rate on unanswerables, cost+latency per query. A static gold
set makes every model/routing change a seconds-fast re-run — **this file is the
POC's most valuable ML artifact.**

### Shortlist
- Text embedding: Gemini Embedding 2 / OpenAI text-embedding-3-large (cheap, batch 50% off).
- Multimodal (for Tier-2 slide embeddings): Gemini Embedding 2 (multimodal).
- Rerank: local cross-encoder (bge-reranker) or hosted; add only if E2 shows need.

### Versioning strategy
Versioned JSON Schema for extraction output; mandatory version tuple on every
record; a model upgrade re-extracts from cached raw media (content-hash keyed),
never re-scrapes; cost ledger convention `(key, model_id, tokens, cost)` per call.

---

## 5. Synthesis — agreed path forward

1. **Write the eval set + gold set FIRST** (PM/ML/Staff all agree: it gates everything).
2. **Run E3 (text-to-SQL probe)** — cheapest, most likely to kill or confirm.
3. **Run E1 (media extraction quality probe)** on 20 posts; check if `analysis.json` already clears the bar.
4. **Build the vertical slice:** 20 posts, one domain → hybrid index + semantic
   layer → MCP facade + SKILL.md → agent queries.
5. **A/B against no-KB baseline** with the gold-set judge (criterion 4).
6. **Log real query distribution** from day one (MCP makes it trivial) — the
   highest-value POC output for scaling decisions.
7. **Let the kill criteria do their job:** if agents don't query it or it doesn't
   beat baseline, stop — the honest POC answer is worth more than an overbuilt KB.

### Required artifacts before implementation (in order)
1. Benchmark/eval spec (10–25 questions + gold set + rubric) — *the gate*
2. PRD-lite (one page: problem, success criteria, kill criteria, non-goals)
3. Tool contract doc (the `kb_query` interface the agent sees)
4. Data contract (canonical `KbPost` schema + provenance/versioning) 
5. User stories with acceptance criteria (agent-as-user)
6. Evaluation protocol (A/B execution, judge, scoring)
7. ADR: what we are NOT building (no GraphRAG, no router service, no multi-tenant)

---
*Generated 2026-08-31 by a four-role expert panel reviewing the POC idea against
2026 research findings.*
