"""Fixed test-only wiring constants shared by the e2e harness.

Every value here is a throwaway literal used only against the local Firestore
emulator and in-process fakes. Nothing here touches a real system.
"""

from __future__ import annotations

from typing import Final

# The README calls the tier ladder and reward catalogue "a frozen commitment
# in code" but names no numbers itself -- import the real constants instead
# of re-transcribing a second, independently-maintained copy of the ladder
# (see tests/outcomes/MIRRORED_AND_WRONG.md).
from infra.clients.users import SESSION_GAP_MS
from user_service.app.src.constants import AMBASSADOR_TIERS, REWARD_PRODUCTS

# Canned user-facing copy and onboarding wiring ids/screens: bound to the
# real constants instead of a hand-transcribed second copy, so a copy or
# wiring-id change is automatically visible here instead of silently going
# stale (same rationale as the reward ladder above).
from infra.canned import CANNED_RESPONSES
from infra.constants import PRODUCT_NAME
from infra.conversation import SOURCES_LABEL
from infra.firestore.collections import (
    BLOCKLIST_COLLECTION,
    GIFTING_SUBCOLLECTION,
    MESSAGE_CLAIMS_COLLECTION,
    ONBOARDING_COLLECTION,
    REFERRERS_COLLECTION,
    SESSION_TRANSCRIPT_SUBCOLLECTION,
    SESSIONS_SUBCOLLECTION,
    THREADS_SUBCOLLECTION,
    USERS_COLLECTION,
)
from whatsapp_adapter.app.src.constants import ONBOARDING_FLOW_TOKEN
from whatsapp_adapter.app.src.flows.constants import (
    DOCUMENT_FORM_SCREEN,
    PERSONA_STUDENT_BUTTON_ID,
    PERSONA_TEACHER_BUTTON_ID,
    RESULTS_SCREEN,
)

TEST_PROJECT: Final[str] = "sujho-e2e-test"
TEST_LOCATION: Final[str] = "asia-south1"

# --- Service secrets (test-only) ---
WHATSAPP_APP_SECRET: Final[str] = "test-whatsapp-app-secret"
WHATSAPP_VERIFY_TOKEN: Final[str] = "test-whatsapp-verify-token"
TEXT_AGENT_SERVICE_SECRET: Final[str] = "test-text-agent-service-secret"
USERS_SERVICE_SECRET: Final[str] = "test-users-service-secret"
USERS_USER_ID_HMAC_SECRET: Final[str] = "test-users-user-id-hmac-secret"

# --- Distinct persona flow ids so persona resolution is observable ---
STUDENT_ONBOARDING_FLOW_ID: Final[str] = "flow-student-onboarding"
TEACHER_ONBOARDING_FLOW_ID: Final[str] = "flow-teacher-onboarding"
STUDENT_DOC_FLOW_ID: Final[str] = "flow-student-doc"
TEACHER_DOC_FLOW_ID: Final[str] = "flow-teacher-doc"
STUDENT_GRADE_FLOW_ID: Final[str] = "flow-student-grade"
TEACHER_GRADE_FLOW_ID: Final[str] = "flow-teacher-grade"

WHATSAPP_PHONE_NUMBER_ID: Final[str] = "111222333444"
WHATSAPP_API_VERSION: Final[str] = "v25.0"
WHATSAPP_ACCESS_TOKEN: Final[str] = "test-whatsapp-access-token"
PUBLIC_WHATSAPP_NUMBER: Final[str] = "919999900000"
PUBLIC_ORIGIN: Final[str] = "https://sujho.test"
CONVERSATION_MEDIA_BUCKET: Final[str] = "sujho-e2e-test-media"

# --- Literal user-facing copy: bound to the real infra.canned.CANNED_RESPONSES
# catalog, not a second hand-transcribed copy. PRODUCT_NAME comes from
# infra.constants (the same module infra/canned/constants.py itself uses to
# build intro). ---
_ONBOARDING_COPY = CANNED_RESPONSES.onboarding
CANNED_ERROR: Final[str] = CANNED_RESPONSES.error
CANNED_BLOCKED: Final[str] = CANNED_RESPONSES.blocked
PERSONA_QUESTION: Final[str] = _ONBOARDING_COPY.persona_question
PHONE_REQUEST: Final[str] = _ONBOARDING_COPY.phone_request
PHONE_ACK: Final[str] = _ONBOARDING_COPY.phone_ack
INTRO: Final[str] = _ONBOARDING_COPY.intro
STUDENT_LAUNCH_BODY: Final[str] = _ONBOARDING_COPY.launch_body["student"]
TEACHER_LAUNCH_BODY: Final[str] = _ONBOARDING_COPY.launch_body["teacher"]
ONBOARDING_FLOW_CTA: Final[str] = CANNED_RESPONSES.flow_cta["onboarding"]
DOCUMENT_FLOW_CTA: Final[str] = CANNED_RESPONSES.flow_cta["document"]
PERSONA_STUDENT_BUTTON_TITLE: Final[str] = (
    _ONBOARDING_COPY.persona_button_titles["student"]
)
PERSONA_TEACHER_BUTTON_TITLE: Final[str] = (
    _ONBOARDING_COPY.persona_button_titles["teacher"]
)

WHATSAPP_THREAD_KEY: Final[str] = "whatsapp"

# --- Hubble reward catalogue: bound to the real named constants, not a
# second hand-copied ladder (a code change here is now automatically visible
# rather than needing this file edited in lockstep). ---
AMAZON_PRODUCT_ID: Final[str] = "01GMAVS2CHXR0XP1BZSTA9A44K"
AMAZON_BRAND: Final[str] = REWARD_PRODUCTS[AMAZON_PRODUCT_ID]
ALL_REWARD_PRODUCT_IDS: Final[tuple[str, ...]] = tuple(REWARD_PRODUCTS)
# Tier 1 of the frozen ladder.
TIER_ONE_POINTS: Final[int] = AMBASSADOR_TIERS[0].points
TIER_ONE_REWARD_INR: Final[int] = AMBASSADOR_TIERS[0].rewardInr
TIER_ONE_NAME: Final[str] = AMBASSADOR_TIERS[0].name
