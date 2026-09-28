"""Auth boundary, exhaustively: every route except the shared ops routes must 401.

Both lists are read from the running system: served routes from the app's
OpenAPI schema, public routes from ``infra.api.ops_router``. A newly added
unguarded route fails here with no change to this file.
"""

from __future__ import annotations

import pytest

from user_service.app.src.api.app import app as real_app

from ..auth_routes import guarded_routes

pytestmark = pytest.mark.asyncio

GUARDED = guarded_routes(real_app)
IDS = [f"{method} {path}" for method, path in GUARDED]


async def test_route_enumeration_is_nonempty():
    """A false pass would hide everything: the enumeration must find guarded routes."""
    assert len(GUARDED) > 10


@pytest.mark.parametrize("method,path", GUARDED, ids=IDS)
async def test_every_guarded_route_401s_with_no_auth_header(client, method, path):
    """require_internal_secret runs before validation and lookup: never 422 or 404 first."""
    response = await client.request(method, path)
    assert response.status_code == 401, f"{method} {path} returned {response.status_code}"


@pytest.mark.parametrize("method,path", GUARDED, ids=IDS)
async def test_every_guarded_route_401s_with_wrong_bearer_token(client, method, path, bad_auth_headers):
    response = await client.request(method, path, headers=bad_auth_headers)
    assert response.status_code == 401, f"{method} {path} returned {response.status_code}"
