"""Pure directory matching, activity-state, and sort keys.

Oracle: user_service README (directory is derived; empty filter lists are
unconstrained — from ``UserDirectoryQuery``), ``ACTIVE_USER_WINDOW_MS``
(a user is active when their last message is within this window),
``_activity_state`` / ``_matches`` / ``_sort_key`` docstrings, and the task
brief (AND across search tokens; casefold unicode; None lastMessageAtMs
sorts after real timestamps).
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from infra.clients.users import ChannelActivity
from infra.curriculum import Subject
from user_service.app.src.directory import (
    _activity_state,
    _matches,
    _sort_key,
    derive_directory_page,
    directory_entry as classify_directory_entry,
)

from .factories import (
    ACTIVE_USER_WINDOW_MS,
    directory_entry,
    directory_query,
    student,
)
from .fakes import FakeBlocklist, FakeUsers

NOW_MS = 1_800_000_000_000


def _matches_entry(entry, **query_kw) -> bool:
    """Apply the same needle construction the directory page uses: strip + casefold."""
    query = directory_query(**query_kw)
    needle = query.q.strip().casefold()
    return _matches(entry, query, needle)


# ---------------------------------------------------------------------------
# _activity_state
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_activity_state_none_last_message_is_never() -> None:
    activity = ChannelActivity(sessionCount=0, lastMessageAtMs=None)
    assert _activity_state(activity, NOW_MS) == "never"


@pytest.mark.boundary
def test_activity_state_exactly_on_the_window_boundary_is_active() -> None:
    """'Within this window' includes the far edge: age == ACTIVE_USER_WINDOW_MS."""
    activity = ChannelActivity(
        sessionCount=1, lastMessageAtMs=NOW_MS - ACTIVE_USER_WINDOW_MS
    )
    assert _activity_state(activity, NOW_MS) == "active"


@pytest.mark.boundary
def test_activity_state_one_ms_inside_the_window_is_active() -> None:
    activity = ChannelActivity(
        sessionCount=1, lastMessageAtMs=NOW_MS - ACTIVE_USER_WINDOW_MS + 1
    )
    assert _activity_state(activity, NOW_MS) == "active"


@pytest.mark.boundary
def test_activity_state_one_ms_outside_the_window_is_dormant() -> None:
    activity = ChannelActivity(
        sessionCount=1, lastMessageAtMs=NOW_MS - ACTIVE_USER_WINDOW_MS - 1
    )
    assert _activity_state(activity, NOW_MS) == "dormant"


@pytest.mark.boundary
def test_activity_state_message_at_now_is_active() -> None:
    activity = ChannelActivity(sessionCount=1, lastMessageAtMs=NOW_MS)
    assert _activity_state(activity, NOW_MS) == "active"


@pytest.mark.property
@given(age=st.integers(min_value=0, max_value=ACTIVE_USER_WINDOW_MS))
def test_any_age_inside_the_closed_window_is_active(age: int) -> None:
    activity = ChannelActivity(sessionCount=1, lastMessageAtMs=NOW_MS - age)
    assert _activity_state(activity, NOW_MS) == "active"


@pytest.mark.property
@given(over=st.integers(min_value=1, max_value=ACTIVE_USER_WINDOW_MS))
def test_any_age_past_the_window_is_dormant(over: int) -> None:
    activity = ChannelActivity(
        sessionCount=1, lastMessageAtMs=NOW_MS - ACTIVE_USER_WINDOW_MS - over
    )
    assert _activity_state(activity, NOW_MS) == "dormant"


# ---------------------------------------------------------------------------
# _matches — search
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_matches_empty_query_matches_everything() -> None:
    entry = directory_entry(student(name="Ada Lovelace"), activity_state="never")
    assert _matches_entry(entry, q="") is True
    assert _matches_entry(entry, q="   ") is True


@pytest.mark.boundary
def test_matches_multi_token_requires_every_token() -> None:
    """'Amit Roy' must not match 'Amit Kumar' — AND across tokens."""
    amit = directory_entry(student(name="Amit Kumar"), activity_state="never")
    bina = directory_entry(
        student(name="Bina Roy", user_id="user-bina"), activity_state="never"
    )
    assert _matches_entry(amit, q="Amit Roy") is False
    assert _matches_entry(bina, q="Amit Roy") is False
    assert _matches_entry(amit, q="Amit Kumar") is True


@pytest.mark.boundary
def test_matches_unicode_name_under_casefold() -> None:
    entry = directory_entry(student(name="José García"), activity_state="never")
    assert _matches_entry(entry, q="JOSÉ") is True
    assert _matches_entry(entry, q="josé") is True
    assert _matches_entry(entry, q="José") is True


@pytest.mark.boundary
def test_matches_unknown_token_rejects() -> None:
    entry = directory_entry(student(name="Ada Lovelace"), activity_state="never")
    assert _matches_entry(entry, q="zzz-no-match") is False


# ---------------------------------------------------------------------------
# _matches — filters in isolation and combined
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_matches_grade_filter_in_isolation() -> None:
    grade_eight = directory_entry(student(grade=8), activity_state="never")
    grade_nine = directory_entry(
        student(grade=9, user_id="u9", name="Nine"), activity_state="never"
    )
    assert _matches_entry(grade_eight, grade=[8]) is True
    assert _matches_entry(grade_nine, grade=[8]) is False
    assert _matches_entry(grade_eight, grade=[8, 9]) is True
    assert _matches_entry(grade_eight, grade=[]) is True


@pytest.mark.boundary
def test_matches_subject_filter_in_isolation() -> None:
    math = directory_entry(
        student(subjects=[Subject.MATHEMATICS]), activity_state="never"
    )
    science = directory_entry(
        student(
            user_id="sci",
            name="Sci",
            subjects=[Subject.SCIENCE],
        ),
        activity_state="never",
    )
    assert _matches_entry(math, subject=[Subject.MATHEMATICS]) is True
    assert _matches_entry(science, subject=[Subject.MATHEMATICS]) is False
    assert _matches_entry(math, subject=[]) is True


@pytest.mark.boundary
def test_matches_activity_filter_in_isolation() -> None:
    active = directory_entry(student(), activity_state="active")
    dormant = directory_entry(
        student(user_id="d", name="Dorm"), activity_state="dormant"
    )
    never = directory_entry(student(user_id="n", name="Never"), activity_state="never")
    assert _matches_entry(active, activity=["active"]) is True
    assert _matches_entry(dormant, activity=["active"]) is False
    assert _matches_entry(never, activity=["never"]) is True
    assert _matches_entry(active, activity=[]) is True


@pytest.mark.boundary
def test_matches_attribution_filter_in_isolation() -> None:
    """Organic is absent attribution; a referrer handle maps to AttributionState 'referrer'."""
    organic = directory_entry(student(referrer_handle=None), activity_state="never")
    attributed = directory_entry(
        student(user_id="a", name="Attr", referrer_handle="alice"),
        activity_state="never",
    )
    assert _matches_entry(organic, attribution=["organic"]) is True
    assert _matches_entry(attributed, attribution=["organic"]) is False
    assert _matches_entry(attributed, attribution=["referrer"]) is True
    assert _matches_entry(organic, attribution=["referrer"]) is False
    assert _matches_entry(organic, attribution=[]) is True


@pytest.mark.boundary
def test_matches_blocked_filter_in_isolation() -> None:
    open_user = directory_entry(student(), activity_state="never", blocked=False)
    blocked_user = directory_entry(
        student(user_id="b", name="Blocked"), activity_state="never", blocked=True
    )
    assert _matches_entry(open_user, blocked=["open"]) is True
    assert _matches_entry(blocked_user, blocked=["open"]) is False
    assert _matches_entry(blocked_user, blocked=["blocked"]) is True
    assert _matches_entry(open_user, blocked=["blocked"]) is False


@pytest.mark.boundary
def test_matches_all_filters_combined() -> None:
    """Only the profile that satisfies grade AND subject AND activity AND
    attribution AND block-state simultaneously matches.
    """
    target = directory_entry(
        student(
            user_id="target",
            name="Target User",
            grade=8,
            subjects=[Subject.MATHEMATICS],
            referrer_handle="alice",
        ),
        activity_state="active",
        blocked=False,
    )
    wrong_grade = directory_entry(
        student(
            user_id="wg",
            name="Target User",
            grade=9,
            subjects=[Subject.MATHEMATICS],
            referrer_handle="alice",
        ),
        activity_state="active",
        blocked=False,
    )
    kwargs = dict(
        q="Target",
        grade=[8],
        subject=[Subject.MATHEMATICS],
        activity=["active"],
        attribution=["referrer"],
        blocked=["open"],
    )
    assert _matches_entry(target, **kwargs) is True
    assert _matches_entry(wrong_grade, **kwargs) is False


@pytest.mark.property
@given(q=st.sampled_from(["", "   ", "\t"]))
def test_blank_queries_match_any_name(q: str) -> None:
    entry = directory_entry(student(name="Zara Ahmed"), activity_state="dormant")
    assert _matches_entry(entry, q=q) is True


# ---------------------------------------------------------------------------
# _sort_key
# ---------------------------------------------------------------------------


@pytest.mark.boundary
def test_sort_key_name_orders_alphabetically_by_casefold() -> None:
    ada = directory_entry(student(name="Ada", user_id="u-ada"))
    bob = directory_entry(student(name="Bob", user_id="u-bob"))
    ordered = sorted([bob, ada], key=lambda e: _sort_key(e, "name"))
    assert [e.profile.name for e in ordered] == ["Ada", "Bob"]


@pytest.mark.boundary
def test_sort_key_identical_names_are_a_stable_tie() -> None:
    """Docstring: always tiebroken by cased name. Two identical names therefore
    compare equal, and Python's stable sort preserves input order.
    """
    left = directory_entry(student(name="Ada Lovelace", user_id="u-1", phone="919811111111"))
    right = directory_entry(
        student(name="Ada Lovelace", user_id="u-2", phone="919811111112")
    )
    assert _sort_key(left, "name") == _sort_key(right, "name")
    preserved = sorted([left, right], key=lambda e: _sort_key(e, "name"))
    assert [e.profile.userId for e in preserved] == ["u-1", "u-2"]
    swapped = sorted([right, left], key=lambda e: _sort_key(e, "name"))
    assert [e.profile.userId for e in swapped] == ["u-2", "u-1"]


@pytest.mark.boundary
def test_sort_key_last_active_puts_none_after_every_real_timestamp() -> None:
    """The README never states most-recent-first as the "last active" sort
    direction; the docstring only says None sorts after every real
    timestamp. Reviewed per tests/outcomes/UNCERTAINTY.md's "guesses that
    stayed green" list and kept intentionally: most-recent-first is the
    only "last active" ordering that is coherent for an admin roster (the
    inverse would surface the least-recently-active users first, which is
    not what "sort by last active" means in ordinary usage), so this is not
    treated as an arbitrary tie between two equally-defensible readings.
    """
    recent = directory_entry(
        student(name="Recent", user_id="recent"),
        last_message_at_ms=NOW_MS,
        activity_state="active",
    )
    older = directory_entry(
        student(name="Older", user_id="older"),
        last_message_at_ms=NOW_MS - 1_000,
        activity_state="active",
    )
    never = directory_entry(
        student(name="Never", user_id="never"),
        last_message_at_ms=None,
        activity_state="never",
    )
    ordered = sorted(
        [never, older, recent], key=lambda e: _sort_key(e, "last_active")
    )
    assert [e.profile.userId for e in ordered] == ["recent", "older", "never"]


@pytest.mark.property
@given(
    ts=st.integers(min_value=1, max_value=NOW_MS),
    name=st.text(min_size=1, max_size=12, alphabet="abcdefghijklmnopqrstuvwxyz"),
)
def test_none_last_message_sorts_after_any_real_timestamp_on_last_active(
    ts: int, name: str
) -> None:
    stamped = directory_entry(
        student(name=name, user_id="stamped"), last_message_at_ms=ts
    )
    blank = directory_entry(
        student(name=name, user_id="blank", phone="919822222222"),
        last_message_at_ms=None,
    )
    ordered = sorted([blank, stamped], key=lambda e: _sort_key(e, "last_active"))
    assert [e.profile.userId for e in ordered] == ["stamped", "blank"]


@pytest.mark.boundary
def test_sort_key_newest_puts_later_created_first() -> None:
    older = directory_entry(
        student(name="Zara", user_id="older", created_at_ms=100)
    )
    newer = directory_entry(
        student(name="Ada", user_id="newer", phone="919811111112", created_at_ms=200)
    )
    ordered = sorted([older, newer], key=lambda e: _sort_key(e, "newest"))
    assert [e.profile.userId for e in ordered] == ["newer", "older"]


@pytest.mark.boundary
def test_sort_key_session_count_puts_higher_count_first() -> None:
    quiet = directory_entry(
        student(name="Ada", user_id="quiet"), session_count=1
    )
    busy = directory_entry(
        student(name="Zara", user_id="busy", phone="919811111112"), session_count=9
    )
    ordered = sorted([quiet, busy], key=lambda e: _sort_key(e, "session_count"))
    assert [e.profile.userId for e in ordered] == ["busy", "quiet"]


@pytest.mark.boundary
def test_directory_entry_uses_whatsapp_activity_and_clock_for_state() -> None:
    profile = student(last_message_at_ms=NOW_MS, session_count=3)
    entry = classify_directory_entry(profile, blocked=True, at_ms=NOW_MS)
    assert entry.activityState == "active"
    assert entry.blocked is True
    assert entry.activity.sessionCount == 3
    assert entry.activity.lastMessageAtMs == NOW_MS


@pytest.mark.boundary
def test_directory_entry_outside_the_window_is_dormant() -> None:
    profile = student(last_message_at_ms=NOW_MS - ACTIVE_USER_WINDOW_MS - 1)
    entry = classify_directory_entry(profile, blocked=False, at_ms=NOW_MS)
    assert entry.activityState == "dormant"
    assert entry.blocked is False


@pytest.mark.boundary
def test_directory_entry_never_messaged_is_never() -> None:
    profile = student(last_message_at_ms=None)
    entry = classify_directory_entry(profile, blocked=False, at_ms=NOW_MS)
    assert entry.activityState == "never"


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_directory_page_blocked_filter_returns_only_blocked_identities(
    monkeypatch,
) -> None:
    """``userId in blocked_ids`` — inverting membership would swap open/blocked."""
    monkeypatch.setattr("user_service.app.src.directory.now_ms", lambda: NOW_MS)
    ada = student(user_id="ada", name="Ada", last_message_at_ms=NOW_MS)
    bob = student(
        user_id="bob",
        name="Bob",
        phone="919811111112",
        last_message_at_ms=NOW_MS,
    )
    users = FakeUsers()
    users.add(ada)
    users.add(bob)
    page = await derive_directory_page(
        users,
        FakeBlocklist({"bob"}),
        directory_query(blocked=["blocked"]),
    )
    assert page.totalCount == 1
    assert page.entries[0].profile.userId == "bob"
    assert page.entries[0].blocked is True
    assert users.by_persona_calls == ["student"]


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_directory_page_open_filter_excludes_blocked_identities(monkeypatch) -> None:
    monkeypatch.setattr("user_service.app.src.directory.now_ms", lambda: NOW_MS)
    ada = student(user_id="ada", name="Ada", last_message_at_ms=NOW_MS)
    bob = student(
        user_id="bob",
        name="Bob",
        phone="919811111112",
        last_message_at_ms=NOW_MS,
    )
    users = FakeUsers()
    users.add(ada)
    users.add(bob)
    page = await derive_directory_page(
        users, FakeBlocklist({"bob"}), directory_query(blocked=["open"])
    )
    assert page.totalCount == 1
    assert page.entries[0].profile.userId == "ada"
    assert page.entries[0].blocked is False


@pytest.mark.boundary
@pytest.mark.asyncio
async def test_directory_page_newest_sort_and_activity_use_the_clock(monkeypatch) -> None:
    monkeypatch.setattr("user_service.app.src.directory.now_ms", lambda: NOW_MS)
    older = student(
        user_id="older",
        name="Zara",
        created_at_ms=100,
        last_message_at_ms=NOW_MS,
    )
    newer = student(
        user_id="newer",
        name="Ada",
        phone="919811111112",
        created_at_ms=200,
        last_message_at_ms=NOW_MS,
    )
    users = FakeUsers()
    users.add(older)
    users.add(newer)
    page = await derive_directory_page(
        users, FakeBlocklist(), directory_query(sort="newest")
    )
    assert [e.profile.userId for e in page.entries] == ["newer", "older"]
    assert page.entries[0].activityState == "active"
    assert page.totalCount == 2
