"""Public ops routes shared by every Sujho service (infra/api/routes.py).

These are not text_agent business logic, but the task brief commits to their
exact literal shape from that shared file: /health -> {"status": "ok",
"started_at": <iso8601 string>}; /version -> {"release_commit_sha": ...,
"release_image_digest": ...}. No auth required.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_is_public_and_returns_documented_shape(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "started_at"}
    assert body["status"] == "ok"
    assert isinstance(body["started_at"], str)


@pytest.mark.asyncio
async def test_version_is_public_and_returns_documented_shape(client):
    response = await client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"release_commit_sha", "release_image_digest"}
