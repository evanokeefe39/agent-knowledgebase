# Plan: Productize KB Engine — generic, config-driven, multi-corpus retrieval engine

**Status:** In progress (step 1 DONE)
**Branch:** `feat/productize-kb`
**Plan:** `docs/productization-plan.md` (authoritative design; §11 sequencing below, §7 layout, §9 gate, §12 resolutions)
**Implementation spec:** `docs/productization-build.md` (epic / user stories / DoD)
**Gate spike:** `tasks/plans/raw-vs-enriched-spike.md` — raw-first vs enriched retrieval; MUST run before locking the ingest seam (plan §10)
**Environment:** never use PowerShell; use `uv` for Python (repo `AGENTS.md`)

## Prerequisites — doc set (plan step 1)

- [x] `docs/productization-plan.md` — agreed plan + expert-panel-validated design
- [x] Config split: `config.yaml` (engine/runtime only) + `corpora/uiux.yaml` (per-corpus contract) — plan §12: split by KIND now, both committed, not under `user_data/`

## Step 2 — Skeleton + config loader + layout migration (pure move)

- [ ] `src/<pkg>/` engine core skeleton: `config.py`, `core/` (records, provenance, contracts), `ingest/`, `index/`, `materialize/`, `verify/`, `serve/`
- [ ] Config loader + validation, fail fast (type x role compatibility matrix enforced at load)
- [ ] Pure-move layout migration per plan §7: `config.yaml`, `corpora/`, `user_data/{sources,gold,baselines,canonical/<corpus>}` committed; `artifacts/` derived + gitignored; `tests/`; `ci/quality_gate.py`
- [ ] Gate inputs never live in a derived directory (gold sets + baselines committed under `user_data/`)
- [ ] Quality gate green after this step

## Step 3 — Generic ingest (adapters / mappers / dedupe)

- [ ] Replace `ingest.py` + `consolidate.py` with `SourceAdapter -> Mapper -> DedupePolicy -> IngestPipeline`
- [ ] Minimum ingest contract enforced: `id` + `content_hash`, provenance `{source, media_ref?, timestamp}`, >=1 retrievable text unit
- [ ] Envelope-required failures surfaced only as coverage gap (abstention) or abort — never silently dropped
- [ ] No hardcoded absolute scrape root; source location from config (scrape repo = one declared source adapter)
- [ ] Deterministic + idempotent by content_hash; add/remove source touches no other source or engine code
- [ ] Media-to-text derivation is an adapter, never core logic (core never fires a vision/LLM call)
- [x] GATE DONE: raw-vs-enriched spike run + read (2026-09-05; report `data/eval/runs/20260905-075117-raw-vs-enriched-spike.json`). READING 2 (meaningful degradation, Δ −0.0312): envelope contract stays RAW-text-shaped; enrichment = optional per-corpus accuracy adapter that additively improves DENSE recall (0.9722 vs 0.9410); Mapper/Chunker must accept enrichment-shaped `search`-role text when a corpus declares it, never assume it. Hybrid masks the gap (raw-hybrid R@5 0.917 = enriched-hybrid) — enrichment matters for the default dense channel. Cheapest raw win: map `caption` into the envelope (currently dropped).

## Step 4 — Generic chunker + index backends + unified retriever

- [ ] One `Chunker` contract replaces three divergent index-text builders
- [ ] `Index` protocol: BM25 FTS5 + vector sqlite-vec pluggable stores; indexes derived, always rebuildable from canonical corpus
- [ ] `Embedder` behind DIP; cost + idempotency part of contract
- [ ] One `Retriever -> RankedHits[]`; consumers depend on order + identity only, never absolute score (LSP fix)
- [ ] Rerank shipped disabled as `{strategy, top_n}` enabled-shape stub; gate on an RRF-style trigger (plan §12)
- [ ] `search`-role `weight` is lexical-only BM25 field boost in v1; dense is per-chunk

## Step 5 — Declarative materializer

- [ ] Replace `gold.py` bespoke views with declarative `View = {name, group_by, metrics, filters, freshness}` + generic group-by/count/avg engine
- [ ] Every row carries provenance + `materialized_at` + schema_version; refuses to serve past freshness
- [ ] `mean(bool)` = share documented convention

## Step 6 — Verify: evaluator + baseline + CI gate

- [ ] `Evaluator` -> Recall@5/10, nDCG@10, MRR + abstention (report-only in v1); deterministic, offline, no API calls at scoring
- [ ] Reports keyed by four-corner version tuple `(schema_version, index_version, eval_set_version, embedder_version)`
- [ ] Committed baseline under `user_data/baselines/`; diff vs baseline, fail on regression
- [ ] `ci/quality_gate.py` owns rebuild-from-canonical -> run gate as documented entry; runs per corpus (N corpora -> N evals)
- [ ] CI cadence per plan §9: small deterministic per-PR subset (`pr_subset: {size, seed, stratify_by}`, committed/stable) + full eval on merge/nightly that refreshes the authoritative baseline
- [ ] Cached artifacts keyed by content-hash + model; unchanged inputs skip re-embedding (never re-bill)
- [ ] Config/schema drift aborts the gate

## Step 7 — Serve: QueryParams envelope + CLI

- [ ] `QueryParams {query, corpus?, mode, top_k, cursor?, filters, sort?}` replaces fat `search(...)` signature; roles Retrieve/GetById/Abstain
- [ ] Filters as explicit ops `{field: {op, value}}`, op in {eq, in, gte, lte, between}; unknown field/op -> clear error, never silent
- [ ] Opaque cursor pagination + `total_matched` in result envelope
- [ ] `sort` restricted to declared filter/facet/metric/sort fields plus `_score`
- [ ] Optional `corpus` (id or list) reserved for the deferred cross-corpus facade
- [ ] CLI removes hardcoded `--tools` / `--owner` / `--gated` / `--value_score` filters
- [ ] `get(record_id)` + typed abstention (`insufficient_evidence`); provenance on every hit; abstention derived from coverage + margin signals only (plan §12)
- [ ] `max_top_k` as server policy; mode validated against declared strategies with `serve.defaults` fallback

## Step 8 — Port existing corpus + prove parity, then clean cutover

- [ ] PARITY/CUTOVER (blocked-on spike outcome; full story + DoD in `docs/productization-build.md`): port the 185-post corpus (86 uiux + 99 creator-growth) through the new canonical path
- [ ] Scrape repo becomes one declared source adapter; location from config, no absolute path
- [ ] Gold sets + baselines moved to committed `user_data/`; materialized gold views + eval runs regenerate under `artifacts/`
- [ ] Prove metric parity with today's M4 baseline (uiux 24-question gold: dense R@5 0.972 / R@10 1.0; hybrid R@5 0.917; BM25 R@5 0.781) BEFORE deleting old code
- [ ] Delete old `kb/` corpus-specific code only after parity is proven (clean cutover)

## Assumptions / notes

- Remaining open items (plan §13, tracked, non-blocking): corpus-level `index_version` bump policy; exact registered-transform list for the `ig_saved` adapter (format-specific; LFS-vs-pointer for canonical manifest payloads tracked in plan §13 as well).
- Every step must keep the quality gate green (plan §11 premise).

## Review

Task complete: tracker authored against `docs/productization-plan.md` §7/§9/§10/§11/§12/§13. Step 1 marked done; steps 2-8 enumerated as checkable items; spike gate and parity/cutover cross-referenced by path. No code run; no other files touched.
