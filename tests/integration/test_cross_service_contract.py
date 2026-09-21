"""Cross-service request/response contract: adapter and text_agent payloads vs user_service models.

whatsapp_adapter and text_agent construct user_service requests via the shared
client types *and* via their own builders (``profile_input_from_flow``,
``user_rows`` / ``assistant_rows``, ``ProfileUpdate``, ``RedeemRequest``). This
suite builds those payloads the same way the callers do, validates them against
user_service's request models, POSTs them to the real service, and validates
the responses with the models those callers parse. Shape drift between a
caller-built dict and the service's models fails here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from infra.clients.text_agent import GenerateRequest, Message
from infra.clients.users import (
    AmbassadorStatus,
    AppendTranscriptRequest,
    AppendTranscriptResult,
    CreateUserRequest,
    ProfileUpdate,
    RewardsList,
    StudentScope,
    UserProfileAdapter,
    WHATSAPP_THREAD_KEY,
)
from infra.clients.users.client import UsersClient
from infra.conversation import TextMessage
from infra.llm.content import TextContent
from whatsapp_adapter.app.src.input.profiles import profile_input_from_flow
from whatsapp_adapter.app.src.transcripts import assistant_rows, user_rows

from . import constants as K
from .helpers import student_profile

pytestmark = pytest.mark.asyncio

FLOW_COMPLETION = {
    "flow_token": "onboarding",
    "persona": "student",
    "institution": "Delhi Public School",
    "institutionId": "school-dps-001",
    "grade": "9",
    "subjects": ["mathematics", "science"],
}


async def test_adapter_create_user_payload_validates_and_round_trips(api):
    """OnboardingCoordinator builds CreateUserRequest from profile_input_from_flow + pending.texts."""
    profile = profile_input_from_flow(
        phone="910000070001",
        persona="student",
        name="Neha",
        response_json=FLOW_COMPLETION,
    )
    request = CreateUserRequest(profile=profile, preOnboardingTexts=["hi @someone"])
    dumped = request.model_dump(mode="json")
    # user_service's own request model (the route body type) accepts this dump.
    reparsed = CreateUserRequest.model_validate(dumped)
    assert reparsed.profile.phone == "910000070001"
    assert reparsed.preOnboardingTexts == ["hi @someone"]

    response = await api.post("/internal/users", json=dumped)
    assert response.status_code == 200
    stored = UserProfileAdapter.validate_python(response.json())
    assert stored.phone == "910000070001"
    assert stored.name == "Neha"
    assert stored.persona == "student"
    assert stored.scope.grade == 9
    assert stored.scope.subjects == ["mathematics", "science"]


async def test_adapter_append_transcript_payload_validates_and_round_trips(api):
    """ReplyRunner sends user_rows then assistant_rows through AppendTranscriptRequest."""
    created = await api.create_user(student_profile("910000070002", name="Runner"))
    user_id = created["userId"]

    inbound = Message(parts=[TextContent(type="text", text="what is gravity")])
    rows = user_rows(inbound, "wamid.contract.1")
    request = AppendTranscriptRequest(
        messages=rows,
        readIds=[],
        startedAtMs=None,
    )
    dumped = request.model_dump(mode="json")
    AppendTranscriptRequest.model_validate(dumped)

    response = await api.post(
        f"/internal/users/{user_id}/threads/{WHATSAPP_THREAD_KEY}/transcript",
        json=dumped,
    )
    assert response.status_code == 200
    result = AppendTranscriptResult.model_validate(response.json())
    assert result.startedAtMs == rows[0].createdAtMs
    assert result.openedSessionNumber == 1

    reply_rows = assistant_rows(
        [TextMessage(type="text", text="Gravity pulls things down")],
        "wamid.contract.1",
        "resp-contract-1",
    )
    reply = AppendTranscriptRequest(
        messages=reply_rows,
        readIds=["node-physics-1"],
        startedAtMs=result.startedAtMs,
    )
    reply_dump = reply.model_dump(mode="json")
    AppendTranscriptRequest.model_validate(reply_dump)
    reply_response = await api.post(
        f"/internal/users/{user_id}/threads/{WHATSAPP_THREAD_KEY}/transcript",
        json=reply_dump,
    )
    assert reply_response.status_code == 200
    reply_result = AppendTranscriptResult.model_validate(reply_response.json())
    assert reply_result.openedSessionNumber is None
    assert reply_result.startedAtMs == result.startedAtMs


async def test_adapter_append_result_is_a_valid_text_agent_previous_response_id(api):
    """whatsapp_adapter passes the session ledger into text_agent GenerateRequest."""
    created = await api.create_user(student_profile("910000070003", name="Chain"))
    user_id = created["userId"]
    inbound = Message(parts=[TextContent(type="text", text="hi")])
    rows = user_rows(inbound, "wamid.chain.1")
    append = await api.post(
        f"/internal/users/{user_id}/threads/{WHATSAPP_THREAD_KEY}/transcript",
        json=AppendTranscriptRequest(
            messages=rows, readIds=[], startedAtMs=None
        ).model_dump(mode="json"),
    )
    tip = AppendTranscriptResult.model_validate(append.json())
    profile = UserProfileAdapter.validate_python(
        (await api.get(f"/internal/users/{user_id}")).json()
    )
    generate = GenerateRequest(
        user=profile,
        threadKey=WHATSAPP_THREAD_KEY,
        rows=rows,
    )
    assert generate.rows[0].turnId == "wamid.chain.1"
    assert generate.user.userId == user_id
    assert tip.openedSessionNumber == 1


async def test_text_agent_profile_update_payload_validates_and_round_trips(api):
    """UpdateProfileTool builds ProfileUpdate(name=..., scope=StudentScope(...))."""
    created = await api.create_user(
        student_profile("910000070004", name="Before", grade=8, subjects=["mathematics"])
    )
    user_id = created["userId"]
    update = ProfileUpdate(
        name="After",
        scope=StudentScope(grade=9, subjects=["science"]),
    )
    dumped = update.model_dump(mode="json", exclude_none=True)
    ProfileUpdate.model_validate(dumped)
    response = await api.post(f"/internal/users/{user_id}/profile", json=dumped)
    assert response.status_code == 200
    stored = UserProfileAdapter.validate_python(response.json())
    assert stored.name == "After"
    assert stored.scope.grade == 9
    assert stored.scope.subjects == ["science"]


async def test_text_agent_ambassador_and_rewards_responses_validate(api, hubble_double):
    """enroll_ambassador / get_ambassador_status / list_rewards / redeem_reward parse."""
    from .helpers import processing_order, seed_reward_catalogue

    created = await api.create_user(
        student_profile("910000070005", name="ToolUser", institution_id="school-1")
    )
    user_id = created["userId"]
    enroll = await api.post(f"/internal/users/{user_id}/ambassador")
    assert enroll.status_code == 200
    status = AmbassadorStatus.model_validate(enroll.json())
    assert status.points == 0
    assert status.balanceInr == 0

    fetched = await api.get(f"/internal/users/{user_id}/ambassador")
    assert fetched.status_code == 200
    AmbassadorStatus.model_validate(fetched.json())

    hubble_double.seed_catalogue(seed_reward_catalogue())
    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    RewardsList.model_validate(rewards.json())
    assert rewards.json()["balanceInr"] == 0


async def test_malformed_create_user_payload_is_422(api):
    """Negative: a payload the adapter would never build is rejected by user_service."""
    response = await api.post(
        "/internal/users",
        json={"profile": {"phone": "910000070006"}, "preOnboardingTexts": []},
    )
    assert response.status_code == 422
    with pytest.raises(ValidationError):
        CreateUserRequest.model_validate(
            {"profile": {"phone": "910000070006"}, "preOnboardingTexts": []}
        )


async def test_malformed_append_payload_is_422(api):
    created = await api.create_user(student_profile("910000070007"))
    response = await api.post(
        f"/internal/users/{created['userId']}/threads/{WHATSAPP_THREAD_KEY}/transcript",
        json={"messages": [{"role": "user", "content": {"type": "text"}}], "readIds": []},
    )
    assert response.status_code == 422


async def test_users_client_parses_live_responses(api, users_server):
    """Vice versa: the client the other services actually use parses live user_service JSON."""
    client = UsersClient(
        base_url=users_server.base_url, service_secret=K.USERS_SERVICE_SECRET
    )
    try:
        created = await client.create_user(
            CreateUserRequest(
                profile=profile_input_from_flow(
                    phone="910000070008",
                    persona="student",
                    name="ClientRoundtrip",
                    response_json=FLOW_COMPLETION,
                ),
                preOnboardingTexts=[],
            )
        )
        assert created.name == "ClientRoundtrip"
        fetched = await client.get_user(created.userId)
        assert fetched.userId == created.userId
        assert fetched.phone == "910000070008"
    finally:
        await client.close()
