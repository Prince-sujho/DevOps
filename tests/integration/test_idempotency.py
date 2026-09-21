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
    """Real MessageClaimsRepository bound to the emulator client for this test."""
    return MessageClaimsRepository(db)


async def test_concurrent_claims_of_the_same_id_exactly_one_wins(claims):
    message_id = "wamid.concurrent.same"
    results = await asyncio.gather(*[claims.claim(message_id) for _ in range(8)])
    assert results.count(True) == 1
    assert results.count(False) == 7


async def test_sequential_claim_of_the_same_id_succeeds_once(claims):
    message_id = "wamid.sequential.same"
    first = await claims.claim(message_id)
    second = await claims.claim(message_id)
    assert first is True
    assert second is False


async def test_distinct_message_ids_each_succeed_once(claims):
    first = await claims.claim("wamid.distinct.a")
    second = await claims.claim("wamid.distinct.b")
    assert first is True
    assert second is True
    replay = await claims.claim("wamid.distinct.a")
    assert replay is False
