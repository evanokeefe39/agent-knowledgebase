# Agent Knowledge Base — Milestones

**Purpose:** sequence development so we **consistently get usable value** at every
stage, not a big-bang build. Each milestone is a shippable, queryable increment —
a user (or agent) can act on its output the day it lands.
**Inputs:** `docs/step-neg1-knowledge-digest.md` (what the corpus holds),
`docs/user-stories.md` (epics + acceptance criteria), `docs/architecture.md` +
`docs/expert-panel.md` (build order + kill criteria).

---

## Guiding principle

**Value-forward sequencing.** Every milestone delivers one of two things: (a) a
user-answerable capability, or (b) the measurement that proves value. No milestone
is pure plumbing with no usable output. Where a milestone is infrastructure, its
acceptance criteria include the demonstration that it changed a user-visible
answer.

The panel's mandate anchors the order: **write the eval/gold set first** (it gates
everything), **run the cheapest probe that could kill or confirm** before any heavy
build, and **let kill criteria stop us** rather than ship an overbuilt KB.

---

## Milestone map

| # | Milestone | Delivers value by | Epics | Est. effort |
|---|---|---|---|---|
| **M0** | ✅ **Queryable artifact + digest** (shipped) | Directly answerable in a 1M window; digest published | 1,2,3 | done |
| **M1** | **Trust foundation** | Complete, traceable, honest artifact | 1,7 | small |
| **M2** | **`kb_query` tool (no infra)** | A real query surface; answers on demand | 1,2,3,6 | small |
| **M3** | **Gold set + eval harness** | Measurement that gates every later change | all | small |
| **M4** | **Hybrid retrieval** | Recall for fuzzy/semantic questions | 1,2,6 | medium |
| **M5** | **Structured / guarded tier** | Aggregations, metrics, entity queries | 4,5,6 | medium |
| **M6** | **Packaging (skill + CLI + MCP)** | Agents discover + use the KB hands-free | 6 | medium |
| **M7** | **A/B validation + kill gate** | Proof it beats no-KB baseline | all | small |
| **M-UX1** | **UI/UX corpus ingestion + extraction** | Second domain track (UI/UX & design) brought to parity with creator-growth | 1,2,3 | medium |
| **M-UX2** | **UI/UX media processing** | Media (163 jpg + 34 mp4) extracted → structured + unstructured KB | 1,2,4 | medium |
| **M-UX3** | **Multi-domain consolidation** | creator-growth + uiux under one canonical index / query surface | 1,4,5,6 | medium |

M1–M3 are cheap and reorderable; **M3 (gold set) should be started in parallel
with M1** because the panel says the eval set gates everything and is the single
most valuable artifact.
The **UI/UX domain track (M-UX1 → M-UX3)** is a second, parallel domain that runs
alongside the creator-growth track. It reuses the same pipeline (ingest → extract →
consolidate → index) but is a separate corpus with its own media. The two tracks
converge at **M-UX3** (one canonical index / query surface) and share M2–M7 tooling.

---

## M0 — Queryable artifact + digest (SHIPPED)

The step −1 JSON (`creator-growth-knowledge.json`, 99 records) + the digest
(`docs/step-neg1-knowledge-digest.md`) are already queryable in one 1M-token window.

**Value:** the corpus already answers questions directly — no retrieval infra.
**Status:** complete, verified (2026-09-01).

---

## M1 — Trust foundation

Make the artifact complete, traceable, and honest — the non-negotiable base for
everything that queries it (US-1.1, US-1.2, US-7.1, US-3.x).

**Value:** every answer resolves to a source and the KB says when it can't answer.

**Scope**
- Backfill `url` for all 99 records from `shortcode`
  (`https://www.instagram.com/p/{shortcode}/`).
- Recover the 2 failed long-video posts (JSON truncation fix: `max_output_tokens`
  / first-complete-object truncation) → 101/101 coverage.
- Flag the 13 `content_type:promo` posts (11 of them gated) so they're surfaced as
  pure promos, not quoted as neutral tips.
- Ensure `gated_trigger` is surfaced on every gated-content answer (US-3.1).

**Acceptance criteria (testable)**
- 101/101 records have a resolvable `url` (shortcode → valid URL).
- 0 records have null `url`.
- The 2 previously-failed posts have `summary`, `workflow_steps`/`tips`, `transcript`.
- All 13 promos carry an explicit `content_type:promo` signal used by downstream
  answers.
- Abstention path exists: a query with no corpus match returns
  `insufficient_evidence`, not a hallucinated answer (US-7.1).

**Kill signal:** if the 2 recovered posts' extraction quality fails the E1 bar
(≥85% precision / ≥70% recall on high-value fields, per expert panel), pause M1 and
revisit the extractor before building on top.

---

## M2 — `kb_query` tool (no infra)

A minimal query tool over the existing JSON — **no vector store, no SQL service**.
This productizes the M0 "stuff it in context" approach into a callable interface
and proves users/agents will actually query before we build retrieval (the panel's
highest-risk question: "do agents query it at all?").

**Value:** users and the agent can ask the corpus questions on demand today.

**Scope**
- A `kb_query` tool/mode with three paths:
  - `search` — keyword + field-scoped match over the JSON (by domain,
    content_type, creator, tool, gated flag).
  - `get_post` — point lookup by shortcode/post_id → full record.
  - `answer` — optional LLM synthesis over matched records, **always** with
    provenance and gated flags (US-1.1, US-3.1).
- Filtering by creator / domain / content_type / tool to defeat volume-as-relevance
  (US-6.1).
- Log every query from day one (the panel's highest-value POC output: a real query
  distribution).

**Acceptance criteria (testable)**
- ≥8/10 of the benchmark questions (from M3's gold set) can be answered by issuing
  ≤2 `kb_query` calls, with results grounded in real posts.
- A domain-scoped query (e.g. `dev_tools`) does not return off-topic
  high-volume branding posts (bywaviboy/vinny_creative) ahead of on-topic ones
  (US-6.1).
- Every `answer` response cites a resolvable source and surfaces `gated_trigger`
  where present.
- Query log records (query, filters, result ids, latency, cost) per call.

**Kill signal:** if real users/agents don't issue ≥2 distinct KB queries on ≥8/10
benchmark questions *without prompting* (expert-panel criterion 2), the product
hypothesis is wrong — stop before building retrieval.

---

## M3 — Gold set + eval harness

A static, hand-authored gold set over the 99-record corpus + a harness to score
every later change in seconds. **This is the POC's most valuable ML artifact**
(expert panel). Start it in parallel with M1.

**Value:** every subsequent milestone (M2, M4, M5, M7) becomes measurable; a model
or extractor change re-runs the regression suite in seconds.

**Scope**
- 25–50 questions stratified by type (from `docs/user-stories.md`): lookup (tests
  BM25/SQL), semantic/fuzzy (tests dense), multi-hop/structural (tests text-to-SQL),
  gated-content (tests gate surfacing), tool-selection (Epic 4), monetization
  (Epic 5), + 5–10 **unanswerables** (tests abstention).
- Per question: gold post IDs (graded 2/1/0), expected answer snippet, expected
  winning store (routing ground truth).
- Metrics: Recall@5/10, nDCG@10, MRR, per-tier routing accuracy, abstention rate on
  unanswerables, cost+latency per query.

**Acceptance criteria (testable)**
- Every question is answerable from the corpus or labeled unanswerable (no
  hallucination-inviting prompts).
- The harness scores any candidate (a retrieval config or an LLM answer) and emits
  the metrics above in < 60s.
- Routing ground truth is labeled for every question (which store answers it).

---

## M4 — Hybrid retrieval (BM25 + dense + RRF)

Add real retrieval **only if M2 shows fuzzy-question demand** (i.e. users ask
questions keyword search can't answer). This is when the corpus outgrows one
1M-window or M2's keyword search underperforms.

**Value:** high recall on fuzzy/semantic questions the M2 keyword path misses.

**Scope**
- Text embedding of all 101 posts (transcript + caption + analysis fields), chunked
  by field with provenance `(post_id, field)` (architecture §2).
- Single multimodal embedding model (Gemini Embedding 2, 768-dim, batch) — one
  unified index; never double-index.
- BM25 + dense → RRF → (cross-encoder rerank if E2 shows need).

**Acceptance criteria (testable)**
- Hybrid beats single-method (BM25-only or dense-only) on the M3 gold set (≥60%
  win rate; top-3 contains the answer ≥80%).
- If BM25-only ≈ hybrid, **skip vector infra** — keep keyword + RRF, don't build
  embeddings (expert-panel fail signal).

**Kill signal:** if M2 answers ≥8/10 benchmark questions without needing M4,
defer M4 indefinitely — the 1M-window direct query may be sufficient for this
corpus size.

---

## M5 — Structured / guarded tier

A curated semantic layer (3–5 read-only gold views: creators, posts, domains,
tools) with guarded, read-only text-to-SQL — for aggregations and metrics the
unstructured path can't do ("which tools recur across the corpus?", "how many
posts are gated per domain?").

**Value:** metric/aggregation answers with hard read-only guarantees.

**Scope**
- Gold views (SELECT-only, read-only replica) over the JSON's structured fields.
- SQL guards: parse-not-regex, deny mutation, row caps, timeouts, abstention on
  low confidence (architecture §4).
- Templates for the most common aggregations (tool frequency, domain counts,
  gated counts) as the fallback.

**Acceptance criteria (testable)**
- ≥8/10 M3 structured questions answered correctly with the semantic layer.
- >2 silent wrongs → **text-to-SQL dies**; replace with pre-written parameterized
  queries (panel fail signal).
- No query path can mutate data (hard read-only).

---

## M6 — Packaging (skill-first + CLI + optional MCP)

Package the KB so a coding agent discovers and uses it hands-free:
`SKILL.md` (progressive disclosure) + a CLI calling the same query surface + MCP
as an optional adapter (architecture §1).

**Value:** agents self-route from a capability manifest — no human setup.

**Scope**
- SKILL.md with routing heuristics ("metrics → /query; how do I do X → search;
  visual → media; creator identity → lookup").
- Capability manifest (`/schema`) the agent reads once to route itself (US-6.2).
- CLI; MCP only if a second consumer appears.

**Acceptance criteria (testable)**
- A fresh agent session discovers and calls the KB with zero setup.
- Agent picks the correct store from tool/manifest descriptions ≥80% of the time
  (architecture E4).
- SKILL.md loads in ~100 tokens; body only on trigger.

---

## M7 — A/B validation + kill gate

The money criterion: does the KB measurably beat the no-KB baseline on the same
questions, judged by a fresh-context rubric?

**Value:** proof the KB earns its place — or an honest "stop."

**Scope**
- Same M3 questions answered with vs without the KB; rubric-scored by a
  fresh-context judge (criterion 4).
- Spot-check citation resolution (≥18/20 cited sources resolve) and abstention
  behavior.

**Acceptance criteria (testable)**
- Rubric-scored KB answers beat no-KB on ≥7/10 M3 questions.
- Every claim cites a post/row id; ≥18/20 spot-checked citations resolve.
- Cost ≤ $50 incremental; per-query ≤ $0.05.

**Kill criteria (any one → stop, write the honest answer):**
- Criterion 2 (M2) or M7's rubric win fails after one round of prompt/tool-description
  iteration.
- Total spend exceeds $100 without an end-to-end answer (panel scope-creep guard).
## M-UX1 — UI/UX corpus ingestion + extraction

**Second domain track.** The repo now holds a UI/UX saved-list snapshot
(`data/uiux/posts.json` — 86 posts, `data/uiux/profiles.json` — 71 profiles,
committed `838df78`). These are **thin metadata only** (shortcode/url/type/
username, profile username/post_count) — no captions, no media refs, no analysis.
The real value is the media in the scrape repo's `data/uiux/`.

**Value:** the UI/UX domain is brought to parity with creator-growth — a
queryable, extracted corpus, not a raw metadata dump.

**Scope**
- Ingest the scrape repo's `data/uiux/` media manifest + `post_metadata.json`
  (which DO contain captions, hashtags, comments, latestComments) into canonical
  KbPost records with provenance.
- **Close the media gap:** posts.json lists 86 posts; only **51 have media** in
  the scrape repo (35 posts metadata-only, 28 usernames without media). The media
  downloader (`download_media.py`) fetches the missing 35 so the UI/UX corpus is
  complete.
- **Extraction:** only 4 of 51 media posts have `analysis.json` (schema_version 2,
  dated 2026-06-24). The remaining 47 need Gemini extraction to reach
  creator-growth parity (summary, workflow_steps, tips, resources, tools_apps,
  gated_content, transcript).
- Media split to process: 19 video / 32 carousel-post; 163 jpg + 34 mp4.

**Acceptance criteria (testable)**
- 86/86 posts in posts.json resolve to a canonical record (51 with media, 35
  with media fetched); 0 unresolved.
- ≥51 posts have `analysis.json` with the full field set (extraction parity with
  creator-growth).
- Every field carries provenance `{source_post_id, media_ref, extractor_model,
  confidence}` (the M1 invariant, from `docs/data-architecture.md`).
- 4 pre-existing analysis.json files (2026-06-24, schema v2) are preserved as a
  versioned snapshot, not silently overwritten.

**Kill signal:** if extraction of the 47 media posts fails the E1 bar (≥85%
precision / ≥70% recall on high-value fields), pause and fix the extractor before
scaling to the rest.

---

## M-UX2 — UI/UX media processing (the full media build)

**This is the milestone the user flagged for sdlc-worker + dlc-worker.** Once M-UX1
proves the ingest/extract pipeline on the UI/UX corpus, run the full
**structured + unstructured** knowledge base build over the media:

**Value:** the UI/UX domain becomes a *full* KB — structured fields AND
unstructured/visual content — not just text extraction.

**Scope**
- **Structured** (dlc-worker): materialize curated gold views over UI/UX KbPost
  records (posts, creators, tools, resources, workflows) — the M5 structured tier,
  now populated with the UI/UX domain.
- **Unstructured / media** (sdlc-worker + dlc-worker): per-slide / per-keyframe
  extraction of the 34 mp4 + carousel slides (the E1 media path from
  `docs/architecture.md`), plus visual embeddings (Gemini Embedding 2, 768-dim)
  for the media subset.
- **Hybrid index:** chunk the UI/UX text + media-derived metadata into the same
  `(post_id, field)` chunks with provenance; BM25 + dense → RRF (M4).
- **Consolidation:** the UI/UX artifact (like creator-growth's
  `creator-growth-knowledge.json`) becomes queryable through the same `kb_query`
  surface (M2) and gold set (M3).

**Acceptance criteria (testable)**
- All 34 mp4 + carousel slides have extracted text (transcript / OCR / slide
  text), not just captions.
- Structured gold views for UI/UX exist and pass the guarded-SQL / aggregation
  checks (M5 criteria).
- UI/UX posts are retrievable via the same query surface as creator-growth.
- Cost stays within the panel envelope (Batch API, tier gating, cache keys).

**Kill signal:** if the visual/media pass adds no measurable retrieval value over
text-only extraction on the UI/UX gold set, cut the media-embedding half and keep
the (cheap) text extraction — do not build a money-pit media pipeline the corpus
doesn't need.

---

## M-UX3 — Multi-domain consolidation

**Value:** one canonical KB across domains — creator-growth + UI/UX — with a
unified index, query surface, gold set, and eval.

**Scope**
- Merge creator-growth (99 records) + UI/UX (86 records) into one canonical
  KbPost corpus under the shared `schema_version` and provenance rules.
- One gold set covering both domains; one eval harness (M3) scoring the whole.
- One query surface (`/search` hybrid + `/query` guarded SQL) and one capability
  manifest (M6).

**Acceptance criteria (testable)**
- ≥1 domain-scoped query returns only its domain's posts (no cross-domain bleed).
- The unified gold set scores ≥ M3 thresholds; adding the second domain does not
  regress the first (version-keyed eval).
- A single SKILL.md / CLI exposes both domains.

---

## Reordering / parallelism

- **M1 and M3 run in parallel** (both cheap, both gate everything downstream).
- **M2 after M1** (needs a trustworthy artifact to query).
- **M4 only if M2 shows demand** — may be skipped entirely if the 1M-window
  direct query suffices for this corpus.
- **M5 can precede M4** if aggregation value is wanted before semantic search
  (E3 is the cheapest probe per the panel — run text-to-SQL first if the questions
  skew metric-heavy).
- **M6 after M2/M4/M5** — packaging is a thin layer over an already-valuable query
  surface.
- **M7 is the gate** — everything prior is the smallest instrument that can prove
  or kill the hypothesis.
- **M-UX1 → M-UX3 run parallel to the creator-growth track** and share its M2–M7
  tooling; they converge at M-UX3.
- **M-UX2 (media processing) uses sdlc-worker + dlc-worker** — see the worker
  division below.

---

## Worker division (sdlc-worker vs dlc-worker) for the UI/UX media build

Per the repo's worker model, the M-UX2 media build splits by lifecycle half:

- **sdlc-worker** owns the *application/feature* side — the code-shaped work that
  reads/writes data and self-corrects on the next build:
  - the media-downloader run to fetch the missing 35 posts (a scraper feature),
  - the per-slide/keyframe extraction *scripts* and the `kb_query` query surface
    it feeds (the tool contract),
  - the hybrid-index build pipeline (BM25 + dense → RRF) as software.
- **dlc-worker** owns the *stateful data/model* side — where changing logic does
  NOT self-correct existing rows:
  - the schema/DDL for the canonical KbPost corpus and the structured gold views,
  - the extraction *output* (a model change requires versioned backfill, not a
    silent overwrite),
  - the embedding batch + index refresh plan (full-refresh vs incremental), and
    the invalidation blast radius (every consumer incl. dashboards) on a schema
    change,
  - the versioned gold set / eval-suite artifacts.

**Coordination:** the two workers hand off on the data contract — dlc-worker
signals the canonical KbPost / gold-view schema and its version; sdlc-worker
consumes it. No shared-file races: sdlc-worker builds the code against
dlc-worker's pinned schema.

## Non-goals preserved

GraphRAG, learned federated router, Web UI, multi-user, Postgres migration,
full-scale visual extraction, video transcript derivation — all deferred per
`docs/architecture.md`, and none appear in the milestones.

---
*Generated 2026-09-01 from `docs/user-stories.md`, `docs/architecture.md`,
`docs/expert-panel.md`, the shipped step −1 artifact, and the UI/UX snapshot
(`data/uiux/` + scrape-repo `data/uiux/`).*
