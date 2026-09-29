"""Test harness for text_agent's POST /respond: real app, faked externals.

Wires the real FastAPI app (text_agent.app.src.api.app:app) with a real
RespondService, but replaces the lifespan so every genuinely external system
(OpenAI Responses/Image APIs, Neo4j graph, Gemini embeddings, document_worker,
user_service) is a fake owned by this directory. Route wiring, Pydantic
validation, and the require_service_secret auth dependency all run for real.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from .fakes import Fakes

SERVICE_SECRET = "test-text-agent-service-secret"


@asynccontextmanager
async def _text_agent_lifespan(app, fakes: Fakes):
    """The app's real lifespan context manager, wired to faked externals.

    Args:
        app: the FastAPI app whose state is populated.
        fakes: the harness's shared fake collaborators.
    Returns:
        None.
    Raises:
        None.
    """
    from text_agent.app.src.api.context import AppState
    from text_agent.app.src.services import RespondService
    from infra.llm.oai.runtime import OpenAIRuntime
    from infra.skills import SkillLibrary

    runtime = OpenAIRuntime(api_key="test-openai-api-key")
    respond = RespondService(
        runtime=runtime,
        users=fakes.users,
        media_bucket=fakes.bucket,
        documents=fakes.documents,
        skills=SkillLibrary.load(),
        graph=fakes.graph,
        embeddings=fakes.embeddings,
    )
    app.state.ctx = AppState(
        respond=respond, text_agent_service_secret=SERVICE_SECRET
    )
    yield
    await runtime.close()


def build_lifespan(fakes: Fakes):
    """Test lifespan for text_agent: real RespondService, faked externals.

    Args:
        fakes: the harness's shared fake collaborators.
    Returns:
        The lifespan context manager to install on the app's router.
    Raises:
        None.
    """
    return partial(_text_agent_lifespan, fakes=fakes)


@pytest.fixture
def fakes() -> Fakes:
    """One fresh set of fakes per test.

    Args:
        None.
    Returns:
        A new Fakes.
    Raises:
        None.
    """
    return Fakes()


@pytest.fixture
def app(fakes: Fakes, monkeypatch):
    """The real text_agent FastAPI app, with its lifespan swapped for the test
    one.

    Args:
        fakes: the harness's shared fake collaborators.
        monkeypatch: pytest's monkeypatch fixture, used to fake the OpenAI
            client class.
    Returns:
        The real FastAPI app.
    Raises:
        None.
    """
    from text_agent.app.src.api.app import app as real_app

    monkeypatch.setattr(
        "text_agent.app.src.services.respond.OpenAIResponsesClient",
        lambda runtime, usage: fakes.openai,
    )
    real_app.router.lifespan_context = build_lifespan(fakes)
    return real_app


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI-transport client bound to the real app, running its real
    lifespan.

    Args:
        app: the FastAPI app the ASGI client is bound to.
    Returns:
        The AsyncClient bound to the app.
    Raises:
        None.
    """
    # raise_app_exceptions=False: an unhandled exception in the route should
    # surface as the real deployed behavior (a 500 response via Starlette's
    # ServerErrorMiddleware), not as a raised exception inside the test client
    # -- matching what a real uvicorn-served client would observe.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http_client:
        async with app.router.lifespan_context(app):
            yield http_client


def auth_headers(token: str = SERVICE_SECRET) -> dict[str, str]:
    """Bearer-auth header for the internal service secret.

    Args:
        token: the bearer token to send.
    Returns:
        The Authorization header dict.
    Raises:
        None.
    """
    return {"Authorization": f"Bearer {token}"}


def student_profile(**overrides) -> dict:
    """A student UserProfile dict matching the README's example shape.

    Args:
        overrides: fields to override on top of the defaults.
    Returns:
        The profile dict.
    Raises:
        None.
    """
    base = {
        "userId": "opaque-user-id",
        "phone": "91XXXXXXXXXX",
        "name": "Aarav",
        "institution": {"id": "2730017", "name": "Delhi Public School"},
        "persona": "student",
        "createdAtMs": 1710000000000,
        "location": None,
        "attribution": None,
        "scope": {"grade": 10, "subjects": ["mathematics"]},
    }
    base.update(overrides)
    return base


def respond_body(**overrides) -> dict:
    """A full /respond request matching GenerateRequest: user, threadKey, rows.

    Args:
        overrides: fields to override on top of the defaults.
    Returns:
        The request body dict.
    Raises:
        None.
    """
    base = {
        "user": student_profile(),
        "threadKey": "whatsapp",
        "rows": [
            {
                "role": "user",
                "createdAtMs": 1710000000000,
                "turnId": "wamid.test.1",
                "content": {
                    "type": "text",
                    "text": "Explain linear equations simply.",
                },
            }
        ],
    }
    base.update(overrides)
    return base


def scripted_turn(text: str, response_id: str = "resp_fake_001"):
    """One completed ChatTurn the fake OpenAI client can return.

    Args:
        text: the reply text.
        response_id: the model response id.
    Returns:
        The ChatTurn.
    Raises:
        None.
    """
    from infra.llm.oai.types.messages import AssistantMessage
    from infra.llm.oai.types.responses import ChatTurn, LlmResponse, Round

    return ChatTurn(
        parsed=LlmResponse(
            reaction=None, messages=[{"type": "text", "text": text}]
        ),
        actions=[],
        thought=Round(responseId=response_id, items=[]),
        speech=AssistantMessage(text=text),
    )
