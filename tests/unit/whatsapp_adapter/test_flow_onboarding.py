"""Onboarding Flow data-exchange: ping, INIT, and the screen router.

README: POST /flows/onboarding is the encrypted data endpoint. Screen ids and
the ping health shape are Meta Flow pins (the published JSON), not README
sentences — handwritten here so a constant rename cannot agree with itself.

Search results still end with the keep-as-typed escape; a listed pick must
carry a directory id, a not-listed pick must not invent one (the same
empty-id rule Wave D already pins on the profile write).
"""

from __future__ import annotations

import pytest

from infra.schools import get_school
from whatsapp_adapter.app.src.flows.onboarding import onboarding_response_payload

pytestmark = pytest.mark.boundary


def exchange(data: dict) -> dict:
    return onboarding_response_payload({"action": "data_exchange", "data": data})


# --------------------------------------------------------------------------
# ping / INIT
# --------------------------------------------------------------------------


def test_a_ping_reports_the_endpoint_active():
    """Meta health-checks the data endpoint; anything other than active
    makes the client refresh the public key and retry.
    """
    assert onboarding_response_payload({"action": "ping"}) == {
        "data": {"status": "active"}
    }


def test_init_opens_the_institution_screen_with_no_results():
    """The results group stays hidden until the user types a query."""
    response = onboarding_response_payload({"action": "INIT"})

    assert response["screen"] == "INSTITUTION_SCREEN"
    assert response["data"] == {"query": "", "results": [], "hasResults": False}


def test_an_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="Unsupported onboarding flow action"):
        onboarding_response_payload({"action": "COMPLETE"})


# --------------------------------------------------------------------------
# institution search
# --------------------------------------------------------------------------


def test_a_blank_query_does_not_invent_results():
    response = exchange({"institution": "   "})

    assert response["screen"] == "INSTITUTION_SCREEN"
    assert response["data"]["query"] == ""
    assert response["data"]["results"] == []
    assert response["data"]["hasResults"] is False


def test_a_typed_query_is_stripped_and_returns_directory_hits_plus_the_escape():
    response = exchange({"institution": "  Delhi Public School  "})

    assert response["screen"] == "INSTITUTION_SCREEN"
    assert response["data"]["query"] == "Delhi Public School"
    assert response["data"]["hasResults"] is True
    results = response["data"]["results"]
    assert results[-1]["id"] == "not_listed"
    assert results[-1]["title"] == "None of these"
    assert any(row["id"] != "not_listed" for row in results)


def test_choosing_a_listed_school_carries_its_directory_id_onto_the_grade_screen():
    """The more specific {institutionChoice, institution} payload must win
    over the search arm that also matches on `institution`.
    """
    hits = exchange({"institution": "Delhi Public School"})["data"]["results"]
    chosen = next(row for row in hits if row["id"] != "not_listed")
    listed = get_school(chosen["id"])

    response = exchange(
        {"institutionChoice": chosen["id"], "institution": "ignored typed name"}
    )

    assert response["screen"] == "GRADE_SCREEN"
    assert response["data"]["institutionId"] == listed.id
    assert response["data"]["institution"] == listed.name
    assert response["data"]["institution"] != "ignored typed name"


def test_choosing_none_of_these_keeps_the_typed_name_without_a_directory_id():
    response = exchange(
        {"institutionChoice": "not_listed", "institution": "  Village School  "}
    )

    assert response["screen"] == "GRADE_SCREEN"
    assert response["data"]["institutionId"] == ""
    assert response["data"]["institution"] == "Village School"


# --------------------------------------------------------------------------
# grades → subjects
# --------------------------------------------------------------------------


def test_a_student_grade_opens_subjects_labelled_for_that_one_grade():
    response = exchange({"studentGrade": "8"})

    assert response["screen"] == "SUBJECTS_SCREEN"
    assert response["data"]["gradesLabel"] == "Grade 8"
    ids = [option["id"] for option in response["data"]["subjectOptions"]]
    assert "science" in ids
    assert "accountancy" not in ids


def test_teacher_grades_open_subjects_labelled_for_every_grade_they_declared():
    response = exchange({"teacherGrades": ["11", "12"]})

    assert response["screen"] == "SUBJECTS_SCREEN"
    assert response["data"]["gradesLabel"] == "Grades 11, 12"
    ids = [option["id"] for option in response["data"]["subjectOptions"]]
    assert "accountancy" in ids
    assert "science" not in ids


def test_an_unknown_data_exchange_payload_is_rejected():
    with pytest.raises(ValueError, match="Unsupported onboarding data-exchange payload"):
        exchange({"unexpected": True})
