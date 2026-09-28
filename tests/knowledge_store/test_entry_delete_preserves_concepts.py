"""Deleting an entry never deletes the concepts it covered.

Oracle: knowledge_store/graph/builder.py — "Concepts are subject-owned (no
entry_id) and reaped only by GC." infra.knowledge.queries.writer.DELETE_ENTRY_NODES
matches only entry-owned nodes, so removing one textbook must not erase a
concept a second textbook also covers.
"""

from __future__ import annotations

import pytest

from infra.knowledge.types import GraphRows
from infra.knowledge.writer import delete_entry_nodes, write_rows

from .conftest import node_props

pytestmark = pytest.mark.asyncio


async def test_deleting_an_entry_removes_its_nodes_but_leaves_the_concept_it_covered(graph):
    rows = GraphRows()
    rows.node("Book", "entry-1", {"title": "Book", "entry_id": "entry-1"})
    rows.node("Chapter", "ch-1", {"name": "Chapter", "entry_id": "entry-1"})
    rows.node("Concept", "shared-concept", {"name": "Shared"})
    rows.edge("Book", "HAS_CHAPTER", "Chapter", "entry-1", "ch-1")
    rows.edge("Chapter", "COVERS", "Concept", "ch-1", "shared-concept")
    await write_rows(graph, rows)

    await delete_entry_nodes(graph, "entry-1")

    assert await node_props(graph, "Book", "entry-1") is None
    assert await node_props(graph, "Chapter", "ch-1") is None
    assert await node_props(graph, "Concept", "shared-concept") is not None
