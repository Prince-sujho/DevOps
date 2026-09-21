"""Outbound WhatsApp Cloud API payload builders.

Oracle is Meta's Cloud API wire format, which these builders exist to satisfy:
the envelope's three fixed fields and the `interactive` type names Meta accepts
(`button`, `list`, `cta_url`, `location_request_message`, `request_contact_info`,
`flow`). Whole-dict assertions are deliberate here — a silent rename of any key
is a message Meta rejects at runtime.
"""

from __future__ import annotations

import pytest

from infra.constants import PRODUCT_NAME
from infra.conversation import Button, ListRow
from whatsapp_adapter.app.src.output.payloads import (
    buttons_payload,
    contact_payload,
    contact_request_payload,
    document_payload,
    envelope,
    flow_payload,
    image_payload,
    list_payload,
    location_request_payload,
    reaction_payload,
    text_payload,
    url_payload,
)

pytestmark = pytest.mark.boundary

RECIPIENT = "919876543210"


def test_the_envelope_merges_the_payload_beside_its_fixed_fields():
    """The typed payload sits at the top level, not nested under a key."""
    assert envelope(RECIPIENT, "text", text_payload("hi")) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": RECIPIENT,
        "type": "text",
        "text": {"preview_url": False, "body": "hi"},
    }


def test_text_never_asks_whatsapp_to_render_a_link_preview():
    assert text_payload("see https://sujho.com")["text"]["preview_url"] is False


def test_image_carries_its_link_and_caption():
    assert image_payload("https://cdn/x.png", "your diagram") == {
        "image": {"link": "https://cdn/x.png", "caption": "your diagram"}
    }


def test_document_carries_the_filename_the_user_will_see():
    assert document_payload("https://cdn/x.pdf", "practice.pdf", "worksheet") == {
        "document": {
            "link": "https://cdn/x.pdf",
            "filename": "practice.pdf",
            "caption": "worksheet",
        }
    }


def test_a_reaction_targets_the_message_it_reacts_to():
    assert reaction_payload("wamid.OLD", "\U0001f44d") == {
        "reaction": {"message_id": "wamid.OLD", "emoji": "\U0001f44d"}
    }


def test_reply_buttons_keep_their_order_and_echo_ids():
    buttons = [
        Button(id="difficulty:easy", title="Easy"),
        Button(id="difficulty:hard", title="Hard"),
    ]
    assert buttons_payload("Pick one", buttons) == {
        "interactive": {
            "type": "button",
            "body": {"text": "Pick one"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "difficulty:easy", "title": "Easy"}},
                    {"type": "reply", "reply": {"id": "difficulty:hard", "title": "Hard"}},
                ]
            },
        }
    }


def test_a_list_renders_its_rows_inside_exactly_one_section():
    rows = [
        ListRow(id="r1", title="Algebra", description="Chapter 4"),
        ListRow(id="r2", title="Geometry"),
    ]
    payload = list_payload("Choose a topic", "Open", rows)

    sections = payload["interactive"]["action"]["sections"]
    assert len(sections) == 1
    assert sections[0]["rows"] == [
        {"id": "r1", "title": "Algebra", "description": "Chapter 4"},
        {"id": "r2", "title": "Geometry", "description": ""},
    ]
    assert payload["interactive"]["action"]["button"] == "Open"


def test_a_link_button_uses_metas_cta_url_type():
    assert url_payload("Read more", "Open", "https://ncert.gov.in/x") == {
        "interactive": {
            "type": "cta_url",
            "body": {"text": "Read more"},
            "action": {
                "name": "cta_url",
                "parameters": {"display_text": "Open", "url": "https://ncert.gov.in/x"},
            },
        }
    }


def test_a_location_request_names_metas_send_location_action():
    assert location_request_payload("Which city are you in?") == {
        "interactive": {
            "type": "location_request_message",
            "body": {"text": "Which city are you in?"},
            "action": {"name": "send_location"},
        }
    }


def test_our_contact_card_fills_both_name_slots_and_both_number_slots():
    """first_name is Meta's required given-name slot; wa_id is what makes Save contact render."""
    assert contact_payload("919000000000") == {
        "contacts": [
            {
                "name": {"formatted_name": PRODUCT_NAME, "first_name": PRODUCT_NAME},
                "phones": [{"phone": "919000000000", "wa_id": "919000000000"}],
            }
        ]
    }


def test_a_contact_request_carries_our_body_and_no_button_label_of_our_own():
    """The button label on request_contact_info is Meta-owned, so we send only the body."""
    assert contact_request_payload("Share your number") == {
        "interactive": {
            "type": "request_contact_info",
            "body": {"text": "Share your number"},
            "action": {"name": "request_contact_info"},
        }
    }


def test_a_flow_without_a_screen_does_not_ask_whatsapp_to_navigate():
    parameters = flow_payload("flow-1", "onboarding", "Set up", "Start", None, None)["interactive"][
        "action"
    ]["parameters"]

    assert "flow_action" not in parameters
    assert "flow_action_payload" not in parameters


def test_a_flow_with_a_screen_navigates_straight_to_it_with_its_data():
    parameters = flow_payload(
        "flow-1", "grade", "Upload", "Open", "GRADE_SCREEN", {"subject": "maths"}
    )["interactive"]["action"]["parameters"]

    assert parameters["flow_action"] == "navigate"
    assert parameters["flow_action_payload"] == {
        "screen": "GRADE_SCREEN",
        "data": {"subject": "maths"},
    }


def test_every_flow_is_published_at_flow_message_version_three():
    parameters = flow_payload("flow-1", "onboarding", "Set up", "Start", None, None)["interactive"][
        "action"
    ]["parameters"]

    assert parameters["flow_message_version"] == "3"
    assert parameters["mode"] == "published"
    assert parameters["flow_id"] == "flow-1"
    assert parameters["flow_token"] == "onboarding"
    assert parameters["flow_cta"] == "Start"
