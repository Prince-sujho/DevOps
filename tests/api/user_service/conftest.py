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

from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio

from user_service.app.src.access import AccessResolver
from user_service.app.src.api.context import AppState
from user_service.app.src.api.app import app as real_app
from user_service.app.src.types import Settings

from infra.clients.users import (
    Ambassador,
    Campaign,
    GiftCard,
    GiftCardDelivery,
    Influencer,
    Persona,
    Referrer,
    ReferrerAdapter,
    UserProfile,
    UserProfileAdapter,
)
from infra.hubble.types import HubbleOrder, HubbleProduct
from infra.platform.gcp import GcpIdentity
from google.api_core.exceptions import AlreadyExists
from google.auth.credentials import AnonymousCredentials

USERS_SERVICE_SECRET = "test-users-service-secret"
USER_ID_HMAC_SECRET = "test-user-id-hmac-secret"
PUBLIC_ORIGIN = "https://sujho.test"


def _dump_attribution(attribution):
    """Attribution as a JSON-mode dict, or None if there is none.

    Args:
        attribution: a pydantic attribution model, or None.
    Returns:
        Its JSON-mode dump, or None.
    Raises:
        None.
    """
    if attribution is None:
        return None
    if hasattr(attribution, "model_dump"):
        return attribution.model_dump(mode="json")
    return attribution


def _attribution_handle(data: dict) -> str | None:
    """The referrer handle on a stored user doc, or None if not
    referrer-attributed.

    Args:
        data: a stored user document.
    Returns:
        The attributed handle, or None.
    Raises:
        None.
    """
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
        """An empty user store, keyed by derived user id.

        Args:
            secret: the HMAC secret used to derive user ids from phone numbers.
        Returns:
            None.
        Raises:
            None.
        """
        self._secret = secret
        self._by_id: dict[str, dict] = {}

    def derive_user_id(self, phone: str) -> str:
        """The deterministic opaque user id for phone, HMAC'd with this repo's
        secret.

        Args:
            phone: the phone number to derive an id from.
        Returns:
            The derived 32-hex-char user id.
        Raises:
            None.
        """
        import hashlib
        import hmac

        digest = hmac.new(
            key=self._secret.encode("utf-8"),
            msg=phone.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return digest[:32]

    def _profile(self, data: dict) -> UserProfile:
        """A stored raw doc, parsed into a UserProfile.

        Args:
            data: a stored raw user document.
        Returns:
            The parsed profile.
        Raises:
            None.
        """
        return UserProfileAdapter.validate_python(data)

    async def get_by_phone(self, phone: str) -> UserProfile | None:
        """The stored profile for phone, or None.

        Args:
            phone: the phone number to look up.
        Returns:
            The matching profile, or None.
        Raises:
            None.
        """
        return await self.get_by_user_id(self.derive_user_id(phone))

    async def get_by_user_id(self, user_id: str) -> UserProfile | None:
        """The stored profile for user_id, or None.

        Args:
            user_id: the user id to look up.
        Returns:
            The matching profile, or None.
        Raises:
            None.
        """
        data = self._by_id.get(user_id)
        return self._profile(data) if data is not None else None

    async def get_many(self, user_ids: list[str]) -> list[UserProfile]:
        """Every stored profile matching user_ids, in the order found.

        Args:
            user_ids: the user ids to look up.
        Returns:
            The matching profiles, missing ids silently skipped.
        Raises:
            None.
        """
        return [
            self._profile(self._by_id[uid])
            for uid in user_ids
            if uid in self._by_id
        ]

    async def by_persona(self, persona: Persona) -> list[UserProfile]:
        """Every stored profile with the given persona.

        Args:
            persona: the persona to filter by.
        Returns:
            The matching profiles.
        Raises:
            None.
        """
        return [
            self._profile(d)
            for d in self._by_id.values()
            if d["persona"] == persona
        ]

    async def by_referrer(self, handle: str) -> list[UserProfile]:
        """Every stored profile attributed to handle, oldest first.

        Args:
            handle: the referrer handle to filter by.
        Returns:
            The matching profiles, oldest createdAtMs first.
        Raises:
            None.
        """
        profiles = [
            self._profile(d)
            for d in self._by_id.values()
            if _attribution_handle(d) == handle
        ]
        return sorted(profiles, key=lambda p: p.createdAtMs)

    async def count_by_referrer(self, handle: str) -> int:
        """How many stored profiles are attributed to handle.

        Args:
            handle: the referrer handle to count.
        Returns:
            The count.
        Raises:
            None.
        """
        return sum(
            1 for d in self._by_id.values() if _attribution_handle(d) == handle
        )

    async def create_user(self, profile, attribution) -> UserProfile:
        """Create-only: an existing phone's stored profile is returned
        unchanged.

        Args:
            profile: the profile being created.
            attribution: the referrer/campaign attribution, or None.
        Returns:
            The created (or pre-existing) profile.
        Raises:
            None.
        """
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
        """Merge update's set fields into the stored profile.

        Args:
            user: the profile being updated.
            update: the fields to change; unset fields are left alone.
        Returns:
            The updated profile.
        Raises:
            None.
        """
        payload = update.model_dump(mode="json", exclude_none=True)
        stored = self._by_id[user.userId]
        stored.update(payload)
        self._by_id[user.userId] = stored
        return self._profile(stored)

    async def set_location(self, user: UserProfile, location) -> UserProfile:
        """Store location on the profile.

        Args:
            user: the profile being updated.
            location: the location to store.
        Returns:
            The updated profile.
        Raises:
            None.
        """
        stored = self._by_id[user.userId]
        stored["location"] = location.model_dump(mode="json")
        self._by_id[user.userId] = stored
        return self._profile(stored)

    async def delete_user(self, user_id: str) -> None:
        """Remove the stored profile for user_id, if any.

        Args:
            user_id: the profile to remove.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_id.pop(user_id, None)

    # --- test-only seeding helpers --------------------------------------------
    def seed(self, profile: dict) -> None:
        """Directly seed a raw user document keyed by profile['userId'].

        Args:
            profile: the raw document to store.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_id[profile["userId"]] = profile


# ---------------------------------------------------------------------------
# Referrers (influencers + ambassadors share one handle namespace)
# ---------------------------------------------------------------------------


class FakeReferrersRepository:
    """In-memory stand-in for infra.firestore.ReferrersRepository."""

    def __init__(self) -> None:
        """An empty referrer store, keyed by handle.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle: dict[str, dict] = {}

    async def exists(self, handle: str) -> bool:
        """True if handle has a stored referrer document.

        Args:
            handle: the referrer handle to check.
        Returns:
            True if a document is stored at handle.
        Raises:
            None.
        """
        return handle in self._by_handle

    async def list_handles(self) -> set[str]:
        """Every stored referrer handle.

        Args:
            None.
        Returns:
            The set of stored handles.
        Raises:
            None.
        """
        return set(self._by_handle.keys())

    async def get(self, handle: str) -> Referrer | None:
        """The stored registry entry of any kind at handle, or None.

        Args:
            handle: the handle to look up.
        Returns:
            The influencer, ambassador or classroom entry, or None.
        Raises:
            None.
        """
        row = self._by_handle.get(handle)
        if row is None:
            return None
        return ReferrerAdapter.validate_python({**row, "handle": handle})

    async def create(self, entry: Referrer) -> None:
        """Mirrors the real repo: a taken handle of any kind raises
        AlreadyExists.

        Args:
            entry: the registry entry to store under its handle.
        Returns:
            None.
        Raises:
            AlreadyExists: if the handle is already taken.
        """
        if entry.handle in self._by_handle:
            raise AlreadyExists(entry.handle)
        self._by_handle[entry.handle] = entry.model_dump(
            mode="json", exclude={"handle"}
        )

    async def list_influencers(self) -> list[Influencer]:
        """Every stored influencer.

        Args:
            None.
        Returns:
            Every stored referrer document whose kind is influencer.
        Raises:
            None.
        """
        return [
            Influencer.model_validate({**row, "handle": h})
            for h, row in self._by_handle.items()
            if row["kind"] == "influencer"
        ]

    async def list_ambassadors(self) -> list[Ambassador]:
        """Every stored ambassador.

        Args:
            None.
        Returns:
            Every stored referrer document whose kind is ambassador.
        Raises:
            None.
        """
        return [
            Ambassador.model_validate({**row, "handle": h})
            for h, row in self._by_handle.items()
            if row["kind"] == "ambassador"
        ]

    async def get_ambassador_by_user(
        self, user_id: str
    ) -> Ambassador | None:
        """The stored ambassador for user_id, or None.

        Args:
            user_id: the underlying user's id.
        Returns:
            The matching ambassador, or None.
        Raises:
            None.
        """
        for handle, row in self._by_handle.items():
            if row["kind"] == "ambassador" and row.get("userId") == user_id:
                return Ambassador.model_validate({**row, "handle": handle})
        return None

    async def delete(self, handle: str) -> None:
        """Remove the stored referrer document at handle, if any.

        Args:
            handle: the referrer document to remove.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle.pop(handle, None)

    # --- test-only seeding helpers --------------------------------------------
    def seed_influencer(self, handle: str, created_at_ms: int) -> None:
        """Directly seed an influencer document at handle.

        Args:
            handle: the influencer's handle.
            created_at_ms: the document's creation time, epoch ms.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle[handle] = {
            "kind": "influencer",
            "createdAtMs": created_at_ms,
        }

    def seed_ambassador(
        self, handle: str, user_id: str, created_at_ms: int
    ) -> None:
        """Directly seed an ambassador document at handle.

        Args:
            handle: the ambassador's handle.
            user_id: the underlying user's id.
            created_at_ms: the document's creation time, epoch ms.
        Returns:
            None.
        Raises:
            None.
        """
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
        """An empty campaign store, keyed by handle then campaign id.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle: dict[str, dict[str, dict]] = {}

    async def list(self, handle: str) -> list:
        """Every campaign for handle, newest start first.

        Args:
            handle: the referrer handle to list campaigns for.
        Returns:
            The campaigns, newest startMs first.
        Raises:
            None.
        """
        rows = self._by_handle.get(handle, {})
        campaigns = [
            Campaign.model_validate({**w, "id": cid}) for cid, w in rows.items()
        ]
        campaigns.sort(key=lambda c: c.startMs, reverse=True)
        return campaigns

    async def create(self, handle: str, body) -> Campaign:
        """Build one campaign, defaulting to the standard payout terms.

        Args:
            handle: the referrer handle the campaign belongs to.
            body: the campaign window request body.
        Returns:
            The created campaign.
        Raises:
            None.
        """
        window = body.model_dump()
        campaign_id = f"{body.startMs}_{body.endMs}"
        self._by_handle.setdefault(handle, {})[campaign_id] = window
        return Campaign.model_validate({**window, "id": campaign_id})

    async def delete(self, handle: str, campaign_id: str) -> None:
        """Remove one campaign under handle, if it exists.

        Args:
            handle: the referrer handle the campaign belongs to.
            campaign_id: the campaign to remove.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle.get(handle, {}).pop(campaign_id, None)

    async def delete_all(self, handle: str) -> None:
        """Remove every campaign under handle.

        Args:
            handle: the referrer handle to clear.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle.pop(handle, None)


# ---------------------------------------------------------------------------
# Clicks
# ---------------------------------------------------------------------------


class FakeClicksRepository:
    """In-memory stand-in for infra.firestore.ClicksRepository."""

    def __init__(self) -> None:
        """An empty click store, keyed by handle.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle: dict[str, list[int]] = {}

    async def record(self, handle: str) -> None:
        """Record one click timestamp for handle.

        Args:
            handle: the referrer handle to record a click for.
        Returns:
            None.
        Raises:
            None.
        """
        from infra.utils.time import now_ms

        self._by_handle.setdefault(handle, []).append(now_ms())

    async def count_all(self, handle: str) -> int:
        """How many clicks are recorded for handle.

        Args:
            handle: the referrer handle to count.
        Returns:
            The click count.
        Raises:
            None.
        """
        return len(self._by_handle.get(handle, []))

    async def count_between(
        self, handle: str, start_ms: int, end_ms: int
    ) -> int:
        """How many of handle's recorded clicks fall within [start_ms, end_ms].

        Args:
            handle: the referrer handle to count.
            start_ms: window start, inclusive.
            end_ms: window end, inclusive.
        Returns:
            The click count within the window.
        Raises:
            None.
        """
        return sum(
            1
            for t in self._by_handle.get(handle, [])
            if start_ms <= t <= end_ms
        )

    async def delete_all(self, handle: str) -> None:
        """Remove every recorded click for handle.

        Args:
            handle: the referrer handle to clear.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_handle.pop(handle, None)

    # --- test-only helper -----------------------------------------------------
    def rows_for(self, handle: str) -> list[int]:
        """Every recorded click timestamp for handle.

        Args:
            handle: the referrer handle to read.
        Returns:
            A copy of the recorded timestamps.
        Raises:
            None.
        """
        return list(self._by_handle.get(handle, []))


# ---------------------------------------------------------------------------
# Gifting
# ---------------------------------------------------------------------------


class FakeGiftingRepository:
    """In-memory stand-in for infra.firestore.GiftingRepository."""

    def __init__(self) -> None:
        """An empty gift-card store, keyed by user id then card id.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_user: dict[str, dict[str, dict]] = {}

    async def create_pending(
        self, user_id, product_id, brand, amount_inr, instructions, credit_inr
    ) -> GiftCard:
        """Create and store a pending gift card for user_id.

        Args:
            user_id: the recipient user.
            product_id: the reward product being minted.
            brand: the gift-card brand.
            amount_inr: the gift-card amount, in INR.
            instructions: redemption instructions.
            credit_inr: unused; kept to match the real signature.
        Returns:
            The created (pending) gift card.
        Raises:
            None.
        """
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
        doc = {
            **gift_card.model_dump(mode="json"),
            "instructions": instructions,
        }
        self._by_user.setdefault(user_id, {})[gift_card.id] = doc
        return gift_card

    async def fail(self, user_id, gift_card: GiftCard) -> GiftCard:
        """Mark the stored gift card failed and return the update.

        Args:
            user_id: the card's owner.
            gift_card: the card to fail.
        Returns:
            The updated gift card.
        Raises:
            None.
        """
        doc = self._by_user[user_id][gift_card.id]
        doc["status"] = "failed"
        return gift_card.model_copy(update={"status": "failed"})

    async def succeed(
        self, user_id, gift_card: GiftCard, card_number, card_pin, valid_till
    ) -> GiftCard:
        """Mark the stored gift card succeeded, with its voucher fields, and
        return the update.

        Args:
            user_id: the card's owner.
            gift_card: the card to succeed.
            card_number: the voucher card number.
            card_pin: the voucher PIN.
            valid_till: the voucher expiry date.
        Returns:
            The updated gift card.
        Raises:
            None.
        """
        doc = self._by_user[user_id][gift_card.id]
        doc.update(
            status="succeeded",
            cardNumber=card_number,
            cardPin=card_pin,
            validTill=valid_till,
        )
        return gift_card.model_copy(update={"status": "succeeded"})

    async def get(
        self, user_id, gift_card_id: str
    ) -> GiftCardDelivery | None:
        """The stored gift-card delivery for (user_id, gift_card_id), or None.

        Args:
            user_id: the card's owner.
            gift_card_id: the card to look up.
        Returns:
            The delivery, or None.
        Raises:
            None.
        """
        doc = self._by_user.get(user_id, {}).get(gift_card_id)
        return (
            GiftCardDelivery.model_validate({**doc, "id": gift_card_id})
            if doc
            else None
        )

    async def list(self, user_id) -> list[GiftCard]:
        """Every stored gift card for user_id, newest first.

        Args:
            user_id: the owner to list cards for.
        Returns:
            The cards, newest createdAtMs first.
        Raises:
            None.
        """
        rows = self._by_user.get(user_id, {})
        cards = [
            GiftCard.model_validate({**d, "id": cid}) for cid, d in rows.items()
        ]
        return sorted(cards, key=lambda c: c.createdAtMs, reverse=True)

    async def delete_for_user(self, user_id) -> None:
        """Remove every stored gift card for user_id.

        Args:
            user_id: the owner to clear.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_user.pop(user_id, None)


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


class FakeBlocklistRepository:
    """In-memory stand-in for infra.firestore.BlocklistRepository."""

    def __init__(self) -> None:
        """An empty blocked-user-id set.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._ids: set[str] = set()

    async def contains(self, user_id: str) -> bool:
        """True if user_id is blocked.

        Args:
            user_id: the user id to check.
        Returns:
            True if user_id is blocked.
        Raises:
            None.
        """
        return user_id in self._ids

    async def add(self, user_id: str) -> None:
        """Block user_id.

        Args:
            user_id: the user id to block.
        Returns:
            None.
        Raises:
            None.
        """
        self._ids.add(user_id)

    async def remove(self, user_id: str) -> None:
        """Unblock user_id.

        Args:
            user_id: the user id to unblock.
        Returns:
            None.
        Raises:
            None.
        """
        self._ids.discard(user_id)

    async def list_ids(self) -> set[str]:
        """Every blocked user id.

        Args:
            None.
        Returns:
            A copy of the blocked user id set.
        Raises:
            None.
        """
        return set(self._ids)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


class FakeOnboardingRepository:
    """In-memory stand-in for infra.firestore.OnboardingRepository."""

    def __init__(self) -> None:
        """An empty pending-onboarding-action store, keyed by sender id.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_sender: dict[str, object] = {}

    async def set(self, sender_id: str, action) -> None:
        """Store action as sender_id's pending action.

        Args:
            sender_id: the sender to store an action for.
            action: the pending action.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_sender[sender_id] = action

    async def get(self, sender_id: str):
        """The stored pending action for sender_id, or None.

        Args:
            sender_id: the sender to look up.
        Returns:
            The stored action, or None.
        Raises:
            None.
        """
        return self._by_sender.get(sender_id)

    async def clear(self, sender_id: str) -> None:
        """Remove the stored pending action for sender_id.

        Args:
            sender_id: the sender to clear.
        Returns:
            None.
        Raises:
            None.
        """
        self._by_sender.pop(sender_id, None)

    async def list_all(self) -> list:
        """Every stored pending action.

        Args:
            None.
        Returns:
            Every stored pending action, in storage order.
        Raises:
            None.
        """
        return list(self._by_sender.values())

    # --- test-only helper -----------------------------------------------------
    def seed(self, sender_id: str, action) -> None:
        """Directly seed a pending action for sender_id.

        Args:
            sender_id: the sender to seed.
            action: the pending action to store.
        Returns:
            None.
        Raises:
            None.
        """
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
        """An empty thread store, keyed by (user_id, thread_key) then session
        start.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        # (user_id, thread_key) -> {startedAtMs: {"session": {...}, "rows":
        # [...]}}
        self._threads: dict[tuple[str, str], dict[int, dict]] = {}

    def _bucket(self, user_id: str, thread_key: str) -> dict[int, dict]:
        """This (user_id, thread_key) pair's session bucket, creating it if
        needed.

        Args:
            user_id: the thread's owner.
            thread_key: the thread key.
        Returns:
            The bucket, keyed by session startedAtMs.
        Raises:
            None.
        """
        return self._threads.setdefault((user_id, thread_key), {})

    def _resolve_session_key(
        self, bucket: dict[int, dict], first_at: int, started_at_ms
    ):
        """The session key to write to, opening a new session if the gap demands
        it.

        Args:
            bucket: this (user_id, thread_key) pair's session bucket.
            first_at: the first message's createdAtMs in this append.
            started_at_ms: pin to this session, or None to open/resolve one.
        Returns:
            (key, opened) — opened is True only if a new session was created.
        Raises:
            None.
        """
        if started_at_ms is not None and started_at_ms in bucket:
            return started_at_ms, False

        existing_keys = sorted(bucket.keys())
        latest_key = existing_keys[-1] if existing_keys else None
        gap = (
            first_at - bucket[latest_key]["session"]["lastMessageAtMs"]
            if latest_key is not None
            else None
        )
        if latest_key is not None and gap <= self.SESSION_GAP_MS:
            return latest_key, False

        key = first_at
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
        return key, True

    async def append_transcript(
        self, user_id, thread_key, messages, read_ids, started_at_ms=None
    ):
        """Append messages, opening a new session if the SESSION_GAP_MS has
        passed.

        Args:
            user_id: the user the transcript belongs to.
            thread_key: the thread being appended to.
            messages: the transcript rows to append.
            read_ids: node ids being marked read by this append.
            started_at_ms: pin to this session, or None to open/resolve one.
        Returns:
            The AppendTranscriptResult.
        Raises:
            None.
        """
        from infra.clients.users import AppendTranscriptResult

        bucket = self._bucket(user_id, thread_key)
        first_at = messages[0].createdAtMs
        key, opened = self._resolve_session_key(bucket, first_at, started_at_ms)
        session = bucket[key]["session"]
        for message in messages:
            bucket[key]["rows"].append(message)
        session["nextTranscriptSequence"] += len(messages)
        user_times = [m.createdAtMs for m in messages if m.role == "user"]
        if user_times:
            session["lastMessageAtMs"] = max(
                session["lastMessageAtMs"], max(user_times)
            )
        session["readNodeIds"] = list({*session["readNodeIds"], *read_ids})
        return AppendTranscriptResult(
            startedAtMs=session["startedAtMs"],
            openedSessionNumber=len(bucket) if opened else None,
        )

    async def get_session_transcripts(self, user_id, thread_key) -> list:
        """Every session transcript for (user_id, thread_key), oldest first.

        Args:
            user_id: the thread's owner.
            thread_key: the thread key.
        Returns:
            Every session transcript, oldest startedAtMs first.
        Raises:
            None.
        """
        from infra.clients.users import SessionTranscript

        bucket = self._bucket(user_id, thread_key)
        out = []
        for key in sorted(bucket.keys()):
            session = bucket[key]["session"]
            rows = bucket[key]["rows"]
            out.append(
                SessionTranscript.model_validate({**session, "messages": rows})
            )
        return out

    async def get_session_transcript(self, user_id, thread_key, started_at_ms):
        """One session's transcript, or None if that session doesn't exist.

        Args:
            user_id: the user the session belongs to.
            thread_key: the thread the session is under.
            started_at_ms: the session's start time.
        Returns:
            Its transcript, or None.
        Raises:
            None.
        """
        from infra.clients.users import SessionTranscript

        bucket = self._bucket(user_id, thread_key)
        if started_at_ms not in bucket:
            return None
        session = bucket[started_at_ms]["session"]
        rows = bucket[started_at_ms]["rows"]
        return SessionTranscript.model_validate({**session, "messages": rows})

    async def set_session_extraction(
        self, user_id, thread_key, started_at_ms, extraction
    ) -> None:
        """Store extraction on an existing session; raises if the session
        doesn't exist.

        Args:
            user_id: the user the session belongs to.
            thread_key: the thread the session is under.
            started_at_ms: the session's start time.
            extraction: the judgment to store.
        Returns:
            None.
        Raises:
            KeyError: no session exists at started_at_ms.
        """
        bucket = self._bucket(user_id, thread_key)
        if started_at_ms not in bucket:
            raise KeyError(f"no session {started_at_ms}")
        session = bucket[started_at_ms]["session"]
        session["extraction"] = extraction.model_dump(mode="json")

    async def delete_for_user(self, user_id) -> None:
        """Remove every thread bucket belonging to user_id.

        Args:
            user_id: the user to clear.
        Returns:
            None.
        Raises:
            None.
        """
        for key in list(self._threads.keys()):
            if key[0] == user_id:
                self._threads.pop(key, None)


# ---------------------------------------------------------------------------
# Hubble / Graph / Media (genuinely external systems)
# ---------------------------------------------------------------------------


class FakeHubbleClient:
    """Recording stand-in for infra.hubble.HubbleClient."""

    def __init__(self) -> None:
        """An empty product/order store; unscripted place_order raises.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.products: dict[str, HubbleProduct] = {}
        self.place_order_result: HubbleOrder | None = None
        self.order_reads: dict[str, HubbleOrder | None] = {}
        self.place_order_calls: list[dict] = []

    async def get_product(self, product_id: str) -> HubbleProduct:
        """The scripted product, or raise if product_id wasn't scripted.

        Args:
            product_id: the product to look up.
        Returns:
            The scripted product.
        Raises:
            AssertionError: product_id wasn't scripted.
        """
        if product_id not in self.products:
            raise AssertionError(
                f"FakeHubbleClient has no product {product_id!r}"
            )
        return self.products[product_id]

    async def place_order(
        self, product_id: str, reference_id: str, amount_inr: int, customer
    ) -> HubbleOrder:
        """Record the call and return the scripted order, or raise if none is
        set.

        Args:
            product_id: the product being ordered.
            reference_id: the order's reference id.
            amount_inr: the order amount, in INR.
            customer: unused; kept to match the real signature.
        Returns:
            The scripted order.
        Raises:
            AssertionError: no order result was scripted.
        """
        self.place_order_calls.append(
            {
                "product_id": product_id,
                "reference_id": reference_id,
                "amount_inr": amount_inr,
            }
        )
        if self.place_order_result is None:
            raise AssertionError(
                "FakeHubbleClient.place_order called with no script"
            )
        return self.place_order_result

    async def get_order_by_reference(
        self, reference_id: str
    ) -> HubbleOrder | None:
        """The scripted order read for reference_id, or None.

        Args:
            reference_id: the order's reference id.
        Returns:
            The scripted order, or None.
        Raises:
            None.
        """
        return self.order_reads.get(reference_id)

    async def close(self) -> None:
        """No-op close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pass


class FakeGraphClient:
    """No-op stand-in for infra.platform.graph.GraphClient."""

    async def query(self, text: str, **params):
        """Always returns no rows.

        Args:
            text: the Cypher query text (ignored).
            params: query parameters (ignored).
        Returns:
            An empty list.
        Raises:
            None.
        """
        return []

    async def close(self) -> None:
        """No-op close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pass


class FakeMediaBucket:
    """No-op stand-in for infra.platform.storage.GcsBucket on user DELETE."""

    async def delete_prefix(self, prefix: str) -> None:
        """No-op delete.

        Args:
            prefix: the path prefix (ignored).
        Returns:
            None.
        Raises:
            None.
        """
        pass

    async def close(self) -> None:
        """No-op close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Fakes:
    """Bag of every fake repository/client wired into one test's AppState."""

    def __init__(self) -> None:
        """Wire one fresh fake of every repository/client this test's AppState
        needs.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.users = FakeUsersRepository(USER_ID_HMAC_SECRET)
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
    """One fresh set of in-memory fakes per test.

    Args:
        None.
    Returns:
        A fresh Fakes bag.
    Raises:
        None.
    """
    return Fakes()


def _test_settings() -> Settings:
    """Test Settings for user_service: real shape, fake project/secrets/origins.

    Args:
        None.
    Returns:
        The test Settings.
    Raises:
        None.
    """
    return Settings(
        gcp=GcpIdentity(
            project="test-project",
            location="test-location",
            credentials=AnonymousCredentials(),
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


def _test_app_state(fakes: Fakes) -> AppState:
    """AppState wired entirely to the given fakes, with no real db.

    Args:
        fakes: the fake repositories/clients to wire in.
    Returns:
        The wired AppState.
    Raises:
        None.
    """
    return AppState(
        db=None,
        settings=_test_settings(),
        users=fakes.users,
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


@pytest_asyncio.fixture
async def client(fakes: Fakes):
    """An httpx AsyncClient bound to the real app, with fakes wired via
    lifespan.

    Args:
        fakes: the fake repositories/clients to wire into AppState.
    Returns:
        The bound AsyncClient.
    Raises:
        None.
    """

    @asynccontextmanager
    async def test_lifespan(app):
        """Wire app.state.ctx to an AppState built entirely from fakes.

        Args:
            app: the FastAPI app being started.
        Returns:
            None.
        Raises:
            None.
        """
        app.state.ctx = _test_app_state(fakes)
        yield

    real_app.router.lifespan_context = test_lifespan
    # raise_app_exceptions=False: an unhandled exception in a route/repository
    # must surface as a real 500 response for the test to assert against,
    # matching what a real deployed server returns to a real caller, rather
    # than propagating as a raw Python exception out of the test itself.
    transport = httpx.ASGITransport(app=real_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        async with real_app.router.lifespan_context(real_app):
            yield http_client


@pytest.fixture
def auth_headers() -> dict:
    """A valid Authorization header for the users service secret.

    Args:
        None.
    Returns:
        The headers dict.
    Raises:
        None.
    """
    return {"Authorization": f"Bearer {USERS_SERVICE_SECRET}"}


@pytest.fixture
def bad_auth_headers() -> dict:
    """An Authorization header carrying the wrong secret.

    Args:
        None.
    Returns:
        The headers dict.
    Raises:
        None.
    """
    return {"Authorization": "Bearer wrong-secret"}


# ---------------------------------------------------------------------------
# Request-body builders (match infra.clients.users types.requests wire shapes)
# ---------------------------------------------------------------------------


def student_profile_input(
    phone: str,
    name: str = "Asha",
    grade: int = 8,
    subjects: list[str] | None = None,
    institution_id: str | None = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict:
    """A well-formed student profile request body.

    Args:
        phone: the student's phone number.
        name: the student's name.
        grade: the student's grade.
        subjects: enrolled subjects, or None for the default (mathematics).
        institution_id: the school's id, or None.
        institution_name: the school's name.
    Returns:
        The request body dict.
    Raises:
        None.
    """
    return {
        "phone": phone,
        "name": name,
        "institution": {"id": institution_id, "name": institution_name},
        "persona": "student",
        "scope": {
            "grade": grade,
            "subjects": subjects if subjects is not None else ["mathematics"],
        },
    }


def teacher_profile_input(
    phone: str,
    name: str = "Mr. Rao",
    grades: list[int] | None = None,
    subjects: list[str] | None = None,
    institution_id: str | None = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict:
    """A well-formed teacher profile request body.

    Args:
        phone: the teacher's phone number.
        name: the teacher's name.
        grades: taught grades, or None for the default ([9, 10]).
        subjects: taught subjects, or None for the default (physics).
        institution_id: the school's id, or None.
        institution_name: the school's name.
    Returns:
        The request body dict.
    Raises:
        None.
    """
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


def create_user_body(
    profile: dict, pre_onboarding_texts: list[str] | None = None
) -> dict:
    """A POST /internal/users request body.

    Args:
        profile: the profile body.
        pre_onboarding_texts: buffered pre-onboarding texts, or None.
    Returns:
        The request body dict.
    Raises:
        None.
    """
    return {
        "profile": profile,
        "preOnboardingTexts": pre_onboarding_texts or [],
    }
