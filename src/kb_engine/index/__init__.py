"""kb_engine.index — chunking, index backends, embedder, retrievers (plan §6.2).

One :class:`~kb_engine.index.chunker.Chunker` contract (kills the three
divergent legacy index-text builders), pluggable index backends (BM25 via
SQLite FTS5, vectors via sqlite-vec / in-memory), an embedder behind DIP with
idempotency + cost in the contract, and one ``Retriever → RankedHit[]``
contract (lexical/dense/hybrid, LSP: order + identity only).
"""

from kb_engine.index.backends import (
    BM25FTS5Backend,
    Hit,
    IndexBackend,
    InMemoryVectorBackend,
    SQLiteVecBackend,
    VectorBackend,
)
from kb_engine.index.chunker import Chunk, Chunker
from kb_engine.index.embedder import (
    Embedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    VoyageEmbedder,
)
from kb_engine.index.retriever import (
    BM25Retriever,
    DenseRetriever,
    HybridRetriever,
    RerankConfig,
    RerankError,
    apply_rerank,
    reciprocal_rank_fusion,
)

__all__ = [
    "BM25FTS5Backend",
    "BM25Retriever",
    "Chunk",
    "Chunker",
    "DenseRetriever",
    "Embedder",
    "EmbeddingError",
    "FakeEmbedder",
    "GeminiEmbedder",
    "apply_rerank",
    "HybridRetriever",
    "IndexBackend",
    "InMemoryVectorBackend",
    "RerankConfig",
    "RerankError",
    "SQLiteVecBackend",
    "VectorBackend",
    "VoyageEmbedder",
    "reciprocal_rank_fusion",
]
