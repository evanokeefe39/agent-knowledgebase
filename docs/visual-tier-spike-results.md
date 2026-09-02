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
| Index cost | ~$1.44 | **~$0.004** | gemini (~300x cheaper on images) |

### Video tier (30 video posts indexed, 804 frames, 31 gold questions after vq001 fix)

| Metric | voyage-multimodal-3.5 | gemini-embedding-2 | Winner |
|---|---|---|---|
| Recall@5 | 0.891 (0.919 post-fix) | **0.969** | gemini |
| Recall@10 | 0.969 | 0.969 | tie |
| nDCG@10 | 0.853 | **0.910** | gemini |
| MRR | 0.814 | **0.888** | gemini |
| Index cost | ~$0.11 | ~$0.32 | voyage (~3x cheaper on video) |

## Decision: keep gemini-embedding-2 for the visual tier

Gemini Embedding 2 **wins both the image AND video tiers on every metric where
they differ** (R@5, nDCG@10, MRR), matching Voyage at R@10. It is dramatically
cheaper on images (~300x) and ~3x more expensive on video — but for a corpus
that is 163 images vs 34 short videos, the image savings dominate. Cross-modal
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

## Cost note (whole-corpus projection)
- Images (163 slides): gemini ~$0.004 vs voyage ~$1.44.
- Video (34 reels, ≤32 frames each): gemini ~$0.32 vs voyage ~$0.11.
- Combined: gemini ~$0.32 for the full visual tier; voyage ~$1.55. Gemini is
  cheaper overall for this corpus despite losing on video unit cost.
