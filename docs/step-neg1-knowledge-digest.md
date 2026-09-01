# Step −1: Creator-Growth Knowledge Digest

**Source:** `data/step-neg1/creator-growth-knowledge.json` (99 records, 322 resources,
296 tips, 46 gated/CTA posts).
**Produced:** 2026-09-01, by querying the consolidated JSON directly in a single
context window (the step −1 approach — no retrieval infrastructure).
**Scope note:** 95/99 records are flagged educational; 4 are not (promos/claims).

---

## Headline findings

1. **The corpus is heavily concentrated.** A single creator, `bywaviboy`, owns
   **27 of 99** records (27%) and spans nearly every domain (ai_tools, branding,
   career, dev_tools, frontend, graphic_design, motion, photography, ui_ux).
   `vinny_creative` (12) and `angus.sewell` (6) are the next largest. Digesting
   these three owners covers ~45% of the whole set.
2. **The dominant theme is career + AI-tooling.** 70/99 records touch `career`,
   55 `ai_tools` — the corpus is not "how to grow on social" broadly, it is
   "use AI to build a career/brand/business." Content types skew strongly to
   **workflow (45)** and **promo (13)**, then resource lists (15).
3. **A small tool stack recurs.** Claude (20), ChatGPT (10), Canva (7),
   Midjourney (6), n8n (4), Figma (4), Cursor (3), Notion (4). Automation
   (n8n/agents) + AI image generation (Midjourney/Nano Banana/Higgsfield) +
   AI coding (Claude/Cursor) is the recurring stack.

---

## Top client-getting / growth workflows (value_score ≥ 4)

| Creator | Score | Workflow (condensed) |
|---|---|---|
| `juliabroome` | 5 | Repurpose one 10–20 min YouTube video into: 30s TikTok + 30s IG Reel + Threads post + 7–15s TikTok audio strip + 2× 15s IG Stories + one Threads line. One shoot, six outputs. |
| `softgirlnocode` | 5 | Test a core idea as a short X/Twitter post first; if it performs, expand into newsletter → YouTube script → podcast script. Use Super X to mine top tweets in the niche. |
| `angus.sewell` | 5 | AI-accelerated web dev: codegen + UI prototyping + component libraries to ship faster. |
| `angus.sewell` | 4 | B2B SaaS from boring industries: find manual jobs (property mgmt, HVAC) → n8n deterministic workflows + Claude/ChatGPT decision agents → integrate into Slack (no custom dashboard) → Hunter.io outreach to the hiring manager. |
| `angus.sewell` | 4 | Niche marketplace: aggregate competitors with AI tools to acquire customers. |
| `angus.sewell` | 4 | Separate software concerns into specialized AI chat sessions to accelerate build. |
| `sabrina_ramonov` | 4 | SEO/AI-citation: analyze existing FAQ gaps → prioritize highest-intent questions → generate on-brand answers → clean automated schema markup. |
| `samson.ai` | 4 | Client acquisition by reverse-engineering the funnel: LTV → map journey (Impressions→Page Views→Applications→Qualified→Booked→Showed→Closed) → competitor funnels via ad libraries → set per-stage conversion targets → fix worst rate first. |
| `onlyzita` | 4 | 3-phase organic strategy for coaches: 7-day content calendar + Meedro competitor script mining → ChatGPT lead-magnet generator → Manychat funnel → 5-step DM qualifying. |
| `ethanleblanc___` | 4 | 12-week personal-brand framework: Week 1 foundation → creating mastery → 4 content types (Education/Storytelling/Authority/Double Down) → analytics → amplify → systems + offer. |
| `itsaiguide` | 4 | Seven AI prompts for job search: resume fixer, job-desc matcher, role-fit finder, bullet upgrader, cover-letter personalizer, recruiter hook, application optimizer. |
| `ashharrisprod` | 4 | $35/month automated content stack combining AI + dev tools. |

### The recurring playbook (across owners)

1. **Automate the boring repeatable task** with n8n/agents (angus.sewell, nick_saraev, askgpts).
2. **Repurpose once → publish everywhere** (juliabroome, softgirlnocode).
3. **Reverse-engineer what already converts** — competitors, top tweets, ad
   libraries, top-performing content (samson.ai, softgirlnocode, onlyzita).
4. **Gate the lead magnet behind a comment/DM/link** (46 gated posts).

---

## Recurring tools (top 30 across the 99 records)

| Tool | Mentions | Tool | Mentions |
|---|---|---|---|
| Claude | 20 | Figma | 4 |
| Instagram | 12 | AI | 4 |
| ChatGPT | 10 | Upwork | 3 |
| LinkedIn | 7 | Slack | 3 |
| YouTube | 7 | Cursor | 3 |
| Canva | 7 | Nano Banana | 3 |
| TikTok | 6 | Facebook | 3 |
| Midjourney | 6 | Dribbble | 3 |
| Behance | 5 | Domestika | 3 |
| Reddit | 4 | Perplexity | 2 |
| n8n | 4 | Claude Code | 2 |
| Notion | 4 | Higgsfield | 2 |

**Stack signatures:** AI-coding (Claude/Cursor) · automation (n8n, agents) ·
image gen (Midjourney, Nano Banana, Higgsfield) · design (Figma/Canva/Behance) ·
video (TikTok/YouTube Shorts).

---

## Gated / CTA content (46 posts)

The gate mechanism is almost always **engagement-based** (comment / DM / link-in-bio
/ prompt-pack purchase), rarely a hard paywall. Notable specific triggers:

- `itsaiguide` — "Link in bio" for the 7 resume/job-search prompts.
- `sociyell` — "Comment 📝" → 5-step Claude workflow for high-performing IG carousels.
- `milamarksonofficial` — "comment CLAUDE" → claims Claude-driven content (prompts NOT shared).
- `logangood` — "DM 30 Airbnbs" → Canva UGC portfolio pitched to Airbnb hosts.
- `ceozac` — "break it down in the caption" → Trial Reels reposting strategy.
- `sabrina_ramonov` — "learn how to COPY HER" → AI-consulting training promo.
- `bywaviboy` — "Prompt Packs in bio" → Midjourney rebrand asset packs.

**Watch-out:** several gated/CTA posts are **thin promos** — they advertise an
offer and withhold the actual method (e.g. `realaaronchen` "Instead I did this",
`milamarksonofficial`). Treat these as marketing surfaces, not knowledge.

---

## Notable resource lists (high value, value_score ≥ 4)

- `simran.khokha` — 40 employers offering visa sponsorship / relocation (EU, non-tech).
- `vinny_creative` — multiple design-learning stacks (courses, film refs, brand
  archives: LogoArchive, BP&O, The Futur, ADPList, The Dots) + designer-vs-brand-designer tool comparison.
- `electroformaint` — 18-item brand-design reading list (Designing Brand Identity,
  The Brand Gap, Zag, Start With Why) + CARI aesthetics archive.
- `angus.sewell` — 14 curated AI/automation creators (CatGPT, Bennett Spooner, James Goldbach, Edward S Honour).
- `nick_saraev` — GitHub repo of 2000+ n8n workflows & AI agents.
- `foundedceo` — 11 legal/admin startup documents (Founder agreements, Delaware, USPTO).
- `bensufiani` — Pirate Codex (free SaaS guide) + Pirate Forge (paid cohort).
- `askgpts` — MoneyPrinterTurbo: open-source automated faceless-video generator.

---

## Source resolution

**Every record resolves to a canonical Instagram URL** via its `shortcode`:
`https://www.instagram.com/p/{shortcode}/` (99/99 shortcodes present, all distinct).

> Note: the `url` field in `creator-growth-knowledge.json` is **null for all 99
> records** — the extractor never populated it. It is fully reconstructable from
> `shortcode`. Recommend backfilling `url` in the consolidation step.

---

## Data-quality caveats

1. **2 posts failed extraction** (deterministic JSON truncation on long video):
   `3838281772950469769` (angus.sewell, 5.5MB), `3948357940829368474`
   (anthonydelucv, 13.2MB). A `max_output_tokens` fix would recover them → 101/101.
2. **Gated/CTA field is over-broad** — includes pure promos; verify before treating
   a trigger as an actual content gate.
3. **Value_score is the model's own heuristic** (distribution 4:1/2/3-heavy), not
   an evaluated relevance grade. The 20-post quality gate (E1) is still the real
   trust benchmark.

---

## Suggested next actions

- **Digest by owner** — pull the full `bywaviboy` (27) and `vinny_creative` (12)
  sets as their own mini-digests; together with angus.sewell they are ~45% of value.
- **Backfill `url`** in the consolidation script (one-liner from shortcode).
- **Recover the 2 failed posts** with the token-limit fix to reach 101/101.
- **Then decide** whether the retrieval POC (`docs/architecture.md`) is still
  needed — step −1 already answers questions on a 1M window; the POC earns its
  keep only when the corpus outgrows one window or needs structured/guarded query.
