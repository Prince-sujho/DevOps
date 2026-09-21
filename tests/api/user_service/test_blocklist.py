"""PUT/DELETE /internal/blocklist/{userId}: block/unblock one user identity."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_block_user_then_access_reports_blocked(client, auth_headers, fakes):
    phone = "919999944001"
    user_id = fakes.users.derive_user_id(phone)
    response = await client.put(f"/internal/blocklist/{user_id}", headers=auth_headers)
    assert response.status_code == 204
    assert await fakes.blocklist.contains(user_id) is True

    check = await client.post(
        "/internal/access/phone", headers=auth_headers, json={"phone": phone}
    )
    assert check.json()["status"] == "blocked"


async def test_unblock_user_removes_block(client, auth_headers, fakes):
    phone = "919999944002"
    user_id = fakes.users.derive_user_id(phone)
    await client.put(f"/internal/blocklist/{user_id}", headers=auth_headers)
    response = await client.delete(f"/internal/blocklist/{user_id}", headers=auth_headers)
    assert response.status_code == 204
    assert await fakes.blocklist.contains(user_id) is False


async def test_phone_body_blocklist_route_is_gone(client, auth_headers):
    """Blocklist no longer accepts a phone. The only door is /blocklist/{userId}."""
    response = await client.post(
        "/internal/blocklist",
        json={"phone": "919999944001"},
        headers=auth_headers,
    )
    assert response.status_code == 404


async def test_unblock_unknown_user_is_an_idempotent_no_op(client, auth_headers, fakes):
    user_id = fakes.users.derive_user_id("919999944099")
    response = await client.delete(f"/internal/blocklist/{user_id}", headers=auth_headers)
    assert response.status_code == 204
