# Spike Plan: Raw-Only vs Enriched Retrieval (Pre-Implementation Gate)

**Status:** Ready to run — pre-implementation gate (docs/productization-plan.md §9 gate, §10 spike). Not yet run; this document contains no results.
**Owner:** dlc-worker (recommended runner; see §7).
**Repo:** agent-knowledgebase, branch `feat/productize-kb`.

---

## 1. Question

**Is enrichment load-bearing for retrieval, or can the minimum ingest contract be
raw text?**

Concretely: does the `"≥1 retrievable text unit"` envelope contract (plan §6.1)
need to be enrichment-shaped, or does raw source-derived text (caption +
transcript + hashtags/tags) retrieve as well as the current enriched index text?

## 2. Why before locking the ingest seam (dependency)

From docs/productization-plan.md §10: this spike's outcome determines whether the
minimum ingest contract must require enrichment-shaped text. Running it after the
Mapper/Chunker seams are locked risks redesigning them. It is a dependency of the
ingest design (plan §11 step 3), not a preference. Cost is near-zero: it reuses
the existing eval harness and committed gold sets; only variant (B)'s embedding
run is new.

## 3. Method — two index texts from the SAME canonical records

Corpus: `data/kb/kb-posts-all.json` (185 records: 86 uiux + 99 creator-growth;
149 extracted, 36 pending). Both variants build from the same canonical records;
only the index-text composition differs.

**Variant A — enriched (baseline):** the current `kb.dense.index_text` composition
(exact, from `kb/dense.py:155-186`): per record, newline-joined non-empty parts of

1. `summary`
2. `workflow_steps` (flat: strings or dict values joined by spaces)
3. `tips` (same flattening)
4. `concepts` — each as `"{term}: {explanation}"` (or bare term)
5. `transcript`
6. `tools_apps` (flat)
7. `tags` (flat)
8. `resources` — each as `"{name} — {purpose}"`

**Variant B — raw-only:** only source-derived text that survives without any
enrichment/extraction: `caption` (falls back to nothing — enriched `summary` is
NOT used) + `transcript` + `hashtags`/`tags`. This is what a generic doc adapter
(consumer of the thin envelope only, plan §3) would yield. Build a parallel index
text function with the same `\n`-join + strip; do not modify `kb/dense.py`.

Build each variant into its own provider DB file (never mixed across providers /
variants), mirroring `kb.dense.build` (batching, retry, `INSERT OR REPLACE`,
5s pacing sleep between batches). Variant A's vectors already exist in
`data/kb/dense.db` (gemini) — reuse them; no re-embed needed for (A).

## 4. Gold sets + harness

- Gold set: `data/eval/gold-set-v1.json` (24 uiux questions; `EVAL_SET_VERSION = v1`
  in `kb/eval.py`). Visual gold sets exist but are **out of scope** for this
  text-only spike.
- Harness: reuse `kb.eval.run_retrieval_eval` (metrics: Recall@5, Recall@10,
  nDCG@10 binary-relevance, MRR; `TOP_K_RECALL = (5, 10)`, `NDCG_K = 10`) and
  `kb.hybrid.run_ablation` (computes the metric set per retriever over the gold
  set, hybrid win rates, and writes `data/eval/runs/{timestamp}-ablation.json`
  keyed by `(schema_version, eval_set_version, retriever)`).
- Variant B channels into the harness by pointing its dense `retrieve_scored` at
  the (B) DB; run `run_ablation` once with the (A) dense module and once with the
  (B) dense module. BM25 channel is identical for both (lexical uses the raw text
  already) — report it once for reference.
- **Report additionally: the lexical-miss pattern** — questions where the dense
  channel on (A) is correct (gold hit in top-5) but (B) misses. Enumerate
  question_ids per comparison table row; this is the evidence for whether
  enrichment supplies vocabulary that raw text lacks (e.g. `concepts` terms,
  `tips`, `resources` names are enrichment-only fields absent from (B)).

## 5. Cost + measurement

- **Only variant (B) embeds new.** (A) vectors are cached in
  `data/kb/dense.db`; unchanged inputs skip re-embedding.
- Embedding cache/idempotency: variant keys must include `(text_hash, model,
  dims)` (the declared cache key, config.yaml `embedding` + corpora/uiux.yaml
  `refresh_hash_fields` note) so unchanged text never re-bills. Record per
  variant: number of texts embedded new, tokens, vectors, provider, model.
- Token/vector cost per corpus is recorded in the run report under
  `data/eval/runs/` alongside the metrics (the `run_ablation` JSON, extended with
  an `embed_cost` block: `{texts_new, tokens, vectors, provider, model, dims}`).
- Provider settings: default gemini (`gemini-embedding-001`, 3072 dims,
  `BATCH_SIZE = 40`, `MAX_RETRIES = 12`); Voyage is the alternate provider
  (`voyage-3` default, 1024 dims, override via `VOYAGE_MODEL`); select via
  `--provider` flag or `KB_EMBED_PROVIDER` env. Keys come from this repo's
  `.env`: **`GEMINI_API_KEY`** / **`VOYAGE_API_KEY`** (see `.env.example`).
  `embedding.batch_documents: 25` and `embedding.idempotent: true` in
  config.yaml are the target-state batch/idempotent settings the engine will
  inherit; the spike scripts pace manually (5s between batches) per
  `kb.dense.build`.
- Run everything via **uv**, never PowerShell (see §8).

Cost bound: ≤ one full embedding pass over 185 records' raw text (variant B
only), i.e. roughly the size of the transcript+caption+tags text for 185 posts —
on the order of a few hundred thousand embedding tokens at free-tier batch
pacing (~5 minutes of API wall time plus rate-limit sleeps). Re-running the
spike after a partial run costs nothing new for already-embedded texts.

## 6. Decision thresholds + reviewer call

Define tolerance: **raw ≈ enriched** iff variant B Recall@5 ≥ variant A
Recall@5 − 0.02 (absolute — same threshold as the committed gate regression
tolerance, config.yaml `verify.regression_threshold: 0.02`).

Two readings (from plan §10):

1. **Raw ≈ enriched Recall@5** (within tolerance) → the minimum ingest contract
   can be "any text-bearing file"; enrichment is optional and the envelope stays
   thin.
2. **Meaningful degradation** (below tolerance) → raw works but is weak alone;
   enrichment becomes an optional per-corpus adapter — never a hardcoded
   engine assumption. The Mapper/Chunker must accept enrichment-shaped text when
   a corpus declares it, but the envelope contract itself stays raw-text-shaped.

**Reviewer decides** which reading applies, using the Recall@5 delta plus the
lexical-miss pattern (are misses concentrated in enrichment-only vocabulary?).
The decision + rationale are written to the DoD record (§7) before the ingest
seam (plan §11 step 3) is implemented.

**Recommended runner:** `dlc-worker` (has `.env` keys and repo access; the run
is read-only over the corpus except for writes under `data/eval/runs/` and the
variant-B vector DB).

## 7. Definition of Done (binary checklist)

- [ ] Both variants' index texts built from `data/kb/kb-posts-all.json` (185 records); (A) served from cache, (B) embedded into its own DB file.
- [ ] Gold set `data/eval/gold-set-v1.json` run through the harness on both variants; Recall@5/10, nDCG@10, MRR computed for each.
- [ ] Lexical-miss pattern (dense-correct-on-A but raw-missed-on-B) enumerated by question_id.
- [ ] Metrics report written to `data/eval/runs/` keyed by the four-corner version tuple `(schema_version, index_version, eval_set_version, embedder_version)` — including the embedder (`provider, model, dims`) per variant.
- [ ] Embed cost recorded in the report (`texts_new, tokens, vectors, provider, model, dims`).
- [ ] Decision + rationale (reading 1 or 2, per §6) written into the run report.

## 8. Environment / run notes

- **Never use PowerShell.** Use bash/Git-Bash and **uv** for every command,
  e.g. `uv run python -m kb.hybrid --ablation`, `uv run python -m kb.dense --build`.
- Before the run, print expected runtime + cost estimate (text count × batch size
  → request count; records × batch pacing → wall time) so the operator can abort
  before any spend.
- Real entrypoints this plan relies on (all verified in code):
  - `kb.dense.build(overwrite, provider_name)` / `kb.dense.retrieve_scored` /
    `kb.dense.index_text` (`kb/dense.py`)
  - `kb.eval.run_retrieval_eval(corpus, gold_set, answer_fn)`, `kb.eval.load_gold_set`,
    `kb.eval.load_corpus` (`kb/eval.py`)
  - `kb.hybrid.run_ablation(gold_set_path, corpus)` / `kb.hybrid.main --ablation`
    (`kb/hybrid.py`)
  - `kb.query` CLI (`kb/query.py`) for spot-checking individual questions
- `.env` keys required: `GEMINI_API_KEY` (default provider) or `VOYAGE_API_KEY`
  (alternate); optional `KB_EMBED_PROVIDER`, `VOYAGE_MODEL`.
- The spike adds NO results to this file. All numbers live in the run report
  under `data/eval/runs/`.
