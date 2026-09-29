"""Real Neo4j for knowledge_store graph-mechanism tests.

Requires
--------
Docker running locally (the ``testcontainers`` package pulls and runs the
official ``neo4j`` image). Install test deps from
``tests/knowledge_store/requirements-test.txt``.

This session fixture starts one disposable Neo4j container, applies the real
schema statements once, and yields a bound ``GraphClient``. Every test then
runs against a graph wiped clean beforehand, so tests do not share nodes.

Do not mock Neo4j. A test that stubs ``GraphClient.query`` and asserts the
stub was called does not belong here — these tests exist to prove the real
Cypher in ``infra.knowledge.queries`` does what its callers assume.
"""

from __future__ import annotations

from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from testcontainers.community.neo4j import Neo4jContainer

from infra.knowledge.writer import ensure_schema
from infra.platform.graph import GraphClient

# A tag with vector-index support (db.create.setNodeVectorProperty), matching
# what knowledge_store's writer Cypher requires in production.
NEO4J_IMAGE = "neo4j:5.26-community"
AUTH = ("neo4j", "test-knowledge-store-password")


@pytest.fixture(scope="session")
def neo4j_container() -> Iterator[Neo4jContainer]:
    """Start one disposable Neo4j container for the whole test session; stop it
    after.

    Args:
        None.
    Returns:
        The started Neo4j container.
    Raises:
        None.
    """
    container = Neo4jContainer(image=NEO4J_IMAGE, password=AUTH[1])
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest_asyncio.fixture(scope="session")
async def _schema_ready(neo4j_container: Neo4jContainer) -> GraphClient:
    """One client for the whole session; schema constraints only need applying
    once.

    Args:
        neo4j_container: the session-scoped disposable Neo4j container.
    Returns:
        A GraphClient bound to the container, with schema constraints applied.
    Raises:
        None.
    """
    graph = GraphClient(neo4j_container.get_connection_url(), *AUTH)
    await ensure_schema(graph)
    return graph


@pytest_asyncio.fixture
async def graph(_schema_ready: GraphClient) -> AsyncIterator[GraphClient]:
    """The shared client, wiped clean before each test.

    Args:
        _schema_ready: the session-scoped GraphClient with schema already
            applied.
    Returns:
        The GraphClient after the schema is applied and the graph is wiped.
    Raises:
        None.
    """
    await _schema_ready.query("MATCH (n) DETACH DELETE n")
    yield _schema_ready


async def node_props(
    graph: GraphClient, label: str, node_id: str
) -> dict | None:
    """Fetch one node's properties by label and id, or None when absent.

    Args:
        graph: the bound GraphClient.
        label: the node's label.
        node_id: the node's id property.
    Returns:
        The node's properties as a dict, or None if no such node exists.
    Raises:
        None.
    """
    records = await graph.query(
        f"MATCH (n:{label} {{id: $id}}) RETURN properties(n) AS props",
        id=node_id,
    )
    return records[0]["props"] if records else None


async def node_count(graph: GraphClient, label: str) -> int:
    """Count nodes carrying one label.

    Args:
        graph: the bound GraphClient.
        label: the label to count nodes for.
    Returns:
        The number of nodes carrying that label.
    Raises:
        None.
    """
    records = await graph.query(f"MATCH (n:{label}) RETURN count(n) AS count")
    return records[0]["count"]
