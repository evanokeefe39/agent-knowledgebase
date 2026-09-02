# Lessons

Recorded after each session. Patterns that prevent mistakes, decisions worth
preserving, and gaps in the specification template.

---

## 2026-09-02 — Embedding spikes (text/image/video) + cross-repo cost modeling

### Cost-estimate validation gate (five whys)

Problem: two successive wrong embeddings-cost estimates shipped (Voyage modeled
at a "$6/1M doc-token" rate instead of per-pixel; a "parity" conclusion used
batch-Gemini vs standard-Voyage — an unfair basis).

- Why 1: vendor pricing was transcribed without verifying the billing unit
  (Voyage multimodal bills per-PIXEL, not per-document/token).
- Why 2: no cross-check against vendor clamp-bounds (per-image 50k–2M px) or a
  known real spend.
- Why 3: cost figures carried no source or date, so an outdated basis survived.
- Why 4: batch-vs-standard discounts were mixed between the two models.
- Why 5: no validation gate before a cost figure enters a doc/conclusion.

Fix (rule): **before any cost estimate is treated as final, it must pass**
(a) vendor-basis confirmed (per-pixel/per-unit/per-token), (b) a comparison at
the SAME discount basis, (c) a source + date attached. Centralize the carrier
rates once (see `docs/research/spike-lessons.md`) instead of re-deriving them.

### Frame-accounting rule

Cost/embed video by FRAMES derived from real durations, never
`file_count × per-video`. Gemini caps 32 frames/video; real mean ~23.7 →
~202K frames for the 8,524-video corpus, ~35% under the naive 8524×32 estimate.

### Cross-repo signal

The scrape → datalake → KB pipeline shares one corpus and (partly) one Gemini
billing account. Cost/tier/quota findings from KB spikes are surfaced to the
other two repos; each keeps only the slice actionable to it. See
`docs/research/spike-lessons.md`.
