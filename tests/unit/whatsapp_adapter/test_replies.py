"""How one generated reply reaches WhatsApp, and in what order.

README oracles (Architecture §10 and Current Delivery Semantics): the reaction
lands on the inbound message, `contents` are delivered in the model's order
without reordering, a sources block becomes an italic page rollup then one
url button per cited web page, forms go to FlowLauncher, and media filenames
become public URLs at send time.

The confirmation barrier (wait on every bubble except the last) is not in the
README. Those tests pin the current implementation so a send-all-then-confirm
race still fails; they are not spec claims.
"""

from __future__ import annotations

import pytest

from infra.conversation import UrlMessage
from whatsapp_adapter.app.src.output.replies import ReplyDelivery, _bubbles

from .fakes import (
    FakeBucket,
    FakeConfirmations,
    FakeFlows,
    FakeUsers,
    FakeWhatsApp,
)
from .factories import (
    GIFT_CARD_ID,
    MESSAGE_ID,
    SENDER_PHONE,
    a_reply,
    a_cited_page,
    buttons_bubble,
    contact_bubble,
    document_bubble,
    document_form,
    gift_card,
    gift_card_bubble,
    grade_form,
    image_bubble,
    list_bubble,
    location_request_bubble,
    profile_form,
    reaction,
    sources_record,
    student,
    text_bubble,
)

# This module mixes the async delivery path with the sync `_bubbles` renderer,
# so the asyncio mark goes on each async test rather than the whole module.
pytestmark = pytest.mark.boundary


class Wiring:
    """A ReplyDelivery plus the fakes behind it, sharing one ordered timeline.

    The timeline is shared so send-vs-confirm order is one sequence, not two
    lists a test would have to correlate by hand.
    """

    def __init__(self, card=None) -> None:
        self.timeline: list[str] = []
        self.whatsapp = FakeWhatsApp(timeline=self.timeline)
        self.confirmations = FakeConfirmations(timeline=self.timeline)
        self.flows = FakeFlows()
        self.users = FakeUsers(gift_card=card)
        self.bucket = FakeBucket()
        self.delivery = ReplyDelivery(
            self.whatsapp, self.flows, self.confirmations, self.users, self.bucket
        )

    async def send(self, *contents) -> None:
        await self.delivery.send(student(), MESSAGE_ID, a_reply(*contents))

    @property
    def only_send(self) -> dict:
        """The single outbound send's fields, asserting it really was single."""
        assert len(self.whatsapp.sent) == 1, f"expected one send, got {self.whatsapp.kinds}"
        return self.whatsapp.sent[0][1]


# --------------------------------------------------------------------------
# reactions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reaction_lands_on_the_inbound_message_before_any_bubble():
    """A reaction is an acknowledgement of what was just said; arriving after
    the reply would read as a reaction to Sujho's own answer.
    """
    wiring = Wiring()

    await wiring.send(reaction("👍"), text_bubble("Here you go."))

    assert wiring.whatsapp.kinds == ["reaction", "text"]
    assert wiring.whatsapp.reactions == [(SENDER_PHONE, MESSAGE_ID, "👍")]


@pytest.mark.asyncio
async def test_a_reaction_is_not_also_delivered_as_a_bubble():
    """`_bubbles` renders a reaction to nothing: it was already sent as a
    reaction, so re-sending it would double-speak.
    """
    wiring = Wiring()

    await wiring.send(reaction("✨"), text_bubble())

    assert wiring.whatsapp.kinds.count("reaction") == 1
    assert wiring.whatsapp.kinds == ["reaction", "text"]


@pytest.mark.asyncio
async def test_every_reaction_in_the_reply_is_delivered():
    wiring = Wiring()

    await wiring.send(reaction("👍"), reaction("📚"), text_bubble())

    assert [emoji for _, _, emoji in wiring.whatsapp.reactions] == ["👍", "📚"]


# --------------------------------------------------------------------------
# ordering: the confirmation barrier
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_bubble_is_confirmed_before_the_next_one_is_sent():
    """Implementation pin, not a README sentence: waiting on each preceding
    wamid is how this code keeps display order. The interleaved timeline is
    the oracle -- asserting only that sends and confirmations both happened
    would pass even if all sends raced first.
    """
    wiring = Wiring()

    await wiring.send(text_bubble("first"), text_bubble("second"), text_bubble("third"))

    assert wiring.timeline == [
        "sent:wamid.out1",
        "confirmed:wamid.out1",
        "sent:wamid.out2",
        "confirmed:wamid.out2",
        "sent:wamid.out3",
    ]


@pytest.mark.asyncio
async def test_the_last_bubble_is_never_waited_on():
    """README is silent. The code waits only on bubbles that have a successor;
    waiting on the last one would add the barrier timeout to every turn.
    Kept so that change stays visible, not because the spec requires it.
    """
    wiring = Wiring()

    await wiring.send(text_bubble("first"), text_bubble("last"))

    assert wiring.confirmations.waited == ["wamid.out1"]


@pytest.mark.asyncio
async def test_a_single_bubble_turn_waits_for_nothing():
    wiring = Wiring()

    await wiring.send(text_bubble("just the one"))

    assert wiring.confirmations.waited == []
    assert wiring.whatsapp.kinds == ["text"]


@pytest.mark.asyncio
async def test_bubbles_are_delivered_in_the_order_the_model_composed_them():
    wiring = Wiring()

    await wiring.send(text_bubble("one"), image_bubble(), text_bubble("three"))

    assert wiring.whatsapp.kinds == ["text", "image", "text"]
    assert [body for _, body in wiring.whatsapp.texts] == ["one", "three"]


# --------------------------------------------------------------------------
# dispatch by bubble kind
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_text_bubble_is_sent_as_text_to_the_users_phone():
    wiring = Wiring()

    await wiring.send(text_bubble("Here you go."))

    assert wiring.only_send == {"to": SENDER_PHONE, "body": "Here you go."}


@pytest.mark.asyncio
async def test_an_image_is_sent_as_a_link_into_this_conversations_media():
    """The model names a stored filename; delivery turns it into a public URL.
    Sending the bare filename would reach WhatsApp as an invalid link.
    """
    wiring = Wiring()

    await wiring.send(image_bubble("diagram.png", "The diagram"))

    fields = wiring.only_send
    assert fields["caption"] == "The diagram"
    assert fields["link"].startswith("https://media.test/media-bucket/")
    assert fields["link"].endswith("diagram.png")


@pytest.mark.asyncio
async def test_a_document_is_sent_with_its_filename_as_well_as_its_link():
    """WhatsApp shows `filename` as the download name, so it travels
    separately from the link that fetches the bytes.
    """
    wiring = Wiring()

    await wiring.send(document_bubble("notes.pdf", "Your notes"))

    fields = wiring.only_send
    assert fields["filename"] == "notes.pdf"
    assert fields["caption"] == "Your notes"
    assert fields["link"].endswith("notes.pdf")


@pytest.mark.asyncio
async def test_buttons_carry_their_body_and_every_button():
    wiring = Wiring()

    await wiring.send(buttons_bubble("Pick one", "Yes", "No"))

    fields = wiring.only_send
    assert fields["body"] == "Pick one"
    assert [button.title for button in fields["buttons"]] == ["Yes", "No"]


@pytest.mark.asyncio
async def test_a_list_carries_its_button_label_and_rows():
    wiring = Wiring()

    await wiring.send(list_bubble("Choose a chapter", "Chapters"))

    fields = wiring.only_send
    assert fields["body"] == "Choose a chapter"
    assert fields["button_label"] == "Chapters"
    assert [row.id for row in fields["rows"]] == ["ch:1"]


@pytest.mark.asyncio
async def test_a_link_bubble_carries_the_page_title_and_its_url():
    """`UrlMessage` is not in `AssistantContent`: the model cannot author one,
    so the only way a link bubble exists is a sources record expanding into it.
    WhatsApp caps the button label at 20 characters; the test does not pin
    the frozen `SOURCE_LINK_LABEL` string.
    """
    wiring = Wiring()

    await wiring.send(sources_record("https://ncert.test/page"))

    fields = wiring.only_send
    assert fields["to"] == SENDER_PHONE
    assert fields["body"] == "Title for https://ncert.test/page"
    assert fields["url"] == "https://ncert.test/page"
    assert 0 < len(fields["display_text"]) <= 20


@pytest.mark.asyncio
async def test_a_location_request_is_sent_as_a_location_request():
    wiring = Wiring()

    await wiring.send(location_request_bubble("Share your location"))

    assert wiring.whatsapp.kinds == ["location_request"]
    assert wiring.only_send == {"to": SENDER_PHONE, "body": "Share your location"}


@pytest.mark.asyncio
async def test_a_contact_card_needs_nothing_but_the_recipient():
    """Our own number is the client's, not the model's, so the bubble carries
    no payload for the model to get wrong.
    """
    wiring = Wiring()

    await wiring.send(contact_bubble())

    assert wiring.only_send == {"to": SENDER_PHONE}


# --------------------------------------------------------------------------
# gift cards
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gift_card_is_fetched_for_this_user_then_sent_as_text():
    """The bubble carries only an id; the secrets are fetched at delivery so
    they never sit in a transcript or a model context.
    """
    wiring = Wiring(card=gift_card(card_number="1234-5678"))

    await wiring.send(gift_card_bubble(GIFT_CARD_ID))

    assert wiring.users.gift_cards_read == [("u-1", GIFT_CARD_ID)]
    assert wiring.whatsapp.kinds == ["text"]
    assert "1234-5678" in wiring.only_send["body"]


@pytest.mark.asyncio
async def test_a_gift_card_bubble_sends_the_rendered_card_not_the_id():
    wiring = Wiring(card=gift_card())

    await wiring.send(gift_card_bubble(GIFT_CARD_ID))

    body = wiring.only_send["body"]
    assert GIFT_CARD_ID not in body
    assert "Amazon" in body


# --------------------------------------------------------------------------
# forms go to the Flow launcher, not the transport
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "form",
    [document_form(), grade_form(), profile_form()],
    ids=["document", "grade", "profile"],
)
async def test_every_form_is_launched_as_a_flow_and_never_sent_as_a_bubble(form):
    """A Flow needs the published flow id for this user's persona, which only
    the launcher knows; the transport has no way to render one.
    """
    wiring = Wiring()

    await wiring.send(form)

    assert wiring.flows.forms == [("u-1", form)]
    assert wiring.whatsapp.sent == []


@pytest.mark.asyncio
async def test_a_form_before_another_bubble_is_confirmed_by_its_flow_wamid():
    """The launcher returns the Flow's own message id; the barrier must wait on
    that, or the bubble after a form could overtake it.
    """
    wiring = Wiring()

    await wiring.send(grade_form(), text_bubble("and one more thing"))

    assert wiring.confirmations.waited == ["wamid.flow1"]


# --------------------------------------------------------------------------
# sources records render to bubbles
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sources_record_becomes_one_link_bubble_per_cited_page():
    """README: one `url` button per cited web page."""
    wiring = Wiring()

    await wiring.send(sources_record("https://a.test/x", "https://b.test/y"))

    assert wiring.whatsapp.kinds == ["url", "url"]
    assert [fields["url"] for _, fields in wiring.whatsapp.sent] == [
        "https://a.test/x",
        "https://b.test/y",
    ]


@pytest.mark.asyncio
async def test_cited_pages_open_the_sources_block_as_an_italic_rollup():
    """README: italic page rollup, then the url buttons. The rollup has to
    name the page we actually cited -- reconstructing the formatter would
    just copy `_line`.
    """
    wiring = Wiring()

    await wiring.send(
        sources_record("https://a.test/x", pages=[a_cited_page("NCERT Mathematics")])
    )

    kinds = wiring.whatsapp.kinds
    assert kinds[0] == "text", f"the rollup must precede the links, got {kinds}"
    assert kinds[1:] == ["url"]
    rollup = wiring.whatsapp.texts[0][1]
    assert rollup.startswith("_") and rollup.endswith("_")
    assert "NCERT Mathematics" in rollup


@pytest.mark.asyncio
async def test_a_sources_record_with_no_pages_has_no_rollup_bubble():
    """Web citations alone still become link buttons; an empty rollup must
    not insert a blank italic bubble in front of them.
    """
    wiring = Wiring()

    await wiring.send(sources_record("https://a.test/x"))

    assert wiring.whatsapp.kinds == ["url"]


@pytest.mark.asyncio
async def test_a_sources_record_expands_in_place_among_the_other_bubbles():
    """Sources belong to the answer they support, so they must land after the
    text that cites them and before anything the model put afterwards.
    """
    wiring = Wiring()

    await wiring.send(
        text_bubble("the answer"),
        sources_record("https://a.test/x"),
        text_bubble("anything else?"),
    )

    assert wiring.whatsapp.kinds == ["text", "url", "text"]


@pytest.mark.asyncio
async def test_a_record_that_renders_no_bubble_is_not_sent():
    """A sources record with nothing cited must not produce an empty bubble."""
    wiring = Wiring()

    await wiring.send(text_bubble("the answer"), sources_record())

    assert wiring.whatsapp.kinds == ["text"]


def test_bubbles_renders_a_plain_message_as_itself():
    """Anything that is not a record is already a bubble; the renderer must
    pass it through untouched rather than rebuild it.
    """
    bubble = text_bubble("unchanged")
    assert _bubbles(bubble) == [bubble]


def test_bubbles_renders_a_reaction_to_nothing():
    assert _bubbles(reaction("👍")) == []


def test_bubbles_renders_a_sources_record_to_link_bubbles():
    rendered = _bubbles(sources_record("https://a.test/x"))

    assert [type(bubble) for bubble in rendered] == [UrlMessage]
    assert rendered[0].url == "https://a.test/x"
