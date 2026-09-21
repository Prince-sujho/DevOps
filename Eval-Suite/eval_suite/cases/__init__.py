"""Load and select the 60-session corpus."""

from __future__ import annotations

from ..types import EvalCase
from .helpers import assert_corpus
from .student import student_cases
from .teacher import teacher_cases

CORPUS_SESSION_IDS = frozenset(
    {
        "1785593650139",
        "1783657065554",
        "1783789725973",
        "1783014261776",
        "1784218187004",
        "1787568750260",
        "1787668397004",
        "1786108159857",
        "1785863880959",
        "1787592774210",
        "1786551435759",
        "1785942242086",
        "1783940069205",
        "1784555429493",
        "1787413552486",
        "1786468115049",
        "1786434553505",
        "1785688402524",
        "1785686149630",
        "1783217988780",
        "1783270123681",
        "1787201141188",
        "1787992075724",
        "1785569040649",
        "1785852319617",
        "1783242578407",
        "1785504858915",
        "1784479803290",
        "1785998727196",
        "1787727327185",
        "1785946828898",
        "1786025085843",
        "1788103187414",
        "1784133912592",
        "1787795234171",
        "1786095341821",
        "1783039688990",
        "1783134415646",
        "1786112487762",
        "1786794988088",
        "1786024210811",
        "1786354044838",
        "1787927995243",
        "1786375965083",
        "1786231452994",
        "1785252541585",
        "1787546900223",
        "1784034546600",
        "1786194153604",
        "1787915736037",
        "1785658520202",
        "1787580564002",
        "1786473374711",
        "1786760793600",
        "1786429633303",
        "1783567284894",
        "1786162948947",
        "1787842025650",
        "1787795270978",
        "1786805803670",
    }
)


def session_id(case_id: str) -> str:
    persona, _, rest = case_id.partition("-")
    if persona not in {"student", "teacher"} or not rest:
        raise ValueError(f"case id is not persona-session: {case_id}")
    return rest


def all_cases() -> list[EvalCase]:
    cases = assert_corpus([*student_cases(), *teacher_cases()])
    found = {session_id(item.id) for item in cases}
    missing = sorted(CORPUS_SESSION_IDS - found)
    extra = sorted(found - CORPUS_SESSION_IDS)
    if missing or extra:
        raise ValueError(f"corpus mismatch missing={missing} extra={extra}")
    if len(cases) != 60:
        raise ValueError(f"expected 60 cases, got {len(cases)}")
    return cases


def select_cases(ids: list[str], tags: set[str]) -> list[EvalCase]:
    cases = all_cases()
    if ids:
        by_id = {item.id: item for item in cases}
        missing = [case_id for case_id in ids if case_id not in by_id]
        if missing:
            raise ValueError(f"unknown case id: {missing}")
        cases = [by_id[case_id] for case_id in ids]
    if tags:
        cases = [item for item in cases if tags <= item.tags]
    if not cases:
        raise ValueError("no cases selected")
    return cases
