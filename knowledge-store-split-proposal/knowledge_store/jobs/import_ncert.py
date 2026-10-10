"""Import NCERT content into the catalog. Deployed as
``knowledge_store.jobs.import_ncert``; takes no arguments. Holds no lease:
importers only append entries, they don't write the graph.
"""

from __future__ import annotations

import asyncio

from ..importers.ncert import NcertImporter
from .setup import job_context, require_no_args


async def main() -> None:
    """Run the import-ncert verb.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    require_no_args()
    await run()


async def run() -> None:
    """Import NCERT entries into the catalog."""
    async with job_context() as ctx:
        await NcertImporter(ctx.storage, ctx.registry).run()


if __name__ == "__main__":
    asyncio.run(main())
