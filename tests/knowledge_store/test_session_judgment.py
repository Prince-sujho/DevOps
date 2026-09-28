"""A session's judgment is pending until decorate_session lands it, once.

Oracle: README (Sessions corpus) — "The Session node carries structured
judgment facts... and embedding (of the intent)." infra.knowledge.rows reads
the same marker this test writes directly: a Session with no ``intent``
property is ungraded. Gemini is faked (the embedding boundary); Neo4j is real.
"""

from __future__ import annotations

import pytest

from infra.clients.users import SessionExtraction, SessionHeader
from infra.knowledge.ids import session_id
from infra.knowledge.writer import decorate_session

from .conftest import node_props
from .fakes import EMBEDDING_DIMENSIONS, FakeEmbeddings

pytestmark = pytest.mark.asyncio

HEADER = SessionHeader(userId="user-1", threadKey="whatsapp", startedAtMs=1_700_000_000_000, persona="student")
EXTRACTION = SessionExtraction(
    intent="wanted help with algebra",
    grounding=3,
    boundaries=3,
    craft=2,
    efficiency=2,
    resolution=2,
    worked=["asked a clarifying question"],
    failed=[],
)


async def test_a_session_has_no_intent_until_it_is_graded(graph):
    await graph.query(
        "MERGE (s:Session {id: $id}) ON CREATE SET s.user_id = $user_id",
        id="SN:test-session-1", user_id=HEADER.userId,
    )

    props = await node_props(graph, "Session", "SN:test-session-1")

    assert "intent" not in props


async def test_decorate_session_lands_the_judgment_and_its_intent_vector(graph):
    await decorate_session(graph, FakeEmbeddings(), HEADER, EXTRACTION)

    props = await node_props(graph, "Session", session_id(HEADER.userId, HEADER.threadKey, HEADER.startedAtMs))
    assert props["intent"] == EXTRACTION.intent
    assert props["grounding"] == EXTRACTION.grounding
    assert props["worked"] == EXTRACTION.worked
    assert len(props["embedding"]) == EMBEDDING_DIMENSIONS


async def test_regrading_the_same_session_overwrites_rather_than_duplicates(graph):
    await decorate_session(graph, FakeEmbeddings(), HEADER, EXTRACTION)
    revised = EXTRACTION.model_copy(update={"intent": "wanted help with geometry"})

    await decorate_session(graph, FakeEmbeddings(), HEADER, revised)

    sid = session_id(HEADER.userId, HEADER.threadKey, HEADER.startedAtMs)
    records = await graph.query("MATCH (s:Session {id: $id}) RETURN count(s) AS count", id=sid)
    assert records[0]["count"] == 1
    assert (await node_props(graph, "Session", sid))["intent"] == revised.intent
