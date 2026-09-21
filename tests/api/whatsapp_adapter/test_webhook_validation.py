"""POST /webhook -- malformed vs. unsupported inbound payloads.

The README's Test Matrix documents two distinct, different behaviors for two
different kinds of bad input:

    | Malformed supported payload | Fail loudly during parsing |
    | Unsupported message type    | Ignore and return 200      |

These are tested distinctly below.

`POST /webhook` has no pydantic request-body model (the route reads
`request.body()` and calls `json.loads` / `extract_inbound_messages` by hand),
so there is no automatic 422 path for this route -- "fail loudly" here means an
unhandled exception, which (per the empirically-verified harness behavior) is
HTTP 500. This literal status was read from `app/src/input/webhook.py`
(no try/except anywhere in the parsing path) BEFORE writing the assertion.
The mandatory "422 for malformed bodies" coverage category is instead
satisfied by the two `/flows/*` routes in `test_flows.py`, which do have a
pydantic body model.

Two distinct "unsupported" cases are split out below (see MIRRORED_AND_WRONG.md
and tests/outcomes/UNCERTAINTY.md Journey 12): `type: "reaction"` is a real Meta type
`_normalize_message` fully drops (returns `None`, never claimed, never
dispatched) -- a genuinely ignored message, but not the case the README's
Test Matrix row is actually naming, since "reaction" isn't an *unsupported*
type at all, it's a deliberately-dropped one. A genuinely unrecognized type
(e.g. `"order"`) instead becomes an `UnsupportedMessage` that *does* run one
full agent turn via `AgentInputBuilder.unsupported()` -- claimed and
dispatched, not ignored. The second test below asserts the README's literal
"Ignore and return 200" claim against that genuinely-unsupported case, and is
expected to fail against current code.
"""

from __future__ import annotations

import pytest

from .conftest import sign
from .payloads import (
    dumps,
    reaction_message_webhook,
    text_message_missing_text_object,
    unrecognized_message_type_webhook,
)


@pytest.mark.asyncio
async def test_malformed_supported_payload_fails_loudly(harness):
    """README Test Matrix: "Malformed supported payload -> Fail loudly during
    parsing." A `type: "text"` message missing its `text` object triggers an
    unhandled `KeyError` in `_normalize_message`, which this harness surfaces
    as a real 500 -- but the README documents "fail loudly," not a specific
    status or exception type, so the assertion here is qualitative (non-2xx,
    no claim, no dispatch) rather than freezing today's 500 as the contract.
    """
    body = dumps(text_message_missing_text_object())
    signature = sign(body)

    response = await harness.client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert not (200 <= response.status_code < 300), "a malformed payload must not succeed"
    assert harness.message_claims.claim_calls == []
    assert harness.turns.calls == []


@pytest.mark.asyncio
async def test_reaction_message_is_dropped_and_returns_200(harness):
    # `type: "reaction"` is a real Meta type `_normalize_message` deliberately
    # returns None for (dropped, never becomes an UnsupportedMessage) -> the
    # webhook yields zero normalized messages for this entry -> route still
    # returns 200, but neither claim nor coordinator dispatch ever happens for
    # this message, since extract_inbound_messages produced nothing to loop
    # over. This documents the "reaction" branch specifically -- it is not
    # the README's "Unsupported message type" Test Matrix row (see the test
    # below for that).
    body = dumps(reaction_message_webhook())
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
    assert harness.message_claims.claim_calls == []
    assert harness.turns.calls == []


@pytest.mark.asyncio
async def test_unrecognized_message_type_is_ignored_and_returns_200(harness):
    """README Test Matrix: "Unsupported message type -> Ignore and return 200."

    A genuinely unrecognized Meta type (`"order"`) is what that row is
    actually describing -- not `"reaction"`, which is a different, already
    fully-dropped branch (see the test above). Per UNCERTAINTY.md Journey 12,
    `_normalize_message`'s wildcard arm converts an unrecognized type into an
    `UnsupportedMessage`, which the coordinator claims and dispatches as one
    full agent turn (`AgentInputBuilder.unsupported()`) rather than ignoring.
    Expected to fail against current code: that failure is the correct oracle
    for the README's literal "ignore" claim.
    """
    body = dumps(unrecognized_message_type_webhook())
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
    assert harness.message_claims.claim_calls == [], "an ignored message must not be claimed"
    assert harness.turns.calls == [], "an ignored message must not run an agent turn"
