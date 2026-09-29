"""Sealing and opening WhatsApp Flow data-endpoint bodies.

README: `decrypted_flow` opens POST /flows/* with the private key and
answers 421 when decryption fails. The 421 mapping lives in the envelope
(already API-tested). This file checks the crypto itself: a request Meta
could have sealed round-trips, and a response is sealed under the flipped
IV Meta's client decrypts with.

The sealer and the response opener are owned by the test, so a skipped IV
flip cannot agree with itself.
"""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from whatsapp_adapter.app.src.flows.crypto import (
    decrypt_request,
    encrypt_response,
    load_private_key,
)
from whatsapp_adapter.app.src.types import EncryptedFlowRequest, FlowExchange

pytestmark = pytest.mark.boundary

# Meta Flow endpoint encryption: AES-128-GCM, 16-byte auth tag, IV flipped
# with XOR 0xFF on the response. Pin the numbers here, not the product
# constants, so a drift cannot agree with the sealer that uses them.
AES_KEY_BYTES = 16
GCM_TAG_BYTES = 16
OAEP_PADDING = OAEP(
    mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
)

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")


def _flip_iv(initial_vector: bytes) -> bytes:
    """Meta's response-encryption IV: every byte XOR 0xFF.

    Args:
        initial_vector: the request's IV bytes.
    Returns:
        The flipped IV bytes.
    Raises:
        None.
    """
    return bytes(byte ^ 0xFF for byte in initial_vector)


def seal_request(
    payload: dict, private_key: RSAPrivateKey = _PRIVATE_KEY
) -> EncryptedFlowRequest:
    """Encrypt one Flow request the way Meta's client does.

    Args:
        payload: the plaintext Flow request body.
        private_key: the RSA key whose public half wraps the AES key.
    Returns:
        The sealed EncryptedFlowRequest.
    Raises:
        None.
    """
    aes_key = os.urandom(AES_KEY_BYTES)
    initial_vector = os.urandom(16)
    encryptor = Cipher(
        algorithms.AES(aes_key), modes.GCM(initial_vector)
    ).encryptor()
    ciphertext = (
        encryptor.update(json.dumps(payload).encode()) + encryptor.finalize()
    )
    wrapped_key = private_key.public_key().encrypt(aes_key, OAEP_PADDING)
    return EncryptedFlowRequest(
        encrypted_aes_key=b64encode(wrapped_key).decode(),
        encrypted_flow_data=b64encode(ciphertext + encryptor.tag).decode(),
        initial_vector=b64encode(initial_vector).decode(),
    )


def open_response(body: str, exchange: FlowExchange) -> dict:
    """Decrypt a Flow response the way Meta's client does (flipped IV).

    Args:
        body: the base64 sealed response body.
        exchange: the FlowExchange holding the AES key and IV.
    Returns:
        The decrypted response payload.
    Raises:
        None.
    """
    blob = b64decode(body)
    ciphertext, tag = blob[:-GCM_TAG_BYTES], blob[-GCM_TAG_BYTES:]
    decryptor = Cipher(
        algorithms.AES(exchange.aes_key),
        modes.GCM(_flip_iv(exchange.initial_vector), tag),
    ).decryptor()
    return json.loads(decryptor.update(ciphertext) + decryptor.finalize())


# --------------------------------------------------------------------------
# request decrypt
# --------------------------------------------------------------------------


def test_a_sealed_request_decrypts_back_to_the_payload():
    """A request sealed the way Meta seals it decrypts back to the original
    payload.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    payload = {"action": "ping"}
    exchange = decrypt_request(seal_request(payload), _PRIVATE_KEY)

    assert exchange.payload == payload


def test_load_private_key_reads_the_pem_the_endpoint_is_booted_with():
    """The PEM the endpoint boots with loads and decrypts a request sealed to
    its public half.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    payload = {"action": "INIT"}
    key = load_private_key(_PEM)

    assert decrypt_request(seal_request(payload, key), key).payload == payload


def test_a_request_sealed_to_another_key_is_rejected():
    """A request sealed to a different RSA key is rejected, not silently
    misread.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError):
        decrypt_request(seal_request({"action": "ping"}, other), _PRIVATE_KEY)


def test_a_truncated_auth_tag_is_rejected():
    """A one-byte-short GCM auth tag is rejected, not silently accepted.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    body = seal_request({"action": "ping"})
    blob = b64decode(body.encrypted_flow_data)
    tampered = body.model_copy(
        update={"encrypted_flow_data": b64encode(blob[:-1]).decode()}
    )
    with pytest.raises(InvalidTag):
        decrypt_request(tampered, _PRIVATE_KEY)


# --------------------------------------------------------------------------
# response encrypt
# --------------------------------------------------------------------------


def test_a_response_opens_under_the_flipped_iv():
    """A response sealed by us opens correctly under Meta's flipped-IV
    convention.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    exchange = decrypt_request(seal_request({"action": "ping"}), _PRIVATE_KEY)
    reply = {"data": {"status": "active"}}

    opened = open_response(encrypt_response(exchange, reply), exchange)

    assert opened == reply


def test_a_response_does_not_open_under_the_request_iv():
    """If the sealer forgets to flip the IV, Meta's client cannot read us
    and the health ping looks like a dead endpoint.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    exchange = decrypt_request(seal_request({"action": "ping"}), _PRIVATE_KEY)
    sealed = encrypt_response(exchange, {"data": {"status": "active"}})
    blob = b64decode(sealed)
    ciphertext, tag = blob[:-GCM_TAG_BYTES], blob[-GCM_TAG_BYTES:]
    decryptor = Cipher(
        algorithms.AES(exchange.aes_key),
        modes.GCM(exchange.initial_vector, tag),
    ).decryptor()
    with pytest.raises(InvalidTag):
        decryptor.update(ciphertext) + decryptor.finalize()
