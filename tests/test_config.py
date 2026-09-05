"""Build-1 loader tests (docs/productization-build.md, Build-1 story).

Fixtures under tests/fixtures/ mirror the exemplar shape (corpora/uiux.yaml)
but are self-contained copies: these tests never depend on the live
corpora/uiux.yaml state (Data-1 finalizes it concurrently).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from kb_engine.config import (
    Config,
    CorpusConfigError,
    expand_vars,
    load,
)

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = FIXTURES / "config.yaml"

VALID_ALPHA = """
    schema:
      schema_version: "1"
      id_field: post_id
      fields:
        post_id:     { type: string }
        owner:       { type: string, role: [filter, facet, sort] }
        value_score: { type: int, role: [metric] }
        summary:     { type: text, role: [search], weight: 1.0 }
        resources:   { type: "list[object]", role: [passthrough] }
    sources:
      - name: src
        adapter: ig_saved
        location: src
        mapping:
          post_id: { from: metadata.id, transform: coerce_str }
        provenance:
          source: scrape-ig-saved-list
          media_ref: dataset_post_dir
          timestamp_field: analysis.analysed_at
"""


@pytest.fixture
def corpora_dir(tmp_path: Path) -> Path:
    d = tmp_path / "corpora"
    d.mkdir()
    return d


@pytest.fixture
def config_with(corpora_dir):
    """Callable: write (name, body) corpus files into a tmp corpora dir and
    load a per-test engine config pointing at it."""

    def _config_with(*corpus_bodies: tuple[str, str]) -> Config:
        for name, body in corpus_bodies:
            (corpora_dir / f"{name}.yaml").write_text(
                textwrap.dedent(body), encoding="utf-8"
            )
        engine_cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        engine_cfg["engine"]["corpora_dir"] = str(corpora_dir)
        cfg_path = corpora_dir.parent / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(engine_cfg), encoding="utf-8")
        return load(cfg_path)

    return _config_with


# ---- Valid parse -------------------------------------------------------------


def test_valid_corpus_parses(config_with):
    cfg = config_with(("alpha", VALID_ALPHA))
    assert cfg.errors == {}
    corpus = cfg.corpus("alpha")
    assert corpus is not None
    assert corpus.schema_version == "1"
    assert corpus.id_field == "post_id"
    assert corpus.field("value_score").type == "int"
    assert corpus.field("value_score").roles == ("metric",)
    assert corpus.field("summary").weight == 1.0
    assert corpus.sources[0].provenance.source == "scrape-ig-saved-list"
    assert corpus.sources[0].provenance.timestamp_field == "analysis.analysed_at"


def test_fixture_exemplar_copy_parses(tmp_path):
    """The full fixture copy of the exemplar shape parses via the shared
    fixture config.yaml (corpora/alpha.yaml + broken.yaml present)."""
    engine_cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    engine_cfg["engine"]["corpora_dir"] = str(FIXTURES / "corpora")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(engine_cfg), encoding="utf-8")
    cfg = load(cfg_path)
    assert "alpha" in cfg.corpora
    alpha = cfg.corpora["alpha"]
    assert alpha.field("resources").roles == ("passthrough",)
    assert alpha.field("published_at").type == "datetime"
    assert alpha.sources[0].adapter == "ig_saved"
    assert alpha.sources[0].location is not None


# ---- Validation failures (fail fast, file + field + problem) -----------------


def test_unknown_type_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string }
                rating:  { type: stars }
        """),
    )
    err = cfg.errors["bad"]
    assert "bad.yaml" in err and "field 'rating'" in err and "unknown type" in err


def test_object_without_passthrough_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string }
                payload: { type: object, role: [filter] }
        """),
    )
    assert "field 'payload'" in cfg.errors["bad"]


def test_unknown_role_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string, role: [join] }
        """),
    )
    assert "unknown role" in cfg.errors["bad"] and "'join'" in cfg.errors["bad"]


def test_metric_on_non_numeric_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string }
                title:   { type: text, role: [metric] }
        """),
    )
    assert "role 'metric'" in cfg.errors["bad"] and "field 'title'" in cfg.errors["bad"]


def test_id_field_undeclared_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: nope
              fields:
                post_id: { type: string }
        """),
    )
    assert "id_field" in cfg.errors["bad"] and "nope" in cfg.errors["bad"]


def test_provenance_missing_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string }
            sources:
              - name: src
                mapping:
                  post_id: { from: id, transform: coerce_str }
        """),
    )
    assert "provenance" in cfg.errors["bad"]


def test_unknown_transform_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: string }
                owner:   { type: string }
            sources:
              - name: src
                mapping:
                  post_id: { from: id, transform: coerce_str }
                  owner:   { from: who, transform: fancy_ai_rewrite }
                provenance:
                  source: s
                  media_ref: m
                  timestamp_field: ts
        """),
    )
    assert "fancy_ai_rewrite" in cfg.errors["bad"] and "field 'owner'" in cfg.errors["bad"]


def test_missing_schema_version_fails(config_with):
    cfg = config_with(
        ("bad", """
            schema:
              id_field: post_id
              fields:
                post_id: { type: string }
        """),
    )
    assert "schema_version" in cfg.errors["bad"]


def test_raised_error_type_and_context():
    """Direct validation (not the aggregate loader) raises with full context."""
    from kb_engine.config import _parse_corpus

    bad = yaml.safe_load(
        """
        schema:
          schema_version: "1"
          id_field: post_id
          fields:
            post_id: { type: string }
            rating:  { type: stars }
        """
    )
    with pytest.raises(CorpusConfigError) as excinfo:
        _parse_corpus("bad", FIXTURES / "corpora" / "bad.yaml", bad)
    assert excinfo.value.corpus == "bad"
    assert "field 'rating'" in excinfo.value.message
    assert "bad.yaml" in str(excinfo.value)


# ---- Multi-corpus isolation ---------------------------------------------------


def test_broken_corpus_does_not_block_others(config_with):
    cfg = config_with(
        ("alpha", VALID_ALPHA),
        ("broken", """
            schema:
              schema_version: "1"
              id_field: post_id
              fields:
                post_id: { type: nope }
        """),
        ("gamma", VALID_ALPHA),
    )
    # alpha loads; broken is reported per-corpus; gamma loads too.
    assert "alpha" in cfg.corpora and "gamma" in cfg.corpora
    assert "broken" in cfg.errors
    assert "post_id" in cfg.errors["broken"]
    assert cfg.corpus("alpha").schema_version == "1"


# ---- ${VAR} resolution + relative paths ----------------------------------------


def test_expand_vars(monkeypatch):
    monkeypatch.setenv("KB_TEST_VAR", "/tmp/xyz")
    assert expand_vars("${KB_TEST_VAR}/data") == "/tmp/xyz/data"
    # Unset vars are left verbatim, not dropped.
    assert expand_vars("${KB_UNSET_VAR}/x") == "${KB_UNSET_VAR}/x"


def test_source_location_env_expansion(config_with, monkeypatch, corpora_dir):
    monkeypatch.setenv("TEST_SOURCE_ROOT", str(corpora_dir.parent))
    cfg = config_with(("alpha", VALID_ALPHA))
    src = cfg.corpus("alpha").sources[0]
    assert src.location is not None
    assert "${" not in str(src.location)
    assert str(corpora_dir.parent) in str(src.location)


# ---- Core scaffold --------------------------------------------------------------


def test_canonical_record_envelope():
    from kb_engine.core import CanonicalRecord, Provenance

    rec = CanonicalRecord(
        id="p1",
        content_hash="abc",
        provenance=Provenance(source="s", media_ref="m", timestamp="2026-01-01"),
        fields={"post_id": "p1"},
    )
    assert rec.provenance.source == "s"

    assert rec.fields["post_id"] == "p1"


def test_retriever_protocol_order_not_score():
    from kb_engine.core.contracts import RankedHit, Retriever

    hits = [RankedHit(record_id="b", score=0.9), RankedHit(record_id="a", score=0.1)]
    # Consumers depend on order + identity, never the absolute score.
    assert [h.record_id for h in hits] == ["b", "a"]

    class _R:
        def search(self, query: str, top_k: int) -> list[RankedHit]:
            return hits

    assert isinstance(_R(), Retriever)
