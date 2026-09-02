# Video Embedding — Research Memo (short IG reels)

**Date:** 2026-08-31 · **Scope:** Research for the agent-knowledgebase POC. Short IG reels (30s–3min).

> Note: web search was largely blocked during this thread; findings below were
> verified directly from primary vendor docs (Google Gemini API docs/model card/
> pricing). Cross-provider video-embedding head-to-head numbers were not
> independently corroborated — flagged accordingly.

---

## 1. Approaches to video embedding in 2026

| Approach | Description | Fit for short reels |
|---|---|---|
| **(a) Frame sampling + image embeddings** | Sample N frames (1 fps or keyframes), embed each with a multimodal/image embedder (CLIP/SigLIP/Gemini Embedding 2), pool (mean) into one vector | Cheap, standard baseline. Loses temporal structure; fine for "what does this video look like" similarity. |
| **(b) Native video encoders** | Model takes video directly. **Gemini Embedding 2** (`gemini-embedding-2`, stable April 2026) maps "text, images, video, audio, and PDFs into a unified embedding space." | **The pragmatic 2026 default** for short reels. One unified space; no separate per-frame pipeline. |
| **(c) VLM summary → embed text** | Use a multimodal VLM (e.g. Gemini 3.1 Flash-Lite) to summarize the video, then embed the summary text. | Good when the *narrative* matters and text retrieval is primary; not for visual similarity. |
| **(d) Token-based video LLM encoders** | Video-LLM encoders (Qwen2.5-VL class, CLAP for audio). | Overkill / experimental for a small POC; heavy infra. |

**Pragmatic default:** (b) native video embedding via **Gemini Embedding 2** — already in the Gemini stack, unified space, batch-discounted.

---

## 2. Gemini Embedding 2 — video specifics (primary source)

From official Google docs (`ai.google.dev/gemini-api/docs/models/gemini-embedding-2` + `docs/embeddings`):

- **Inputs:** text, image, video, audio, PDF → one unified embedding space.
- **Video limits:** max **120 sec**, MP4/MOV (H264/H265/AV1/VP9), **max 32 frames** —
  ≤32s sampled at 1fps; longer videos uniformly sampled to 32 frames.
- **Audio is NOT processed in video files.** → For speech content, you must embed
  the **transcript text separately** (this strongly supports making transcript
  text the primary retrieval surface; visual embedding is complementary).
- Output dims 128–3072 (MRL-truncatable; 768 recommended).
- Input token limit 8192 across modalities.

**Pricing (primary, from `ai.google.dev/gemini-api/docs/pricing`):**

| | Standard | Batch (−50%) |
|---|---|---|
| Text | $0.20 / 1M | $0.10 / 1M |
| Image | $0.45 / 1M (~$0.00012/img) | $0.225 / 1M (~$0.00006/img) |
| **Video** | **$12.00 / 1M ($0.00079/frame)** | **$6.00 / 1M ($0.000395/frame)** |
| Audio | $6.50 / 1M | $3.25 / 1M |

**Cost per short reel (batch):** capped at 32 frames regardless of length →
~32 × $0.000395 ≈ **$0.0126/reel** (up to 120s; a 180s reel needs 2 chunks ≈ $0.026).

- ~50-post visual subset: **~$0.65**
- all 809 posts' videos: **~$10.50**
- Trivially within the <$100 POC budget.

---

## 3. Where video value actually lives (for IG reels)

- **Speech (narration)** → transcript. IG reels are voiceover-driven; the transcript
  carries most of the *information*. Embed transcript text as the primary retrieval
  surface (already produced by the Gemini extraction pipeline).
- **On-screen visuals** → tool UIs, listicles, diagrams, URLs rendered in-frame.
  These are *not* in the transcript. Visual embedding (or key-frame image
  embedding) captures this; it's complementary and most valuable for the
  screen-share/design-heavy subset (~50 posts).

**Recommendation:** transcript text = primary; visual/frame embedding = secondary,
applied to the visual subset. Never rely on video embedding alone for reels whose
value is spoken — Gemini Embedding 2 ignores audio.

---

## 4. Recommendation for the POC

1. **Text (all 809):** embed transcript + caption + analysis fields with Gemini
   Embedding 2 text (batch). This is the retrieval backbone.
2. **Visual (subset / per-slide + keyframes):** Gemini Embedding 2 video for reels
   (≤120s, 32 frames) and multimodal image embedding for carousel slides — same
   model, one unified space, batch-discounted.
3. **Cost:** ~$0.65 (visual subset) to ~$10.50 (all video) — negligible.
4. **Watch-outs:** chunk videos >120s; remember audio isn't embedded (transcript
   covers speech); 32-frame cap means long-reel visual detail is coarse — combine
   with key-frame image embeddings for on-screen text.

**Cross-provider note:** OpenAI has no native video/image embedding product;
Cohere embed v4 is image-capable but not a native video embedder (and its image
path is rate-limited, ~400/min). Gemini Embedding 2 is the only 2026 product with
a batch-discounted unified text+image+video embedding space — which is why it's
the pragmatic single-model default for this POC.

---

## Key sources (primary)
- Gemini Embedding 2 model card: https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2
- Gemini embeddings docs (video limits, aggregation): https://ai.google.dev/gemini-api/docs/embeddings
- Gemini API pricing (text/image/video/audio, standard + batch): https://ai.google.dev/gemini-api/docs/pricing

---

# Companion: Image Embeddings (2026) + Model-Selection & Spike Method

*Synthesized from the image-embedding and embedding-eval research threads.*

## Image / multimodal embeddings — best, cheapest, best-value

| Model | Type | Price | Notes |
|---|---|---|---|
| **Gemini Embedding 2** | Multimodal (text+img+video+audio+PDF) | Batch: text $0.10/1M, image $0.225/1M (~$0.00006/img), video $6.00/1M (~$0.000395/frame) | STABLE (Apr 2026). 3072-dim MRL→768 rec. In-stack (Gemini). Only 2026 product with batch-discounted unified text+img+video space. No independent head-to-head vs Voyage yet (first-party claims). |
| **voyage-multimodal-3.5** | Multimodal, single-backbone | $0.12/1M text + $0.60/B pixels (~$0.00003–0.0012/img); 200M free text tokens + 150B free pixels | Strongest independent 2026 benchmark: +2.26% vs Cohere embed-v4, +30.6% vs Google Multimodal 001 on visual-doc NDCG@10; +4.65% on video at ~6x lower cost. GA since Jan 2026. Single-backbone solves CLIP modality-gap. 1024-dim MRL. |
| Cohere embed-v4.0 | Multimodal | $0.12 text / $0.47 image per 1K | Mature; image path rate-limited (~400/min), separate model. |
| OpenAI text-embedding-3-large/small | **Text only** | $0.13 / $0.02 per 1K | No native image/video embedding. MTEB 64.6%/62.3%. |
| Jina CLIP v2 / Nomic embed-vision / SigLIP (open) | Open CLIP-class | ~$0 marginal (self-host) | Hit CLIP modality-gap; need GPU; Jina CLIP v2 is **non-commercial** (cc-by-nc-4.0). Not worth infra for a one-shot POC. |

**Best-performing (independent evidence):** voyage-multimodal-3.5.
**Most economical (API):** Gemini Embedding 2 batch (image $0.00006, video ~$0.0126/reel); Voyage free tier covers the whole corpus.
**Best value for this POC:** a single multimodal model (Gemini Embedding 2 primary; Voyage if visual-doc quality wins an eval). A separate text+image pipeline is *not* worth it — corpus is text-in-image heavy (listicles) and cross-modal (text query → image) retrieval is required.

> **CORRECTED 2026-09-01 (verified against `docs.voyageai.com` + live API):**
> `voyage-multimodal-3.5` **IS available on the Voyage AI platform and works on
> this account** — it must be called via **`client.multimodal_embed()`**, NOT
> `client.embed()`. The earlier "Model voyage-multimodal-3.5 is not supported"
> error was a **wrong-method artifact**: `client.embed()` is the text-only
> endpoint and correctly rejects multimodal models (its supported list is
> `voyage-4*`, `voyage-3*`, `voyage-code-4`, etc.). Via
> `client.multimodal_embed(inputs=[['...']], model='voyage-multimodal-3.5')` it
> returns 1024-dim embeddings (verified live). Inputs are dict/list (text, PIL
> image, or Video), not bare strings.
>
> **Rate limits** (`docs.voyageai.com/docs/rate-limits`): Voyage gates on usage
> tier. Tier 1 (payment method attached) grants 2000 RPM across models —
> `voyage-3` 8M TPM, `voyage-multimodal-3.5` 2M TPM, `voyage-4*` 3-16M TPM.
> The **3 RPM / 10K TPM** limit observed during the index build is the
> **pre-Tier-1 reduced rate applied until a payment method is added** to the
> API key (the API returned: "add your payment method... reduced rate limits of
> 3 RPM and 10K TPM"). Adding a billing method unlocks Tier 1 (2000 RPM), making
> large batch builds practical; free tokens (e.g. 200M for voyage-3) still apply.
> No rate-limit increase is needed for the 185-post corpus once a payment method
> is attached.

**Whole-corpus embedding cost:** Gemini batch ≈ **$0.01–0.63** (images) + ~$10.50 (all video); Voyage ≈ $0.15–0.30 (covered by free quota). Tiny sliver of the <$100 budget. Self-hosting open models is a net loss at this scale.

## Do we need to test different models? (and throughput/reliability)

**Default: one multimodal model (Gemini Embedding 2).** Reasons: it's the only 2026 product with batch-discounted unified text+image+video in one space; OpenAI has no image/video product; Cohere's image path is slow and separate. Text-only bulk retrieval needs one provider.

**Test at most 2 candidates** — Gemini Embedding 2 vs one alternative (Voyage) — **only if a single-model spike underdelivers** on a small visual gold set. Key constraint: **embedding re-indexing is the hidden cost** — switching models = full re-index. So spike on a ~50-post subset, pick the winner, **index the whole corpus exactly once**. Never double-index.

**Throughput/reliability spike (only after model choice):**
- Verify **batch-video/frame feasibility** (the 32-frame / 120s cap) as the first check.
- Soak the winner for rate limits / 429s / retries on the actual batch job.
- Query-time latency only matters if live embedding is needed (it isn't for a snapshot KB — index once, query vectors at read time).

## Spike sequence (commit decision rule)
1. Embed ~50-post visual subset + gold set → compute Recall@5/MRR.
2. If strong → STOP, index whole corpus once in batch. If marginal → A/B one alternative on the identical gold set, adopt winner.
3. Throughput/429 soak on the winner only.
4. Skip self-hosting (iGPU not viable; no privacy gate; API cost is a few dollars).

## Key sources (primary)
- Gemini Embedding 2 model card: https://ai.google.dev/gemini-api/docs/models/gemini-embedding-2
- Gemini embeddings docs: https://ai.google.dev/gemini-api/docs/embeddings
- Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing
- Voyage multimodal-3.5 + pricing: https://docs.voyageai.com/docs/multimodal-embeddings · https://docs.voyageai.com/docs/pricing · https://blog.voyageai.com/2026/01/15/voyage-multimodal-3-5/
- OpenAI embeddings (text-only): https://platform.openai.com/docs/guides/embeddings
- Cohere embed-v4: https://docs.cohere.com/docs/embeddings
- MTEB: https://github.com/embeddings-benchmark/mteb
