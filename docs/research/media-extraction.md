# Media Value Extraction — Research Memo
*Extracting value from social-media MEDIA (Instagram saved posts) for an agent-queryable knowledge base. Research only. State of the art as of 2026-08-31.*

---

## 1. Image2Text / Vision Models for Carousel Listicles (text-in-image)

### The problem
Instagram carousels are frequently text-as-image: each slide is a rendered "slide deck" whose content (tool names, URLs, steps, tips) lives in the pixels, not in the caption. The repo confirms this — the scraped `alt_text`/`caption` fields frequently say things like *"Cover slide titled 'Brand Systems'. Text reads 'The 5 layers behind every scalable brand...'"*; the meaningful listicle content is only readable by vision. Extracting this requires either dedicated OCR + layout analysis or a multimodal VLM that reads the image holistically.

### 2026 state: multimodal VLMs have largely absorbed pure OCR for this use case
Document/image understanding has shifted from rule-based OCR pipelines to **vision-first architectures** that "understand document structure before extraction," which is the key property for carousel slides where reading order/columns matter. Multimodal LLMs now "process text and images natively, understanding documents holistically by integrating semantics, layout, and visual cues." ([flexi.ink](https://flexi.ink/blog/business/ai-document-extraction-in-2026-techniques-accuracy-and-integration), [vellum.ai](https://www.vellum.ai/blog/document-data-extraction-llms-vs-ocrs), [matik.io](https://www.matik.io/blog/the-definitive-guide-to-automating-documents-in-2026))

- Printed-text OCR accuracy at the top end is 95–99% character accuracy on clean inputs, dropping to 60–75% on low-quality images / unusual fonts ([recrew.ai](https://www.recrew.ai/blog/what-is-optical-character-recognition-ocr), [local-ai-zone.github.io](https://local-ai-zone.github.io/guides/best-ai-ocr-models-ultimate-ranking-2026.html)). IG carousel slides are usually clean rendered text, so they sit in the high-accuracy regime.
- For **layout-aware** extraction: Transformer-based layout models (LayoutLM family, DiT/ViT) "segment pages into typed regions (text blocks, tables, figures)" and run before OCR to preserve reading order and table structure — the failure mode classic OCR has (multi-column collapse). ([extend.ai](https://www.extend.ai/resources/document-layout-analysis-page-structure))
- **Multimodal-LLM approaches vs. dedicated OCR engines**: For generic listicle slides, the frontier-VLM approach (feed the image, ask for structured JSON) is now the recommended pattern because it fuses OCR + layout + semantics in one pass. Google's Gemini "layout parser" exposes this as a service that identifies tables, figures, lists, headers and preserves hierarchy. ([Google Docs AI layout parse chunk](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk)) Dedicated OCR engines (Tesseract/PaddleOCR-class and cloud OCR) still win only where you need raw glyph-level text at the lowest per-1000-image cost with no semantic understanding; they do not grant context (differentiating "an IBAN vs a phone number") and cap around ~85% on complex layouts vs 95–99% for vision-first systems. ([vellum.ai](https://www.vellum.ai/blog/document-data-extraction-llms-vs-ocrs), [unsiloed.ai](https://www.unsiloed.ai/blog/document-data-extraction-software-technical-comparison))
- Front-runner 2026 models for this: **Gemini** (3.1 Flash-Lite / 3.5 Flash — cheap, long context, native vision+audio+video, 1M-token window); **OpenAI GPT-5/GPT-4o** (strong spatial understanding, ~95% handwriting accuracy); **Anthropic Claude** (agentic self-correction on extraction, good structured output). ([aimlapi.com](https://aimlapi.com/blog/best-llms-for-long-context-multimodal-tasks-in-2026), [aimagicx.com](https://www.aimagicx.com/blog/ai-vision-models-image-understanding-guide-2026), [anablock.com](https://anablock.com/blog/claude-pdf-processing-document-analysis))
- Specialized visual parsing: **OmniParser V2** (Microsoft, arXiv 2502.16161) is a unified framework for text-spotting, KIE, table recognition and layout analysis — an open, integrable option if you want to decouple OCR from the generation model. ([arXiv:2502.16161](https://arxiv.org/abs/2502.16161))

**Repo grounding:** `quick_analyze.py` already sends each carousel slide in sequence (inline images, `MAX_SLIDES=12`) to `gemini-3.1-flash-lite` and instructs the model to "Read URLs off the slides exactly as shown." This is the correct multimodal approach; the open questions are only about tiering cost (see §5).

---

## 2. Video: transcription + visual context

### Does Apify `instagram-scraper` provide transcripts?
**No — it does not provide speech transcripts.** Verified against the actual scraped `post_metadata.json` in this repo: the actor returns `caption`, `id`, `type`, `inputUrl`, `shortCode`, `hashtags`, `mentions`, `commentsCount`, `latestComments`, and media URLs (`videoUrl`/`displayUrl`/`childPosts[]`) — there is **no audio field and no transcript field**. It also is not documented to return one. **How to verify for your run:** inspect a post's `post_metadata.json` keys after a scrape; if a `transcript`/`captionAudioUrl` field ever appears it would be visible there. Today, transcription must be derived from the downloaded `.mp4` yourself.

### Transcripts must therefore be generated locally
The repo already does the right thing: it uploads the whole video file to the **Gemini Files API** and the model performs **native audio+video understanding** (speech transcription via the audio track, not separate OCR/ASR), interleaving bracketed scene notes into the transcript ("words [scene: ...] words"). This is a single-pass native-vision approach. Alternatives for speech-only: local **Whisper** (open-weight ASR, `whisper-large-v3` is a common 2026 fallback for low-resource languages) or Gemini-native ASR, both far cheaper than paying for a vision model per second when you only need the words. ([arXiv 2605.19075 CRAFT](https://arxiv.org/html/2605.19075v1) documents Whisper-large-v3 + Qwen3-ASR as the pragmatic 2026 ASR stack in video pipelines.)

### What "visual context" beyond transcript requires
A transcript captures only what was *said*. For IG reels/screen-share content, the value is often *on-screen*: tool names rendered in the UI, lists, URLs, diagrams, demo steps. Two complementary captures:
- **Key-frame extraction** — sample I-frames or N evenly-spaced frames (`num_frames`, `keyframes_only` for I-frames) as cheap proxies for the whole video, then run vision extraction/OCR over those frames. This is standard in 2026 video-intelligence pipelines. ([pixeltable.com](https://www.pixeltable.com/blog/video-intelligence-pipeline-tutorial), [arXiv 2605.16740 TRACE](https://arxiv.org/html/2605.16740v2))
- **On-screen text OCR over frames** — the TRACE approach extracts "structured grounding signals via object detection and OCR over video frames." ([arXiv:2605.16740](https://arxiv.org/html/2605.16740v2)) Combined with Gemini-native video ("263 tokens per second" of video — see §3) you can have the VLM read on-screen text + narration in one call.
- **Native-video VLMs** (Gemini video mode, video-capable MLLMs) encode sampled frames directly and can correlate speech + visuals + on-screen text with timestamps, which pure ASR cannot do. The known limitation is context-window pressure on long reels — hence key-frame pre-selection. ([arXiv:2603.22285 VideoDetective](https://arxiv.org/html/2603.22285v2), [arXiv:2606.02569 AdaCodec](https://arxiv.org/html/2606.02569v1))

**Recommendation for video:** use a native video-pass for the transcript + scene notes (Gemini), and additionally extract N key-frames for on-screen text/visual embedding. You do not need a separate OCR engine if you use Gemini native video; you may want one only if you switch to Whisper + frame-OCR to minimize vision-model spend.

---

## 3. Core question — extract-once vs embed vs both

### The three options, evaluated

**(a) Extract structured content ONCE with a multimodal model, store the text.**
- *Pros:* Cheapest per query (text-only embeddings ~$0.02/M tokens; retrieval is pure text RAG); one clean text index; reuses existing text RAG infra; output is directly usable by agents (resources, steps, tips). ([bigdataboutique.com](https://bigdataboutique.com/blog/multimodal-rag-retrieval-over-images-pdfs-and-text), [leanware.co](https://leanware.co/insights/multi-modal-rag-systems))
- *Cons:* Inherent **information loss** — spatial layout, visual patterns, exact diagram structure are discarded; retrieval quality is gated entirely by caption/extraction quality, and if the extractor "misses" a fact the retriever can *never* find it. VLM captions can also hallucinate details that then poison the index. ([nutrient.io](https://www.nutrient.io/blog/multimodal-rag/), [huggingface.co](https://huggingface.co/blog/Omartificial-Intelligence-Space/building-multimodal-rag-systems))
- *Re-processing:* A VLM or text-embedding upgrade requires re-captioning + re-embedding to benefit. ([bigdataboutique.com](https://bigdataboutique.com/blog/multimodal-rag-retrieval-over-images-pdfs-and-text))

**(b) Embed/vectorize the media directly (per-image / per-frame embeddings).**
- *Pros:* **Highest retrieval fidelity** for layout/visual content — direct image embeddings capture spatial/visual detail better than text, and cross-modal search (text query → image) works because models like CLIP / Gemini embedding place text+image in a shared space. ([agentset.ai](https://agentset.ai/blog/multimodal-vs-text-embeddings), [milvus.io](https://milvus.io/blog/choose-embedding-model-rag-2026.md))
- *Cons:* A modeled **"modality gap"** can make cross-modal similarity unreliable without re-ranking; a model upgrade means full re-indexing of the whole corpus; multimodal embeddings are more compute/GPU-intense. ([milvus.io](https://milvus.io/blog/choose-embedding-model-rag-2026.md), [bigdataboutique.com](https://bigdataboutique.com/blog/multimodal-rag-retrieval-over-images-pdfs-and-text))

**(c) Both (hybrid multimodal RAG).**
- The recommended 2026 pattern: **use extracted text for semantic retrieval AND pass the retrieved original image/frames to a multimodal LLM at generation time** — the LLM sees the actual pixels, not just the caption. This is "Hybrid / semi-structured multimodal RAG." Retrieval quality is still gated by caption quality, but the final answer is grounded in the real visual. ([langchain.com](https://www.langchain.com/blog/semi-structured-multi-modal-rag), [nvidia.com](https://developer.nvidia.com/blog/an-easy-introduction-to-multimodal-retrieval-augmented-generation/), [dataiku.com](https://www.dataiku.com/blog/multimodal-rag))

### Concrete cost math (primary sources)
Google's official token docs give the per-modality token rates: **image ≤384px = 258 tokens; larger images tiled into 768×768 tiles, 258 tokens/tile; video = 263 tokens/second; audio = 32 tokens/second.** ([Google Gemini API token docs](https://ai.google.dev/gemini-api/docs/tokens))

At **gemini-3.1-flash-lite pricing ≈ $0.25 / M input tokens, $1.50 / M output** ([nicolalazzari.ai](https://nicolalazzari.ai/articles/gemini-api-pricing-explained-2026), [anotherwrapper.com](https://anotherwrapper.com/tools/llm-pricing/gemini-3-flash-preview); repo currently uses `gemini-3.1-flash-lite` at these rates):

- **1080p carousel slide** (~1080×1080 → 2×2 tiles ≈ 4 tiles): ≈ 4 × 258 ≈ **1,032 input tokens ≈ $0.00026** per slide in input cost. A 10-slide carousel ≈ **$0.003 input** per post.
- **60s reel, native video pass**: 263 tok/s × 60 ≈ 15,780 input tokens ≈ **$0.0039** per video input.
- **48kHz audio, 60s**: 32 tok/s × 60 ≈ 1,920 tokens ≈ **$0.0005** per minute — i.e. native-Audio ASR is roughly **8× cheaper than native-video** for speech-only transcription (per [Google token docs](https://ai.google.dev/gemini-api/docs/tokens)).

Extraction output is a fixed JSON blob (small); the dominant cost is input. Net: **extract-once structured text is cheap** (~a fraction of a cent per post) — cheap enough that cost is not the reason to avoid it.

### Decision
For media where **visual/layout content is the primary value** (which the repo's own sample data confirms — listicles render in slides), **option (a) alone is insufficient** because it throws away layout and can't be re-queried for visual similarity. **Pure (b) alone is wasteful** because it can't turn a slide into agent-consumable structured facts (resources, steps, URLs). **The correct direction is (c) — both**, sequenced to control cost:
1. **Cheap text/lexical pre-filter** to decide which posts deserve the expensive vision pass (see §5).
2. **Extract structured text ONCE** per media unit (native multimodal). This is permanent structured knowledge.
3. **Additionally emit a per-slide / per-key-frame visual embedding** so the KB supports both text-semantic and image-similarity retrieval, and can pass the original image to a VLM at query time.

Re-processing story: because the raw media is retained and extraction is **versioned per schema** (the repo already archives `analysis_v<schema>_<timestamp>.json` and bumps `SCHEMA_VERSION`), a model improvement re-runs **extraction only, never re-scraping**. Embeddings re-index if you change the embedding model — isolate that cost by keeping embeddings on a small per-frame set.

---

## 4. Call-to-action / gated-content detection

This is the one-pager from the repo's own prompt and it is **reliably detectable as a structured field** — the primary signal is lexical + intent, which small models handle well, and it doesn't require heavy vision.

Repo grounding in `quick_analyze.py`: the extraction prompt already defines `gated_content: boolean` and `gated_trigger: string`, with the rule *"true if the real resource is withheld behind an engagement gate ('comment X and I'll DM you the link'); gated_trigger = the exact word/phrase, else ''."* Crucially, the repo's scraped `alt_text` examples confirm this is a real, repeated IG pattern worth capturing: *"Follow me and comment 'MONEY' to get this prompt"*, *"Comment 'VIBE' for the full workflow"*, *"Comment the word 'CLAUDE' and I'll DM you the template"*, *"Comment the exact keyword to get the full episode"*, *"DM link to get links"*. Each is a gated-resource hook.

**Key insight:** CTA/gating is mostly in **text** — the caption and the on-screen slide text — which your multimodal extraction already reads (the model reads URLs/words "off the slides exactly as shown"). It does **not** usually require separate video understanding. Detection approaches and reliability:
- **Lexical/heuristic base rate** is high because CTAs cluster on a small vocabulary ("comment X", "DM", "link in bio", "follow + comment", "keyword"). This is the same signal "Comment-to-DM," "DM keyword replies," and "follow-gate" automation vendors rely on as their core engagement trigger — confirming the pattern is well-defined and machine-addressable. ([replyrush.com](https://www.replyrush.com/post/best-instagram-auto-dm-tools), [vistasocial.com](https://vistasocial.com/insights/grow-followers-with-dm-automation/), [expertbeacon.com](https://expertbeacon.com/how-to-drive-traffic-from-instagram/))
- **As a structured tag/field:** yes — emit `gated_content: bool` + `gated_trigger: string` (the keyword/phrase) + `gated_target` (link-in-bio / DM / comment / story-sticker) in the per-post analysis. A cheap mini-LLM classifier or even regex-on-extracted-text covers ~95% given the vocabulary clustering; the VLM pass already populates it as a by-product (zero marginal cost).
- **Limits / open question:** the *actual gate payload* (the DM'd link, the template) is never visible in the post — only the trigger is. So the KB can reliably answer *"this post gates X behind keyword Y"* and surface the trigger for an agent to act on, but cannot resolve the gated resource itself without the account owner performing the DM.

**Recommendation:** keep `gated_content` + `gated_trigger` as a first-class structured field in the analysis schema; detect it in the same VLM pass (free) and optionally add a text-regex backstop for speed on the cheap pre-filter.

---

## 5. Recommended architecture direction (conceptual)

No implementation plan — what the media-ingestion pipeline should produce conceptually.

1. **Normalize media into stable, versioned units.** Every media item (single image, each carousel slide, each video) gets a stable id and keeps its **raw file** (already done: `data/ingest/<dataset>/<post_id>/media_NN.{jpg,mp4}`). Raw-file retention is what makes re-extraction cheap — never re-scrape.
2. **Two-tier extraction to control cost.**
   - *Tier 0 — cheap lexical pre-filter:* scan caption/`alt_text`/tags for obvious promos / non-educational / gated / listicle signals. Route the minority that looks knowledge-bearing to Tier 1; everything else gets a light path (caption-only, no vision).
   - *Tier 1 — structured once-extraction, native multimodal:* for each qualifying post, produce a **schema-versioned** JSON: `transcript` (video: speech + interleaved scene/on-screen-text notes; carousel: ordered `[slide N]` text), `resources[{name,url,type,purpose}]`, `workflow_steps[]`, `tips[]`, `concepts[]`, `tools_apps[]`, `tags[]`, `gated_content` + `gated_trigger` + `gated_target`, `is_educational`, `value_score`. This is a direct extension of the repo's current schema v2.
3. **Dual retrieval surfaces (both).** Store the extracted text (embedded with a text/multimodal embedding model) AND, for image/carousel-slide/frame media, a **low-cost per-slide/per-keyframe visual embedding** in the same vector index. Queries resolve by text-semantics, visual-similarity, or both; on hit, the original image/frame can be passed to a VLM for grounding. Refresh semantics: bump `SCHEMA_VERSION` to re-extract text; re-embed only if you change the embedding model.
4. **Version + archive.** Keep `schema_version`, `analysed_at`, and archive old payloads (repo already does via `data/archive/`). Enables clean re-extraction as models improve without touching source media.
5. **What the pipeline emits.** A normalized, later-stage-consumption artifact per post: raw media (retained) + structured analysis (versioned) + text embedding + visual embeddings + frame/keyframe pointers + CTA fields — plus metadata provenance (shortcode, URL, scraped_at). That is the substrate another component (REST API + CLI/Web, packaged as a tool/skill/plugin) can index and expose to coding agents.

---

## Key citations
- Image/video/audio token economics (258 tok/img, 263 tok/s video, 32 tok/s audio): [Google Gemini API — Understand and count tokens](https://ai.google.dev/gemini-api/docs/tokens)
- Gemini 3.1 Flash-Lite pricing ($0.25/$1.50 per M): [nicolalazzari.ai](https://nicolalazzari.ai/articles/gemini-api-pricing-explained-2026), [anotherwrapper.com](https://anotherwrapper.com/tools/llm-pricing/gemini-3-flash-preview)
- Multimodal/vision-first document extraction state of the art: [flexi.ink](https://flexi.ink/blog/business/ai-document-extraction-in-2026-techniques-accuracy-and-integration), [vellum.ai](https://www.vellum.ai/blog/document-data-extraction-llms-vs-ocrs), [matik.io](https://www.matik.io/blog/the-definitive-guide-to-automating-documents-in-2026)
- Layout-aware extraction: [extend.ai](https://www.extend.ai/resources/document-layout-analysis-page-structure), [Google Docs AI layout parse chunk](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk)
- OCR accuracy bounds: [recrew.ai](https://www.recrew.ai/blog/what-is-optical-character-recognition-ocr), [local-ai-zone.github.io](https://local-ai-zone.github.io/guides/best-ai-ocr-models-ultimate-ranking-2026.html)
- OmniParser V2: [arXiv:2502.16161](https://arxiv.org/abs/2502.16161)
- Hybrid/multimodal RAG (both): [nvidia.com](https://developer.nvidia.com/blog/an-easy-introduction-to-multimodal-retrieval-augmented-generation/), [langchain.com](https://www.langchain.com/blog/semi-structured-multi-modal-rag), [nutrient.io](https://www.nutrient.io/blog/multimodal-rag/), [huggingface.co](https://huggingface.co/blog/Omartificial-Intelligence-Space/building-multimodal-rag-systems), [bigdataboutique.com](https://bigdataboutique.com/blog/multimodal-rag-retrieval-over-images-pdfs-and-text), [dataiku.com](https://www.dataiku.com/blog/multimodal-rag)
- Video key-frames / on-screen OCR / ASR: [pixeltable.com](https://www.pixeltable.com/blog/video-intelligence-pipeline-tutorial), [arXiv:2605.16740 TRACE](https://arxiv.org/html/2605.16740v2), [arXiv:2605.19075 CRAFT (Whisper-large-v3/Qwen3-ASR)](https://arxiv.org/html/2605.19075v1)
- CTA/engagement-gate patterns: [replyrush.com](https://www.replyrush.com/post/best-instagram-auto-dm-tools), [vistasocial.com](https://vistasocial.com/insights/grow-followers-with-dm-automation/)
- **Repo grounding (primary, not web):** `quick_analyze.py` schema v2 (`gemini-3.1-flash-lite`, `gated_content`/`gated_trigger`/`transcript` fields, carousel-in-sequence, native video upload); `download_media.py` media targets (`childPosts` `videoUrl`/`displayUrl`/`images`); scraped `data/ingest/.../post_metadata.json` confirming Apify actor returns `caption`/media URLs/**no transcript** field.
