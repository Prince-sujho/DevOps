"""Which WhatsApp Flow gets launched, for whom, and opened on which screen.

README: form messages are delivered by FlowLauncher (document, grade, or
profile), and the Flow id is persona-specific. Screen names and the empty
institution seed are not in the README; they are the published Flow contract
this launcher has to match so the results group stays hidden until a search.
Canned CTA/body strings live in `CANNED_RESPONSES` -- tests here assert
relationships (name in the body, distinct CTAs), not a second copy of the copy.
"""

from __future__ import annotations

import pytest

from whatsapp_adapter.app.src.constants import DOCUMENT_FORM_SCREEN, ONBOARDING_FLOW_TOKEN
from whatsapp_adapter.app.src.flows.constants import INSTITUTION_SCREEN
from whatsapp_adapter.app.src.output.launcher import FlowLauncher
from whatsapp_adapter.app.src.types import FlowIds
from whatsapp_adapter.app.src.types.settings import PersonaFlowIds

from .fakes import FakeWhatsApp
from .factories import (
    SENDER_PHONE,
    document_form,
    grade_form,
    profile_form,
    student,
    teacher,
)

pytestmark = pytest.mark.asyncio

# Distinct ids everywhere, so picking the wrong persona or the wrong form
# cannot coincidentally produce the right value.
FLOW_IDS = FlowIds(
    student=PersonaFlowIds(onboarding="s-onb", doc="s-doc", grade="s-grade"),
    teacher=PersonaFlowIds(onboarding="t-onb", doc="t-doc", grade="t-grade"),
)


class Wiring:
    """A FlowLauncher plus the transport behind it."""

    def __init__(self) -> None:
        self.whatsapp = FakeWhatsApp()
        self.launcher = FlowLauncher(self.whatsapp, FLOW_IDS)

    @property
    def flow(self) -> dict:
        """The single Flow send's fields, asserting it really was single."""
        assert len(self.whatsapp.sent) == 1, f"expected one send, got {self.whatsapp.kinds}"
        kind, fields = self.whatsapp.sent[0]
        assert kind == "flow", f"a Flow launch went out as {kind}"
        return fields


# --------------------------------------------------------------------------
# onboarding launches
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("persona", "flow_id"),
    [("student", "s-onb"), ("teacher", "t-onb")],
)
async def test_onboarding_launches_the_flow_published_for_that_persona(persona, flow_id):
    wiring = Wiring()

    await wiring.launcher.onboarding(persona, SENDER_PHONE, "Priya")

    assert wiring.flow["flow_id"] == flow_id
    assert wiring.flow["to"] == SENDER_PHONE


async def test_onboarding_greets_the_sender_by_name_and_returns_what_it_said():
    """The returned body is what the caller records as Sujho's bubble, so it
    has to be the same text that actually went out.
    """
    wiring = Wiring()

    body = await wiring.launcher.onboarding("student", SENDER_PHONE, "Priya")

    assert "Priya" in body
    assert wiring.flow["body"] == body


async def test_each_persona_gets_its_own_onboarding_copy():
    """The two personas must not share a bubble; both must greet this sender."""
    student_body = await Wiring().launcher.onboarding("student", SENDER_PHONE, "Priya")
    teacher_body = await Wiring().launcher.onboarding("teacher", SENDER_PHONE, "Priya")

    assert "Priya" in student_body
    assert "Priya" in teacher_body
    assert student_body != teacher_body


async def test_onboarding_opens_on_the_institution_screen_with_an_empty_seed():
    """Navigating straight to a seeded screen skips the Flow's INIT endpoint,
    which is what keeps the results group hidden until the user searches.
    The empty seed is asserted field-by-field so a change inside
    `institution_screen_seed()` cannot hide behind equality with itself.
    """
    wiring = Wiring()

    await wiring.launcher.onboarding("student", SENDER_PHONE, "Priya")

    assert wiring.flow["screen"] == INSTITUTION_SCREEN
    assert wiring.flow["data"] == {"query": "", "results": [], "hasResults": False}


async def test_onboarding_uses_the_onboarding_flow_token():
    """Frozen identifier in `constants.py`, not a README sentence. The
    completion router keys on this token, so a silent rename here would
    orphan onboarding completions.
    """
    wiring = Wiring()

    await wiring.launcher.onboarding("student", SENDER_PHONE, "Priya")

    assert wiring.flow["flow_token"] == ONBOARDING_FLOW_TOKEN


async def test_onboarding_cta_is_not_a_form_cta():
    """Onboarding must not reuse a document/grade/profile button label."""
    onboarding = Wiring()
    grade = Wiring()

    await onboarding.launcher.onboarding("student", SENDER_PHONE, "Priya")
    await grade.launcher.launch(student(), grade_form())

    assert onboarding.flow["cta"]
    assert onboarding.flow["cta"] != grade.flow["cta"]


# --------------------------------------------------------------------------
# agent-sent form launches
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "form", "flow_id"),
    [
        (student(), document_form(), "s-doc"),
        (teacher(), document_form(), "t-doc"),
        (student(), grade_form(), "s-grade"),
        (teacher(), grade_form(), "t-grade"),
        (student(), profile_form(), "s-onb"),
        (teacher(), profile_form(), "t-onb"),
    ],
    ids=[
        "student-doc",
        "teacher-doc",
        "student-grade",
        "teacher-grade",
        "student-profile",
        "teacher-profile",
    ],
)
async def test_each_form_launches_that_personas_published_flow(profile, form, flow_id):
    """The profile form reuses the onboarding Flow: it collects the same fields."""
    wiring = Wiring()

    await wiring.launcher.launch(profile, form)

    assert wiring.flow["flow_id"] == flow_id


async def test_a_form_is_launched_to_the_users_own_phone():
    wiring = Wiring()

    await wiring.launcher.launch(student(phone="919999999999"), grade_form())

    assert wiring.flow["to"] == "919999999999"


async def test_the_forms_request_text_becomes_the_flow_token():
    """The token carries the model's request into the Flow so the completion
    can be routed back to what the user actually asked for.
    """
    wiring = Wiring()

    await wiring.launcher.launch(student(), grade_form(request_text="grade these papers"))

    assert wiring.flow["flow_token"] == "grade these papers"


async def test_the_forms_body_is_the_bubble_that_goes_out():
    wiring = Wiring()

    await wiring.launcher.launch(student(), grade_form(body="Upload the papers"))

    assert wiring.flow["body"] == "Upload the papers"


async def test_each_form_has_its_own_call_to_action():
    """A shared CTA would send "Start grading" on a profile update."""
    launched = []
    for form in (document_form(), grade_form(), profile_form()):
        wiring = Wiring()
        await wiring.launcher.launch(student(), form)
        launched.append(wiring.flow["cta"])

    assert all(launched)
    assert len(set(launched)) == 3


async def test_the_document_form_is_prefilled_with_what_the_model_already_knows():
    """The document Flow is the only one with prefillable screen data; the
    prefill is the form's own fields, minus the routing fields.
    """
    wiring = Wiring()

    await wiring.launcher.launch(student(), document_form())

    assert wiring.flow["screen"] == DOCUMENT_FORM_SCREEN
    data = wiring.flow["data"]
    assert data["detailsPrompt"] == "Which chapter?"
    assert data["kind"] == "practice"


async def test_the_document_prefill_omits_the_fields_that_only_route_the_message():
    """`type`, `form`, and `body` steer the adapter, not the Flow's screen;
    sending them as prefill would push unknown fields into the Flow.
    """
    wiring = Wiring()

    await wiring.launcher.launch(student(), document_form(body="Tell me more"))

    data = wiring.flow["data"]
    assert "type" not in data
    assert "form" not in data
    assert "body" not in data


async def test_the_document_prefill_omits_values_the_model_left_unset():
    """`difficulty` is absent for plan and notes; sending `None` would prefill
    the Flow's field with an empty selection.
    """
    wiring = Wiring()

    await wiring.launcher.launch(student(), document_form())

    assert "difficulty" not in wiring.flow["data"]


async def test_the_grade_form_opens_on_no_particular_screen():
    """Grading has nothing to prefill, so it opens at the Flow's own entry."""
    wiring = Wiring()

    await wiring.launcher.launch(student(), grade_form())

    assert wiring.flow["screen"] is None
    assert wiring.flow["data"] is None


async def test_a_profile_update_opens_seeded_exactly_like_first_time_onboarding():
    """Same Flow, same hidden-results behaviour: a profile update must not
    open showing a stale or empty results group.
    """
    wiring = Wiring()

    await wiring.launcher.launch(student(), profile_form())

    assert wiring.flow["screen"] == INSTITUTION_SCREEN
    assert wiring.flow["data"] == {"query": "", "results": [], "hasResults": False}


async def test_launching_a_form_returns_the_flows_message_id():
    """The caller feeds this id to the confirmation barrier, so it has to be
    the transport's real wamid, not the form or the body.
    """
    wiring = Wiring()

    wamid = await wiring.launcher.launch(student(), grade_form())

    assert wamid == "wamid.out1"
