"""Remove one entry: graph delete, GC, blob deletes, registry delete.
Idempotent and rerunnable. Deployed as ``knowledge_store.jobs.remove``; the
one positional argument is the entry id.
"""

from __future__ import annotations

import asyncio
import sys

from infra.catalog import GRAPH_LEASE
from infra.knowledge.writer import delete_entry_nodes, gc_orphan_concepts

from ..progress import Run
from .setup import JobContext, graph_client, job_context


async def main() -> None:
    """Run the remove verb for one entry id.

    Args:
        None.
    Returns:
        None.
    Raises:
        IndexError: no entry id was given on the command line.
    """
    entry_id = sys.argv[1]
    async with job_context() as ctx:
        async with ctx.leases.hold(GRAPH_LEASE, holder=f"remove {entry_id}"):
            await _run_remove(entry_id, ctx)


async def _run_remove(entry_id: str, ctx: JobContext) -> None:
    """Graph delete -> GC -> blob deletes -> registry delete (the existence
    bit dies last).

    Args:
        entry_id: the catalog entry to remove.
        ctx: the shared services this verb needs.
    Returns:
        None.
    Raises:
        Exception: re-raised after marking the run failed.
    """
    stage = Run("remove", ctx.registry, entry_id)
    await stage.activity("removing_entry")
    graph = graph_client(ctx.secrets)
    try:
        await delete_entry_nodes(graph, entry_id)
        await gc_orphan_concepts(graph)
        await ctx.storage.delete_extracted(entry_id)
        await ctx.storage.delete_raw(entry_id)
        # Remove's success is the entry vanishing: delete the doc, never mark it.
        await ctx.registry.delete(entry_id)
    except Exception:
        await stage.fail()
        raise
    finally:
        await graph.close()


if __name__ == "__main__":
    asyncio.run(main())
