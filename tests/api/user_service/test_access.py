"""POST /internal/access/phone: blocked / needs_onboarding / allowed, with user on allowed."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input

pytestmark = pytest.mark.asyncio


async def test_public_access_phone_route_is_gone(client):
    """README: besides /health and /version there is no public surface."""
    response = await client.post("/access/phone", json={"phone": "919999900001"})
    assert response.status_code == 404


async def test_internal_access_phone_needs_onboarding_for_unknown_phone(client, auth_headers):
    response = await client.post(
        "/internal/access/phone", headers=auth_headers, json={"phone": "919999900001"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_onboarding"
    assert body["user"] is None


async def test_internal_access_phone_allowed_includes_user(client, auth_headers, fakes):
    phone = "919999900002"
    user_id = fakes.users.derive_user_id(phone)
    await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input(phone)),
    )
    response = await client.post(
        "/internal/access/phone", headers=auth_headers, json={"phone": phone}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "allowed"
    assert body["userId"] == user_id
    assert body["user"] is not None
    assert body["user"]["phone"] == phone


async def test_internal_access_phone_blocked_takes_precedence(client, auth_headers, fakes):
    phone = "919999900003"
    user_id = fakes.users.derive_user_id(phone)
    await fakes.blocklist.add(user_id)
    response = await client.post(
        "/internal/access/phone", headers=auth_headers, json={"phone": phone}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["userId"] == user_id


async def test_internal_access_phone_422_on_missing_field(client, auth_headers):
    response = await client.post("/internal/access/phone", headers=auth_headers, json={})
    assert response.status_code == 422


async def test_internal_access_phone_422_on_wrong_type(client, auth_headers):
    response = await client.post(
        "/internal/access/phone", headers=auth_headers, json={"phone": 12345}
    )
    assert response.status_code == 422
