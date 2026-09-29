"""Contracts for one eval case and one run."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    model_validator,
)

Modality = Literal[
    "text",
    "image",
    "document",
    "buttons",
    "list",
    "url",
    "location_request",
    "contact",
    "gift_card",
    "form",
]
Script = Literal["latin", "devanagari", "kannada", "malayalam"]
CaseStatus = Literal["pass", "fail", "xfail", "xpass"]

EvalUserId = Literal[
    "eval-student-grade-6-math",
    "eval-student-grade-7-science",
    "eval-student-grade-8-social-science",
    "eval-student-grade-9-math",
    "eval-student-grade-9-social-science",
    "eval-student-grade-10-math",
    "eval-student-grade-10-science",
    "eval-student-grade-11-math",
    "eval-student-grade-12-math",
    "eval-student-grade-12-commerce",
    "eval-student-grade-12-accountancy",
    "eval-student-grade-12-humanities",
    "eval-student-grade-12-physics",
    "eval-teacher-grade-9-science",
    "eval-teacher-grade-9-social-science",
    "eval-teacher-grade-6-8-science",
    "eval-teacher-grade-9-10-math",
    "eval-teacher-grade-11-12-math",
    "eval-teacher-grade-11-12-physics",
    "eval-teacher-grade-11-12-commerce",
    "eval-teacher-grade-11-12-humanities",
]


def _compile(value: str | re.Pattern[str]) -> re.Pattern[str]:
    """value as a compiled pattern, compiling it if it's still a plain string.

    Args:
        value: a regex string, or an already-compiled pattern.
    Returns:
        The compiled pattern.
    Raises:
        re.error: value is a string that isn't a valid regex.
    """
    return value if isinstance(value, re.Pattern) else re.compile(value)


def _compile_all(values: list[str | re.Pattern[str]]) -> list[re.Pattern[str]]:
    """Every value compiled via _compile.

    Args:
        values: regex strings and/or already-compiled patterns.
    Returns:
        The compiled patterns, in order.
    Raises:
        re.error: any value is a string that isn't a valid regex.
    """
    return [_compile(value) for value in values]


Patterns = Annotated[list[re.Pattern[str]], BeforeValidator(_compile_all)]


class Attachments(BaseModel):
    min_count: int = 1
    suffix: str | None = None
    live: bool = False
    fresh: bool = False
    contains: Patterns = Field(default_factory=list)

    @model_validator(mode="after")
    def _contains_is_live(self) -> Attachments:
        """Enforce that a contains-pattern check is only meaningful on a live
        attachment.

        Args:
            None.
        Returns:
            self, unchanged.
        Raises:
            ValueError: contains is set but live is False.
        """
        if self.contains and not self.live:
            raise ValueError("attachment contains requires live=True")
        return self


class Stack(BaseModel):
    tools_any: list[str] = Field(default_factory=list)
    tools_none: list[str] = Field(default_factory=list)
    tools_all: list[str] = Field(default_factory=list)
    required_tool_must_succeed: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> Stack:
        """Enforce that no tool is both required (any/all) and forbidden.

        Args:
            None.
        Returns:
            self, unchanged.
        Raises:
            ValueError: a tool appears in tools_none and in tools_any/tools_all.
        """
        overlap = (set(self.tools_any) | set(self.tools_all)) & set(
            self.tools_none
        )
        if overlap:
            raise ValueError(
                f"tool both required and forbidden: {sorted(overlap)}"
            )
        return self


class Expect(BaseModel):
    modalities_any: list[Modality] = Field(default_factory=list)
    modalities_none: list[Modality] = Field(default_factory=list)
    attachments: Attachments | None = None
    script: Script | None = None
    word_count_min: int | None = None
    word_count_max: int | None = None
    stack: Stack | None = None
    hard_text_matches: Patterns = Field(default_factory=list)
    hard_text_forbidden: Patterns = Field(default_factory=list)
    text_matches: Patterns = Field(default_factory=list)
    text_forbidden: Patterns = Field(default_factory=list)
    ends_with_prompt: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> Expect:
        """Enforce Expect's internal consistency rules.

        Args:
            None.
        Returns:
            self, unchanged.
        Raises:
            ValueError: a modality is both required and forbidden, attachments
                are required while document/image are forbidden modalities, or
                word_count_min exceeds word_count_max.
        """
        overlap = set(self.modalities_any) & set(self.modalities_none)
        if overlap:
            raise ValueError(
                f"modality both required and forbidden: {sorted(overlap)}"
            )
        if self.attachments and {"document", "image"} & set(
            self.modalities_none
        ):
            raise ValueError(
                "attachments required while document/image forbidden"
            )
        if (
            self.word_count_min is not None
            and self.word_count_max is not None
            and self.word_count_min > self.word_count_max
        ):
            raise ValueError("word_count_min > word_count_max")
        return self

    def hard_armed(self) -> bool:
        """Whether this Expect actually asserts anything hard.

        Args:
            None.
        Returns:
            True if any hard-checkable field is set (modality, attachment,
            script, word count, stack, or hard text pattern).
        Raises:
            None.
        """
        return bool(
            self.modalities_any
            or self.modalities_none
            or self.attachments
            or self.script
            or self.stack
            or self.word_count_min is not None
            or self.word_count_max is not None
            or self.hard_text_matches
            or self.hard_text_forbidden
        )


class EvalTurn(BaseModel):
    prompt: str
    expect: Expect = Field(default_factory=Expect)
    review: list[str] = Field(default_factory=list)


class KnownRed(BaseModel):
    defect: str
    owner: Literal["prompt", "engineering", "accuracy"]
    signature: Annotated[
        re.Pattern[str],
        BeforeValidator(_compile),
        PlainSerializer(lambda pattern: pattern.pattern, return_type=str),
    ]
    opened_on: date


class EvalCase(BaseModel):
    id: str
    user_id: EvalUserId
    tags: set[str]
    turns: list[EvalTurn] = Field(min_length=1)
    profile_unchanged: bool = False
    waive: set[str] = Field(default_factory=set)
    known_red: KnownRed | None = None

    @model_validator(mode="after")
    def _armed(self) -> EvalCase:
        """Enforce that every case actually asserts something, unless it's
        profile_unchanged-only.

        Args:
            None.
        Returns:
            self, unchanged.
        Raises:
            ValueError: profile_unchanged is False and no turn has a hard
                Expect.
        """
        if self.profile_unchanged:
            return self
        if not any(turn.expect.hard_armed() for turn in self.turns):
            raise ValueError(f"{self.id} has no hard Expect on any turn")
        return self


class EvalTurnResult(BaseModel):
    prompt: str
    finished: bool
    latency_ms: int
    modalities: list[str]
    contents: list[dict]
    actions: list[dict]
    hard: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)
    review: list[str] = Field(default_factory=list)
    error: str | None = None


class EvalCaseResult(BaseModel):
    case_id: str
    tags: set[str]
    status: CaseStatus
    known_red: KnownRed | None = None
    latency_ms: int
    failures: list[str]
    soft: list[str] = Field(default_factory=list)
    turns: list[EvalTurnResult]


class EvalRunResult(BaseModel):
    run_id: str
    duration_ms: int
    counts: dict[CaseStatus, int]
    results: list[EvalCaseResult]
