# Lessons

Recorded after each session. Patterns that prevent mistakes, decisions worth
## 2026-09-05 — Raw-vs-enriched retrieval spike (executed; Reading 2)

### Enrichment value is channel-dependent — measure per serving channel, not once

The spike asked "is enrichment load-bearing?" The answer is NOT a single number:
it depends on the retrieval channel.

- Pure dense: enriched R@5 0.9722 vs raw-only 0.9410 (Δ −0.0312, outside the
  0.02 gate) → enrichment earns its keep for the default dense serving channel.
- Hybrid (BM25+RRF+raw-dense): R@5 0.917, EQUAL to enriched-hybrid → raw text
  suffices when fusion masks the dense gap.

Lesson: "does X matter" conclusions must name the channel they were measured on.
The fusion-vs-dense decision (RRF held) and the enrichment decision are coupled:
enrichment matters most when dense is the serving channel.

### Read the miss PATTERN, not the R@5 headline

The delta was 3 PARTIAL recall losses (q013/q017/q018, ranking-margin shifts on
shorter raw texts), and **0 full A-correct/B-missed questions** — raw text carried
enough vocabulary for every question enriched-dense answered. The gap was not
enrichment-only vocabulary. A headline-only reading would have misattributed the
cause. Report both full-miss and partial-recall deltas.

### Data-contract gap: caption never survives into KbPost v1

`raw` here = transcript + tags only (tags ← hashtags); the caption field is
populated by no ingest path in this corpus. Mapping caption into the envelope is
the cheapest enrichment-independent raw-recall win, and the natural first move if
a raw-first corpus underperforms.

### Validity gate before spend

Reproducing the documented M4 dense baseline (R@5 0.9722 vs 0.972, Δ0.0002) on the
merged 185-corpus BEFORE the variant-B embedding run gated all spend; variant B
cost <$0.01 (150 texts, 48,457 tokens). A validity run that gates external spend is
the right order — never embed a comparison corpus before proving the harness
reproduces the known baseline.

### Artifacts preserved

Scratch (builder script, variant-B vector DB, build/validity logs) preserved on
disk at `scratch/spike_raw_enriched/` (gitignored). Report committed:
`data/eval/runs/20260905-075117-raw-vs-enriched-spike.json` (+ A/B ablation JSONs).

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
