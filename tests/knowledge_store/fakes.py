"""Embeddings double: knowledge_store/sessions tests are about the graph, not Gemini."""

from __future__ import annotations

from typing import Sequence

EMBEDDING_DIMENSIONS = 8


class FakeEmbeddings:
    """In-memory stand-in for GeminiEmbeddingClient.embed_documents."""

    async def embed_documents(self, parts: Sequence) -> list[list[float]]:
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in parts]
