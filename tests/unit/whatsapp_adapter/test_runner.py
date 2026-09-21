"""The transcript ledger: every row is an event that happened, recorded when it did.

Oracle is the adapter README line 115: the first append resolves the session's
`startedAtMs` and later appends in the turn pin to it; the response's `actions`
are appended as trace rows with `readIds` at once, each stamped with its round's
`responseId`; if more inbound landed meanwhile the reply is "held -- never sent,
never recorded"; and when the sender is quiet the reply is delivered and
recorded, "its `thought` as trace rows, then exactly what was said as assistant
rows, all stamped with the speaking round's `responseId`".
"""

from __future__ import annotations

import pytest

from infra.canned import CANNED_RESPONSES
from infra.clients.text_agent import GenerateResponse
from infra.clients.users import WHATSAPP_THREAD_KEY, SessionTranscript
from infra.conversation import TextMessage
from infra.llm import Round
from infra.llm.oai.types.trace import ReasoningItem
from whatsapp_adapter.app.src.service.runner import ReplyRunner
from whatsapp_adapter.app.src.transcripts import user_rows
from whatsapp_adapter.app.src.types import PendingTurn, TurnInput

from .fakes import (
    SESSION_MS,
    FakeConversions,
    FakeDelivery,
    FakeTextAgent,
    FakeUsage,
    FakeUsers,
    FakeWhatsApp,
    tagged,
)
from .factories import SENDER_PHONE, student

pytestmark = pytest.mark.asyncio

FIRST_INBOUND = "wamid.FIRST"
SECOND_INBOUND = "wamid.SECOND"
THOUGHT_ID = "resp_thought"
ACTION_ID = "resp_action"


def a_round(response_id: str, *item_ids: str) -> Round:
    """One response and the replayable items it emitted."""
    return Round(
        responseId=response_id,
        items=[
            ReasoningItem(id=item_id, summary=[], encrypted_content="enc")
            for item_id in item_ids
        ],
    )


def a_response(
    *,
    actions: list[Round] | None = None,
    read_ids: list[str] | None = None,
) -> GenerateResponse:
    """One agent turn: optional tool rounds, then the speaking round."""
    return GenerateResponse(
        contents=[TextMessage(type="text", text="x squared is 4.")],
        readIds=read_ids or [],
        actions=actions or [],
        thought=a_round(THOUGHT_ID, "rs_thought"),
        usage=[],
    )


def a_contribution(inbound_id: str = FIRST_INBOUND, **overrides) -> TurnInput:
    """One gated inbound, rendered and ready to record."""
    fields = {
        "user": student(),
        "message": tagged("content"),
        "inbound_id": inbound_id,
    }
    return TurnInput(**{**fields, **overrides})


class Wiring:
    """A ReplyRunner plus the fakes behind it."""

    def __init__(
        self,
        response: GenerateResponse | None = None,
        *,
        opened_session_number: int | None = 1,
        delivery_error: Exception | None = None,
    ) -> None:
        replay = SessionTranscript(
            startedAtMs=SESSION_MS,
            lastMessageAtMs=SESSION_MS,
            readNodeIds=[],
            messages=user_rows(tagged("earlier"), FIRST_INBOUND),
        )
        self.users = FakeUsers(replay=replay, opened_session_number=opened_session_number)
        self.text_agent = FakeTextAgent(response or a_response())
        self.delivery = FakeDelivery(error=delivery_error)
        self.whatsapp = FakeWhatsApp()
        self.usage = FakeUsage()
        self.conversions = FakeConversions()
        self.runner = ReplyRunner(
            self.text_agent,
            self.delivery,
            self.users,
            self.whatsapp,
            self.usage,
            self.conversions,
        )
        self.replay = replay


def an_open_turn() -> PendingTurn:
    """A turn already pinned to an open session."""
    return PendingTurn(user=student(), inbound_ids=[FIRST_INBOUND], started_at_ms=SESSION_MS)


# --------------------------------------------------------------------------
# record: the opening inbound
# --------------------------------------------------------------------------


async def test_the_opening_inbound_names_the_turn_and_opens_the_session():
    wiring = Wiring()

    turn = await wiring.runner.record(None, a_contribution())

    assert turn.turn_id == FIRST_INBOUND
    assert turn.inbound_ids == [FIRST_INBOUND]
    # The session is not known until the append resolves it.
    assert turn.started_at_ms == SESSION_MS


async def test_the_first_append_is_unpinned_because_it_is_what_resolves_the_session():
    wiring = Wiring()

    await wiring.runner.record(None, a_contribution())

    append = wiring.users.appends[0]
    assert append.started_at_ms is None
    assert append.user_id == "u-1"
    assert append.thread_key == WHATSAPP_THREAD_KEY


async def test_recording_the_inbound_claims_no_reads_because_nothing_ran_yet():
    """Reads are the model's own doing, attributed at generation time; an
    inbound message cannot have read anything before the agent even ran.
    """
    wiring = Wiring()

    await wiring.runner.record(None, a_contribution())

    assert wiring.users.appends[0].read_ids == []


async def test_what_sujho_said_pre_session_is_recorded_before_the_users_own_words():
    """Onboarding bubbles happened first, so the ledger must read in that order."""
    wiring = Wiring()
    said = [TextMessage(type="text", text="Perfect, thanks!")]
    contribution = a_contribution(said=said, message=tagged("replay"))

    await wiring.runner.record(None, contribution)

    append = wiring.users.appends[0]
    assert append.roles == ["assistant", "user"]
    assert append.turn_ids == [FIRST_INBOUND, FIRST_INBOUND]
    # Nothing said before a session existed belongs to a response.
    assert append.response_ids == [None, None]


async def test_rendering_the_inbound_is_billed_to_the_session_the_append_resolved():
    """The session is known only now, so transcription bills to it, not to nothing."""
    wiring = Wiring()

    await wiring.runner.record(None, a_contribution())

    (booking,) = wiring.usage.of_kind("transcription")
    assert booking.sessionStartedAtMs == SESSION_MS
    assert booking.turnId == FIRST_INBOUND
    assert booking.userId == "u-1"
    assert booking.threadKey == WHATSAPP_THREAD_KEY


async def test_the_append_result_is_handed_to_the_conversions_reporter():
    """Meta hears about every session an ad user opens; the reporter decides which."""
    wiring = Wiring()

    await wiring.runner.record(None, a_contribution())

    (user_id, result) = wiring.conversions.reported[0]
    assert user_id == "u-1"
    assert result.openedSessionNumber == 1
    assert result.startedAtMs == SESSION_MS


# --------------------------------------------------------------------------
# record: a later inbound joining the same burst
# --------------------------------------------------------------------------


async def test_a_later_inbound_joins_the_turn_the_first_one_named():
    wiring = Wiring()
    turn = an_open_turn()

    joined = await wiring.runner.record(turn, a_contribution(SECOND_INBOUND))

    assert joined.turn_id == FIRST_INBOUND
    assert joined.inbound_ids == [FIRST_INBOUND, SECOND_INBOUND]


async def test_a_later_append_is_pinned_so_it_cannot_open_a_second_session():
    wiring = Wiring()

    await wiring.runner.record(an_open_turn(), a_contribution(SECOND_INBOUND))

    assert wiring.users.appends[0].started_at_ms == SESSION_MS


async def test_a_later_inbounds_rows_are_stamped_with_the_opening_inbounds_turn_id():
    wiring = Wiring()

    await wiring.runner.record(an_open_turn(), a_contribution(SECOND_INBOUND))

    assert wiring.users.appends[0].turn_ids == [FIRST_INBOUND]


async def test_a_later_inbounds_rendering_is_billed_to_the_turn_that_opened_the_burst():
    """One turn, one booking key: the burst's cost must not split across inbounds."""
    wiring = Wiring()

    await wiring.runner.record(an_open_turn(), a_contribution(SECOND_INBOUND))

    (booking,) = wiring.usage.of_kind("transcription")
    assert booking.turnId == FIRST_INBOUND
    assert booking.sessionStartedAtMs == SESSION_MS


async def test_the_profile_from_the_latest_inbound_replaces_the_one_on_the_turn():
    """A location or Flow update mid-burst must not be overwritten by a stale profile."""
    wiring = Wiring()
    turn = an_open_turn()
    moved = student(name="Priya after the update")

    joined = await wiring.runner.record(turn, a_contribution(SECOND_INBOUND, user=moved))

    assert joined.user is moved


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------


async def test_the_agent_is_run_over_this_turns_own_session_replay():
    wiring = Wiring()
    turn = an_open_turn()

    await wiring.runner.generate(turn)

    assert wiring.users.replays_read == [("u-1", WHATSAPP_THREAD_KEY, SESSION_MS)]
    assert wiring.text_agent.asked_with == [wiring.replay.messages]


async def test_generation_is_billed_even_though_the_reply_may_never_be_sent():
    """Money was spent at respond time; a held reply does not un-spend it.

    The turn carries two inbounds so the booking's turn id is distinguishable
    from the latest inbound id -- a burst bills once, to the turn that named it.
    """
    wiring = Wiring()
    turn = PendingTurn(
        user=student(), inbound_ids=[FIRST_INBOUND, SECOND_INBOUND], started_at_ms=SESSION_MS
    )

    await wiring.runner.generate(turn)

    (booking,) = wiring.usage.of_kind("generation")
    assert booking.sessionStartedAtMs == SESSION_MS
    assert booking.turnId == FIRST_INBOUND
    assert booking.userId == "u-1"


async def test_tool_rounds_are_recorded_at_once_with_what_they_read():
    """The rounds already happened, so they are on the ledger before any reply is sent."""
    wiring = Wiring(a_response(actions=[a_round(ACTION_ID, "rs_a", "rs_b")], read_ids=["node-1"]))

    await wiring.runner.generate(an_open_turn())

    append = wiring.users.appends[0]
    assert append.roles == ["trace", "trace"]
    # Each trace row is stamped with the round that emitted it, not the speaking one.
    assert append.response_ids == [ACTION_ID, ACTION_ID]
    assert append.read_ids == ["node-1"]
    assert append.started_at_ms == SESSION_MS


async def test_a_pure_speech_turn_records_nothing_at_generation_time():
    """No tool rounds means no rows; an empty append would be a lie about the ledger."""
    wiring = Wiring(a_response(actions=[]))

    await wiring.runner.generate(an_open_turn())

    assert wiring.users.appends == []


async def test_typing_shows_against_the_latest_inbound_while_the_agent_thinks():
    wiring = Wiring()
    turn = PendingTurn(
        user=student(), inbound_ids=[FIRST_INBOUND, SECOND_INBOUND], started_at_ms=SESSION_MS
    )

    await wiring.runner.generate(turn)

    assert wiring.whatsapp.typing == [SECOND_INBOUND]


# --------------------------------------------------------------------------
# deliver
# --------------------------------------------------------------------------


async def test_the_reply_is_sent_against_the_latest_inbound():
    wiring = Wiring()
    response = a_response()
    turn = PendingTurn(
        user=student(), inbound_ids=[FIRST_INBOUND, SECOND_INBOUND], started_at_ms=SESSION_MS
    )

    await wiring.runner.deliver(turn, response)

    assert wiring.delivery.sent == [("u-1", SECOND_INBOUND, response)]
    assert len(wiring.users.appends) == 1


async def test_a_reply_that_fails_to_send_is_never_recorded():
    """Sending first is what makes the ledger honest.

    README: a held reply is "never sent, never recorded". Recording before
    sending would leave the transcript claiming Sujho said something the user
    never saw, and the next generation would read that lie back to the model.
    """
    wiring = Wiring(delivery_error=RuntimeError("whatsapp rejected the send"))

    with pytest.raises(RuntimeError):
        await wiring.runner.deliver(an_open_turn(), a_response())

    assert wiring.users.appends == []


async def test_the_thought_is_recorded_then_exactly_what_was_said():
    wiring = Wiring()
    response = a_response()

    await wiring.runner.deliver(an_open_turn(), response)

    append = wiring.users.appends[0]
    assert append.roles == ["trace", "assistant"]
    # Both stamped with the speaking round, so the ledger says who said it.
    assert append.response_ids == [THOUGHT_ID, THOUGHT_ID]
    assert append.turn_ids == [FIRST_INBOUND, FIRST_INBOUND]
    assert append.started_at_ms == SESSION_MS


async def test_delivering_reads_nothing_new_so_it_claims_no_further_reads():
    wiring = Wiring()

    await wiring.runner.deliver(an_open_turn(), a_response())

    assert wiring.users.appends[0].read_ids == []


# --------------------------------------------------------------------------
# fail
# --------------------------------------------------------------------------


async def test_a_failed_turn_sends_the_canned_error_and_records_it_as_sujhos_words():
    wiring = Wiring()

    await wiring.runner.fail(an_open_turn())

    assert wiring.whatsapp.texts == [(SENDER_PHONE, CANNED_RESPONSES.error)]
    append = wiring.users.appends[0]
    assert append.roles == ["assistant"]
    assert append.rows[0].content.text == CANNED_RESPONSES.error
    # No round spoke it, so it is attributed to none.
    assert append.response_ids == [None]
    assert append.started_at_ms == SESSION_MS
