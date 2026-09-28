"""Deterministic user-id derivation from phone.

Oracle: user_service README — ``userId`` is HMAC of the WhatsApp phone digits
Meta sends, used verbatim. Two phones must never share an id, and the id
space belongs to one secret.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given, strategies as st

from infra.firestore.repos.users import _derive_user_id

from .factories import HMAC_SECRET

INDIAN_MOBILE = st.from_regex(r"91[6-9][0-9]{9}", fullmatch=True)


@pytest.mark.property
@given(phone=INDIAN_MOBILE)
def test_different_hmac_secrets_do_not_alias_the_same_phone(phone: str) -> None:
    """Keep USERS_USER_ID_HMAC_SECRET stable: a rotated secret is a new identity space."""
    assert _derive_user_id(phone, HMAC_SECRET) != _derive_user_id(phone, HMAC_SECRET + "-rotated")


@pytest.mark.property
@given(a=INDIAN_MOBILE, b=INDIAN_MOBILE)
def test_distinct_canonical_phones_do_not_collide(a: str, b: str) -> None:
    assume(a != b)
    assert _derive_user_id(a, HMAC_SECRET) != _derive_user_id(b, HMAC_SECRET)
