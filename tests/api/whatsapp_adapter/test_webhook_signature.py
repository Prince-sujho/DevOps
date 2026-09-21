"""POST /webhook -- Meta's HMAC envelope as a FastAPI dependency.

`signed_body` admits the body only under a valid Meta HMAC: a missing header is
request parsing (422), a forged signature is 403. Routes never see it unsigned.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import APP_SECRET, WRONG_APP_SECRET, sign
from .payloads import dumps, text_message_webhook

pytestmark = pytest.mark.asyncio

BODY = dumps(text_message_webhook())
JSON_HEADERS = {"Content-Type": "application/json"}


async def _post(harness, headers: dict[str, str]) -> httpx.Response:
    """POST the one webhook body under the given headers."""
    return await harness.client.post("/webhook", content=BODY, headers=headers)


async def test_missing_signature_header_is_rejected_with_422(harness):
    """No X-Hub-Signature-256 is a missing required header, same class as missing JSON."""
    response = await _post(harness, JSON_HEADERS)

    assert response.status_code == 422
    assert harness.message_claims.claim_calls == []
    assert harness.turns.calls == []


@pytest.mark.parametrize(
    "signature",
    [sign(BODY, secret=WRONG_APP_SECRET), "sha256=not-a-real-hex-digest"],
    ids=["wrong-secret", "not-a-digest"],
)
async def test_invalid_signature_is_rejected_with_403(harness, signature):
    response = await _post(harness, {**JSON_HEADERS, "X-Hub-Signature-256": signature})

    assert response.status_code == 403
    assert harness.message_claims.claim_calls == []
    assert harness.turns.calls == []


async def test_correct_signature_is_accepted(harness):
    signature = sign(BODY, secret=APP_SECRET)

    response = await _post(harness, {**JSON_HEADERS, "X-Hub-Signature-256": signature})

    assert response.status_code == 200
