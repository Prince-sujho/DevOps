"""Which inbound messages reach the agent, and as what.

Oracles are the adapter README Test Matrix rows: "Blocked phone inbound ->
Canned blocked message only; no transcript append", "Location share -> Profile
location saved; agent acknowledges in one turn", "Button/list tap -> Adapter
records the visible title and runs one agent turn with the tapped id", "Flow
completion -> profile updates persist first, then acknowledge via one agent
turn", and "Hidden-number inbound (no `from`) -> REQUEST_CONTACT_INFO prompt".
"""

from __future__ import annotations

import pytest

from infra.canned import CANNED_RESPONSES
from infra.clients.users import ResolveAccessResult, UserProfile
from infra.conversation import TextMessage
from whatsapp_adapter.app.src.input import PendingAction
from whatsapp_adapter.app.src.service.gate import TurnGate
from whatsapp_adapter.app.src.types import TurnInput

from .fakes import (
    FakeInputs,
    FakeOnboarding,
    FakePending,
    FakeUsers,
    FakeWhatsApp,
    tag_of,
    tagged,
)
from .factories import (
    MESSAGE_ID,
    PROFILE_FLOW_RESPONSE,
    SENDER_ID,
    SENDER_PHONE,
    inbound_contact,
    inbound_flow,
    inbound_location,
    inbound_tap,
    inbound_text,
    student,
)

pytestmark = pytest.mark.asyncio


class Wiring:
    """A TurnGate plus the fakes behind it, so assertions can read both."""

    def __init__(
        self,
        status: str = "allowed",
        *,
        pending: PendingAction | None = None,
        handled: TurnInput | None = None,
        refreshed: UserProfile | None = None,
    ) -> None:
        profile = student()
        access = ResolveAccessResult(
            status=status,
            userId=profile.userId,
            user=profile if status == "allowed" else None,
        )
        self.users = FakeUsers(access=access, refreshed=refreshed)
        self.whatsapp = FakeWhatsApp()
        self.inputs = FakeInputs()
        self.onboarding = FakeOnboarding(handled=handled)
        self.store = FakePending(pending=pending)
        self.gate = TurnGate(
            self.users, self.whatsapp, self.inputs, self.onboarding, self.store
        )


# --------------------------------------------------------------------------
# identity gate
# --------------------------------------------------------------------------


async def test_a_hidden_number_is_asked_for_its_phone_and_yields_no_turn():
    wiring = Wiring()
    hidden = inbound_text(sender_phone=None)

    assert await wiring.gate.process(hidden) is None
    assert wiring.onboarding.phone_requests == [hidden]
    # Nothing was resolved or rendered: there is no identity to resolve yet.
    assert wiring.users.resolved == []
    assert wiring.inputs.calls == []


async def test_a_blocked_sender_gets_only_the_canned_line_and_yields_no_turn():
    """README: canned blocked message only; no transcript append."""
    wiring = Wiring("blocked")

    assert await wiring.gate.process(inbound_text()) is None
    assert wiring.whatsapp.texts == [(SENDER_PHONE, CANNED_RESPONSES.blocked)]
    assert wiring.inputs.calls == []
    assert wiring.onboarding.handled_with == []


async def test_an_unonboarded_sender_is_handed_to_onboarding_with_their_pending_action():
    pending = PendingAction(action="select_persona")
    wiring = Wiring("needs_onboarding", pending=pending)
    inbound = inbound_text()

    assert await wiring.gate.process(inbound) is None
    assert wiring.onboarding.handled_with == [(inbound, pending)]
    assert wiring.inputs.calls == []


async def test_onboarding_completion_is_the_turn_onboarding_returns():
    """Only the Flow completion yields a turn; the gate passes it straight through."""
    completed = TurnInput(user=student(), message=tagged("replay"), inbound_id=MESSAGE_ID)
    wiring = Wiring("needs_onboarding", handled=completed)

    assert await wiring.gate.process(inbound_text()) is completed


async def test_the_senders_phone_is_the_one_looked_up():
    wiring = Wiring()
    await wiring.gate.process(inbound_text())
    assert wiring.users.resolved == [SENDER_PHONE]


# --------------------------------------------------------------------------
# resuming a conversation buffered behind the phone ask
# --------------------------------------------------------------------------


async def test_an_allowed_sender_with_a_pending_phone_action_replays_what_was_buffered():
    buffered = [inbound_text("first"), inbound_text("second")]
    said = [TextMessage(type="text", text="Share your number")]
    pending = PendingAction(action="resolve_phone", messages=buffered, said=said)
    wiring = Wiring(pending=pending)

    turn = await wiring.gate.process(inbound_text())

    assert tag_of(turn.message) == "<replay>"
    assert wiring.inputs.replayed == buffered
    # What Sujho said before a session existed travels with the turn so the
    # runner can record it, and the action is closed exactly once.
    assert turn.said == said
    assert wiring.store.cleared == [SENDER_ID]


async def test_a_pending_action_that_is_not_the_phone_ask_does_not_block_an_allowed_turn():
    wiring = Wiring(pending=PendingAction(action="select_persona"))

    turn = await wiring.gate.process(inbound_text())

    assert tag_of(turn.message) == "<content>"
    assert wiring.store.cleared == []


# --------------------------------------------------------------------------
# dispatch by message kind
# --------------------------------------------------------------------------


async def test_a_text_message_is_rendered_as_content():
    wiring = Wiring()
    turn = await wiring.gate.process(inbound_text())

    assert tag_of(turn.message) == "<content>"
    assert turn.inbound_id == MESSAGE_ID


async def test_usage_billed_while_rendering_content_travels_with_the_turn():
    """Voice-note transcription is billed while rendering; a dropped or copied
    list here would silently un-bill it before the runner ever sees it.
    """
    wiring = Wiring()
    turn = await wiring.gate.process(inbound_text())

    assert len(turn.usage) == 1
    assert turn.usage[0].kind == "audio"


async def test_a_tap_is_rendered_as_a_tap():
    """README: the adapter runs one agent turn with the tapped id."""
    wiring = Wiring()
    turn = await wiring.gate.process(inbound_tap())

    assert tag_of(turn.message) == "<tapped>"
    assert wiring.inputs.calls == ["tapped"]


async def test_a_contact_card_is_rendered_as_a_contact():
    wiring = Wiring()
    turn = await wiring.gate.process(inbound_contact())
    assert tag_of(turn.message) == "<contact>"


async def test_a_location_share_is_saved_to_the_profile_before_the_turn_is_built():
    """README: profile location saved; agent acknowledges in one turn."""
    moved = student(name="Priya after the move")
    wiring = Wiring(refreshed=moved)

    turn = await wiring.gate.process(inbound_location())

    user_id, location = wiring.users.locations[0]
    assert user_id == "u-1"
    assert (location.latitude, location.longitude) == (12.97, 77.59)
    assert location.address == "MG Road, Bengaluru"
    assert tag_of(turn.message) == "<location>"
    # The turn carries the profile the write returned, not the pre-write one.
    assert turn.user is moved


# --------------------------------------------------------------------------
# Flow completions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["documents", "grade"])
async def test_an_agent_routed_flow_feeds_the_model_and_writes_no_profile(route):
    wiring = Wiring()

    turn = await wiring.gate.process(inbound_flow({"route": route, "topic": "algebra"}))

    assert wiring.inputs.calls == [f"flow:{route}"]
    assert tag_of(turn.message) == f"<flow:{route}>"
    assert wiring.users.profile_updates == []


async def test_a_profile_shaped_flow_persists_the_update_then_acknowledges():
    """README: profile updates persist first, then acknowledge via one agent turn."""
    updated = student(name="Priya Sharma")
    wiring = Wiring(refreshed=updated)

    turn = await wiring.gate.process(inbound_flow(PROFILE_FLOW_RESPONSE))

    user_id, update = wiring.users.profile_updates[0]
    assert user_id == "u-1"
    assert update.institution.name == "Delhi Public School"
    assert update.scope.grade == 8
    assert wiring.inputs.calls == ["profile_updated"]
    assert turn.user is updated


async def test_an_unlisted_institution_carries_no_directory_id():
    """A typed-in school has no id; the overlay must not invent one."""
    wiring = Wiring()
    await wiring.gate.process(inbound_flow(PROFILE_FLOW_RESPONSE))

    _, update = wiring.users.profile_updates[0]
    assert update.institution.id is None
