"""One phone is one user, and its first touch is decided once.

infra UsersRepository.create_user: "an existing phone is returned unchanged";
BaseUserProfile.attribution: "set at creation, never rewritten". Ambassador
points are derived from attribution, so a rewrite would move reward credit.
"""

from __future__ import annotations

import pytest

from infra.attribution import referral_prefill

from .helpers import student_profile

pytestmark = pytest.mark.asyncio


async def _ambassador(api, phone: str, name: str) -> tuple[str, str]:
    holder = await api.create_user(student_profile(phone, name=name, institution_id="school-1"))
    enroll = await api.post(f"/internal/users/{holder['userId']}/ambassador")
    assert enroll.status_code == 200
    return holder["userId"], enroll.json()["handle"]


async def _points(api, user_id: str) -> int:
    status = await api.get(f"/internal/users/{user_id}/ambassador")
    assert status.status_code == 200
    return status.json()["points"]


async def test_recreating_a_phone_keeps_the_user_and_its_first_touch(api):
    first_id, first_handle = await _ambassador(api, "910000080001", "Ravi")
    second_id, second_handle = await _ambassador(api, "910000080002", "Sita")
    phone = "910000080101"

    original = await api.create_user(
        student_profile(phone, name="Original"), texts=[referral_prefill(first_handle, None)]
    )
    again = await api.create_user(
        student_profile(phone, name="Impostor"), texts=[referral_prefill(second_handle, None)]
    )

    assert again["userId"] == original["userId"]
    assert again["createdAtMs"] == original["createdAtMs"]
    assert again["name"] == original["name"]
    assert again["attribution"] == original["attribution"]
    assert original["attribution"]["handle"] == first_handle
    assert await _points(api, first_id) == 1
    assert await _points(api, second_id) == 0
