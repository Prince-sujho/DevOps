"""Shared fixtures and in-memory fakes for user_service API-level tests.

These tests drive the real FastAPI app (real routes, real Pydantic models,
real ``require_internal_secret`` auth dependency) through an ASGI transport.
Only the Firestore-backed repositories and the Hubble/Neo4j/GCS clients are
replaced with pure in-memory fakes, via a test ``lifespan`` that builds the
same ``AppState`` shape the real ``lifespan`` builds.

Fakes intentionally mirror the *plumbing* behavior of the real Firestore
repositories they replace (e.g. idempotent creates, no server-side uniqueness
checks) rather than inventing spec-compliant business rules the route layer
itself does not implement. Where the README promises behavior (e.g. 409 on
handle collision) that no layer of the real application actually enforces,
tests built against these faithful fakes will fail against the spec-derived
expectation -- that is a confirmed finding, not a fake-writing bug.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import pytest
import pytest_asyncio

from user_service.app.src.access import AccessResolver
from user_service.app.src.api.context import AppState
from user_service.app.src.api.app import app as real_app
from user_service.app.src.types import Settings

from infra.clients.users import (
    Ambassador,
    GiftCard,
    GiftCardDelivery,
    Influencer,
    Persona,
    Platform,
    UserProfile,
    UserProfileAdapter,
)
from infra.hubble.types import HubbleOrder, HubbleProduct
from infra.platform.gcp import GcpIdentity
from google.auth.credentials import AnonymousCredentials

USERS_SERVICE_SECRET = "test-users-service-secret"
USER_ID_HMAC_SECRET = "test-user-id-hmac-secret"
PUBLIC_ORIGIN = "https://sujho.test"


def _dump_attribution(attribution):
    if attribution is None:
        return None
    if hasattr(attribution, "model_dump"):
        return attribution.model_dump(mode="json")
    return attribution


def _attribution_handle(data: dict) -> Optional[str]:
    attr = data.get("attribution")
    if attr is None:
        return None
    kind = attr.kind if hasattr(attr, "kind") else attr.get("kind")
    if kind != "referrer":
        return None
    return attr.handle if hasattr(attr, "handle") else attr.get("handle")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class FakeUsersRepository:
    """In-memory stand-in for infra.firestore.UsersRepository."""

    def __init__(self, secret: str) -> None:
        self._secret = secret
        self._by_id: dict[str, dict] = {}

    def derive_user_id(self, phone: str) -> str:
        import hashlib
        import hmac

        digest = hmac.new(
            key=self._secret.encode("utf-8"), msg=phone.encode("utf-8"), digestmod=hashlib.sha256
        ).hexdigest()
        return digest[:32]

    def _profile(self, data: dict) -> UserProfile:
        return UserProfileAdapter.validate_python(data)

    async def get_by_phone(self, phone: str) -> Optional[UserProfile]:
        return await self.get_by_user_id(self.derive_user_id(phone))

    async def get_by_user_id(self, user_id: str) -> Optional[UserProfile]:
        data = self._by_id.get(user_id)
        return self._profile(data) if data is not None else None

    async def get_many(self, user_ids: list[str]) -> list[UserProfile]:
        return [self._profile(self._by_id[uid]) for uid in user_ids if uid in self._by_id]

    async def by_persona(self, persona: Persona) -> list[UserProfile]:
        return [self._profile(d) for d in self._by_id.values() if d["persona"] == persona]

    async def by_referrer(self, handle: str) -> list[UserProfile]:
        profiles = [
            self._profile(d) for d in self._by_id.values() if _attribution_handle(d) == handle
        ]
        return sorted(profiles, key=lambda p: p.createdAtMs)

    async def count_by_referrer(self, handle: str) -> int:
        return sum(1 for d in self._by_id.values() if _attribution_handle(d) == handle)

    async def create_user(self, profile, attribution) -> UserProfile:
        """Create-only: an existing phone's stored profile is returned unchanged."""
        user_id = self.derive_user_id(profile.phone)
        if user_id in self._by_id:
            return self._profile(self._by_id[user_id])
        from infra.utils.time import now_ms

        created_at_ms = now_ms()
        payload = {
            **profile.model_dump(mode="json"),
            "userId": user_id,
            "createdAtMs": created_at_ms,
            "attribution": _dump_attribution(attribution),
            "updatedAtMs": created_at_ms,
        }
        self._by_id[user_id] = payload
        return self._profile(payload)

    async def update_profile(self, user: UserProfile, update) -> UserProfile:
        payload = update.model_dump(mode="json", exclude_none=True)
        stored = self._by_id[user.userId]
        stored.update(payload)
        self._by_id[user.userId] = stored
        return self._profile(stored)

    async def set_location(self, user: UserProfile, location) -> UserProfile:
        stored = self._by_id[user.userId]
        stored["location"] = location.model_dump(mode="json")
        self._by_id[user.userId] = stored
        return self._profile(stored)

    async def delete_user(self, user_id: str) -> None:
        self._by_id.pop(user_id, None)

    # --- test-only seeding helpers -------------------------------------------------
    def seed(self, profile: dict) -> None:
        """Directly seed a raw user document keyed by profile['userId']."""
        self._by_id[profile["userId"]] = profile


# ---------------------------------------------------------------------------
# Referrers (influencers + ambassadors share one handle namespace)
# ---------------------------------------------------------------------------


class FakeReferrersRepository:
    """In-memory stand-in for infra.firestore.ReferrersRepository."""

    def __init__(self) -> None:
        self._by_handle: dict[str, dict] = {}

    async def exists(self, handle: str) -> bool:
        return handle in self._by_handle

    async def list_handles(self) -> set[str]:
        return set(self._by_handle.keys())

    async def get_influencer(self, handle: str) -> Optional[Influencer]:
        row = self._by_handle.get(handle)
        if row is None or row["kind"] != "influencer":
            return None
        return Influencer.model_validate({**row, "handle": handle})

    async def create_influencer(self, handle: str, platform: Platform) -> Influencer:
        """Mirrors the real repo: an existing doc id is returned as-is (no collision error)."""
        existing = self._by_handle.get(handle)
        if existing is not None:
            return Influencer.model_validate({**existing, "handle": handle})
        from infra.utils.time import now_ms

        influencer = Influencer(handle=handle, platform=platform, createdAtMs=now_ms())
        self._by_handle[handle] = influencer.model_dump(mode="json")
        return influencer

    async def create_ambassador(self, handle: str, user_id: str) -> Ambassador:
        from infra.utils.time import now_ms

        ambassador = Ambassador(handle=handle, userId=user_id, createdAtMs=now_ms())
        self._by_handle[handle] = ambassador.model_dump(mode="json")
        return ambassador

    async def list_influencers(self) -> list[Influencer]:
        return [
            Influencer.model_validate({**row, "handle": h})
            for h, row in self._by_handle.items()
            if row["kind"] == "influencer"
        ]

    async def list_ambassadors(self) -> list[Ambassador]:
        return [
            Ambassador.model_validate({**row, "handle": h})
            for h, row in self._by_handle.items()
            if row["kind"] == "ambassador"
        ]

    async def get_ambassador_by_user(self, user_id: str) -> Optional[Ambassador]:
        for handle, row in self._by_handle.items():
            if row["kind"] == "ambassador" and row.get("userId") == user_id:
                return Ambassador.model_validate({**row, "handle": handle})
        return None

    async def delete(self, handle: str) -> None:
        self._by_handle.pop(handle, None)

    # --- test-only seeding helpers -------------------------------------------------
    def seed_influencer(self, handle: str, platform: Platform, created_at_ms: int) -> None:
        self._by_handle[handle] = {
            "kind": "influencer",
            "platform": platform,
            "createdAtMs": created_at_ms,
        }

    def seed_ambassador(self, handle: str, user_id: str, created_at_ms: int) -> None:
        self._by_handle[handle] = {
            "kind": "ambassador",
            "userId": user_id,
            "createdAtMs": created_at_ms,
        }


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class FakeCampaignsRepository:
    """In-memory stand-in for infra.firestore.CampaignsRepository."""

    def __init__(self) -> None:
        self._by_handle: dict[str, dict[str, dict]] = {}

    async def list(self, handle: str) -> list:
        from infra.clients.users import Campaign

        rows = self._by_handle.get(handle, {})
        campaigns = [Campaign.model_validate({**w, "id": cid}) for cid, w in rows.items()]
        campaigns.sort(key=lambda c: c.startMs, reverse=True)
        return campaigns

    async def create(self, handle: str, body) -> "Campaign":
        """Mirrors the real repo: deterministic id, no overlap check."""
        from infra.clients.users import Campaign

        window = body.model_dump()
        campaign_id = f"{body.startMs}_{body.endMs}"
        self._by_handle.setdefault(handle, {})[campaign_id] = window
        return Campaign.model_validate({**window, "id": campaign_id})

    async def delete(self, handle: str, campaign_id: str) -> None:
        self._by_handle.get(handle, {}).pop(campaign_id, None)

    async def delete_all(self, handle: str) -> None:
        self._by_handle.pop(handle, None)


# ---------------------------------------------------------------------------
# Clicks
# ---------------------------------------------------------------------------


class FakeClicksRepository:
    """In-memory stand-in for infra.firestore.ClicksRepository."""

    def __init__(self) -> None:
        self._by_handle: dict[str, list[int]] = {}

    async def record(self, handle: str) -> None:
        from infra.utils.time import now_ms

        self._by_handle.setdefault(handle, []).append(now_ms())

    async def count_all(self, handle: str) -> int:
        return len(self._by_handle.get(handle, []))

    async def count_between(self, handle: str, start_ms: int, end_ms: int) -> int:
        return sum(1 for t in self._by_handle.get(handle, []) if start_ms <= t <= end_ms)

    async def delete_all(self, handle: str) -> None:
        self._by_handle.pop(handle, None)

    # --- test-only helper -----------------------------------------------------
    def rows_for(self, handle: str) -> list[int]:
        return list(self._by_handle.get(handle, []))


# ---------------------------------------------------------------------------
# Gifting
# ---------------------------------------------------------------------------


class FakeGiftingRepository:
    """In-memory stand-in for infra.firestore.GiftingRepository."""

    def __init__(self) -> None:
        self._by_user: dict[str, dict[str, dict]] = {}

    async def create_pending(
        self, user_id, product_id, brand, amount_inr, instructions, credit_inr
    ) -> GiftCard:
        import uuid

        from infra.utils.time import now_ms

        gift_card = GiftCard(
            id=uuid.uuid4().hex,
            productId=product_id,
            brand=brand,
            amountInr=amount_inr,
            status="pending",
            createdAtMs=now_ms(),
        )
        doc = {**gift_card.model_dump(mode="json"), "instructions": instructions}
        self._by_user.setdefault(user_id, {})[gift_card.id] = doc
        return gift_card

    async def fail(self, user_id, gift_card: GiftCard) -> GiftCard:
        doc = self._by_user[user_id][gift_card.id]
        doc["status"] = "failed"
        return gift_card.model_copy(update={"status": "failed"})

    async def succeed(self, user_id, gift_card: GiftCard, card_number, card_pin, valid_till) -> GiftCard:
        doc = self._by_user[user_id][gift_card.id]
        doc.update(status="succeeded", cardNumber=card_number, cardPin=card_pin, validTill=valid_till)
        return gift_card.model_copy(update={"status": "succeeded"})

    async def get(self, user_id, gift_card_id: str) -> Optional[GiftCardDelivery]:
        doc = self._by_user.get(user_id, {}).get(gift_card_id)
        return GiftCardDelivery.model_validate({**doc, "id": gift_card_id}) if doc else None

    async def list(self, user_id) -> list[GiftCard]:
        rows = self._by_user.get(user_id, {})
        cards = [GiftCard.model_validate({**d, "id": cid}) for cid, d in rows.items()]
        return sorted(cards, key=lambda c: c.createdAtMs, reverse=True)

    async def delete_for_user(self, user_id) -> None:
        self._by_user.pop(user_id, None)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------


class FakeEnrollmentsRepository:
    """In-memory stand-in for infra.firestore.EnrollmentsRepository."""

    def __init__(self) -> None:
        self._rows: set[tuple[str, str]] = set()

    async def get_student_ids_for_teacher(self, teacher_id: str) -> list[str]:
        return [s for t, s in self._rows if t == teacher_id]

    async def get_teacher_ids_for_student(self, student_id: str) -> list[str]:
        return [t for t, s in self._rows if s == student_id]

    async def create(self, teacher_user_id: str, student_user_id: str) -> None:
        self._rows.add((teacher_user_id, student_user_id))

    async def delete(self, teacher_user_id: str, student_user_id: str) -> None:
        self._rows.discard((teacher_user_id, student_user_id))

    async def delete_for_user(self, user_id: str) -> None:
        self._rows = {(t, s) for t, s in self._rows if t != user_id and s != user_id}


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


class FakeBlocklistRepository:
    """In-memory stand-in for infra.firestore.BlocklistRepository."""

    def __init__(self) -> None:
        self._ids: set[str] = set()

    async def contains(self, user_id: str) -> bool:
        return user_id in self._ids

    async def add(self, user_id: str) -> None:
        self._ids.add(user_id)

    async def remove(self, user_id: str) -> None:
        self._ids.discard(user_id)

    async def list_ids(self) -> set[str]:
        return set(self._ids)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


class FakeOnboardingRepository:
    """In-memory stand-in for infra.firestore.OnboardingRepository."""

    def __init__(self) -> None:
        self._by_sender: dict[str, object] = {}

    async def set(self, sender_id: str, action) -> None:
        self._by_sender[sender_id] = action

    async def get(self, sender_id: str):
        return self._by_sender.get(sender_id)

    async def clear(self, sender_id: str) -> None:
        self._by_sender.pop(sender_id, None)

    async def list_all(self) -> list:
        return list(self._by_sender.values())

    # --- test-only helper -----------------------------------------------------
    def seed(self, sender_id: str, action) -> None:
        self._by_sender[sender_id] = action


# ---------------------------------------------------------------------------
# Threads (sessions + transcripts)
# ---------------------------------------------------------------------------


class FakeThreadsRepository:
    """Simplified in-memory stand-in for infra.firestore.ThreadsRepository.

    Implements the Firestore-layout contract (2h session gap, transactional
    sequence counter, tip advance semantics) closely enough to drive the real
    routes for API-shape testing; it is not a byte-for-byte port of the
    production transactional implementation.
    """

    SESSION_GAP_MS = 2 * 60 * 60 * 1000

    def __init__(self) -> None:
        # (user_id, thread_key) -> {startedAtMs: {"session": {...}, "rows": [...]}}
        self._threads: dict[tuple[str, str], dict[int, dict]] = {}

    def _bucket(self, user_id: str, thread_key: str) -> dict[int, dict]:
        return self._threads.setdefault((user_id, thread_key), {})

    async def append_transcript(
        self, user_id, thread_key, messages, read_ids, started_at_ms=None
    ):
        from infra.clients.users import AppendTranscriptResult

        bucket = self._bucket(user_id, thread_key)
        first_at = messages[0].createdAtMs
        opened = False
        if started_at_ms is not None and started_at_ms in bucket:
            key = started_at_ms
        else:
            existing_keys = sorted(bucket.keys())
            latest_key = existing_keys[-1] if existing_keys else None
            if (
                latest_key is not None
                and first_at - bucket[latest_key]["session"]["lastMessageAtMs"] <= self.SESSION_GAP_MS
            ):
                key = latest_key
            else:
                key = first_at
                opened = True
                bucket[key] = {
                    "session": {
                        "startedAtMs": key,
                        "lastMessageAtMs": key,
                        "nextTranscriptSequence": 0,
                        "readNodeIds": [],
                        "extraction": None,
                    },
                    "rows": [],
                }
        session = bucket[key]["session"]
        for message in messages:
            bucket[key]["rows"].append(message)
        session["nextTranscriptSequence"] += len(messages)
        user_times = [m.createdAtMs for m in messages if m.role == "user"]
        if user_times:
            session["lastMessageAtMs"] = max(session["lastMessageAtMs"], max(user_times))
        session["readNodeIds"] = list({*session["readNodeIds"], *read_ids})
        return AppendTranscriptResult(
            startedAtMs=session["startedAtMs"],
            openedSessionNumber=len(bucket) if opened else None,
        )

    async def get_session_transcripts(self, user_id, thread_key) -> list:
        from infra.clients.users import SessionTranscript

        bucket = self._bucket(user_id, thread_key)
        out = []
        for key in sorted(bucket.keys()):
            session = bucket[key]["session"]
            out.append(SessionTranscript.model_validate({**session, "messages": bucket[key]["rows"]}))
        return out

    async def get_session_transcript(self, user_id, thread_key, started_at_ms):
        from infra.clients.users import SessionTranscript

        bucket = self._bucket(user_id, thread_key)
        if started_at_ms not in bucket:
            return None
        session = bucket[started_at_ms]["session"]
        return SessionTranscript.model_validate({**session, "messages": bucket[started_at_ms]["rows"]})

    async def set_session_extraction(self, user_id, thread_key, started_at_ms, extraction) -> None:
        bucket = self._bucket(user_id, thread_key)
        if started_at_ms not in bucket:
            raise KeyError(f"no session {started_at_ms}")
        session = bucket[started_at_ms]["session"]
        session["extraction"] = extraction.model_dump(mode="json")

    async def delete_for_user(self, user_id) -> None:
        for key in list(self._threads.keys()):
            if key[0] == user_id:
                self._threads.pop(key, None)


# ---------------------------------------------------------------------------
# Hubble / Graph / Media (genuinely external systems)
# ---------------------------------------------------------------------------


class FakeHubbleClient:
    """Recording stand-in for infra.hubble.HubbleClient."""

    def __init__(self) -> None:
        self.products: dict[str, HubbleProduct] = {}
        self.place_order_result: Optional[HubbleOrder] = None
        self.order_reads: dict[str, Optional[HubbleOrder]] = {}
        self.place_order_calls: list[dict] = []

    async def get_product(self, product_id: str) -> HubbleProduct:
        if product_id not in self.products:
            raise AssertionError(f"FakeHubbleClient has no product {product_id!r}")
        return self.products[product_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer
    ) -> HubbleOrder:
        self.place_order_calls.append(
            {"product_id": product_id, "reference_id": reference_id, "amount_inr": amount_inr}
        )
        if self.place_order_result is None:
            raise AssertionError("FakeHubbleClient.place_order called with no script")
        return self.place_order_result

    async def get_order_by_reference(self, reference_id: str) -> Optional[HubbleOrder]:
        return self.order_reads.get(reference_id)

    async def close(self) -> None:
        pass


class FakeGraphClient:
    """No-op stand-in for infra.platform.graph.GraphClient."""

    async def query(self, text: str, **params):
        return []

    async def close(self) -> None:
        pass


class FakeMediaBucket:
    """No-op stand-in for infra.platform.storage.GcsBucket on user DELETE."""

    async def delete_prefix(self, prefix: str) -> None:
        pass

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Fakes:
    """Bag of every fake repository/client wired into one test's AppState."""

    def __init__(self) -> None:
        self.users = FakeUsersRepository(USER_ID_HMAC_SECRET)
        self.enrollments = FakeEnrollmentsRepository()
        self.threads = FakeThreadsRepository()
        self.referrers = FakeReferrersRepository()
        self.clicks = FakeClicksRepository()
        self.campaigns = FakeCampaignsRepository()
        self.blocklist = FakeBlocklistRepository()
        self.gifting = FakeGiftingRepository()
        self.onboarding = FakeOnboardingRepository()
        self.hubble = FakeHubbleClient()
        self.graph = FakeGraphClient()
        self.media_bucket = FakeMediaBucket()


@pytest.fixture
def fakes() -> Fakes:
    """One fresh set of in-memory fakes per test."""
    return Fakes()


@pytest_asyncio.fixture
async def client(fakes: Fakes):
    """An httpx AsyncClient bound to the real app, with fakes wired via lifespan."""

    @asynccontextmanager
    async def test_lifespan(app):
        settings = Settings(
            gcp=GcpIdentity(
                project="test-project", location="test-location", credentials=AnonymousCredentials()
            ),
            users_service_secret=USERS_SERVICE_SECRET,
            user_id_hmac_secret=USER_ID_HMAC_SECRET,
            public_origin=PUBLIC_ORIGIN,
            hubble_api_origin="https://hubble.invalid",
            hubble_client_id="test-hubble-client-id",
            hubble_client_secret="test-hubble-client-secret",
            conversation_media_bucket="test-bucket",
            neo4j_uri="bolt://neo4j.invalid:7687",
            neo4j_user="test-neo4j-user",
            neo4j_password="test-neo4j-password",
        )
        app.state.ctx = AppState(
            db=None,
            settings=settings,
            users=fakes.users,
            enrollments=fakes.enrollments,
            threads=fakes.threads,
            referrers=fakes.referrers,
            clicks=fakes.clicks,
            campaigns=fakes.campaigns,
            blocklist=fakes.blocklist,
            gifting=fakes.gifting,
            onboarding=fakes.onboarding,
            hubble=fakes.hubble,
            access=AccessResolver(users=fakes.users, blocklist=fakes.blocklist),
            graph=fakes.graph,
            media_bucket=fakes.media_bucket,
        )
        yield

    real_app.router.lifespan_context = test_lifespan
    # raise_app_exceptions=False: an unhandled exception in a route/repository
    # must surface as a real 500 response for the test to assert against,
    # matching what a real deployed server returns to a real caller, rather
    # than propagating as a raw Python exception out of the test itself.
    transport = httpx.ASGITransport(app=real_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        async with real_app.router.lifespan_context(real_app):
            yield http_client


@pytest.fixture
def auth_headers() -> dict:
    return {"Authorization": f"Bearer {USERS_SERVICE_SECRET}"}


@pytest.fixture
def bad_auth_headers() -> dict:
    return {"Authorization": "Bearer wrong-secret"}


# ---------------------------------------------------------------------------
# Request-body builders (match infra.clients.users types.requests wire shapes)
# ---------------------------------------------------------------------------


def student_profile_input(
    phone: str,
    name: str = "Asha",
    grade: int = 8,
    subjects: Optional[list[str]] = None,
    institution_id: Optional[str] = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict:
    return {
        "phone": phone,
        "name": name,
        "institution": {"id": institution_id, "name": institution_name},
        "persona": "student",
        "scope": {"grade": grade, "subjects": subjects if subjects is not None else ["mathematics"]},
    }


def teacher_profile_input(
    phone: str,
    name: str = "Mr. Rao",
    grades: Optional[list[int]] = None,
    subjects: Optional[list[str]] = None,
    institution_id: Optional[str] = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict:
    return {
        "phone": phone,
        "name": name,
        "institution": {"id": institution_id, "name": institution_name},
        "persona": "teacher",
        "scope": {
            "grades": grades if grades is not None else [9, 10],
            "subjects": subjects if subjects is not None else ["physics"],
        },
    }


def create_user_body(profile: dict, pre_onboarding_texts: Optional[list[str]] = None) -> dict:
    return {"profile": profile, "preOnboardingTexts": pre_onboarding_texts or []}
