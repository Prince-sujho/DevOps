"""GET /go/{handle} — the public redirect route.

Spec (redirect_service/README.md):
  - "The service passes the raw path segment straight through; user_service is
    the single boundary that normalizes and validates handles." -> redirect_service
    never itself rejects a handle; it always redirects.
  - "The redirect target is https://wa.me/{PUBLIC_WHATSAPP_NUMBER}?text=<urlencoded
    prefill>, with the handle dropped into the opener message."
  - "The service knows nothing: it always sends the user to WhatsApp, even if
    click logging fails."

The exact prefill template/format string is not specified word-for-word in the
README, so per the task's explicit carve-out we read it from
infra/clients/users (ATTRIBUTION_PREFILL_TEMPLATE) as a signature/constant
fact, then build the full expected Location literal ourselves using the
stdlib `urllib.parse.quote` (a generic, well-known transform — not source
business logic) with the same default `safe='/'` the route itself uses.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest

from infra.clients.users import ATTRIBUTION_PREFILL_TEMPLATE
from redirect_service.app.src.constants import WHATSAPP_BASE_URL

from .conftest import TEST_PUBLIC_WHATSAPP_NUMBER, FakeUsersClient

pytestmark = pytest.mark.asyncio


def _expected_location(handle: str) -> str:
    text = quote(ATTRIBUTION_PREFILL_TEMPLATE.format(handle=handle))
    return f"{WHATSAPP_BASE_URL}/{TEST_PUBLIC_WHATSAPP_NUMBER}?text={text}"


async def test_go_redirects_302_to_exact_whatsapp_location(
    async_client: httpx.AsyncClient,
) -> None:
    handle = "shreya"
    response = await async_client.get(f"/go/{handle}")

    assert response.status_code == 302
    assert response.headers["location"] == _expected_location(handle)


async def test_go_unregistered_handle_still_redirects(
    async_client: httpx.AsyncClient,
    fake_users_client: FakeUsersClient,
) -> None:
    """redirect_service does not validate handles; unregistered ones still 302.

    The fake user_service click client behaves like the documented no-op for
    an unregistered handle (returns normally, records nothing rejected) and
    the redirect must still happen exactly as for a registered handle.
    """
    handle = "no-such-handle-ever-registered"
    response = await async_client.get(f"/go/{handle}")

    assert response.status_code == 302
    assert response.headers["location"] == _expected_location(handle)


async def test_go_handle_with_space_is_passed_through_raw(
    async_client: httpx.AsyncClient,
) -> None:
    """A URL-encoded space in the path segment decodes to a literal space in
    the handle, which redirect_service passes straight through (per README:
    "passes the raw path segment straight through") into the prefill text,
    which then gets re-encoded in the Location header.
    """
    response = await async_client.get("/go/shre%20ya")

    assert response.status_code == 302
    assert response.headers["location"] == _expected_location("shre ya")


async def test_go_handle_with_at_sign_is_passed_through_raw(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/go/shre@ya")

    assert response.status_code == 302
    assert response.headers["location"] == _expected_location("shre@ya")


async def test_go_empty_handle_segment_is_404_via_routing_not_handler(
    async_client: httpx.AsyncClient,
) -> None:
    """`/go/` (empty path segment) never matches the `/go/{handle}` route at
    all — FastAPI's default str path converter requires at least one
    character, so this is a routing fact (empirically confirmed against the
    real app: FastAPI returns its own 404), not a behavioral decision made by
    redirect_service's own handler code.
    """
    response = await async_client.get("/go/")

    assert response.status_code == 404
