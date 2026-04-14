"""Pluggable embedding provider.

Default provider is **disabled** — returns no vectors. That lets `recall()`
work end-to-end with BM25 + recency alone (no heavy deps required). When
the user wants semantic search, they can opt in by setting an environment
variable or installing a provider; see :func:`get_provider`.

Providers must implement:
- ``dim`` property (int or None while disabled)
- ``embed(texts: list[str]) -> list[list[float] | None]``

Disabled providers return a list of ``None`` of matching length — callers
must handle this.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dim(self) -> Optional[int]: ...

    @property
    def enabled(self) -> bool:
        return self.dim is not None

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Optional[list[float]]]: ...


class DisabledProvider(EmbeddingProvider):
    """No-op provider. ``enabled`` is False; used when nothing is configured."""

    @property
    def dim(self) -> Optional[int]:
        return None

    def embed(self, texts: list[str]) -> list[Optional[list[float]]]:
        return [None] * len(texts)


class SentenceTransformersProvider(EmbeddingProvider):
    """Local sentence-transformers provider. Loaded lazily."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None
        self._dim: Optional[int] = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers not installed; set IRIS_EMBED_PROVIDER=disabled "
                "or `uv add sentence-transformers`"
            ) from e
        self._model = SentenceTransformer(self._model_name)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    @property
    def dim(self) -> Optional[int]:
        if self._dim is None:
            try:
                self._load()
            except RuntimeError:
                return None
        return self._dim

    def embed(self, texts: list[str]) -> list[Optional[list[float]]]:
        if not texts:
            return []
        self._load()
        vecs = self._model.encode(texts, normalize_embeddings=True)  # type: ignore
        return [list(map(float, v)) for v in vecs]


_PROVIDER_SINGLETON: Optional[EmbeddingProvider] = None


def get_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (cached).

    Selection via ``IRIS_EMBED_PROVIDER`` env var:
    - ``disabled`` (default): DisabledProvider
    - ``sentence-transformers``: SentenceTransformersProvider
    """
    global _PROVIDER_SINGLETON
    if _PROVIDER_SINGLETON is not None:
        return _PROVIDER_SINGLETON
    name = os.environ.get("IRIS_EMBED_PROVIDER", "disabled").strip().lower()
    if name in ("", "disabled", "none", "off"):
        _PROVIDER_SINGLETON = DisabledProvider()
    elif name in ("st", "sentence-transformers", "sbert"):
        _PROVIDER_SINGLETON = SentenceTransformersProvider()
    else:
        raise ValueError(f"unknown IRIS_EMBED_PROVIDER={name!r}")
    return _PROVIDER_SINGLETON


def reset_provider_for_tests() -> None:
    global _PROVIDER_SINGLETON
    _PROVIDER_SINGLETON = None
