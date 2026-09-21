"""GET /webhook -- Meta's webhook verification challenge.

Spec (README "Routes" table): "Meta verification challenge". Meta's own webhook
verification protocol (read as the documented contract per the task brief) says:
on `hub.mode == "subscribe"` and a matching `hub.verify_token`, echo back
`hub.challenge`; otherwise reject.

The literal query-param names, and the literal status codes / body shape the
route actually returns, were read from `app/src/api/routes.py::verify_webhook`
(signature facts, per the task brief) BEFORE any assertion below was written:

    params["hub.mode"] != "subscribe" or params["hub.verify_token"] != <token>
        -> Response(status_code=403)                      # empty body
    else -> PlainTextResponse(params["hub.challenge"])     # 200, text/plain body

Both `params["hub.mode"]` and friends are direct (non-`.get`) dict lookups on
`request.query_params`, so a request missing one of the three params raises an
unhandled `KeyError` rather than returning a controlled 4xx. Under this
harness's client (`raise_app_exceptions=False`), an unhandled exception in the
app surfaces as a real HTTP 500 response (verified once, empirically, on a
throwaway FastAPI app -- see UNCERTAINTY.md -- before writing any assertion
against the real app).

No README line names a status for missing query params specifically, but
this same route already establishes 403 as its rejection code for a wrong
`hub.verify_token` / `hub.mode` (both tested above) -- missing a required
param is not a different kind of failure than supplying a wrong one, so 500
is not promoted to spec here. The test below asserts the 403 this route's
own verification boundary should give, and is expected to fail against
current code (FINDINGS whatsapp_adapter robustness #1).
"""

from __future__ import annotations

import pytest

from .conftest import VERIFY_TOKEN


@pytest.mark.asyncio
async def test_matching_token_echoes_challenge(harness):
    # Committed: 200, body == the literal challenge string, verbatim.
    response = await harness.client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 200
    assert response.text == "1158201444"


@pytest.mark.asyncio
async def test_wrong_verify_token_is_rejected(harness):
    # Committed: 403, empty body.
    response = await harness.client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "not-the-real-token",
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403
    assert response.content == b""


@pytest.mark.asyncio
async def test_wrong_hub_mode_is_rejected(harness):
    # Committed: 403, empty body -- hub.mode must be exactly "subscribe".
    response = await harness.client.get(
        "/webhook",
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    assert response.status_code == 403
    assert response.content == b""


@pytest.mark.asyncio
async def test_missing_query_params_is_rejected_with_403(harness):
    """A verification boundary should reject a request with no verification
    params the same way it rejects one with the wrong params (403, both
    tested above), not crash. Expected to fail against current code -- see
    the module docstring and FINDINGS whatsapp_adapter robustness #1.
    """
    response = await harness.client.get("/webhook")

    assert response.status_code == 403
