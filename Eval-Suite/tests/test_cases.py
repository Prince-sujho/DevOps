"""Corpus coverage: 60 sessions, unique ids, all_cases() builds."""

from __future__ import annotations

from eval_suite.cases import (
    CORPUS_SESSION_IDS,
    all_cases,
    select_cases,
    session_id,
)
from eval_suite.constants import REQUIRED_TAGS


def test_all_cases_build() -> None:
    """The corpus builds to exactly 60 cases with unique ids.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    cases = all_cases()
    assert len(cases) == 60
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))


def test_every_gold_session_is_present() -> None:
    """Every gold session id from CORPUS_SESSION_IDS appears exactly once.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    found = {session_id(case.id) for case in all_cases()}
    assert found == CORPUS_SESSION_IDS
    assert len(CORPUS_SESSION_IDS) == 60


def test_every_case_has_a_hard_bar() -> None:
    """Every case (unless profile_unchanged) has a hard Expect on some turn.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    for case in all_cases():
        if case.profile_unchanged:
            continue
        assert any(turn.expect.hard_armed() for turn in case.turns), case.id


def test_select_cases_by_id_and_unknown_id() -> None:
    """select_cases finds a known id and raises on an unknown one.

    Args:
        None.
    Returns:
        None.
    Raises:
        AssertionError: an unknown case id did not raise ValueError.
    """
    selected = select_cases(["student-1783940069205"], set())
    assert [case.id for case in selected] == ["student-1783940069205"]
    try:
        select_cases(["does_not_exist"], set())
    except ValueError as error:
        assert "does_not_exist" in str(error)
    else:
        raise AssertionError("unknown case id must raise")


def test_required_tags_are_covered() -> None:
    """Every tag REQUIRED_TAGS demands is used by at least one case.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    tags = {tag for case in all_cases() for tag in case.tags}
    for required in REQUIRED_TAGS.values():
        for tag in required:
            assert tag in tags, f"missing required tag {tag!r}"


def test_delivery_cases_require_a_live_file() -> None:
    """Every case tagged delivery has a turn expecting a live attachment.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    delivery = [case for case in all_cases() if "delivery" in case.tags]
    assert delivery
    for case in delivery:
        live = [
            turn
            for turn in case.turns
            if turn.expect.attachments and turn.expect.attachments.live
        ]
        assert live, case.id


def test_named_defects_use_hard_text() -> None:
    """Named-defect cases assert hard_text_matches/forbidden, not the soft form.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    by_id = {case.id: case for case in all_cases()}
    volume = by_id["student-1783940069205"].turns[-1].expect
    assert volume.hard_text_matches and volume.hard_text_forbidden
    assert not volume.text_matches
    current = next(
        turn.expect
        for turn in by_id["student-1783014261776"].turns
        if turn.prompt == "50"
    )
    assert current.hard_text_matches and current.hard_text_forbidden
    assert not current.text_matches
    cropped = by_id["teacher-1786194153604"].turns[-1].expect
    assert cropped.hard_text_forbidden
    assert not cropped.text_forbidden
