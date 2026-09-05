"""Data-2 migration runner tests (hermetic; no real scrape repo required).

Covers scripts/migrate_uiux.py: raw re-ingest + legacy port -> canonical
manifest, reconciliation against the reference, and idempotency (re-run
rewrites nothing, no re-ingest).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "migrate_uiux", Path(__file__).parent.parent / "scripts" / "migrate_uiux.py"
)
assert _SPEC and _SPEC.loader
migrate_uiux = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("migrate_uiux", migrate_uiux)
_SPEC.loader.exec_module(migrate_uiux)

ENGINE_CONFIG = """
engine:
  artifacts_dir: {tmp}/artifacts
  user_data_dir: {tmp}/user_data
  corpora_dir: {tmp}/corpora
  default_corpus: uiux
"""

CORPUS_YAML = """
schema:
  schema_version: "1"
  id_field: post_id
  refresh_hash_fields: []
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
    location: {scrape}
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
      policy: keep_first
    missing:
      envelope_failure: gap
"""


def _write_post(
    root: Path, dataset: str, folder: str, metadata: dict, analysis: dict | None
) -> None:
    post = root / "scrape" / dataset / folder
    post.mkdir(parents=True)
    (post / "post_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    if analysis is not None:
        (post / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")


def _legacy(post_id: str, **overrides: object) -> dict:
    record = {
        "post_id": post_id,
        "shortcode": post_id,
        "url": f"https://www.instagram.com/p/{post_id}/",
        "owner": "someone",
        "content_type": "other",
        "domains": [],
        "is_educational": None,
        "value_score": None,
        "gated_content": None,
        "gated_trigger": "",
        "summary": "",
        "transcript": "",
        "workflow_steps": [],
        "tips": [],
        "caption": "",
        "concepts": [],
        "tools_apps": [],
        "resources": [],
        "tags": [],
        "media_files": [],
        "extraction_status": "pending",
        "is_promo": None,
        "provenance": {
            "media_ref": None,
            "extracted_at": "2026-09-01T00:00:00+00:00",
            "extractor_model": "gemini-test",
            "confidence": None,
        },
    }
    record.update(overrides)
    return record


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Hermetic mini-repo: config + corpus + scrape tree + legacy reference.

    111: schema-v2 nested analysis with {term, explanation} concepts (raw).
    222: flat v1-shaped analysis (raw).
    333: scraped but never analysed -> pending, ported as envelope gap.
    SHRT: HAR-only shortcode-id post -> ported as envelope gap.
    """
    (tmp_path / "corpora").mkdir()
    (tmp_path / "corpora" / "uiux.yaml").write_text(
        CORPUS_YAML.format(scrape=str(tmp_path / "scrape").replace("\\", "/")),
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        ENGINE_CONFIG.format(tmp=str(tmp_path).replace("\\", "/")),
        encoding="utf-8",
    )
    _write_post(
        tmp_path, "ds1", "111",
        {"id": "111", "shortCode": "AAA", "ownerUsername": "alice",
         "caption": "cap 111", "hashtags": ["ui"]},
        {"schema_version": 2, "analysed_at": "2026-09-01T10:00:00+00:00",
         "analysis": {
             "summary": "s 111", "transcript": "t 111",
             "concepts": [{"term": "grid", "explanation": "modular layouts"}],
             "value_score": 5, "content_type": "tip",
         }},
    )
    _write_post(
        tmp_path, "ds1", "222",
        {"id": "222", "shortCode": "BBB", "ownerUsername": "bob",
         "caption": "cap 222", "hashtags": []},
        {"summary": "s 222", "concepts": ["plain"], "value_score": 7},
    )
    _write_post(
        tmp_path, "ds2", "333",
        {"id": "333", "shortCode": "CCC", "ownerUsername": "carol",
         "caption": "", "hashtags": []},
        None,
    )
    reference = [
        _legacy("111"),
        _legacy("222"),
        _legacy("333"),
        _legacy("SHRT", caption="", extraction_status="pending"),
    ]
    (tmp_path / "data" / "uiux").mkdir(parents=True)
    (tmp_path / "data" / "uiux" / "kb-posts.json").write_text(
        json.dumps(reference), encoding="utf-8"
    )
    return tmp_path


def _read(repo: Path, name: str) -> dict:
    return json.loads(
        (repo / "user_data" / "canonical" / "uiux" / name).read_text(encoding="utf-8")
    )


def test_migration_builds_manifest_matching_reference(repo: Path) -> None:
    report = migrate_uiux.migrate(repo / "config.yaml")
    manifest = _read(repo, "manifest.json")
    assert manifest["schema_version"] == "1"
    assert manifest["snapshot_id"] == "test-snap"
    ids = [r["id"] for r in manifest["records"]]
    assert ids == ["111", "222", "333", "SHRT"]  # reference order
    assert all(len(r["content_hash"]) == 64 for r in manifest["records"])
    assert len(_read(repo, "corpus.json")) == 4
    assert report["reingested_from_raw"] == 2  # 111 + 222
    assert report["ported_from_legacy"] == 2  # 333 + SHRT
    assert [g["id"] for g in report["ported_envelope_gaps"]] == ["333", "SHRT"]


def test_raw_ingest_normalizes_v2_and_concepts(repo: Path) -> None:
    migrate_uiux.migrate(repo / "config.yaml")
    corpus = {r["id"]: r for r in _read(repo, "corpus.json")}
    nested = corpus["111"]["fields"]
    assert nested["summary"] == "s 111"  # schema-v2 nesting unwrapped
    assert nested["concepts"] == ["grid: modular layouts"]  # searchability kept
    assert nested["extraction_status"] == "ok"
    assert corpus["111"]["provenance"]["timestamp"] == "2026-09-01T10:00:00+00:00"
    flat = corpus["222"]["fields"]
    assert flat["summary"] == "s 222"
    assert flat["concepts"] == ["plain"]
    assert flat["extraction_status"] == "ok"


def test_ported_pending_record_carries_fields(repo: Path) -> None:
    migrate_uiux.migrate(repo / "config.yaml")
    corpus = {r["id"]: r for r in _read(repo, "corpus.json")}
    ported = corpus["SHRT"]
    assert ported["fields"]["extraction_status"] == "pending"
    assert ported["fields"]["summary"] == ""
    assert ported["provenance"]["extractor"] == "gemini-test"
    assert ported["provenance"]["source"] == "scrape-ig-saved-list"


def test_rerun_is_idempotent_and_skips_reingest(repo: Path) -> None:
    migrate_uiux.migrate(repo / "config.yaml")
    before = {
        name: (repo / "user_data" / "canonical" / "uiux" / name).read_text(
            encoding="utf-8"
        )
        for name in ("manifest.json", "corpus.json")
    }
    report = migrate_uiux.migrate(repo / "config.yaml")
    after = {
        name: (repo / "user_data" / "canonical" / "uiux" / name).read_text(
            encoding="utf-8"
        )
        for name in ("manifest.json", "corpus.json")
    }
    assert before == after  # byte-identical: no rewrite, no re-ingest
    assert report["reingested_from_raw"] == 0
    assert report["unchanged_since_last_run"] == 2


def test_extra_raw_post_fails_reconciliation(repo: Path) -> None:
    _write_post(
        repo, "ds1", "444",
        {"id": "444", "shortCode": "EEE", "ownerUsername": "dave",
         "caption": "cap 444", "hashtags": []},
        {"summary": "s 444"},
    )
    with pytest.raises(SystemExit, match="reconciliation drift"):
        migrate_uiux.migrate(repo / "config.yaml")


def test_schema_drift_fails_not_forced(repo: Path) -> None:
    # A legacy record whose value violates the declared type is a hard
    # failure, never silently coerced or dropped.
    reference = json.loads(
        (repo / "data" / "uiux" / "kb-posts.json").read_text(encoding="utf-8")
    )
    reference.append(_legacy("BAD", value_score="not-an-int"))
    (repo / "data" / "uiux" / "kb-posts.json").write_text(
        json.dumps(reference), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="declared-schema validation"):
        migrate_uiux.migrate(repo / "config.yaml")
