"""Ambassador enrollment, self-status, and derived admin reports."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input

pytestmark = pytest.mark.asyncio


async def test_enroll_ambassador_first_call_mints_handle_and_returns_status(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999955001", name="Arjun", institution_id="school-9")),
    )
    user_id = create.json()["userId"]
    response = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["handle"].startswith("arjun-")
    assert body["points"] == 0
    assert body["studentsReferred"] == 0
    assert body["teachersReferred"] == 0
    assert body["tier"] is None
    assert body["balanceInr"] == 0


async def test_enroll_ambassador_is_idempotent_same_handle_on_second_call(client, auth_headers):
    """README: 'Enroll one user as a campus ambassador (idempotent)'."""
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999955002", name="Bina", institution_id="school-9")),
    )
    user_id = create.json()["userId"]
    first = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    second = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    assert second.status_code == 200, (
        f"idempotent enroll should not error on a second call; got {second.status_code}: {second.text}"
    )
    assert second.json()["handle"] == first.json()["handle"], (
        "idempotent enroll must mint the handle only once and reuse it on replay"
    )


async def test_enroll_ambassador_refuses_when_institution_id_is_null(client, auth_headers):
    """README: refuses when the profile school has no directory id.

    The route reports that refusal as 200 with result=school_not_recognised
    (no HTTP status is specified). The sibling test checks no handle is minted.
    """
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(
            student_profile_input("919999955003", name="Chetna", institution_id=None)
        ),
    )
    user_id = create.json()["userId"]
    response = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["result"] == "school_not_recognised"


async def test_enroll_ambassador_refusal_does_not_create_a_registry_row(client, auth_headers, fakes):
    """Regardless of the returned status, a refused enroll must not mint a handle."""
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(
            student_profile_input("919999955004", name="Deven", institution_id=None)
        ),
    )
    user_id = create.json()["userId"]
    await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    ambassador = await fakes.referrers.get_ambassador_by_user(user_id)
    assert ambassador is None, "a refused enroll must not create an ambassador registry row"


async def test_enroll_ambassador_404_for_unknown_user(client, auth_headers):
    response = await client.post("/internal/users/no-such-user/ambassador", headers=auth_headers)
    assert response.status_code == 404


async def test_get_ambassador_status_null_when_not_enrolled(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999955005"))
    )
    user_id = create.json()["userId"]
    response = await client.get(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() is None


async def test_get_ambassador_status_after_enroll(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999955006", name="Esha", institution_id="school-9")),
    )
    user_id = create.json()["userId"]
    await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    response = await client.get(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["handle"].startswith("esha-")


async def test_list_ambassadors_row_shape(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999955007", name="Farhan", institution_id="school-9")),
    )
    user_id = create.json()["userId"]
    enroll = await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    handle = enroll.json()["handle"]

    response = await client.get("/internal/ambassadors", headers=auth_headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["userId"] == user_id
    assert rows[0]["handle"] == handle
    assert rows[0]["points"] == 0
    assert rows[0]["started"] == 0
    assert rows[0]["tier"] is None


async def test_ambassador_detail_404_for_unenrolled_user(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999955008"))
    )
    user_id = create.json()["userId"]
    response = await client.get(f"/internal/ambassadors/{user_id}", headers=auth_headers)
    assert response.status_code == 404


async def test_ambassador_detail_shape(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999955009", name="Gopi", institution_id="school-9")),
    )
    user_id = create.json()["userId"]
    await client.post(f"/internal/users/{user_id}/ambassador", headers=auth_headers)
    response = await client.get(f"/internal/ambassadors/{user_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["row"]["userId"] == user_id
    assert body["referrals"] == []
    assert body["giftCards"] == []
    assert body["earnedInr"] == 0
    assert body["balanceInr"] == 0
