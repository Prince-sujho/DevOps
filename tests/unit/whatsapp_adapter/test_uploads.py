"""Decrypting WhatsApp Flow uploads and storing a grade submission.

README: a grade Flow completion fetches uploaded papers/sheets. Meta encrypts
those CDN objects; a hash or HMAC mismatch must fail loudly rather than store
garbage the model would read as a paper.

The encrypt helper below is the inverse of the product decrypt, owned by the
test, so a round-trip asserts decrypt-against-a-known-plaintext rather than
comparing the function to itself.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from base64 import b64encode

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from infra.clients.users import WHATSAPP_THREAD_KEY
from infra.conversation_media import ConversationMediaScope, ConversationMediaStore
from whatsapp_adapter.app.src.input.uploads import (
    FlowUploadFetcher,
    _decrypt_flow_upload,
)
from whatsapp_adapter.app.src.types import (
    FlowMediaEncryptionMetadata,
    GradeFlowPayload,
)

from .fakes import FakeBucket, FakeWhatsApp
from .factories import flow_media_ref, png_bytes, student

# Decrypt tests are sync; fetch tests are async.
pytestmark = pytest.mark.boundary

USER = student()
PLAINTEXT = b"%PDF-1.4 a question paper"
# Meta Flow CDN HMAC suffix is 10 bytes. Pin the number here so a product
# constant drift cannot agree with the sealer that uses the same constant.
META_HMAC_SUFFIX_BYTES = 10


def seal(plaintext: bytes) -> tuple[bytes, FlowMediaEncryptionMetadata]:
    """Encrypt one blob the way Meta's Flow CDN does, so decrypt can be checked."""
    key, hmac_key, iv = os.urandom(32), os.urandom(32), os.urandom(16)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    digest = hmac.new(hmac_key, iv + ciphertext, hashlib.sha256).digest()
    encrypted = ciphertext + digest[:META_HMAC_SUFFIX_BYTES]
    metadata = FlowMediaEncryptionMetadata(
        encrypted_hash=_b64sha(encrypted),
        iv=b64encode(iv).decode(),
        encryption_key=b64encode(key).decode(),
        hmac_key=b64encode(hmac_key).decode(),
        hmac=b64encode(digest).decode(),
        plaintext_hash=_b64sha(plaintext),
    )
    return encrypted, metadata


def _b64sha(data: bytes) -> str:
    return b64encode(hashlib.sha256(data).digest()).decode()


def a_ref(media_id: str, encrypted: bytes, metadata: FlowMediaEncryptionMetadata):
    ref = flow_media_ref(media_id)
    return ref.model_copy(update={"encryption_metadata": metadata, "cdn_url": f"https://cdn.test/{media_id}"})


# --------------------------------------------------------------------------
# decrypt
# --------------------------------------------------------------------------


def test_a_sealed_upload_decrypts_back_to_the_plaintext():
    encrypted, metadata = seal(PLAINTEXT)
    assert _decrypt_flow_upload(encrypted, metadata) == PLAINTEXT


def test_a_tampered_ciphertext_is_rejected():
    encrypted, metadata = seal(PLAINTEXT)
    tampered = bytes([encrypted[0] ^ 0xFF]) + encrypted[1:]
    with pytest.raises(ValueError):
        _decrypt_flow_upload(tampered, metadata)


def test_a_wrong_encrypted_hash_is_rejected():
    """The CDN hash is the first check; without it a bit-flip can still
    present a plausible HMAC if the suffix is left intact.
    """
    encrypted, metadata = seal(PLAINTEXT)
    bad = metadata.model_copy(update={"encrypted_hash": _b64sha(b"other")})
    with pytest.raises(ValueError, match="hash mismatch"):
        _decrypt_flow_upload(encrypted, bad)


def test_a_wrong_hmac_is_rejected():
    encrypted, metadata = seal(PLAINTEXT)
    bad = metadata.model_copy(update={"hmac": b64encode(b"\x00" * 32).decode()})
    with pytest.raises(ValueError, match="HMAC mismatch"):
        _decrypt_flow_upload(encrypted, bad)


def test_a_wrong_plaintext_hash_is_rejected():
    """Decrypt can succeed and still be the wrong file; the plaintext hash is
    what stops us storing that file as the user's paper.
    """
    encrypted, metadata = seal(PLAINTEXT)
    bad = metadata.model_copy(update={"plaintext_hash": _b64sha(b"other")})
    with pytest.raises(ValueError, match="hash mismatch"):
        _decrypt_flow_upload(encrypted, bad)


# --------------------------------------------------------------------------
# grade submission persistence
# --------------------------------------------------------------------------


class Wiring:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.whatsapp = FakeWhatsApp()
        self.whatsapp.download_media = self._download
        self._blobs = blobs
        self.bucket = FakeBucket()
        self.store = ConversationMediaStore(
            self.bucket,
            ConversationMediaScope(user_id=USER.userId, thread_key=WHATSAPP_THREAD_KEY),
        )
        self.fetcher = FlowUploadFetcher(self.whatsapp)

    async def _download(self, url: str) -> bytes:
        self.whatsapp.downloads.append(url)
        return self._blobs[url]


@pytest.mark.asyncio
async def test_question_papers_are_stored_as_pdfs():
    encrypted, metadata = seal(PLAINTEXT)
    url = "https://cdn.test/qp"
    wiring = Wiring({url: encrypted})
    payload = GradeFlowPayload(
        question_paper=[a_ref("qp", encrypted, metadata).model_copy(update={"cdn_url": url})],
        rubric=[],
        answer_sheets=[],
    )

    parts = await wiring.fetcher.fetch_grade_submission(payload, wiring.store, "wamid.g1")

    assert len(parts) == 1
    assert parts[0].type == "document"
    assert parts[0].filename.startswith("file-")
    assert parts[0].filename.endswith(".pdf")
    assert wiring.bucket.uploads[0][1] == PLAINTEXT


@pytest.mark.asyncio
async def test_answer_sheets_are_stored_as_photos():
    original = png_bytes()
    encrypted, metadata = seal(original)
    url = "https://cdn.test/a1"
    wiring = Wiring({url: encrypted})
    payload = GradeFlowPayload(
        question_paper=[],
        rubric=[],
        answer_sheets=[a_ref("a1", encrypted, metadata).model_copy(update={"cdn_url": url})],
    )

    parts = await wiring.fetcher.fetch_grade_submission(payload, wiring.store, "wamid.g1")

    assert parts[0].type == "image"
    assert parts[0].filename.startswith("photo-")
    assert parts[0].filename.endswith(".jpg")
    stored = wiring.bucket.uploads[0][1]
    assert stored[:2] == b"\xff\xd8"
    assert original[:8] == b"\x89PNG\r\n\x1a\n"
    assert stored != original


@pytest.mark.asyncio
async def test_every_slot_is_fetched_and_kept_in_slot_order():
    """Question paper, then rubric, then answer sheets -- that is the order
    the model will see them in the grade turn.
    """
    sheets = [png_bytes((255, 0, 0)), png_bytes((0, 255, 0))]
    blobs: dict[str, bytes] = {}
    refs = {}
    for slot, body in (
        ("qp", b"paper-bytes"),
        ("rb", b"rubric-bytes"),
        ("a1", sheets[0]),
        ("a2", sheets[1]),
    ):
        encrypted, metadata = seal(body)
        url = f"https://cdn.test/{slot}"
        blobs[url] = encrypted
        refs[slot] = a_ref(slot, encrypted, metadata).model_copy(update={"cdn_url": url})

    wiring = Wiring(blobs)
    payload = GradeFlowPayload(
        question_paper=[refs["qp"]],
        rubric=[refs["rb"]],
        answer_sheets=[refs["a1"], refs["a2"]],
    )

    parts = await wiring.fetcher.fetch_grade_submission(payload, wiring.store, "wamid.g1")

    assert [part.type for part in parts] == ["document", "document", "image", "image"]
    stored = [data for _, data, _ in wiring.bucket.uploads]
    assert stored[0] == b"paper-bytes"
    assert stored[1] == b"rubric-bytes"
    assert stored[2].startswith(b"\xff\xd8")
    assert stored[3].startswith(b"\xff\xd8")


@pytest.mark.asyncio
async def test_an_empty_submission_stores_nothing():
    wiring = Wiring({})
    payload = GradeFlowPayload(question_paper=[], rubric=[], answer_sheets=[])

    parts = await wiring.fetcher.fetch_grade_submission(payload, wiring.store, "wamid.g1")

    assert parts == []
    assert wiring.bucket.uploads == []
