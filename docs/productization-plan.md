# Agent Knowledge Base — Productization Plan

**Status:** Proposed refactor plan (design agreed 2026-09-05; no code changes yet).
**Scope:** genericize the KB core so it works for any corpus of data, decouple it
from the current uiux/creator-growth enriched-post schema, and add a CI quality
gate that catches retrieval regressions on every build.

---

## 1. Intent

Turn the current `kb/` vertical slice — a working but domain-hardcoded pipeline —
into a **generic, declarative, multi-corpus engine** whose core code contains zero
reference to any particular corpus's semantics. All corpus specifics move into
`config.yaml` + `user_data`. The refactor is a clean cutover: port the existing
185-post corpus through the new engine and prove metric parity with today's
baseline before deleting old code. A CI/quality gate must fail a build when
Recall@5/10, nDCG@10, or MRR regress below a committed baseline.

## 2. Scope boundary

**In scope (the middle of the pipeline):**
- **Ingest** — multi-source read, normalization, dedupe, provenance stamping.
- **Index** — chunking, lexical (BM25) + vector (dense) + hybrid (RRF) retrieval.
- **Materialize** — declarative aggregate/materialized views.
- **Verify** — eval harness + committed baseline + CI regression gate.
- **Serve** — structured search/get with provenance + typed abstention.

**Explicitly out of scope (separate concerns, by decision):**
- LLM **enrichment/extraction** (turning raw media/docs into semantic fields) —
  an upstream producer or an optional per-corpus adapter, never core logic.
- LLM **packaging** of query results into a prose answer (downstream consumer).
  Note: today's `query.answer()` is split accordingly — its abstention thresholds
  stay in serve; its text synthesis moves out.

**Non-goals (avoid overbuilding):** GraphRAG / multi-hop graph indexing · arbitrary
nested-relational schemas · a learned federated router · a REST/MCP server (that is
the M6 seam, not this pass).

## 3. Design thesis

**A thin universal envelope every input must satisfy + per-corpus declared rich
schema + a multi-corpus engine.** No force-normalization onto one rich schema.

- **Envelope (mandatory, same-shape for all inputs):** `id`, `content_hash`,
  provenance `{source, media_ref?, timestamp}`, and at least one retrievable text
  unit (or a `media_ref` whose text an extractor can derive).
- **Rich attributes (optional, declared per corpus):** `summary`, `tools_apps`,
  `value_score`, facets, etc. Never referenced by engine code by name.
- **Corpus model:** one corpus = multiple raw sources of *related* shape normalized
  onto that corpus's declared attribute schema. Truly different schemas = different
  corpora, each declared in config. Retrieval is unified **per corpus** over text
  chunks; cross-corpus search is a defined-but-deferred facade.

Rationale (from `docs/data-architecture.md` and the M4 ablation in `architecture.md`):
retrieval is schema-agnostic because BM25/dense rank *text chunks*, not schema;
structured filters, aggregation, enrichment profiles, gold sets, and eval baselines
only make sense within one declared schema.

## 4. Current state and coupling audit (grounding)

Current artifacts and their coupling, for reference during migration:

- `data/kb/kb-posts-all.json` — 185 records (86 uiux + 99 creator-growth; 149
  extracted, 36 pending). The two domains are one logical schema (enriched posts),
  so today's one-schema normalization is legitimate *for them*.
- M4 text baseline (uiux 24-question gold set): dense R@5 0.972 / R@10 1.0; hybrid
  R@5 0.917; BM25 R@5 0.781. Hybrid win-rate vs dense is 0.0% → RRF fusion is held
  until a trigger fires (see `architecture.md` "Re-evaluation triggers").
- `kb/` modules each re-derive repo root (`__file__.parent.parent`) and their own
  corpus/db paths; `ingest.py` bakes an absolute `C:/Users/evano/...` scrape root.
- Existing visual spikes (`kb/visual_image.py`, `kb/visual_video.py`) prove
  slides/video-frame retrieval works; gold sets exist.

Couplings that must be removed:
- **Schema coupling:** domain enums (`schema.py`), routing keywords, gold views
  (`tools`/`domains`/`creators`), query filters (`tools`/`owner`/`gated`/
  `value_score`), index-text field lists.
- **Source-layout coupling:** ingest walks the scrape repo's specific directory
  layout and reads `post_metadata.json`/`analysis.json` shapes.
- **Path coupling:** scattered module-level constants, absolute user path, no
  central config.

## 5. SOLID fixes (mapped to concrete violations)

| Principle | Current violation | Fix |
|---|---|---|
| SRP | `query.answer()` does retrieval + evidence flattening + gated detection + abstention + synthesis. `consolidate.py` mixes per-domain loaders, a bespoke mapper, collision rename, validation, write, report. | Stage = pure transformation (records in → records out, no IO/config globals) + a thin IO adapter. Mapping is config data, not per-domain code. |
| OCP (worst) | Adding a corpus edits `schema` enums, ingest funcs, consolidate loaders, routing keywords, `gold.VIEWS`, index-text lists, query filters. | Extension via config (declared schema/facets/sources/views) + registered strategies (embedder, backend, fusion). Model already in `dense._provider`; formalize everywhere. |
| LSP (latent) | `bm25/dense/hybrid/visual` retrievers each return post_ids but with different score semantics and drifting shapes. | One `Retriever` protocol returning `RankedHits[]`; consumers depend only on order + identity + optional per-retriever metadata, never absolute score. |
| ISP | `search(records, query, domains, content_type, owner, tools, gated, value_score_min, top_k)` is a fat schema-specific signature; CLI mirrors it. | Narrow generic `QueryParams {query, top_k, mode, filters: map}` validated against declared facets; separate narrow roles Retrieve / GetById / Abstain. |
| DIP | Stages read hardcoded paths/constants; IO + API calls not behind interfaces; not unit-testable without real disk/keys. | Stages composed via config + injected adapters; core logic pure and testable with in-memory fixtures. `eval`'s injected `retriever_fn` is the pattern to generalize. |
| DRY / cohesion | Three divergent index-text builders (`query._searchable_text`, `bm25._post_text`, `dense.index_text`). | One `Chunker` contract. |

## 6. Seams and contracts

### 6.1 Ingest — the minimum contract

Every input item (adapter output) MUST satisfy:

1. `id` + `content_hash` — otherwise dedupe, refresh, and index rebuild all fail.
2. Provenance `{source, media_ref?, timestamp}` — the core invariant.
3. One or more retrievable text units (or a `media_ref` with a registered
   extractor) — otherwise the item is un-indexable noise.
4. Failure of 1–3 is surfaced as a **coverage gap / abstention**, never silently
   dropped (mirrors existing "truncated JSON = hard-fail, not silent drop").

"Take any docs/media" is satisfied at the contract level because *deriving* text
from raw media (OCR, transcript, multimodal captioning) is an **adapter**, not core
logic. Core ingest accepts already-extracted text units or `media_ref` pointers; it
never fires a vision/LLM call itself.

Roles:

- `SourceAdapter` — reads a configured source location, yields source-native
  `RawItem`s.
- `Mapper` — applies declared field mapping/normalization → `CanonicalRecord`,
  stamping provenance + `content_hash`.
- `DedupePolicy` — resolves candidates by declared dedupe key (keep-first /
  newest / highest-confidence / version-append); cross-source id collisions get a
  declared namespace prefix.
- `IngestPipeline` — per-source, deterministic + idempotent (unchanged
  `content_hash` ⇒ skip, never re-bill). Any source add/remove touches no other
  source or engine code.

### 6.2 Index

- `Chunker` — `Record → Chunk[]`, chunk = `{record_id, field, text, provenance,
  chunk_idx, media_ref?}`, declared by config.
- `Index` protocol (backend seam) — BM25/FTS5 and vector/sqlite-vec are pluggable
  stores behind `add(doc)` / `retrieve(query, top_k, filters)`.
- `Embedder` (DIP) — provider interface (gemini/voyage) formalized; idempotency +
  cost estimate part of the contract (keyed by text hash + model + dims).
- `Retriever` — `retrieve(question, params) → RankedHits[]`, each hit
  `{record_id, score, rank, evidence/matched_fields, provenance}`. Lexical / dense /
  hybrid(RRF) are swappable strategies behind one signature.
- Contract: indexes are **derived, always rebuildable** from the canonical corpus;
  index version recorded.

### 6.3 Materialize

- Declarative `View` = `{name, group_by[fields], metrics, filters, freshness}`.
- Generic group-by/count/avg engine replaces bespoke `tools`/`domains`/`creators`
  views.
- Contract: every view row carries provenance + `materialized_at` + schema_version,
  and refuses to serve past a freshness threshold.

### 6.4 Verify

- `Evaluator` — gold set × retriever(s) → Recall@5/10, nDCG@10, MRR, abstention.
  Deterministic, offline, no API calls at scoring.
- `Baseline + Gate` — committed `baseline.json`; CI diffs a run against it and fails
  on regression; config/schema drift aborts.
- Reports keyed by `(schema_version, index_version, eval_set_version)`.

### 6.5 Serve

- `QueryParams` envelope — `{query, mode, top_k, filters: {field: value|list|range
  |min}, sort?}` — validated against the declared facet schema; unknown field ⇒
  clear error, never silent.
- CLI decoupled from corpus: e.g.
  `search --params '{"filters":{"tools":["figma"]},"top_k":20}'`.
- `get(record_id)` and typed abstention (`insufficient_evidence`) as first-class
  results. Provenance on every hit.

## 7. Repo layout

```
config.yaml          # root: engine/runtime/pipeline knobs + declared per-corpus
                     # schema/mapping/facets/views (user-editable)
pyproject.toml
src/<pkg>/           # engine core only; zero corpus-specific code
  config.py          # loader + validation (fail fast)
  core/              # records.py, provenance.py, contracts.py (Protocols above)
  ingest/  index/  materialize/  verify/  serve/
user_data/           # INPUTS, kept out of src
  sources/           # raw source exports (scrape snapshot, analysis.json, ...)
  gold/              # gold sets (versioned, committed)
artifacts/           # DERIVED + gitignored: canonical corpus, index dbs,
                     # materialized views, eval reports
tests/               # ported
ci/quality_gate.py   # regression entry the workflow calls
```

Decisions locked or to confirm:
- **Locked:** `src/` + `user_data/` (inputs) split; derived artifacts under
  `artifacts/`, gitignored.
- **Confirm:** per-corpus schema/mapping in root `config.yaml` (recommended, clearly
  sectioned) vs `user_data/corpus.yaml`. Split to a per-corpus file only if a second
  corpus appears.
- **Stopwords/tokenization:** engine-internal defaults; optionally overridable under
  an `index.tokenization` advanced section — not a first-class user knob.

## 8. Migration of existing data

- Port canonical records (`data/uiux/kb-posts.json`, `data/kb/kb-posts-all.json`)
  through the new canonical-corpus path under `artifacts/`.
- The scrape repo becomes one declared **source adapter** whose location comes from
  `config.yaml` (no hardcoded absolute path).
- Gold sets move to `user_data/gold/` (versioned).
- Materialized gold views (`data/gold/*.json`) and eval runs regenerate under
  `artifacts/`.

## 9. CI quality gate (cost-aware)

- Per PR build: build index from committed gold-relevant corpus, reusing cached
  artifacts keyed by content-hash + model (unchanged inputs skip re-embedding), then
  run eval on the committed gold set, diff vs `baseline.json`, fail on regression,
  attach the report artifact.
- **Decision:** small committed eval subset for fast per-PR gating + full eval on
  merge/nightly (recommended), vs full eval every PR (burns embedding budget).

## 10. Spike — raw-first vs enriched retrieval (run before locking the ingest seam)

**Question:** is enrichment load-bearing for recall, or can the minimum ingest
contract be raw text?

- On the existing 185-post corpus, build index text two ways from the same canonical
  records: (A) enriched — current `index_text`; (B) raw-only — source-derived text
  that survives without enrichment (caption + transcript + hashtags), i.e. what a
  generic doc adapter yields.
- Run committed gold sets through the existing eval harness; report Recall@5/10,
  nDCG@10, MRR + the lexical-miss pattern; report token/vector cost per corpus
  (transcripts dominate).
- **Reading it:** raw-only ≈ enriched Recall@5 → ingest can be "any text-bearing
  file," enrichment optional. Meaningful degradation → raw ingest works but is weak
  alone; the declared enrichment profile makes retrieval good — productize both, but
  enrichment stays an optional per-corpus adapter.
- Cost: near-zero — reuses harness + existing gold; only the (B) embedding run is
  new (bounded, sub-dollar).

## 11. Sequencing (each step keeps the quality gate green; no branch/code until step 1 review)

1. **This plan** + a draft `config.yaml` schema for review (in progress).
2. Skeleton + config loader + layout migration (pure move, no behavior change) on
   branch `feat/productize-kb`.
3. Generic ingest (adapters/mappers/dedupe) replacing `ingest.py` + `consolidate.py`.
4. Generic chunker + index backends + unified retriever/hybrid.
5. Declarative materializer replacing `gold.py` views.
6. Verify: evaluator + baseline + CI gate.
7. Serve: query-params envelope + CLI (removes hardcoded `--tools`/`--owner`/etc.).
8. Port existing 185-post corpus + gold sets through new config; prove metric parity
   with the current baseline before deleting old code (clean cutover).

## 12. Open decisions

- CI cadence: small-subset per-PR + full on merge (recommended) vs full every PR.
- Per-corpus declarations in root `config.yaml` (recommended) vs `user_data/corpus.yaml`.
- Index topology confirmed: multi-corpus engine, per-corpus text search; cross-corpus
  unified facade deferred.
- Whether the raw-vs-enriched spike runs before or in parallel with the refactor
  (recommended: before locking the ingest seam).

## 13. Assumptions and negative space

**Assumptions:** every input can be reduced to the thin envelope; enrichment and
answer-packaging remain external concerns; retrieval over text chunks is
schema-independent; provenance + version discipline is preserved as the core
invariant.

**What must not change:** the provenance invariant (no field without provenance);
version-keyed eval; read-only derived discipline; content-hash idempotency so
rebuilds never re-bill. Out of scope as decided in §2.
