"""Materialize-replace: one entry's subgraph always equals its current extraction.

Oracle: knowledge_store/graph/materializer.py — "Replaces one entry's subgraph
with its cached extraction." A re-ingest must leave exactly the new rows
behind, never a duplicate of the old ones, because both writes upsert by the
same deterministic ids and every entry-owned node carries entry_id.
"""

from __future__ import annotations

import pytest

from infra.knowledge.writer import delete_entry_nodes, write_rows
from infra.knowledge.types import GraphRows

from .conftest import node_count, node_props

pytestmark = pytest.mark.asyncio

ENTRY_ID = "entry-materialize-1"


def _rows(chapter_name: str) -> GraphRows:
    rows = GraphRows()
    rows.node("Book", ENTRY_ID, {"title": "Book", "entry_id": ENTRY_ID})
    rows.node("Chapter", "chapter-1", {"name": chapter_name, "entry_id": ENTRY_ID})
    rows.edge("Book", "HAS_CHAPTER", "Chapter", ENTRY_ID, "chapter-1")
    return rows


async def _materialize(graph, chapter_name: str) -> None:
    await delete_entry_nodes(graph, ENTRY_ID)
    await write_rows(graph, _rows(chapter_name))


async def test_reingesting_an_entry_replaces_its_chapter_without_duplicating_it(graph):
    await _materialize(graph, "First Pass")
    await _materialize(graph, "Second Pass")

    assert await node_count(graph, "Chapter") == 1
    assert (await node_props(graph, "Chapter", "chapter-1"))["name"] == "Second Pass"


async def test_materialize_leaves_other_entries_untouched(graph):
    other_rows = GraphRows()
    other_rows.node("Book", "entry-other", {"title": "Other", "entry_id": "entry-other"})
    await write_rows(graph, other_rows)

    await _materialize(graph, "Mine")

    assert (await node_props(graph, "Book", "entry-other"))["title"] == "Other"
