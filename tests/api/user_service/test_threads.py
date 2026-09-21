"""Thread session/transcript routes: append, list, extraction."""

from __future__ import annotations

import pytest

from .conftest import create_user_body, student_profile_input

pytestmark = pytest.mark.asyncio


def _user_message(created_at_ms: int, text: str) -> dict:
    return {
        "role": "user",
        "content": {"type": "text", "text": text},
        "createdAtMs": created_at_ms,
        "turnId": "wamid.test.1",
    }


def _extraction(**overrides) -> dict:
    body = {
        "intent": "test",
        "grounding": 2,
        "boundaries": 2,
        "craft": 2,
        "efficiency": 2,
        "resolution": 2,
        "worked": [],
        "failed": [],
    }
    body.update(overrides)
    return body


async def _make_user(client, auth_headers, phone: str) -> str:
    create = await client.post(
        "/internal/users", headers=auth_headers, json=create_user_body(student_profile_input(phone))
    )
    return create.json()["userId"]


async def test_append_transcript_returns_tip_and_started_at_ms(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977001")
    body = {
        "messages": [_user_message(1_700_000_000_000, "hello")],
        "readIds": [],
        "startedAtMs": None,
    }
    response = await client.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript", headers=auth_headers, json=body
    )
    assert response.status_code == 200
    result = response.json()
    assert result == {"startedAtMs": 1_700_000_000_000, "openedSessionNumber": 1}


async def test_append_transcript_422_empty_messages(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977002")
    body = {"messages": [], "readIds": []}
    response = await client.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript", headers=auth_headers, json=body
    )
    assert response.status_code == 422


async def test_append_transcript_422_missing_read_ids(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977003")
    body = {"messages": [_user_message(1_700_000_000_000, "hi")]}
    response = await client.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript", headers=auth_headers, json=body
    )
    assert response.status_code == 422


async def test_get_session_transcripts_returns_appended_session(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977004")
    append_body = {
        "messages": [_user_message(1_700_000_000_000, "hello")],
        "readIds": ["node-1"],
    }
    await client.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript", headers=auth_headers, json=append_body
    )
    response = await client.get(f"/internal/users/{user_id}/threads/whatsapp/sessions", headers=auth_headers)
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["startedAtMs"] == 1_700_000_000_000
    assert sessions[0]["readNodeIds"] == ["node-1"]
    assert len(sessions[0]["messages"]) == 1
    assert sessions[0]["messages"][0]["content"] == {"type": "text", "text": "hello"}


async def test_get_session_transcripts_404_for_unknown_user(client, auth_headers):
    response = await client.get(
        "/internal/users/no-such-user/threads/whatsapp/sessions", headers=auth_headers
    )
    assert response.status_code == 404


async def test_get_session_transcripts_empty_for_thread_never_used(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977005")
    response = await client.get(f"/internal/users/{user_id}/threads/whatsapp/sessions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_set_session_extraction_404_for_unknown_session(client, auth_headers):
    """No session exists at this startedAtMs; a well-formed lookup-by-id request should 404.

    Committing to 404 before running, per the general mandatory-coverage rule
    for routes that address a resource by id.
    """
    user_id = await _make_user(client, auth_headers, "919999977006")
    response = await client.put(
        f"/internal/users/{user_id}/threads/whatsapp/sessions/1700000000000/extraction",
        headers=auth_headers,
        json=_extraction(),
    )
    assert response.status_code == 404, (
        f"expected 404 for grading a nonexistent session; got {response.status_code}: {response.text}"
    )


async def test_set_session_extraction_then_visible_on_read(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977007")
    append_body = {
        "messages": [_user_message(1_700_000_000_000, "hello")],
        "readIds": [],
    }
    await client.post(
        f"/internal/users/{user_id}/threads/whatsapp/transcript", headers=auth_headers, json=append_body
    )
    extraction_body = _extraction(
        intent="wanted help with algebra",
        grounding=3,
        boundaries=3,
        craft=2,
        efficiency=2,
        resolution=3,
        worked=["explained clearly"],
        failed=[],
    )
    response = await client.put(
        f"/internal/users/{user_id}/threads/whatsapp/sessions/1700000000000/extraction",
        headers=auth_headers,
        json=extraction_body,
    )
    assert response.status_code == 200

    sessions = await client.get(
        f"/internal/users/{user_id}/threads/whatsapp/sessions", headers=auth_headers
    )
    stored = sessions.json()[0]
    assert stored["extraction"] == extraction_body


async def test_set_session_extraction_422_missing_field(client, auth_headers):
    user_id = await _make_user(client, auth_headers, "919999977008")
    response = await client.put(
        f"/internal/users/{user_id}/threads/whatsapp/sessions/1700000000000/extraction",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422
