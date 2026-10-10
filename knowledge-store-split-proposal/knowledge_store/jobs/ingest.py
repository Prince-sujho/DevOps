"""Ingest one entry: extract, materialize-replace, embed own nodes, GC.
Idempotent and rerunnable. Deployed as ``knowledge_store.jobs.ingest``; the
one positional argument is the entry id.
"""

from __future__ import annotations

import asyncio

from infra.catalog import GRAPH_LEASE
from infra.knowledge import CONTENT_EMBEDDED_LABELS
from infra.knowledge.writer import ensure_schema, gc_orphan_concepts
from infra.llm import Usage
from infra.llm.gemini.runtime import GeminiRuntime
from infra.llm.oai.responses import OpenAIResponsesClient
from infra.llm.oai.runtime import OpenAIRuntime
from infra.usage import IngestUsage
from infra.utils.time import now_ms

from ..embedder import Embedder
from ..extraction import Extractor
from ..graph.materializer import Materializer
from ..progress import Run
from .setup import JobContext, graph_client, job_context, require_entry_id


async def main() -> None:
    """Run the ingest verb for one entry id.

    Args:
        None.
    Returns:
        None.
    Raises:
        ValueError: the command line does not contain exactly one entry id.
    """
    await run(require_entry_id())


async def run(entry_id: str) -> None:
    """Ingest an entry while holding the graph-writer lease."""
    async with job_context() as ctx:
        async with ctx.leases.hold(GRAPH_LEASE, holder=f"ingest {entry_id}"):
            await _run_ingest(entry_id, ctx)


async def _run_ingest(entry_id: str, ctx: JobContext) -> None:
    """Extract -> materialize-replace -> embed own nodes -> GC, for one entry.

    Args:
        entry_id: the catalog entry to ingest.
        ctx: the shared services this verb needs.
    Returns:
        None.
    Raises:
        Exception: re-raised after marking the run failed.
    """
    entry = await ctx.registry.get(entry_id)
    stage = Run("ingest", ctx.registry, entry_id)
    openai = OpenAIRuntime(api_key=ctx.secrets.get("OPENAI_API_KEY"))
    gemini = GeminiRuntime(ctx.secrets.get("GEMINI_API_KEY"))
    graph = graph_client(ctx.secrets)
    # One bill per ingest run; flushed in `finally` so a failed run still lands its spend.
    spent: list[Usage] = []
    try:
        # Ingest is offline and rerunnable; use default while Flex is unavailable.
        await Extractor(
            OpenAIResponsesClient(openai, spent, "default"), graph, ctx.storage
        ).extract(entry, stage)
        await ensure_schema(graph)
        await Materializer(graph, ctx.storage).materialize(entry)
        await stage.activity("embedding_nodes")
        await Embedder(gemini, graph, ctx.storage).run(CONTENT_EMBEDDED_LABELS)
        # A re-ingest can drop coverage: reap concepts nothing references anymore.
        await gc_orphan_concepts(graph)
        await stage.succeed()
    except Exception:
        await stage.fail()
        raise
    finally:
        await ctx.usage.record(
            IngestUsage(createdAtMs=now_ms(), entryId=entry_id, usage=spent)
        )
        await graph.close()
        await gemini.close()
        await openai.close()


if __name__ == "__main__":
    asyncio.run(main())
