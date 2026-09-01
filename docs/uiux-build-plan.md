# UI/UX KB Build Plan — sdlc-worker + dlc-worker to the BM25 + pgvector stack

**Goal:** move the UI/UX corpus (and then the consolidated KB) through the
milestones from `docs/milestones.md` (M-UX1 → M-UX3, plus M1–M7) up to and
including the **BM25 + pgvector hybrid retrieval** stack (M4), with a **numeric
validation gate at every milestone** (per `docs/user-stories.md` Epic 8 and
`docs/research/llm-eval-frameworks.md`).
**Date:** 2026-09-01. **Status:** plan (no code written yet).

---

## Worker division (from `docs/milestones.md`)

| Worker | Owns | Typical work |
|---|---|---|
| **sdlc-worker** | application/feature code (stateless, self-corrects on next build) | media downloader, extraction scripts, `kb_query` surface, hybrid-index build pipeline as software |
| **dlc-worker** | stateful data/model + schema + versioning (changing logic does NOT self-correct existing rows) | KbPost/gold-view schemas, extraction output, embeddings + index refresh plan, gold set / eval suite, invalidation blast radius |

**Coordination rule:** dlc-worker publishes the canonical schema/version contract
first; sdlc-worker builds code against that pinned contract. No shared-file races.

---

## Current state (verified 2026-09-01)

- **Thin metadata** in this repo: `data/uiux/posts.json` (86 posts:
  shortcode/url/type/username), `data/uiux/profiles.json` (71 profiles:
  username/post_count). No captions, no media, no analysis.
- **Rich media corpus** in `~/repos/scrape-ig-saved-list/data/uiux/`: 51 posts
  (32 video / 19 sidecar) with **197 media files** (163 jpg + 34 mp4), each with
  `post_metadata.json` (captions, hashtags, comments, latestComments); **only 4
  have `analysis.json`** (schema v2, dated 2026-06-24).
- **Gap:** 86 posts.json vs 51 media posts = **35 posts have metadata but no
  media downloaded** (28 usernames without media).
- **Immediate value already delivered:** `docs/uiux-knowledge-digest.md` (text
  extraction of all 51 captions + 62,890 comments, categorized; 19 gated posts).
- **Worker handoff contract** spec'd in `docs/milestones.md` §Worker division.

---

## Milestone execution plan (worker + validation gate each)

### M-UX1 — UI/UX corpus ingestion + extraction
**Workers:** dlc-worker (schema + versioning contract) → sdlc-worker (ingest + download + extract scripts).

**dlc-worker first:**
- Define canonical `KbPost v1` for the UI/UX domain (superset of the 86-post
  metadata + the 51-post media fields), with `schema_version`, provenance
  `{source_post_id, media_ref, extractor_model, confidence}`, `extraction_status`,
  `is_promo`, `ingestion{snapshot_id}`. (Per `docs/data-architecture.md`.)
- Publish the versioned snapshot contract: `snapshot_id`, source commit hash,
  the 4 pre-existing analysis.json preserved as v1 (not overwritten).

**sdlc-worker:**
- Media downloader run: fetch the **missing 35 posts** (28 usernames) via
  `download_media.py` so the UI/UX corpus is 86/86.
- Ingest `post_metadata.json` (captions, hashtags, comments, latestComments) →
  canonical KbPost records with provenance stamped per field.
- Gemini extraction for the **47 unanalyzed media posts** (to match the 4
  existing), producing the full field set (summary, workflow_steps, tips,
  resources, tools_apps, gated_content, transcript).

**Validation gate (numeric, Epic 8):**
- 86/86 posts resolve to a canonical record; 0 unresolved.
- ≥51 posts have `analysis.json` with the full field set.
- Every field carries provenance; 4 pre-existing analysis files preserved.
- **E1 extraction-quality spot-check:** on a ≥10-post hand-review, ≥85%
  precision / ≥70% recall on high-value fields (workflow_steps, tools_apps,
  resources). Fail → fix extractor before scaling.

---

### M-UX2 — UI/UX media processing (the full structured + unstructured build)
**Workers:** sdlc-worker (extraction scripts + query surface) + dlc-worker (structured gold views + embeddings + versioning).

**sdlc-worker:**
- Per-slide / per-keyframe extraction of the 34 mp4 (transcript) + carousel slide
  text (the E1 media path). This unlocks the listicle content inside the images
  (e.g. the 15-slide AI-product-shoot walkthrough).
- Build the `kb_query` surface (search / get_post / answer) over the UI/UX
  artifact, with provenance + gated-trigger surfacing (M2 contract).

**dlc-worker:**
- Materialize curated **gold views** (posts, creators, tools, resources,
  workflows) — the M5 structured tier, now populated with UI/UX.
- Compute **visual embeddings** (Gemini Embedding 2, 768-dim, Batch API) for the
  media subset; cache key `(media_hash, model_id, prompt_id)`.
- Versioned gold set + eval-suite artifacts.

**Validation gate (numeric):**
- All 34 mp4 + carousel slides have extracted text (transcript/OCR/slide text).
- Structured gold views exist and pass guarded-SQL / aggregation checks.
- UI/UX posts retrievable via `kb_query` same as creator-growth.
- **Retrieval baseline (Epic 8, M3 harness):** Recall@5/10, nDCG@10, MRR on a
  UI/UX gold set. **Abstention rate** measured on unanswerables.
- **Cost gate:** ≤ panel envelope (Batch API, tier gating, cache keys).

---

### M-UX3 — Multi-domain consolidation
**Workers:** dlc-worker (schema merge) → sdlc-worker (unified query surface).

- Merge creator-growth (99) + UI/UX (86) into one canonical KbPost corpus under
  shared `schema_version` + provenance.
- One gold set covering both domains; one eval harness (M3).
- One query surface + one capability manifest (M6).

**Validation gate (numeric):**
- ≥1 domain-scoped query returns only its domain's posts (no bleed).
- Unified gold set scores ≥ M3 thresholds; adding the second domain does **not**
  regress the first (version-keyed eval).

---

### M4 — Hybrid retrieval (BM25 + dense → RRF) — the named target
**Workers:** dlc-worker (embeddings + index schema) + sdlc-worker (index build + query pipeline).

**This is the milestone the user named: "BM25 + pgvector stack."**

**dlc-worker:**
- Text embeddings for all posts (transcript + caption + analysis fields),
  chunked **by field** `(post_id, field)` with provenance (per architecture §2).
- Embedding metadata: model name + version per vector batch (model versioning).
- Storage decision: **pgvector + tsvector in Postgres** (per architecture) vs
  staying file-backed (SQLite FTS5 + local vectors) until scale demands. Recorded
  as an open question until the corpus size justifies Postgres.

**sdlc-worker:**
- BM25 (tsvector) + dense → RRF → optional cross-encoder rerank, behind the same
  `kb_query search` signature (drop-in — no new agent-facing surface).
- Query pipeline at serve time; ranking provenance (which retriever hit) added to
  the query log.

**Validation gate (numeric) — the hybrid-ablation gate (from the eval research):**
- **Hybrid beats BM25-only AND dense-only** on the M3 gold set: ≥60% win rate,
  top-3 contains the answer ≥80% (the milestone M4 criterion).
- **If BM25-only ≈ hybrid → skip vector infra** (keep keyword + RRF, don't build
  embeddings). This is the "do we even need pgvector" kill signal.
- **Division-of-labor breakdown** (per the fusion paper): split gold questions by
  type (lexical / semantic / gated) — report which channel serves each, to show
  *why* hybrid helps (or doesn't) for this corpus.
- **Fusion-cutoff sensitivity** (per the DESA paper): confirm the fused top-k is
  not an artifact of the RRF top-L cutoff.
- Every change passes the **regression gate**: smoke tier 100%, regression tier
  ~95%, metrics keyed by `(schema_version, index_version, eval_set_version)`.

---

## Cross-cutting: the numeric eval harness (built at M3, used everywhere)

Per `docs/user-stories.md` Epic 8 + `docs/research/llm-eval-frameworks.md`, the
**single most important build is the eval harness** (DeepEval as the runner;
Promptfoo's gate model; Ragas metric vocabulary). It is what makes every
validation gate above *numeric instead of vibes*.

- **Smoke tier** (must-never-break core questions): 100% pass, gates every change.
- **Regression tier** (full stratified set): ~95% pass, gates merges.
- **Metrics:** Recall@5/10, nDCG@10, MRR, routing accuracy, abstention rate,
  faithfulness (silent-wrongness guard), cost+latency per query.
- **Version-keyed:** every report keyed by `(schema_version, index_version,
  eval_set_version)` so a regression is attributable to exactly what changed.
- **Eval harness workers:** dlc-worker owns the gold set + eval-suite artifacts
  (stateful); sdlc-worker owns the harness runner + CI/local command (code).

---

## Suggested execution order (value-first)

1. **Now (this session):** UI/UX digest delivered (`docs/uiux-knowledge-digest.md`)
   — immediate value from captions, zero media processing.
2. **M-UX1** — dlc-worker defines the KbPost v1 contract; sdlc-worker downloads the
   35 missing posts + ingests + extracts the 47. Gate: 86/86 + E1 spot-check.
3. **M3-first principle:** build the **eval harness + gold set** in parallel with
   M-UX1 (it's the ruler; everything after is measured against it).
4. **M-UX2** — media extraction (unlocks listicle content) + structured gold
   views + embeddings. Gate: retrieval baseline + cost.
5. **M4** — hybrid retrieval. **The BM25 + pgvector stack.** Gate: hybrid-ablation
   (hybrid beats single-channel, else skip vector).

---

## Open questions to resolve before the workers start
1. **M4 storage** — Postgres (pgvector/tsvector) vs file-backed (SQLite FTS5 +
   local vectors) until scale. The milestone is named "BM25 + pgvector" so Postgres
   is the intent, but the corpus (99 + 86 = 185 posts) fits a 1M window — the
   hybrid-vs-direct-query decision (milestone M4 kill gate) may make pgvector
   unnecessary. Resolve at M4 gate, not before.
2. **Missing-35 media download** — does the scrape repo's `download_media.py`
   reach the 28 usernames without media? Needs a smoke test against the scrape
   repo's export before assuming 86/86 is achievable.
3. **The 4 pre-existing analysis.json** (2026-06-24, schema v2) — preserve as
   snapshot v1, and confirm the extractor model they used for provenance.
4. **Judge model for faithfulness** — which cheap model, versioned, so historical
   eval scores stay comparable.

---
*Generated 2026-09-01 from `docs/milestones.md`, `docs/data-architecture.md`,
`docs/user-stories.md`, `docs/research/llm-eval-frameworks.md`, and the verified
UI/UX corpus in `~/repos/scrape-ig-saved-list/data/uiux/`.*
