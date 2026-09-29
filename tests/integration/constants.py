"""Throwaway wiring constants for the persistence integration suite.

Nothing here is a production secret. Collection names are transcribed from
``infra.firestore.collections`` (the map the README points at). Hubble product
ids and the two-hour gap are transcribed from the frozen constants the README
names as the source of those values.
"""

from __future__ import annotations

from typing import Final

# Bound to the real named constants instead of a second hand-transcribed
# copy (see tests/outcomes/MIRRORED_AND_WRONG.md) -- a change to the ladder,
# the gap window, or the collection map is automatically visible here.
from infra.clients.users import SESSION_GAP_MS, WHATSAPP_THREAD_KEY
from infra.firestore.collections import (
    BLOCKLIST_COLLECTION,
    CAMPAIGNS_SUBCOLLECTION,
    CLICKS_SUBCOLLECTION,
    ENROLLMENTS_COLLECTION,
    GIFTING_SUBCOLLECTION,
    MESSAGE_CLAIMS_COLLECTION,
    ONBOARDING_COLLECTION,
    REFERRERS_COLLECTION,
    SESSION_TRANSCRIPT_SUBCOLLECTION,
    SESSIONS_SUBCOLLECTION,
    THREADS_SUBCOLLECTION,
    USERS_COLLECTION,
)
from user_service.app.src.constants import (
    AMBASSADOR_TIERS,
    RETENTION_WINDOW_MS,
    REWARD_PRODUCTS,
)

TEST_PROJECT: Final[str] = "sujho-integration-test"
TEST_LOCATION: Final[str] = "asia-south1"

USERS_SERVICE_SECRET: Final[str] = "test-users-service-secret"
USERS_USER_ID_HMAC_SECRET: Final[str] = "test-users-user-id-hmac-secret"
PUBLIC_ORIGIN: Final[str] = "https://sujho.test"
CONVERSATION_MEDIA_BUCKET: Final[str] = "sujho-integration-test-media"

AMAZON_PRODUCT_ID: Final[str] = "01GMAVS2CHXR0XP1BZSTA9A44K"
AMAZON_BRAND: Final[str] = REWARD_PRODUCTS[AMAZON_PRODUCT_ID]
ALL_REWARD_PRODUCT_IDS: Final[tuple[str, ...]] = tuple(REWARD_PRODUCTS)

TIER_ONE_POINTS: Final[int] = AMBASSADOR_TIERS[0].points
TIER_ONE_REWARD_INR: Final[int] = AMBASSADOR_TIERS[0].rewardInr
TIER_ONE_NAME: Final[str] = AMBASSADOR_TIERS[0].name

# Field names that the Stored-derivations rule forbids as stored counters.
# Session cursors and the activity tip are the legal stored derivations.
FORBIDDEN_STORED_COUNTERS: Final[frozenset[str]] = frozenset(
    {
        "points",
        "referralCount",
        "referrals",
        "studentsReferred",
        "teachersReferred",
        "started",
        "onboards",
        "clicks",
        "retained",
        "balance",
        "balanceInr",
        "earnedInr",
        "spendInr",
        "rewardBalance",
        "spentInr",
    }
)
