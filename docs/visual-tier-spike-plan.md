# Visual-Tier Spike Plan — voyage-multimodal-3.5 vs Gemini Embedding 2 (image + video)

**Status:** Proposed plan (issue #3). **Date:** 2026-09-02.
**Owner:** dlc-worker (visual embeddings + gold set, stateful) + orchestrator verification.

Text retrieval is settled (Gemini wins all gold-set metrics over voyage-3/voyage-4;
see `data/eval/runs/20260902-061350-voyage4-spike.json`). The open question is the
**visual/multimodal tier**: does Voyage's independent benchmark lead on images/video
hold on OUR carousel/screen-share corpus, and is the cost difference worth it?

---

## Why this is the open question

- Architecture §3 calls for **one multimodal embedding model** for the ~50-post
  visual subset (carousel slides + reel keyframes).
- Research (`docs/research/media-embeddings.md`) favors Gemini Embedding 2 as primary
  but flags Voyage as the strongest independent 2026 benchmark performer (visual-doc
  NDCG@10 +30.6% vs Google Multimodal 001; +4.65% on video at ~6x lower cost).
- **We have never validated either model on our own media.** The text-tier head-to-head
  does not transfer — visual retrieval is a different signal.

## Media substrate (verified 2026-09-02, uiux corpus)

| Carrier | Posts | Files | Detail |
|---|---|---|---|
| Carousel images | 19 | 163 (7-15 slides/post) | `media_NN.jpg`, screen-share/listicle/UI-heavy |
| Video (mp4) | 34 | 34 | 2-134s, mean 40s; 1 exceeds Gemini 120s cap (134s/25.8MB → chunk or exclude) |
| Neither | 1 | — | text-only post |

## Models under test

| Model | API | Dims | Video limit | Image limit | Cost |
|---|---|---|---|---|---|
| Gemini Embedding 2 (`gemini-embedding-2`) | genai embed_content (multimodal) | 3072 MRL→768 | ≤120s, ≤32 frames | unified space | ~$0.00006/img, ~$0.0004/frame (batch) |
| voyage-multimodal-3.5 | `voyageai.multimodal_embed()` | 1024 MRL | ≤32k tokens/input | ≤20MB, ≤16M px | $0.60/B px; text $0.12/1M |

**Key API facts:**
- Voyage multimodal MUST use `multimodal_embed()`, NOT `embed()` (text-only).
  Inputs are `List[dict]`/`List[List[str|PIL.Image|Video]]`, not bare strings.
- Gemini video does NOT process audio — transcript text remains the speech-retrieval
  surface; visual embedding is complementary.
- Gemini free-tier embed quota is recurring-constrained; Voyage Tier-1 (billing
  attached, 2000 RPM) is now unlocked.

## Spike design

### 1. Image spike (primary — cheapest, highest signal)
- **Index:** embed each carousel slide per post with both models → store
  `(post_id, slide_idx, vec)` in per-model DBs (image vectors, matching dims/schema).
- **Gold set:** ~25-50 image-grounded questions. Two types:
  - *Visual-match*: "which post shows a tool UI / a dark-mode listicle / a
    3-column layout" — answerable from the image alone (tests visual similarity).
  - *Cross-modal*: text query → the post whose SLIDE visually matches the described
    content (the listicle/screen-share use case).
- **Metric:** Recall@5 / MRR per model, same eval-harness pattern as the text tier.

### 2. Video spike (secondary — cost-sensitive)
- **Index:** sample ≤32 frames/video (1 fps up to 32s; uniform sample beyond, per
  architecture §3), embed per model. Two retrieval modes:
  - *Cross-modal*: text query → video (does the model serve text→video?).
  - *Visual-video*: frame/visual query → video similarity.
- **Exclude or chunk** the single 134s video (Gemini 120s cap).
- **Metric:** Recall@5 / MRR per model.

### 3. Cross-modal retrieval is the real deliverable
The corpus is text-in-image heavy (listicles, tool UIs, URLs rendered in-frame).
The deciding question: **can either model answer a text query by retrieving the
right visual content** — and does Voyage's claimed single-backbone advantage show
up as fewer modality-gap misses than Gemini's?

### 4. Cost table
Per carrier per model: whole-corpus projection (19 image posts × ~11 slides avg;
34 videos × ≤32 frames). Compare against the research's estimates ($0.00006/img
Gemini vs Voyage pixel pricing; $0.0004/frame Gemini video).

## Decision gate (per re-evaluation triggers in `docs/architecture.md`)
- Gemini-visual, Voyage-visual, or split (text=Gemini + visual=Voyage) based on
  which wins Recall@5/MRR AND the cost delta.
- Embedding re-index is the hidden cost — spike on the subset, pick a winner,
  index the whole corpus once. Never double-index.

## Acceptance criteria
- [ ] Carousel-image head-to-head (both models) → Recall@5/MRR
- [ ] Video head-to-head (≤32 frames/post) → Recall@5/MRR
- [ ] Cross-modal text→visual retrieval measured (the key use case)
- [ ] Cost table per carrier + whole-corpus projection
- [ ] Documented decision (keep / switch / split) with re-index cost

## References
- Issue: #3
- `docs/research/media-embeddings.md` — visual/video design, corrected Voyage findings
- `docs/architecture.md` §2-3 — hybrid retrieval + embedding decisions
- Media on disk: `~/repos/scrape-ig-saved-list/data/uiux/<creator>/<post_id>/`
