# Research Memo — Agent-Queryable Knowledge Base (State of the Art, 2026)

**Date:** 2026-08-31 · **Scope:** Research only; POC for a KB built from social/IG-media, articles, docs, and tabular data, exposed to coding agents (Claude Code, oh-my-pi, Cursor) via REST + CLI/Web.
**Maturity legend:** 🟢 Mature/production-ready · 🟡 Maturing (early production) · 🔴 Experimental/research.

---

## 1. Is vector RAG still the best way to search unstructured data in 2026?

**Short answer: No — plain vector RAG is a baseline, not the answer. Hybrid (BM25+dense) is the 2026 production default; graph augmentation earns its cost only for multi-hop relational questions.**

### 1.1 Why naive/vector-only RAG is now a liability
Pure vector search is repeatedly described in 2026 sources as "naive RAG" that is "outdated" and a "liability" for production. Failure modes: weak exact-term/identifier matching (schema names, product codes, handles), context poisoning from semantically-near-but-irrelevant chunks, and inability to handle relational/"entire-dataset-shape" questions. Sources:
- Denser.ai "Hybrid Search for RAG" (precision/recall and context-poisoning limits): https://denser.ai/blog/hybrid-search-for-rag/
- Medium/Data Science Collective "Modern RAG in 2026" (naive RAG = liability): https://medium.com/data-science-collective/modern-rag-in-2026-the-components-that-actually-matter-3f6a138ef117
- Substack "All you need to know about RAG in 2026": https://aishwaryasrinivasan.substack.com/p/all-you-need-to-know-about-rag-in

### 1.2 Hybrid search (BM25/lexical + dense vector + RRF) — 🟢 THE production default
Combining sparse keyword retrieval (BM25/TF-IDF) with dense embeddings, fused via Reciprocal Rank Fusion (RRF). Consistently beats either alone on NDCG/Recall; critical where exact terms matter (saved-post tags, creator handles, URLs, domains). Called "the single highest-impact retrieval upgrade" and "production default" in 2026. Latency penalty ~80–200 ms, RRF sub-ms. Corroborated sources (2+):
- Denser.ai: https://denser.ai/blog/hybrid-search-for-rag/
- essamamdani.com 2026 GraphRAG/hybrid guide: https://essamamdani.com/blog/complete-guide-graphrag-hybrid-search-2026
- NoSQLBench: https://redis.io/blog/hybrid-search-benefits-rag-systems/
- Meilisearch: https://www.meilisearch.com/blog/hybrid-search-rag

Rerankers (cross-encoders) are the widely recommended post-retrieval addition — part of the 2026 "modern RAG components" stack (Medium 2026; Substack 2026, above).

### 1.3 Hybrid GraphRAG / knowledge graphs — 🟡 to 🔴 (use selectively)
Graph extraction + community summarization + local/global search. Strong for multi-hop/"implications across the whole dataset," reduced hallucination via structured grounding. Historically expensive to index; Microsoft's **LazyGraphRAG** (2025, arXiv 2504.06085 — "Setting a new standard... cost") defers LLM summarization to query time, bringing indexing near vector-RAG parity. Caveat: research shows GraphRAG can *underperform* vanilla RAG on single-hop QA (a 13.4% drop on Natural Questions reported in arXiv 2602.03578), so graph value is query-type-dependent — do not apply it globally.
Sources:
- TigerGraph "Advanced RAG techniques (naive → hybrid → graphRAG)": https://www.tigergraph.com/blog/advanced-rag-techniques-naive-to-hybrid-graphrag/
- cruxdigits.nl "RAG vs GraphRAG 2026": https://cruxdigits.nl/blog/rag-vs-graphrag-2026/
- LazyGraphRAG paper: https://arxiv.org/abs/2504.06085 (verify ID; associated with Microsoft GraphRAG lineage)
- GraphRAG-underperforms-vanilla on single-hop (arXiv 2602.03578): https://arxiv.org/html/2602.03578v1

### 1.4 Agentic / iterative RAG — 🟡 (maturing)
Autonomous agent plans multiple retrieval steps, decides sources/tools, re-retrieves, evaluates. Emerging but real in 2026; covered across:
- n8n "Agentic RAG: Guide to Autonomous AI Systems" (Retriever Router): https://blog.n8n.io/agentic-rag/
- Substack RAG-2026: https://aishwaryasrinivasan.substack.com/p/all-you-need-to-know-about-rag-in
- TuringPost "RAG types": https://www.turingpost.com/p/ragtypes

### 1.5 SQL-over-unstructured (structured RAG / SQL-augmented retrieval) — 🟡
A 2026 trend: rather than straight vector similarity, build a relational view of document/text and issue precise SQL (exact values, joins, filters). Advantages claimed: schema awareness + deterministic, verifiable values → fewer hallucinations. See SQuARE (section 3) and the "structured RAG / SQL-augmented RAG" line it cites with 2+ corroborating sources (Meibel STAG: https://www.meibel.ai/post/structure-augmented-generation-bridging-structured-and-unstructured-data-for-enhanced-rag-systems).

### 1.6 DSPy-style pipelines (programmatic LLM pipelines + optimizers) — 🟡
DSPy is a Python framework to "program, don't prompt": structured signatures, interchangeable modules, and **GEPA optimizers** that auto-tune prompts. Production adoption cited by the project (Databricks, Shopify, Dropbox); 6.6M+ monthly downloads, 452+ contributors, 38k GitHub stars. Real but primarily a developer framework/tool, not a turnkey KB. Sources:
- DSPy official site (stats + optimizer GEPA): https://dspy.ai/
- DSPy GitHub: https://github.com/stanfordnlp/dspy
- Framework comparison (AutoGen RAG vs DSPy vs Semantic Kernel, 2026): https://www.index.dev/skill-vs-skill/ai-semantic-kernel-vs-autogen-vs-dspy

### 1.7 Semantic caching — 🟢 (mature, orthogonal)
Reusing prior LLM/retrieval outputs for semantically similar queries is a recognized cost/latency optimization (provider-side prompt-prefix caching and query-side semantic caching). Production-mature, and relevant to a KB exposed to many agents (dedupe repeated lookups). Sources:
- SuredPrompts glossary (context caching): https://sureprompts.com/glossary
- Hyscaler "Context Engineering": https://hyscaler.com/insights/context-engineering-complete-guide/

**Bottom line §1:** Use **hybrid search (BM25+dense, RRF, with a cross-encoder reranker)** as the retrieval core for the media/article transcript tier. Add graph augmentation *only* where multi-hop relational questions dominate. Treat SQL-over-structured and agentic layers as complementary, not replacements.

---

## 2. Text-to-SQL maturity — is it a viable primary interface for a structured KB layer in 2026?

**Short answer: Yes for small/clean schemas (the POC's DuckDB/SQLite tier), with a hard caveat: performance "cliffs" to near-zero on complex real-world schemas. It is viable ONLY behind a curated schema / semantic layer + rigid guardrails.** So the user's "LLMs are very good at text-to-sql" is true for clean relational data and dangerously false for complex ones.

### 2.1 Maturity evidence (2+ sources)
- Top models hit 85–92% execution accuracy on academic benchmarks (Spider 1.0), but this collapses to ~6–21% (occasionally near 0%) on real enterprise schemas; a proper **semantic layer + rich metadata** restores ~86–95%. ("The text-to-SQL performance cliff," Medium 2026: https://medium.com/@visrow/the-text-to-sql-performance-cliff-2026-why-natural-language-to-sql-breaks-a7281a23dbea ; Omni: https://omni.co/blog/why-text-to-sql-fails ; BlazeSQL: https://www.blazesql.com/blog/natural-language-to-sql)
- 45% of companies report focusing on deploying/scaling GenAI text-to-SQL (K2View: https://www.k2view.com/blog/llm-text-to-sql/)

### 2.2 Failure modes (corroborated across multiple sources)
- **Schema hallucination / misinterpretation** (non-existent tables/columns; wrong joins): https://www.omni.co/blog/why-text-to-sql-fails ; https://www.selectstar.com/resources/text-to-sql-llm
- **Incorrect joins / logic errors** → duplicated or miscalculated rows: https://medium.com/@puppygraph ... PuppyGraph: https://www.puppygraph.com/blog/text-to-sql-llm
- **Missing filters** (over-broad results): PuppyGraph (above)
- **Ambiguous/domain terms** ("revenue," "active user") misinterpreted without a semantic layer: Omni (above); SelectStar (above)
- **Non-determinism** (same question → different SQL/answers, "metric drift"): Omni (above)
- **Inefficient SQL** (slow/expensive) & **security** (generated DELETE/DROP/UPDATE, PII exposure): K2View (above); https://medium.com/@gregory.horne/i-built-a-natural-language-sql-agent-with-3-layers-of-safety-guardrails-here%27s-why-each-one-df166ba6f04d
- **Silent failures** — SQL executes and returns plausible-but-wrong data (the most dangerous for agent use): Omni (above); BlazeSQL (above)
- **NULL semantics / date-range / clock-awareness** issues: https://tianpan.co/blog/2026-04-10-text-to-sql-failure-modes-production

### 2.3 Guardrails (what makes it safe to expose to agents) — this is the key engineering point
- **Curated read-only views / semantic layer** instead of raw tables (deterministic metrics; de-risks joins): https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026 ; SelectStar (above)
- **RAG over the schema/metadata** to ground the generator: Red Hat "Evolution of agentic AI and text-to-SQL": https://developers.redhat.com/articles/2026/06/16/evolution-agentic-ai-and-text-sql ; https://ezinsights.ai/how-to-build-text-to-sql-agent-rag-llms-sql-guards/
- **SQL Guards** (block DELETE/DROP/UPDATE/INSERT/TRUNCATE/ALTER; fix structure): ezinsights (above); Gregory Horne (above)
- **Read-only scoped credentials + statement timeouts**: tianpan.co (above)
- **Pre/post-execution validation** (run against a copy; second-LLM or rule check answers the original question; reject empty/implausible results): K2View (above); SelectStar (above); and the SQuARE "quality gate + abstain" pattern below
- **Fine-tuning** for stable schemas: SelectStar (above)

**Bottom line §2:** Text-to-SQL is **viable as the primary interface for the POC's structured tier** (DuckDB/SQLite lake), precisely because those schemas are small, clean, and deterministic — the case where text-to-SQL stays strong (85–95%+). Do NOT expose raw tables; expose curated views, lock to SELECT-only on a read-only replica, apply SQL guards, and add post-execution result validation. For media/text/transcripts, text-to-SQL is the wrong tool — that's hybrid retrieval's job (this is exactly the heterogeneous case in §3).

---

## 3. Federated / hybrid search across heterogeneous data: how does an agent decide which store to query?

**Short answer: This is an active research area, not yet a solved problem. The frontier (2026) is source-aware routing + native-language query generation + cross-source evidence consolidation. There are strong emerging frameworks but no turnkey standard.**

### 3.1 The core problem
Real answers span unstructured text, relational tables, and graphs, each with its own query language (SQL, SPARQL, Cypher, free-form). Collapsing everything into one embedding space is lossy (modality gap; loses joins/joins/traversals). The correct pattern: **keep each source native, add an access/routing layer above**. (See the OmniRetrieval motivation and rationale, below — this is the canonical formulation.)

### 3.2 **OmniRetrieval** (KAIST — arXiv 2605.29250, May 2026) — 🔴 research, but the blueprint
Takes a natural-language query, (1) reads a **catalog of structural descriptors** (schemas, ontologies, corpus summaries) jointly with the query using a long-context LLM → selects k relevant sources; (2) generates a **native-query per source** (SQL/SPARQL/Cypher/text) grounded in that source's schema; (3) executes each and runs **cross-source evidence selection** (LLM picks the relevant subset). Evaluated across 13 datasets / 309 KBs / 4 backend types (BEIR docs, Spider+BIRD SQL, Wikidata/SPARQL, Neo4j/Cypher); consistently beats single-source baselines and single-KB routing. Key design insight: adding a source = **registration only**, no shared encoder to retrain. Source: https://arxiv.org/html/2605.29250v1

### 3.3 **SQuARE** (S&P Global / IEEE FinLLM workshop, Dec 2025) — hybrid routing with confidence-aware fallback
For tabular/spreadsheet data: computes a structural-complexity score (header depth, merge density), routes each query to either structure-preserving **chunk retrieval** or **constrained SQL** over an autogenerated relational view; a lightweight agent supervises, refines, or merges both paths on low confidence, and **abstains** if the quality gate fails. Outperforms single-strategy baselines and ChatGPT-4o on retrieval precision and end-to-end answer accuracy. This is the closest published template to the POC's "media-derived metadata vs structured tables" split. Source: https://arxiv.org/html/2512.04292v1 (also corroborated: TableRAG mixed retrieval, cited within SQuARE; TabRAG, cited within SQuARE).

### 3.4 Industry / open-source framing (corroboration + maturity)
- **Hybrid Search Graph RAG** as the enterprise target (vector over unstructured + keyword + graph traversal), per TigerGraph and essamamdani (links in §1.3) — 🟡 enterprise pattern.
- **Agentic query routing / "Router" components** are a recognized agent-RAG component: https://blog.n8n.io/agentic-rag/
- Data virtualization / real-time access to live structured+unstructured systems as a grounding approach: https://squirro.com/squirro-blog/state-of-rag-genai
- Structured/Augmented Generation (STAG) bridging vector+relational+graph: https://www.meibel.ai/post/structure-augmented-generation-bridging-structured-and-unstructured-data-for-enhanced-rag-systems

### 3.5 How the POC agent should decide which store to query (synthesis)
Use the **OmniRetrieval long-context source-selection** pattern: ship the query together with a *catalog of source descriptors* (datalake tables + their columns; media corpus + topic/domain summary; analysis.json fields; creators/profiles SCD2 schema), let the agent/router pick the 1–3 relevant sources, generate a native query per source (SQL for lake tables, hybrid/vector query for media text), execute, and consolidate evidence. Register sources so adding a store is cheap. This gives the "contextual decision about which store" the assignment asks about — driven by schema/descriptor semantics, not just vector similarity.

**Maturity:** OmniRetrieval/SQuARE = 🔴; agent routers = 🟡; hybrid-fusion of a small number of fixed stores the POC can hand-wire = 🟢 (low risk to implement directly once source selection is min("k" sources) over a known catalog).

---

## 4. Agent side: multi-agent orchestration + packaging a KB for coding agents

**Short answer: This is the most mature part of the stack in 2026. MCP is the de-facto tool/data standard; Agent Skills (SKILL.md) is the progressive-disclosure instruction format; oh-my-pi/Claude Code consume both. For the POC, wrap the KB as an MCP server exposing search/query tools + an optional Agent Skill wrapper.**

### 4.1 Model Context Protocol (MCP) — 🟢 THE standard
Open protocol ("USB-C for AI": standardized connect data sources, tools, workflows). Broad client support: Claude, ChatGPT, VS Code, Cursor, and many more (official docs). Adopted across the ecosystem — OpenAI, Google DeepMind, Microsoft, AWS; **donated to the Linux Foundation (Agentic AI Foundation, late 2025)**. This is the natural REST/CLI-to-agent bridge for the POC's KB: expose tools like `search_media`, `query_lake(sql)`, `get_post`, `list_sources`. Sources (2+):
- MCP official: https://modelcontextprotocol.io/
- WorkOS "Everything about MCP in 2026": https://workos.com/blog/everything-your-team-needs-to-know-about-mcp-in-2026
- Linux Foundation AAIF donation: https://cuttlesoft.com/blog/2025/11/25/anthropics-model-context-protocol-the-standard-for-ai-tool-integration/ ; https://interviewbaba.com/mcp-interview-questions/ ; https://ssntpl.com/what-is-mcp-model-context-protocol/
- MCP + function calling practice: https://tetrate.io/learn/ai/llm-function-calling-guide

### 4.2 Anthropic Agent Skills (SKILL.md) — 🟢 document/instruction packaging
Filesystem-based directories (metadata + SKILL.md instructions + scripts/ressources) with **progressive disclosure** (≈100 tokens for name+description at startup; body loaded only when triggered; scripts run via bash so only output enters context). Available on Claude API, claude.ai, AWS/Foundry; **skills in Claude Code live in `~/.claude/skills/` (personal) or `.claude/skills/` (project)**, and are shareable via Claude Code Plugins. This is exactly how a KB "how to use" layer can ride on top of an MCP server. Sources (2+):
- Official Agent Skills docs: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- Anthropic engineering "Equipping agents for the real world with Agent Skills": https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- MCP-vs-Skills decision guidance: https://ravichaganti.com/blog/agent-skills-vs-model-context-protocol-how-do-you-choose/

### 4.3 Function-calling / tool-use
Native tool-calling is the mechanism agents use to invoke MCP tools — a standard, production-mature capability (OpenAI/Anthropic). MCP is largely a standardized transport for this. Sources: https://tetrate.io/learn/ai/llm-function-calling-guide ; MCP cross-client adoption (above).

### 4.4 Multi-agent orchestration
Several 2026 frameworks target orchestration + RAG adaptation (AutoGen, DSPy, Semantic Kernel, LangGraph, Haystack, LlamaIndex). Notable specific insight: a single agent managing a workflow can mis-prioritize steps (e.g., skip schema fetch) — a documented text-to-SQL multi-agent failure (Google Cloud: https://medium.com/google-cloud/the-six-failures-of-text-to-sql-and-how-to-fix-them-with-agents-ef5fd2b74b68). General guidance: prefer sub-agent-per-store with an orchestrator/router, not one agent juggling everything. Framework comparison source: https://www.index.dev/skill-vs-skill/ai-semantic-kernel-vs-autogen-vs-dspy ; LlamaIndex ownership framing: https://developersvoice.com/blog/agentic-ai/architecting-agentic-rag-enterprise-knowledge-management/

### 4.5 Packaging recommendation for the POC
1. Build the KB service (hybrid retrieval + curated-view text-to-SQL + source catalog) with a REST API + CLI/Web.
2. Expose it as an **MCP server** (tools: search, query_lake, get_post, list_sources) → instantly usable by Claude Code, Cursor, oh-my-pi, others.
3. Bundle an **Agent Skill** (SKILL.md) that teaches agents when/how to call the KB (progressive disclosure; ~5k-token body).
4. Optionally surface a CLI wrapper for non-MCP harnesses (like oh-my-pi's tool/skill/plugin packaging).
Maturity mix: MCP/Skills = 🟢; plugin/tool packaging per-harness = 🟢 but fragmented (each harness has its own plugin format; MCP + Skills converge most of it).

---

## 5. Open problems and recommended reading for the POC

### 5.1 Key open problems (2026)
1. **Source selection / router reliability** — getting the *router itself* to be accurate (which store) is unsolved at scale; OmniRetrieval uses long-context selection but correctness at hundreds of heterogeneous KBs is 🔴. For the POC (a small, hand-registered catalog) this is tractable.
2. **Silent-wrongness/verifiability** — across text-to-SQL *and* RAG, plausible-but-wrong answers are the top reliability risk for autonomous agents. The guardrail answer (quality gates, SQL guards, abstain-on-low-confidence) is partial.
3. **GraphRAG cost/benefit** — when graph augmentation is worth its index cost remains query-type-dependent and unresolved; LazyGraphRAG mitigates cost but routing to it correctly is open.
4. **Benchmark/live-accuracy gap** — academic text-to-SQL/RAG numbers do not predict real-schema performance ("performance cliff") — evaluation must be on the POC's own data.
5. **Cross-harness distribution** — no single packaging standard covers every harness; MCP helps, but plugin-format fragmentation remains operational friction.

### 5.2 Recommended reading (primary / authoritative)
- Hybrid search & modern RAG components: Denser.ai (https://denser.ai/blog/hybrid-search-for-rag/); Medium-2026 (https://medium.com/data-science-collective/modern-rag-in-2026-the-components-that-actually-matter-3f6a138ef117)
- GraphRAG lineage + LazyGraphRAG: TigerGraph (https://www.tigertgraph.com/blog/advanced-rag-techniques-naive-to-hybrid-graphrag/); cruxdigits (https://cruxdigits.nl/blog/rag-vs-graphrag-2026/); arXiv 2602.03578 (http vs vanilla: https://arxiv.org/html/2602.03578v1)
- Federated/heterogeneous routing: **OmniRetrieval** (https://arxiv.org/html/2605.29250v1) 🔴-but-the-blueprint; **SQuARE** (https://arxiv.org/html/2512.04292v1) — the most POC-relevant paper
- Text-to-SQL production realities & guardrails: performance cliff (https://medium.com/@visrow/the-text-to-sql-performance-cliff-2026-why-natural-language-to-sql-breaks-a7281a23dbea); failure modes (https://tianpan.co/blog/2026-04-10-text-to-sql-failure-modes-production); semantic layer vs text-to-SQL (https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- Agent packaging: **MCP** (https://modelcontextprotocol.io/); **Agent Skills official docs** (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview); MCP-vs-Skills (https://ravichaganti.com/blog/agent-skills-vs-model-context-protocol-how-do-you-choose/)
- DSPy (https://dspy.ai/); awesome-rag-production (https://github.com/Yigtwxx/awesome-rag-production)

### 5.3 Recommended POC architecture (synthesis; NOT an implementation plan — for reading reference)
```
                    ┌─────────────────────────────────────────┐
                    │        Coding agent (Claude Code,       │
                    │        oh-my-pi, Cursor)                │
                    └───────────────┬─────────────────────────┘
                                    │ MCP (tools) + Agent Skill (SKILL.md)
                    ┌───────────────▼─────────────────────────┐
                    │   KB service                            │
                    │   · Router/source-selector   [🟡]      │
                    │   · Hybrid retrieval (BM25+dense+RRF)   │
                    │     + cross-encoder rerank  [🟢]        │
                    │   · Text-to-SQL over curated views      │
                    │     (SELECT-only replica + SQL guards)  │
                    │   · Evidence consolidation + quality gate│
                    └───┬──────────┬──────────┬───────────────┘
         media/transcripts  lake (DuckDB/)  analysis.json/
         (vector+BM25)      curated views   creators SCD2
```
**Suggested maturity mix for the POC build:** hybrid retrieval 🟢, curated-view text-to-SQL 🟢, MCP + Agent Skills 🟢, agentic router 🔴/🟡 (start with OmniRetrieval-style long-context selection over a small registered catalog).
