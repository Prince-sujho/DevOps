"""Turning a completed profile Flow into a create or update write.

README: a profile update persists institution and scope. Independently
statable: an empty institution id is "not listed" (no directory id invented);
the student's one grade and the teacher's grades list must not be swapped;
leading/trailing spaces on a typed name are not part of the identity.
"""

from __future__ import annotations

from typing import get_args

import pytest

from infra.clients.users import Persona, StudentScope, TeacherScope
from whatsapp_adapter.app.src.input.profiles import (
    profile_input_from_flow,
    profile_update_from_flow,
)

from .factories import (
    PROFILE_FLOW_RESPONSE,
    STUDENT_ONBOARDING_RESPONSE,
    TEACHER_ONBOARDING_RESPONSE,
)

pytestmark = pytest.mark.boundary


def test_an_unlisted_school_is_stored_without_a_directory_id():
    """A typed-in name has no id; inventing one would attach the user to a
    school they did not pick.
    """
    update = profile_update_from_flow("student", PROFILE_FLOW_RESPONSE)

    assert update.institution.id is None
    assert update.institution.name == "Delhi Public School"


def test_a_listed_school_keeps_the_directory_id_the_flow_sent():
    update = profile_update_from_flow("student", STUDENT_ONBOARDING_RESPONSE)

    assert update.institution.id == "school-1"


def test_a_student_write_carries_one_grade_not_a_list():
    response = {
        "institutionId": "school-1",
        "institution": "Kendriya Vidyalaya",
        "grade": "6",
        "subjects": ["science"],
    }
    update = profile_update_from_flow("student", response)

    assert isinstance(update.scope, StudentScope)
    assert update.scope.grade == 6
    assert update.name is None


def test_a_teacher_write_carries_every_grade_they_declared():
    response = {
        "institutionId": "school-1",
        "institution": "Kendriya Vidyalaya",
        "grades": ["11", "12"],
        "subjects": ["mathematics"],
    }
    update = profile_update_from_flow("teacher", response)

    assert isinstance(update.scope, TeacherScope)
    assert update.scope.grades == [11, 12]
    assert update.name is None


def test_create_input_strips_the_typed_name():
    created = profile_input_from_flow(
        "919876543210", "student", "  Priya  ", STUDENT_ONBOARDING_RESPONSE
    )

    assert created.name == "Priya"
    assert created.phone == "919876543210"


@pytest.mark.parametrize("persona", get_args(Persona))
def test_every_persona_can_build_both_a_create_and_an_update(persona):
    """A fifth persona with no match arm would silently drop the Flow."""
    response = (
        STUDENT_ONBOARDING_RESPONSE
        if persona == "student"
        else TEACHER_ONBOARDING_RESPONSE
    )

    created = profile_input_from_flow("919876543210", persona, "Priya", response)
    updated = profile_update_from_flow(persona, response)

    assert created.persona == persona
    assert updated.name is None
    if persona == "student":
        assert isinstance(created.scope, StudentScope)
        assert isinstance(updated.scope, StudentScope)
    else:
        assert isinstance(created.scope, TeacherScope)
        assert isinstance(updated.scope, TeacherScope)
