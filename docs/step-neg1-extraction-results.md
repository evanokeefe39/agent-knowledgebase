# Step −1: Creator-Growth Extraction Results

**Branch:** `feat/step-neg1-creator-growth-triage`
**Date:** 2026-08-31
**Budget:** $10 (actual spend: < $1)

## What was done

1. **Triaged** the full saved corpus (1102 posts) for content-creator-growth /
   social-content-practice signal → 94 strong candidates.
2. **Extended the set** with the explicitly-named creators so none were missed:
   - `angus.sewell` (7 posts — added explicitly; was not in the lexical-strong tier)
   - `edhonour` (1) + `edward.builds` (2) — "ed honor"
   - `sabrina_ramonov` (2, already in strong tier)
3. **Ran Gemini extraction** (`quick_analyze.py`, `gemini-3.1-flash-lite`) on the
   101-post target set (94 strong + 7 adds). 60 needed fresh extraction; the rest
   were already analyzed.
4. **Consolidated** all extracted knowledge into one queryable artifact.

## Results

| Metric | Value |
|---|---|
| Target set | 101 posts (94 strong + 7 named adds) |
| Successfully analyzed | **99 / 101** |
| Failed (deterministic) | 2 (long-video JSON truncation) |
| Total resources extracted | **322** |
| Total tips extracted | **296** |
| Gated/CTA posts | **46** |
| Cost estimate | **~$0.28** (well under $10) |

### Named creators (verified present in output)
- `sabrina_ramonov`: 2 records — e.g. SEO/AI-citation workflow, AI-consulting promo
- `angus.sewell`: 6 records — B2B software strategy, AI/automation YouTube resources
- `edhonour`: 1 record — project-suitability criteria
- `edward.builds`: 2 records — SEO topical authority, SERP manipulation

## Outputs (on this branch)

- `triage_creator_growth.py` — the triage script (reproducible, no LLM)
- `data/step-neg1/creator-growth-candidates.json` — ranked candidates (94 strong / 234 medium)
- `data/step-neg1/extraction-targets.json` — the 101-post extraction manifest
- **`data/step-neg1/creator-growth-knowledge.json`** — the consolidated, queryable
  knowledge artifact (99 records: summary, resources, workflow_steps, tips,
  concepts, tools, gated/CTA, transcript)

## Known limitations (2 failed posts)

Two posts failed with a deterministic `bad JSON: Extra data` error — the model
returns valid JSON followed by trailing content at a fixed byte offset (a
long-video output-truncation issue), consistent across 4+ retries:
- `3838281772950469769` (angus.sewell, 5.5MB video)
- `3948357940829368474` (anthonydelucv, 13.2MB video)

Both videos were extracted as text/metadata but their `analysis.json` is absent.
A targeted fix (set `max_output_tokens` in the generation config, or truncate
`response.text` at the first complete JSON object) would recover these — flagged
for a follow-up, not blocking the step −1 value.

## Next step (the "action" this enables)

The consolidated `creator-growth-knowledge.json` is the input for the actual
actioning: **query it directly** (it fits in a 1M context window) to answer
questions like "what client-getting workflows did these creators share?", "which
posts gate content and behind what trigger?", "what tools recur across the
growth corpus?" — with sources (URLs) attached.
