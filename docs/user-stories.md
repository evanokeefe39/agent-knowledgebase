# Agent Knowledge Base — User Stories & Epics

**Source:** simulated prospective-user panel (2026-09-01) + `docs/architecture.md`
agent-as-user brief.
**Corpus under discussion:** the step −1 creator-growth knowledge base
(`data/step-neg1/creator-growth-knowledge.json`, 99 posts) as the concrete
reference for what the KB holds.

---

## How this was produced

A four-persona **prospective-user panel** was convened (each persona run as an
independent simulation grounded in the verified corpus facts in
`docs/step-neg1-knowledge-digest.md`), plus the **agent-as-user** perspective
carried over from the architecture/expert-panel docs. Personas:

| Persona | Who they are | Why they'd use the KB |
|---|---|---|
| **Career-seeking creative** | Job-hunter / career-pivot building a personal brand, optimizing applications, finding employers | Career strategy, resume/cover-letter prompts, employer discovery, personal-brand framework |
| **Solo creator / solopreneur** | No team, AI-heavy stack (Claude/ChatGPT/Canva/Midjourney/n8n), limited hours | Growth workflows, repurposing systems, funnels, monetization, tool-stack value |
| **Brand / graphic designer** | Working designer building identity systems + AI-assisted visual work | Resource stacks, reading lists, tool comparisons, AI-image workflows, client-winning |
| **AI-automation freelancer / no-code founder** | Sells n8n/agent workflows, hunts boring B2B niches, packaging a micro-SaaS | Client-acquisition plays, workflow teardowns, n8n steps, gated lead-magnet mechanics |
| **Agent (primary user)** | The coding agent that queries the KB on a human's behalf | Decompose fuzzy requests, route to the right store, ground every claim in evidence |

---

## Cross-persona findings (the jobs everyone wants)

Five needs recurred **unanimously** across all four personas — these define the
epics and are the highest-value targets:

1. **Provenance or nothing.** Every answer must resolve to the original post URL
   and quote concrete `workflow_steps`/`tips`, not paraphrase a summary. Unlinked
   answers are dead ends.
2. **Gated-content awareness on every answer.** With 46/99 posts gated, the KB
   must surface `gated_content`/`gated_trigger` (and flag *pure promos* that
   withhold the method) or users burn cycles chasing dead ends.
3. **Volume ≠ relevance.** bywaviboy (27) + vinny_creative (12) are ~45% of the
   corpus but skew branding/design. Ranking must honor domain/content_type/creator
   filters, not post count.
4. **Corpus-boundary honesty (abstention).** The KB is a static snapshot, not
   current market truth. It must say "the corpus doesn't cover that" rather than
   hallucinate, and must not pretend 2026 validity it can't verify.
5. **Workflow depth, not vibes.** Users come for "do this, then this" — buildable,
   ordered steps (trigger → nodes → action → handoff), with the attached resources.

---

## Epics & user stories

Each epic groups user stories. Acceptance criteria are written to be **testable
against the actual KB data fields** (`post_id`, `shortcode`→URL, `summary`,
`resources`, `workflow_steps`, `tips`, `concepts`, `tools_apps`, `domains`,
`content_type`, `gated_content`, `gated_trigger`, `transcript`, `value_score`,
`owner`).

---

### Epic 1 — Trustworthy, provenanced retrieval (foundation)

Every answer is grounded in source posts and carries the trail back to them.

**US-1.1** As a solo creator, I want every KB answer to cite the exact post(s) and
resolvable Instagram URL it came from, so I can verify and go deeper.

- Given a query that matches ≥1 post, WHEN the KB returns an answer, THEN every
  factual claim resolves to a post `shortcode` forming a valid
  `https://www.instagram.com/p/{shortcode}/` URL and cites the post `owner`.
- GIVEN a claim drawn from a specific field (e.g. a `tip`), THEN the citation names
  the post and field, not just the post.

**US-1.2** As any user, I want quoted workflow steps / tips returned verbatim from
the corpus, not paraphrased, so I trust the fidelity.

- GIVEN a post whose `workflow_steps`/`tips` are present, WHEN asked about that
  content, THEN the answer reproduces the steps in order and does not add invented
  steps (abstention applies to gaps).
- GIVEN a post that mentions a tool only in `transcript`/`summary` with no
  step-level detail, THEN the answer says "named, but no workflow detail in corpus"
  instead of synthesizing steps.

**US-1.3** As a designer, I want the actual visual posts surfaced when visual
signal matters, so a design KB isn't text-only.

- GIVEN a query where the answer's value depends on the post's imagery, THEN the
  KB returns a media reference (or states media access is unavailable) rather than
  silently dropping the visual half.

---

### Epic 2 — Workflow & how-to execution

Turn saved playbooks into buildable, ordered procedures.

**US-2.1** As a solo creator, I want the exact repurposing workflow (e.g.
juliabroome: one YouTube video → six platform-native formats) as an ordered,
copyable procedure.

- GIVEN the juliabroome repurposing post, WHEN I ask for the workflow, THEN the
  answer returns the `workflow_steps` in order and labels which steps are
  automated vs manual (where the corpus says).

**US-2.2** As an AI-automation freelancer, I want every post containing real n8n /
agent workflow steps, with those steps listed buildably (trigger → nodes → action
→ handoff).

- GIVEN a query for n8n workflows, THEN the answer returns all posts where
  `tools_apps` includes n8n AND `workflow_steps` is non-empty, renders each as an
  ordered buildable list, and separately flags posts that merely mention n8n
  without steps.
- GIVEN nick_saraev's 2000+ workflows repo is referenced, THEN it is surfaced as a
  clone-and-customize resource with its attached `resources`.

**US-2.3** As a brand designer, I want bywaviboy's AI-image pipeline
(brief → generation → refinement → deliverable) as concrete steps with the named
stack (Midjourney / Nano Banana / Higgsfield).

- GIVEN the AI-image workflow posts, THEN the answer lists the actual
  `workflow_steps`, distinguishes tips from full workflows, and admits when
  prompt-parameter detail (aspect ratios, style refs) is absent from the corpus.

---

### Epic 3 — Gated-content & lead-magnet intelligence

Users need to know what's gated, behind what trigger, and whether it's worth
stepping through.

**US-3.1** As any user, I want the gate mechanic surfaced on every answer that
touches gated content.

- GIVEN an answer referencing a post where `gated_content` is true, THEN the
  answer includes `gated_trigger` (comment keyword, DM, link-in-bio) verbatim.
- GIVEN a post whose method is withheld behind a gate, THEN the answer says so
  explicitly rather than presenting the gated method as available knowledge.

**US-3.2** As a solo creator building a lead magnet, I want the full gated
playbook across the corpus — what each gated post gives away, what it withholds,
and the trigger mechanic.

- GIVEN a request for the gated-content playbook, THEN the answer enumerates the
  46 gated posts grouped by trigger type (comment/DM/link/prompt-pack), names the
  promised give-away, and flags which are **pure promos** (no method disclosed).

**US-3.3** As a career-seeker, I want gated career resources (e.g. sabrina_ramonov
checklist) surfaced with their trigger so I know it's gated before I fish for it.

- GIVEN a gated career resource is relevant, THEN the answer flags it as gated,
  states the trigger, and does not present its (unavailable) contents as fact.

---

### Epic 4 — Tool & stack decision support

Which tool for which job, backed by what the corpus actually shows.

**US-4.1** As a solo creator, I want to know which AI tools the saved creators
actually use for which jobs before I pay for anything.

- GIVEN a tool-selection question, THEN the answer returns `tools_apps` frequencies
  and, for the top tools, the specific posts + contexts where each appears,
  separating "named by a creator" from "has workflow detail in corpus."

**US-4.2** As a brand designer, I want creator-made tool comparisons (e.g.
vinny_creative's designer-vs-brand-designer breakdown) surfaced directly.

- GIVEN a comparison request, THEN the answer returns the post(s) that compare
  tools, plus the corpus counts (Figma 4, Canva 7, Midjourney 6) as corroboration —
  and does not blend in unrelated AI-tool posts.

**US-4.3** As an AI-automation freelancer, I want build-vs-assemble guidance: when
to hand-code an agent (Claude/Cursor) vs assemble a no-code n8n flow.

- GIVEN a build-vs-assemble question, THEN the answer surfaces posts pairing
  Claude (20) / Cursor (3) / n8n (4) with their context, and states when the corpus
  is silent rather than recommending a stack it never shows.

---

### Epic 5 — Client-getting & monetization plays

Reverse-engineer what converts and apply it.

**US-5.1** As a solo creator, I want the funnel-reverse-engineering method
(samson.ai: LTV → journey map → competitor ad-library teardown → per-stage
targets → fix worst rate) as a copyable procedure.

- GIVEN the funnel post, THEN the answer returns the ordered `workflow_steps` and
  the journey stages (Impressions→Page Views→Applications→Qualified→Booked→Showed→
  Closed), and states the corpus has no post-lead-magnet (onboarding/nurture/offer)
  content rather than inventing it.

**US-5.2** As an AI-automation freelancer, I want angus.sewell's boring-industry
B2B client play separated from his adjacent posts, each with its concrete
mechanism.

- GIVEN a query for angus.sewell's client-acquisition posts, THEN the answer names
  each post individually, separates boring-industry B2B from niche-marketplace /
  freelance-automation / AI-web-dev, and quotes the `workflow_steps`/`tips`
  verbatim, flagging any that sit behind a `gated_trigger`.

**US-5.3** As a solo creator, I want to know which creators' posts cover the
free-content → paid-offer transition, and the exact gates/DM sequences used.

- GIVEN a transition/monetization question, THEN the answer returns the relevant
  posts (e.g. onlyzita organic→high-ticket), their transition sequence, and the
  gates/DM framework, and abstains where the corpus lacks the offer details.

**US-5.4** As a career-seeker, I want the resume/cover-letter prompt set
(itsaiguide) and the personal-brand framework (ethanleblanc___) as actionable
procedures.

- GIVEN a job-application workflow request, THEN the answer lists the seven
  prompts/roles and the 12-week brand framework as ordered steps, with source URLs.

---

### Epic 6 — Filtered, routed discovery

Rank by relevance, not volume; let users filter by creator/domain/type/tool.

**US-6.1** As any user, I want results filtered by domain, content_type, creator,
and tool — not drowned in bywaviboy/vinny_creative volume when I asked about a
specific play.

- GIVEN a query scoped to a domain (e.g. `dev_tools`), creator, `content_type`
  (e.g. `workflow`), or tool, THEN ranking honors the filter and excludes
  off-topic high-volume posts.

**US-6.2** As the agent, I want the KB to expose its stores/fields so I can route
the query myself (metrics → SQL; "how do I do X" → search; visual → media; creator
identity → lookup) without guessing.

- GIVEN a fuzzy request, THEN the agent can read a capability manifest and route to
  the correct store with ≥80% correct picks (per architecture E4).

**US-6.3** As any user, I want the KB to separate educational substance from pure
promo so I don't mistake marketing for knowledge.

- GIVEN a query whose results include `content_type` promo posts, THEN those are
  flagged as promo (and withheld-method) rather than quoted as neutral tips.

---

### Epic 7 — Honest abstention & corpus boundary

The KB knows what it doesn't know and says so.

**US-7.1** As any user, I want the KB to say "the corpus doesn't cover that" when
it doesn't, instead of hallucinating.

- GIVEN a question outside the corpus (e.g. pricing a first high-ticket offer, or
  post-lead-magnet nurture), THEN the answer explicitly states the corpus lacks
  that content, points to the closest related posts, and returns an
  `insufficient_evidence` signal.

**US-7.2** As any user, I want the KB to be honest that it's a static snapshot, not
current market truth.

- GIVEN a recency/validity question (e.g. "are these 2026-current?"), THEN the
  answer states the corpus is a snapshot with no verification of current
  performance or live gates, rather than asserting currency.

---

### Epic 8 — Measurable performance & regression detection (developer / maintainer)

This epic is for the **developer who builds and maintains the KB** (the repo's
own team + the coding agents that iterate on it) — not the end user. Without it,
every change to the index, chunking, model, prompt, or schema is judged by vibes,
and a silent regression ships unnoticed. Grounded in `docs/research/llm-eval-frameworks.md`
(DeepEval as the runner; Promptfoo's layered-gate model; Ragas metric vocabulary).

**US-8.1** As a developer, I want a repeatable numeric eval harness over a fixed
gold set, so I can tell whether a change improved or degraded the KB instead of
relying on vibes.

- GIVEN a fixed gold set (M3, 25–50 stratified questions + 5–10 unanswerables),
  WHEN I run the eval harness, THEN it emits Recall@5/10, nDCG@10, MRR, routing
  accuracy, abstention rate, and cost+latency per query — all in one reproducible
  report.
- GIVEN the same gold set and config, WHEN I run the harness twice, THEN the
  metrics are identical (deterministic; no silent score drift).

**US-8.2** As a developer, I want a numeric regression gate so a change that
degrades answer quality fails before it lands.

- GIVEN a previous baseline report, WHEN a new config (index / chunking / model /
  prompt / schema) scores below the threshold on any gated metric, THEN the change
  is marked failed (CI or local command), not merged on vibes.
- GIVEN the gold set split into a **smoke tier** (must-never-break core questions)
  and a **regression tier**, THEN the smoke tier gates every change at 100% pass
  and the regression tier gates merges at ~95% pass (Promptfoo gate model).

**US-8.3** As a developer, I want to know *what* caused a regression, so I fix the
right component rather than guessing.

- GIVEN a failed metric, THEN the report is keyed by
  `(schema_version, index_version, eval_set_version)` so the regression
  attributes to exactly what changed (index, extractor model, prompt, or schema).
- GIVEN a faithfulness/answer-relevancy drop, THEN I can inspect which retrieved
  posts (or chunks) the answer was grounded in, to see if the retriever or the
  generator regressed.

**US-8.4** As a developer, I want silent-wrongness and abstention measured, not
assumed.

- GIVEN the unanswerable subset of the gold set, WHEN the harness runs, THEN it
  measures abstention rate (does the KB say `insufficient_evidence` when it
  should?) and hallucination rate (does it invent answers it shouldn't?).
- GIVEN an answer, THEN faithfulness is scored against the cited posts — a
  plausible-but-ungrounded answer is a failing case, not a pass.

**US-8.5** As a developer, I want cost/latency asserted so a "quality improved"
change can't silently blow up the budget.

- GIVEN a quality-neutral or quality-positive change, THEN if per-query cost or
  latency exceeds a configured threshold, the change fails — quality and cost are
  measured together.
- GIVEN any eval run, THEN the judge/answer model and cost are recorded in the
  report, so scores across model changes stay comparable.

**US-8.6** As a developer, I want an A/B path so I can compare two candidate
configs on the same gold set (M7).

- GIVEN two configs (e.g. hybrid vs BM25-only), THEN the harness produces a paired
  metrics report + a kill-gate verdict on the same gold set and snapshot.

---

## Mapping: persona → epic coverage

| Persona | Strongest epics |
|---|---|
| Solo creator | 1, 2, 3, 5 (workflows, gated playbook, monetization) |
| AI-automation freelancer | 1, 2, 3, 4, 5 (n8n teardowns, client plays, gated mechanics) |
| Brand designer | 1, 2, 4, 6 (resource stacks, tool comparisons, visual) |
| Career-seeker | 1, 3, 5, 6 (career workflows, gated resources, filters) |
| Agent | 1, 6 (provenance, routing/manifest) |
| Developer / maintainer | 8 (numeric evals, regression gates, attribution, cost) |

---

## Priority (highest-leverage first)

1. **Epic 1 (provenance)** + **Epic 7 (abstention)** — the trust foundation; all
   four personas flagged unlinked/hallucinated answers as instant abandonment.
2. **Epic 8 (measurable performance)** — the developer's own eval harness; it is
   the instrument that makes every other epic's acceptance criteria checkable
   (build the ruler before measuring). Maps to M3.
3. **Epic 3 (gated-content awareness)** — 46/99 posts are gated; surfaced gate
   triggers prevent dead-end queries and are cheap to render from existing fields.
4. **Epic 6 (filtered routing)** — kills the volume-as-relevance failure; also
   covers the agent-as-user routing need.
5. **Epic 2 (workflow execution)** — the "do this, then this" depth users want;
   depends on Epic 1 fidelity.
6. **Epic 4 & 5 (tools, monetization)** — value-adding but higher-certainty, lower
   surprise; build after the trust layer holds.

## Non-goals (what the KB must NOT do)

- Assert current-market validity or that saved-post knowledge is truth about the
  world (US-7.2).
- Return unlinked summaries as answers (US-1.1).
- Present gated/withheld methods as available knowledge (US-3.x).
- Invent workflow steps or tools never in the corpus (US-2.x, US-7.1).
- Rank purely by creator post-count (US-6.1).

---
*Generated 2026-09-01 by a simulated four-persona prospective-user panel + the
agent-as-user brief from the architecture, plus a developer-facing eval epic
grounded in `docs/research/llm-eval-frameworks.md`. Inputs:
`docs/step-neg1-knowledge-digest.md` and `docs/architecture.md`.*
