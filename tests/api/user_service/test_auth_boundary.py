"""Auth boundary, exhaustively: every route except the documented exceptions must 401.

Generated from the runtime route table (app.routes), not a hand-written list,
so a newly added unguarded route fails this test automatically.
"""

from __future__ import annotations

import re

import pytest

from user_service.app.src.api.app import app as real_app

pytestmark = pytest.mark.asyncio

PUBLIC_EXEMPT = {
    ("GET", "/health"),
    ("GET", "/version"),
}


def _concrete_path(path: str) -> str:
    """Substitute a syntactically plausible dummy value for every {param}."""
    return re.sub(r"\{[^{}]+\}", "x", path)


def _enumerate_routes() -> list[tuple[str, str]]:
    """Every (method, concrete path) pair the running app actually serves.

    Reads FastAPI's own generated OpenAPI schema (app.openapi()["paths"]) so
    the enumeration reflects real runtime route wiring -- including router
    prefixes such as /internal -- rather than a hand-maintained list, and
    survives internal FastAPI routing-object changes across versions.
    """
    schema = real_app.openapi()
    pairs: list[tuple[str, str]] = []
    for path, operations in schema["paths"].items():
        for method in operations:
            if method.upper() in ("HEAD", "OPTIONS"):
                continue
            pairs.append((method.upper(), _concrete_path(path)))
    return pairs


ALL_ROUTES = _enumerate_routes()


@pytest.mark.asyncio
async def test_route_enumeration_is_nonempty():
    """Sanity: the enumeration actually found routes (a false pass would hide everything)."""
    assert len(ALL_ROUTES) > 10


@pytest.mark.parametrize(
    "method,path",
    [pair for pair in ALL_ROUTES if pair not in PUBLIC_EXEMPT],
    ids=[f"{m} {p}" for m, p in ALL_ROUTES if (m, p) not in PUBLIC_EXEMPT],
)
async def test_every_guarded_route_401s_with_no_auth_header(client, method, path):
    """Every route not in the documented public exemption set must 401 with no auth.

    require_internal_secret runs before body validation and before any lookup,
    so a nonsense/empty body on a guarded route must still 401 -- never a 422
    or 404. A route that returns something else here is a confirmed
    dependency-ordering bug, not something to accommodate by adding a body.
    """
    response = await client.request(method, path)
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code} with no Authorization header; "
        "expected 401 (require_internal_secret must short-circuit before validation/lookup)"
    )


@pytest.mark.parametrize(
    "method,path",
    [pair for pair in ALL_ROUTES if pair not in PUBLIC_EXEMPT],
    ids=[f"{m} {p}" for m, p in ALL_ROUTES if (m, p) not in PUBLIC_EXEMPT],
)
async def test_every_guarded_route_401s_with_wrong_bearer_token(client, method, path, bad_auth_headers):
    """Every route not in the documented public exemption set must 401 with a wrong token."""
    response = await client.request(method, path, headers=bad_auth_headers)
    assert response.status_code == 401, (
        f"{method} {path} returned {response.status_code} with a wrong bearer token; expected 401"
    )


def test_public_route_exemption_set_matches_readme():
    """README: besides /health and /version there is no public surface."""
    assert PUBLIC_EXEMPT == {("GET", "/health"), ("GET", "/version")}
