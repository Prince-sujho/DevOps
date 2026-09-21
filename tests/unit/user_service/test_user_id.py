"""Deterministic user-id derivation from phone.

Oracle: user_service README — ``userId`` is HMAC of the WhatsApp phone digits
Meta sends, used verbatim. Access resolution and user creation are the only
places a phone becomes an identity. Different spellings are different ids.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, strategies as st

from infra.firestore.repos.users import _derive_user_id

from .factories import HMAC_SECRET

CANONICAL = "919876543210"


@pytest.mark.boundary
def test_same_phone_yields_the_same_user_id_across_calls() -> None:
    first = _derive_user_id(CANONICAL, HMAC_SECRET)
    second = _derive_user_id(CANONICAL, HMAC_SECRET)
    assert first == second
    assert first == _derive_user_id("919876543210", HMAC_SECRET)


@pytest.mark.boundary
def test_plus_91_is_a_different_identity_from_digits() -> None:
    """README: digits are used verbatim. +91 is not the WhatsApp form."""
    assert _derive_user_id("+919876543210", HMAC_SECRET) != _derive_user_id(
        CANONICAL, HMAC_SECRET
    )


@pytest.mark.boundary
def test_spaces_in_the_phone_are_a_different_identity() -> None:
    assert _derive_user_id("91 98765 43210", HMAC_SECRET) != _derive_user_id(
        CANONICAL, HMAC_SECRET
    )
    assert _derive_user_id("  919876543210  ", HMAC_SECRET) != _derive_user_id(
        CANONICAL, HMAC_SECRET
    )


@pytest.mark.boundary
def test_leading_zero_is_a_different_identity() -> None:
    assert _derive_user_id("0919876543210", HMAC_SECRET) != _derive_user_id(
        CANONICAL, HMAC_SECRET
    )


@pytest.mark.boundary
def test_two_different_phones_never_share_an_id() -> None:
    left = _derive_user_id("919876543210", HMAC_SECRET)
    right = _derive_user_id("919876543211", HMAC_SECRET)
    assert left != right


@pytest.mark.boundary
def test_different_hmac_secrets_do_not_alias_the_same_phone() -> None:
    """Keep USERS_USER_ID_HMAC_SECRET stable: a rotated secret is a new identity space."""
    assert _derive_user_id(CANONICAL, HMAC_SECRET) != _derive_user_id(
        CANONICAL, "a-different-hmac-secret"
    )


@pytest.mark.property
@given(phone=st.from_regex(r"91[6-9][0-9]{9}", fullmatch=True))
def test_derivation_is_deterministic_for_any_indian_mobile(phone: str) -> None:
    assert _derive_user_id(phone, HMAC_SECRET) == _derive_user_id(phone, HMAC_SECRET)


@pytest.mark.property
@given(
    a=st.from_regex(r"91[6-9][0-9]{9}", fullmatch=True),
    b=st.from_regex(r"91[6-9][0-9]{9}", fullmatch=True),
)
def test_distinct_canonical_phones_do_not_collide(a: str, b: str) -> None:
    assume(a != b)
    assert _derive_user_id(a, HMAC_SECRET) != _derive_user_id(b, HMAC_SECRET)
