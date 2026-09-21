"""The Graph API transport: what each send puts on the wire.

This is the thin client, so the oracle is the wire itself -- the request path,
the envelope, the declared message type, and the id read back out. `payloads.py`
owns the body shapes and is tested in `test_payloads.py`; what is tested here is
the pairing: every send must declare the `type` that matches the payload it
carries, or Meta rejects it.
"""

from __future__ import annotations

import json

import httpx
import pytest

from infra.conversation import Button, ListRow
from whatsapp_adapter.app.src.output.whatsapp import WhatsAppClient

pytestmark = pytest.mark.asyncio

PHONE_NUMBER_ID = "PNID1"
PUBLIC_NUMBER = "919000000000"
TO = "919876543210"
ACCESS_TOKEN = "token-abc"
RETURNED_WAMID = "wamid.returned"


class Wiring:
    """A WhatsAppClient whose transport records requests instead of sending them."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response
        self.client = WhatsAppClient(
            access_token=ACCESS_TOKEN,
            phone_number_id=PHONE_NUMBER_ID,
            api_version="v21.0",
            public_number=PUBLIC_NUMBER,
        )
        self.client._http = httpx.AsyncClient(
            base_url="https://graph.test/v21.0",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            transport=httpx.MockTransport(self._handle),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._response is not None:
            return self._response
        return httpx.Response(200, json={"messages": [{"id": RETURNED_WAMID}]})

    @property
    def request(self) -> httpx.Request:
        assert len(self.requests) == 1, f"expected one request, got {len(self.requests)}"
        return self.requests[0]

    @property
    def body(self) -> dict:
        return json.loads(self.request.content)


# --------------------------------------------------------------------------
# the envelope every send shares
# --------------------------------------------------------------------------


async def test_a_send_posts_to_this_business_numbers_messages_endpoint():
    wiring = Wiring()

    await wiring.client.send_text(to=TO, body="hello")

    assert wiring.request.method == "POST"
    assert wiring.request.url.path.endswith(f"/{PHONE_NUMBER_ID}/messages")


async def test_a_send_is_addressed_to_the_recipient_as_whatsapp_product():
    wiring = Wiring()

    await wiring.client.send_text(to=TO, body="hello")

    assert wiring.body["messaging_product"] == "whatsapp"
    assert wiring.body["to"] == TO


async def test_a_send_returns_the_message_id_whatsapp_assigned():
    """This id is what the confirmation barrier and the transcript key on, so
    it must be read from the response, never synthesized.
    """
    wiring = Wiring()

    wamid = await wiring.client.send_text(to=TO, body="hello")

    assert wamid == RETURNED_WAMID


async def test_a_rejected_send_raises_instead_of_returning_a_fake_id():
    """A silent failure here would record a reply the user never saw."""
    wiring = Wiring(response=httpx.Response(400, json={"error": {"message": "bad"}}))

    with pytest.raises(httpx.HTTPStatusError):
        await wiring.client.send_text(to=TO, body="hello")


async def test_the_access_token_travels_as_a_bearer_header():
    wiring = Wiring()

    await wiring.client.send_text(to=TO, body="hello")

    assert wiring.request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


# --------------------------------------------------------------------------
# each send declares the type matching its payload
# --------------------------------------------------------------------------


async def test_text_declares_the_text_type_and_carries_the_body():
    wiring = Wiring()

    await wiring.client.send_text(to=TO, body="hello there")

    assert wiring.body["type"] == "text"
    assert wiring.body["text"]["body"] == "hello there"


async def test_an_image_declares_the_image_type_with_its_link_and_caption():
    wiring = Wiring()

    await wiring.client.send_image(to=TO, link="https://m.test/a.png", caption="a diagram")

    assert wiring.body["type"] == "image"
    assert wiring.body["image"]["link"] == "https://m.test/a.png"
    assert wiring.body["image"]["caption"] == "a diagram"


async def test_a_document_declares_the_document_type_and_keeps_its_filename():
    """WhatsApp shows `filename` as the download name, so it is not
    interchangeable with the link.
    """
    wiring = Wiring()

    await wiring.client.send_document(
        to=TO, link="https://m.test/n.pdf", filename="notes.pdf", caption="your notes"
    )

    assert wiring.body["type"] == "document"
    assert wiring.body["document"]["filename"] == "notes.pdf"
    assert wiring.body["document"]["link"] == "https://m.test/n.pdf"


async def test_a_reaction_declares_the_reaction_type_against_one_message():
    """A reaction names the message it decorates; without the id it has
    nothing to attach to.
    """
    wiring = Wiring()

    await wiring.client.send_reaction(to=TO, message_id="wamid.inbound", emoji="👍")

    assert wiring.body["type"] == "reaction"
    assert wiring.body["reaction"]["message_id"] == "wamid.inbound"
    assert wiring.body["reaction"]["emoji"] == "👍"


async def test_buttons_are_sent_as_an_interactive_message():
    """Buttons, lists, links, location prompts, and Flows all share the
    `interactive` type and are told apart by the payload's own subtype.
    """
    wiring = Wiring()

    await wiring.client.send_buttons(
        to=TO, body="pick", buttons=[Button(id="b:1", title="Yes")]
    )

    assert wiring.body["type"] == "interactive"
    assert wiring.body["interactive"]["type"] == "button"


async def test_a_list_is_sent_as_an_interactive_list():
    wiring = Wiring()

    await wiring.client.send_list(
        to=TO,
        body="choose",
        button_label="Chapters",
        rows=[ListRow(id="r:1", title="Chapter 1", description="Integers")],
    )

    assert wiring.body["type"] == "interactive"
    assert wiring.body["interactive"]["type"] == "list"


async def test_a_url_button_is_sent_as_an_interactive_cta_url():
    wiring = Wiring()

    await wiring.client.send_url(
        to=TO, body="the page", display_text="Open", url="https://ncert.test/p"
    )

    assert wiring.body["type"] == "interactive"
    assert wiring.body["interactive"]["type"] == "cta_url"


async def test_a_location_request_is_sent_as_an_interactive_location_request():
    wiring = Wiring()

    await wiring.client.send_location_request(to=TO, body="share your location")

    assert wiring.body["type"] == "interactive"
    assert wiring.body["interactive"]["type"] == "location_request_message"


async def test_our_contact_card_carries_our_own_public_number():
    """The number is the client's, bound at construction: the caller cannot
    accidentally send someone else's card.
    """
    wiring = Wiring()

    await wiring.client.send_contact(to=TO)

    assert wiring.body["type"] == "contacts"
    phones = wiring.body["contacts"][0]["phones"]
    assert phones[0]["wa_id"] == PUBLIC_NUMBER


async def test_a_contact_request_is_sent_as_an_interactive_prompt():
    wiring = Wiring()

    await wiring.client.send_contact_request(to=TO, body="share your number")

    assert wiring.body["type"] == "interactive"


# --------------------------------------------------------------------------
# Flows
# --------------------------------------------------------------------------


async def test_a_flow_carries_its_id_token_and_call_to_action():
    wiring = Wiring()

    await wiring.client.send_flow(
        to=TO, flow_id="f-1", flow_token="tok-1", body="open it", cta="Get started"
    )

    assert wiring.body["type"] == "interactive"
    params = wiring.body["interactive"]["action"]["parameters"]
    assert params["flow_id"] == "f-1"
    assert params["flow_token"] == "tok-1"


async def test_a_flow_opened_on_no_screen_sends_no_screen_or_data():
    """The grade Flow opens at its own entry point; sending a null screen
    would override that with nothing.
    """
    wiring = Wiring()

    await wiring.client.send_flow(
        to=TO, flow_id="f-1", flow_token="tok-1", body="open it", cta="Start"
    )

    params = wiring.body["interactive"]["action"]["parameters"]
    assert "flow_action_payload" not in params


async def test_a_flow_opened_on_a_screen_carries_that_screen_and_its_data():
    wiring = Wiring()

    await wiring.client.send_flow(
        to=TO,
        flow_id="f-1",
        flow_token="tok-1",
        body="open it",
        cta="Start",
        screen="INSTITUTION_SCREEN",
        data={"query": "", "results": [], "hasResults": False},
    )

    payload = wiring.body["interactive"]["action"]["parameters"]["flow_action_payload"]
    assert payload["screen"] == "INSTITUTION_SCREEN"
    assert payload["data"]["hasResults"] is False


# --------------------------------------------------------------------------
# reads and the non-message endpoints
# --------------------------------------------------------------------------


async def test_showing_typing_also_marks_the_inbound_message_read():
    """One call does both: the indicator is what the user sees while the model
    runs, and the read receipt is what stops WhatsApp re-delivering.
    """
    wiring = Wiring()

    await wiring.client.show_typing("wamid.inbound")

    body = wiring.body
    assert body["status"] == "read"
    assert body["message_id"] == "wamid.inbound"
    assert body["typing_indicator"] == {"type": "text"}


async def test_showing_typing_on_a_rejected_call_raises():
    wiring = Wiring(response=httpx.Response(400, json={"error": {"message": "bad"}}))

    with pytest.raises(httpx.HTTPStatusError):
        await wiring.client.show_typing("wamid.inbound")


async def test_a_media_id_is_resolved_to_its_temporary_download_url():
    wiring = Wiring(response=httpx.Response(200, json={"url": "https://lookaside.test/x"}))

    url = await wiring.client.get_media_url("media-1")

    assert url == "https://lookaside.test/x"
    assert wiring.request.url.path.endswith("/media-1")


async def test_resolving_a_missing_media_id_raises():
    wiring = Wiring(response=httpx.Response(404, json={"error": {"message": "gone"}}))

    with pytest.raises(httpx.HTTPStatusError):
        await wiring.client.get_media_url("media-1")


async def test_media_is_downloaded_as_raw_bytes():
    """Voice notes and photos are binary; decoding here would corrupt them."""
    wiring = Wiring(response=httpx.Response(200, content=b"\x89PNG\r\n\x1a\n"))

    content = await wiring.client.download_media("https://lookaside.test/x")

    assert content == b"\x89PNG\r\n\x1a\n"


async def test_a_failed_download_raises_instead_of_returning_empty_bytes():
    """Empty bytes would reach the model as an unreadable attachment."""
    wiring = Wiring(response=httpx.Response(500, content=b""))

    with pytest.raises(httpx.HTTPStatusError):
        await wiring.client.download_media("https://lookaside.test/x")


async def test_closing_the_client_stops_it_from_sending():
    """Shutdown must actually release the connection pool, so a send attempted
    afterwards fails rather than quietly reusing a closed client.
    """
    wiring = Wiring()

    await wiring.client.close()

    with pytest.raises(RuntimeError, match="closed"):
        await wiring.client.send_text(to=TO, body="too late")
    assert wiring.requests == []
