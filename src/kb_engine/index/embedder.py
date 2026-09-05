"""Embedder (plan §6.2): DIP seam with idempotency + cost in the contract.

* :class:`Embedder` — the protocol consumers depend on (never on a provider).
* :class:`GeminiEmbedder` / :class:`VoyageEmbedder` — provider adapters that
  lazy-import their SDKs; instantiation never fires a network call, so the
  engine can be imported/configured offline. Tests use
  :class:`FakeEmbedder` — NO live embedding API anywhere in the suite.
* The embed cache is keyed by ``(text_hash, model, dims)`` so identical
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

_CHARS_PER_TOKEN = 4  # rough token estimate for cost quoting


class EmbeddingError(RuntimeError):
    """Embedding provider unavailable or call failed (missing SDK/API key)."""


@runtime_checkable
class Embedder(Protocol):
    """Embedding seam. ``model`` + ``dims`` are part of the identity that
    keys the cache and the four-corner version tuple."""

    model: str
    dims: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents (chunk texts)."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed one query text (providers may apply a query prefix)."""
        ...

    def estimate_cost(self, texts: list[str]) -> dict[str, Any]:
        """Estimated input tokens + billable embeddings for a batch — cost
        is part of the embedder contract, quoteable before the call."""
        ...


def text_hash(text: str) -> str:
    """Content hash of one text (first component of the cache key)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(text: str, model: str, dims: int) -> str:
    """Documented cache key: ``(text_hash, model, dims)``."""
    return f"{text_hash(text)}::{model}::{dims}"


class FakeEmbedder:
    """Deterministic offline embedder for tests and hermetic runs.

    Maps text to a stable unit vector by hashing tokens into ``dims``
    buckets — no network, no SDK, no randomness. Records how many texts it
    actually embedded so tests can prove re-runs re-bill zero."""

    def __init__(self, dims: int = 16, model: str = "fake-embed") -> None:
        self.dims = dims
        self.model = model
        self.calls = 0  # number of embeddings actually computed (billed)

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in text.lower().split():
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dims] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def estimate_cost(self, texts: list[str]) -> dict[str, Any]:
        return {
            "model": self.model,
            "dims": self.dims,
            "texts": len(texts),
            "estimated_tokens": sum(len(t) // _CHARS_PER_TOKEN + 1 for t in texts),
            "billable_embeddings": len(texts),
        }


class CachedEmbedder:
    """Cache wrapper over any :class:`Embedder` (decorator, DIP).

    Every embedded text is stored under ``cache_key(text, model, dims)`` in
    a SQLite table (file- or memory-backed), so a re-run over unchanged
    content re-bills ZERO embeddings. ``cache_hits`` / ``cache_misses``
    expose the billing counters."""

    def __init__(self, inner: Embedder, db_path: str | Path = ":memory:") -> None:
        self.inner = inner
        self.model = inner.model
        self.dims = inner.dims
        self.cache_hits = 0
        self.cache_misses = 0
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embed_cache (
                key       TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            )
            """
        )

    def _lookup(self, key: str) -> list[float] | None:
        row = self.conn.execute(
            "SELECT embedding FROM embed_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        import struct

        return list(struct.unpack(f"<{self.dims}f", row[0]))

    def _store(self, key: str, vec: list[float]) -> None:
        import struct

        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO embed_cache VALUES (?,?)",
                (key, struct.pack(f"<{len(vec)}f", *vec)),
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [cache_key(t, self.model, self.dims) for t in texts]
        cached = [self._lookup(k) for k in keys]
        missing = [i for i, v in enumerate(cached) if v is None]
        if missing:
            fresh = self.inner.embed_documents([texts[i] for i in missing])
            for i, vec in zip(missing, fresh):
                self._store(keys[i], vec)
                cached[i] = vec
        self.cache_hits += len(texts) - len(missing)
        self.cache_misses += len(missing)
        return [list(v) for v in cached]  # type: ignore[arg-type]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def estimate_cost(self, texts: list[str]) -> dict[str, Any]:
        keys = [cache_key(t, self.model, self.dims) for t in texts]
        cached_n = sum(1 for k in keys if self._lookup(k) is not None)
        return {
            **self.inner.estimate_cost(texts),
            "cache_keyed_by": "(text_hash, model, dims)",
            "already_cached": cached_n,
            "billable_embeddings": len(texts) - cached_n,
        }


class GeminiEmbedder:
    """gemini-embedding provider adapter (lazy SDK import; never imports at
    module load so offline configure stays possible)."""

    def __init__(
        self,
        model: str = "gemini-embedding-2",
        dims: int = 768,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.dims = dims
        self._api_key = api_key

    def _client(self) -> Any:
        try:
            from google import genai  # noqa: PLC0415 - deliberate lazy import
        except ImportError as exc:
            raise EmbeddingError(
                "google-genai SDK not installed; add it or use a fake/test embedder"
            ) from exc
        key = self._api_key or __import__("os").environ.get("GEMINI_API_KEY")
        if not key:
            raise EmbeddingError("GEMINI_API_KEY not set; embeddings unavailable")
        return genai.Client(api_key=key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._client()
        resp = client.models.embed_content(model=self.model, contents=texts)
        return [list(e.values) for e in resp.embeddings]  # type: ignore[attr-defined]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def estimate_cost(self, texts: list[str]) -> dict[str, Any]:
        return {
            "provider": "gemini",
            "model": self.model,
            "dims": self.dims,
            "texts": len(texts),
            "estimated_tokens": sum(len(t) // _CHARS_PER_TOKEN + 1 for t in texts),
        }


class VoyageEmbedder:
    """Voyage provider adapter (lazy SDK import; query/document input types)."""

    def __init__(
        self,
        model: str = "voyage-3",
        dims: int = 1024,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.dims = dims
        self._api_key = api_key

    def _client(self) -> Any:
        try:
            import voyageai  # noqa: PLC0415 - deliberate lazy import
        except ImportError as exc:
            raise EmbeddingError(
                "voyageai SDK not installed; add it or use a fake/test embedder"
            ) from exc
        key = self._api_key or __import__("os").environ.get("VOYAGE_API_KEY")
        if not key:
            raise EmbeddingError("VOYAGE_API_KEY not set; embeddings unavailable")
        return voyageai.Client(api_key=key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        r = self._client().embeddings.create(texts, model=self.model, input_type="document")
        return [list(e) for e in r.embeddings]  # type: ignore[attr-defined]

    def embed_query(self, text: str) -> list[float]:
        r = self._client().embeddings.create([text], model=self.model, input_type="query")
        return list(r.embeddings[0])

    def estimate_cost(self, texts: list[str]) -> dict[str, Any]:
        return {
            "provider": "voyage",
            "model": self.model,
            "dims": self.dims,
            "texts": len(texts),
            "estimated_tokens": sum(len(t) // _CHARS_PER_TOKEN + 1 for t in texts),
        }
