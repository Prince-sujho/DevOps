"""Request-validation tests for POST /respond.

GenerateRequest (infra/clients/text_agent/types/turns.py) requires `user`,
`threadKey`, `message`, and `previousResponseId` (Optional[str] with no
default -- required, but None is a valid value). `user` is the discriminated
UserProfile union on `persona` (`student` | `teacher`); StudentProfile
requires `scope.grade`, TeacherProfile requires `scope.grades`
(infra/clients/users/types/profiles.py). FastAPI's own default shape for a
Pydantic validation failure is `{"detail": [...]}` with at least one entry;
we assert that shape, not specific message text.
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers, respond_body, student_profile, scripted_turn


def assert_is_standard_422(response) -> None:
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    assert len(body["detail"]) >= 1


@pytest.mark.asyncio
async def test_missing_user_field_is_422(client):
    body = respond_body()
    del body["user"]
    response = await client.post("/respond", json=body, headers=auth_headers())
    assert_is_standard_422(response)


@pytest.mark.asyncio
async def test_persona_outside_discriminator_is_422(client):
    body = respond_body(user=student_profile(persona="parent"))
    response = await client.post("/respond", json=body, headers=auth_headers())
    assert_is_standard_422(response)


@pytest.mark.asyncio
async def test_student_missing_scope_grade_is_422(client):
    user = student_profile()
    del user["scope"]["grade"]
    body = respond_body(user=user)
    response = await client.post("/respond", json=body, headers=auth_headers())
    assert_is_standard_422(response)


@pytest.mark.asyncio
async def test_teacher_missing_scope_grades_is_422(client):
    teacher = student_profile(
        persona="teacher",
        scope={"subjects": ["mathematics"]},
    )
    body = respond_body(user=teacher)
    response = await client.post("/respond", json=body, headers=auth_headers())
    assert_is_standard_422(response)


@pytest.mark.asyncio
async def test_missing_previous_response_id_is_accepted(client, fakes):
    """README §Request Format's own example request body omits
    `previousResponseId` entirely and presents it as a valid request -- the
    README never marks it required. Sending that example verbatim must be
    accepted, not rejected.

    This is the WRONG->rewritten version of the old
    `test_missing_previous_response_id_is_422`: `GenerateRequest.
    previousResponseId: Optional[str]` currently has no default, making the
    field required despite being `Optional`, so omitting it 422s today (see
    FINDINGS text_agent). Left asserting the README's documented shape on
    purpose -- a failure here is the correct oracle for that mismatch.
    """
    fakes.openai.script.append(scripted_turn("Hi!", "resp_fake_no_tip_001"))
    body = respond_body()
    response = await client.post("/respond", json=body, headers=auth_headers())
    assert response.status_code == 200, (
        "README's own request example omits previousResponseId and presents "
        "it as valid -- a 422 here means the field is undocumentedly required"
    )
