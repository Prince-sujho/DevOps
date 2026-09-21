"""How inbound bytes become a stored conversation file.

README: the adapter derives public media URLs from stored filenames. This
module is the inbound half of that: photos become capped JPEG, documents keep
the bytes they arrived as. Naming (`photo-` / `file-`) lives in constants,
not the README; tests assert the stem and suffix, not a reconstructed
fingerprint.
"""

from __future__ import annotations

import pytest

from infra.clients.users import WHATSAPP_THREAD_KEY
from infra.conversation_media import ConversationMediaScope, ConversationMediaStore
from infra.llm.content import UriMediaContent
from whatsapp_adapter.app.src.input.attachments import store_inbound

from .fakes import FakeBucket
from .factories import png_bytes, student

pytestmark = pytest.mark.asyncio

USER = student()


def store() -> tuple[ConversationMediaStore, FakeBucket]:
    bucket = FakeBucket()
    media = ConversationMediaStore(
        bucket,
        ConversationMediaScope(user_id=USER.userId, thread_key=WHATSAPP_THREAD_KEY),
    )
    return media, bucket


async def test_a_photo_is_stored_as_jpeg_under_a_photo_stem():
    media, bucket = store()
    original = png_bytes()

    part = await store_inbound(media, ["wamid.1"], original, "image/png")

    assert isinstance(part, UriMediaContent)
    assert part.type == "image"
    assert part.filename.startswith("photo-")
    assert part.filename.endswith(".jpg")
    assert len(bucket.uploads) == 1
    _, data, content_type = bucket.uploads[0]
    assert content_type == "image/jpeg"
    assert data[:2] == b"\xff\xd8"  # JPEG SOI
    assert original[:8] == b"\x89PNG\r\n\x1a\n"
    assert data != original


async def test_a_pdf_is_stored_verbatim_under_a_file_stem():
    media, bucket = store()
    payload = b"%PDF-1.4 the worksheet"

    part = await store_inbound(media, ["wamid.1"], payload, "application/pdf")

    assert part.type == "document"
    assert part.filename.startswith("file-")
    assert part.filename.endswith(".pdf")
    _, data, content_type = bucket.uploads[0]
    assert data == payload
    assert content_type == "application/pdf"


async def test_the_same_inbound_id_stores_under_the_same_name():
    """put_stable is what makes a retry overwrite rather than fork a copy."""
    media, _ = store()

    first = await store_inbound(media, ["wamid.1"], png_bytes(), "image/jpeg")
    second = await store_inbound(media, ["wamid.1"], png_bytes((0, 255, 0)), "image/jpeg")

    assert first.filename == second.filename


async def test_two_inbounds_do_not_share_a_filename():
    media, _ = store()

    first = await store_inbound(media, ["wamid.1"], png_bytes(), "image/jpeg")
    second = await store_inbound(media, ["wamid.2"], png_bytes(), "image/jpeg")

    assert first.filename != second.filename
