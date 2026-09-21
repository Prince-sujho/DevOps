"""POST /webhook -- success-path Test Matrix rows.

Per the task brief, `POST /webhook` schedules background/async processing and
returns 200 immediately (README architecture step 4: "the webhook route
returns 200 immediately"). Success-path assertions here are scoped to what the
route itself contractually guarantees synchronously:

- the HTTP status code,
- the claim-then-enqueue ordering (README architecture steps 3 then 4:
  "Idempotency claim" happens before "Sender queue"), which IS observable
  synchronously since `receive_webhook` awaits `ctx.message_claims.claim(...)`
  before calling `ctx.coordinator.process_inbound(...)`, both before the
  response is returned.

The route hands each claimed message to `ConversationCoordinator.process_inbound`,
which is a synchronous fire-and-forget call (it just submits to an in-process
queue in the real implementation) -- so `FakeCoordinator.calls` reflects
exactly what the route itself did, with no reliance on unawaited background
work completing. No bounded poll is needed for these assertions.

"Unknown phone inbound" vs. "Known phone inbound" (Test Matrix rows) are
indistinguishable at the route layer: the route never inspects `sender_phone`
or user access state itself -- that branching lives entirely inside the real
`ConversationCoordinator`, which this suite fakes as an opaque call recorder
per the task's own route-layer scoping. Both matrix rows therefore collapse,
at this layer, to the single assertion this file makes: claim, then hand-off,
then 200. See UNCERTAINTY in the final report.
"""

from __future__ import annotations

import pytest

from .conftest import sign
from .payloads import dumps, sent_status_webhook, text_message_webhook


@pytest.mark.asyncio
async def test_well_formed_inbound_message_is_claimed_then_enqueued_then_200(harness):
    # Committed: 200; claim happens for this message id; coordinator receives
    # exactly one call carrying that same message id -- claim-then-enqueue
    # ordering per architecture steps 3 then 4.
    message_id = "wamid.KNOWN1"
    body = dumps(text_message_webhook(message_id=message_id))
    signature = sign(body)

    response = await harness.client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert harness.message_claims.claim_calls == [message_id]
    assert len(harness.turns.calls) == 1
    assert harness.turns.calls[0].message_id == message_id


@pytest.mark.asyncio
async def test_duplicate_delivery_is_claimed_and_processed_only_once(harness):
    # Committed: README's "Idempotency claim" guarantee -- POSTing the
    # identical signed body twice returns 200 both times, but the second
    # claim() call sees the id already claimed (FakeMessageClaimsRepository
    # mirrors the real repo's create-or-AlreadyExists semantics), so the
    # coordinator is invoked exactly once, not twice.
    message_id = "wamid.DUPLICATE1"
    body = dumps(text_message_webhook(message_id=message_id))
    signature = sign(body)
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
    }

    first = await harness.client.post("/webhook", content=body, headers=headers)
    second = await harness.client.post("/webhook", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    # claim() itself is called twice (once per delivery)...
    assert harness.message_claims.claim_calls == [message_id, message_id]
    # ...but only the first claim succeeded, so the coordinator ran once.
    assert len(harness.turns.calls) == 1
    assert harness.turns.calls[0].message_id == message_id


@pytest.mark.asyncio
async def test_sent_status_confirms_delivery(harness):
    # Committed: a 'sent' status webhook (no `messages` array, only `statuses`)
    # -> 200, and DeliveryConfirmations.confirm_sent is called with that wamid.
    # No inbound message means no claim and no coordinator dispatch.
    wamid = "wamid.STATUS1"
    body = dumps(sent_status_webhook(wamid=wamid))
    signature = sign(body)

    response = await harness.client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert harness.confirmations.confirmed == [wamid]
    assert harness.message_claims.claim_calls == []
    assert harness.turns.calls == []
