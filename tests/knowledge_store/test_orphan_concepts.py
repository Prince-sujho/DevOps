"""Orphan-concept GC: a concept dies only when nothing references its subtree.

Oracle: infra.knowledge.queries.writer.DELETE_ORPHAN_CONCEPTS comment — "A
concept dies when its subtree has no chapter coverage and no curriculum
item." Run after every re-ingest, so a concept a chapter stopped covering
must not linger forever.
"""

from __future__ import annotations

import pytest

from infra.knowledge.types import GraphRows
from infra.knowledge.writer import gc_orphan_concepts, write_rows

from .conftest import node_props

pytestmark = pytest.mark.asyncio


async def _seed(graph, rows: GraphRows) -> None:
    await write_rows(graph, rows)


async def test_a_concept_covered_by_a_chapter_survives_gc(graph):
    rows = GraphRows()
    rows.node("Chapter", "ch-1", {"name": "Chapter", "entry_id": "e1"})
    rows.node("Concept", "concept-covered", {"name": "Covered"})
    rows.edge("Chapter", "COVERS", "Concept", "ch-1", "concept-covered")
    await _seed(graph, rows)

    deleted = await gc_orphan_concepts(graph)

    assert deleted == 0
    assert await node_props(graph, "Concept", "concept-covered") is not None


async def test_a_concept_holding_a_question_survives_gc(graph):
    rows = GraphRows()
    rows.node("Concept", "concept-with-item", {"name": "Has item"})
    rows.node("Question", "q-1", {"stem": "2+2?", "entry_id": "e1"})
    rows.edge("Concept", "HAS_QUESTION", "Question", "concept-with-item", "q-1")
    await _seed(graph, rows)

    deleted = await gc_orphan_concepts(graph)

    assert deleted == 0
    assert await node_props(graph, "Concept", "concept-with-item") is not None


async def test_a_concept_with_no_coverage_and_no_items_is_deleted(graph):
    rows = GraphRows()
    rows.node("Concept", "concept-orphan", {"name": "Orphan"})
    await _seed(graph, rows)

    deleted = await gc_orphan_concepts(graph)

    assert deleted == 1
    assert await node_props(graph, "Concept", "concept-orphan") is None


async def test_an_uncovered_parent_survives_through_a_covered_child(graph):
    """The subtree check walks HAS_SUBCONCEPT*0.., so a parent survives via any covered descendant."""
    rows = GraphRows()
    rows.node("Chapter", "ch-1", {"name": "Chapter", "entry_id": "e1"})
    rows.node("Concept", "parent", {"name": "Parent"})
    rows.node("Concept", "child", {"name": "Child"})
    rows.edge("Concept", "HAS_SUBCONCEPT", "Concept", "parent", "child")
    rows.edge("Chapter", "COVERS", "Concept", "ch-1", "child")
    await _seed(graph, rows)

    deleted = await gc_orphan_concepts(graph)

    assert deleted == 0
    assert await node_props(graph, "Concept", "parent") is not None
