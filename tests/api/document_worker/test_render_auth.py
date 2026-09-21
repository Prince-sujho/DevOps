"""Auth coverage for POST /render.

README: "This route requires `Authorization: Bearer <DOCUMENT_WORKER_SERVICE_SECRET>`."
infra/api/auth/middleware.py::require_service_secret raises HTTPException(401, ...)
for both a missing token and a wrong one (never 403) -- read for the exact
status code, not for whether auth is required (that's in the README).
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers, render_body


@pytest.mark.asyncio
async def test_render_without_authorization_header_is_401(client):
    response = await client.post("/render", json=render_body())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_render_with_wrong_bearer_token_is_401(client):
    response = await client.post(
        "/render", json=render_body(), headers=auth_headers("not-the-right-secret")
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_render_with_malformed_authorization_header_is_401(client):
    # Not "Bearer <token>" shaped -- read_bearer_token raises 401 for scheme != "Bearer".
    response = await client.post(
        "/render", json=render_body(), headers={"Authorization": "Token abc123"}
    )
    assert response.status_code == 401
