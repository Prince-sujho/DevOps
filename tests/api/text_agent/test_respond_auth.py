"""Auth-boundary tests for POST /respond.

Per infra/api/auth/middleware.py::require_service_secret (read for signature
only): a missing bearer token and a wrong bearer token both raise
HTTPException(401, ...) -- there is no 403 path. Both cases below commit to
401 before running.
"""

from __future__ import annotations

import pytest

from .conftest import respond_body


@pytest.mark.asyncio
async def test_respond_without_authorization_header_is_401(client):
    response = await client.post("/respond", json=respond_body())
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_respond_with_wrong_bearer_token_is_401(client):
    response = await client.post(
        "/respond",
        json=respond_body(),
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert response.status_code == 401
