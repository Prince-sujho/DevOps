"""Shared fixtures for redirect_service API tests.

Drives the real FastAPI app via an in-process ASGI transport, with the
lifespan replaced so `app.state.ctx` is wired to test-controlled settings and
a fake user_service click client instead of the real network client.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator, Callable, Optional

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from redirect_service.app.src.api.app import app as real_app
from redirect_service.app.src.api.context import AppState

# Test-controlled literal for PUBLIC_WHATSAPP_NUMBER (Secret Manager value in
# real deployments; here it's a constant we own so expected Location headers
# can be asserted as full literals).
TEST_PUBLIC_WHATSAPP_NUMBER = "911234500000"


class FakeUsersClient:
    """In-memory stand-in for infra.clients.users.client.UsersClient.

    Only implements the one method the redirect route actually calls
    (`record_referrer_click`), per the route's signature usage.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._raise: Optional[BaseException] = None

    def fail_next_click_with(self, exc: BaseException) -> None:
        """Make the next (and subsequent) record_referrer_click calls raise."""
        self._raise = exc

    async def record_referrer_click(self, handle: str) -> None:
        if self._raise is not None:
            raise self._raise
        self.calls.append(handle)


@pytest.fixture
def fake_users_client() -> FakeUsersClient:
    return FakeUsersClient()


@pytest.fixture
def test_settings() -> SimpleNamespace:
    """Duck-typed Settings: the route only ever reads `.public_whatsapp_number`."""
    return SimpleNamespace(public_whatsapp_number=TEST_PUBLIC_WHATSAPP_NUMBER)


@pytest.fixture
def app(fake_users_client: FakeUsersClient, test_settings: SimpleNamespace) -> FastAPI:
    """The real FastAPI app with its lifespan replaced by a test lifespan."""

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ctx = AppState(settings=test_settings, users=fake_users_client)
        yield

    real_app.router.lifespan_context = test_lifespan
    return real_app


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=False,
    ) as client:
        async with app.router.lifespan_context(app):
            yield client
