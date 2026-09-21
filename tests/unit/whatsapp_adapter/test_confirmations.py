"""The barrier that keeps sequential bubbles in display order.

README is silent on status webhooks. Independently statable: wait blocks until
that wamid is confirmed; a dropped status must lapse instead of hanging the
turn; a waiter must not leak on timeout, success, or cancellation; confirming
one id must not release another.
"""

from __future__ import annotations

import asyncio

import pytest

from whatsapp_adapter.app.src.output import confirmations as confirmations_module
from whatsapp_adapter.app.src.output.confirmations import DeliveryConfirmations

# `confirm_sent` is sync, so one test here needs no event loop; the asyncio
# mark goes on each async test rather than the whole module.
pytestmark = pytest.mark.boundary

WAMID = "wamid.out1"


@pytest.mark.asyncio
async def test_a_confirmed_send_unblocks_its_waiter():
    barrier = DeliveryConfirmations()
    waiting = asyncio.create_task(barrier.wait(WAMID))
    # Let `wait` register its event before the status arrives.
    await asyncio.sleep(0)

    barrier.confirm_sent(WAMID)
    await asyncio.wait_for(waiting, timeout=1)

    assert waiting.done()


@pytest.mark.asyncio
async def test_waiting_blocks_until_the_confirmation_actually_arrives():
    """The whole point of the barrier: it must not fall through early, or the
    next bubble could overtake this one. Shown by demanding the wait still be
    pending after the loop has had every chance to run it.
    """
    barrier = DeliveryConfirmations()
    waiting = asyncio.create_task(barrier.wait(WAMID))
    await asyncio.sleep(0)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(waiting), timeout=0.01)

    barrier.confirm_sent(WAMID)
    await asyncio.wait_for(waiting, timeout=1)
    assert waiting.result() is None


@pytest.mark.asyncio
async def test_a_dropped_status_webhook_lapses_instead_of_hanging_the_turn(monkeypatch):
    """A status that never arrives must cost one timeout, not the whole turn.
    The timeout is shortened here so the test does not wait the real 10s.
    """
    monkeypatch.setattr(confirmations_module, "DELIVERY_BARRIER_TIMEOUT_SECONDS", 0.01)
    barrier = DeliveryConfirmations()

    await asyncio.wait_for(barrier.wait(WAMID), timeout=1)


@pytest.mark.asyncio
async def test_a_lapsed_wait_leaves_no_waiter_behind(monkeypatch):
    """The registry is cleaned in `finally`, so the timeout path cannot leak."""
    monkeypatch.setattr(confirmations_module, "DELIVERY_BARRIER_TIMEOUT_SECONDS", 0.01)
    barrier = DeliveryConfirmations()

    await barrier.wait(WAMID)

    assert barrier._events == {}


@pytest.mark.asyncio
async def test_a_confirmed_wait_leaves_no_waiter_behind():
    """One entry per bubble would otherwise accumulate for the process's life."""
    barrier = DeliveryConfirmations()
    waiting = asyncio.create_task(barrier.wait(WAMID))
    await asyncio.sleep(0)
    barrier.confirm_sent(WAMID)
    await asyncio.wait_for(waiting, timeout=1)

    assert barrier._events == {}


@pytest.mark.asyncio
async def test_a_cancelled_wait_leaves_no_waiter_behind():
    """Cleanup lives in `finally`, not on the timeout path, because a turn can
    be cancelled mid-wait (the loop drops a failed turn, or the process shuts
    down). Cleaning up only on timeout and success would leak one event per
    cancelled turn, forever.
    """
    barrier = DeliveryConfirmations()
    waiting = asyncio.create_task(barrier.wait(WAMID))
    await asyncio.sleep(0)
    assert barrier._events != {}, "the waiter was never registered"

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert barrier._events == {}


def test_confirming_a_message_nobody_awaits_is_harmless():
    """Status webhooks arrive for every send, including the last bubble of a
    turn, which is deliberately never waited on.
    """
    barrier = DeliveryConfirmations()

    barrier.confirm_sent("wamid.never-awaited")

    assert barrier._events == {}


@pytest.mark.asyncio
async def test_confirming_one_message_does_not_release_another():
    """Two bubbles in flight must be released by their own ids; releasing the
    wrong one would let a later bubble overtake an unsent earlier one.
    """
    barrier = DeliveryConfirmations()
    first = asyncio.create_task(barrier.wait("wamid.first"))
    second = asyncio.create_task(barrier.wait("wamid.second"))
    await asyncio.sleep(0)

    barrier.confirm_sent("wamid.first")
    await asyncio.wait_for(first, timeout=1)

    assert first.done()
    assert not second.done()

    barrier.confirm_sent("wamid.second")
    await asyncio.wait_for(second, timeout=1)
