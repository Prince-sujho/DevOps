"""Shared ops routes: /health and /version (public, no auth required).

Shape asserted per infra/api/routes.py, which document_worker/README.md's
ops-router include (`app.include_router(ops_router)`) wires in unmodified.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "started_at"}
    assert body["status"] == "ok"
    assert isinstance(body["started_at"], str)


@pytest.mark.asyncio
async def test_version_shape(client):
    response = await client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"release_commit_sha", "release_image_digest"}
