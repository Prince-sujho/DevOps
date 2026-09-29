"""Cross-service contract: callers' payloads vs user_service's models, over the
wire.

whatsapp_adapter and text_agent build user_service requests with their own
builders (``profile_input_from_flow``, ``user_rows`` / ``assistant_rows``,
``ProfileUpdate``) and send them through ``UsersClient``. This suite builds
those payloads the way the callers do, sends them to the real service, and
parses the responses with the models the callers parse. Services deploy one at
a time, so shape drift between them fails here, not in production.
"""

from __future__ import annotations

import pytest

from infra.clients.users import (
    WHATSAPP_THREAD_KEY,
    AmbassadorStatus,
    CreateUserRequest,
    ProfileUpdate,
    RewardsList,
    StudentScope,
    UserProfileAdapter,
    assistant_rows,
    user_rows,
)
from infra.clients.users.client import UsersClient
from infra.conversation import TextMessage
from infra.llm.content import TextContent
from whatsapp_adapter.app.src.input.profiles import profile_input_from_flow

from . import constants as K
from .helpers import seed_reward_catalogue, student_profile

pytestmark = pytest.mark.asyncio


def _flow_completion(name: str) -> dict:
    """A completed onboarding Flow response body, as Meta would send it.

    Args:
        name: the completing user's name.
    Returns:
        The Flow completion body.
    Raises:
        None.
    """
    return {
        "flow_token": "onboarding",
        "name": name,
        "institution": "Delhi Public School",
        "institutionId": "school-dps-001",
        "grade": "9",
        "subjects": ["mathematics", "science"],
    }


@pytest.fixture
async def users_client(users_server):
    """The real UsersClient other services use, bound to the running test
    server.

    Args:
        users_server: the running user_service server thread.
        Yields:
        The UsersClient.
    Returns:
        The UsersClient bound to the running test server.
    Raises:
        None.
    """
    client = UsersClient(
        base_url=users_server.base_url, service_secret=K.USERS_SERVICE_SECRET
    )
    yield client
    await client.close()


async def test_adapter_create_user_payload_validates_and_round_trips(api):
    """The adapter's profile_input_from_flow output validates against
    user_service and round-trips.

    Args:
        api: the UsersApi test client.
    Returns:
        None.
    Raises:
        None.
    """
    flow = _flow_completion("Neha")
    profile = profile_input_from_flow(
        phone="910000070001", persona="student", response_json=flow
    )
    request = CreateUserRequest(profile=profile, preOnboardingTexts=["hi"])

    response = await api.post(
        "/internal/users", json=request.model_dump(mode="json")
    )
    assert response.status_code == 200
    stored = UserProfileAdapter.validate_python(response.json())
    assert stored.phone == profile.phone
    assert stored.name == flow["name"]
    assert stored.persona == profile.persona
    assert stored.scope == profile.scope


async def test_adapter_transcript_rows_append_through_the_client(
    api, users_client
):
    """The adapter's user_rows/assistant_rows builders append through the real
    UsersClient.

    Args:
        api: the UsersApi test client.
        users_client: the real UsersClient bound to the running server.
    Returns:
        None.
    Raises:
        None.
    """
    created = await api.create_user(
        student_profile("910000070002", name="Runner")
    )
    user_id = created["userId"]

    inbound = user_rows(
        [TextContent(type="text", text="what is gravity")], "wamid.contract.1"
    )
    opened = await users_client.append_transcript(
        user_id, WHATSAPP_THREAD_KEY, inbound
    )
    assert opened.startedAtMs == inbound[0].createdAtMs
    assert opened.openedSessionNumber == 1

    reply = assistant_rows(
        [TextMessage(type="text", text="Gravity pulls things down")],
        "wamid.contract.1",
        "resp-contract-1",
    )
    joined = await users_client.append_transcript(
        user_id, WHATSAPP_THREAD_KEY, reply, started_at_ms=opened.startedAtMs
    )
    assert joined.startedAtMs == opened.startedAtMs
    assert joined.openedSessionNumber is None

    session = await users_client.get_session_transcript(
        user_id, WHATSAPP_THREAD_KEY, opened.startedAtMs
    )
    assert [row.role for row in session.messages] == [
        row.role for row in inbound + reply
    ]


async def test_text_agent_profile_update_payload_validates_and_round_trips(
    api, users_client
):
    """text_agent's ProfileUpdate payload validates against user_service and
    round-trips.

    Args:
        api: the UsersApi test client.
        users_client: the real UsersClient bound to the running server.
    Returns:
        None.
    Raises:
        None.
    """
    created = await api.create_user(
        student_profile(
            "910000070004", name="Before", grade=8, subjects=["mathematics"]
        )
    )
    update = ProfileUpdate(
        name="After", scope=StudentScope(grade=9, subjects=["science"])
    )

    stored = await users_client.update_profile(created["userId"], update)
    assert stored.name == update.name
    assert stored.scope == update.scope


async def test_text_agent_ambassador_and_rewards_responses_validate(
    api, hubble_double
):
    """user_service's ambassador/rewards responses validate against text_agent's
    models.

    Args:
        api: the UsersApi test client.
        hubble_double: the scriptable Hubble HTTP double.
    Returns:
        None.
    Raises:
        None.
    """
    created = await api.create_user(
        student_profile(
            "910000070005", name="ToolUser", institution_id="school-1"
        )
    )
    user_id = created["userId"]
    enroll = await api.post(f"/internal/users/{user_id}/ambassador")
    assert enroll.status_code == 200
    status = AmbassadorStatus.model_validate(enroll.json())
    assert status.points == 0

    fetched = await api.get(f"/internal/users/{user_id}/ambassador")
    assert fetched.status_code == 200
    AmbassadorStatus.model_validate(fetched.json())

    hubble_double.seed_catalogue(seed_reward_catalogue())
    rewards = await api.get(f"/internal/users/{user_id}/rewards")
    assert rewards.status_code == 200
    assert (
        RewardsList.model_validate(rewards.json()).balanceInr
        == status.balanceInr
    )


async def test_users_client_parses_live_responses(users_client):
    """The real UsersClient parses live user_service responses without error.

    Args:
        users_client: the real UsersClient bound to the running server.
    Returns:
        None.
    Raises:
        None.
    """
    flow = _flow_completion("ClientRoundtrip")
    created = await users_client.create_user(
        CreateUserRequest(
            profile=profile_input_from_flow(
                phone="910000070008", persona="student", response_json=flow
            ),
            preOnboardingTexts=[],
        )
    )
    assert created.name == flow["name"]
    fetched = await users_client.get_user(created.userId)
    assert fetched.userId == created.userId
    assert fetched.phone == created.phone
