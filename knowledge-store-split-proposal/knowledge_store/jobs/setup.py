"""Shared setup for every knowledge-store job verb: GCP identity, secrets,
bucket/storage, database repositories, and the graph client. Every verb's
own file in this package builds its specific logic on top of this, instead
of repeating what run.py's main() used to do once for all of them.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dotenv import load_dotenv
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

load_dotenv()


@dataclass
class JobContext:
    """Every shared service one verb needs, built once per run."""

    secrets: SecretReader
    storage: KnowledgeStoreStorage
    registry: CatalogRepository
    usage: UsageRepository
    leases: LeasesRepository


def require_entry_id(argv: Sequence[str] | None = None) -> str:
    """Return the sole entry id argument, or reject an invalid invocation."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise ValueError("entry job requires exactly one entry id")
    return args[0]


def require_no_args(argv: Sequence[str] | None = None) -> None:
    """Reject arguments for a job that accepts none."""
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args:
        raise ValueError("this job takes no arguments")


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
