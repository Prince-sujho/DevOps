"""HTTP the live services actually issue through infra clients.

Oracle is each service README's Routes table (handwritten paths), not a copy of
`client.py`. A renamed path here is a production 404: WhatsApp never reaches
user_service / text_agent / document_worker.

Only the calls the running products make: adapter gate/onboarding/runner/delivery,
and text_agent's document render. Admin influencer routes are not in this file.

Forbidden: `assert request.url.path == f"/internal/users/{user_id}"` built from
the same f-string the client uses.
"""

from __future__ import annotations

import json

import httpx
import pytest

from infra.clients.document_worker import DocumentSource, DocumentWorkerClient
from infra.clients.document_worker import client as document_worker_client
from infra.clients.text_agent.client import TextAgentClient
from infra.clients.text_agent import client as text_agent_client
from infra.clients.users import (
    CreateUserRequest,
    ProfileUpdate,
    StudentProfile,
    StudentProfileInput,
    UserLocation,
    UserTranscriptMessage,
)
from infra.clients.users import client as users_client
from infra.conversation_media import ConversationMediaScope
from infra.curriculum import Subject
from infra.llm.content import TextContent

pytestmark = pytest.mark.asyncio

SECRET = "svc-secret"
USER_ID = "user-1"
PHONE = "919876543210"
STARTED_AT_MS = 1_700_000_000_000

STUDENT = {
    "userId": USER_ID,
    "phone": PHONE,
    "name": "Priya",
    "institution": {"name": "Delhi Public School"},
    "persona": "student",
    "createdAtMs": STARTED_AT_MS,
    "scope": {"grade": 8, "subjects": ["mathematics"]},
}


def _json_response(payload: object, request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=payload, request=request)


def _patch_create_client(monkeypatch, target, captured: list[httpx.Request], handler):
    def factory(base_url: str = "", headers=None, auth_header=None):
        merged = dict(headers or {})
        if auth_header:
            merged[auth_header[0]] = auth_header[1]

        def transport(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return handler(request)

        return httpx.AsyncClient(
            base_url=base_url,
            headers=merged,
            transport=httpx.MockTransport(transport),
        )

    monkeypatch.setattr(target, "create_client", factory)


def _bearer(request: httpx.Request) -> None:
    assert request.headers["Authorization"] == f"Bearer {SECRET}"


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


# --------------------------------------------------------------------------
# user_service README routes the adapter hits
# --------------------------------------------------------------------------


async def test_resolve_phone_posts_the_access_route_with_the_digit_string(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"status": "needs_onboarding", "userId": USER_ID, "user": None},
            request,
        )

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        access = await client.resolve_phone(PHONE)
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == "/internal/access/phone"
    assert _body(request) == {"phone": PHONE}
    assert access.status == "needs_onboarding"


async def test_create_user_posts_the_users_collection_not_a_get(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(STUDENT, request)

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        user = await client.create_user(
            CreateUserRequest(
                profile=StudentProfileInput(
                    phone=PHONE,
                    name="Priya",
                    institution={"name": "Delhi Public School"},
                    scope={"grade": 8, "subjects": [Subject.MATHEMATICS]},
                ),
                preOnboardingTexts=["hi"],
            )
        )
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == "/internal/users"
    assert _body(request)["preOnboardingTexts"] == ["hi"]
    assert user.userId == USER_ID


async def test_session_replay_gets_the_replay_suffix_not_the_raw_session(monkeypatch):
    captured: list[httpx.Request] = []
    session = {
        "startedAtMs": STARTED_AT_MS,
        "lastMessageAtMs": STARTED_AT_MS,
        "readNodeIds": [],
        "messages": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(session, request)

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        replay = await client.get_session_replay(USER_ID, "whatsapp", STARTED_AT_MS)
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "GET"
    assert request.url.path == (
        f"/internal/users/{USER_ID}/threads/whatsapp/sessions/{STARTED_AT_MS}/replay"
    )
    assert replay.startedAtMs == STARTED_AT_MS


async def test_append_transcript_posts_onto_the_whatsapp_thread(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"startedAtMs": STARTED_AT_MS, "openedSessionNumber": 1},
            request,
        )

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        result = await client.append_transcript(
            USER_ID,
            "whatsapp",
            [
                UserTranscriptMessage(
                    createdAtMs=STARTED_AT_MS,
                    turnId="wamid.1",
                    content=TextContent(type="text", text="hi"),
                )
            ],
            read_ids=[],
        )
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == f"/internal/users/{USER_ID}/threads/whatsapp/transcript"
    assert result.openedSessionNumber == 1


async def test_set_location_posts_onto_the_location_slot(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(STUDENT, request)

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        await client.set_location(
            USER_ID, UserLocation(latitude=28.6, longitude=77.2, address="Delhi")
        )
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == f"/internal/users/{USER_ID}/location"
    body = _body(request)
    assert body["latitude"] == 28.6
    assert body["longitude"] == 77.2


async def test_update_profile_posts_onto_the_profile_overlay(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(STUDENT, request)

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        await client.update_profile(USER_ID, ProfileUpdate(name="Priya Sharma"))
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == f"/internal/users/{USER_ID}/profile"
    assert _body(request)["name"] == "Priya Sharma"


async def test_gift_card_delivery_gets_the_card_id_not_the_rewards_list(monkeypatch):
    """ReplyDelivery GETs this route. Hitting /rewards instead would skip the card."""
    captured: list[httpx.Request] = []
    card = {
        "id": "gc-1",
        "productId": "amazon",
        "brand": "Amazon",
        "amountInr": 100,
        "status": "succeeded",
        "createdAtMs": STARTED_AT_MS,
        "instructions": "open the Amazon app",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(card, request)

    _patch_create_client(monkeypatch, users_client, captured, handler)
    client = users_client.UsersClient("http://users.test", SECRET)
    try:
        delivery = await client.get_gift_card(USER_ID, "gc-1")
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "GET"
    assert request.url.path == f"/internal/users/{USER_ID}/gift-cards/gc-1"
    assert "/rewards" not in request.url.path
    assert delivery.instructions == "open the Amazon app"


# --------------------------------------------------------------------------
# text_agent / document_worker README routes
# --------------------------------------------------------------------------


async def test_text_agent_responds_at_the_bare_respond_path(monkeypatch):
    captured: list[httpx.Request] = []
    payload = {
        "contents": [],
        "readIds": [],
        "actions": [],
        "thought": {"responseId": "resp-1", "items": []},
        "usage": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(payload, request)

    _patch_create_client(monkeypatch, text_agent_client, captured, handler)
    client = TextAgentClient("http://agent.test", SECRET)
    try:
        await client.respond(
            user=StudentProfile.model_validate(STUDENT),
            thread_key="whatsapp",
            rows=[],
        )
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == "/respond"
    assert request.url.path != "/internal/respond"
    assert _body(request)["threadKey"] == "whatsapp"


async def test_document_worker_renders_at_the_bare_render_path(monkeypatch):
    captured: list[httpx.Request] = []
    payload = {
        "files": ["notes.docx", "notes.pdf"],
        "previews": ["notes-page-1.png"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(payload, request)

    _patch_create_client(monkeypatch, document_worker_client, captured, handler)
    client = DocumentWorkerClient("http://docs.test", SECRET)
    try:
        rendered = await client.render(
            DocumentSource(
                title="Notes",
                filename="notes",
                markdown="# Notes",
                format="docx",
            ),
            ConversationMediaScope(user_id=USER_ID, thread_key="whatsapp"),
        )
    finally:
        await client.close()

    request = captured[0]
    _bearer(request)
    assert request.method == "POST"
    assert request.url.path == "/render"
    assert rendered.files[0] == "notes.docx"
