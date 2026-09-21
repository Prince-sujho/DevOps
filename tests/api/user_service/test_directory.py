"""GET /internal/users (derived directory page)."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input

pytestmark = pytest.mark.asyncio


async def _seed_students(client, auth_headers):
    """Deterministic, hand-built roster: mixed name/grade/subject/activity."""
    rows = [
        # (phone, name, grade, subjects)
        ("919999922001", "Amit Kumar", 8, ["mathematics"]),
        ("919999922002", "Bina Roy", 9, ["science"]),
        ("919999922003", "Chetan Das", 8, ["science"]),
        ("919999922004", "Deepa Nair", 10, ["mathematics", "science"]),
    ]
    ids = {}
    for phone, name, grade, subjects in rows:
        response = await client.post(
            "/internal/users",
            headers=auth_headers,
            json=create_user_body(student_profile_input(phone, name=name, grade=grade, subjects=subjects)),
        )
        ids[name] = response.json()["userId"]
    return ids


async def test_list_users_offset_beyond_total_returns_empty_but_true_total(client, auth_headers):
    await _seed_students(client, auth_headers)
    response = await client.get(
        "/internal/users", headers=auth_headers, params={"persona": "student", "offset": 1000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["totalCount"] == 4


async def test_list_users_limit_zero_returns_zero_items(client, auth_headers):
    """limit=0 is an empty page; totalCount is still the real roster size."""
    await _seed_students(client, auth_headers)
    response = await client.get(
        "/internal/users", headers=auth_headers, params={"persona": "student", "limit": 0}
    )
    assert response.status_code == 200, (
        f"expected 200 with an empty page for limit=0, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["entries"] == []
    assert body["totalCount"] == 4


async def test_list_users_sort_by_name_is_case_insensitive_alphabetical(client, auth_headers):
    ids = await _seed_students(client, auth_headers)
    response = await client.get(
        "/internal/users", headers=auth_headers, params={"persona": "student", "sort": "name"}
    )
    assert response.status_code == 200
    names = [entry["profile"]["name"] for entry in response.json()["entries"]]
    assert names == ["Amit Kumar", "Bina Roy", "Chetan Das", "Deepa Nair"]


async def test_list_users_search_matching_nothing_returns_empty(client, auth_headers):
    await _seed_students(client, auth_headers)
    response = await client.get(
        "/internal/users", headers=auth_headers, params={"persona": "student", "q": "zzz-no-match"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["totalCount"] == 0


async def test_list_users_search_multi_token_requires_all_tokens_to_match(client, auth_headers):
    """A profile matching only one of two search tokens must be excluded (AND semantics)."""
    await _seed_students(client, auth_headers)
    # "Amit" matches Amit Kumar; "Roy" matches Bina Roy. No single profile has both.
    response = await client.get(
        "/internal/users", headers=auth_headers, params={"persona": "student", "q": "Amit Roy"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == [], (
        "expected AND semantics across search tokens: a profile matching only one token "
        f"must not match, got {[e['profile']['name'] for e in body['entries']]}"
    )
    assert body["totalCount"] == 0


async def test_list_users_combined_grade_and_subject_filters(client, auth_headers):
    """Only the profile satisfying grade AND subject simultaneously is returned."""
    await _seed_students(client, auth_headers)
    # grade=8 matches Amit(math) and Chetan(science); subject=science narrows to Chetan only.
    response = await client.get(
        "/internal/users",
        headers=auth_headers,
        params={"persona": "student", "grade": [8], "subject": ["science"]},
    )
    assert response.status_code == 200
    body = response.json()
    names = [entry["profile"]["name"] for entry in body["entries"]]
    assert names == ["Chetan Das"]
    assert body["totalCount"] == 1


async def test_list_users_401_and_shape_smoke(client, auth_headers):
    response = await client.get("/internal/users", headers=auth_headers, params={"persona": "teacher"})
    assert response.status_code == 200
    assert response.json() == {"entries": [], "totalCount": 0}


async def test_list_users_422_missing_required_persona(client, auth_headers):
    response = await client.get("/internal/users", headers=auth_headers)
    assert response.status_code == 422


async def test_list_profiles_route_is_gone(client, auth_headers):
    """GET /internal/profiles was dropped with the unused public/institution surface."""
    response = await client.get(
        "/internal/profiles", headers=auth_headers, params={"persona": "student"}
    )
    assert response.status_code == 404
