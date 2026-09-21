"""In-memory users for eval clones. Methods RespondService and its tools call."""

from __future__ import annotations

from typing import get_args

from infra.clients.users import (
    AmbassadorRefusal,
    AmbassadorStatus,
    EnrollmentIdsResponse,
    GiftCard,
    Institution,
    ProfileUpdate,
    RewardsList,
    StudentProfile,
    StudentScope,
    TeacherProfile,
    TeacherScope,
    UserProfile,
)
from infra.curriculum import Subject

from .types import EvalUserId

_CREATED = 1_700_000_000_000
_SCHOOL = Institution(name="Eval School")


def _student(
    user_id: EvalUserId, grade: int, subjects: list[Subject], phone: str
) -> StudentProfile:
    return StudentProfile(
        userId=user_id,
        phone=phone,
        name=user_id.replace("eval-student-", "").replace("-", " ").title(),
        institution=_SCHOOL,
        persona="student",
        createdAtMs=_CREATED,
        scope=StudentScope(grade=grade, subjects=subjects),
    )


def _teacher(
    user_id: EvalUserId, grades: list[int], subjects: list[Subject], phone: str
) -> TeacherProfile:
    return TeacherProfile(
        userId=user_id,
        phone=phone,
        name=user_id.replace("eval-teacher-", "").replace("-", " ").title(),
        institution=_SCHOOL,
        persona="teacher",
        createdAtMs=_CREATED,
        scope=TeacherScope(grades=grades, subjects=subjects),
    )


EVAL_USERS: dict[EvalUserId, UserProfile] = {
    "eval-student-grade-6-math": _student(
        "eval-student-grade-6-math", 6, [Subject.MATHEMATICS], "+910000000001"
    ),
    "eval-student-grade-7-science": _student(
        "eval-student-grade-7-science", 7, [Subject.SCIENCE], "+910000000002"
    ),
    "eval-student-grade-8-social-science": _student(
        "eval-student-grade-8-social-science",
        8,
        [Subject.SOCIAL_SCIENCE],
        "+910000000003",
    ),
    "eval-student-grade-9-math": _student(
        "eval-student-grade-9-math", 9, [Subject.MATHEMATICS], "+910000000004"
    ),
    "eval-student-grade-9-social-science": _student(
        "eval-student-grade-9-social-science",
        9,
        [Subject.SOCIAL_SCIENCE],
        "+910000000005",
    ),
    "eval-student-grade-10-math": _student(
        "eval-student-grade-10-math", 10, [Subject.MATHEMATICS], "+910000000006"
    ),
    "eval-student-grade-10-science": _student(
        "eval-student-grade-10-science", 10, [Subject.SCIENCE], "+910000000007"
    ),
    "eval-student-grade-11-math": _student(
        "eval-student-grade-11-math", 11, [Subject.MATHEMATICS], "+910000000008"
    ),
    "eval-student-grade-12-math": _student(
        "eval-student-grade-12-math", 12, [Subject.MATHEMATICS], "+910000000009"
    ),
    "eval-student-grade-12-commerce": _student(
        "eval-student-grade-12-commerce",
        12,
        [Subject.BUSINESS_STUDIES, Subject.ACCOUNTANCY, Subject.ECONOMICS],
        "+910000000010",
    ),
    "eval-student-grade-12-accountancy": _student(
        "eval-student-grade-12-accountancy", 12, [Subject.ACCOUNTANCY], "+910000000011"
    ),
    "eval-student-grade-12-humanities": _student(
        "eval-student-grade-12-humanities",
        12,
        [Subject.HISTORY, Subject.POLITICAL_SCIENCE, Subject.ENGLISH],
        "+910000000012",
    ),
    "eval-student-grade-12-physics": _student(
        "eval-student-grade-12-physics",
        12,
        [Subject.PHYSICS, Subject.CHEMISTRY, Subject.MATHEMATICS],
        "+910000000013",
    ),
    "eval-teacher-grade-9-science": _teacher(
        "eval-teacher-grade-9-science", [9], [Subject.SCIENCE], "+910000000014"
    ),
    "eval-teacher-grade-9-social-science": _teacher(
        "eval-teacher-grade-9-social-science",
        [9],
        [Subject.SOCIAL_SCIENCE],
        "+910000000015",
    ),
    "eval-teacher-grade-6-8-science": _teacher(
        "eval-teacher-grade-6-8-science",
        [6, 7, 8],
        [Subject.SCIENCE],
        "+910000000016",
    ),
    "eval-teacher-grade-9-10-math": _teacher(
        "eval-teacher-grade-9-10-math",
        [9, 10],
        [Subject.MATHEMATICS],
        "+910000000017",
    ),
    "eval-teacher-grade-11-12-math": _teacher(
        "eval-teacher-grade-11-12-math",
        [11, 12],
        [Subject.MATHEMATICS],
        "+910000000018",
    ),
    "eval-teacher-grade-11-12-physics": _teacher(
        "eval-teacher-grade-11-12-physics",
        [11, 12],
        [Subject.PHYSICS],
        "+910000000019",
    ),
    "eval-teacher-grade-11-12-commerce": _teacher(
        "eval-teacher-grade-11-12-commerce",
        [11, 12],
        [Subject.BUSINESS_STUDIES, Subject.ACCOUNTANCY, Subject.ECONOMICS],
        "+910000000020",
    ),
    "eval-teacher-grade-11-12-humanities": _teacher(
        "eval-teacher-grade-11-12-humanities",
        [11, 12],
        [Subject.HISTORY, Subject.POLITICAL_SCIENCE],
        "+910000000021",
    ),
}

assert set(EVAL_USERS) == set(get_args(EvalUserId))


class EvalUsers:
    def __init__(self) -> None:
        self._users: dict[str, UserProfile] = dict(EVAL_USERS)
        self._ambassadors: dict[str, AmbassadorStatus] = {}

    def clone(self, case_id: str, user_id: EvalUserId) -> UserProfile:
        isolated_id = f"{user_id}--{case_id}"
        clone = EVAL_USERS[user_id].model_copy(deep=True, update={"userId": isolated_id})
        self._users[isolated_id] = clone
        return clone

    def drop(self, user_id: str) -> None:
        del self._users[user_id]
        self._ambassadors.pop(user_id, None)

    async def get_user(self, user_id: str) -> UserProfile:
        return self._users[user_id]

    async def update_profile(self, user_id: str, update: ProfileUpdate) -> UserProfile:
        user = self._users[user_id]
        payload = update.model_dump(exclude_none=True)
        updated = user.model_copy(update={key: getattr(update, key) for key in payload})
        self._users[user_id] = updated
        return updated

    async def get_enrollment_ids(self, user_id: str) -> EnrollmentIdsResponse:
        if user_id not in self._users:
            raise KeyError(user_id)
        return EnrollmentIdsResponse(teacherUserIds=[], studentUserIds=[])

    async def batch_get_users(self, user_ids: list[str]) -> list[UserProfile]:
        return [self._users[user_id] for user_id in user_ids]

    async def enroll_ambassador(self, user_id: str) -> AmbassadorStatus | AmbassadorRefusal:
        user = self._users[user_id]
        if user.institution.id is None:
            return AmbassadorRefusal(result="school_not_recognised")
        raise RuntimeError(f"directory enrollment is not implemented for {user_id}")

    async def get_ambassador_status(self, user_id: str) -> AmbassadorStatus | None:
        if user_id not in self._users:
            raise KeyError(user_id)
        return self._ambassadors.get(user_id)

    async def list_rewards(self, user_id: str) -> RewardsList:
        status = self._ambassadors[user_id]
        return RewardsList(balanceInr=status.balanceInr, options=[])

    async def redeem_reward(self, user_id: str, product_id: str, amount_inr: int) -> GiftCard:
        raise RuntimeError(
            f"eval user {user_id} has no gift-card mint; {product_id}/{amount_inr}"
        )
