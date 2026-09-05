# Agent Knowledge Base — Productization Plan

**Status:** Agreed plan + expert-panel-validated design (2026-09-05). No engine
code yet; config split and contract fixes applied per panel consensus.
**Scope:** genericize the KB core so it works for any corpus, decouple it from the
uiux/creator-growth enriched-post schema, and add a CI quality gate that catches
retrieval regressions on every build.

---

## 1. Intent

Turn the current `kb/` vertical slice — a working but domain-hardcoded pipeline —
into a **generic, declarative, multi-corpus engine** whose core code contains zero
reference to any particular corpus's semantics. All corpus specifics move into
`config.yaml` + `corpora/<name>.yaml` + `user_data/`. Clean cutover: port the
existing 185-post corpus through the new engine and prove metric parity with
today's baseline before deleting old code. A CI quality gate must fail a build when
Recall@5/10, nDCG@10, or MRR regress below a committed baseline.

## 2. Scope boundary

**In scope:** ingest (multi-source read, normalize, dedupe, provenance-stamp) →
index (chunk, lexical/vector/hybrid) → materialize (declarative views) → verify
(eval + regression gate) → serve (structured search/get with provenance +
abstention).
**Out of scope (separate concerns):** LLM enrichment/extraction upstream; LLM
packaging of results into prose downstream. `query.answer()` splits accordingly —
abstention stays in serve, text synthesis moves out.
**Non-goals:** GraphRAG/multi-hop · arbitrary nested-relational schemas · learned
federated router · REST/MCP server (M6 seam, not this pass).

## 3. Design thesis

**Thin universal envelope every input must satisfy + per-corpus declared rich
schema + a multi-corpus engine.** No force-normalization onto one rich schema.

- **Envelope (mandatory):** `id`, `content_hash`, provenance
  `{source, media_ref?, timestamp}`, and ≥1 retrievable text unit (operationalized
  as: ≥1 `search`-role field yields a non-empty chunk, or a `media_ref` with a
  registered extractor).
- **Rich attributes (optional, per-corpus):** declared fields with locked
  type + role vocabulary; never referenced by engine code by name.
- **Corpus model:** one corpus = multiple related-shape sources normalized onto one
  declared schema; different schema = sibling corpus. Retrieval unified **per
  corpus** over text chunks; cross-corpus search is a deferred facade.

**Consensus anchor (industry):** LangChain `Document {page_content, metadata}` /
LlamaIndex `Document→Node` / `unstructured` all normalize diverse formats to a
minimal envelope + metadata bag — none force a rich universal schema. Per-field
capability declarations (Elasticsearch/Weaviate/Vespa) validate the role contract.
RAG eval CI gates (Recall@k/MRR vs committed baseline, retrieval eval separate
from generation) validate the verify design. dbt (`profiles.yml` runtime vs
`dbt_project.yml` project) validates the config split.

## 4. Current state and coupling audit

- `data/kb/kb-posts-all.json` — 185 records (86 uiux + 99 creator-growth; 149
  extracted, 36 pending). One logical schema (enriched posts).
- M4 text baseline (uiux 24-question gold): dense R@5 0.972 / R@10 1.0; hybrid R@5
  0.917; BM25 R@5 0.781. Hybrid win-rate 0.0% → RRF held until a trigger fires.
- `kb/` modules each re-derive repo root + own paths; `ingest.py` bakes an absolute
  `C:/Users/evano/...` scrape root.
- Visual spikes (`kb/visual_image.py`, `kb/visual_video.py`) prove slide/frame
  retrieval works.

Couplings to remove: schema enums (`schema.py`), routing keywords, gold views,
query filters (`tools`/`owner`/`gated`/`value_score`), index-text field lists,
source-layout walk, scattered module constants + absolute path.

## 5. SOLID fixes

| Principle | Current violation | Fix |
|---|---|---|
| SRP | `query.answer()` does retrieval+flatten+gating+abstention+synthesis; `consolidate.py` mixes loaders/mapper/collision/validation/write | Stage = pure transformation + thin IO adapter; mapping is config data |
| OCP (worst) | Adding a corpus edits schema enums, ingest funcs, loaders, routing keywords, gold views, index-text lists, query filters | Extension via config + registered strategies (embedder/backend/fusion); adapter is the sole extension point |
| LSP | bm25/dense/hybrid/visual retrievers return ids with different score semantics + drifting shapes | One `Retriever` → `RankedHits[]`; consumers depend on order + identity only, never absolute score |
| ISP | `search(...domains, content_type, owner, tools, gated, value_score_min, top_k)` fat schema-specific signature | Narrow generic `QueryParams` validated against declared facets; roles Retrieve/GetById/Abstain |
| DIP | Stages read hardcoded paths/constants; IO+API not behind interfaces | Stages composed via config + injected adapters; core pure/testable |
| DRY | Three divergent index-text builders | One `Chunker` contract |

## 6. Seams and contracts

### 6.1 Ingest — minimum contract
Every input item MUST satisfy: (1) `id` + `content_hash`; (2) provenance
`{source, media_ref?, timestamp}`; (3) ≥1 retrievable text unit (or `media_ref` +
registered extractor). Envelope-required failures may ONLY be surfaced as a
coverage **gap** (abstention) or **abort** the pipeline — never silently dropped.
Optional-attribute absence = null + coverage stat. Media→text derivation is an
**adapter**, never core logic (core never fires a vision/LLM call).

Roles: `SourceAdapter` (yields raw items) → `Mapper` (declared mapping → canonical
record, stamps provenance + content_hash) → `DedupePolicy` (declared key + policy +
deterministic order) → `IngestPipeline` (per-source, deterministic + idempotent by
content_hash; any source add/remove touches no other source or engine code).

### 6.2 Index
`Chunker` (`Record → Chunk[]`, provenance-carrying) · `Index` protocol (BM25 FTS5
+ vector sqlite-vec pluggable stores) · `Embedder` (DIP, cost + idempotency part of
contract) · `Retriever` (`→ RankedHits[]`, lexical/dense/hybrid swappable). Indexes
are derived, always rebuildable from the canonical corpus. `rerank` declared as a
disabled seam (`{strategy, top_n}` stub), not a live feature.

### 6.3 Materialize
Declarative `View = {name, group_by, metrics, filters, freshness}`; generic
group-by/count/avg engine replaces bespoke views. Every row carries provenance +
`materialized_at` + schema_version; refuses to serve past freshness. `mean(bool)` =
share is a documented convention.

### 6.4 Verify
`Evaluator` → Recall@5/10, nDCG@10, MRR, abstention (report-only in v1);
deterministic, offline, no API calls at scoring. Reports keyed by the **four-corner
version tuple** `(schema_version, index_version, eval_set_version,
embedder_version)` — embedder (provider+model+dims) added because the cache is
keyed by it. `Baseline + Gate`: committed baseline diff, fail on regression,
config/schema drift aborts.

### 6.5 Serve
`QueryParams` envelope `{query, corpus?, mode, top_k, cursor?, filters, sort?}`.
Filters are **explicit ops**: `filters: {field: {op, value}}`, op ∈
{eq, in, gte, lte, between}, shorthand scalar=eq / list=in. Unknown field OR op →
clear error, never silent. Opaque `cursor` for pagination (offset breaks under
re-ranking); `total_matched` in the result envelope. `sort: [{field, order}]`
restricted to declared filter/facet/metric/sort fields plus `_score`. Optional
`corpus` (id or list) reserved now so the deferred facade is not a breaking change.
Mode validated against declared strategies, caller-controllable, `serve.defaults`
fallback. `max_top_k` is server policy. `get(record_id)` + typed abstention
(`insufficient_evidence`) first-class; provenance on every hit.

### 6.6 Locked type + role vocabulary
**Types:** `text` (scalar) | `string` | `list[text]` | `list[string]` | `int` |
`float` | `bool` | `datetime` (ISO-8601) | `date` | `url`; `object`/`list[object]`
only with role `passthrough`. **Roles:** `search` (chunker source; `weight` is
lexical-only BM25 field boost in v1 — dense is per-chunk) | `filter` | `facet`
(filter + aggregatable; list-unnest) | `metric` (int/float: range filter + agg +
sort) | `sort` | `passthrough`; no role = stored + returned, no capability. A
type×role compatibility matrix is enforced at config load, fail fast. Vocabulary is
registration-extensible (no geo/currency until a corpus needs one).

## 7. Repo layout

```
config.yaml                 # engine/runtime ONLY (artifacts_dir, user_data_dir,
                            #   corpora_dir, default_corpus, global embedding,
                            #   global gate defaults)
corpora/<name>.yaml         # per-corpus data contract (schema/sources/mapping/
                            #   index/materialize/verify/serve) - committed,
                            #   one file per corpus; "add a corpus" = add a file
pyproject.toml
src/<pkg>/                  # engine core only; zero corpus-specific code
  config.py                 # loader + validation (fail fast)
  core/                     # records.py, provenance.py, contracts.py (Protocols)
  ingest/ index/ materialize/ verify/ serve/
user_data/                  # INPUTS + reference, committed (NOT derived):
  sources/                  #   raw source exports (large -> gitignored / LFS)
  gold/                     #   gold sets (versioned)
  baselines/                #   committed eval baselines (NEVER artifacts/)
  canonical/<corpus>/       #   pinned canonical manifest (ids + content_hash +
                            #     snapshot_id) the CI gate rebuilds from + validates
artifacts/                  # DERIVED + gitignored: index DBs, materialized views,
                            #   eval reports (never a gate input)
tests/
ci/quality_gate.py          # owns "rebuild-from-canonical -> run gate"; the CI entry
```

Key rules: a **gate input never lives in a derived directory** — gold sets and
baselines are committed under `user_data/`, only eval *reports* are derived. The
**canonical corpus manifest** is the pinned contract CI validates fresh ingest
against (new/removed/changed ids → fail or explicitly bless as a new snapshot).
`corpora/` is a directory convention (engine lists `corpora/*.yaml`), not a
registry file.

## 8. Migration of existing data

Port canonical records through the new canonical path; the scrape repo becomes one
declared source adapter whose location comes from config (no hardcoded absolute
path); gold sets + baselines move to committed `user_data/`; materialized gold
views + eval runs regenerate under `artifacts/`.

## 9. CI quality gate (cost-aware; resolved)

- **Cadence (resolved):** small deterministic per-PR subset + full eval on
  merge/nightly. The per-PR subset is committed/stable (`pr_subset: {size, seed,
  stratify_by}`), not random, so the gate is regression-sensitive and not noisy.
  Merge/nightly full runs refresh the authoritative baseline.
- Per-PR run: reuse cached artifacts keyed by content-hash + model (unchanged
  inputs skip re-embedding), run eval on the committed subset, diff vs committed
  baseline, fail on regression, attach report artifact.
- `ci/quality_gate.py` owns **rebuild-from-canonical → run gate** as its documented
  entry (otherwise "index rebuildable from canonical" is asserted, never
  exercised). It runs per corpus (N corpora → N evals).
- Gate metrics: Recall@5/10, nDCG@10, MRR + abstention (report-only). Gate on
  recall@10 while serving top_k 20 is a blind spot — optional cheap recall@20.

## 10. Spike — raw-first vs enriched retrieval (run BEFORE locking the ingest seam)

**Question:** is enrichment load-bearing for recall, or can the minimum ingest
contract be raw text? Its outcome determines whether the "≥1 retrievable text unit"
contract must be enrichment-shaped; running after risks redesigning Mapper/Chunker
— a dependency, not a preference.

- Build index text two ways on the existing corpus: (A) enriched (current
  `index_text`); (B) raw-only (caption + transcript + hashtags — what a generic doc
  adapter yields). Run committed gold sets through the eval harness; report
  Recall@5/10, nDCG@10, MRR + lexical-miss pattern + token/vector cost per corpus.
- **Reading it:** raw ≈ enriched Recall@5 → ingest can be "any text-bearing file,"
  enrichment optional. Meaningful degradation → raw works but is weak alone;
  enrichment is an optional per-corpus adapter, never a hardcoded assumption.
- Cost: near-zero — reuses harness + existing gold; only the (B) embedding run is new.

## 11. Sequencing (each step keeps the quality gate green)

1. **This plan** + config split (`config.yaml` + `corpora/uiux.yaml`) — DONE.
2. Skeleton + config loader + layout migration (pure move) on branch `feat/productize-kb`.
3. Generic ingest (adapters/mappers/dedupe) replacing `ingest.py` + `consolidate.py`.
4. Generic chunker + index backends + unified retriever/hybrid.
5. Declarative materializer replacing `gold.py` views.
6. Verify: evaluator + baseline + CI gate.
7. Serve: QueryParams envelope + CLI (removes hardcoded `--tools`/`--owner`/etc.).
8. Port existing corpus + gold sets through new config; prove metric parity before
   deleting old code (clean cutover).

## 12. Open decisions — RESOLVED (expert panel consensus)

| Decision | Resolution |
|---|---|
| CI cadence | Small deterministic/stratified subset per-PR + full eval on merge/nightly |
| Corpus-declaration placement | Split by KIND now: `config.yaml` (engine/runtime) + `corpora/<name>.yaml` (per-corpus contract); both committed, NOT under `user_data/` (dbt profiles-vs-project consensus) |
| Index topology | Multi-corpus engine, per-corpus text search, cross-corpus facade deferred (filters/agg/gold/baselines are schema-bound) |
| Spike timing | Before locking the ingest seam |
| Rerank | Ship disabled with an enabled-shape stub; gate on an RRF-style trigger |
| Transform DSL | Registered pure parametric primitives only (`identity`, `coerce_str/int/bool`, `list`, `template`, `path_join`); bespoke → per-source adapter, never registry accretion |
| Type/role vocabulary | Locked per §6.6, enforced by a load-time compatibility matrix |
| Abstention | Derived signals only (coverage + margin), never a raw retriever score |

## 13. Assumptions, negative space, remaining open items

**Assumptions:** every input reduces to the thin envelope; enrichment and
answer-packaging are external; retrieval over text chunks is schema-independent;
provenance + version discipline is the core invariant.

**Must not change:** provenance invariant; four-corner version keying; read-only
derived discipline; content-hash idempotency so rebuilds never re-bill.

**Remaining open (tracked, non-blocking):** corpus-level `index_version` bump
policy; exact registered-transform list for the `ig_saved` adapter (format
specific); whether the canonical manifest payloads ride LFS vs pointer-only in v1.
