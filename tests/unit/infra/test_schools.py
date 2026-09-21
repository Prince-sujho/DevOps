"""The school directory the onboarding Flow searches.

There is no schools README. Oracles are: user_service README (`institution.id`
is set only for a directory school — lookup must return that campus, not invent
one); the `School` field meanings (subtitle is locality/city/state; address is
search fuel, not shown); and the dataset row for a unique campus, pinned by id
so a ranking formula cannot agree with itself.

Forbidden: re-scoring with rapidfuzz / heapq and comparing to `search_schools`.
"""

from __future__ import annotations

import pytest

from infra.schools import School, get_school, search_schools

pytestmark = pytest.mark.boundary

# Unique in schools.json (one row). Typing this name must surface this campus.
AMBAH_ID = "1000105"
AMBAH_NAME = "Kendriya Vidyalaya Ambah"

# A different unique campus, used only so "first" is a rank, not membership.
VILLAGE_ID = "1031219"
VILLAGE_NAME = "The Village Elementary Public School"

# Unique campus whose registered name uses dotted initials (P.D.).
PD_JAIN_ID = "1130370"
PD_JAIN_NAME = "P.D. Jain Public School"


# --------------------------------------------------------------------------
# lookup: the id stored on the profile is this campus
# --------------------------------------------------------------------------


def test_a_directory_id_opens_that_campus_not_another():
    school = get_school(AMBAH_ID)

    assert school.id == AMBAH_ID
    assert school.name == AMBAH_NAME
    assert school.id != VILLAGE_ID


def test_an_unknown_id_does_not_invent_a_campus():
    with pytest.raises(KeyError):
        get_school("not-a-directory-id")


# --------------------------------------------------------------------------
# search: what the user is shown
# --------------------------------------------------------------------------


def test_typing_a_unique_full_name_ranks_that_campus_first():
    """Membership alone is not enough — a worse-first ranking would still
    include Ambah somewhere in 31k rows.
    """
    hits = search_schools(AMBAH_NAME, limit=5)

    assert hits[0].id == AMBAH_ID
    assert hits[0].name == AMBAH_NAME
    assert hits[0].id != VILLAGE_ID


def test_typing_another_campus_name_does_not_rank_ambah_first():
    hits = search_schools(VILLAGE_NAME, limit=5)

    assert hits[0].id == VILLAGE_ID
    assert hits[0].id != AMBAH_ID


def test_search_does_not_return_more_rows_than_asked():
    hits = search_schools(AMBAH_NAME, limit=3)

    assert len(hits) <= 3
    assert any(row.id == AMBAH_ID for row in hits)


def test_spaced_initials_still_rank_the_dotted_campus_first():
    """Documented folding: ``P.D.``, ``P D``, and ``PD`` share one token.
    Rapidfuzz already ignores case, so a SHOUTY Ambah query would not prove
    this — the initials merge is the part only our normalizer does.
    """
    hits = search_schools("P D Jain Public School", limit=5)

    assert hits[0].id == PD_JAIN_ID
    assert hits[0].name == PD_JAIN_NAME


# --------------------------------------------------------------------------
# subtitle on the Flow card
# --------------------------------------------------------------------------


def test_place_joins_locality_city_state_and_skips_blanks():
    school = School(
        id="x",
        name="N",
        locality="Pachpeda",
        city="Porsa",
        state="Madhya Pradesh",
        address="must-not-appear-in-the-subtitle",
    )

    assert school.place == "Pachpeda, Porsa, Madhya Pradesh"
    assert "must-not-appear" not in school.place


def test_place_does_not_keep_an_empty_locality_slot():
    """Ambah's dataset row has no locality; the subtitle must not start with a comma."""
    school = get_school(AMBAH_ID)

    assert school.place == "Ambah, Madhya Pradesh"
    assert not school.place.startswith(",")
    assert school.address not in school.place
