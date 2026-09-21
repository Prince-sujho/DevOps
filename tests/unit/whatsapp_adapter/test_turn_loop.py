"""Per-sender batching: absorb what arrives, speak only once the sender is quiet.

Oracle is the adapter README's in-process ordering tradeoff ("one sender's full
lifecycle is serialized within a service instance") and the loop's own rule
that a reply is withheld while more inbound is still waiting.
"""

from __future__ import annotations

import asyncio

import pytest

from whatsapp_adapter.app.src.service.turns import TurnLoop
from whatsapp_adapter.app.src.types import TurnInput

from .fakes import FakeRunner, tagged
from .factories import inbound_text, student

pytestmark = pytest.mark.asyncio


async def admit_everything(inbound):  # noqa: RUF029  (Gate must be a coroutine)
    """A gate that lets every message through as its own contribution."""
    return TurnInput(user=student(), message=tagged("content"), inbound_id=inbound.message_id)


async def admit_nothing(inbound):  # noqa: RUF029  (Gate must be a coroutine)
    """A gate that drops everything, as it does for blocked or onboarding senders."""
    return None


async def drain(loop: TurnLoop) -> None:
    """Wait for every in-flight sender loop to retire.

    TurnLoop is fire-and-forget by design and hands back no handle, so the
    tests await its task map directly rather than sleeping and hoping.
    """
    while loop._tasks:
        await asyncio.gather(*list(loop._tasks.values()))


async def test_one_message_is_recorded_generated_then_delivered():
    runner = FakeRunner()
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text())
    await drain(loop)

    assert runner.calls == ["record", "generate", "deliver"]


async def test_a_gated_out_message_never_reaches_the_runner():
    """A blocked or mid-onboarding sender produces no turn, so nothing is generated."""
    runner = FakeRunner()
    loop = TurnLoop(admit_nothing, runner)

    loop.submit(inbound_text())
    await drain(loop)

    assert runner.calls == []


async def test_messages_already_waiting_together_become_one_turn_spoken_once():
    runner = FakeRunner()
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text("first", message_id="wamid.1"))
    loop.submit(inbound_text("second", message_id="wamid.2"))
    await drain(loop)

    assert runner.calls == ["record", "record", "generate", "deliver"]
    (turn, _), = runner.delivered
    assert turn.inbound_ids == ["wamid.1", "wamid.2"]


async def test_a_message_landing_during_generation_withholds_that_reply():
    """More arrived while generating, so the loop absorbs it and generates again
    rather than speaking to a sender who is still typing.
    """
    submitted: list[bool] = []

    def land_one_more():
        """Exactly one late message, or the loop would never fall quiet."""
        if not submitted:
            submitted.append(True)
            loop.submit(inbound_text("late", message_id="wamid.2"))

    runner = FakeRunner(on_generate=land_one_more)
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text("first", message_id="wamid.1"))
    await drain(loop)

    assert runner.calls == ["record", "generate", "record", "generate", "deliver"]
    # One reply, carrying both inbound ids: the burst was spoken to once.
    assert len(runner.delivered) == 1
    (turn, _), = runner.delivered
    assert turn.inbound_ids == ["wamid.1", "wamid.2"]


async def test_a_generation_failure_is_absorbed_and_the_turn_is_failed():
    runner = FakeRunner(fail_generate=True)
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text())
    await drain(loop)

    assert runner.calls == ["record", "generate", "fail"]
    assert len(runner.failed) == 1


async def test_a_gate_failure_before_any_turn_exists_fails_nothing():
    """With no turn open there is nothing to apologise for, so fail is not called."""

    async def gate_that_breaks(inbound):  # noqa: RUF029  (Gate must be a coroutine)
        raise RuntimeError("gate exploded")

    runner = FakeRunner()
    loop = TurnLoop(gate_that_breaks, runner)

    loop.submit(inbound_text())
    await drain(loop)

    assert runner.calls == []
    assert runner.failed == []


async def test_the_loop_keeps_serving_the_next_message_after_a_failure():
    runner = FakeRunner(fail_generate=True)
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text("first", message_id="wamid.1"))
    await drain(loop)
    loop.submit(inbound_text("second", message_id="wamid.2"))
    await drain(loop)

    assert runner.calls == ["record", "generate", "fail"] * 2


async def test_a_gated_out_message_mid_burst_does_not_erase_the_turn_already_open():
    """A reaction or dropped type arriving between two real messages must not
    lose the turn the first message already opened.
    """

    async def admit_only_first(inbound):  # noqa: RUF029  (Gate must be a coroutine)
        if inbound.message_id != "wamid.1":
            return None
        return TurnInput(user=student(), message=tagged("content"), inbound_id="wamid.1")

    runner = FakeRunner()
    loop = TurnLoop(admit_only_first, runner)

    loop.submit(inbound_text("first", message_id="wamid.1"))
    loop.submit(inbound_text("dropped", message_id="wamid.2"))
    await drain(loop)

    assert runner.calls == ["record", "generate", "deliver"]
    (turn, _), = runner.delivered
    assert turn.inbound_ids == ["wamid.1"]


async def test_two_senders_are_served_as_two_independent_turns():
    runner = FakeRunner()
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text(sender_id="sender-a", message_id="wamid.a"))
    loop.submit(inbound_text(sender_id="sender-b", message_id="wamid.b"))
    await drain(loop)

    assert len(runner.delivered) == 2
    assert sorted(turn.inbound_ids[0] for turn, _ in runner.delivered) == ["wamid.a", "wamid.b"]


async def test_a_sender_queue_retires_once_it_empties():
    """Nothing is left behind per sender, so a busy day does not leak queues."""
    runner = FakeRunner()
    loop = TurnLoop(admit_everything, runner)

    loop.submit(inbound_text())
    await drain(loop)

    assert loop._tasks == {}
    assert loop._pending == {}
