# Data-2 contract fixes applied (2026-09-05, dlc-worker)

Real-data ingest of the UIUX scrape (`scrape-ig-saved-list/data/uiux`) surfaced
two mismatches between the declared raw-item contract and the actual scrape
files. Both were reconciled **in the `ig_saved` adapter** (the sanctioned
bespoke-logic home per plan §12) — `corpora/uiux.yaml` is unchanged.

## 1. Schema-v2 nested analysis envelope

**Observed:** every `analysis.json` in the real scrape (all 50 analysed posts)
uses `schema_version: 2` and nests the enrichment under a top-level
`analysis` object (`analysis.analysis.summary`), with `analysed_at` at the top
level. The declared mapping (`analysis.summary`, `analysis.analysed_at`, ...)
targets the flat v1 shape; as declared, every search field resolved to null
and all 50 posts failed the envelope.

**Fix:** `IgSavedAdapter.normalize_analysis()` (src/kb_engine/ingest/adapters.py)
unwraps a nested `analysis` object to the flat shape the mapping declares,
carrying top-level sibling keys (`analysed_at`, `schema_version`, ...) the
inner object does not already define, so provenance
`timestamp_field: analysis.analysed_at` still resolves. Flat (v1-shaped)
payloads — including the existing engine fixture — pass through unchanged.

## 2. Concepts: `{term, explanation}` objects vs declared `list[string]`

**Observed:** real data stores `concepts` as a list of objects
(`{"term", "explanation"}`; 83 dict elements across 50 files) — the same shape
the legacy canonical reference stores. The contract declares
`concepts: list[string]`; the mapper fail-fasts (never coerces), so every
record with concepts became a gap.

**Fix:** `IgSavedAdapter.flatten_concepts()` flattens dict entries to
`"term: explanation"` strings — the exact representation the previous engine
indexed — preserving declared type AND searchability. Strings pass through.
The migration runner applies the same helper to ported legacy records.

## Decision record

Main authorized adapter-level reconciliation (options were editing
corpora/uiux.yaml vs adapter bridging). Adapter-side was chosen because the
flat shape is what the mapper's dotted-path contract already declares and what
the committed engine fixtures encode; zero contract churn keeps the shared
read-only contract and Build-1 loader untouched.

## Downstream note

No schema field, type, role, or mapping path changed — `corpora/uiux.yaml`
and its `schema_version` are untouched, so no consumer-facing contract change.
The adapter's raw-item shape is unchanged for v1-shaped inputs; consumers of
`ig_saved` raw items with schema-v2 scrape files now see the flat shape (they
previously could not consume those files at all).
