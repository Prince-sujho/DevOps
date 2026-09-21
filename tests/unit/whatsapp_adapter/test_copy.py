"""Onboarding copy assembly and Flow option formatting.

Oracle is `CANNED_RESPONSES.onboarding` plus the Flow display caps in
`flows/constants.py` — both imported rather than re-transcribed, so a copy or
cap change shows up here automatically instead of needing this file edited in
lockstep.
"""

from __future__ import annotations

import pytest

from infra.canned import CANNED_RESPONSES
from infra.constants import PRODUCT_NAME
from whatsapp_adapter.app.src.flows.constants import (
    NOT_LISTED_ID,
    OPTION_DESCRIPTION_CHARS,
    OPTION_TITLE_CHARS,
    PERSONA_STUDENT_BUTTON_ID,
    PERSONA_TEACHER_BUTTON_ID,
)
from whatsapp_adapter.app.src.flows.copy import (
    grades_label,
    institution_options,
    onboarding_fork_body,
    onboarding_fork_buttons,
    persona_resume_body,
    phone_request_body,
)

from .factories import school

pytestmark = pytest.mark.boundary

ONBOARDING = CANNED_RESPONSES.onboarding
NAME = "Priya"


# --------------------------------------------------------------------------
# onboarding copy
# --------------------------------------------------------------------------


def test_the_fork_greets_by_name_then_asks_which_role():
    expected = f"{ONBOARDING.intro_template.format(name=NAME)}\n{ONBOARDING.persona_question}"
    body = onboarding_fork_body(NAME)
    assert body == expected
    # Belt and suspenders: the name must actually land in the rendered text,
    # not just in a template placeholder both sides happen to skip alike.
    assert NAME in body
    assert body.index(NAME) < body.index(ONBOARDING.persona_question)


def test_the_phone_ask_greets_by_name_then_asks_for_the_number():
    expected = f"{ONBOARDING.intro_template.format(name=NAME)}\n{ONBOARDING.phone_request}"
    body = phone_request_body(NAME)
    assert body == expected
    assert NAME in body
    assert ONBOARDING.persona_question not in body


def test_resuming_after_a_shared_phone_thanks_them_and_skips_the_intro():
    """The intro already went out with the phone ask; only the acknowledgement is new."""
    body = persona_resume_body()
    assert body == f"{ONBOARDING.phone_ack} {ONBOARDING.persona_question}"
    assert ONBOARDING.intro_template.format(name="") not in body


def test_the_fork_body_matches_a_hand_transcribed_literal_snapshot():
    """The tests above recompute onboarding_fork_body's own formula, so a bad
    formula shared by both sides would slip through. This copy is retyped by
    hand from the current CANNED_RESPONSES content as an independent check;
    it must be updated by hand too when that copy changes.
    """
    assert onboarding_fork_body("Priya") == (
        f"Hi Priya! \U0001f44b I'm {PRODUCT_NAME} \u2014 your AI for learning.\n"
        "To set you up, tell me \u2014 are you a student or a teacher?"
    )


def test_the_fork_offers_student_first_then_teacher():
    buttons = onboarding_fork_buttons()
    assert [button.id for button in buttons] == [
        PERSONA_STUDENT_BUTTON_ID,
        PERSONA_TEACHER_BUTTON_ID,
    ]
    assert [button.title for button in buttons] == [
        ONBOARDING.persona_button_titles["student"],
        ONBOARDING.persona_button_titles["teacher"],
    ]


# --------------------------------------------------------------------------
# institution options
# --------------------------------------------------------------------------


def test_each_search_result_becomes_an_option_titled_by_name_and_placed_by_subtitle():
    found = school(school_id="dps-1", name="Delhi Public School")
    options = institution_options([found], typed="delhi public")

    assert options[0] == {
        "id": "dps-1",
        "title": "Delhi Public School",
        "description": found.place,
    }


def test_the_keep_as_typed_escape_is_always_the_last_option():
    options = institution_options([school(), school(school_id="s2")], typed="my school")

    assert len(options) == 3
    assert options[-1]["id"] == NOT_LISTED_ID
    assert options[-1]["title"] == "None of these"
    assert options[-1]["description"] == 'Continue with "my school"'


def test_no_search_results_still_offers_the_escape():
    """A user whose school is not in the directory must still be able to continue."""
    options = institution_options([], typed="tiny village school")

    assert options == [
        {
            "id": NOT_LISTED_ID,
            "title": "None of these",
            "description": 'Continue with "tiny village school"',
        }
    ]


def _numbered(length: int) -> str:
    """A string with a distinct digit at every position, so a clip test can
    pin exactly which prefix survived rather than just the resulting length.
    """
    return "".join(str(index % 10) for index in range(length))


def test_a_title_exactly_at_the_display_cap_is_left_alone():
    exact = _numbered(OPTION_TITLE_CHARS)
    options = institution_options([school(name=exact)], typed="n")
    assert options[0]["title"] == exact


def test_a_title_over_the_display_cap_is_clipped_to_the_cap_with_an_ellipsis():
    """Content over the cap is not rendered by WhatsApp, so it is trimmed to fit."""
    long_name = _numbered(OPTION_TITLE_CHARS + 1)
    options = institution_options([school(name=long_name)], typed="n")
    title = options[0]["title"]

    # Exact equality pins which characters survived, not just how many.
    assert title == long_name[: OPTION_TITLE_CHARS - 1] + "\u2026"


def test_a_long_typed_escape_description_is_clipped_to_its_own_cap():
    typed = _numbered(OPTION_DESCRIPTION_CHARS + 50)
    options = institution_options([], typed=typed)
    description = options[0]["description"]

    prefix = f'Continue with "{typed}"'
    assert description == prefix[: OPTION_DESCRIPTION_CHARS - 1] + "\u2026"


def test_a_long_place_subtitle_is_clipped_to_its_own_cap():
    """institution_options clips the subtitle too, not just the title."""
    far = school(locality=_numbered(OPTION_DESCRIPTION_CHARS + 50), city="", state="")
    options = institution_options([far], typed="x")
    description = options[0]["description"]

    assert description == far.place[: OPTION_DESCRIPTION_CHARS - 1] + "\u2026"


# --------------------------------------------------------------------------
# grades label
# --------------------------------------------------------------------------


def test_one_selected_grade_reads_singular():
    assert grades_label((7,)) == "Grade 7"


def test_several_selected_grades_read_plural_and_comma_joined():
    assert grades_label((6, 7, 8)) == "Grades 6, 7, 8"
