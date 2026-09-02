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
| MRR | 0.930 | **1.000** | gemini |
| Index cost | ~$0.170 | **~$0.010** | gemini (~17x cheaper on images) |

### Video tier (30 video posts indexed, 804 frames, 31 gold questions after vq001 fix)

| Metric | voyage-multimodal-3.5 | gemini-embedding-2 | Winner |
|---|---|---|---|
| Recall@5 | 0.891 (0.919 post-fix) | **0.969** | gemini |
| Recall@10 | 0.969 | 0.969 | tie |
| nDCG@10 | 0.853 | **0.910** | gemini |
| MRR | 0.814 | **0.888** | gemini |
| Index cost | ~$0.111 | ~$0.318 | voyage (~2.9x cheaper on video) |

## Decision: keep gemini-embedding-2 for the visual tier

Gemini Embedding 2 **wins both the image AND video tiers on every metric where
they differ** (R@5, nDCG@10, MRR), matching Voyage at R@10. It is dramatically
cheaper on images (~17x) and ~2.9x more expensive on video — for this corpus
the two nearly cancel: whole-corpus index cost is ~$0.28 voyage vs ~$0.33
gemini (see cost note), i.e. essentially cost parity. The decision therefore
rests on accuracy, not cost. Cross-modal
text→visual retrieval works for both models; Gemini is more accurate.

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
4. **Video embedding cost is the only place Voyage wins** (~3x cheaper), and it's
   where the corpus is smallest (34 short reels). Not worth switching the tier.

## Artifacts
- Modules: `kb/visual_image.py`, `kb/visual_video.py`
- Image indexes: `data/kb/visual-image-{voyage,gemini}.db` (163 slides each)
- Video indexes: `data/kb/visual-video-{voyage,gemini}.db` (804 frames each)
- Gold sets: `data/eval/gold-set-visual-image.json` (30), `data/eval/gold-set-visual-video.json` (31)
- Reports: `data/eval/runs/20260902-085605-visual-image-spike.json`,
  `data/eval/runs/20260902-070910-visual-video-spike.json`
- Media: `~/repos/scrape-ig-saved-list/data/uiux/<creator>/<post_id>/`

## Cost note (whole-corpus projection, reconciled 2026-09-02)
Pricing basis (verified vendor docs): Voyage multimodal billed PER PIXEL
($0.60/1B, per-image clamp 50k-2M px); Gemini billed per carrier unit at the
batch/paid-tier rate. Free tiers apply during spikes (Voyage 150B px; Gemini
free); figures below are paid-tier batch estimates.
- Images (163 slides, 2160x2877 → each clamped ~2M px): voyage ~$0.17 vs
  gemini ~$0.010 (~17x cheaper on images).
- Video (804 frames across 30 posts): voyage ~$0.11 vs gemini ~$0.32
  (voyage ~2.9x cheaper on video).
- Combined full visual tier: voyage ~$0.28 vs gemini ~$0.33 — essentially
  **cost parity** (image savings ≈ video premium for Gemini). The decision to
  keep gemini-embedding-2 therefore rests on its accuracy lead on both
  carriers, not on cost.
