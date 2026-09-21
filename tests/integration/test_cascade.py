"""DELETE /internal/users/{userId} removes user-service-owned data and cascades the referrer registry.

README: "Delete one user and user-service-owned data."
Ambassador registry: "school is read live off the profile" / identity-only
referrers docs. A missing profile for a registry entry is a bug — the cascade
test would catch a leftover ``referrers/{handle}`` whose ``userId`` 404s.
"""

from __future__ import annotations

import pytest

from infra.conversation import ContentMessage, PendingAction
from infra.firestore.repos.onboarding import OnboardingRepository

from .helpers import (
    blocklist_exists,
    enrollment_ids,
    gifting_docs,
    onboarding_exists,
    referrer_doc,
    session_ids,
    student_profile,
    teacher_profile,
    transcript_rows,
    user_doc,
    user_message,
)

pytestmark = pytest.mark.asyncio

BASE_MS = 1_790_000_000_000


async def _enroll_ambassador(api, phone: str, name: str) -> tuple[str, str]:
    profile = await api.create_user(
        student_profile(phone, name=name, institution_id="school-1")
    )
    user_id = profile["userId"]
    enroll = await api.post(f"/internal/users/{user_id}/ambassador")
    assert enroll.status_code == 200
    return user_id, enroll.json()["handle"]


async def test_delete_user_removes_owned_data_and_cascades_referrer_registry(api, db):
    user_id, handle = await _enroll_ambassador(api, "910000050001", "Priya")
    teacher = await api.create_user(teacher_profile("910000050101", name="Teacher"))
    enroll = await api.post(
        "/internal/enrollments",
        json={"teacherUserId": teacher["userId"], "studentUserId": user_id},
    )
    assert enroll.status_code == 204
    await api.put(f"/internal/blocklist/{user_id}")
    appended = await api.append(user_id, [user_message("hello", BASE_MS, turn_id="t1")])
    assert appended.status_code == 200
    assert await session_ids(db, user_id) == [str(BASE_MS)]
    assert await referrer_doc(db, handle) is not None
    assert await blocklist_exists(db, user_id) is True

    deleted = await api.delete(f"/internal/users/{user_id}")
    assert deleted.status_code == 204

    assert await user_doc(db, user_id) is None
    gone = await api.get(f"/internal/users/{user_id}")
    assert gone.status_code == 404
    assert await referrer_doc(db, handle) is None
    assert await session_ids(db, user_id) == []
    assert await transcript_rows(db, user_id) == []
    assert await gifting_docs(db, user_id) == []
    assert enrollment_id_for(user_id, teacher["userId"]) not in await enrollment_ids(db)
    assert await blocklist_exists(db, user_id) is False


def enrollment_id_for(student_id: str, teacher_id: str) -> str:
    return f"{teacher_id}__{student_id}"


async def test_delete_cascade_would_catch_a_dangling_ambassador_registry_entry(api, db):
    """A leftover referrers/{handle} whose profile is gone is the documented bug.

    After DELETE, every ambassador roster row must still resolve to a live
    profile. The deleted user's handle must not appear in GET /internal/ambassadors,
    and GET /internal/users/{id}/ambassador on the deleted id must not surface a
    registry row with a missing profile.
    """
    user_id, handle = await _enroll_ambassador(api, "910000050002", "Kabir")
    other_id, other_handle = await _enroll_ambassador(api, "910000050003", "Leela")

    deleted = await api.delete(f"/internal/users/{user_id}")
    assert deleted.status_code == 204

    roster = await api.get("/internal/ambassadors")
    assert roster.status_code == 200
    handles = [row["handle"] for row in roster.json()]
    assert handle not in handles
    assert other_handle in handles

    for row in roster.json():
        profile = await api.get(f"/internal/users/{row['userId']}")
        assert profile.status_code == 200, (
            f"ambassador roster row handle={row['handle']!r} userId={row['userId']!r} "
            f"has no profile (status {profile.status_code}); a missing profile for a "
            "registry entry is a bug"
        )

    dangling = await referrer_doc(db, handle)
    assert dangling is None

    status = await api.get(f"/internal/users/{user_id}/ambassador")
    # Deleted user: no profile, so no ambassador status. 404 on the user, or
    # a 200-null, both mean "not a live ambassador". A 200 body with a handle
    # would be the dangling-registry bug.
    assert status.status_code in (200, 404)
    if status.status_code == 200:
        assert status.json() is None


async def test_delete_does_not_remove_adapter_owned_onboarding(api, db):
    """onboarding is whatsapp_adapter-owned; user DELETE must not wipe it."""
    profile = await api.create_user(student_profile("910000050004", name="Keep"))
    user_id = profile["userId"]
    pending = PendingAction(
        action="select_persona",
        messages=[
            ContentMessage(
                type="text",
                content={"body": "hello"},
                phone_number_id="111",
                sender_phone="910000050099",
                sender_id="bsuid-keep-onboarding",
                profile_name="Stranger",
                message_id="wamid.keep.1",
                timestamp="1750000000",
            )
        ],
    )
    await OnboardingRepository(db).set("bsuid-keep-onboarding", pending)
    assert await onboarding_exists(db, "bsuid-keep-onboarding") is True

    deleted = await api.delete(f"/internal/users/{user_id}")
    assert deleted.status_code == 204
    assert await onboarding_exists(db, "bsuid-keep-onboarding") is True


async def test_delete_unknown_user_does_not_crash(api):
    """DELETE is documented as deleting owned data, not as a lookup-404, but
    the README names no status for an unknown user_id either. `204` is
    explicitly named in tests/outcomes/UNCERTAINTY.md as a guess this suite
    must not keep just because it happens to be green -- only the
    qualitative claim (must not crash) is asserted here.
    """
    response = await api.delete("/internal/users/never-existed")
    assert response.status_code < 500
