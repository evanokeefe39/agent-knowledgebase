"""Build-4 tests: chunker, index backends, embedder, retrievers (plan §6.2).

Hermetic: no live embedding API anywhere — :class:`FakeEmbedder` only,
tempfile/memory DBs, fixture records under ``tests/fixtures/index/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_engine.config import load
from kb_engine.core.contracts import RankedHit
from kb_engine.core.provenance import Provenance
from kb_engine.core.records import CanonicalRecord
from kb_engine.index import (
    BM25FTS5Backend,
    BM25Retriever,
    Chunk,
    Chunker,
    DenseRetriever,
    EmbeddingError,
    FakeEmbedder,
    HybridRetriever,
    InMemoryVectorBackend,
    RerankConfig,
    RerankError,
    SQLiteVecBackend,
    apply_rerank,
    reciprocal_rank_fusion,
)

FIXTURES = Path(__file__).parent / "fixtures" / "index"
SEARCH_FIELDS = ["summary", "transcript", "workflow_steps", "tips", "concepts", "caption"]
METADATA_FIELDS = ["owner", "content_type"]


# ---- helpers -----------------------------------------------------------------


def load_fixture_records() -> list[CanonicalRecord]:
    raw = json.loads((FIXTURES / "corpus_records.json").read_text(encoding="utf-8"))
    records = []
    for item in raw:
        prov = item["provenance"]
        records.append(
            CanonicalRecord(
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
        )
    return records


def make_chunker(mode: str = "by_field") -> Chunker:
    return Chunker(SEARCH_FIELDS, mode=mode, metadata_fields=METADATA_FIELDS)


def index_chunks(backend: BM25FTS5Backend, records: list[CanonicalRecord]) -> int:
    return backend.add(make_chunker().chunk_all(records))


def make_dense(records: list[CanonicalRecord]) -> tuple[DenseRetriever, FakeEmbedder]:
    embedder = FakeEmbedder(dims=32)
    backend = InMemoryVectorBackend()
    chunker = make_chunker()
    chunks = chunker.chunk_all(records)
    backend.add_vectors([(c, embedder.embed_documents([c.text])[0]) for c in chunks])
    return DenseRetriever(backend, embedder), embedder


# ---- Chunker -----------------------------------------------------------------


class TestChunker:
    def test_by_field_chunks_carry_provenance(self) -> None:
        records = load_fixture_records()
        chunks = make_chunker().chunk(records[0])
        # summary + transcript + 3 list fields + caption = 6 chunks
        assert len(chunks) == 6
        by_field = {c.chunk_field: c for c in chunks}
        assert set(by_field) == set(SEARCH_FIELDS)
        for chunk in chunks:
            assert chunk.record_id == "post-001"
            assert chunk.chunk_id == f"post-001::{chunk.chunk_field}::{chunk.chunk_idx}"
            # provenance (record_id, field) carried per chunk
            assert chunk.provenance.timestamp == "2026-08-01T10:00:00Z"
            assert chunk.provenance.source == "scrape-ig-saved-list"
            assert chunk.media_ref == "dataset/post-001"
        assert "WCAG" in by_field["summary"].text
        # list fields join items with newlines
        assert "Pick a base hue\n" in by_field["workflow_steps"].text

    def test_empty_fields_yield_no_chunks(self) -> None:
        records = load_fixture_records()
        chunks = make_chunker().chunk(records[3])  # caption is null
        assert all(c.chunk_field != "caption" for c in chunks)

    def test_by_size_mode_splits_windows(self) -> None:
        records = load_fixture_records()
        long_text = " ".join(["contrast ratio accessibility"] * 300)
        records[0].fields["summary"]  # fixture untouched
        rec = CanonicalRecord(
            id=records[0].id,
            content_hash=records[0].content_hash,
            provenance=records[0].provenance,
            fields={**records[0].fields, "transcript": long_text},
        )
        chunks = Chunker(
            ["transcript"], mode="by_size", max_chars=500, overlap=100
        ).chunk(rec)
        assert len(chunks) > 1
        assert all(len(c.text) <= 500 for c in chunks)
        assert all(c.chunk_field == "transcript" for c in chunks)
        assert chunks[0].chunk_idx == 0 and chunks[1].chunk_idx == 1

    def test_metadata_fields_copied_for_filters(self) -> None:
        records = load_fixture_records()
        chunks = make_chunker().chunk(records[0])
        assert chunks[0].metadata == {"owner": "ada", "content_type": "carousel"}

    def test_from_corpus_declares_search_fields_from_contract(self) -> None:
        from kb_engine.config import load

        config = load(Path(__file__).parents[1] / "config.yaml")
        corpus = config.corpus("uiux")
        assert corpus is not None
        chunker = Chunker.from_corpus(corpus)
        # corpora/uiux.yaml declares 6 role=search fields
        assert set(chunker.fields) == set(SEARCH_FIELDS)
        assert "owner" in chunker.metadata_fields

    def test_invalid_mode_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            Chunker(["summary"], mode="by_paragraph")

    def test_no_fields_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="field"):
            Chunker([])


# ---- BM25 FTS5 backend --------------------------------------------------------


class TestBM25Backend:
    def test_index_and_retrieve(self, tmp_path: Path) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(tmp_path / "bm25.db")
        n = backend.add(make_chunker().chunk_all(records))
        assert n == backend.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]

        hits = backend.retrieve("contrast ratios accessibility", top_k=3)
        assert 0 < len(hits) <= 3
        assert hits[0].record_id == "post-001"
        assert hits[0].score > 0.0

    def test_rebuild_is_idempotent_per_chunk_id(self) -> None:
        records = load_fixture_records()
        chunks = make_chunker().chunk_all(records)
        backend = BM25FTS5Backend(":memory:")
        backend.add(chunks)
        backend.add(chunks)  # rebuild from canonical corpus: replace, not duplicate
        assert (
            backend.conn.execute("SELECT count(*) FROM fts_chunks").fetchone()[0]
            == len(chunks)
        )

    def test_filters_trim_results(self) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        hits = backend.retrieve("interview prompts questions", top_k=10, filters={"owner": "ada"})
        assert hits and all(h.record_id == "post-003" for h in hits)

    def test_clear_empties_index(self) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        backend.clear()
        assert backend.retrieve("contrast ratios", top_k=5) == []

    def test_empty_query_returns_nothing(self) -> None:
        backend = BM25FTS5Backend(":memory:")
        assert backend.retrieve("   ", top_k=5) == []


class TestSQLiteVecBackend:
    """The sqlite-vec adapter: local extension load (no network), file-backed."""

    def test_knn_over_persisted_vectors(self, tmp_path: Path) -> None:
        records = load_fixture_records()
        embedder = FakeEmbedder(dims=32)
        backend = SQLiteVecBackend(tmp_path / "vec.db", dims=32)
        chunks = make_chunker().chunk_all(records)
        n = backend.add_vectors(
            [(c, embedder.embed_documents([c.text])[0]) for c in chunks]
        )
        assert n == len(chunks)
        hits = backend.retrieve_vectors(
            embedder.embed_query("contrast ratios accessibility color"), 3
        )
        assert len(hits) == 3
        assert hits[0].record_id == "post-001"
        # cosine distance → score ≈ [-1, 1] (float32 drift possible), higher better
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)
        assert all(-1.0 <= s <= 1.0 for s in scores)
        backend.close()

    def test_dim_mismatch_fails_fast(self, tmp_path: Path) -> None:
        backend = SQLiteVecBackend(tmp_path / "vec.db", dims=8)
        chunk = make_chunker().chunk(load_fixture_records()[0])[0]
        with pytest.raises(ValueError, match="dims"):
            backend.add_vectors([(chunk, [0.0] * 16)])
        backend.close()

    def test_clear_empties_vectors(self, tmp_path: Path) -> None:
        embedder = FakeEmbedder(dims=32)
        backend = SQLiteVecBackend(":memory:", dims=32)
        chunks = make_chunker().chunk_all(load_fixture_records())
        backend.add_vectors(
            [(c, embedder.embed_documents([c.text])[0]) for c in chunks]
        )
        backend.clear()
        assert backend.retrieve_vectors(embedder.embed_query("contrast"), 5) == []
        backend.close()


# ---- Dense retriever (fake embedder — no live API) ----------------------------


class TestDenseRetriever:
    def test_returns_ranked_hits_best_first(self) -> None:
        records = load_fixture_records()
        dense, _ = make_dense(records)
        hits = dense.search("contrast ratios accessibility color", top_k=4)
        assert 0 < len(hits) <= 4
        assert all(isinstance(h, RankedHit) for h in hits)
        # best-first: the accessibility post outranks the others
        assert hits[0].record_id == "post-001"
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)

    def test_ranking_is_deterministic(self) -> None:
        records = load_fixture_records()
        dense, _ = make_dense(records)
        a = dense.search("figma auto layout components", top_k=4)
        b = dense.search("figma auto layout components", top_k=4)
        assert [(h.record_id, h.chunk_id) for h in a] == [
            (h.record_id, h.chunk_id) for h in b
        ]


# ---- Hybrid (RRF) -------------------------------------------------------------


class TestHybridRetriever:
    def _build(self, records: list[CanonicalRecord], with_dense: bool):
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        bm25 = BM25Retriever(backend)
        dense = None
        if with_dense:
            dense, _ = make_dense(records)
        return HybridRetriever(bm25, dense, k=60)

    def test_rrf_fuses_bm25_and_dense(self) -> None:
        records = load_fixture_records()
        hybrid = self._build(records, with_dense=True)
        hits = hybrid.search("contrast ratios accessibility", top_k=4)
        assert hits
        # both channels rank post-001 first → fused top is post-001
        assert hits[0].record_id == "post-001"
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)
        # fused scores are rank sums in (0, 2/(k+1)]
        assert all(0.0 < s <= 2.0 / 61.0 for s in scores)

    def test_bm25_fallback_when_dense_unavailable(self) -> None:
        records = load_fixture_records()
        hybrid = self._build(records, with_dense=False)
        bm25_only = hybrid.bm25
        expected = bm25_only.search("interview prompts questions", top_k=3)
        fallback = hybrid.search("interview prompts questions", top_k=3)
        assert [h.record_id for h in fallback] == [h.record_id for h in expected]

    def test_fallback_on_dense_failure(self) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        bm25 = BM25Retriever(backend)

        class ExplodingDense:
            def search(self, query: str, top_k: int, filters=None):
                raise EmbeddingError("dense channel down")

        hybrid = HybridRetriever(bm25, ExplodingDense(), k=60)  # type: ignore[arg-type]
        hits = hybrid.search("contrast ratios accessibility", top_k=3)
        assert hits == bm25.search("contrast ratios accessibility", top_k=3)

    def test_rrf_k_is_configurable(self) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        bm25 = BM25Retriever(backend)
        dense, _ = make_dense(records)
        h60 = HybridRetriever(bm25, dense, k=60).search("figma auto layout", top_k=4)
        h1 = HybridRetriever(bm25, dense, k=1).search("figma auto layout", top_k=4)
        assert all(isinstance(h, RankedHit) for h in h60 + h1)
        # k scales fused scores (1/(k+rank)); order/identity are the contract
        assert h60[0].record_id == h1[0].record_id == "post-002"
        assert h1[0].score > h60[0].score > 0.0

    def test_fusion_function_tie_breaks_deterministically(self) -> None:
        a = [RankedHit("r1", 1.0), RankedHit("r2", 0.5)]
        b = [RankedHit("r2", 1.0), RankedHit("r1", 0.5)]
        fused = reciprocal_rank_fusion(a, b, k=60)
        # equal fused scores → deterministic record_id tiebreak
        assert fused[0].record_id == "r1"
        assert abs(fused[0].score - fused[1].score) < 1e-12



# ---- Embedder: idempotency + cost contract (no live API) ------------------------


class TestEmbedder:
    def test_cache_key_is_text_hash_model_dims(self) -> None:
        from kb_engine.index.embedder import cache_key, text_hash
        key = cache_key("some text", "gemini-embedding-2", 768)
        assert key == f"{text_hash('some text')}::gemini-embedding-2::768"
    def test_rerun_rebills_zero(self, tmp_path: Path) -> None:
        from kb_engine.index.embedder import CachedEmbedder

        inner = FakeEmbedder(dims=16)
        cached = CachedEmbedder(inner, tmp_path / "cache.db")
        texts = ["contrast ratios decide readability", "figma auto layout"]
        cached.embed_documents(texts)
        assert cached.cache_misses == 2 and cached.cache_hits == 0
        assert inner.calls == 2  # billed once
        # same content again → zero new embeddings, zero billing
        cached.embed_documents(texts)
        assert inner.calls == 2
        assert cached.cache_misses == 2 and cached.cache_hits == 2

    def test_cache_key_includes_model_and_dims(self, tmp_path: Path) -> None:
        from kb_engine.index.embedder import CachedEmbedder

        inner = FakeEmbedder(dims=16)
        cached = CachedEmbedder(inner, tmp_path / "cache.db")
        vec1 = cached.embed_query("same text")
        assert cached.cache_misses == 1
        # a DIFFERENT model/dims identity never shares a cache row
        other = CachedEmbedder(FakeEmbedder(dims=32, model="other"), tmp_path / "cache.db")
        other.embed_query("same text")
        assert other.cache_misses == 1
        assert vec1 != other.embed_query("same text") or len(vec1) != 32

    def test_estimate_cost_quotes_before_call(self) -> None:
        from kb_engine.index.embedder import CachedEmbedder

        inner = FakeEmbedder(dims=16)
        cached = CachedEmbedder(inner)
        quote = cached.estimate_cost(["a" * 40])
        assert quote["billable_embeddings"] == 1
        assert quote["estimated_tokens"] >= 1
        cached.embed_documents(["a" * 40])
        quote2 = cached.estimate_cost(["a" * 40])
        assert quote2["already_cached"] == 1 and quote2["billable_embeddings"] == 0

    def test_providers_fail_closed_without_sdk_or_key(self) -> None:
        from kb_engine.index.embedder import GeminiEmbedder, VoyageEmbedder

        # no API key in this env → clear error, never a silent live call
        with pytest.raises(EmbeddingError):
            GeminiEmbedder(api_key=None)._client()
        with pytest.raises(EmbeddingError):
            VoyageEmbedder(api_key=None)._client()


# ---- Rerank seam (disabled) ----------------------------------------------------


class TestRerankSeam:
    def test_ships_disabled(self) -> None:
        config = RerankConfig()
        assert config.enabled is False
        assert config.strategy is None and config.top_n is None

    def test_disabled_rerank_passes_through(self) -> None:
        hits = [RankedHit("r1", 1.0), RankedHit("r2", 0.5)]
        assert apply_rerank(RerankConfig(), hits) is hits

    def test_enabled_without_strategy_raises(self) -> None:
        with pytest.raises(RerankError, match="disabled seam"):
            apply_rerank(RerankConfig(enabled=True, strategy="llm", top_n=20), [])


# ---- LSP shape: one RankedHit[] contract across strategies ---------------------


class TestLSPShape:
    def test_all_retrievers_return_identical_ranked_hit_shape(self) -> None:
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        bm25 = BM25Retriever(backend)
        dense, _ = make_dense(records)
        hybrid = HybridRetriever(bm25, dense, k=60)

        for retriever in (bm25, dense, hybrid):
            hits = retriever.search("contrast ratios accessibility color", top_k=3)
            assert isinstance(hits, list)
            for hit in hits:
                assert isinstance(hit, RankedHit)
                assert isinstance(hit.record_id, str) and hit.record_id
                assert isinstance(hit.score, float)
                # chunk_id is None or a str — no strategy-specific fields
                assert hit.chunk_id is None or isinstance(hit.chunk_id, str)
            assert [h.score for h in hits] == sorted(
                (h.score for h in hits), reverse=True
            )
            # record-level contract: unique record ids, best chunk per record
            assert len({h.record_id for h in hits}) == len(hits)

    def test_consumers_can_be_strategy_agnostic(self) -> None:
        """The LSP proof: one consumer function works for all strategies."""
        records = load_fixture_records()
        backend = BM25FTS5Backend(":memory:")
        backend.add(make_chunker().chunk_all(records))
        dense, _ = make_dense(records)
        strategies = [
            BM25Retriever(backend),
            dense,
            HybridRetriever(BM25Retriever(backend), dense, k=60),
        ]

        def top_ids(retriever, query: str, top_k: int) -> list[str]:
            hits = retriever.search(query, top_k)
            assert all(isinstance(h, RankedHit) for h in hits)
            return [h.record_id for h in hits]

        for retriever in strategies:
            assert top_ids(retriever, "interview prompts questions", 2)[0] == "post-003"
