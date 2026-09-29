"""MessageClaimsRepository.claim succeeds exactly once per Meta message id.

whatsapp_adapter owns ``message_claims``; the repository is the persistence
boundary the adapter uses for webhook idempotency. Concurrent claims of the
same id: exactly one wins. Firestore emulator, no mocks.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from infra.firestore.repos.message_claims import MessageClaimsRepository

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def claims(db):
    """Real MessageClaimsRepository bound to the emulator client for this test.

    Args:
        db: the emulator-bound Firestore client.
    Returns:
        A MessageClaimsRepository bound to db.
    Raises:
        None.
    """
    return MessageClaimsRepository(db)


async def test_concurrent_claims_of_the_same_id_exactly_one_wins(claims):
    """8 concurrent claims of one message id: exactly one wins, the rest lose.

    Args:
        claims: the MessageClaimsRepository under test.
    Returns:
        None.
    Raises:
        None.
    """
    message_id = "wamid.concurrent.same"
    results = await asyncio.gather(
        *[claims.claim(message_id) for _ in range(8)]
    )
    assert results.count(True) == 1
    assert results.count(False) == 7


async def test_sequential_claim_of_the_same_id_succeeds_once(claims):
    """Claiming the same message id twice in a row: the second claim loses.

    Args:
        claims: the real MessageClaimsRepository under test.
    Returns:
        None.
    Raises:
        None.
    """
    message_id = "wamid.sequential.same"
    first = await claims.claim(message_id)
    second = await claims.claim(message_id)
    assert first is True
    assert second is False


async def test_distinct_message_ids_each_succeed_once(claims):
    """Different message ids each get their own successful first claim.

    Args:
        claims: the real MessageClaimsRepository under test.
    Returns:
        None.
    Raises:
        None.
    """
    first = await claims.claim("wamid.distinct.a")
    second = await claims.claim("wamid.distinct.b")
    assert first is True
    assert second is True
    replay = await claims.claim("wamid.distinct.a")
    assert replay is False
