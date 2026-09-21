"""Inbound WhatsApp media becoming something the model can read.

README: onboarded traffic fetches inbound media; audio is transcribed (the
text_agent README: "Audio parts are transcribed to text before the model
call"); incompatible media must not reach the model as a broken attachment.
The synthetic-event wire format is `[label] detail`, handwritten here so a
label change cannot agree with itself.

Size ceilings live in `constants.py` (README silent). Oversize tests import
those ceilings; the image test below asserts the relationship the comment
states — absent kind means no ceiling — by sending a photo larger than the
document cap.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from infra.clients.users import WHATSAPP_THREAD_KEY
from infra.conversation_media import ConversationMediaScope, ConversationMediaStore
from infra.llm.content import TextContent, UriMediaContent
from whatsapp_adapter.app.src.constants import MAX_BYTES_BY_KIND
from whatsapp_adapter.app.src.input.media import MediaFetcher

from .fakes import FakeBucket, FakeWhatsApp
from .factories import inbound_media, jpeg_bytes, student

pytestmark = pytest.mark.asyncio

USER = student()


class FakeRuntime:
    """OpenAI runtime stand-in: records the transcription call, returns a script."""

    def __init__(self, transcript: str = "the spoken words") -> None:
        self.asked: list[dict] = []
        self._transcript = transcript
        self.client = SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))
        )

    async def _create(self, **kwargs):
        self.asked.append(kwargs)
        return SimpleNamespace(
            text=self._transcript, usage=SimpleNamespace(seconds=4.2)
        )


class Wiring:
    """A MediaFetcher plus the fakes behind it."""

    def __init__(self, media: bytes = b"", transcript: str = "the spoken words") -> None:
        self.whatsapp = FakeWhatsApp(media=media)
        self.runtime = FakeRuntime(transcript)
        self.bucket = FakeBucket()
        self.store = ConversationMediaStore(
            self.bucket,
            ConversationMediaScope(user_id=USER.userId, thread_key=WHATSAPP_THREAD_KEY),
        )
        self.usage: list = []
        self.fetcher = MediaFetcher(self.whatsapp, self.runtime)

    async def fetch(self, inbound) -> list:
        return await self.fetcher.fetch(inbound, self.store, self.usage)


# --------------------------------------------------------------------------
# images and documents are stored; the model sees a file
# --------------------------------------------------------------------------


async def test_an_image_is_stored_as_a_photo_the_model_can_open():
    """README: inbound media is fetched and stored; the model gets a URI part,
    not the raw WhatsApp media id.
    """
    wiring = Wiring(media=jpeg_bytes())

    parts = await wiring.fetch(inbound_media("image", mime_type="image/jpeg"))

    assert len(parts) == 1
    part = parts[0]
    assert isinstance(part, UriMediaContent)
    assert part.type == "image"
    assert part.filename.startswith("photo-")
    assert part.filename.endswith(".jpg")
    assert part.uri.startswith("https://media.test/")
    assert wiring.whatsapp.media_ids == ["media-1"]
    assert wiring.whatsapp.downloads == ["https://lookaside.test/media-1"]


async def test_a_document_is_stored_as_a_file_keeping_its_pdf_type():
    wiring = Wiring(media=b"%PDF-1.4 test")

    parts = await wiring.fetch(
        inbound_media("document", mime_type="application/pdf")
    )

    part = parts[0]
    assert isinstance(part, UriMediaContent)
    assert part.type == "document"
    assert part.filename.startswith("file-")
    assert part.filename.endswith(".pdf")


async def test_a_caption_rides_after_the_attachment_not_instead_of_it():
    wiring = Wiring(media=jpeg_bytes())

    parts = await wiring.fetch(
        inbound_media("image", mime_type="image/jpeg", caption="the diagram")
    )

    assert isinstance(parts[0], UriMediaContent)
    assert parts[1] == TextContent(text="the diagram")


async def test_an_empty_caption_is_not_sent_as_a_blank_text_part():
    wiring = Wiring(media=jpeg_bytes())

    parts = await wiring.fetch(inbound_media("image", mime_type="image/jpeg"))

    assert all(not isinstance(part, TextContent) for part in parts)


# --------------------------------------------------------------------------
# audio is transcribed, never stored as an attachment
# --------------------------------------------------------------------------


async def test_a_voice_note_reaches_the_model_as_transcribed_text():
    """text_agent README: audio is transcribed to text before the model call.
    Storing the ogg would hand the model bytes it cannot read.
    """
    wiring = Wiring(media=b"ogg-bytes", transcript="please explain photosynthesis")

    parts = await wiring.fetch(inbound_media("audio", mime_type="audio/ogg"))

    assert [part.text for part in parts] == [
        "[voice note] please explain photosynthesis"
    ]
    assert wiring.bucket.uploads == []


async def test_transcription_is_billed_onto_the_callers_usage_list():
    """The turn, not the fetcher, owns the list; a copied list here would
    silently un-bill the note (the Wave B usage-threading bug).
    """
    wiring = Wiring(media=b"ogg-bytes")

    marker = wiring.usage
    await wiring.fetch(inbound_media("audio", mime_type="audio/ogg"))

    assert wiring.usage is marker
    assert len(wiring.usage) == 1
    assert wiring.usage[0].kind == "audio"


async def test_a_caption_on_a_voice_note_follows_the_transcript():
    wiring = Wiring(media=b"ogg-bytes", transcript="hello")

    parts = await wiring.fetch(
        inbound_media("audio", mime_type="audio/ogg", caption="from class")
    )

    assert [part.text for part in parts] == [
        "[voice note] hello",
        "from class",
    ]


# --------------------------------------------------------------------------
# incompatible media degrades; it must not download or store
# --------------------------------------------------------------------------


async def test_a_video_is_refused_before_any_download():
    """Video is a ContentMessage kind the fetcher does not materialize.
    Downloading it would spend the media URL's lifetime on something the
    model will never see.
    """
    wiring = Wiring(media=b"should-not-download")

    parts = await wiring.fetch(inbound_media("video", mime_type="video/mp4"))

    assert [part.text for part in parts] == [
        "[attachment unavailable] video (video/mp4) — not supported"
    ]
    assert wiring.whatsapp.media_ids == []
    assert wiring.whatsapp.downloads == []
    assert wiring.bucket.uploads == []


async def test_an_unknown_document_type_is_refused_before_any_download():
    wiring = Wiring(media=b"should-not-download")

    parts = await wiring.fetch(
        inbound_media("document", mime_type="application/zip")
    )

    assert [part.text for part in parts] == [
        "[attachment unavailable] document (application/zip) — unsupported file type"
    ]
    assert wiring.whatsapp.downloads == []


async def test_an_oversize_document_is_downloaded_then_refused():
    """The size is only known after the bytes arrive. The file must not then
    be stored under a name the model could later open.
    """
    ceiling = MAX_BYTES_BY_KIND["document"]
    wiring = Wiring(media=b"%PDF" + bytes(ceiling + 1))

    parts = await wiring.fetch(
        inbound_media("document", mime_type="application/pdf")
    )

    assert wiring.whatsapp.downloads == ["https://lookaside.test/media-1"]
    assert wiring.bucket.uploads == []
    assert "file too large" in parts[0].text
    assert parts[0].text.startswith("[attachment unavailable]")


async def test_an_oversize_voice_note_is_not_sent_to_transcription():
    ceiling = MAX_BYTES_BY_KIND["audio"]
    wiring = Wiring(media=bytes(ceiling + 1))

    parts = await wiring.fetch(inbound_media("audio", mime_type="audio/ogg"))

    assert wiring.runtime.asked == []
    assert wiring.usage == []
    assert parts[0].text.startswith("[attachment unavailable]")
    assert "file too large" in parts[0].text


async def test_a_photo_larger_than_the_document_ceiling_is_still_stored():
    """constants.py: absent kind => no ceiling. Copying the document cap onto
    images would refuse a photo the model can still open.
    """
    ceiling = MAX_BYTES_BY_KIND["document"]
    photo = jpeg_bytes()
    wiring = Wiring(media=photo + bytes(ceiling + 1 - len(photo)))

    parts = await wiring.fetch(inbound_media("image", mime_type="image/jpeg"))

    assert isinstance(parts[0], UriMediaContent)
    assert parts[0].type == "image"
    assert parts[0].filename.startswith("photo-")
    assert wiring.bucket.uploads
    assert all(not isinstance(part, TextContent) for part in parts)
