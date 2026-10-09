"""DELETE /internal/users/{userId} removes user-service-owned data.

Also cascades the referrer registry. README: "Delete one user and
user-service-owned data."
Ambassador registry: "school is read live off the profile" / identity-only
referrers docs. A missing profile for a registry entry is a bug — the cascade
test would catch a leftover ``referrers/{handle}`` whose ``userId`` 404s.
"""

from __future__ import annotations

import pytest

from infra.conversation import ContentMessage, HeldConversation
from infra.firestore.repos.onboarding import OnboardingRepository

from .helpers import (
    blocklist_exists,
    gifting_docs,
    onboarding_exists,
    referrer_doc,
    session_ids,
    student_profile,
    transcript_rows,
    user_doc,
    user_message,
)

pytestmark = pytest.mark.asyncio

BASE_MS = 1_790_000_000_000


async def _enroll_ambassador(api, phone: str, name: str) -> tuple[str, str]:
    """Create a student and enroll them as an ambassador; return (user_id,
    handle).

    Args:
        api: HTTP client for user_service's internal surface.
        phone: the new student's phone number.
        name: the new student's display name.
    Returns:
        The (user_id, ambassador handle) pair.
    Raises:
        None.
    """
    profile = await api.create_user(
        student_profile(phone, name=name, institution_id="school-1")
    )
    user_id = profile["userId"]
    enroll = await api.post(f"/internal/users/{user_id}/ambassador")
    assert enroll.status_code == 200
    return user_id, enroll.json()["handle"]


async def _populated_ambassador(api, db, phone: str) -> tuple[str, str]:
    """Enroll an ambassador who also has a block and a row.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
        phone: the ambassador's phone number.
    Returns:
        (user_id, ambassador handle).
    Raises:
        AssertionError: enrollment or the seed append did not succeed.
    """
    user_id, handle = await _enroll_ambassador(api, phone, "Priya")
    await api.put(f"/internal/blocklist/{user_id}")
    appended = await api.append(
        user_id, [user_message("hello", BASE_MS, turn_id="t1")]
    )
    assert appended.status_code == 200
    assert await session_ids(db, user_id) == [str(BASE_MS)]
    assert await referrer_doc(db, handle) is not None
    assert await blocklist_exists(db, user_id) is True
    return user_id, handle


async def _assert_deleted_keeps_block(
    api, db, user_id: str, handle: str
) -> None:
    """Owned documents are gone and the phone block is still present.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
        user_id: the deleted user's id.
        handle: the deleted ambassador's handle.
    Returns:
        None.
    Raises:
        AssertionError: owned data remains, or the phone block was removed.
    """
    assert await user_doc(db, user_id) is None
    gone = await api.get(f"/internal/users/{user_id}")
    assert gone.status_code == 404
    assert await referrer_doc(db, handle) is None
    assert await session_ids(db, user_id) == []
    assert await transcript_rows(db, user_id) == []
    assert await gifting_docs(db, user_id) == []
    # The blocklist is keyed by phone identity, not owned by the profile:
    # deleting the profile must not let a blocked phone re-onboard unblocked.
    assert await blocklist_exists(db, user_id) is True


async def test_delete_user_removes_owned_data_cascades_registry_and_keeps_phone_block(
    api, db
):
    """Deleting a user removes their data and registry entry, but keeps the
    phone block.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, handle = await _populated_ambassador(api, db, "910000050001")
    deleted = await api.delete(f"/internal/users/{user_id}")
    assert deleted.status_code == 204
    await _assert_deleted_keeps_block(api, db, user_id, handle)


async def _assert_live_roster(api, handle: str, other_handle: str) -> None:
    """The roster omits the deleted handle and every remaining row has a
    profile.

    Args:
        api: HTTP client for user_service's internal surface.
        handle: the deleted ambassador's handle, which must be absent.
        other_handle: the surviving ambassador's handle, which must remain.
    Returns:
        None.
    Raises:
        AssertionError: the roster is wrong or a row has no live profile.
    """
    roster = await api.get("/internal/ambassadors")
    assert roster.status_code == 200
    handles = [row["handle"] for row in roster.json()]
    assert handle not in handles
    assert other_handle in handles
    for row in roster.json():
        profile = await api.get(f"/internal/users/{row['userId']}")
        assert profile.status_code == 200, (
            f"ambassador roster row handle={row['handle']!r} userId={
                row['userId']!r
            } "
            f"has no profile (status {profile.status_code}); a missing profile "
            f"for a "
            "registry entry is a bug"
        )


async def test_delete_cascade_would_catch_a_dangling_ambassador_registry_entry(
    api, db
):
    """A leftover referrers/{handle} whose profile is gone is the documented
    bug.

    After DELETE, every ambassador roster row must still resolve to a live
    profile. The deleted user's handle must not appear in GET
    /internal/ambassadors, and GET /internal/users/{id}/ambassador on the
    deleted id must not surface a registry row with a missing profile.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    user_id, handle = await _enroll_ambassador(api, "910000050002", "Kabir")
    other_id, other_handle = await _enroll_ambassador(
        api, "910000050003", "Leela"
    )

    deleted = await api.delete(f"/internal/users/{user_id}")
    assert deleted.status_code == 204

    await _assert_live_roster(api, handle, other_handle)

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
    """onboarding is whatsapp_adapter-owned; user DELETE must not wipe it.

    Args:
        api: HTTP client for user_service's internal surface.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    profile = await api.create_user(
        student_profile("910000050004", name="Keep")
    )
    user_id = profile["userId"]
    pending = HeldConversation(
        messages=[
            ContentMessage(
                type="text",
                content={"body": "hello"},
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
