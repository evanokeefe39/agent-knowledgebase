# Agent Knowledge Base — Productization Build: Implementation Epic & Stories

**Workstream:** refactor of the `kb/` vertical slice into a generic, config-driven,
multi-corpus retrieval engine, per `docs/productization-plan.md` (2026-09-05).
**Branch:** `feat/productize-kb`.

This is the *implementation* epic for the refactor. Product-level user stories
already live in `docs/user-stories.md` and are NOT duplicated here. This workstream
maps to **Epic 8 — Measurable performance & regression detection (developer /
maintainer)** in `docs/user-stories.md`: every story here exists so the maintainer
can rebuild, evaluate, and gate the KB mechanically instead of by vibes. Sequencing
context comes from the M0–M7 arc in `docs/milestones.md` (the refactor ports the
M4-era retrieval stack and preserves its M4 baseline).

**Format note:** stories follow the factory Executable-Spec shape (Intent, Context,
Behavioral contracts GIVEN/WHEN/THEN, Edge-case inventory, binary DoD, Negative
space, Open questions). Never use PowerShell; use `uv` for all Python work.

---

## Epic summary

Productize the hardcoded `kb/` pipeline (plan §1–§3): every module currently bakes
in the enriched-post schema, absolute paths, routing keywords, gold views, and
query filters. The refactor turns it into a **generic, declarative, multi-corpus
engine** whose core contains zero reference to any corpus's semantics. Every input
satisfies a thin mandatory envelope (`id`, `content_hash`, provenance, ≥1
retrievable text unit); rich attributes are declared per-corpus in
`corpora/<name>.yaml` against a locked type + role vocabulary (§6.6), and the
engine references declared types/roles — never field names. A CI quality gate
(`ci/quality_gate.py`, rebuild-from-canonical → eval → diff vs committed baseline)
fails any build that regresses Recall@5/10, nDCG@10, or MRR. Clean cutover: port
the existing 185-record corpus through the new engine, prove metric parity with the
M4 baseline, then delete old code.

---

## WORKER SPLIT

Every build story is assigned to one of the two worker types. Rationale: the plan's
SOLID fixes (§5) split cleanly along statefulness. **Application/feature code that
is stateless and deterministic** (config loading, adapters, chunker, retrievers,
materializer, evaluator, gate, CLI) is pure transformation + thin IO adapters —
testable offline, no data lifecycle. **The corpus itself — data contracts, manifests,
gold sets, baselines, migrations — is stateful data with lifecycle, drift, and
pinning concerns**, which is data-lifecycle work. Assigning both to one worker
would mix schema-provenance discipline with plumbing.

### sdlc-worker — stateless application / feature code

| Story | Deliverable |
|---|---|
| Build-1 | Skeleton + `src/<pkg>/config.py` loader + layout migration |
| Build-3 | Generic ingest: `SourceAdapter` / `Mapper` / `DedupePolicy` / `IngestPipeline` |
| Build-4 | `Chunker` + index backends (FTS5, sqlite-vec) + unified `Retriever`/hybrid |
| Build-5 | Declarative materializer (generic group-by/count/avg view engine) |
| Build-6 | `Evaluator` + baseline/gate logic + `ci/quality_gate.py` |
| Build-7 | `QueryParams` envelope + serve + CLI |

Why: each of these replaces a `kb/` module with a config-driven strategy set
(§6.1–§6.5). None owns data; all are exercised against whatever contract the
dlc-worker pins. No state carries across runs beyond derived, rebuildable
artifacts.

### dlc-worker — stateful data + eval/data lifecycle

| Story | Deliverable |
|---|---|
| Data-1 | Per-corpus data contract finalization: `corpora/uiux.yaml` schema + provenance fields (the envelope + schema IS the hand-off artifact) |
| Data-2 | Canonical-corpus manifest (`user_data/canonical/uiux/`) + migration of the 185 existing records |
| Data-3 | Gold set + committed baseline seeding under `user_data/gold/` + `user_data/baselines/` |
| Spike-1 | The §10 raw-vs-enriched SPIKE, runnable plan `tasks/plans/raw-vs-enriched-spike.md` |
| PARITY | The PARITY + CUTOVER story (port 185 records through the new engine; compare vs M4 numbers) |

Why: manifest pinning, snapshot blessing, gold-set versioning, baseline commits,
and content-hash migration discipline are data lifecycle invariants (§7 "a gate
input never lives in a derived directory"; §8 migration). The spike determines
whether the ingest contract must be enrichment-shaped — a data-contract decision
that must be measured, not coded.

### Hand-off protocol

- **The shared contract is the envelope + per-corpus schema in
  `corpora/uiux.yaml`** (locked type/role vocabulary §6.6, `schema_version`, refresh
  hash semantics, envelope-failure policy). dlc-worker owns this file's data meaning;
  sdlc-worker's loader validates it mechanically.
- dlc-worker signals sdlc-worker whenever the shared contract changes (field
  added/removed, type or role change, `schema_version` bump). sdlc-worker must not
  edit schema semantics unilaterally; sdlc-worker proposes loader/type-matrix changes
  through the same signal.
- Sequencing: Spike-1 and Data-1 unblock Build-3 (ingest seam lock, plan §10:
  the spike runs BEFORE locking the ingest seam). Build-3..7 can start on skeleton
  + contract in parallel thereafter.

---

## User stories (one per plan §11 step)

Plan §11 step 1 (plan + config split) is DONE; stories cover steps 2–8, with step 8
expanded into the explicit PARITY + CUTOVER story. Spike-1 (§10) sits before Build-3
as a blocking prerequisite.

---

### Spike-1 — Raw-vs-enriched retrieval spike (runs before the ingest seam locks)

**Owner:** dlc-worker. **Source:** plan §10, §12 (spike timing resolution).

**Intent:** determine whether enrichment is load-bearing for recall or whether the
minimum ingest contract can be raw text. Its outcome decides whether the "≥1
retrievable text unit" contract must be enrichment-shaped — running after would
force a Mapper/Chunker redesign.

**Context:** existing corpus + committed gold sets + existing eval harness
(`kb/eval.py`); near-zero cost — only the (B) raw-only embedding run is new.

**Behavioral contracts:**
- GIVEN the existing 185-record corpus, WHEN index text is built as (A) enriched
  (current `index_text`) and (B) raw-only (caption + transcript + hashtags, what a
  generic doc adapter yields), THEN both are evaluated through the committed gold
  sets reporting Recall@5/10, nDCG@10, MRR + lexical-miss pattern + token/vector
  cost.
- GIVEN raw ≈ enriched Recall@5, THEN the ingest contract is written as
  "any text-bearing file; enrichment optional."
- GIVEN meaningful degradation on (B), THEN raw is recorded as weak-alone and
  enrichment is declared an optional per-corpus adapter, never a hardcoded
  assumption.

**Edge cases:** embedder-version mismatch between the (A) and (B) runs invalidates
the comparison — the eval report must carry the four-corner version tuple; an
empty-raw-text record counts as an envelope gap, never silently dropped.

**DoD:**
- [ ] `tasks/plans/raw-vs-enriched-spike.md` exists as a runnable plan (exact
      commands/modules against `kb/dense.py`, `kb/hybrid.py`, `kb/query.py`,
      `kb/eval.py`)
- [ ] Both (A) and (B) runs complete and produce metric reports
- [ ] Report states the reading (raw-sufficient vs enrichment-optional-adapter)
- [ ] Report is committed and cited by Build-3

**Negative space:** no new engine code; no registry changes; no second corpus.

**Outcome (executed 2026-09-05, dlc-worker):** Reading 2 — meaningful degradation.
A (enriched) dense R@5 **0.9722** vs B (raw-only) **0.9410**, delta **−0.0312**
outside the 0.02 gate; variant A reproduced M4 (R@5 0.9722/0.972, R@10 1.0) as a
validity gate first. 0 full A-correct/B-missed questions — degradation is 3 partial
recall losses (q013/q017/q018) from ranking-margin shifts, not enrichment-only
vocabulary. Report committed:
`data/eval/runs/20260905-075117-raw-vs-enriched-spike.json`; scratch preserved
(gitignored) at `scratch/spike_raw_enriched/`.

**Applied to Build-3 / Data-1:** (1) the "≥1 retrievable text unit" envelope
contract stays **raw-text-shaped** — it does not require enrichment; enrichment is
an optional per-corpus **accuracy adapter** that additively improves DENSE recall,
and Mapper/Chunker must accept enrichment-shaped `search`-role text only when a
corpus declares it. (2) Enrichment value is channel-dependent — the dense-only gap
is masked by hybrid (raw-hybrid R@5 0.917 = enriched-hybrid), so enrichment matters
for the default dense serving channel; the fusion-vs-dense and enrichment decisions
are coupled. (3) Captions do not survive into KbPost v1 (raw = transcript + tags);
mapping `caption` into the envelope is the cheapest raw-recall win.

**DoD:**
- [x] `tasks/plans/raw-vs-enriched-spike.md` exists as a runnable plan (exact
      commands/modules against `kb/dense.py`, `kb/hybrid.py`, `kb/query.py`,
      `kb/eval.py`)
- [x] Both (A) and (B) runs complete and produce metric reports
- [x] Report states the reading (Reading 2 — enrichment-optional-adapter)
- [ ] Report is committed and cited by Build-3   (committed `7ba0a23`; cite when Build-3 lands)

---

### Build-1 — Skeleton, config loader, layout migration (plan §11 step 2)

**Owner:** sdlc-worker.

**Intent:** pure-move the codebase to the §7 layout and load the two-config split
fail-fast.

**Context:** `config.yaml` (engine/runtime) + `corpora/*.yaml` (per-corpus
contract) already exist as agreed shapes; no engine consumes them yet.

**Behavioral contracts:**
- GIVEN `config.yaml` + any `corpora/<name>.yaml`, WHEN the loader runs, THEN it
  validates the locked type×role compatibility matrix (§6.6) and fails fast on the
  first invalid combination, naming file + field.
- GIVEN one corpus file with a broken declaration, WHEN the loader enumerates
  `corpora/*.yaml`, THEN the other corpora still load (one broken corpus cannot
  fail every corpus).
- GIVEN `${VAR}` expansion and relative paths, WHEN a path resolves, THEN
  config.yaml paths resolve against repo root and corpus paths resolve against
  repo root via the loader (never a module-local re-derivation).
- GIVEN engine code, THEN it contains zero corpus-specific references (no field
  names, enums, routing keywords, absolute paths).

**Edge cases:** unknown type OR role string → fail fast, never coerce; `object` /
`list[object]` with any role other than `passthrough` → fail fast; unknown
registered adapter / transform id → fail fast; an omitted `default_corpus` with a
corpus-less query errors (no silent fallback).

**DoD:**
- [ ] Layout matches plan §7 (config.yaml, corpora/, src/<pkg>/{core,ingest,index,
      materialize,verify,serve}, user_data/{sources,gold,baselines,canonical},
      artifacts/, tests/, ci/)
- [ ] Loader enforces type×role matrix fail-fast (test proves rejection)
- [ ] Zero corpus-specific code in engine core
- [ ] Old module-path constants/absolute scrape root removed from the moved code

**Negative space:** no registry file for corpora (directory convention only); no
geo/currency types.

**Open questions:** corpus-level `index_version` bump policy (tracked, non-blocking).

---

### Build-3 — Generic ingest (plan §11 step 3) — gated on Spike-1

**Owner:** sdlc-worker (code) against the dlc-worker's Data-1 contract.

**Intent:** replace `ingest.py` + `consolidate.py` with
`SourceAdapter → Mapper → DedupePolicy → IngestPipeline` (§6.1).

**Behavioral contracts:**
- GIVEN any input item, WHEN it fails an envelope requirement (`id` + `content_hash`,
  provenance `{source, media_ref?, timestamp}`, ≥1 retrievable text unit), THEN the
  pipeline surfaces it ONLY as a coverage **gap** (abstention) or **abort** — never
  a silent discard.
- GIVEN an optional-attribute absence, THEN it becomes null + a coverage stat,
  never a failure.
- GIVEN declared mapping with registered pure transforms only (`identity`,
  `coerce_str/int/bool`, `list`, `template`, `path_join`), WHEN mapping runs, THEN
  anything not expressible as a primitive lives in the per-source adapter and
  never accretes into the registry.
- GIVEN a pipeline re-run over unchanged sources, THEN output is identical
  (deterministic + idempotent by `content_hash`).
- GIVEN a source added or removed, THEN no other source or engine code changes.

**Edge cases:** unknown filter field or op downstream of ingest → clear error,
never silent (enforced at serve; ingest must not pre-silence); dedupe order
`source_declaration` is the tiebreak — a missing declared order is a config error;
media→text derivation is an adapter only (core never fires a vision/LLM call);
`extraction_status` via `presence_to_status` is declared in the source, not
hardcoded.

**DoD:**
- [ ] `ingest.py` and `consolidate.py` responsibilities replaced by the four
      declared contracts
- [ ] Envelope-failure paths produce gap/abort, proven by test
- [ ] Pipeline deterministic + idempotent by content_hash (re-run test)
- [ ] Scrape-root absolute path removed; location comes from config

**Negative space:** no LLM enrichment in core; no transform-registry growth.

**Open questions:** exact registered-transform list for the `ig_saved` adapter
(tracked, non-blocking).

---

### Build-4 — Chunker, index backends, unified retriever (plan §11 step 4)

**Owner:** sdlc-worker.

**Intent:** one `Chunker` contract (kills three divergent index-text builders),
pluggable BM25 FTS5 + vector sqlite-vec stores, one `Retriever → RankedHits[]`
(§6.2).

**Behavioral contracts:**
- GIVEN a record with role=search fields, WHEN chunked, THEN chunks carry
  provenance `(record_id, field)` and chunking follows the declared
  `by_field`/`by_size` mode.
- GIVEN any retriever (lexical/dense/hybrid), WHEN it returns hits, THEN the shape
  is `RankedHits[]` and consumers depend on order + identity only, never absolute
  score.
- GIVEN the embedder, THEN cost + idempotency are part of its contract: cache keyed
  by `(text_hash, model, dims)` so identical inputs never re-bill.
- GIVEN indexes, THEN they are derived and always rebuildable from the canonical
  corpus.
- GIVEN `rerank`, THEN it ships as a disabled seam (`{strategy, top_n}` stub), not
  a live feature.

**Edge cases:** content-hash refresh — re-ingest with unchanged hash skips
re-embedding; a changed hash re-indexes exactly that record; dense is per-chunk
unweighted (search `weight` is a BM25 field boost only); `max_top_k` caps callers.

**DoD:**
- [ ] One `Chunker` contract; divergent index-text builders deleted
- [ ] bm25/dense/hybrid all return `RankedHits[]` (shape test per strategy)
- [ ] Embed cache keyed by (text_hash, model, dims); re-run re-bills zero
- [ ] `rerank` stub present, disabled; indexes rebuildable from canonical

**Negative space:** no rerank implementation; no cross-corpus index.

**Open questions:** none.

---

### Build-5 — Declarative materializer (plan §11 step 5)

**Owner:** sdlc-worker.

**Intent:** generic group-by/count/avg engine replaces bespoke `gold.py` views;
`View = {name, group_by, metrics, filters, freshness}` (§6.3).

**Behavioral contracts:**
- GIVEN a declared view, WHEN materialized, THEN every row carries provenance +
  `materialized_at` + schema_version.
- GIVEN a view older than its declared freshness, WHEN served, THEN it refuses.
- GIVEN `mean(bool)`, THEN it computes share (documented convention).
- GIVEN a list facet group-by (e.g. `tools_apps`), THEN values unnest per value.

**Edge cases:** filter with unknown field/op → clear error, never silent; a metric
over a non-metric-role field → config-load fail fast; empty group sets emit rows
with zero counts, never absent rows.

**DoD:**
- [ ] `gold.py` bespoke views replaced by the generic engine
- [ ] Rows carry provenance + materialized_at + schema_version (test)
- [ ] Stale view refuses to serve (test)
- [ ] mean(bool)=share documented

**Negative space:** no guarded text-to-SQL tier (that is M5's product surface,
unchanged).

**Open questions:** none.

---

### Build-6 — Verify: evaluator + baseline + CI gate (plan §11 step 6)

**Owner:** sdlc-worker (evaluator/gate code) against dlc-worker's Data-3 committed
inputs.

**Intent:** `Evaluator → Recall@5/10, nDCG@10, MRR, abstention (report-only)`;
committed baseline diff; `ci/quality_gate.py` as the documented entry (§6.4, §9).

**Behavioral contracts:**
- GIVEN a committed gold set + baseline under `user_data/`, WHEN the gate runs,
  THEN scoring is deterministic, offline, with no API calls at scoring time.
- GIVEN any eval report, THEN it is keyed by the four-corner version tuple
  `(schema_version, index_version, eval_set_version, embedder_version)`.
- GIVEN a per-PR run, THEN it evaluates the committed `pr_subset` (deterministic
  size/seed/stratify) and fails on regression beyond `regression_threshold: 0.02`.
- GIVEN merge/nightly, THEN the full eval refreshes the authoritative baseline.
- GIVEN N declared corpora, WHEN `ci/quality_gate.py` runs, THEN N evals run (per
  corpus: rebuild-from-canonical → gate).
- GIVEN config or schema drift, THEN the gate aborts rather than scoring across a
  version mismatch.

**Edge cases:** multi-corpus gate = N independent evals, one corpus's failure fails
the gate without masking others; gate inputs never live in `artifacts/` (gold +
baselines committed, only reports derived); an unchanged-input PR skips
re-embedding via the content-hash + model cache; serving top_k 20 while gating
only on recall@10 is a blind spot — optional cheap recall@20 noted in the report.

**DoD:**
- [ ] Evaluator emits the full metric set deterministically (same-run-twice test)
- [ ] Reports keyed by the four-corner tuple
- [ ] `ci/quality_gate.py` rebuilds from canonical manifest then gates
- [ ] Baseline diff fails CI on regression >0.02; report artifact attached
- [ ] Deterministic `pr_subset` (size 8, seed 1, stratify_by) used per-PR

**Negative space:** abstention gating (report-only in v1); generation-side eval.

**Open questions:** recall@20 gate metric — optional, decide at merge.

---

### Build-7 — Serve: QueryParams envelope + CLI (plan §11 step 7)

**Owner:** sdlc-worker.

**Intent:** narrow generic `QueryParams` replaces the fat schema-specific signature
(§6.5); removes hardcoded `--tools`/`--owner`/etc.

**Behavioral contracts:**
- GIVEN `QueryParams {query, corpus?, mode, top_k, cursor?, filters, sort?}`, WHEN
  validated, THEN filters are explicit ops `{field: {op, value}}`, op ∈ {eq, in,
  gte, lte, between}, shorthand scalar=eq / list=in.
- GIVEN an unknown filter field OR unknown op, THEN the caller gets a clear error,
  never silent acceptance.
- GIVEN `sort`, THEN it is restricted to declared filter/facet/metric/sort fields
  plus `_score`.
- GIVEN pagination, THEN it uses an opaque `cursor` (offset breaks under
  re-ranking) and `total_matched` in the result envelope.
- GIVEN a mode, THEN it validates against declared retrieval strategies with
  `serve.defaults` fallback; `max_top_k` is server policy.
- GIVEN a point lookup `get(record_id)`, THEN it returns the record with
  provenance; insufficient evidence returns typed abstention
  (`insufficient_evidence`).
- GIVEN abstention, THEN it keys on derived signals only (coverage ratio, relative
  margin) — never a raw retriever score.

**Edge cases:** cross-retriever abstention must use derived signals only — BM25/
dense/RRF scores are incomparable scales (unbounded vs [-1,1] vs rank-sum); an
omitted `corpus` scope applies `default_corpus` at the caller boundary only and
errors otherwise; optional `corpus` (id or list) reserved now so the deferred
cross-corpus facade is not a breaking change; cursor from an older index version is
rejected, not misread.

**DoD:**
- [ ] `QueryParams` envelope implemented per §6.5 with op validation
- [ ] Unknown field/op produce clear errors (test both)
- [ ] Cursor pagination + total_matched in result envelope
- [ ] Typed `insufficient_evidence` abstention on derived signals (test)
- [ ] CLI hardcoded `--tools`/`--owner`/etc. flags removed

**Negative space:** no REST/MCP server (M6 seam, later pass); no LLM answer
packaging (`query.answer()` text synthesis moves out of core).

**Open questions:** none.

---

### Data-1 — Finalize the per-corpus data contract (runs alongside Build-1)

**Owner:** dlc-worker.

**Intent:** make `corpora/uiux.yaml` + the thin envelope the authoritative shared
contract (§3, §6.6) that sdlc-worker's loader validates and every other story
depends on.

**Behavioral contracts:**
- GIVEN the declared schema, THEN every field carries a locked type (§6.6) and a
  role from the locked vocabulary, with `refresh_hash_fields` semantics declared
  (empty = hash covers all mapped fields).
- GIVEN `missing.envelope_failure`, THEN it is exactly one of `gap | abort` —
  never discard.
- GIVEN a source declaration, THEN it pins `snapshot`, `dedupe.key`, `dedupe.order`,
  `dedupe.policy`, and provenance fields — sufficient for sdlc-worker to build the
  adapter without guessing data semantics.
- GIVEN any contract change, THEN dlc-worker signals sdlc-worker (see Hand-off
  protocol) before sdlc-worker's dependent code merges.

**Edge cases:** schema/embedder drift → both are corners of the version tuple; a
role change on a field used by an index/serve block is a breaking contract change
requiring a `schema_version` bump; media-expiry is represented as a `media_ref`
provenance pointer into the byte cache, never copied bytes into core.

**DoD:**
- [ ] `corpora/uiux.yaml` exemplar finalized against §6.6 vocabulary
- [ ] Envelope requirements stated as machine-checkable declarations
- [ ] Hand-off signal sent to sdlc-worker on finalization
- [ ] No envelope-required failure path ends in silent discard

**Negative space:** no second corpus file yet (`corpora/creator-growth.yaml` is
created when declared, post-ingest-spike).

**Open questions:** none blocking.

---

### Data-2 — Canonical-corpus manifest + migration of the 185 records

**Owner:** dlc-worker.

**Intent:** pin the 185-record corpus (86 uiux + 99 creator-growth; 149 extracted,
36 pending) as the canonical contract CI validates against (§7, §8).

**Behavioral contracts:**
- GIVEN the migrated records, THEN `user_data/canonical/uiux/` holds the pinned
  manifest (ids + content_hash + snapshot_id) that `ci/quality_gate.py` rebuilds
  from and validates fresh ingest against.
- GIVEN fresh ingest over the same sources, WHEN run, THEN a new/removed/changed
  id fails, or is explicitly blessed as a new snapshot.
- GIVEN the scrape repo, THEN it becomes one declared source adapter whose location
  comes from config — no hardcoded `C:/Users/evano/...` absolute path.

**Edge cases:** content-hash refresh — a record with unchanged hash re-migrates at
zero embedding cost; a changed hash re-indexes exactly that record; records failing
envelope requirements surface as gaps in a coverage report, never discarded;
`schema_version` change during migration forces a version-tuple bump so baselines
are not silently compared across schemas.

**DoD:**
- [ ] Manifest covers all 185 records with ids + content_hash + snapshot_id
- [ ] Fresh-ingest validation fails on id drift (test)
- [ ] Migration deterministic and idempotent by content_hash
- [ ] No absolute scrape-root path remains in config or code

**Negative space:** no re-extraction or new enrichment during migration.

**Open questions:** whether canonical manifest payloads ride LFS vs pointer-only in
v1 (tracked, non-blocking).

---

### Data-3 — Gold set + committed baseline seeding

**Owner:** dlc-worker.

**Intent:** move gold sets + baselines to committed `user_data/` so the gate has
committed, non-derived inputs (§7, §8, §9).

**Behavioral contracts:**
- GIVEN the uiux 24-question gold, THEN it lands at `user_data/gold/uiux-v1.json`
  with `eval_set_version: v1`.
- GIVEN the M4 baseline, THEN it lands at `user_data/baselines/uiux-baseline.json`
  keyed by the four-corner version tuple.
- GIVEN a gate run, THEN a gate input never resolves into `artifacts/` (derived,
  gitignored).

**Edge cases:** baseline refresh only on merge/nightly full runs, never by a
failing per-PR run; a gold-set edit bumps `eval_set_version` and re-baselines
explicitly; materialized gold views + eval runs regenerate under `artifacts/`.

**DoD:**
- [ ] Gold set + baseline committed under user_data/
- [ ] Baseline keys match the four-corner tuple
- [ ] No gate input under artifacts/ (test asserts resolution)
- [ ] Existing M4 gold runs reproduce under artifacts/

**Negative space:** no new gold questions authored in this pass.

**Open questions:** none.

---

### PARITY + CUTOVER — Port the corpus through the new engine and prove parity before deletion

**Owner:** dlc-worker (executes the port + metric comparison) with sdlc-worker's
engine stories merged. **Blocked-on:** Spike-1 (plan §10/§12: the spike runs
BEFORE the ingest seam locks; its outcome shapes Mapper/Chunker) and Build-1..7.

**Intent:** clean cutover per plan §1/§8/§11 step 8: the 185-record corpus through
the new config-driven engine reproduces today's M4 metrics within tolerance, and
only then is old `kb/` code deleted. No shims, no parallel-maintenance period.

**Context (authoritative numbers, plan §4):** M4 text baseline on the uiux
24-question gold set — dense Recall@5 **0.972**, dense Recall@10 **1.0**; hybrid
Recall@5 **0.917**; BM25 Recall@5 **0.781**. Hybrid win-rate **0.0%** → RRF held
until a trigger fires; `corpora/uiux.yaml` sets `retrieval.default: dense` for the
same reason.

**Behavioral contracts:**
- GIVEN the ported 185-record corpus, WHEN the uiux 24-question gold set is run
  through the new engine, THEN dense Recall@5 ≥ 0.972, dense Recall@10 = 1.0,
  hybrid Recall@5 ≥ 0.917, and BM25 Recall@5 ≥ 0.781 each within the committed
  `regression_threshold` (0.02 absolute) of the M4 baseline — else cutover fails.
- GIVEN parity is proven, THEN old `kb/` schema enums, routing keywords, gold
  views, query filters, index-text builders, and the absolute-path ingest are
  deleted in the same cutover — no deprecated paths, no aliases, no shims.
- GIVEN parity is NOT proven, THEN cutover stops: the regression is attributed via
  the four-corner version tuple and fixed before any deletion.
- GIVEN the report, THEN it is keyed by
  `(schema_version, index_version, eval_set_version, embedder_version)` and diffs
  against `user_data/baselines/uiux-baseline.json`.

**Edge cases:** multi-corpus parity — the gate runs N evals (one per declared
corpus); only uiux has a committed baseline in this pass, so only uiux gates
cutover; envelope-required failures during the port appear as coverage gaps, never
silent record loss (count 185 in → 185 gap-accounted out); embedder-version drift
between M4 and the port re-keys the baseline rather than silently comparing
metrics; schema drift aborts the gate.

**DoD:**
- [ ] All 185 records ported through the new engine; gap/abort accounting shows 0
      silently dropped
- [ ] Gate run reproduces the four M4 numbers within the 0.02 threshold
- [ ] Parity report committed and keyed by the four-corner tuple
- [ ] Old `kb/` hardcoded pipeline deleted after parity (clean cutover)
- [ ] Spike-1 result cited in the port report

**Negative space:** no new features during cutover; no baseline relaxation to make
parity pass.

**Open questions:** none — the spike dependency and the numbers are fixed above.

---

## Negative space (explicitly OUT OF SCOPE for this build)

Per plan §2 and §13, this workstream does NOT include:

- **GraphRAG / multi-hop graph retrieval.**
- **A learned federated router** — the agent routes itself from a capability
  manifest; no learned routing component.
- **REST/MCP server** — the M6 packaging seam is a later pass; this build ships
  CLI + `QueryParams` only.
- **LLM enrichment/extraction in core** — media→text and enrichment are adapters
  upstream; core never fires a vision/LLM call.
- **LLM answer packaging** — `query.answer()` text synthesis moves out; serve
  stays structured search/get with provenance + abstention.
- **Arbitrary nested-relational schemas** — `object`/`list[object]` are
  `passthrough` only.
- **A live reranker** — disabled seam stub only.

---

## Open questions log

Intentionally minimal/near-empty: plan §12 resolved all build decisions by expert
panel; the remaining items are tracked and **non-blocking** for this build:

1. **Corpus-level `index_version` bump policy** (plan §13) — touches Build-1's
   loader and the version tuple; decide before the first baseline refresh, not
   before skeleton.
2. **Canonical manifest payloads: LFS vs pointer-only in v1** (plan §13) — affects
   Data-2 storage only; either choice satisfies the manifest contract.

Spike-1's raw-vs-enriched outcome is a dependency, not an open question: its
reading gates the ingest seam (Build-3), not the plan.