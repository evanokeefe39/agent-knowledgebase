# PARITY + Cutover-Readiness Report (uiux)

**Owner:** dlc-worker (wave D). **Date:** 2026-09-05. **Branch:** `feat/productize-kb`.

**Verdict: GATE FAIL — dense parity does NOT hold. Cutover NOT READY.**
The gap is attributable to index-text composition (Build-4 chunker `by_field`
mode vs the legacy single-blob `kb/dense.py index_text`), not to the embedder
or the evaluation. Numbers are real (gemini-embedding-001, 3072 dims) and
reproducible from the committed canonical corpus + gold set.

## Measured vs M4 baseline

Run: `data/eval/runs/parity-20260905T111400Z.json` (86 records → 249 chunks, 21 scored
search questions; 8 abstain/answer questions report-only).

| Metric   | M4 baseline | Engine (this run) | Delta    | Gate (±0.02) |
|----------|-------------|-------------------|----------|--------------|
| recall@5 | 0.9722      | **0.9246**        | −0.0476  | FAIL         |
| recall@10| 1.0000      | **0.9246**        | −0.0754  | FAIL         |
| ndcg@10  | 0.9306      | **0.8891**        | −0.0415  | FAIL         |
| mrr      | 0.9306      | **0.9206**        | −0.0099  | PASS (within)|

R@5 == R@10 means every miss is a **total miss** (expected post not in top 10),
not a ranking-margin shuffle: 4 search questions (q002, q008, q011, q018) each
lose exactly one expected post entirely.

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
# embeddings cached in data/eval/runs/parity-embed-cache/embed_cache.sqlite3 —
# re-runs re-bill ZERO (verified: cache hits=249 misses=0 on second run)
uv run --with google-genai python scratch/parity_run.py
```

The script imports `src/kb_engine` read-only (Build-4 `Chunker.from_corpus` +
`DenseRetriever`, Build-6 `evaluate` + `run_gate`), injects the M4 embedder at
the embedder seam (config-declared gemini-embedding-2/768 NOT edited), and
gates vs `user_data/baselines/uiux-baseline.json`. The CI equivalent is
`uv run --with google-genai python ci/quality_gate.py --corpus uiux --embedder gemini --embedder-model gemini-embedding-001 --dims 3072 --retriever dense --index-version 1` — but it currently scores 0.0 (see defect D1 below).

## Diagnosis (honest, per the no-forced-numbers contract)

The embedder is NOT the cause — same model/dims as M4, and cache is keyed on
exact text. The cause is **index-text composition**:

1. **Chunk granularity.** Legacy `index_text` embedded ONE concatenation per
   record (summary + workflow_steps + tips + concepts(term: expl) + transcript
   + tools_apps + tags + resources). The engine's declared `by_field` chunker
   emits 249 per-field chunks over `[summary, transcript, workflow_steps, tips,
   concepts, caption]` and takes the best chunk per record. A record whose
   summary/tips don't share the query's vocabulary loses its best chunk even
   when the transcript (or metadata) would have matched in the legacy blob.
2. **Missing fields.** The legacy blob includes `tools_apps`, `tags`, and
   `resources`; the declared chunker fields omit all three. All 4 missed posts
   carry `tools_apps`; the evidence suggests per-field chunking is the larger
   factor, but the field omission compounds it.
3. **What parity is NOT sensitive to:** id normalization was corrected before
   scoring (defect D1), and the miss pattern is consistent — 4/21 questions
   each drop exactly one of 2–4 expected posts.

### Recommendation: align the chunker, do NOT re-baseline

The engine's composition is **not** close enough to accept as-is (recall@10
lost 0.0754, entirely from total misses — a serving-quality risk, not noise).
Before cutover:

- Preferred: give the dense channel a one-text-per-record composition
  (concatenated search fields, mirroring the legacy blob — e.g. a `by_record`
  chunker mode or `by_size` with `max_chars` above the corpus maximum), OR
- Add `tools_apps`, `tags`, `resources` to `index.chunker.fields` and re-measure;
  if recall is still below the gate, re-baseline ONLY after the composition
  change is deliberate, versioned (`index_version` bump), and recorded.

Cutover of `kb/` must stay blocked until a passing gate run exists.

## Engine defects found during PARITY (not fixed — outside my ownership)

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

## Clean-cutover legacy file list (DELETE ONLY after a passing gate run)

`kb/__init__.py`, `kb/bm25.py`, `kb/build_voyage_freetier.py`,
`kb/consolidate.py`, `kb/dense.py`, `kb/eval.py`, `kb/gold.py`,
`kb/hybrid.py`, `kb/ingest.py`, `kb/query.py`, `kb/routing.py`,
`kb/schema.py`, `kb/spike_voyage.py`, `kb/visual_image.py`,
`kb/visual_video.py` (all superseded by `src/kb_engine/{core,config,ingest,index,materialize,verify,serve}`).

## Cost disclosure

One authorized real dense-embed of the canonical corpus: 249 chunk texts,
~28,862 estimated tokens (gemini-embedding-001, 3072 dims), cached persistently
at `data/eval/runs/parity-embed-cache/` so all re-runs (including the final
post-fix parity re-run) re-bill zero. An earlier uncached attempt embedded the
same 249 texts once more (identical content) before the id-normalization
diagnosis — total ≈ 2× the corpus embedding, still on the order of $0.01.
