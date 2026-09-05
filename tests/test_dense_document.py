"""Document-level dense (M4 parity): document_text + DocumentDenseRetriever.

M4 (kb/dense.py) embedded ONE document blob per record via index_text —
summary + workflow_steps + tips + concepts(term: explanation) + transcript +
tools_apps + tags + resources("name — purpose"), newline-joined. These tests
pin the composition and the one-vector-per-record retrieval granularity.
All hermetic: FakeEmbedder / CachedEmbedder, no live API.
"""

from __future__ import annotations

import json
from pathlib import Path

from kb_engine.config import load
from kb_engine.core.contracts import RankedHit
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord
from kb_engine.index import (
    DocumentDenseRetriever,
    FakeEmbedder,
    InMemoryVectorBackend,
    document_text,
)
from kb_engine.index.document import search_fields

FIXTURES = Path(__file__).parent / "fixtures" / "index"
ROOT = Path(__file__).parents[1]


def load_fixture_records() -> list[CanonicalRecord]:
    raw = json.loads((FIXTURES / "corpus_records.json").read_text(encoding="utf-8"))
    return [_to_record(item) for item in raw]


def _to_record(item: dict) -> CanonicalRecord:
    prov = item["provenance"]
    return CanonicalRecord(
        id=item["id"],
        content_hash=item["content_hash"],
        provenance=Provenance(
            source=prov["source"],
            media_ref=prov["media_ref"] or "",
            timestamp=prov["timestamp"],
            extractor=prov["extractor"],
            confidence=prov["confidence"],
        ),
        fields=dict(item["fields"]),
    )


FIELDS = ["summary", "workflow_steps", "tips", "concepts", "transcript",
          "tools_apps", "tags", "resources_text"]


def make_record(fields: dict) -> CanonicalRecord:
    return CanonicalRecord(
        id="p1",
        content_hash="h",
        provenance=Provenance("s", "", "t", "e", None),
        fields=fields,
    )


def make_doc_retriever(
    records: list[CanonicalRecord], dims: int = 32
) -> tuple[DocumentDenseRetriever, FakeEmbedder, InMemoryVectorBackend]:
    embedder = FakeEmbedder(dims=dims)
    backend = InMemoryVectorBackend()
    retr = DocumentDenseRetriever(backend, embedder, FIELDS)
    retr.build(records)
    return retr, embedder, backend


# ---- document_text composition ------------------------------------------------


class TestDocumentText:
    def test_one_blob_per_record_declared_order(self) -> None:
        rec = make_record({
            "summary": "Sum line",
            "transcript": "Words here",
            "workflow_steps": ["Step one", "Step two"],
            "tips": ["Tip A", "Tip B"],
            "concepts": ["contrast", "hierarchy"],
            "tools_apps": ["Figma", "Notion"],
            "tags": ["layout"],
            "resources_text": None,
        })
        text = document_text(rec, FIELDS)
        lines = text.split("\n")
        assert lines == [
            "Sum line",          # declared order: summary first
            "Step one", "Step two",
            "Tip A", "Tip B",
            "contrast", "hierarchy",
            "Words here",
            "Figma", "Notion",
            "layout",
        ]

    def test_legacy_concepts_term_explanation(self) -> None:
        rec = make_record({
            "concepts": [
                {"term": "white space", "explanation": "breathing room"},
                {"term": "balance"},
            ],
        })
        assert document_text(rec, ["concepts"]) == (
            "white space: breathing room\nbalance"
        )

    def test_legacy_resources_name_purpose(self) -> None:
        rec = make_record({
            "resources_text": None,
            "resources": [{"name": "Figma file", "purpose": "reference"}],
        })
        # resources_text is the declared flattened search representation; a
        # bare legacy-style dict list in a search field also flattens the
        # legacy "name — purpose" way.
        assert document_text(rec, ["resources_text"]) == ""
        rec2 = make_record({"search_blob": [
            {"name": "Figma file", "purpose": "reference"},
        ]})
        assert document_text(rec2, ["search_blob"]) == "Figma file — reference"

    def test_empty_and_missing_fields_dropped(self) -> None:
        rec = make_record({
            "summary": "",
            "transcript": None,
            "tags": [],
            "tips": ["only one"],
        })
        assert document_text(rec, FIELDS) == "only one"
        assert document_text(make_record({}), FIELDS) == ""


# ---- DocumentDenseRetriever: one vector per record -----------------------------


class TestDocumentDenseRetriever:
    def test_embeds_one_vector_per_record(self) -> None:
        records = load_fixture_records()
        retr, embedder, backend = make_doc_retriever(records)
        assert embedder.calls == len(records)          # billed once per record
        assert len(backend._vectors) == len(records)   # one vector, not 346 chunks

    def test_retrieval_best_first_and_record_level(self) -> None:
        records = [
            make_record({"summary": "typography spacing rhythm"}),
            make_record({"summary": "color palette systems"}),
            make_record({"summary": "grid layout alignment"}),
        ]
        for i, rec in enumerate(records):
            records[i] = CanonicalRecord(
                id=f"p{i}", content_hash="h", provenance=rec.provenance,
                fields=dict(rec.fields),
            )
        retr, _, _ = make_doc_retriever(records, dims=256)
        hits = retr.search("palette color systems", top_k=3)
        # p1 matches exactly; p0/p2 tie at 0.0 and break on record_id.
        assert [h.record_id for h in hits] == ["p1", "p0", "p2"]
        assert hits[0].score > 0.99 and hits[1].score == 0.0
        assert all(isinstance(h, RankedHit) for h in hits)
        assert all(h.chunk_id.startswith(f"{h.record_id}::__document__::0")
                   for h in hits)

    def test_rebuild_is_idempotent(self) -> None:
        records = load_fixture_records()
        retr, embedder, _ = make_doc_retriever(records)
        calls_after_first = embedder.calls
        retr.build(records)  # same texts → re-embed, backend replaces per record id
        assert embedder.calls == calls_after_first * 1 + len(records)
        assert len(backend_vectors(retr)) == len(records)

    def test_cache_reuses_identical_document_texts(self) -> None:
        from kb_engine.index.embedder import CachedEmbedder

        records = load_fixture_records()
        inner = FakeEmbedder(dims=16)
        cache = CachedEmbedder(inner)
        backend = InMemoryVectorBackend()
        retr = DocumentDenseRetriever(backend, cache, FIELDS)
        retr.build(records)
        miss_1 = cache.cache_misses
        assert miss_1 == len(records)

        # Fresh retriever, identical records → every document text is a hit.
        backend2 = InMemoryVectorBackend()
        retr2 = DocumentDenseRetriever(backend2, cache, FIELDS)
        retr2.build(load_fixture_records())
        assert cache.cache_misses == miss_1        # zero new billing
        assert cache.cache_hits == miss_1

    def test_from_corpus_declares_search_fields_in_order(self, tmp_path) -> None:
        config = load(ROOT / "config.yaml")
        corpus = config.corpus("uiux")
        assert "summary" in search_fields(corpus)
        fields = search_fields(corpus)
        assert fields[0] == "summary"
        assert set(fields) >= {
            "summary", "transcript", "workflow_steps", "tips", "concepts",
            "caption", "tools_apps", "tags", "resources_text",
        }

    def test_canonical_uiux_yields_one_document_text_per_record(self) -> None:
        corpus_json = ROOT / "user_data" / "canonical" / "uiux" / "corpus.json"
        records = [
            _to_record(item)
            for item in json.loads(corpus_json.read_text(encoding="utf-8"))
        ]
        config = load(ROOT / "config.yaml")
        fields = search_fields(config.corpus("uiux"))
        texts = [document_text(r, fields) for r in records]
        assert len(records) == 86
        assert len(texts) == 86                      # one document per record
        assert any(texts)                            # real content, not all-empty


def backend_vectors(retr: DocumentDenseRetriever) -> list:
    return retr.backend.retrieve_vectors([0.0] * retr.embedder.dims, top_k=10**6)
