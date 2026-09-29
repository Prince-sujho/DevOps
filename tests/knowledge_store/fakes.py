"""Embeddings double: knowledge_store/sessions tests are about the graph, not
Gemini.
"""

from __future__ import annotations

from typing import Sequence

EMBEDDING_DIMENSIONS = 8


class FakeEmbeddings:
    """In-memory stand-in for GeminiEmbeddingClient.embed_documents."""

    async def embed_documents(self, parts: Sequence) -> list[list[float]]:
        """Return one fixed, deterministic vector per part.

        Args:
            parts: the content parts to embed.
        Returns:
            One EMBEDDING_DIMENSIONS-length zero vector per part.
        Raises:
            None.
        """
        return [[0.0] * EMBEDDING_DIMENSIONS for _ in parts]
