"""Subjects the onboarding Flow offers after a grade is chosen.

Oracle is the NCERT split a student would recognise (class 8 has Science, not
Accountancy; 11–12 the reverse), not a reconstruction of
`subjects_for_grade`. Slugs and titles in the checkbox options are handwritten
so `subject.value` / `subject.title` cannot agree with themselves.

Forbidden: `assert subjects_for_grade(8) == tuple(s for s in Subject if 8 in s.grades)`.
"""

from __future__ import annotations

import pytest

from infra.curriculum import (
    Subject,
    subject_options,
    subjects_for_grade,
    subjects_for_grades,
)

pytestmark = pytest.mark.boundary


def _ids(grade: int) -> set[str]:
    return {subject.value for subject in subjects_for_grade(grade)}


# --------------------------------------------------------------------------
# what a student of that class is offered
# --------------------------------------------------------------------------


def test_class_8_is_offered_science_not_accountancy():
    ids = _ids(8)

    assert "science" in ids
    assert "social-science" in ids
    assert "accountancy" not in ids
    assert "physics" not in ids
    assert "the-world-around-us" not in ids


def test_class_11_is_offered_accountancy_not_science():
    ids = _ids(11)

    assert "accountancy" in ids
    assert "physics" in ids
    assert "science" not in ids
    assert "social-science" not in ids


def test_class_3_is_offered_the_world_around_us_not_science():
    ids = _ids(3)

    assert "the-world-around-us" in ids
    assert "science" not in ids
    assert "accountancy" not in ids


def test_knowledge_traditions_is_class_11_only():
    """A teacher who only declared 12 must not see an 11-only checkbox."""
    assert "knowledge-traditions-practices-of-india" in _ids(11)
    assert "knowledge-traditions-practices-of-india" not in _ids(12)


# --------------------------------------------------------------------------
# a teacher who declared several grades
# --------------------------------------------------------------------------


def test_union_of_8_and_11_offers_both_science_and_accountancy():
    ids = {subject.value for subject in subjects_for_grades((8, 11))}

    assert "science" in ids
    assert "accountancy" in ids


def test_repeating_a_grade_does_not_duplicate_a_checkbox():
    """The Flow would show Science twice if the union concatenated blindly."""
    ids = [subject.value for subject in subjects_for_grades((8, 8))]

    assert ids.count("science") == 1
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# checkbox labels the Flow actually renders
# --------------------------------------------------------------------------


def test_a_science_checkbox_uses_the_slug_as_id_and_the_display_title():
    options = subject_options(subjects_for_grade(8))
    science = next(row for row in options if row["id"] == "science")

    assert science == {"id": "science", "title": "Science"}


def test_option_order_follows_the_subjects_it_was_given():
    """The picker must not sort or drop a subject the catalog already chose.

    Science-then-Accountancy is the anti-alphabetical pair: sorting by slug
    would swap them, so the assertion cannot agree with a sorted copy.
    """
    options = subject_options((Subject.SCIENCE, Subject.ACCOUNTANCY))

    assert [row["id"] for row in options] == ["science", "accountancy"]
    assert [row["title"] for row in options] == ["Science", "Accountancy"]
