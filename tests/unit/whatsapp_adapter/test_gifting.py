"""How one gift card reads as a WhatsApp bubble.

README is silent on gift-card formatting. Independently statable: brand and
amount are visible; instructions are always present; a field that was never
secured (None or blank) must not render as an empty or `None` line.
The exact `*brand gift card — ₹N*` header is this renderer's current copy,
not a spec sentence.
"""

from __future__ import annotations

import pytest

from whatsapp_adapter.app.src.output.gifting import render_gift_card

from .factories import gift_card

pytestmark = pytest.mark.boundary


def test_the_card_opens_with_its_brand_and_amount():
    rendered = render_gift_card(gift_card(brand="Amazon", amount_inr=500))

    assert "Amazon" in rendered
    assert "₹500" in rendered


def test_a_fully_secured_card_shows_number_pin_and_expiry():
    rendered = render_gift_card(
        gift_card(card_number="1234-5678", card_pin="4321", valid_till="2027-03-31")
    )

    assert "1234-5678" in rendered
    assert "4321" in rendered
    assert "2027-03-31" in rendered


def test_the_redemption_instructions_always_close_the_bubble():
    """Instructions are the one non-optional field: a card with no usable
    instructions is not deliverable.
    """
    rendered = render_gift_card(gift_card())

    assert rendered.endswith("Redeem at amazon.in/gc")
    assert "How to use:" in rendered


@pytest.mark.parametrize(
    ("field", "label"),
    [("card_number", "Card number"), ("card_pin", "PIN"), ("valid_till", "Valid till")],
)
def test_a_field_that_was_never_secured_is_left_out_entirely(field, label):
    """Not rendered as an empty value, and not rendered as `None`: absent."""
    rendered = render_gift_card(gift_card(**{field: None}))

    assert label not in rendered
    assert "None" not in rendered


def test_a_card_with_nothing_secured_still_reads_as_a_card():
    """A pending card has a brand, an amount, and instructions, and nothing
    else; it must not render a bubble of blank lines or leaked nulls.
    """
    rendered = render_gift_card(
        gift_card(card_number=None, card_pin=None, valid_till=None)
    )

    assert "Amazon" in rendered
    assert "₹500" in rendered
    assert "Redeem at amazon.in/gc" in rendered
    assert "None" not in rendered
    assert "Card number" not in rendered
    assert "PIN" not in rendered
    assert "Valid till" not in rendered


def test_every_detail_sits_on_its_own_line():
    """WhatsApp renders a single bubble, so the newlines are the only
    structure the user gets. Labels are this renderer's copy; the invariant
    is that number, pin, and expiry do not share a line.
    """
    rendered = render_gift_card(gift_card())
    lines = rendered.split("\n")

    number_lines = [line for line in lines if "1234-5678" in line]
    pin_lines = [line for line in lines if "4321" in line]
    expiry_lines = [line for line in lines if "2027-03-31" in line]
    assert len(number_lines) == 1
    assert len(pin_lines) == 1
    assert len(expiry_lines) == 1
    assert number_lines[0] != pin_lines[0]
    assert pin_lines[0] != expiry_lines[0]


def test_a_blank_secured_field_is_treated_as_unsecured():
    """The renderer tests truthiness, not `is None`: an empty string from the
    voucher provider must not produce a "Card number: " line with no number.
    """
    rendered = render_gift_card(gift_card(card_number=""))

    assert "Card number" not in rendered
