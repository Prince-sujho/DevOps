"""GET /health and GET /version — shared ops routes (infra/api/routes.py).

These aren't documented word-for-word in redirect_service/README.md beyond
"Health check" / "Release metadata", but the exact response shape is a
literal, shared contract defined once in infra/api/routes.py's ops_router
(read only for its literal dict shape, not for any redirect_service-specific
behavior). redirect_service includes this router unmodified in app.py.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


async def test_health_returns_exact_documented_shape(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "started_at"}
    assert body["status"] == "ok"
    assert isinstance(body["started_at"], str)
    # started_at must be a real ISO-8601 timestamp, not just any string.
    from datetime import datetime

    datetime.fromisoformat(body["started_at"])


async def test_version_returns_exact_documented_shape(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELEASE_COMMIT_SHA", "abc123deadbeef")
    monkeypatch.setenv("RELEASE_IMAGE_DIGEST", "sha256:feedface")

    response = await async_client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"release_commit_sha", "release_image_digest"}
    assert body["release_commit_sha"] == "abc123deadbeef"
    assert body["release_image_digest"] == "sha256:feedface"


async def test_version_fields_are_null_when_env_unset(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RELEASE_COMMIT_SHA", raising=False)
    monkeypatch.delenv("RELEASE_IMAGE_DIGEST", raising=False)

    response = await async_client.get("/version")

    assert response.status_code == 200
    body = response.json()
    assert body == {"release_commit_sha": None, "release_image_digest": None}
