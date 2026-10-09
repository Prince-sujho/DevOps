"""Grade pending sessions; each judgment lands on its Session node with its
vector. Deployed as ``knowledge_store.jobs.sessions``; takes no arguments.
"""

from __future__ import annotations

import asyncio

from infra.catalog import SESSIONS_LEASE
from infra.clients.users.client import UsersClient
from infra.llm.gemini.embeddings import GeminiEmbeddingClient
from infra.llm.gemini.runtime import GeminiRuntime
from infra.llm.oai.runtime import OpenAIRuntime
from infra.skills import SkillLibrary

from ..sessions.extractor import SessionExtractor
from .setup import JobContext, graph_client, job_context


async def main() -> None:
    """Run the sessions verb.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    async with job_context() as ctx:
        async with ctx.leases.hold(SESSIONS_LEASE, holder="sessions"):
            await _run_sessions(ctx)


async def _run_sessions(ctx: JobContext) -> None:
    """Grade pending sessions; each judgment lands on its Session node with
    its vector.

    Args:
        ctx: the shared services this verb needs.
    Returns:
        None.
    Raises:
        None.
    """
    gemini = GeminiRuntime(ctx.secrets.get("GEMINI_API_KEY"))
    openai = OpenAIRuntime(api_key=ctx.secrets.get("OPENAI_API_KEY"))
    graph = graph_client(ctx.secrets)
    users = UsersClient(
        ctx.secrets.get("USERS_API_ORIGIN"), ctx.secrets.get("USERS_SERVICE_SECRET")
    )
    try:
        extractor = SessionExtractor(
            openai,
            graph,
            GeminiEmbeddingClient(gemini),
            users,
            SkillLibrary.load(),
            ctx.usage,
        )
        await extractor.run()
    finally:
        await users.close()
        await graph.close()
        await openai.close()
        await gemini.close()


if __name__ == "__main__":
    asyncio.run(main())
