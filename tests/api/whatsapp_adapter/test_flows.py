"""POST /flows/onboarding, POST /flows/grade -- RSA-encrypted Flow data endpoints.

`decrypted_flow` is a dependency, same class as JSON parsing: a malformed body
is 422, undecryptable ciphertext is 421 so the client refreshes our public key.
"""

from __future__ import annotations

import base64
import os

import pytest

from .conftest import RSA_KEY_SIZE_BYTES

FLOW_ROUTES = ["/flows/onboarding", "/flows/grade"]

# Same byte length as a real RSA-2048 OAEP ciphertext, so the request reaches
# decrypt_request (past pydantic) but is not encrypted to our private key.
VALID_SHAPED_BODY = {
    "encrypted_aes_key": base64.b64encode(os.urandom(RSA_KEY_SIZE_BYTES)).decode(),
    "encrypted_flow_data": base64.b64encode(os.urandom(64)).decode(),
    "initial_vector": base64.b64encode(os.urandom(16)).decode(),
}

pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize("route", FLOW_ROUTES)]


@pytest.mark.parametrize("field", list(VALID_SHAPED_BODY))
async def test_missing_envelope_field_returns_422(harness, route, field):
    body = {k: v for k, v in VALID_SHAPED_BODY.items() if k != field}
    response = await harness.client.post(route, json=body)
    assert response.status_code == 422


async def test_empty_body_returns_422(harness, route):
    response = await harness.client.post(route, json={})
    assert response.status_code == 422


async def test_plausible_shaped_garbage_ciphertext_fails_with_421(harness, route):
    """Correctly-shaped ciphertext that is not encrypted to our key."""
    response = await harness.client.post(route, json=VALID_SHAPED_BODY)
    assert response.status_code == 421


async def test_non_base64_ciphertext_fails_with_421(harness, route):
    body = {field: "not-valid-base64-!!!" for field in VALID_SHAPED_BODY}
    response = await harness.client.post(route, json=body)
    assert response.status_code == 421


async def test_empty_string_fields_fail_with_421(harness, route):
    """Empty strings satisfy pydantic `str` but cannot decrypt."""
    body = {field: "" for field in VALID_SHAPED_BODY}
    response = await harness.client.post(route, json=body)
    assert response.status_code == 421
