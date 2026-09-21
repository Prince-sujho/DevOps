"""GET /health and GET /version: public, unauthenticated status routes."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_returns_200(client):
    response = await client.get("/health")
    assert response.status_code == 200


async def test_version_returns_200(client):
    response = await client.get("/version")
    assert response.status_code == 200
