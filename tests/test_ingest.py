"""Build-3 generic ingest tests (docs/productization-build.md, Build-3).

Hermetic: no live API calls, no dependence on the live corpora/uiux.yaml —
the corpus declaration is written into a tmp corpora dir mirroring the
Data-1 contract, and the ig_saved fixture tree lives under
tests/fixtures/ingest/. Uses only the build-1 loader + the ingest seam.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from kb_engine.config import load
from kb_engine.ingest import (
    EnvelopeFailure,
    Gap,
    IngestPipeline,
    MappingError,
    PipelineError,
    RecordDedupe,
    RecordMapper,
    TransformError,
    apply_transform,
    content_hash,
    make_adapter,
)
from kb_engine.ingest.adapters import AdapterError, IgSavedAdapter
from kb_engine.ingest.dedupe import DedupeError
FIXTURES = Path(__file__).parent / "fixtures"
SCRAPE = FIXTURES / "ingest" / "scrape"

ENGINE_CONFIG = """
engine:
  artifacts_dir: {tmp}/artifacts
  user_data_dir: {tmp}/user_data
  corpora_dir: {tmp}/corpora
  default_corpus: uiux
"""

# Mirrors the Data-1 contract (corpora/uiux.yaml) source block, with the
# location pointed at the hermetic fixture tree.
CORPUS_YAML = """
schema:
  schema_version: "1"
  id_field: post_id
  refresh_hash_fields: {refresh}
  fields:
    post_id:          {{ type: string }}
    shortcode:        {{ type: string }}
    url:              {{ type: url }}
    owner:            {{ type: string, role: [filter, facet, sort] }}
    content_type:     {{ type: string, role: [filter, facet] }}
    domains:          {{ type: "list[string]", role: [filter, facet] }}
    is_educational:   {{ type: bool,  role: [filter] }}
    value_score:      {{ type: int,   role: [metric] }}
    gated_content:    {{ type: bool,  role: [filter] }}
    gated_trigger:    {{ type: text }}
    summary:          {{ type: text,  role: [search], weight: 1.0 }}
    transcript:       {{ type: text,  role: [search] }}
    workflow_steps:   {{ type: "list[text]", role: [search] }}
    tips:             {{ type: "list[text]", role: [search] }}
    caption:          {{ type: text,  role: [search] }}
    concepts:         {{ type: "list[string]", role: [search] }}
    tools_apps:       {{ type: "list[string]", role: [filter, facet] }}
    tags:             {{ type: "list[string]" }}
    media_files:      {{ type: "list[string]" }}
    extraction_status: {{ type: string, role: [filter, facet] }}
    is_promo:         {{ type: bool,  role: [filter] }}
sources:
  - name: uiux-scrape
    adapter: ig_saved
    location: {location}
    snapshot: test-snap
    mapping:
      post_id:      {{ from: metadata.id, transform: coerce_str }}
      shortcode:    {{ from: metadata.shortCode, transform: coerce_str }}
      url:          {{ from: shortcode, transform: template, pattern: "https://www.instagram.com/p/{{value}}/" }}
      owner:        {{ from: metadata.ownerUsername, transform: coerce_str }}
      summary:      {{ from: analysis.summary, transform: coerce_str }}
      transcript:   {{ from: analysis.transcript, transform: coerce_str }}
      workflow_steps: {{ from: analysis.workflow_steps, transform: list }}
      tips:         {{ from: analysis.tips, transform: list }}
      concepts:     {{ from: analysis.concepts, transform: list }}
      tools_apps:   {{ from: analysis.tools_apps, transform: list }}
      value_score:  {{ from: analysis.value_score, transform: coerce_int }}
      content_type: {{ from: analysis.content_type, transform: coerce_str }}
      domains:      {{ from: analysis.domains, transform: list }}
      is_educational: {{ from: analysis.is_educational, transform: coerce_bool }}
      gated_content:  {{ from: analysis.gated_content, transform: coerce_bool }}
      gated_trigger:  {{ from: analysis.gated_trigger, transform: coerce_str }}
      tags:         {{ from: metadata.hashtags, transform: list }}
      caption:    {{ from: metadata.caption, transform: coerce_str }}
      media_files:  {{ from: media, transform: list }}
      is_promo:     {{ from: analysis.is_promo, transform: coerce_bool }}
    provenance:
      source: scrape-ig-saved-list
      media_ref: dataset_post_dir
      timestamp_field: analysis.analysed_at
      extractor_field: analysis.extractor_model
      confidence_field: analysis.confidence
    dedupe:
      key: [post_id]
      order: source_declaration
      policy: {policy}
{dedupe_extra}
    missing:
      envelope_failure: {missing}
"""

# Small corpus for dedupe/namespace/hash-narrowing unit tests.
MINI_CORPUS = """
schema:
  schema_version: "1"
  id_field: post_id
  refresh_hash_fields: {refresh}
  fields:
    post_id: {{ type: string }}
    summary: {{ type: text, role: [search] }}
sources:
{sources}
"""


class StaticAdapter:
    """Hermetic adapter returning canned raw items."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    def load(self) -> Any:
        return iter(self._items)


def _write(corpus_name: str, corpus_yaml: str, tmp_path: Path):
    corpora = tmp_path / "corpora"
    corpora.mkdir(exist_ok=True)
    (corpora / f"{corpus_name}.yaml").write_text(corpus_yaml, encoding="utf-8")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(ENGINE_CONFIG.format(tmp=tmp_path.as_posix()), encoding="utf-8")
    config = load(cfg_path)
    assert config.errors == {}, config.errors
    return config.corpus(corpus_name)


def uiux_corpus(tmp_path: Path, **overrides: str) -> Any:
    return _write("uiux", CORPUS_YAML.format(
        location=SCRAPE.as_posix(),
        refresh=overrides.get("refresh", "[]"),
        policy=overrides.get("policy", "keep_first"),
        missing=overrides.get("missing", "gap"),
        dedupe_extra=overrides.get("dedupe_extra", ""),
    ), tmp_path)


def mini_corpus(tmp_path: Path, sources_yaml: str, refresh: str = "[]") -> Any:
    return _write("mini", MINI_CORPUS.format(
        sources=sources_yaml, refresh=refresh), tmp_path)


def uiux_source_spec(tmp_path: Path, **overrides: str):
    corpus = uiux_corpus(tmp_path, **overrides)
    return corpus, corpus.sources[0]


# ---- transform registry ------------------------------------------------------

def test_transform_registry_rejects_unknown_id():
    with pytest.raises(TransformError, match="unknown transform"):
        apply_transform("slugify", "x", {})


def test_transform_registry_is_the_closed_primitive_set():
    from kb_engine.ingest import registered_transforms

    assert registered_transforms() == frozenset(
        {"identity", "coerce_str", "coerce_int", "coerce_bool",
         "list", "template", "path_join"}
    )


@pytest.mark.parametrize(
    ("name", "value", "params", "expected"),
    [
        ("identity", "v", {}, "v"),
        ("coerce_str", 42, {}, "42"),
        ("coerce_str", True, {}, "true"),
        ("coerce_int", "12", {}, 12),
        ("coerce_int", 3.0, {}, 3),
        ("coerce_bool", "false", {}, False),
        ("coerce_bool", 1, {}, True),
        ("list", "solo", {}, ["solo"]),
        ("list", None, {}, []),
        ("template", "Cp1", {"pattern": "https://x/p/{value}/"}, "https://x/p/Cp1/"),
        ("path_join", ["a", "b", "c"], {}, "a/b/c"),
        ("path_join", ["a", "", None, "d"], {}, "a/d"),
    ],
)
def test_transform_primitives(name, value, params, expected):
    assert apply_transform(name, value, params) == expected


def test_transform_errors_on_bad_values():
    with pytest.raises(TransformError):
        apply_transform("coerce_int", "12x", {})
    with pytest.raises(TransformError):
        apply_transform("template", "x", {})  # missing pattern param


# ---- mapping + envelope ------------------------------------------------------


def raw_by_id(item: Mapping[str, Any]) -> str:
    return item["metadata"]["id"]


def test_mapper_produces_canonical_envelope(tmp_path):
    corpus, spec = uiux_source_spec(tmp_path)
    adapter = IgSavedAdapter(spec)
    raw = next(r for r in adapter.load() if r["metadata"]["id"] == "p1")

    record = RecordMapper(corpus, spec).map(raw)

    assert record.id == "p1"
    assert record.content_hash
    assert record.provenance.source == "scrape-ig-saved-list"
    assert record.provenance.media_ref == "test-snap/ds1/p1"
    assert record.provenance.timestamp == "2026-09-01T00:00:00Z"
    assert record.provenance.extractor == "gemini-test-1"
    assert record.provenance.confidence == pytest.approx(0.9)

    fields = record.fields
    assert fields["post_id"] == "p1"
    assert fields["shortcode"] == "Cp1"
    assert fields["url"] == "https://www.instagram.com/p/Cp1/"
    assert fields["owner"] == "alice"
    assert fields["summary"] == "Summary one"
    assert fields["workflow_steps"] == ["step a", "step b"]
    assert fields["domains"] == ["uiux"]
    assert fields["value_score"] == 8
    assert fields["is_educational"] is True
    assert fields["gated_content"] is False
    assert fields["tags"] == ["ui", "ux"]
    assert fields["caption"] == "A caption about design systems"
    assert fields["media_files"] == ["img1.jpg"]
    assert fields["extraction_status"] == "ok"  # adapter-stamped, not mapped
    # declared types hold
    assert isinstance(fields["value_score"], int)
    assert isinstance(fields["is_educational"], bool)
    assert isinstance(fields["domains"], list)


def test_content_hash_is_deterministic_and_covers_mapping(tmp_path):
    corpus, spec = uiux_source_spec(tmp_path)
    mapper = RecordMapper(corpus, spec)
    raw = next(iter(IgSavedAdapter(spec).load()))
    first = mapper.map(raw)
    second = mapper.map(raw)
    assert first.content_hash == second.content_hash
    assert first.content_hash == content_hash(first.fields, ())


def test_refresh_hash_fields_narrow_the_hash(tmp_path):
    sources = """
      - name: s
        adapter: ig_saved
        location: x
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
          caption: { from: metadata.caption, transform: coerce_str }
        provenance:
          source: src
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
        missing:
          envelope_failure: gap
    """
    body = MINI_CORPUS.format(sources=sources, refresh="[summary]").replace(
        "    summary: { type: text, role: [search] }",
        "    summary: { type: text, role: [search] }\n"
        "    caption: { type: text, role: [search] }",
    )
    corpus = _write("mini", body, tmp_path)
    spec = corpus.sources[0]
    mapper = RecordMapper(corpus, spec)
    base = {"metadata": {"id": "r1", "caption": "cap"},
            "analysis": {"summary": "sum", "analysed_at": "t"},
            "dataset_post_dir": ""}
    same_caption_changed = mapper.map(base)
    changed_summary = mapper.map({**base,
                                  "analysis": {**base["analysis"],
                                               "summary": "other"}})
    changed_caption = mapper.map({**base,
                                  "metadata": {**base["metadata"],
                                               "caption": "other cap"}})
    assert same_caption_changed.content_hash == changed_caption.content_hash
    assert changed_summary.content_hash != same_caption_changed.content_hash


def test_optional_absence_is_none_not_failure(tmp_path):
    corpus, spec = uiux_source_spec(tmp_path)
    raw = next(r for r in IgSavedAdapter(spec).load()
               if r["metadata"]["id"] == "p2")
    record = RecordMapper(corpus, spec).map(raw)
    assert record.id == "p2"
    assert record.fields["summary"] is None
    assert record.fields["value_score"] is None
    assert record.fields["gated_trigger"] is None
    assert record.fields["is_educational"] is None
    assert record.fields["caption"] == "Second caption about accessibility"
    assert record.fields["extraction_status"] == "pending"


def test_type_mismatch_raises_mapping_error(tmp_path):
    sources = """
      - name: s
        adapter: ig_saved
        location: x
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
          value_score: { from: analysis.value_score, transform: coerce_int }
        provenance:
          source: src
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
        missing:
          envelope_failure: gap
    """
    body = MINI_CORPUS.format(sources=sources, refresh="[]").replace(
        "    summary: { type: text, role: [search] }",
        "    summary: { type: text, role: [search] }\n"
        "    value_score: { type: int, role: [metric] }",
    )
    corpus = _write("mini", body, tmp_path)
    spec = corpus.sources[0]
    raw = {"metadata": {"id": "r1"},
           "analysis": {"summary": "s", "value_score": "not-a-number"},
           "dataset_post_dir": ""}
    with pytest.raises(MappingError, match="value_score"):
        RecordMapper(corpus, spec).map(raw)


def test_no_search_text_and_no_media_is_envelope_failure(tmp_path):
    corpus, spec = uiux_source_spec(tmp_path)
    raw = next(r for r in IgSavedAdapter(spec).load()
               if r["metadata"].get("id") == "p5")
    with pytest.raises(EnvelopeFailure, match="no_retrievable_text"):
        RecordMapper(corpus, spec).map(raw)


# ---- ig_saved adapter --------------------------------------------------------


def test_ig_saved_adapter_reads_fixture_tree(tmp_path):
    corpus, spec = uiux_source_spec(tmp_path)
    adapter = make_adapter(spec)
    assert isinstance(adapter, IgSavedAdapter)
    items = {item["metadata"].get("id", f"no-id-{i}"): item
             for i, item in enumerate(adapter.load())}

    assert set(items) == {"p1", "p2", "no-id-2", "p4", "p5"}
    p1 = items["p1"]
    assert p1["metadata"]["ownerUsername"] == "alice"
    assert p1["analysis"]["value_score"] == 8
    assert p1["media"] == ["img1.jpg"]
    assert p1["dataset_post_dir"] == "test-snap/ds1/p1"
    assert p1["extraction_status"] == "ok"
    # metadata-only post: analysis absent -> empty, status pending, no media_ref
    p2 = items["p2"]
    assert p2["analysis"] == {}
    assert p2["media"] == []
    assert p2["dataset_post_dir"] == ""
    assert p2["extraction_status"] == "pending"
    # media-only post: media_ref present despite no text
    p4 = items["p4"]
    assert p4["dataset_post_dir"] == "test-snap/ds1/p4"


def test_ig_saved_location_comes_from_config(tmp_path):
    # A nonexistent declared location fails with a clear adapter error —
    # proving nothing is hardcoded and location flows from config only.
    corpus = _write("uiux", CORPUS_YAML.format(
        location=(tmp_path / "does-not-exist").as_posix(),
        refresh="[]", policy="keep_first", missing="gap",
        dedupe_extra=""), tmp_path)
    with pytest.raises(AdapterError, match="location does not exist"):
        IgSavedAdapter(corpus.sources[0])


# ---- pipeline ----------------------------------------------------------------


def test_pipeline_surfaces_gaps_and_adds(tmp_path):
    corpus = uiux_corpus(tmp_path)
    results = IngestPipeline(corpus).run("uiux-scrape")
    assert len(results) == 1
    result = results[0]
    assert sorted(r.id for r in result.added) == ["p1", "p2", "p4"]
    reasons = sorted(g.reason for g in result.gaps)
    assert reasons == ["missing_id", "no_retrievable_text"]  # p3, p5 — never dropped
    assert all(isinstance(g, Gap) for g in result.gaps)
    assert result.skipped == []
    # coverage stats: non-None counts across successfully mapped items
    assert result.coverage["caption"] == 3  # p1, p2, and p4/p5 fail only later
    assert result.coverage["value_score"] == 1  # p1 only


def test_pipeline_idempotent_by_content_hash(tmp_path):
    corpus = uiux_corpus(tmp_path)
    pipeline = IngestPipeline(corpus)
    first = pipeline.run("uiux-scrape")[0]
    assert [r.id for r in first.added] == ["p1", "p2", "p4"]
    assert first.skipped == []
    # same instance, unchanged sources: everything skipped, never re-billed
    second = pipeline.run("uiux-scrape")[0]
    assert second.added == []
    assert sorted(second.skipped) == ["p1", "p2", "p4"]
    # seeded state from a previous ingest behaves identically
    existing = {r.id: r.content_hash for r in first.added}
    seeded = IngestPipeline(corpus, existing=existing).run("uiux-scrape")[0]
    assert seeded.added == [] and sorted(seeded.skipped) == ["p1", "p2", "p4"]
    # a changed hash re-ingests exactly that record
    stale = {k: v for k, v in existing.items() if k != "p1"}
    partial = IngestPipeline(corpus, existing=stale).run("uiux-scrape")[0]
    assert [r.id for r in partial.added] == ["p1"]
    assert sorted(partial.skipped) == ["p2", "p4"]


def test_pipeline_abort_policy_fails_loudly(tmp_path):
    corpus = uiux_corpus(tmp_path, missing="abort")
    with pytest.raises(PipelineError, match="missing_id"):
        IngestPipeline(corpus).run("uiux-scrape")


def test_pipeline_deterministic_output_order(tmp_path):
    corpus = uiux_corpus(tmp_path)
    ids_a = [r.id for r in IngestPipeline(corpus).run("uiux-scrape")[0].added]
    ids_b = [r.id for r in IngestPipeline(corpus).run("uiux-scrape")[0].added]
    assert ids_a == ids_b


def test_source_add_remove_touches_no_other_source(tmp_path):
    sources_two = """
      - name: a
        adapter: ig_saved
        location: x
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
        provenance:
          source: src-a
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
        missing:
          envelope_failure: gap
      - name: b
        adapter: ig_saved
        location: y
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
        provenance:
          source: src-b
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
        missing:
          envelope_failure: gap
    """
    corpus_two = mini_corpus(tmp_path, sources_two)
    sources_one = sources_two.split("      - name: b")[0] + "\n"
    # rebuild the one-source corpus in a separate tmp dir to avoid the
    # directory-is-a-registry convention conflating the two declarations
    import tempfile

    with tempfile.TemporaryDirectory() as other:
        corpus_one = _write(
            "mini", MINI_CORPUS.format(sources=sources_one, refresh="[]"),
            Path(other))

    items_a = [{"metadata": {"id": "a1"},
                "analysis": {"summary": "s", "analysed_at": "t"},
                "dataset_post_dir": ""}]
    registry = {"ig_saved": lambda spec: StaticAdapter(items_a)}
    result_two = IngestPipeline(corpus_two, registry).run("a")[0]
    result_one = IngestPipeline(corpus_one, registry).run("a")[0]
    assert [(r.id, r.content_hash) for r in result_two.added] == \
        [(r.id, r.content_hash) for r in result_one.added]
    assert [r.provenance.source for r in result_one.added] == ["src-a"]


# ---- dedupe ------------------------------------------------------------------


def _dedupe_raws() -> list[dict[str, Any]]:
    return [
        {"metadata": {"id": "dup"}, "analysis": {"summary": "first",
         "analysed_at": "2026-01-01", "confidence": 0.5},
         "dataset_post_dir": ""},
        {"metadata": {"id": "dup"}, "analysis": {"summary": "newest",
         "analysed_at": "2026-06-01", "confidence": 0.4},
         "dataset_post_dir": ""},
        {"metadata": {"id": "dup"}, "analysis": {"summary": "confident",
         "analysed_at": "2026-03-01", "confidence": 0.9},
         "dataset_post_dir": ""},
        {"metadata": {"id": "solo"}, "analysis": {"summary": "solo",
         "analysed_at": "2026-01-01", "confidence": 0.1},
         "dataset_post_dir": ""},
    ]



@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("keep_first", ["dup", "solo"]),
        ("newest", ["dup", "solo"]),
        ("highest_confidence", ["dup", "solo"]),
        ("version_append", ["dup", "dup#v2", "dup#v3", "solo"]),
    ],
)
def test_dedupe_policies_deterministic(tmp_path, policy, expected):
    corpus = _write("mini", MINI_CORPUS.format(
        sources=_mini_sources(policy), refresh="[]"), tmp_path)
    pipeline = IngestPipeline(
        corpus, {"ig_saved": lambda spec: StaticAdapter(_dedupe_raws())})
    records = pipeline.run("s")[0].added
    assert [r.id for r in records] == expected
    if policy == "newest":
        dup = next(r for r in records if r.id == "dup")
        assert dup.fields["summary"] == "newest"
    if policy == "highest_confidence":
        dup = next(r for r in records if r.id == "dup")
        assert dup.fields["summary"] == "confident"
    # deterministic across runs
    again = IngestPipeline(
        corpus, {"ig_saved": lambda spec: StaticAdapter(_dedupe_raws())}
    ).run("s")[0].added
    assert [r.id for r in again] == expected


def _mini_sources(policy: str) -> str:
    return f"""
      - name: s
        adapter: ig_saved
        location: x
        mapping:
          post_id: {{ from: metadata.id, transform: coerce_str }}
          summary: {{ from: analysis.summary, transform: coerce_str }}
        provenance:
          source: src
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
          confidence_field: analysis.confidence
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: {policy}
        missing:
          envelope_failure: gap
    """


def test_dedupe_invalid_declaration_is_config_error():
    with pytest.raises(DedupeError, match="order"):
        RecordDedupe({"key": ["post_id"], "policy": "keep_first"})
    with pytest.raises(DedupeError, match="policy"):
        RecordDedupe({"key": ["post_id"], "order": "source_declaration",
                      "policy": "last_write_wins"})


def test_cross_source_namespace_collision(tmp_path):
    sources = """
      - name: a
        adapter: ig_saved
        location: x
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
        provenance:
          source: src-a
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
        missing:
          envelope_failure: gap
      - name: b
        adapter: ig_saved
        location: y
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
          summary: { from: analysis.summary, transform: coerce_str }
        provenance:
          source: src-b
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
        dedupe:
          key: [post_id]
          order: source_declaration
          policy: keep_first
          namespace: b
        missing:
          envelope_failure: gap
    """
    corpus = _write("mini", MINI_CORPUS.format(sources=sources, refresh="[]"),
                    tmp_path)
    raw = {"metadata": {"id": "shared"},
           "analysis": {"summary": "s", "analysed_at": "t"},
           "dataset_post_dir": ""}
    registry = {
        "ig_saved": lambda spec: StaticAdapter(
            [raw] if spec.name == "a" else [dict(raw, metadata={"id": "shared"},
                                                    analysis={"summary": "b",
                                                              "analysed_at": "t"},
                                             dataset_post_dir="")])
    }
    results = IngestPipeline(corpus, registry).run()
    ids = [r.id for result in results for r in result.added]
    # the namespaced source stays distinct instead of colliding/dropping
    assert ids == ["shared", "b:shared"]


# ---- content hash sanity -----------------------------------------------------


def test_content_hash_canonical_json():
    a = content_hash({"b": 1, "a": "x"}, ())
    b = content_hash({"a": "x", "b": 1}, ())
    assert a == b
    assert a == hashlib.sha256(
        json.dumps({"a": "x", "b": 1}, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
