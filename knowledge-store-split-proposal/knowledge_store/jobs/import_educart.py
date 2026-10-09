"""Import Educart content into the catalog. Deployed as
``knowledge_store.jobs.import_educart``; takes no arguments. Holds no
lease: importers only append entries, they don't write the graph.
"""

from __future__ import annotations

import asyncio

from ..importers.educart import EducartImporter
from .setup import job_context


async def main() -> None:
    """Run the import-educart verb.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    async with job_context() as ctx:
        await EducartImporter(ctx.storage, ctx.registry).run()


if __name__ == "__main__":
    asyncio.run(main())
