# Agent Knowledge Base — Data Architecture Evolution

**Panel:** Data Architect · Schema & Contract · Interface · Data Pipeline
**Date:** 2026-09-01
**Inputs:** `docs/milestones.md`, `docs/architecture.md`, `docs/expert-panel.md`,
`docs/RESEARCH.md`, and the shipped step −1 artifact
(`data/step-neg1/creator-growth-knowledge.json`).
**Scope:** how the data architecture evolves across milestones M0–M7 — what data
exists, where it's stored, what schemas/contracts/interfaces govern it, and where
data pipelines appear at each stage.

---

## The evolution arc (one paragraph)

The KB starts (M0) as a **single hand-curated JSON artifact** consumed whole in a
1M-token window — no infra, no index, no provenance. The arc is: **canonicalize**
(M1: repair + provenance) → **index** (M2: query log over flat JSON) →
**measure** (M3: gold set) → **retrieve** (M4: hybrid index, gated) →
**materialize** (M5: gold views + guarded SQL) → **package** (M6: manifest) →
**validate** (M7: A/B read-only). The KB stays a **derived, read-only consumer**
of `scrape-ig-saved-list` (snapshot export) and `datalake` (enrichment sidecar).
Every new stage adds **one bounded pipeline, never a second writer**. The core
invariant, established at M1 and never regressed: **no field without provenance**;
records are versioned; source repos are one-directional.

```
M0  flat JSON (99 rec) ──► M1  canonical KbPost + provenance
   ──► M2  kb_query tool + query log ──► M3  gold set + eval harness
   ──► M4  BM25 + dense → RRF (GATED) ──► M5  gold views + guarded SQL
   ──► M6  SKILL.md + CLI (+MCP) ──► M7  A/B validation + kill gate
```

---

## Stage-by-stage architecture

### M0 — Queryable artifact + digest (SHIPPED)

**Data:** `data/step-neg1/creator-growth-knowledge.json` (99 records:
`post_id, shortcode, url=null, owner, content_type, value_score, is_educational,
domains, summary, resources[], workflow_steps[], tips[], concepts[], tools_apps[],
tags[], gated_content, gated_trigger, transcript`) + `creator-growth-candidates.json`
+ `extraction-targets.json` (101-post manifest, 60 needing fresh extraction; 2
failed on JSON truncation).
**Storage:** one flat JSON file, read wholesale into a 1M-token window. No DB.
**Pipelines:** none. Schema is v0 (unversioned): no provenance, `url` null
everywhere, no `record_version`. Defects carried forward: `url` reconstructable
from `shortcode` (unwritten transform), 2 extraction failures (coverage gap).

### M1 — Trust foundation

**Data:** canonical `KbPost` records (the 99 fields, now complete + trustworthy);
`url` backfilled via deterministic shortcode→url transform; 2 recovered posts;
`is_promo` flag on the 13 promos; abstention metadata (coverage map of what the
KB does *not* know); re-scored 101-post manifest.
**Storage:** still flat JSON in the KB repo (versioned directory). Provenance
embedded per record; no sidecar DB yet.
**New plumbing (one-shot):** snapshot ingestion (results.jsonl + analysis.json →
canonical KbPost with provenance), extraction recovery (2 posts + 60 stale via
retry queue), promo-flag pass, abstention labeling, schema versioning start,
change-detection diff (prove no silent mutation vs M0).
**Pipelines begin here** — but all one-shot, manual-trigger.

### M2 — `kb_query` tool (no infra)

**Data:** canonical JSON (unchanged) + **query log** (append-only JSONL:
`timestamp, mode[search|get_post|answer], filters, query text, matched post_ids,
result count, latency, cost tokens, abstained`).
**Storage:** canonical JSON unchanged; query log in `data/query-log/`. No database.
**New plumbing:** **query-logging (first forever-recurring pipeline)** + lightweight
manual snapshot-refresh (diff on hash first) + in-memory filter index (pure
function, cached, invalidated on source hash).
**Interface contract born:** `kb_query` with modes `search` (filters: owner,
content_type, domains, is_educational, value_score≥N), `get_post(post_id)`,
`answer` (grounded synthesis + citations + abstention). Provenance surfaces
through the interface for the first time.

### M3 — Gold set + eval harness

**Data:** gold set (25–50 graded questions: `{question_id, question,
expected_post_ids[], expected_answer_facts[], mode, graders, difficulty}`,
versioned) + eval metrics reports (Recall@5/10, nDCG, MRR, routing accuracy,
abstention rate, cost, latency) + baseline snapshot.
**Storage:** `data/eval/gold-set-v1.*`; timestamped reports in `data/eval/runs/`.
**New plumbing:** eval pipeline (recurring, per gate) — cheap-model answering, no
API calls during scoring. Gold-set authoring is one-shot, then append-only.
**First cross-version data contract:** metrics keyed by
`(schema_version, index_version, eval_set_version)` — without it M4/M7
comparisons are meaningless.

### M4 — Hybrid retrieval (GATED)

**Data:** chunk corpus `(post_id, field, text, provenance)` — chunked **by field**
(summary, transcript segments, tips, workflow_steps), each chunk carries
`{source_post_id, media_ref, extractor_model, confidence, field, chunk_idx}`;
BM25 (tsvector) + dense embedding index + RRF merge + rerank config; embedding
model+version metadata per vector batch.
**Storage:** indexes in Postgres (pgvector + tsvector) per the brief's naming;
canonical JSON remains source of truth (indexes fully rebuildable derived state).
**New plumbing:** first real ingestion/indexing pipeline — snapshot → chunk
(field-aware, provenance-preserving) → BM25 build + batch embedding job (Batch
API, idempotent, keyed `media_hash+model_id+prompt_id`) → index store.
**GATE:** this milestone **only runs if M2's query log shows fuzzy/semantic
demand** that filters+exact search miss. If M2 already answers ≥8/10 benchmark
questions, **defer M4 indefinitely** — and if BM25-only ≈ hybrid, **skip vector
infra entirely**.

### M5 — Structured / guarded tier

**Data:** curated, materialized gold views over canonical posts (denormalized: by
domain, by workflow, top-value-per-topic), schema-versioned, each row carrying
provenance + a `source_schema_version` + refresh timestamp (a stale view is a
silent-wrongness vector).
**Storage:** materialized views in Postgres alongside M4 indexes; manifest
versioned in repo.
**New plumbing:** gold-view materialization (silver→gold, idempotent, per refresh)
+ guarded-SQL schema sync (one job emits views + manifest atomically) + query
log→silver (moves from JSONL to a queryable table).
**Interface:** `/query` guarded read-only text-to-SQL over the allow-listed gold
views (creators, posts, domains, tools); parse-not-regex guards, deny mutation,
row caps, timeouts, low-confidence abstention; templated fallbacks mandated if
>2 silent wrongs.

### M6 — Packaging (SKILL.md + CLI + optional MCP)

**Data:** unchanged (JSON + Postgres). Adds a **capability manifest** (modes,
views, provenance guarantees, schema_version, index freshness).
**New plumbing:** manifest generation (auto-derived from data layer — a
hand-written manifest drifts) + release bundle assembly (kb-posts + index +
embeddings as one versioned snapshot).
**Interface:** `/schema` manifest (agent reads once, self-routes) + SKILL.md
(~100-token progressive disclosure, routing heuristics) + CLI (thin client over
same REST surface) + MCP **only if a second consumer appears**. Full surface:
`/schema, /search (hybrid), /query (guarded SQL), /post (point lookup/provenance)`.

### M7 — A/B validation + kill gate

**Data:** A/B run records (baseline vs variant metrics keyed by the M3 version
tuple) + kill-gate decision record + variant definitions (versioned).
**New plumbing:** A/B eval pipeline (two configs, same gold set, paired metrics).
Reversion is possible only because every stage's artifacts are versioned and
rebuildable from canonical JSON + source snapshot.
**No new primary store** — reports under `data/eval/runs/`.

---

## Contracts

### Provenance rule (the core invariant, from M1)
**No field without provenance is queryable.** Every KbPost field resolves to:
```
Provenance { source_post_id: string (FK→KbPost.post_id),
             media_ref: string|null (pointer into scrape-repo media; null=text-derived),
             extractor_model: string (version recorded, not assumed),
             confidence: number|null }
```
Plus per-field `extracted_at`. Fields mirrored from source metadata get
`extractor_model: "source_metadata"`. **KB-generated fields (e.g. `is_promo`)
must carry provenance too.** Enforced at ingest: incomplete provenance = rejected
(fail loudly, not silently-wrong). New extraction = new version, old archived —
mirroring the source repo's own analysis.json archiving.

### Source-repo contracts (one-directional, KB never a second writer)
- **KB ↔ scrape-ig-saved-list (INGEST, snapshot):** KB reads `results.jsonl` +
  per-post `post_metadata.json` + `analysis.json` (versioned) and pins a
  `snapshot_id`. Ingest fields: `post_id, shortcode, caption, ownerUsername,
  analysis{...}, analysis_version, extracted_at`. Handles known gaps
  contractually: truncated JSON = hard-fail → `extraction-targets.json` (not
  silent drop); `url` null → derive from shortcode; media stays in scrape repo
  (KB stores only `media_ref` pointers, never bytes; records CDN-expiry risk).
  **No back-channel.**
- **KB ↔ datalake (GOLD VIEW, read-only consumer):** consumes version-pinned gold
  views (`{name, version, schema_hash, row_count, materialized_at}`). Must NOT
  assume enrichment coverage — datalake is text-only today (`media_files "[]"`),
  so any field depending on datalake media enrichment is nullable + flagged
  not-yet-produced (provenance = absent, not fabricated).

### Versioning
1. **KbPost schema version** — additive-only; breaking = major bump + re-ingest.
2. **Snapshot versioning** — immutable `snapshot_id` per import; re-extraction
   creates a new post version under the same `post_id` (`version_history[]`).
3. **View/materialization versions** — gold views + gold sets carry
   `version, materialized_at, source_snapshot_id`; eval results record which
   version they graded.
4. **Model versioning** — `extractor_model` at field level; embedding_model per
   vector batch; upgrading never rewrites provenance, it appends.
5. **Query-log schema version** — header field so the M3 harness parses older logs.

---

## Interfaces (evolution across stages)

| Milestone | Interface | Routing |
|---|---|---|
| M0 | Direct-JSON in a 1M window (+ digest doc) | model's job |
| M1 | Same surface, hardened contract (url, promo flag, gated_trigger, abstention shape) | model's job |
| M2 | `kb_query`: search / get_post / answer + filters + query log | explicit tool |
| M3 | Eval harness (offline, scores any surface in <60s) | — |
| M4 | `search` upgraded internally (hybrid behind same signature) — no new agent surface | tool + hybrid |
| M5 | `/query` guarded text-to-SQL + templated fallbacks | agent picks /search vs /query |
| M6 | `/schema` manifest + SKILL.md + CLI (+ MCP optional) | agent self-routes from manifest |
| M7 | A/B harness over packaged surface | judge |

**Key invariant (architecture §5):** the agent routes, not the server. No learned
federated router.

---

## Pipelines by stage

| Stage | Pipelines (type) |
|---|---|
| M0 | none (static artifact; upstream scrape+extraction already ran) |
| M1 | snapshot-ingestion (one-shot), extraction-recovery (one-shot, retry-queue), promo-flag (one-shot), abstention-labeling (one-shot) |
| M2 | **query-logging (recurring — first forever pipeline)**, snapshot-refresh (recurring, manual), kb-index-build (per-refresh, pure) |
| M3 | eval (recurring per gate), gold-set authoring (one-shot then append), query-log consolidation (recurring) |
| M4 | embedding-batch (one-shot per model, then incremental, **gated**), hybrid-index-build (per refresh), rerank-inference (per query, cached) |
| M5 | gold-view-materialization (recurring, idempotent), guarded-sql-schema-sync (recurring, atomic with views), query-log→silver (recurring) |
| M6 | manifest-generation (per release, auto-derived), release-bundle assembly (one-shot per release) |
| M7 | a-b-eval (recurring per experiment) — by now a single orchestrated `refresh` command chains all steps, each diff-keyed (unchanged data costs zero LLM tokens) |

**Cost control (all compute-heavy jobs):** Batch API (−50%), tier gating, cache
key `(media_hash, model_id, prompt_id)` so identical inputs are never re-billed.

---

## Query-capability roadmap (from the prospective-user interjection)

Two concrete questions, answered against verified corpus data:

**Q1: When can we reliably extract workflows / recommended tools / strategies from
posts like "use these tools for the next vibe-coded website", "how I grew my
account to 10k followers in 30 days", "what's killing your job applications",
"where to find customers"?**

**The extraction itself already works today (M0).** The shipped artifact already
contains `workflow_steps`, `tools_apps`, `tips`, `concepts`, `summary` for exactly
these post types — verified: 14 `dev_tools` posts have full `workflow_steps`
(e.g. angus.sewell's 7-step n8n/Claude/Hunter.io client play); growth-workflow and
client-getting posts (samson.ai funnel, onlyzita high-ticket, angus.sewell
boring-industry) all carry structured steps and tool lists.

What is **not yet** reliable:
- **Coverage** — only 99 of 809 posts are analyzed; 13 are promos (method
  withheld); 2 extractions failed. Full-coverage reliability needs M1's recovery +
  extending extraction to the remaining corpus.
- **Trust** — is `workflow_steps` faithful or hallucinated? Reliability of
  extraction is **proven at M1** (provenance `{extractor_model, confidence}` makes
  every workflow/tool field verifiable) and **measured at M3** (gold set grades
  extraction fidelity, catching silent-wrongness per the E1 bar: ≥85% precision /
  ≥70% recall on high-value fields).

So: **extract workflow/tools from a given post = M0 already. Trust that extraction
reliably = M1 (provenance) + M3 (measurement). Full corpus coverage = M1 extension.**

**Q2: When can we identify relevant accounts for "find me creators that give job
application advice" / "what creators give ui/ux tips"?**

This is a **retrieval + aggregation** question, not extraction. Verified data: 70
career posts, 13 ui_ux posts across distinct creator sets (career: bywaviboy 16,
vinny_creative 8, angus.sewell 4; ui_ux: vinny_creative 3, angus.sewell 2,
electroformaint 2, …).

| Milestone | What you get | Reliability |
|---|---|---|
| **M2** | `kb_query search` with `domains=career` / `content_type=workflow` filters → a list of creators in that domain | basic, lexical |
| **M4** | hybrid retrieval over chunked text → *semantic* account identification ("creators that give job application advice" even when phrasing doesn't lexically match) | reliable recall |
| **M5** | `GoldCreator` / `GoldDomain` views (post_count, avg_value_score per domain) → a **ranked, defensible** answer ("top job-application-advice creators") | precise aggregation |

So: **M2 gives a basic domain-filtered list; M4 makes account identification
semantically reliable; M5 makes it a ranked, defensible answer.** For the ui/ux
example, the corpus already has the answer (13 ui_ux posts, clear creator
signature) — M2 surfaces it, M5 ranks it.

---

## Evolution traps (must not regress)

1. **Silent-wrongness** — the defining trap. `value_score`, `domains`,
   `gated_trigger`, `summary` are model opinions with confidence, not ground
   truth. Provenance + abstention (M1) + gold set (M3) make wrongness measurable
   instead of silent.
2. **Schema drift** — M0 is unversioned. Explicit `schema_version`, archived old
   versions, diff-check on every canonical change, eval keyed by version.
3. **Model versioning** — mixing vectors/extractions from different models corrupts
   retrieval silently. Model id on every derived artifact; model-aware partial
   re-index.
4. **Media expiry** — CDN URLs die in ~4-5 days. `media_ref` points at the
   datalake byte cache, never a raw CDN URL; dead refs = abstention, not broken
   answer.
5. **Re-indexing cost** — transcripts dominate tokens. Idempotent,
   content-hash-keyed, model-aware chunk+embed jobs keep rebuilds incremental.
6. **Derived-consumer discipline** — extraction recovery runs IN the source repo
   and flows forward via snapshot. If the KB "fixes" data locally, the next
   snapshot silently reverts it.
7. **View staleness (M5)** — materialized views must refuse past a freshness
   threshold rather than serve plausible-but-outdated SQL answers.

---

## Open questions (flagged, not decided)

1. **M4 storage** — Postgres (pgvector/tsvector, per brief) vs staying
   file-backed (SQLite FTS5 + local vectors) until scale demands it.
2. **Query-log home at M4+** — JSONL vs table.
3. **M6 packaging** — bundled snapshot vs repo pointer (freshness vs portability).
4. **Index invalidation** on KbPost schema change (full rebuild vs field delta).
5. **M4 gate threshold** — what fraction of M2 queries counts as "fuzzy demand"
   (e.g. >20% keyword-miss but semantic-hit)?
6. **Refresh cadence** — cron vs manual `kb-refresh` vs diff-on-read (no webhook
   exists in the scrape repo).
7. **Cache-key definition** — media_hash requires a read-only handle to datalake's
   media cache; or hash caption/transcript text instead (cross-repo decision).
8. **Extraction-recovery fix** — chunked Gemini vs higher max_output_tokens vs
   transcript-only summary (a prompt change or a new source-repo pipeline stage).
9. **Interface taxonomy** — `kb_query` modes (search/get_post/answer) vs REST
   routes (/schema /search /query /post): one canonical naming decision needed.
10. **MCP trigger** — no second consumer is named; does MCP simply never ship
    (honest scope cut)?
11. **Query-log retention / PII** — define at M2, not retrofitted at M7.

---
*Generated 2026-09-01 by a four-lens data-architecture panel, synthesized from
`docs/milestones.md`, `docs/architecture.md`, `docs/expert-panel.md`,
`docs/RESEARCH.md`, and the shipped step −1 artifact.*
