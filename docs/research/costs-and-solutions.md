# Research Memo — Agent-Queryable Knowledge Base from Social Media + Articles + Tabular Data (POC)

**Date:** 2026-08-31 · **Purpose:** Existing tools/platforms with strong overlap + typical 2026 costs for a POC combining structured + unstructured + media-derived data, exposed to coding agents (Claude Code, oh-my-pi, Cursor) via REST API + CLI/Web packaged as a tool/skill/plugin. Research only — no implementation.

---

## 1. Existing tools/platforms with strong (not 100%) overlap

### 1a. RAG frameworks

| Tool | Fit for this POC |
|---|---|
| **LlamaIndex** | Best structural fit. Ingestion/indexing-first: document + table + metadata-native (indexes for text, `VectorStoreIndex`, `SQLTableNodeMapping`/tabular via `NLSQLTableQueryEngine`, `PropertyGraphIndex`). Built for "data-heavy retrieval systems." Most aligned for combining structured + unstructured retrieval. Sources: [LangChain vs LlamaIndex 2026 production RAG comparison — premai.io](https://www.premai.io/blog/langchain-vs-llamaindex-2026-complete-production-rag-comparison/); [decision guide — myengineeringpath.dev, Mar 2026](https://myengineeringpath.dev/tools/langchain-vs-llamaindex/) ("LlamaIndex for RAG-first… 80% of production teams adopt a hybrid"). |
| **LangChain / LangGraph** | Better for agent orchestration (multi-step tool calling, chain composition) than for retrieval quality. Use if the KB's query side becomes agent-heavy. Sources: [ortemtech.com, 2026](https://ortemtech.com/blog/langchain-vs-llamaindex-vs-custom-rag-comparison-2026/); [kunalganglani.com, 2026](https://www.kunalganglani.com/blog/langchain-vs-llamaindex-2026). |

**Takeaway:** LlamaIndex is the right framework if you build rather than buy; LangGraph complements if the query path needs agentic orchestration.

### 1b. Vector databases

| DB | Managed (cloud) | Self-host | Notes for this POC |
|---|---|---|---|
| **Pinecone** | Yes (Serverless) | No | $0.33/GB/mo storage, **$50/mo Standard-plan minimum** (below-usage still billed $50). Capacity fees $50–150/mo under agent load. Free tier: 2GB + 1M RUs (~300k vectors). Source: [pinecone.io/docs understand-cost](https://docs.pinecone.io/guides/manage-cost/understanding-cost); [pinecone.io/pricing](https://www.pinecone.io/pricing/); [ranksquire Apr 2026](https://ranksquire.com/2026/04/02/pinecone-pricing-2026/). |
| **Qdrant** | Yes (Cloud) | Yes (OSS) | ~$0.12/GB storage; ~$80–120/mo for a 4GB cluster; free single-node cluster (0.5 vCPU/1GB RAM/4GB disk ≈ 1M 768-dim vectors). Source: [qdrant.tech/pricing](https://qdrant.tech/pricing/); [ranksquire Qdrant, Apr 2026](https://ranksquire.com/2026/04/19/qdrant-cloud-pricing-2026/). |
| **Weaviate** | Yes | Yes | Open source + managed; hybrid search (vector + BM25/rerank) built in — useful for mixed text/media. (Survey signal; see §4 of [premai.io comparison](https://www.premai.io/blog/langchain-vs-llamaindex-2026-complete-production-rag-comparison/).) |
| **pgvector** | Via RDS/GCP/DO | Yes | **Best cost if you already run Postgres.** Storage only ~$0.115/GB/mo (AWS RDS gp3); but compute dominates — a 32GB-RAM instance (`db.r8g.xlarge`) ≈ **$398/mo** is cited as min for 1M vectors; ~**near-zero marginal cost** on an existing Postgres box. Sources: [dev.to pgvector vs pinecone](https://dev.to/polliog/postgresql-as-a-vector-database-when-to-use-pgvector-vs-pinecone-vs-weaviate-4kfi); [usage.ai RDS extensions cost](https://www.usage.ai/blogs/aws/reserved-instances/rds/postgresql/extensions-cost/); [supabase pgvector-vs-pinecone](https://supabase.com/blog/pgvector-vs-pinecone). |
| **LanceDB** | Yes (cloud) | Yes | Embedded/lance-native, zero-ops, Parquet-backed — fits a medallion-lake codebase well (Parquet-native). Source: [awesome-rag-production decision tree](https://github.com/Yigtwxx/awesome-rag-production). |
| **Milvus/Zilliz** | Yes | Yes | High-scale option; overkill for POC volumes (809 posts). |

### 1c. Self-hosted knowledge-base apps

| App | What it is | Fit |
|---|---|---|
| **anythingLLM** | Zero-config desktop/app RAG + built-in agents (web search, SQL). Simple document Q&A, multi-user workspaces, swappable model/embedding backends. | Good if you want a **UI + RAG fast**, but it's chat-app-oriented — wiring a programmatic REST/MCP surface for coding agents is not its model. Sources: [localaimaster.com](https://localaimaster.com/blog/anythingllm-vs-open-webui); [areebi.com compare](https://www.areebi.com/compare/anythingllm-vs-open-webui). |
| **Open WebUI** | Most customizable/self-hosted chat; pipelines, multi-provider, MCP support, team collaboration. | Strongest **extensible UI + MCP out-of-box** of the three; still UI-first, retrieval is bolted on. Sources: [docs.openwebui.com/alternatives](https://docs.openwebui.com/alternatives/anythingllm/); [aicoolies](https://aicoolies.com/comparisons/anythingllm-vs-open-webui). |
| **Onyx (formerly Danswer)** | Enterprise search/RAG platform unifying workplace knowledge across SaaS connectors (Slack, Drive, Confluence, GitHub…). | If your KB's value is *connectors*, this wins; but connectors ≠ your bespoke media-extraction pipeline. Source: [docs.openwebui.com/alternatives/onyx/](https://docs.openwebui.com/alternatives/onyx/); [aicoolies Onyx-vs-OpenWebUI](https://aicoolies.com/comparisons/onyx-vs-open-webui). |

### 1d. Agent KB / retrieval products (coding-agent target)

- **kapa.ai** — AI docs/answer product with **MCP server support** for docs/forum content; enterprise-connector oriented. Source: [kapa.ai best-AI-docs-tools 2026](https://www.kapa.ai/blog/best-ai-documentation-tools-for-2026).
- **Context7** — **MCP server** giving coding agents up-to-date library/docs context at query time; the pattern closest to "package a KB as a tool skill/plugin" for Claude Code/Cursor. Source: [kapa.ai blog (Context7 MCP)](https://www.kapa.ai/blog/best-ai-documentation-tools-for-2026).
- **Agent memory/retrieval**: Mem0 (ECAI 2025 benchmark paper), Letta (memory-in-framework), Zep/Graphiti (graph memory). Relevant as *query-context* layers, less as document KBs. Sources: [mem0.ai State-of-Agent-Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026); [supermemory.ai best-memory-APIs](https://supermemory.ai/blog/best-memory-apis-stateful-ai-agents/); [atlan.com agent-context-layer tools](https://atlan.com/know/ai-agent/agent-context-layer-tools-compared/).
- **Vercel AI SDK "knowledge"** — in-SDK RAG/data-source abstraction for agent apps; good if exposing to AI SDK-based clients. [INFERENCE — feature exists in current AI SDK; primary docs URL 404'd on read].

### 1e. Text-to-SQL / tabular query

- **Vanna.ai** — open-source (22k+ GitHub stars), "chat with your SQL database," SQL-generating RAG over arbitrary DBs. Most polished OSS option. Sources: [github.com/vanna-ai/vanna](https://github.com/vanna-ai/vanna); [getdot.ai Vanna-alternatives 2026](https://www.getdot.ai/blog/vanna-ai-alternatives).
- **Wren AI** — open-source governed text-to-SQL, native Python + MDL semantic layer. Source: [getwren.ai Wren-vs-Vanna](https://www.getwren.ai/post/wren-ai-vs-vanna-the-enterprise-guide-to-choosing-a-text-to-sql-solution).
- **Dataherald / TxtSQL / SQLChat** — smaller OSS projects; superseded in practice by framework-native `NLSQLTableQueryEngine` (LlamaIndex) or `SQLDatabase` (LangChain). Source: [github.com/topics/text-to-sql](https://github.com/topics/text-to-sql); [bytebase.com top text-to-sql tools 2026](https://www.bytebase.com/blog/top-text-to-sql-query-tools/).
- **DB MCP servers** (e.g. DBHub, Postgres/MySQL MCP) — route structured queries straight to agents; relevant for the REST/agent exposure. Source: [bytebase.com, 2026](https://www.bytebase.com/blog/top-text-to-sql-query-tools/).

### 1f. Graph databases

- **Neo4j** — leader; AuraDB free tier $0, **Professional from ~$65/mo**; self-hosted Community (GPLv3) free, Enterprise commercial license. Great for *entity-relationship* queries across creators/posts/topics, but adds ops + cost for a POC. Sources: [anyinstructor.com (free $0, professional ~$65/mo)](https://anyinstructor.com/best-nosql-databases/); [gurukulgalaxy.com 2026](https://gurukulgalaxy.com/blog/top-10-knowledge-graph-construction-tools-features-pros-cons-comparison/).

### 1g. Most-aligned recommendation for the POC

**LlamaIndex (build the extraction/index layer) + pgvector on existing Postgres (store) + MCP/REST facade (expose)**. Rationale: (1) no off-the-shelf platform handles your *bespoke media path* (carousel image→text, video transcription + visual-aid extraction); (2) you already run DuckDB/Postgres + Parquet in the datalake, so pgvector is near-free; (3) the "package for coding agents" requirement points to a thin MCP server (Context7-style), not a chat app. LlamaIndex over LangChain because retrieval quality + ingestion matter more than agent orchestration here.

---

## 2. Costs (2026, USD)

> All figures are as-of dates noted inline. Batch API (OpenAI & Gemini) = **50% discount** — use for one-time backfill extraction.

### 2a. Multimodal LLM extraction (per 1K tokens; image/video effective per-minute)

| Model | Input price | Notes / effective media rates |
|---|---|---|
| **Gemini 3.7 / 3.6 Flash** | $0.75 / 1M input tokens (intro, through 2026-12-31; **$1.50 after 2027-01-01**) | Cheapest frontier-class multimodal. **Audio = 25 tokens/sec**; **effective ~$0.002/min for image/video input** (Flash). Output incl. thinking $3.75/1M (through 2026). Source: [ai.google.dev Gemini API pricing (official, live)](https://ai.google.dev/gemini-api/docs/pricing). |
| **Gemini 3.5 Flash** | $1.50 / 1M | Output $9.00/1M. Source: [official pricing](https://ai.google.dev/gemini-api/docs/pricing). |
| **Gemini 3.5 Flash-Lite** | $0.30 / 1M input (text/image/video/audio) | Cheapest tier; output $2.50/1M. Batch $0.15/1M. Source: [official pricing](https://ai.google.dev/gemini-api/docs/pricing). |
| **Gemini 3 Flash Preview** | $0.50/1M (t/v/a) | Source: [official pricing](https://ai.google.dev/gemini-api/docs/pricing). |
| **GPT-4o (legacy)** | $2.50 / 1M in, $10.00 / 1M out | Batch in $1.25/1M. Source: [aifreeapi.com gpt-4o](https://www.aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens); [openrouter.ai gpt-4o](https://openrouter.ai/openai/gpt-4o). |
| **GPT-4o-mini** | $0.15 / 1M in, $0.60 / 1M out | Budget vision. Source: [pecollective.com](https://pecollective.com/tools/gpt-4o-pricing/). |

**Per-1K-posts estimate (image carousels, Gemini Flash Batch @$0.375/1M in):** assume ~500–1,500 input tokens/image + ~300–600 output tokens for structured extraction. At ~$0.375/1M in + $1.875/1M out → roughly **$1–5 per 1,000 images**, or **$5–25 per 1,000 posts** (carousels of 1–5 images + caption text). This is the single largest, but still tiny, cost driver. Video: a 60s clip ≈ 25 tokens/s × 60 = ~1,500 audio tokens + sampled frames; effectively a few cents per short clip on Flash.

### 2b. Embeddings (per 1K tokens) — as of Aug 2026

| Model | Text | Image | Source |
|---|---|---|---|
| **OpenAI text-embedding-3-large** | $0.13 /1K (batch $0.065) | — | [cloudzero.com OpenAI pricing, Aug 2026](https://www.cloudzero.com/blog/openai-pricing/) |
| **Gemini Embedding v001** | $0.15 /1K | — | [developers.googleblog.com](https://developers.googleblog.com/gemini-embedding-available-gemini-api/) |
| **Gemini Embedding 2** (multimodal) | $0.20 /1K | $0.45 /1K | [openrouter.ai gemini-embedding-2](https://openrouter.ai/google/gemini-embedding-2); [metacto.com](https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration) |
| **Cohere embed v4** | $0.12 /1K | $0.47 /1K | [embeddingcost.com/cohere](https://embeddingcost.com/cohere); [azure pricing](https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/cohere/) |

**Per-1K-posts:** 1–5 images + caption ≈ 1–4K tokens → **$1.30–5 (OpenAI)** or **$1.20–5 (Cohere text)**, plus image-side if using a multimodal embedder (~$0.47/1K image tokens ≈ a few cents/image). Embeddings are a rounding error vs. extraction.

### 2c. Transcription (Whisper local vs API) — per minute

| Provider / model | $/min | $/hr | Source |
|---|---|---|---|
| OpenAI **whisper-1** API | $0.006 | $0.36 | [brasstranscripts.com](https://brasstranscripts.com/blog/openai-whisper-api-pricing-2025-self-hosted-vs-managed); [costgoat.com](https://costgoat.com/pricing/openai-transcription) |
| OpenAI **gpt-4o-mini-transcribe** | ~$0.003 | $0.18 | [diyai.io](https://diyai.io/ai-tools/speech-to-text/openai-whisper-api-pricing-2026/) |
| **Deepgram Nova-3** (batch) | ~$0.0043 | $0.26 | [convertaudiototext.com](https://convertaudiototext.com/blog/deepgram-nova-3-explained) |
| **AssemblyAI Universal-2** (async) | $0.0025 | $0.15 | [assemblyai.com/pricing](https://www.assemblyai.com/pricing) |
| **AssemblyAI Universal-3.5 Pro** (async) | $0.0035 | $0.21 | [assemblyai.com blog](https://www.assemblyai.com/blog/speech-to-text-api-pricing) |
| **Self-hosted local Whisper (e.g. faster-whisper)** | ~$0 | ~$0 but GPU/compute cost | [brasstranscripts.com (self-hosted vs managed)](https://brasstranscripts.com/blog/openai-whisper-api-pricing-2025-self-hosted-vs-managed) |

Your 809 posts with short IG videos: transcription is trivial cost (API ≈ a few dollars total, or free locally on the i5 CPU for short clips).

### 2d. OCR

| Option | Cost | Source |
|---|---|---|
| **Google Cloud Vision** OCR (TEXT_DETECTION) | **$1.50 / 1,000 units** (verified Aug 2026); 1,000 free units/mo | [google.cloud/vision/pricing](https://cloud.google.com/vision/pricing); [receiptocr.ai Aug 2026](https://receiptocr.ai/blog/google-cloud-vision-api-pricing) |
| **Tesseract** (local, gratis) | $0 (CPU-only; lower accuracy on stylized/carousel text) | [apiscout.dev best-OCR-APIs-2026](https://apiscout.dev/guides/best-ocr-api-2026) |
| **AWS Textract / Azure Document Intelligence** | comparable per-page; ~$1.50/1K pages class | [imagetotable.ai OCR comparison](https://imagetotable.ai/blog/google-vs-aws-vs-azure-ocr-2026) |

**Note:** for caption-overlaid carousel *listicles*, a multimodal LLM (Gemini Flash / GPT-4o-mini) usually beats OCR + layout reconstruction for structured field extraction — OCR is a fallback, near-zero cost for this volume.

### 2e. Vector DB hosting (see §1b links)

| Option | Storage $/GB/mo | Compute/ops | Effective monthly at POC scale (809 posts) |
|---|---|---|---|
| Pinecone Serverless | ~$0.33 | RU/WU + **$50/mo min on Standard** | **$50/mo floor** (overkill) |
| Qdrant Cloud | ~$0.12 | ~$80–120 for 4GB cluster | ~$30–120/mo (can downsize) |
| **pgvector on existing Postgres** | ~$0.115 (RDS gp3) / ~$0 (existing box) | near-zero if capacity exists | **~$0 marginal** |
| RDS heavy (new 32GB instance) | $0.115 | ~$398/mo | not needed at 809 posts |

### 2f. Media object storage (per GB/mo)

| Provider | $/GB/mo | Source |
|---|---|---|
| **S3 Standard** | ~$0.023 (first 50TB) | [runcloud.io S3-vs-R2](https://runcloud.io/blog/cloudflare-r2-vs-aws-s3); [themedev.net](https://themedev.net/blog/cloudflare-r2-vs-aws-s3/) |
| **Cloudflare R2** | $0.015 + **no egress fee** | [r2-calculator.cloudflare.com](https://r2-calculator.cloudflare.com/); [runcloud.io](https://runcloud.io/blog/cloudflare-r2-vs-aws-s3) |
| **Backblaze B2** | $6.95/TB ($0.0068/GB) | [cloudzat.com object-storage 2026](https://cloudzat.com/object-storage/) |
| **Wasabi** | $7.99/TB ($0.0078/GB) | [cloudzat.com](https://cloudzat.com/object-storage/) |

R2's free egress is the clear winner for a KB where media bytes get pulled by agents frequently.

### 2g. Total cost envelope for the POC (one-time backfill of 809 posts + 557 creators)

- Extraction (multimodal): **~$5–30** (batch Gemini Flash/Flash-Lite)
- Embeddings: **~$1–5**
- Transcription: **~$0–10** (or free locally)
- OCR (optional): ~$0–2
- Vector storage: **~$0–50/mo** (pgvector ≈ $0; Qdrant Cloud ~$30+)
- Media storage: **~$1–10/mo** (R2 at ~800GB worst case ≈ $12; realistically a few dollars)
- **Compute/API total ≈ under $100 one-time, < $50/mo recurring** for the POC.

---

## 3. Build vs buy

### Build (DIY pipeline: own extraction + indexing + REST/MCP facade)
- **+ Lower marginal cost** — near-free if leveraging existing datalake Postgres/DuckDB (pgvector marginal ~$0; see [embeddingcost.com/storage](https://embeddingcost.com/storage)).
- **+ Only way to handle the bespoke media path.** No off-the-shelf platform extracts carousel-listicle text or video visual-aids from your IG corpus out-of-box.
- **+ Full control over schema, refresh, model versioning, and the agent-facing API/MCP surface.**
- **− Engineering time** (you already have extraction + datalake machinery from `quick_analyze.py` / medallion lake, so marginal effort is indexing + API only).

### Buy (off-the-shelf RAG/KB platform)
- **+ Less code** for standard doc Q&A.
- **− Feature mismatch:** anythingLLM/Open WebUI/Onyx are chat-apps with *retrieval bolted on*; Pinecone adds a $50/mo floor at POC scale; none ingest your media-derived ontology.
- **− Black-box model/embedding versioning and refresh semantics.**
- **− Vendor lock-in + data-egress concerns** for a KB you intend to repackage as a skill/plugin.

### Verdict
Given the existing assets (Apify actor, medallion datalake, Gemini pipeline), **build-on-thin-layer wins**: use LlamaIndex (orchestrate ingestion/retrieval) + pgvector (on existing Postgres) + Cloudflare R2 (bytes) + a ~100-line MCP/REST facade. Adopting a turnkey RAG/KB platform adds cost and removes flexibility without covering the hard part (media-derived extraction). A middle path: keep DIY *ingestion*, but expose *query* via an MCP server so any agent (Claude Code/Cursor/oh-my-pi) consumes it — this is the Context7 model ([kapa.ai](https://www.kapa.ai/blog/best-ai-documentation-tools-for-2026)).

---

## 4. Operational concerns

### 4a. Media storage
- Object store for original bytes (video + carousel images) separate from derived text/embeddings. Use **Cloudflare R2** ($0.015/GB, **free egress**) for agent-driven retrieval; keep a Parquet/medallion bronze copy in the datalake. Sources above (§2f).
- Consider **transcoding/thumbnail tier** for carousel images to cap multimodal token sizes (fewer image tokens → lower extraction cost).

### 4b. Cache / refresh of derived data
- Store derived artifacts as **versioned blobs with a `model_version` + `extracted_at`** (mirrors your existing SCD2 `creators`/`profiles` pattern — do the same for posts).
- Only re-run extraction when: a post is *new*, media bytes change, or you *bump the model version*. Idempotent per-`item_key` cache keyed on `(item_hash, model_version)`.
- **Batch API (50% off)** for all backfill/re-refresh waves ([official OpenAI](https://www.aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens); [official Gemini](https://ai.google.dev/gemini-api/docs/pricing)).

### 4c. Model versioning for re-extraction
- LLM extraction is non-deterministic and model-version-sensitive: pin the model + a prompt hash; tag every `analysis`/embedding row with `(model, prompt_version)` — your existing `analysis.json` per post can gain these fields.
- **Embedding re-indexing is the hidden cost:** upgrading the embedder requires re-embedding the whole corpus and rebuilding the vector index. Budget for it by keeping embeddings regenerable from cached raw text (not chained off earlier embedding outputs).
- Gemini 3.x Flash intro pricing **doubles 2027-01-01** — time backfill batches accordingly ([official pricing](https://ai.google.dev/gemini-api/docs/pricing)).

---

## Key sources (primary preferred)
1. Gemini API pricing (official, live 2026): https://ai.google.dev/gemini-api/docs/pricing
2. OpenAI GPT-4o / whisper / embeddings pricing: https://www.aifreeapi.com/en/posts/gpt-4o-pricing-per-million-tokens · https://cloudzero.com/blog/openai-pricing/ · https://www.pecollective.com/tools/openai-api-pricing/
3. Transcription: https://www.assemblyai.com/blog/speech-to-text-api-pricing · https://deepgram.com/learn/deepgram-vs-openai-vs-stt-accuracy-latency-price-compared
4. OCR: https://cloud.google.com/vision/pricing · https://receiptocr.ai/blog/google-cloud-vision-api-pricing (Aug 2026)
5. Vector DB: https://docs.pinecone.io/guides/manage-cost/understanding-cost · https://qdrant.tech/pricing/ · https://www.usage.ai/blogs/aws/reserved-instances/rds/postgresql/extensions-cost/
6. RAG framework choice: https://www.premai.io/blog/langchain-vs-llamaindex-2026-complete-production-rag-comparison/
7. Self-hosted KB: https://docs.openwebui.com/alternatives/ · https://www.aicoolies.com/comparisons/
8. Text-to-SQL: https://github.com/vanna-ai/vanna · https://www.getwren.ai/post/wren-ai-vs-vanna-the-enterprise-guide-to-choosing-a-text-to-sql-solution
9. Agent-context/memory: https://mem0.ai/blog/state-of-ai-agent-memory-2026 · https://atlan.com/know/ai-agent/agent-context-layer-tools-compared/ · https://www.kapa.ai/blog/best-ai-documentation-tools-for-2026
10. Object storage: https://runcloud.io/blog/cloudflare-r2-vs-aws-s3 · https://cloudzat.com/object-storage/ · https://r2-calculator.cloudflare.com/
