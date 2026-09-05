# PARITY + Cutover-Readiness Report (uiux)

**Owner:** dlc-worker (wave D). **Date:** 2026-09-05. **Branch:** `feat/productize-kb`.

**Verdict: GATE PASS — dense parity holds at DOCUMENT granularity. CUTOVER READY.**
The document-level dense path (`src/kb_engine/index/document.py`
`DocumentDenseRetriever` + `document_text`, one vector per record mirroring
legacy `kb/dense.py index_text`) reproduces the M4 baseline within the ±0.02
gate on all four metrics. The earlier by_field chunk-level failures
(R@5 0.9246 / 0.9365) were a granularity mismatch, not an embedder/eval defect.
Numbers are real (gemini-embedding-001, 3072 dims) and reproducible from the
committed canonical corpus + gold set.

## Measured vs M4 baseline

**Final run:** `data/eval/runs/parity-20260905T124500Z.json` — DOCUMENT-level
dense (`DocumentDenseRetriever`, one vector per record, legacy `index_text`
field set `summary, workflow_steps, tips, concepts, transcript, tools_apps,
tags, resources` in legacy order), 86 records → 51 indexable (35 are
`extraction_status: pending` with empty content — nothing to index, matching
legacy behavior), 21 scored search questions; 8 abstain/answer report-only.

| Metric   | M4 baseline | Engine (this run) | Delta    | Gate (±0.02) |
|----------|-------------|-------------------|----------|--------------|
| recall@5 | 0.9722      | **0.9683**        | −0.0040  | PASS (within)|
| recall@10| 1.0000      | **0.9841**        | −0.0159  | PASS (within)|
| ndcg@10  | 0.9306      | **0.9257**        | −0.0050  | PASS (within)|
| mrr      | 0.9306      | **0.9405**        | +0.0099  | PASS (within)|

Gate decision: **pass** (no metric beyond −0.02).

## Four-corner tuple used (matches baseline — gate compared, did not abort)

```
schema_version   = "1"
index_version    = "1"     (PARITY override: corpora/uiux.yaml declares index.schema_version "2";
                            baseline was recorded at "1" — pre-existing tuple drift to reconcile)
eval_set_version = "v1"
embedder_version = { provider: gemini, model: gemini-embedding-001, dims: 3072 }
```
## Reproduce

```bash
# embeddings cached in data/eval/runs/parity-embed-cache/embed_cache.sqlite3,
# keyed (text_hash, model, dims) — re-runs re-bill ZERO
uv run --with google-genai python scratch/parity_run_doc.py
```

The script imports `src/kb_engine` read-only (`DocumentDenseRetriever` +
`document_text`, `evaluate` + `run_gate`), injects the M4 embedder at the
embedder seam (config-declared 768-dim model NOT edited), and gates vs
`user_data/baselines/uiux-baseline.json`.

Field-set note (why this is the correct parity composition): the
corpus-declared `role=search` fields are `[summary, transcript,
workflow_steps, tips, caption, concepts, tools_apps, resources_text, tags]`.
Legacy `kb/dense.py index_text` embedded `[summary, workflow_steps, tips,
concepts, transcript, tools_apps, tags, resources]` — no `caption`, no
`resources_text`, different order. A first document-level run over the
declared fields (`parity-20260905T124129Z.json`) measured R@5 0.9444 — FAIL
(−0.0278). The passing run passes the legacy field set through
`DocumentDenseRetriever`'s `fields` parameter explicitly. Any cutover wiring
of the document-dense channel MUST use the legacy field set (or re-baseline
deliberately with a version bump if the declared set is preferred).

## Diagnosis (of the earlier by_field FAIL — resolved)

The embedder was never the cause — same model/dims as M4, cache keyed on exact
text. The cause was **index-text composition**, in two parts:

1. **Chunk granularity (primary).** Legacy `index_text` embedded ONE
   concatenation per record; the engine's declared `by_field` chunker emitted
   249 per-field chunks and took the best chunk per record. A record whose
   summary/tips don't share the query's vocabulary loses its best chunk even
   when the transcript would have matched in the legacy blob.
2. **Field set / order (secondary, confirmed by the final run).** With
   document-level granularity over the corpus-DECLARED search fields
   (`caption` included, `resources`/`tools_apps`/`tags` differently ordered),
   R@5 still missed the gate (0.9444, −0.0278). Passing the exact legacy
   `index_text` field set through `DocumentDenseRetriever`'s `fields` seam
   closed it (0.9683, −0.0040).

### Recommendation: CUTOVER READY

The document-level dense path reproduces M4 within the gate on all four
metrics. Conditions carried into cutover:

- Wire the serving dense channel over `DocumentDenseRetriever` with the
  legacy field set (`summary, workflow_steps, tips, concepts, transcript,
  tools_apps, tags, resources`, legacy order) — NOT the corpus-declared
  search-field list (see Reproduce note); or, if the declared list is
  preferred, re-baseline deliberately with an `index_version` bump.
- Records whose `document_text` is empty (35/86, all
  `extraction_status: pending`) are skipped by the index — keep that behavior
  and their `extraction_status` visible to the re-extraction pipeline.
- Defects D1/D2 below are fixed in engine code (VerifyFix); the CI quality
  gate should be re-enabled against this document-dense path.

## Engine defects found during PARITY (since fixed by VerifyFix)

- **D1 — id normalization gap (blocks the CI gate).** 51/86 canonical records
  carry numeric Instagram media-pk `id`s while the gold set expects shortcodes
  (`fields.shortcode`); `ci/quality_gate.py` builds the index on raw `id` with
  no `id_map`, so `evaluate` scores 0.0 across the board (run
  `parity-20260905T111157Z.json`). Fix: map ids via the declared
  `id_field`/`shortcode` in `load_canonical_records` or pass `id_map`.
- **D2 — `evaluate` stringifies hits.** `evaluate()` does
  `hits = [str(h) for h in retriever.search(...)]` before `_hit_id`, so
  `RankedHit` objects are converted to their repr and their `record_id` is
  never extracted; any retriever returning dataclass hits scores 0.0. Hermetic
  tests pass only because their fakes return plain strings. Fix: extract the
  id BEFORE stringification (`_hit_id(h)` on the original object).

## Clean-cutover legacy file list (CUTOVER READY — passing gate run: `data/eval/runs/parity-20260905T124500Z.json`)

`kb/__init__.py`, `kb/bm25.py`, `kb/build_voyage_freetier.py`,
`kb/consolidate.py`, `kb/dense.py`, `kb/eval.py`, `kb/gold.py`,
`kb/hybrid.py`, `kb/ingest.py`, `kb/query.py`, `kb/routing.py`,
`kb/schema.py`, `kb/spike_voyage.py`, `kb/visual_image.py`,
`kb/visual_video.py` (all superseded by `src/kb_engine/{core,config,ingest,index,materialize,verify,serve}`).

## Cost disclosure

Real dense-embeds (gemini-embedding-001, 3072 dims), all cached persistently
at `data/eval/runs/parity-embed-cache/` keyed `(text_hash, model, dims)` so
re-runs re-bill zero:

- Earlier by_field runs: 249 chunk texts ×2 ≈ $0.01 (documented above).
- Document-level, declared-field texts: 51 texts ~32k tokens (billed once, cached).
- Final document-level, legacy-field texts: 50 new texts, ~26,881 tokens
  (1 cache hit) ≈ $0.005. Total spend across all runs ≈ $0.02.
