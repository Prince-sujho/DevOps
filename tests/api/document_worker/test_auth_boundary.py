"""Auth boundary for document_worker: every served route except the shared ops
routes must 401.
"""

from __future__ import annotations

import pytest

from document_worker.src.api.app import app as real_app

from ..auth_routes import guarded_routes

pytestmark = pytest.mark.asyncio

GUARDED = guarded_routes(real_app)
# An empty enumeration would silently skip every case below; fail collection
# instead.
assert GUARDED, "no guarded routes found"
BAD_HEADERS = {
    "missing": {},
    "wrong-token": {"Authorization": "Bearer not-the-right-secret"},
    "wrong-scheme": {"Authorization": "Token abc123"},
}


@pytest.mark.parametrize(
    "headers", list(BAD_HEADERS.values()), ids=list(BAD_HEADERS)
)
@pytest.mark.parametrize(
    "method,path", GUARDED, ids=[f"{m} {p}" for m, p in GUARDED]
)
async def test_every_guarded_route_401s_without_the_service_secret(
    client, method, path, headers
):
    """Every guarded route 401s for every missing/wrong-token/wrong-scheme
    header case.

    Args:
        client: HTTP client for the running document_worker app.
        method: the guarded route's HTTP method.
        path: the guarded route's concrete path.
        headers: the parametrized bad-auth header case.
    Returns:
        None.
    Raises:
        None.
    """
    response = await client.request(method, path, headers=headers)
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code}"
    )
