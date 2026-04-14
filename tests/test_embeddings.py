"""Tests for ``iris.projects.embeddings`` — provider abstraction."""

from __future__ import annotations

import pytest

from iris.projects.embeddings import (
    EMBEDDING_DEFAULT_DIM,
    EmbeddingProvider,
    OllamaProvider,
    SentenceTransformerProvider,
    load_provider,
)


def test_sentence_transformer_default_dim() -> None:
    p = SentenceTransformerProvider()
    assert p.dim == EMBEDDING_DEFAULT_DIM
    assert p.model == "all-MiniLM-L6-v2"


def test_sentence_transformer_embed_empty() -> None:
    p = SentenceTransformerProvider()
    assert p.embed([]) == []


def test_ollama_default_dim() -> None:
    p = OllamaProvider()
    assert p.dim == 768
    assert p.model == "nomic-embed-text"
    assert p.base_url.startswith("http")


def test_load_provider_defaults_to_sentence_transformer() -> None:
    p = load_provider()
    assert isinstance(p, SentenceTransformerProvider)
    assert p.dim == EMBEDDING_DEFAULT_DIM


def test_load_provider_selects_ollama() -> None:
    p = load_provider({"provider": "ollama", "model": "custom-embed", "dim": 512})
    assert isinstance(p, OllamaProvider)
    assert p.model == "custom-embed"
    assert p.dim == 512


def test_load_provider_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown embedding provider"):
        load_provider({"provider": "not-a-backend"})


def test_provider_is_abstract() -> None:
    # Can't instantiate the ABC directly — subclasses must implement embed.
    with pytest.raises(TypeError):
        EmbeddingProvider()  # type: ignore[abstract]
