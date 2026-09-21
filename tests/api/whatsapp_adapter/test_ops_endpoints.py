"""Shared ops endpoints (`/health`, `/version`) mounted by `infra.api.ops_router`.

Spec: these are public, unauthenticated endpoints shared by every Sujho API
service (per the task brief, "the shared ops router"). Expected shapes are
taken directly from `infra/api/routes.py`'s literal return values, since that
router's behavior -- not whatsapp_adapter's own README -- is the contract here.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok_status_and_started_at(harness):
    # Committed expectation: 200, body == {"status": "ok", "started_at": <str>}.
    response = await harness.client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["started_at"], str)
    assert set(body.keys()) == {"status", "started_at"}


@pytest.mark.asyncio
async def test_version_returns_release_metadata_shape(harness):
    # Committed expectation: 200, body has exactly these two keys (values may be
    # None when the release env vars are unset, per os.getenv's default).
    response = await harness.client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"release_commit_sha", "release_image_digest"}
