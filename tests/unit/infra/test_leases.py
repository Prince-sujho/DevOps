"""When a named lease still blocks another holder.

knowledge_store takes GRAPH_LEASE / SESSIONS_LEASE through LeasesRepository.
The Firestore I/O stays in integration; this file pins the rule the ticker
uses: another holder blocks only while the expiry instant has not arrived.
Same-token renewals (the heartbeat) must never look like a foreign holder.

Forbidden: constructing a fake Firestore and replaying `_claim`.
"""

from __future__ import annotations

import pytest

from infra.firestore.types import Lease

pytestmark = pytest.mark.boundary

TOKEN = "token-a"
OTHER = "token-b"
HOLDER = "ingest entry-1"
EXPIRY = 1_700_000_000_000


def _lease(*, token: str = TOKEN) -> Lease:
    return Lease(token=token, holder=HOLDER, expiresAtMs=EXPIRY)


def test_another_holder_is_blocked_while_the_lease_is_still_live():
    assert _lease().blocks(OTHER, EXPIRY - 1) is True


def test_the_expiry_instant_frees_the_name_for_the_next_holder():
    """`now_ms < expiresAtMs`: silence at the expiry tick is already free."""
    assert _lease().blocks(OTHER, EXPIRY) is False


def test_a_heartbeat_with_the_same_token_is_not_a_foreign_holder():
    assert _lease().blocks(TOKEN, EXPIRY - 1) is False
