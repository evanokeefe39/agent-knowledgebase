# Spike & Experiment Lessons — agent-knowledgebase embeddings research

**Date:** 2026-09-02. **Scope:** cross-repo distillation of the embedding-spike
learnings from this repo, surfaced for `datalake` and `scrape-ig-saved-list`.
Each repo inherits only the slice actionable to it; this memo is the
authoritative source.

The three repos form one pipeline: **scrape** (`scrape-ig-saved-list`) collects
media → **datalake** runs Gemini enrichment over the same creator corpus →
**KB** (this repo) embeds and serves a curated subset. Spikes run on KB's uiux
corpus, but the cost/tier/quota mechanics apply to every repo that calls the
Gemini or Voyage APIs.

---

## 1. Embedding-carrier cost models (correct basis)

Vendor billing differs by carrier and must NOT be conflated:

- **Voyage multimodal is billed PER PIXEL** (`$0.60/1B px`), with a per-image
  clamp (50k–2M px). It is NOT billed per-document/token for image/video.
  Earlier analysis used a wrong "$6/1M doc-token" Voyage model — corrected.
- **Gemini Embedding 2 is billed PER CARRIER UNIT** (image, video frame).
- **Always compare at the SAME basis** — batch-vs-batch or standard-vs-standard.
  A batch-Gemini vs standard-Voyage comparison is unfair and reverses the cost
  conclusion (that bug produced a false "parity" claim).

**Relevant to:** all three repos (any repo costing Voyage vs Gemini must use the
per-pixel/per-unit basis and same-discount comparison).

## 2. Cost video by FRAMES from real durations, never file-count × per-video

Gemini caps video at **32 frames regardless of length**. Costing video as
`num_videos × 32 frames` overstates the total. Real durations (sampled 60
videos: mean 37s, median 33s) give **~23.7 frames/video mean** → **~202K
total frames** across the 8,524-video corpus, NOT `8524 × 32 ≈ 273K` (~35%
overcount).

Rule: **derive total frames from real (or sampled) durations** before
multiplying by the per-frame rate.

**Relevant to:** datalake + scrape (both cost/embed video from the same corpus).

## 3. Gemini Embedding pricing + batch tiers

- Gemini Embedding 2 **has batch pricing (50% off, paid tier only)**. Batch is
  NOT available on the free tier — the 50% rates require Tier 1 (linked billing).
  Free-tier embeddings cost $0 (but quota-limited).
- **Batch enqueued-token caps** (ai.google.dev rate-limits, 2026-08): Tier 1 =
  500k, Tier 2 = 5M, Tier 3 = 10M. These are per-model and differ from the
  Flash-Lite generation caps (10M/500M) datalake's AGENTS documents — embedding
  and generation are governed by separate limits.
- **The cap is IN-FLIGHT** (tokens enqueued across active batch jobs), NOT
  cumulative lifetime volume. **No corpus size ever "requires" or "exceeds" a
  tier as a blocker** — an 18M-token full-corpus embed runs on Tier 1 as ~36
  sequential batch jobs (~24h turnaround each). Tiers select concurrency/speed,
  never feasibility.
- **Tier unlocks**: Tier 1 = link active billing account; Tier 2 = $100 paid
  spend + 3 days; Tier 3 = $1,000 paid + 30 days. (Not cumulative-lifetime caps;
  these are account-tier qualification thresholds.)

**Relevant to:** datalake (same Google Cloud billing account, its own batch
strategy) + scrape (`quick_analyze.py` calls Gemini via the same key).

## 4. Scale economics — cost is cheap; quotas are the real constraint

Whole creator corpus (~17,368 images + ~8,524 videos → ~202K frames), both-batch:

| Subset | Gemini | Voyage |
|---|---|---|
| Current uiux (~197 media) | ~$0.33 | ~$0.19 |
| Curated 10% (~2.6K media) | ~$8 | ~$3 |
| Full corpus (~25.9K media) | ~$81 | ~$31 |

- Voyage is ~2.6x cheaper at every scale; cost never constrains at corpus scale.
- **The real gate is the free-tier quota ceiling** (~1000 embed/day + RPM/RPD)
  that stalled builds and throttled re-runs — not dollars. Tier 1 removes it.

**Relevant to:** datalake + scrape (cost/throughput planning on the shared corpus).

## 5. Spike methodology + results

- **Gold-set R@5 evaluation on your own corpus, not vendor benchmarks.** Voyage's
  independent-benchmark lead (visual-doc NDCG@10 +30.6%) did NOT reproduce on our
  carousel/screen-share data.
- **Results:** Gemini wins text + image (R@5 0.978) + video (R@5 0.969) tiers;
  Voyage wins cost. Decision rests on Gemini's accuracy lead.
- **API gotchas:** voyage-multimodal-3.5 requires `multimodal_embed()` (not
  `embed()`); Gemini `embed_content` with multiple image parts returns ONE joint
  embedding — embed per-image to avoid silent truncation.

**Relevant to:** datalake (its `enrichment_worker` shares the same API-usage
gotchas) + scrape (analysis via the same key).

---

## Source documents
- Spike plan: `docs/visual-tier-spike-plan.md` (issue #3)
- Results + cost note + scale projection: `docs/visual-tier-spike-results.md`
- Price reconciliation: `kb/visual_image.py`, `kb/visual_video.py` (fixed cost models)
- Vendor pricing: ai.google.dev rate-limits (2026-08) — batch caps, tier unlocks
