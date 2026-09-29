"""Clone isolation for eval users. No network."""

from __future__ import annotations

import pytest

from eval_suite.users import EVAL_USERS, EvalUsers


@pytest.mark.asyncio
async def test_clone_is_isolated_from_the_fixture() -> None:
    """A clone's mutations never touch the shared EVAL_USERS fixture.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    users = EvalUsers()
    clone = users.clone("student-1783940069205", "eval-student-grade-12-math")
    assert clone.userId == "eval-student-grade-12-math--student-1783940069205"
    fixture = EVAL_USERS["eval-student-grade-12-math"]
    clone.scope.subjects.clear()
    assert fixture.scope.subjects
    fetched = await users.get_user(clone.userId)
    assert fetched.userId == clone.userId


@pytest.mark.asyncio
async def test_drop_removes_the_clone() -> None:
    """Dropping a clone makes it unreachable via get_user.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    users = EvalUsers()
    clone = users.clone("x", "eval-student-grade-6-math")
    users.drop(clone.userId)
    with pytest.raises(KeyError):
        await users.get_user(clone.userId)


@pytest.mark.asyncio
async def test_enrollment_is_empty_and_unknown_ids_crash() -> None:
    """Enrollment is always empty; batch_get_users raises for a missing id.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    users = EvalUsers()
    clone = users.clone("x", "eval-teacher-grade-9-science")
    enrollment = await users.get_enrollment_ids(clone.userId)
    assert enrollment.teacherUserIds == []
    assert enrollment.studentUserIds == []
    with pytest.raises(KeyError):
        await users.batch_get_users(["missing"])


@pytest.mark.asyncio
async def test_undirectory_school_refuses_ambassador_enroll() -> None:
    """Enrollment is refused when the clone's institution has no recognised id.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    users = EvalUsers()
    clone = users.clone("x", "eval-student-grade-9-math")
    result = await users.enroll_ambassador(clone.userId)
    assert result.result == "school_not_recognised"


@pytest.mark.asyncio
async def test_redeem_does_not_mint_a_card() -> None:
    """redeem_reward always raises — eval users have no gift-card mint.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    users = EvalUsers()
    clone = users.clone("x", "eval-student-grade-9-math")
    with pytest.raises(RuntimeError, match="no gift-card mint"):
        await users.redeem_reward(clone.userId, "amazon", 100)
