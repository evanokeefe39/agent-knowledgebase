# UI/UX Knowledge Digest — from the scrape-repo media corpus

**Source:** the 51 posts with media in `~/repos/scrape-ig-saved-list/data/uiux/`
(post_metadata.json with captions, hashtags, comments, and media on disk).
**Produced:** 2026-09-01, by extracting the real captions/comments from the
scrape repo (not the thin 86-post metadata dump in this repo's `data/uiux/`).
**Note:** this is the **immediate-value slice** — text from captions/comments only.
Media extraction (per-slide/per-frame text + transcript of the 34 mp4) is the
M-UX2 milestone. Sources resolve via `https://www.instagram.com/p/{shortcode}/`.

---

## Corpus at a glance

| Metric | Value |
|---|---|
| Posts with media (video/sidecar) | **51** (32 video, 19 sidecar; 197 media files: 163 jpg + 34 mp4) |
| Captions present | 51/51 |
| Total comments | **62,890** |
| Gated/CTA posts (comment-to-get) | **19** of 51 |
| Dominant themes | Claude Code design workflows · AI image/video · design references/inspo · vibecoding · font/typography |

---

## The 5 highest-value posts (by engagement + substance)

### 1. `DaNYCILlDgO` — 42 Claude design skills in 6 layers (15,998 comments)
**The single most valuable post in the corpus.** A creator who spent months
collecting Claude Code skills that "fix slop" — generic gradients, cheap motion,
templated defaults — sorted into 6 layers:
- **Frontend & UI** — force bold aesthetic directions, not templated defaults
- **Graphics, 3D & Video** — editable vectors, Blender, Remotion, After Effects
- **Claude Design (Canvas)** — high-fidelity app frames and design systems
- **Interaction patterns** — token budgeting, frustration detection, graceful repair
- **Prompt architecture** — persona, tone, constraints that never drift
- **Trust & orchestration** — guardrails, citations, agent handoffs

**The usage recipe he shares:** don't install all 42 at once; stack 3–4 that "fight
slop at the source," then add eyes:
1. `frontend-design` / `impeccable` / `taste-skill` — one base taste layer
2. `animate` — motion that doesn't feel cheap
3. `playwright-mcp` — the feedback loop so the model grades its own work

**Gate:** Comment `DESIGN`. → https://www.instagram.com/p/DaNYCILlDgO/

### 2. `DcEFABnvBuH` — 5 Claude Code plugins for better UI (9,054 comments)
A concrete, named five-plugin stack:
1. **Taste Skill** — pulls real design taste from premium references (76,000+ stars on GitHub)
2. **Web Design Guidelines** — audits code against Vercel's design rules, flags weaknesses + accessibility
3. **Full design system skill** — hands AI a complete design system (colors, type, spacing, buttons)
4. **21st Dev MCP** — 10,000+ professional UI components, add with one command
5. **Playwright CLI** — opens a browser, screenshots what was built, catches messy output

**Gate:** Comment `DESIGN`. → https://www.instagram.com/p/DcEFABnvBuH/

### 3. `Dblrpj-E_Lf` — font pairing: "one loud, one quiet" (5,971 comments)
The whole secret to font pairing is **contrast**, not taste: a heavy display font
next to a plain one does 90% of the work. He paired 8 fonts for 8 feelings, with
**Canva-safe free swaps** for the half that are paid (so you can use them without
buying). "You don't need to collect fonts. You need two."
**Gate:** Comment `PAIRS`. → https://www.instagram.com/p/Dblrpj-E_Lf/

### 4. `DbO1JEoSBE7` — layout-reference sites (2,508 comments)
A curated list of where to study layout, each with a specific use:
- **Land-book** — filter landing pages down to a single component (one pricing block, 20 ways)
- **godlywebsite** — high floor on landing pages specifically
- **siteinspire** — running since 2009; archives show how typography/grids evolved
- **awwwards** — for ambition/spectacle, not patterns
- **mobbindesign** — real app flows screen-by-screen (hierarchy > most courses)

**Gate:** Comment `LAYOUT`. → https://www.instagram.com/p/DbO1JEoSBE7/

### 5. `DaQQ79mjeo3` — realistic AI images: campaign-ready vs "a result" (1,991 comments)
The difference between any AI image and a campaign-ready one comes down to:
- **Composition** — how everything sits in the frame
- **Lighting** — what light shapes the shot, where it comes from
- **Campaign match** — whether it matches an existing campaign look
- **Intent** — what the shot is for and must communicate

"Without that precision behind every prompt, the results won't feel consistent."
**Gates:** Comment `editz` (180+ page strategy guide) / `AI` (full editing workflow).
→ https://www.instagram.com/p/DaQQ79mjeo3/

---

## Theme clusters (all posts, categorized)

### A. Claude Code / AI-assisted design workflow (highest-value cluster)
| Post | Comments | What it shares | Gate |
|---|---|---|---|
| `DaNYCILlDgO` | 15,998 | 42 design skills, 6 layers + usage recipe | `DESIGN` |
| `DcEFABnvBuH` | 9,054 | 5 named Claude Code plugins | `DESIGN` |
| `DblU1r_HA5p` | 4,813 | Claude Code workflows, skills, guides | `agent` |
| `Dblx-7rJUPG` | 1,227 | Claude Code workflows, skills, guides | `agent` |
| `DcEJDHBTyPY` | 979 | "Does your VIBECODED site have any of this" — quality checklist | DM |
| `DcOs3VwRK0B` | 1,288 | Tools for startup/marketing/Claude | `Claude` |

### B. AI image & video generation (production workflows)
| Post | Comments | What it shares | Gate |
|---|---|---|---|
| `DYNprnKDdFr` | 1,020 | Nano Banana: transform images into new angles/styles/props, keep brand consistency | `editz`/`AI` |
| `DZxnLlkDaHx` | 763 | AI product shoots for fragrance/beauty — scene, model, props, product accuracy | `editz`/`AI` |
| `DaQQ79mjeo3` | 1,991 | Campaign-ready AI images: composition/lighting/match/intent | `editz`/`AI` |
| `Da0GgfHuCRr` | 4,811 | **Cinematic AI websites decoded:** the animations are looping videos behind the hero, made in Google Flow / any AI video generator; caution: video backgrounds wreck load time | stan.store |

### C. Design references & inspiration sites
| Post | Comments | What it shares | Gate |
|---|---|---|---|
| `DbO1JEoSBE7` | 2,508 | Land-book, godlywebsite, siteinspire, awwwards, mobbindesign | `LAYOUT` |
| `DZnIfiCojhr` | 1,258 | "SITES I STEAL AESTHETICS FROM" — analyze better references; ask GPT for a visual DNA breakdown | `STEAL` |
| `DcerVsOPsfx` | 201 | Website inspo top-to-bottom, "footers can be fun" | `websites` |
| `DZ2rnYetXam` | 30 | Amazing websites for UI/UX designers | — |
| `DZj9G-hEiZW` | 5 | Sites for designers | — |
| `DZYEipolXZJ` | 31 | 3 websites to level up taste as a developer (technical→UX) | — |

### D. Design principles & systems
| Post | Comments | What it shares | Gate |
|---|---|---|---|
| `DaiaqXrnxu2` | 8 | "A design system starts with invisible rules, not buttons/cards/components" | — |
| `DX9cnyts9J1` | 69 | "A logo isn't enough" — without a system, colors/type drift | — |
| `DbcSTKNthGN` | 11 | AI websites look the same (purple gradients, giant headlines, cards-in-cards) | — |
| `DaM26LMulZF` | 278 | "No one rushes to compliment boring design" | — |
| `DUELjjBDsKc` | 11 | Three design rules you probably didn't know | — |
| `DaSLzVBOREn` | 7 | Copy pixel-perfect → build modern taste | — |

### E. Tool & resource lists
| Post | Comments | What it shares | Gate |
|---|---|---|---|
| `DaK9bi0jVmN` | 34 | "Tools people use quietly": Interfaces, FreeDraw, Spotted in Prod, Billow, TaskLearn, Showreel | `TOOLS` |
| `DaNmxb2jYUh` | 266 | "Skip the usual stack" — 7 design bookmarks (Ditther etc.) | — |
| `DaWogaDOn5j` | 628 | 3 no-code design tools for websites | `design` |
| `DbYbGxekWK5` | 10 | Tools/resources used to build a design portfolio (not sponsored) | — |
| `DcMlAi4v1fb` | 69 | Curated niche-collection sites | `inspo` |
| `DZIFpkJleov` | 47 | Color palettes for branding projects (screenshot/save/share) | — |

---

## Gated-content inventory (19 posts)

The corpus is **heavily gated** — 19/51 posts (37%) push a comment-to-get trigger.
The mechanics are consistent: **comment a keyword → DM with a list/guide/skill-set.**
The gates cluster into a few high-value lead magnets:

| Lead magnet | Triggers | Posts |
|---|---|---|
| Claude Code design skills/plugins | `DESIGN`, `agent`, `Claude` | DaNYCILlDgO, DcEFABnvBuH, DblU1r_HA5p, Dblx-7rJUPG, DcOs3VwRK0B |
| AI imagery strategy (180+ page guide) | `editz`, `AI` | DYNprnKDdFr, DZxnLlkDaHx, DaQQ79mjeo3 |
| Design reference/landing-page links | `LAYOUT`, `WEB`, `PAGES`, `websites`, `board`, `STEAL`, `sites`, `inspo` | DbO1JEoSBE7, DaU7F9UPje_, DaV1qGHRyHZ, DcerVsOPsfx, DbfaVtWMIM9, DZnIfiCojhr, DaZX4a4sPYV, DcMlAi4v1fb |
| Tool lists | `TOOLS`, `design`, `library` | DaK9bi0jVmN, DaWogaDOn5j, DaVirTTxDLP |
| Full list/skills | `DESIGN`, `website` | DY04AwpleW6, DcNMBB0FgD8 |

**Watch-out:** several gated posts are **pure promos** — they advertise the lead
magnet and withhold the method (e.g. `DaU7F9UPje_` 5,253 comments is `#ad #sponsored`
Manus promo; `DZ4Eh5UPyMb` 1,193 comments is sponsored vibecoding). The
high-value *substance* sits in the few that actually describe the method in the
caption (DaNYCILlDgO, DcEFABnvBuH, DbO1JEoSBE7, Dblrpj-E_Lf).

---

## How this helps across your projects (the immediate value)

1. **Better vibecoded sites** — the Claude Code skill stacks (DaNYCILlDgO,
   DcEFABnvBuH) are directly actionable: install 3–4 skills that "fight slop" +
   a browser feedback loop. No media processing needed — the recipe is in the caption.
2. **Design reference engine** — the site lists (DbO1JEoSBE7, DZnIfiCojhr,
   DZYEipolXZJ) name exactly where to study layout, typography, and taste.
3. **AI-image production** — the composition/lighting/match/intent framework
   (DaQQ79mjeo3) and the video-background trick for cinematic sites (Da0GgfHuCRr)
   are production-ready techniques.
4. **Font pairing** — "one loud, one quiet" with Canva-safe swaps (Dblrpj-E_Lf)
   is immediately applicable.

## What's NOT here yet (the M-UX2 gap)

This digest is **text-only from captions/comments**. The 34 mp4 (video transcripts)
and the 163 jpg slide text are **not extracted** — that's the media-processing
milestone. The listicle content that lives *inside* the carousel images (e.g. the
10-slide tool lists, the 15-slide AI-product-shoot walkthrough) is the highest-value
unstructured content and requires the per-slide extraction.

---
*Generated 2026-09-01 from `~/repos/scrape-ig-saved-list/data/uiux/` post_metadata
(captions, hashtags, comments) — the 51 posts with media on disk. Sources resolve
via `https://www.instagram.com/p/{shortcode}/`.*
