"""Case constructors shared by every corpus module."""

from __future__ import annotations

from ..constants import REQUIRED_TAGS, TOOL_CREATE, TOOL_IMAGE, TOOL_PROFILE
from ..types import Attachments, EvalCase, EvalTurn, EvalUserId, Expect, KnownRed, Stack

LIVE = Attachments(live=True)
FRESH = Attachments(live=True, fresh=True)
PDF = Attachments(live=True, suffix=".pdf")
PPTX = Attachments(live=True, suffix=".pptx")
PNG = Attachments(live=True, suffix=".png")
TWO = Attachments(min_count=2, live=True)
CREATE = Stack(tools_any=["create_document"], required_tool_must_succeed=True)
DECK = Stack(tools_any=["create_presentation"], required_tool_must_succeed=True)
IMAGE = Stack(tools_any=[TOOL_IMAGE], required_tool_must_succeed=True)
NO_CREATE = Stack(tools_none=list(TOOL_CREATE))
NO_PROFILE = Stack(tools_none=[TOOL_PROFILE])
IMAGE_KEEP_PROFILE = Stack(
    tools_any=[TOOL_IMAGE],
    tools_none=[TOOL_PROFILE],
    required_tool_must_succeed=True,
)
ASK = r"\?"


def doc(
    *need: str,
    suffix: str | None = None,
    fresh: bool = False,
    min_count: int = 1,
) -> Attachments:
    return Attachments(
        live=True,
        suffix=suffix,
        fresh=fresh,
        min_count=min_count,
        contains=list(need),
    )


def turn(prompt: str, expect: Expect | None = None, review: list[str] | None = None) -> EvalTurn:
    return EvalTurn(prompt=prompt, expect=expect or Expect(), review=review or [])


def case(
    case_id: str,
    user_id: EvalUserId,
    tags: set[str],
    turns: list[EvalTurn],
    *,
    profile_unchanged: bool = False,
    waive: set[str] | None = None,
    known_red: KnownRed | None = None,
) -> EvalCase:
    return EvalCase(
        id=case_id,
        user_id=user_id,
        tags=tags,
        turns=turns,
        profile_unchanged=profile_unchanged,
        waive=waive or set(),
        known_red=known_red,
    )


def assert_corpus(cases: list[EvalCase]) -> list[EvalCase]:
    ids = [item.id for item in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case id")
    used_tags = {tag for item in cases for tag in item.tags}
    for item in cases:
        if not {"student", "teacher"} & item.tags:
            raise ValueError(f"{item.id} missing persona tag")
        if not item.profile_unchanged and not any(
            turn.expect.hard_armed() for turn in item.turns
        ):
            raise ValueError(f"{item.id} has no hard Expect")
    for group, required in REQUIRED_TAGS.items():
        missing = [tag for tag in required if tag not in used_tags]
        if missing:
            raise ValueError(f"corpus missing {group} tags: {missing}")
    return cases
