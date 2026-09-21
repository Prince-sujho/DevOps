"""POST/GET /internal/users, batchGet, get-one, delete, profile overlay, location."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input, teacher_profile_input

pytestmark = pytest.mark.asyncio


async def test_create_user_returns_201_or_200_with_profile_shape(client, auth_headers):
    body = create_user_body(student_profile_input("919999911001", name="Zara", grade=6))
    response = await client.post("/internal/users", headers=auth_headers, json=body)
    assert response.status_code == 200
    profile = response.json()
    assert profile["phone"] == "919999911001"
    assert profile["name"] == "Zara"
    assert profile["persona"] == "student"
    assert profile["scope"]["grade"] == 6
    assert profile["attribution"] is None
    assert profile["institution"] == {"id": "school-1", "name": "Delhi Public School"}


async def test_create_user_is_create_only_original_profile_survives_second_create(
    client, auth_headers
):
    """README: creation is create-only; an existing user is neither overwritten nor re-attributed."""
    phone = "919999911002"
    # Pre-seed a referrer handle so the second create's mention could plausibly attribute.
    await client.post(
        "/internal/influencers",
        headers=auth_headers,
        json={"handle": "firsttag", "platform": "instagram"},
    )
    await client.post(
        "/internal/influencers",
        headers=auth_headers,
        json={"handle": "secondtag", "platform": "youtube"},
    )
    first_body = create_user_body(
        student_profile_input(phone, name="Original Name", grade=5),
        pre_onboarding_texts=["hi @firsttag"],
    )
    first = await client.post("/internal/users", headers=auth_headers, json=first_body)
    assert first.status_code == 200
    first_profile = first.json()
    assert first_profile["name"] == "Original Name"
    assert first_profile["attribution"] == {"kind": "referrer", "handle": "firsttag"}

    second_body = create_user_body(
        student_profile_input(phone, name="Changed Name", grade=5),
        pre_onboarding_texts=["hi @secondtag"],
    )
    second = await client.post("/internal/users", headers=auth_headers, json=second_body)

    read_back = await client.get(f"/internal/users/{first_profile['userId']}", headers=auth_headers)
    assert read_back.status_code == 200
    stored = read_back.json()
    assert stored["name"] == "Original Name", (
        f"create-only: name must remain the first create's value, got {stored['name']!r} "
        f"(second call returned status {second.status_code})"
    )
    assert stored["attribution"] == {"kind": "referrer", "handle": "firsttag"}, (
        "create-only: attribution is immutable, first-touch only"
    )


async def test_create_user_422_missing_required_field(client, auth_headers):
    body = {"profile": {"phone": "919999911003"}, "preOnboardingTexts": []}
    response = await client.post("/internal/users", headers=auth_headers, json=body)
    assert response.status_code == 422


async def test_get_user_404_for_unknown_user_id(client, auth_headers):
    response = await client.get("/internal/users/no-such-user-id", headers=auth_headers)
    assert response.status_code == 404


async def test_get_user_200_returns_created_profile(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(teacher_profile_input("919999911004", name="Mrs Iyer")),
    )
    user_id = create.json()["userId"]
    response = await client.get(f"/internal/users/{user_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Mrs Iyer"


async def test_batch_get_users_returns_only_existing_ids_in_request_order(client, auth_headers):
    c1 = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911005"))
    )
    c2 = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911006"))
    )
    id1, id2 = c1.json()["userId"], c2.json()["userId"]
    response = await client.post(
        "/internal/users:batchGet",
        headers=auth_headers,
        json={"userIds": [id2, "unknown-id", id1]},
    )
    assert response.status_code == 200
    returned_ids = [row["userId"] for row in response.json()]
    assert returned_ids == [id2, id1]


async def test_batch_get_users_422_wrong_type(client, auth_headers):
    response = await client.post(
        "/internal/users:batchGet", headers=auth_headers, json={"userIds": "not-a-list"}
    )
    assert response.status_code == 422


async def test_get_directory_entry_404_for_unknown_user(client, auth_headers):
    response = await client.get("/internal/directory/no-such-user", headers=auth_headers)
    assert response.status_code == 404


async def test_get_directory_entry_shape(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999911007", name="Ravi")),
    )
    user_id = create.json()["userId"]
    response = await client.get(f"/internal/directory/{user_id}", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["userId"] == user_id
    assert body["activity"] == {"sessionCount": 0, "lastMessageAtMs": None}
    assert body["activityState"] == "never"
    assert body["blocked"] is False


async def test_delete_user_returns_204_and_user_then_404s(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911008"))
    )
    user_id = create.json()["userId"]
    response = await client.delete(f"/internal/users/{user_id}", headers=auth_headers)
    assert response.status_code == 204
    after = await client.get(f"/internal/users/{user_id}", headers=auth_headers)
    assert after.status_code == 404


async def test_delete_unknown_user_does_not_crash(client, auth_headers):
    """The route deletes unconditionally across owned collections with no
    existence check first, so there is no README promise to test an exact
    status against for an unknown user_id. `204` is explicitly named in
    tests/outcomes/UNCERTAINTY.md as a guess this suite must not keep just
    because it happens to be green -- so only the qualitative claim (an
    unknown user_id must not crash the route) is asserted here.
    """
    response = await client.delete("/internal/users/never-existed", headers=auth_headers)
    assert response.status_code < 500


async def test_update_profile_overlays_only_provided_fields(client, auth_headers):
    create = await client.post(
        "/internal/users",
        headers=auth_headers,
        json=create_user_body(student_profile_input("919999911009", name="Before")),
    )
    user_id = create.json()["userId"]
    response = await client.post(
        f"/internal/users/{user_id}/profile", headers=auth_headers, json={"name": "After"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "After"
    # institution untouched since it was omitted from the overlay
    assert body["institution"] == {"id": "school-1", "name": "Delhi Public School"}


async def test_update_profile_404_for_unknown_user(client, auth_headers):
    response = await client.post(
        "/internal/users/no-such-user/profile", headers=auth_headers, json={"name": "X"}
    )
    assert response.status_code == 404


async def test_update_profile_422_wrong_type(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911010"))
    )
    user_id = create.json()["userId"]
    response = await client.post(
        f"/internal/users/{user_id}/profile", headers=auth_headers, json={"name": 123}
    )
    assert response.status_code == 422


async def test_set_location_200_returns_profile_with_location(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911011"))
    )
    user_id = create.json()["userId"]
    response = await client.post(
        f"/internal/users/{user_id}/location",
        headers=auth_headers,
        json={"latitude": 28.6, "longitude": 77.2, "address": "New Delhi"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["location"] == {"latitude": 28.6, "longitude": 77.2, "address": "New Delhi"}


async def test_set_location_404_for_unknown_user(client, auth_headers):
    response = await client.post(
        "/internal/users/no-such-user/location",
        headers=auth_headers,
        json={"latitude": 1.0, "longitude": 2.0},
    )
    assert response.status_code == 404


async def test_set_location_422_missing_required_field(client, auth_headers):
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input("919999911012"))
    )
    user_id = create.json()["userId"]
    response = await client.post(
        f"/internal/users/{user_id}/location", headers=auth_headers, json={"latitude": 1.0}
    )
    assert response.status_code == 422
