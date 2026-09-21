"""Shared fixtures for document_worker API tests.

The real app (document_worker/src/api/app.py) builds AppState with a real
GcsBucket, which needs live GCP credentials. We replace only that storage
boundary with an in-memory fake and drive the rest of the stack (routing,
Pydantic validation, the bearer-secret auth dependency, real Pandoc
rendering) for real, via an ASGI test client.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from document_worker.src.api.app import app as document_worker_app
from document_worker.src.api.context import AppState
from document_worker.src.service import DocumentWorkerService
from infra.conversation_media import ConversationMediaStore

# Matches the shape of a real DOCUMENT_WORKER_SERVICE_SECRET value.
SERVICE_SECRET = "test-document-worker-service-secret"

# Same format string GcsBucket.public_url produces (infra/platform/storage/gcs.py),
# so URL-shape assertions exercise the real ConversationMediaStore object-naming
# logic and only the network call itself is faked.
PUBLIC_URL_ROOT = "https://storage.googleapis.com/fake-conversation-media-bucket"


class FakeGcsBucket:
    """In-memory stand-in for infra.platform.storage.GcsBucket.

    Implements exactly the surface ConversationMediaStore.upload_generated_document
    and the app lifespan's shutdown call use: upload(), public_url(), close().
    """

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []
        self.closed = False
        self.upload_error: Optional[Exception] = None

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((object_name, data, content_type))

    async def exists(self, object_name: str) -> bool:
        return any(name == object_name for name, _, _ in self.uploads)

    def public_url(self, object_name: str) -> str:
        return f"{PUBLIC_URL_ROOT}/{object_name}"

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_bucket() -> FakeGcsBucket:
    """A fresh fake storage backend for one test."""
    return FakeGcsBucket()


@pytest_asyncio.fixture
async def client(fake_bucket: FakeGcsBucket):
    """An httpx AsyncClient wired to the real FastAPI app over ASGI.

    Overrides app.router.lifespan_context so AppState is built with the fake
    storage backend instead of a real GcsBucket (which needs live GCP
    credentials). Everything else -- routing, Pydantic validation, the
    require_service_secret auth dependency, DocumentWorkerService, real
    Pandoc rendering -- runs for real.
    """
    app = document_worker_app

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.ctx = AppState(
            worker=DocumentWorkerService(media_bucket=fake_bucket),
            document_worker_service_secret=SERVICE_SECRET,
        )
        yield
        await fake_bucket.close()

    app.router.lifespan_context = test_lifespan

    async with test_lifespan(app):
        # raise_app_exceptions=False: an unhandled exception in the route must
        # surface as the real HTTP response (500 via Starlette's default
        # ServerErrorMiddleware), not as a raised Python exception in the test.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


VALID_MARKDOWN = "# Linear Equations\n\nSolve for x: 2x + 3 = 7.\n\n## Step 1\n\nSubtract 3 from both sides."


def render_body(
    *,
    filename: str = "linear-equations-revision-sheet",
    title: str = "Linear Equations Revision Sheet",
    markdown: str = VALID_MARKDOWN,
    format: str = "docx",
    user_id: str = "user-id",
    thread_key: str = "whatsapp",
) -> dict:
    """A well-formed /render request body, matching the README example shape."""
    return {
        "document": {
            "title": title,
            "filename": filename,
            "markdown": markdown,
            "format": format,
        },
        "scope": {
            "user_id": user_id,
            "thread_key": thread_key,
        },
    }


def auth_headers(token: str = SERVICE_SECRET) -> dict:
    return {"Authorization": f"Bearer {token}"}
