# LLM / RAG Evaluation Frameworks — Research for the Agent KB

**Status:** Research. **Date:** 2026-09-01
**Purpose:** choose how to measure the KB's performance *numerically* (not vibes)
and detect **regressions** when we change the index, chunking, model, prompt, or
schema. Maps to milestone **M3 (gold set + eval harness)** and **M7 (A/B + kill
gate)**.
**Sources:** web research, 2026-09-01. Links in §Sources.

---

## The problem we're solving

The KB is a retrieval + generation system with two answer paths:
- **M2/M4 unstructured** — `search` over flat JSON, later hybrid (BM25 + dense →
  RRF → rerank).
- **M5 structured** — guarded text-to-SQL over curated gold views.

Every change (a new extractor model, field-level chunking, a hybrid-retrieval
config, a schema bump, a prompt tweak, a data refresh) can silently improve or
degrade answer quality. Today we have **no numeric way to tell the difference** —
the only signal is vibes and manual spot-checks. We need:

1. **Offline regression evals** — a fixed gold set + numeric metrics, run on every
   change, that fail the change if quality dropped below a threshold.
2. **Attribution** — when a metric regresses, trace which component caused it
   (retriever, chunker, model, prompt).
3. **Cost/latency guardrails** — a "quality improved" change must not secretly
   double the bill.
4. **A/B comparison** — two configs over the same gold set, paired metrics (M7).

---

## Framework landscape (2026)

The three open-source Python frameworks most relevant to a RAG/KB system, plus
two observability-first tools and one managed platform.

| Framework | Category | Best at | Weakness for us |
|---|---|---|---|
| **Ragas** | RAG evaluation | Reference-free retrieval + grounding metrics (faithfulness, context precision/recall, answer relevancy) | Notebook-oriented; no first-class pytest/CI; no agent tracing; no synthetic dataset gen is the strong suite |
| **DeepEval** | All-in-one (Python) | "Pytest for LLM apps": test cases, metrics, assertions, thresholds, `assert_test()` + `deepeval test run` in CI; RAG + agent + chat metrics; **Agent Skill for coding agents**; local→Confident AI path | Heavier than needed for pure RAG; some metrics cost LLM judge calls |
| **Promptfoo** | CLI/YAML eval + red-team | **Layered regression gates** (smoke / regression / red-team / human review) with threshold tiers; cost+latency assertions; CI/CD; side-by-side model/prompt compare | YAML/config-driven, not Python-native metric library; now OpenAI-owned (vendor-neutrality concern) |
| **Braintrust** | Managed platform | LLM-as-judge, side-by-side regression diffs, CI quality gates, online scoring | Platform, not local-first; overkill for a 99-post POC |
| **Arize Phoenix** | Observability | Tracing + trace-to-dataset loop, RAG diagnostics | Observability-first, not a standalone metric library; overkill now |
| **TruLens** | Python instrumentation | RAG groundedness/relevance feedback functions, agent GPA | Now Snowflake-centric; not pytest/CI-native; we don't use Snowflake |

---

## The framework that fits: DeepEval (primary), Promptfoo's gate model (pattern), Ragas (metric reference)

For our stack — **Python, `uv`-managed, small corpus (99–101 posts), a coding
agent as the primary consumer, CI regression gates required** — the evidence
points to a layered recommendation:

### 1. DeepEval — the runner (adopt)
**Why:** it is Python-native with first-class **pytest + CI** (`assert_test()`,
`deepeval test run`), ships RAG metrics (faithfulness, context precision/recall,
answer relevancy, answer correctness) plus a 50+ metric catalog, has a **local
Agent Skill** (works with Claude Code / Cursor / Codex — it can generate a
dataset, run the suite, inspect failures, fix, rerun), and has a clean path from
local evals to Confident AI if we ever need managed reporting. This matches how
the KB itself is built and consumed (a coding agent driving evals).

Concretely for the KB:
- **Retrieval metrics (M4):** context precision / context recall against the M3
  gold set — are the right posts retrieved, in the right rank?
- **Answer metrics (M2/M7):** faithfulness (is the answer grounded in the cited
  posts?) and answer relevancy (does it answer the question?). Faithfulness is
  exactly our **silent-wrongness guard** — the top KB reliability risk per the
  expert panel.
- **Abstention:** assert the `insufficient_evidence` path fires when the gold set
  expects it (tests our US-7.1 abstention contract).
- **CI gate:** `deepeval test run` fails the build when a metric drops below a
  configured threshold — the regression detector we lack today.

### 2. Promptfoo's gate model — the threshold pattern (borrow, don't adopt)
Promptfoo's regression-gate architecture is the right *design* even if we use
DeepEval as the runner. Layer by risk, not one giant suite:

| Layer | Runs on | Threshold |
|---|---|---|
| **Smoke** (~10–30 must-never-break questions) | every change / PR | 100% pass — release blocker |
| **Regression** (broader realistic set) | merge / nightly | ~95% pass, reviewed failures |
| **Exploratory** (broad, unlabeled) | periodic | trend-based reporting, not blocking |
| **Red-team / abuse** | high-risk releases | block until fixed/accepted |

This maps cleanly to our M3 gold set: split it into a **smoke tier** (the core
epic questions that must never break) and a **regression tier** (the full
25–50 stratified set). Smoke gates every change; regression gates merges.

Also borrow Promptfoo's **cost + latency assertions**: a "better quality" change
must not silently double per-query cost — we already log tokens/cost in the M2
query log and per-query cost in M7.

### 3. Ragas — the metric vocabulary (reference)
We don't need to adopt Ragas wholesale, but its metric definitions are the
standard vocabulary we should use and can implement directly (or via DeepEval's
equivalents): **faithfulness, context precision, context recall, answer
relevancy, answer correctness**. Keeping these names consistent with the
literature makes our M3 metrics comparable to any external benchmark.

### What we do NOT adopt now
- **Braintrust / Phoenix / TruLens / Confident AI** — managed/observability-first
  platforms; overkill for a 99-post POC with a local, agent-consumed surface. The
  DeepEval→Confident AI path exists if we ever need it.
- **Promptfoo itself** — YAML-driven, OpenAI-owned roadmap; not Python-native
  enough for our pytest-driven, agent-driven dev loop. We borrow its *gate model*.

---

## Recommended eval stack (decision)

- **Runner / metrics:** DeepEval (pytest integration, RAG + faithfulness metrics,
  Agent Skill, CI gates). Installed via `uv` (per repo rule — never pip).
- **Gold set:** our M3 hand-authored set (25–50 stratified questions + 5–10
  unanswerables), split into **smoke** (must-never-break) and **regression** tiers
  per Promptfoo's model. Already specified in `docs/milestones.md` M3.
- **Metrics (from `docs/milestones.md` M3, kept, plus faithfulness):**
  Recall@5/10, nDCG@10, MRR (retrieval), routing accuracy, abstention rate
  (abstention), cost+latency per query, **+ faithfulness / answer relevancy**
  (generation, from DeepEval — the silent-wrongness guard).
- **Regression detection:** `deepeval test run` in CI with per-metric thresholds;
  metrics keyed by `(schema_version, index_version, eval_set_version)` so a
  regression is attributable to exactly what changed (from `docs/data-architecture.md`).
- **A/B (M7):** same gold set, two configs (e.g. hybrid vs BM25-only), paired
  metrics report + kill-gate verdict.

**Cost note:** some DeepEval metrics use an LLM-as-judge (LLM calls during
scoring). Per the M3 spec, use the cheapest judge model and the Batch API; the
gold set is small, so scoring is cents per run. Keep a "no API calls during pure
retrieval scoring" rule so retrieval metrics (Recall/nDCG/MRR) stay free and
fast.

---

## Open questions
1. **Judge model for faithfulness/answer-relevancy** — which cheap model, and does
   it need to match the extraction model family? (Versioning matters: judge model
   changes make historical scores non-comparable — record it in the eval-set
   version tuple.)
2. **Smoke-tier size** — how many must-never-break questions before a gold set is
   "regression-worthy"? (Promptfoo suggests ~10–30; we'd start nearer 10.)
3. **Threshold calibration** — what pass-rate per metric blocks a merge, vs is
   review-only? Needs a baseline snapshot from M3 before thresholds are set.
4. **Where evals run** — local `deepeval test run` per change, vs a CI action.
   The KB is a research repo (no CI configured yet per AGENTS.md); local-command
   gating is the immediate fit, CI later.

---
## Are there eval frameworks explicitly for *hybrid search*?

**Short answer: no — and that's by design.** Hybrid search (BM25 + dense → RRF)
is not a separate eval category. It is evaluated with the **standard IR
retrieval metrics** — Recall@k, nDCG@k, MRR, Hit@k — which the frameworks above
already provide (Ragas `context_precision`/`context_recall`; DeepEval equivalents;
BEIR/MTEB as offline benchmarks). The *hybrid-specific* work is not a metric, it
is an **ablation methodology**: comparing the fused hybrid result against each
single-channel baseline to prove fusion earns its keep. No framework ships that
ablation as a first-class object — you build it.

Two 2026 papers make this explicit:

- **Lysenstøen, "Training-Free Lexical–Dense Fusion" (arXiv 2606.04194, 2026-06):**
  a clean hybrid-fusion study. Metrics are the **field-standard retrieval set**
  (Hit@1, Recall@3/5, MRR, NDCG@5); the *hybrid contribution* is reported as a
  **delta over each single channel** (+8.8 to +17.2 pp Hit@1 over dense alone;
  +11.2 over BM25). A per-category "division of labor" analysis shows dense wins
  on multi-hop/temporal, BM25 wins on adversarial, fusion hedges both. The
  harness is a custom script — not a framework.
- **Zhang, "Dense Expands, Sparse Anchors" (arXiv 2608.15851, 2026-08):** hybrid
  evaluation on seven **BEIR** datasets with nDCG@10 and Recall@20, plus a
  **fusion-cutoff-sensitivity** check (a gain at one top-L cutoff can reverse at
  another) and per-channel "access depth" — again a custom protocol over standard
  metrics.

### What this means for the KB (M4)
The **M4 gate in `docs/milestones.md` is already correct**: "hybrid beats
single-method (BM25-only or dense-only) on the M3 gold set (≥60% win; top-3
contains the answer ≥80%)." That is precisely the standard hybrid ablation —
three configs (BM25-only / dense-only / hybrid) over the same gold set, scored
with Recall@k / nDCG / MRR, comparing hybrid vs each single channel. We do **not**
need a hybrid-specific framework; we need:

1. **A single-channel ablation harness** — run the gold set through BM25-only,
   dense-only, and hybrid; report each config's Recall@5/10, nDCG@10, MRR. This is
   the "if BM25-only ≈ hybrid, skip vector infra" fail signal.
2. **Division-of-labor breakdown** (per the fusion paper) — split gold questions
   by type (lexical-match vs semantic/fuzzy vs gated) and report which channel
   serves each. Tells us *why* hybrid helps (or doesn't) for our corpus.
3. **Fusion-cutoff sensitivity** (per the DESA paper) — check the fused top-k is
   not an artifact of the RRF top-L cutoff; record it in the query log.
4. **BEIR is NOT for us** — it's a general-domain offline benchmark; our gold set
   (M3) over the 99-post corpus is the right evaluator for the KB, not BEIR.

So the practical answer: use **DeepEval/Ragas for the metrics**, and build a
**thin custom ablation script** for the hybrid-vs-single-channel comparison that
the M4 gate requires. The frameworks give us the ruler; the ablation is the
experiment design.

## Sources
- DeepEval — "Top 5 LLM Evaluation Frameworks in 2026, Compared" (deepeval.com, 2026)
- ScrollTest — "PromptFoo Regression Gates for QA Teams in 2026" (scrolltest.com, 2026-07-27)
- DeepEval vs RAGAS vs TruLens comparisons (analyticsvidhya.com, datasumi.com, atlan.com, 2026)
- Promptfoo repository stats (GitHub: ~23.6k stars, 1.7M monthly npm downloads, 2026-07)
- RAG evaluation practice guides (braintrust.dev, bigdataboutique.com, latitude.so — offline regression testing, layered system)

---
*Generated 2026-09-01 by web research, mapped to `docs/milestones.md` (M3/M7)
and `docs/data-architecture.md` (version-keyed eval).*
