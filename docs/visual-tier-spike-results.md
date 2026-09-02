# Visual-Tier Spike Results — voyage-multimodal-3.5 vs Gemini Embedding 2

**Date:** 2026-09-02. **Status:** Complete (issue #3). **Corpus:** uiux (image + video media).

Head-to-head of the two multimodal embedding models on OUR carousel-image and
video media — the first time either was validated on our own corpus. Text
retrieval was already settled (Gemini wins; see `data/eval/runs/20260902-061350-voyage4-spike.json`).

## Result summary

### Image tier (19 carousel posts, 163 slides, 30 gold questions)

| Metric | voyage-multimodal-3.5 | gemini-embedding-2 | Winner |
|---|---|---|---|
| Recall@5 | 0.944 | **0.978** | gemini |
| Recall@10 | 1.000 | 1.000 | tie |
| nDCG@10 | 0.940 | **0.994** | gemini |
| Index cost | ~$0.114 (batch) | **~$0.010** (batch) | gemini on images |

### Video tier (30 video posts indexed, 804 frames, 31 gold questions after vq001 fix)

| Metric | voyage-multimodal-3.5 | gemini-embedding-2 | Winner |
|---|---|---|---|
| Recall@5 | 0.891 (0.919 post-fix) | **0.969** | gemini |
| Recall@10 | 0.969 | 0.969 | tie |
| nDCG@10 | 0.853 | **0.910** | gemini |
| MRR | 0.814 | **0.888** | gemini |
| Index cost | ~$0.074 (batch) | ~$0.318 (batch) | voyage on video |

## Decision: keep gemini-embedding-2 for the visual tier

Gemini Embedding 2 **wins both the image AND video tiers on every metric where
they differ** (R@5, nDCG@10, MRR), matching Voyage at R@10. On cost, Voyage is
actually cheaper once both models are compared at the SAME basis: at standard
rates voyage ~$0.28 vs gemini ~$0.65 (Voyage ~2.3x cheaper); at both-batch
rates (Gemini 50% off, Voyage 33% off) voyage ~$0.19 vs gemini ~$0.33 (Voyage
~1.7x cheaper). Gemini's 50% batch discount does NOT close the gap on this
corpus. The decision therefore rests on Gemini's accuracy lead, not cost —
with the honest tradeoff that Voyage is cheaper and Gemini is more accurate.
Cross-modal text→visual retrieval works for both models; Gemini is more
accurate.

This matches the architecture's Gemini-first decision and the text-tier finding:
**Gemini is the better retrieval model across all three carriers on this corpus.**
Voyage's independent-benchmark lead (visual-doc NDCG +30.6%) does NOT reproduce
on our carousel/screen-share data.

## Notable findings

1. **voyage-multimodal-3.5 requires `multimodal_embed()`**, not `embed()` (text-only).
   Inputs are `List[List[str|PIL.Image]]`, not bare strings.
2. **Gemini `embed_content` with multiple image parts returns ONE joint embedding**,
   not one per image — embed per-image to avoid silent truncation (a bug caught
   and fixed during this spike).
3. **1 video (134s/25.8MB, Dblx-7rJUPG) exceeds Gemini's 120s cap** — excluded.
   A gold question targeting it (vq001) was removed from the gold set as
   unanswerable.
4. **Cost:** Voyage wins cost at every basis (total ~1.7x cheaper at both-batch);
   Gemini wins accuracy on both carriers. The corpus's absolute visual-tier cost
   is tiny (~$0.19-0.33), so cost does not materially drive the decision — Gemini
   is chosen for accuracy, with Voyage the documented cheaper alternative.

## Artifacts
- Modules: `kb/visual_image.py`, `kb/visual_video.py`
- Image indexes: `data/kb/visual-image-{voyage,gemini}.db` (163 slides each)
- Video indexes: `data/kb/visual-video-{voyage,gemini}.db` (804 frames each)
- Gold sets: `data/eval/gold-set-visual-image.json` (30), `data/eval/gold-set-visual-video.json` (31)
- Reports: `data/eval/runs/20260902-085605-visual-image-spike.json`,
  `data/eval/runs/20260902-070910-visual-video-spike.json`
- Media: `~/repos/scrape-ig-saved-list/data/uiux/<creator>/<post_id>/`

## Cost note (whole-corpus projection, fair basis, 2026-09-02)
Pricing basis (verified vendor docs): Voyage multimodal billed PER PIXEL
($0.60/1B, per-image clamp 50k-2M px); Gemini billed per carrier unit
(image/video). Free tiers apply during spikes (Voyage 150B px; Gemini free);
figures below are PAID-tier estimates on BOTH models. Voyage has a 33% Batch
discount; Gemini has a 50% Batch discount (paid tier). Compare at the same
basis, not batch-vs-standard:
- Images (163 slides): standard voyage ~$0.170 / gemini ~$0.020; BATCH voyage
  ~$0.114 / gemini ~$0.010. Gemini cheaper on images at either basis.
- Video (804 frames): standard voyage ~$0.111 / gemini ~$0.635; BATCH voyage
  ~$0.074 / gemini ~$0.318. Voyage cheaper on video at either basis.
- Full visual tier, both-batch (fair): voyage ~$0.188 vs gemini ~$0.327 —
  **Voyage ~1.7x cheaper**, not cost parity. (The earlier "parity" figure used
  batch-Gemini vs standard-Voyage, an unfair basis.)
- **Conclusion:** Gemini wins accuracy on both carriers; Voyage wins cost.
  The decision to keep gemini-embedding-2 rests on its accuracy lead and the
  corpus's modest absolute cost (~$0.33), not on a cost advantage it does not
  actually have.

## Scale projection — full creator corpus (datalake) + Gemini tier economics

**Source scale:** the datalake (~24.6K media) mirrors the scrape repo's full
creator corpus: ~17,368 images + ~8,524 videos. Sampled durations: mean 37s,
median 33s → ~23.7 frames/video (Gemini caps at 32; many shorter) → **~202K
frames** for the full corpus (NOT 8524×32; that overcounts by ~35%).

**Cost is cheap at every scale** (both-batch basis, real frame counts):

| Subset | Images | Videos | Frames | Gemini | Voyage |
|---|---|---|---|---|---|
| Current uiux | 163 | 34 | ~806 | ~$0.33 | ~$0.19 |
| Curated 10% | 1,737 | 852 | ~20K | ~$8 | ~$3 |
| Curated 25% | 4,342 | 2,131 | ~50K | ~$20 | ~$8 |
| Full corpus | 17,368 | 8,524 | ~202K | ~$81 | ~$31 |

Voyage is ~2.6x cheaper at every scale; cost is never the constraint.

### Gemini batch tiers — the enqueued-token cap is IN-FLIGHT, not cumulative

Gemini Embedding batch enqueued-token caps (ai.google.dev rate-limits, 2026-08):
Tier 1 = 500k, Tier 2 = 5M, Tier 3 = 10M. Critically, this cap applies to tokens
**IN FLIGHT across active batch jobs**, NOT cumulative lifetime corpus volume.
So **no corpus size ever "requires" or "exceeds" a tier as a blocker** — an
18M-token full-corpus embed runs fine on Tier 1 as a rolling pipeline of ~36
sequential jobs (~24h turnaround each). Higher tiers buy **concurrency/speed,
not feasibility**:

| Subset | Batch tokens | T1 (500k in-flight) | T2 (5M) | T3 (10M) |
|---|---|---|---|---|
| Current uiux | ~124K | 1 job ✓ | 1 job | 1 job |
| Curated 10% | ~1.8M | 4 jobs | 1 job ✓ | 1 job |
| Curated 25% | ~4.5M | 9 jobs | 1 job ✓ | 1 job |
| Full corpus | ~18M | ~36 jobs | ~4 jobs | 2 jobs ✓ |

### Tier guidance (correct framing)
- **Tier 1** removes the free-tier quota wall that actually blocked our builds and
  unlocks the real (batch) pricing. It embeds **any corpus** via rolling batch
  waves — for the realistic curated KB subset (well under 500k tokens) it's a
  single job. **This is all the KB needs.**
- **Tier 2/3 only buy fewer, faster waves** for a *full* 25.9K-media embed
  (T1 ≈ 36 jobs over ~5 weeks vs T2 ≈ 4 jobs over ~1 week). Not worth chasing
  for the KB's own ~$81 cost — Tier 2 unlocks at $100 paid spend + 3 days, so
  it only makes sense if aggregate Cloud spend crosses $100 organically.
- **There is no corpus size at which embedding is blocked.** Always chunk.
