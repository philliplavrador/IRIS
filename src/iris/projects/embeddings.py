"""Embedding provider abstraction (REVAMP Task 11.3, spec §14.2).

Wraps the "turn a string into a float vector" step behind a tiny
interface so the embedding backend can be swapped (local
sentence-transformers, remote Ollama, test stubs) without touching the
worker or the retrieval layer.

The two shipped implementations are:

- :class:`SentenceTransformerProvider` — local, CPU-friendly, 384-dim by
  default (``all-MiniLM-L6-v2``). Matches the vec dimension declared in
  ``migrations/v2.sql``.
- :class:`OllamaProvider` — calls a locally running Ollama instance's
  embedding endpoint. Default model ``nomic-embed-text`` produces
  768-dim vectors, so projects using this provider must re-create the
  vec0 virtual tables with the correct dimension.

Configuration lands in ``configs/config.toml`` under ``[memory.embeddings]``::

    [memory.embeddings]
    provider = "sentence-transformer"   # or "ollama"
    model    = "all-MiniLM-L6-v2"       # provider-specific
    # ollama only
    base_url = "http://localhost:11434"

:func:`load_provider` reads that table and returns an instance. Both
providers import their heavy deps lazily so ``iris.projects.embeddings``
stays importable on a minimal install.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Final

__all__ = [
    "EMBEDDING_DEFAULT_DIM",
    "EmbeddingProvider",
    "OllamaProvider",
    "SentenceTransformerProvider",
    "load_provider",
]

EMBEDDING_DEFAULT_DIM: Final[int] = 384


class EmbeddingProvider(ABC):
    """Abstract embedding backend. Implementations must be stateless."""

    #: Dimension of the output vectors. Must match the vec0 virtual-table
    #: declaration for the project whose DB receives the vectors.
    dim: int

    #: Human-readable identifier written into ``memory_entries.embedding_model``
    #: (or the equivalent operations field) for audit + staleness checks.
    model: str

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input string."""

    def embed_one(self, text: str) -> list[float]:
        """Convenience wrapper around :meth:`embed` for single strings."""
        return self.embed([text])[0]


class SentenceTransformerProvider(EmbeddingProvider):
    """Local embeddings via ``sentence-transformers``.

    Default model ``all-MiniLM-L6-v2`` produces 384-dim vectors and runs
    comfortably on CPU. The model is loaded lazily on the first
    :meth:`embed` call so import-time cost stays near zero.
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2", dim: int | None = None) -> None:
        self.model = model
        self.dim = dim if dim is not None else EMBEDDING_DEFAULT_DIM
        self._impl: Any | None = None

    def _load(self) -> Any:
        if self._impl is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - trivial
                raise RuntimeError(
                    "sentence-transformers not installed; run "
                    "`uv add sentence-transformers` or pick a different provider"
                ) from exc
            self._impl = SentenceTransformer(self.model)
        return self._impl

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(list(texts), convert_to_numpy=True, show_progress_bar=False)
        return [list(map(float, v)) for v in vectors]


class OllamaProvider(EmbeddingProvider):
    """Remote embeddings via a local Ollama server.

    Ollama exposes ``POST {base_url}/api/embeddings`` with body
    ``{"model": "...", "prompt": "..."}``. Default model
    ``nomic-embed-text`` produces 768-dim vectors — callers must ensure
    the project's vec0 table was created with ``embedding float[768]``.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        dim: int = 768,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            import json as _json
            import urllib.request
        except ImportError as exc:  # pragma: no cover - stdlib
            raise RuntimeError("urllib/json missing") from exc

        out: list[list[float]] = []
        for text in texts:
            payload = _json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
            vec = body.get("embedding")
            if not isinstance(vec, list):
                raise RuntimeError(f"ollama returned no embedding: {body!r}")
            out.append([float(x) for x in vec])
        return out


def load_provider(config: dict[str, Any] | None = None) -> EmbeddingProvider:
    """Return an :class:`EmbeddingProvider` built from ``[memory.embeddings]``.

    ``config`` is the resolved ``[memory.embeddings]`` table. When ``None``
    or empty, defaults to :class:`SentenceTransformerProvider` with the
    384-dim V2 model.
    """
    cfg = dict(config or {})
    provider_name = str(cfg.pop("provider", "sentence-transformer")).lower()
    model = cfg.pop("model", None)

    if provider_name in {"sentence-transformer", "sentence-transformers", "st"}:
        return SentenceTransformerProvider(
            model=model or "all-MiniLM-L6-v2",
            dim=cfg.get("dim"),
        )
    if provider_name == "ollama":
        return OllamaProvider(
            model=model or "nomic-embed-text",
            base_url=cfg.get("base_url", "http://localhost:11434"),
            dim=int(cfg.get("dim", 768)),
        )
    raise ValueError(f"unknown embedding provider {provider_name!r}")
