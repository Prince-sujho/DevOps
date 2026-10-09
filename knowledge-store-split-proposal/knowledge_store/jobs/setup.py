"""Shared setup for every knowledge-store job verb: GCP identity, secrets,
bucket/storage, database repositories, and the graph client. Every verb's
own file in this package builds its specific logic on top of this, instead
of repeating what run.py's main() used to do once for all of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from infra.firestore import (
    CatalogRepository,
    LeasesRepository,
    UsageRepository,
    firestore_client,
)
from infra.platform.gcp import GcpIdentity
from infra.platform.graph import GraphClient
from infra.platform.secrets import SecretReader
from infra.platform.storage import GcsBucket

from ..storage import KnowledgeStoreStorage


@dataclass
class JobContext:
    """Every shared service one verb needs, built once per run."""

    secrets: SecretReader
    storage: KnowledgeStoreStorage
    registry: CatalogRepository
    usage: UsageRepository
    leases: LeasesRepository


@asynccontextmanager
async def job_context() -> AsyncIterator[JobContext]:
    """Build every shared service a verb needs, and close what owns a
    connection on exit — the same lifecycle run.py's main() held, before
    the split.

    Args:
        None.
    Yields:
        The JobContext every verb's main() calls into.
    Raises:
        None.
    """
    gcp = GcpIdentity.from_env()
    secrets = SecretReader(gcp)
    bucket = GcsBucket(
        secrets.get("KNOWLEDGE_STORE_GCS_BUCKET"), credentials=gcp.credentials
    )
    storage = KnowledgeStoreStorage(bucket)
    db = firestore_client(gcp)
    try:
        yield JobContext(
            secrets=secrets,
            storage=storage,
            registry=CatalogRepository(db),
            usage=UsageRepository(db),
            leases=LeasesRepository(db),
        )
    finally:
        await bucket.close()


def graph_client(secrets: SecretReader) -> GraphClient:
    """Build the Neo4j Aura client from Secret Manager credentials.

    Args:
        secrets: the job's SecretReader.
    Returns:
        A new GraphClient.
    Raises:
        None.
    """
    return GraphClient(
        uri=secrets.get("NEO4J_URI"),
        user=secrets.get("NEO4J_USER"),
        password=secrets.get("NEO4J_PASSWORD"),
    )
