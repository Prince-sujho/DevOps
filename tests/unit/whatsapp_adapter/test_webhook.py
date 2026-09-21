"""Webhook payload parsing: which change blocks are admitted, and how each
inbound message type normalizes.

Oracles are the adapter README ("Validate inbound webhook payloads"; Test
Matrix "Unsupported message type -> Ignore") and the normalized inbound types
in `infra.conversation.inbound` — `ContentMessage.type`, `LocationMessage.detail`,
`BaseInboundMessage.at_ms`, and `AdAttribution`, whose `ctwaClid` is documented
as "Absent on some placements".
"""

from __future__ import annotations

import json

import pytest

from whatsapp_adapter.app.src.input.message import (
    ContactMessage,
    ContentMessage,
    FlowCompletionMessage,
    InteractiveReplyMessage,
    LocationMessage,
)
from whatsapp_adapter.app.src.input.webhook import (
    admit_changes,
    extract_failed_statuses,
    extract_inbound_messages,
    extract_sent_status_ids,
)

from .factories import (
    PHONE_NUMBER_ID,
    PROFILE_NAME,
    SENDER_ID,
    SENDER_PHONE,
    envelope,
    message,
    messages_change,
    statuses_change,
    without_sender_phone,
)

pytestmark = pytest.mark.boundary

MEDIA_KINDS = ["image", "audio", "video", "document"]


def _one(*messages) -> object:
    """Normalize a single inbound message and return it."""
    extracted = extract_inbound_messages([messages_change(*messages)])
    assert len(extracted) == 1
    return extracted[0]


# --------------------------------------------------------------------------
# admit_changes
# --------------------------------------------------------------------------


def test_only_messages_field_changes_are_admitted():
    """Non-'messages' fields (e.g. account alerts) are not inbound traffic."""
    other_field = {"field": "account_alerts", "value": {}}
    admitted = admit_changes(envelope(other_field), PHONE_NUMBER_ID)
    assert admitted == []


def test_changes_for_another_phone_number_id_are_skipped():
    """A shared app receives other numbers' traffic; only our number is ours to answer."""
    foreign = messages_change(message("text", text={"body": "hi"}), phone_number_id="OTHER")
    admitted = admit_changes(envelope(foreign), PHONE_NUMBER_ID)
    assert admitted == []


def test_every_matching_change_across_entries_is_admitted():
    ours = messages_change(message("text", text={"body": "hi"}))
    raw = {"entry": [{"changes": [ours]}, {"changes": [ours]}]}
    assert admit_changes(raw, PHONE_NUMBER_ID) == [ours, ours]


# --------------------------------------------------------------------------
# delivery statuses
# --------------------------------------------------------------------------


def test_only_sent_status_ids_are_returned():
    change = statuses_change(
        {"id": "wamid.A", "status": "sent"},
        {"id": "wamid.B", "status": "delivered"},
        {"id": "wamid.C", "status": "read"},
    )
    assert extract_sent_status_ids([change]) == ["wamid.A"]


def test_a_change_with_no_statuses_block_yields_no_sent_ids():
    change = messages_change(message("text", text={"body": "hi"}))
    assert extract_sent_status_ids([change]) == []


def test_failed_status_reports_the_wamid_with_its_code_and_title():
    change = statuses_change(
        {
            "id": "wamid.D",
            "status": "failed",
            "errors": [{"code": 131026, "title": "Message undeliverable"}],
        }
    )
    assert extract_failed_statuses([change]) == [("wamid.D", "131026 Message undeliverable")]


def test_non_failed_statuses_are_not_reported_as_failures():
    change = statuses_change(
        {"id": "wamid.A", "status": "sent"},
        {"id": "wamid.B", "status": "delivered"},
    )
    assert extract_failed_statuses([change]) == []


def test_a_failed_status_with_no_errors_block_fails_loudly():
    change = statuses_change({"id": "wamid.E", "status": "failed"})
    with pytest.raises(KeyError):
        extract_failed_statuses([change])


# --------------------------------------------------------------------------
# content messages
# --------------------------------------------------------------------------


def test_text_message_carries_its_body_as_the_text_surface():
    normalized = _one(message("text", text={"body": "help me with algebra"}))
    assert isinstance(normalized, ContentMessage)
    assert normalized.type == "text"
    assert normalized.text == "help me with algebra"
    assert normalized.sender_phone == SENDER_PHONE
    assert normalized.sender_id == SENDER_ID
    assert normalized.profile_name == PROFILE_NAME


def test_a_text_message_with_no_text_block_at_all_fails_loudly_during_parsing():
    """README: a malformed supported payload fails loudly during parsing.
    A declared type with no matching payload block is the parse-time case.
    """
    raw = message("text")  # no text= payload attached
    with pytest.raises(KeyError):
        extract_inbound_messages([messages_change(raw)])


def test_a_text_message_with_an_empty_body_field_fails_loudly_when_read():
    """A present but empty payload block parses fine; the missing field only
    surfaces once something reads .text, since parsing never forces it open.
    """
    normalized = _one(message("text", text={}))
    with pytest.raises(KeyError):
        _ = normalized.text


@pytest.mark.parametrize("kind", MEDIA_KINDS)
def test_each_media_kind_keeps_its_own_type_and_media_fields(kind):
    payload = {"id": f"media-{kind}", "mime_type": f"{kind}/fake"}
    normalized = _one(message(kind, **{kind: payload}))
    assert isinstance(normalized, ContentMessage)
    assert normalized.type == kind
    assert normalized.media_id == f"media-{kind}"
    assert normalized.media_mime_type == f"{kind}/fake"


def test_media_caption_is_the_text_surface():
    normalized = _one(
        message("image", image={"id": "m1", "mime_type": "image/jpeg", "caption": "my working"})
    )
    assert normalized.text == "my working"


def test_media_without_a_caption_has_an_empty_text_surface():
    normalized = _one(message("image", image={"id": "m1", "mime_type": "image/jpeg"}))
    assert normalized.text == ""


def test_a_sticker_normalizes_to_an_image():
    """Stickers carry media like images and are not a ContentMessage type of their own."""
    normalized = _one(message("sticker", sticker={"id": "st1", "mime_type": "image/webp"}))
    assert isinstance(normalized, ContentMessage)
    assert normalized.type == "image"
    assert normalized.media_id == "st1"


# --------------------------------------------------------------------------
# location
# --------------------------------------------------------------------------


def test_location_with_an_address_details_the_address():
    normalized = _one(
        message(
            "location",
            location={"latitude": 12.97, "longitude": 77.59, "address": "MG Road, Bengaluru"},
        )
    )
    assert isinstance(normalized, LocationMessage)
    assert normalized.latitude == 12.97
    assert normalized.longitude == 77.59
    assert normalized.detail == "MG Road, Bengaluru"


def test_location_without_an_address_details_the_coordinates():
    normalized = _one(message("location", location={"latitude": 12.97, "longitude": 77.59}))
    assert normalized.address is None
    assert normalized.detail == "12.97, 77.59"


def test_a_location_share_carries_no_user_authored_text():
    normalized = _one(message("location", location={"latitude": 1.0, "longitude": 2.0}))
    assert normalized.text == ""


# --------------------------------------------------------------------------
# contact cards
# --------------------------------------------------------------------------


def test_a_requested_phone_share_rewrites_the_sender_phone_to_the_shared_number():
    """origin 'contact_request' is the user answering the phone ask with a card."""
    shared = [{"origin": "contact_request", "phones": [{"wa_id": "919100000099"}]}]
    normalized = _one(message("contacts", contacts=shared))
    assert isinstance(normalized, ContactMessage)
    assert normalized.origin == "contact_request"
    assert normalized.sender_phone == "919100000099"


def test_a_forwarded_contact_card_leaves_the_sender_phone_untouched():
    """origin 'other' is a card forwarded in chat, not the sender's own number."""
    forwarded = [{"origin": "other", "phones": [{"wa_id": "919100000099"}]}]
    normalized = _one(message("contacts", contacts=forwarded))
    assert normalized.origin == "other"
    assert normalized.sender_phone == SENDER_PHONE


def test_a_contact_message_with_no_contact_cards_fails_loudly():
    with pytest.raises(IndexError):
        extract_inbound_messages([messages_change(message("contacts", contacts=[]))])


# --------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------


def test_flow_completion_lifts_the_flow_token_out_of_the_response():
    reply = {
        "type": "nfm_reply",
        "nfm_reply": {"response_json": {"flow_token": "onboarding", "persona": "student"}},
    }
    normalized = _one(message("interactive", interactive=reply))
    assert isinstance(normalized, FlowCompletionMessage)
    assert normalized.flow_token == "onboarding"
    assert normalized.response_json == {"persona": "student"}


def test_a_flow_response_sent_as_a_json_string_is_parsed():
    reply = {
        "type": "nfm_reply",
        "nfm_reply": {
            "response_json": json.dumps({"flow_token": "grade", "subject": "maths"})
        },
    }
    normalized = _one(message("interactive", interactive=reply))
    assert normalized.flow_token == "grade"
    assert normalized.response_json == {"subject": "maths"}


@pytest.mark.parametrize("kind", ["button_reply", "list_reply"])
def test_a_tap_normalizes_to_an_interactive_reply(kind):
    reply = {"type": kind, kind: {"id": "persona:student", "title": "Student"}}
    normalized = _one(message("interactive", interactive=reply))
    assert isinstance(normalized, InteractiveReplyMessage)
    assert normalized.reply_id == "persona:student"
    assert normalized.title == "Student"


def test_an_unknown_interactive_type_is_dropped():
    normalized = extract_inbound_messages(
        [messages_change(message("interactive", interactive={"type": "product_enquiry"}))]
    )
    assert normalized == []


# --------------------------------------------------------------------------
# dropped kinds
# --------------------------------------------------------------------------


def test_an_unrecognized_message_type_is_dropped():
    """README Test Matrix: an unsupported message type is ignored, not turned into a turn."""
    raw = message("order", order={"catalog_id": "cat-1"})
    assert extract_inbound_messages([messages_change(raw)]) == []


def test_a_reaction_is_dropped():
    """Feedback on a prior message, not a conversational turn."""
    raw = message("reaction", reaction={"message_id": "wamid.OLD", "emoji": "\U0001f44d"})
    assert extract_inbound_messages([messages_change(raw)]) == []


# --------------------------------------------------------------------------
# sender identity and ordering
# --------------------------------------------------------------------------


def test_a_hidden_sender_number_leaves_the_sender_phone_unresolved():
    """'from' carries the phone only while visible; the business-scoped id is always there."""
    raw = without_sender_phone(message("text", text={"body": "hi"}))
    normalized = _one(raw)
    assert normalized.sender_phone is None
    assert normalized.sender_id == SENDER_ID


def test_messages_in_one_change_keep_their_arrival_order():
    first = message("text", text={"body": "first"}) | {"id": "wamid.1"}
    second = message("text", text={"body": "second"}) | {"id": "wamid.2"}
    extracted = extract_inbound_messages([messages_change(first, second)])
    assert [row.text for row in extracted] == ["first", "second"]


def test_messages_across_several_changes_are_all_extracted():
    change = messages_change(message("text", text={"body": "hi"}))
    extracted = extract_inbound_messages([change, change])
    assert len(extracted) == 2


def test_the_webhook_timestamp_is_read_as_epoch_seconds():
    normalized = _one(message("text", text={"body": "hi"}))
    assert normalized.at_ms == 1_700_000_000_000


# --------------------------------------------------------------------------
# Click-to-WhatsApp ad attribution
# --------------------------------------------------------------------------


def test_a_click_to_whatsapp_ad_referral_becomes_ad_attribution():
    referral = {
        "source_type": "ad",
        "source_id": "ad-123",
        "headline": "Learn maths on WhatsApp",
        "source_url": "https://fb.me/abc",
        "ctwa_clid": "clid-xyz",
    }
    normalized = _one(message("text", text={"body": "hi"}, referral=referral))
    assert normalized.ad is not None
    assert normalized.ad.sourceId == "ad-123"
    assert normalized.ad.headline == "Learn maths on WhatsApp"
    assert normalized.ad.sourceUrl == "https://fb.me/abc"
    assert normalized.ad.ctwaClid == "clid-xyz"


def test_an_ad_referral_without_a_ctwa_clid_still_attributes():
    """AdAttribution documents ctwaClid as absent on some placements."""
    referral = {
        "source_type": "ad",
        "source_id": "ad-123",
        "headline": "Learn maths on WhatsApp",
        "source_url": "https://fb.me/abc",
    }
    normalized = _one(message("text", text={"body": "hi"}, referral=referral))
    assert normalized.ad.sourceId == "ad-123"
    assert normalized.ad.ctwaClid is None


def test_a_post_share_referral_carries_no_attribution():
    """Only source_type 'ad' is a Click-to-WhatsApp arrival."""
    referral = {"source_type": "post", "source_id": "post-1"}
    normalized = _one(message("text", text={"body": "hi"}, referral=referral))
    assert normalized.ad is None


def test_a_message_with_no_referral_carries_no_attribution():
    normalized = _one(message("text", text={"body": "hi"}))
    assert normalized.ad is None
