# Agent Knowledge Base

Research, design, and POC for an **agent-queryable knowledge base** — a
domain-oriented knowledge layer (first domain: UI/UX & design) derived from
social media content, articles, docs, and tabular data, exposed to coding agents
(oh-my-pi, Claude Code, Cursor) as a **tool / skill / plugin** via REST + CLI/Web.

The motivating idea: agents are good at decomposing broad, poorly-defined
questions into sub-queries and investigations. This KB gives them a grounded,
queryable knowledge surface so they do **less guesswork**, and it complements
whatever other tools the agent has access to.

> **Status: research / discovery.** This repo currently contains requirements,
> research, and an architecture proposal — not implementation. See
> [docs/](docs/) and the [POC architecture](docs/architecture.md).

## Why this exists

- A user curates a library of Instagram saved posts (listicles, tutorials,
  design resources). The value is in the **media** — carousel images are
  text-in-image; videos carry narration + on-screen visuals.
- The knowledge in that library is currently not queryable by agents.
- This POC makes it queryable: media → structured extraction + embeddings →
  hybrid retrieval → an agent-facing skill.

## Repository map

```
docs/
  RESEARCH.md             # idea, requirements, context, research threads, 2026 landscape
  architecture.md         # the proposed POC architecture (build order + spikes)
  expert-panel.md         # 4-role panel: validation, vertical slice, kill criteria, docs
  research/
    kb-search-state-of-art.md  # hybrid/vector/graph RAG, text-to-SQL, federated routing, MCP+Skills
    media-extraction.md        # extract-once vs embed vs both (the deep dive)
    media-embeddings.md        # 2026 image/video embedding models, costs, spike method
    costs-and-solutions.md     # aligned platforms + 2026 cost tables
```

## Related source repos

This POC builds on and references two existing projects:

- **`scrape-ig-saved-list`** — Apify `instagram-scraper` pipeline extracting saved
  Instagram posts (rich metadata + media). Includes a Gemini-based analysis
  pipeline (`quick_analyze.py`) that already extracts structured knowledge
  (resources/URLs, workflow steps, tips, concepts, gated-content/CTA detection)
  per post into `analysis.json`. 557 profiles / 809 posts.
- **`datalake`** — medallion lakehouse (bronze/silver/gold Parquet + DuckDB +
  SQLite) with Gemini enrichment, async batch worker, media byte cache, and a
  `creators`/`profiles` (SCD2) model. Focused on **creator analysis**.

The KB is a distinct **content/knowledge** layer that consumes from both: post
metadata/media + analysis from the scrape repo, and profile/creator structure +
a read-only consumption path from the datalake. The KB is a **derived consumer,
never a second writer**.

## How to use this repo

Read [docs/RESEARCH.md](docs/RESEARCH.md) for the full picture, then
[docs/architecture.md](docs/architecture.md) for the proposed POC build. It is a
requirements-and-research artifact, not an implementation spec.

## Roadmap (research to implementation)

1. Research + requirements — *current state* (done in `docs/`)
2. Write eval/gold set → run spikes (E1–E4) → confirm architecture
3. Vertical slice: 20-post extraction gate, then full-corpus index
4. Agent skill + CLI + optional MCP; A/B against baseline
5. Publish and iterate

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
