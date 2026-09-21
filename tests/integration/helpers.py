"""Builders and Firestore readers for the persistence integration suite."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Optional

import httpx

from . import constants as K


def derive_user_id(phone: str) -> str:
    """Recompute user_service's deterministic opaque user id for one phone."""
    digest = hmac.new(
        key=K.USERS_USER_ID_HMAC_SECRET.encode("utf-8"),
        msg=phone.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest[:32]


def student_profile(
    phone: str,
    *,
    name: str = "Asha",
    grade: int = 8,
    subjects: Optional[list[str]] = None,
    institution_id: Optional[str] = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict[str, Any]:
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


def teacher_profile(
    phone: str,
    *,
    name: str = "Mr Rao",
    grades: Optional[list[int]] = None,
    subjects: Optional[list[str]] = None,
    institution_id: Optional[str] = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict[str, Any]:
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
    profile: dict[str, Any], pre_onboarding_texts: Optional[list[str]] = None
) -> dict[str, Any]:
    return {"profile": profile, "preOnboardingTexts": pre_onboarding_texts or []}


def user_message(
    text: str,
    created_at_ms: int,
    *,
    turn_id: Optional[str] = "turn-1",
    sequence: Optional[int] = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "role": "user",
        "content": {"type": "text", "text": text},
        "createdAtMs": created_at_ms,
        "turnId": turn_id,
    }
    if sequence is not None:
        row["sequence"] = sequence
    return row


def assistant_message(
    text: str,
    created_at_ms: int,
    *,
    turn_id: Optional[str] = "turn-1",
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": {"type": "text", "text": text},
        "createdAtMs": created_at_ms,
        "turnId": turn_id,
    }


def append_body(
    messages: list[dict[str, Any]],
    *,
    read_ids: Optional[list[str]] = None,
    previous_response_id: Optional[str] = None,
    started_at_ms: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "messages": messages,
        "readIds": read_ids if read_ids is not None else [],
        "startedAtMs": started_at_ms,
    }


def amazon_product_body() -> dict[str, Any]:
    """An ACTIVE Amazon SKU that offers ₹50 and ₹100 against a ₹100 balance."""
    return {
        "id": K.AMAZON_PRODUCT_ID,
        "status": "ACTIVE",
        "amountRestrictions": {
            "minVoucherAmount": 50,
            "maxVoucherAmount": 1000,
            "denominations": [50, 100],
        },
        "howToUseInstructions": [{"instructions": ["Open the app", "Enter the code"]}],
    }


def inactive_product_body(product_id: str) -> dict[str, Any]:
    return {
        "id": product_id,
        "status": "INACTIVE",
        "amountRestrictions": None,
        "howToUseInstructions": [],
    }


def seed_reward_catalogue() -> dict[str, dict[str, Any]]:
    catalogue = {pid: inactive_product_body(pid) for pid in K.ALL_REWARD_PRODUCT_IDS}
    catalogue[K.AMAZON_PRODUCT_ID] = amazon_product_body()
    return catalogue


def success_order(
    *,
    card_number: str = "4111-1111",
    card_pin: str = "9999",
    valid_till: str = "2027-12-31",
) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "vouchers": [
            {"cardNumber": card_number, "cardPin": card_pin, "validTill": valid_till}
        ],
    }


def processing_order() -> dict[str, Any]:
    return {"status": "PROCESSING", "vouchers": []}


def empty_success_order() -> dict[str, Any]:
    return {"status": "SUCCESS", "vouchers": []}


def terminal_failure_order(status: str) -> dict[str, Any]:
    return {"status": status, "vouchers": []}


def forbidden_counters_present(data: dict[str, Any]) -> set[str]:
    """Stored-field names the Stored-derivations rule forbids."""
    return set(data) & K.FORBIDDEN_STORED_COUNTERS


# ---------------------------------------------------------------------------
# HTTP helpers against the running user_service
# ---------------------------------------------------------------------------


class UsersApi:
    """Bearer-authenticated client for the running user_service."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.headers = {"Authorization": f"Bearer {K.USERS_SERVICE_SECRET}"}

    async def post(self, path: str, json: Optional[dict[str, Any]] = None) -> httpx.Response:
        return await self._client.post(path, headers=self.headers, json=json)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(path, headers=self.headers, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(path, headers=self.headers, **kwargs)

    async def put(self, path: str, json: Optional[dict[str, Any]] = None) -> httpx.Response:
        return await self._client.put(path, headers=self.headers, json=json)

    async def create_user(
        self, profile: dict[str, Any], texts: Optional[list[str]] = None
    ) -> dict[str, Any]:
        response = await self.post("/internal/users", json=create_user_body(profile, texts))
        response.raise_for_status()
        return response.json()

    async def append(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        *,
        read_ids: Optional[list[str]] = None,
        previous_response_id: Optional[str] = None,
        started_at_ms: Optional[int] = None,
        thread_key: str = K.WHATSAPP_THREAD_KEY,
    ) -> httpx.Response:
        return await self.post(
            f"/internal/users/{user_id}/threads/{thread_key}/transcript",
            json=append_body(
                messages,
                read_ids=read_ids,
                previous_response_id=previous_response_id,
                started_at_ms=started_at_ms,
            ),
        )


# ---------------------------------------------------------------------------
# Firestore readers (emulator)
# ---------------------------------------------------------------------------


async def user_doc(db, user_id: str) -> Optional[dict[str, Any]]:
    snap = await db.collection(K.USERS_COLLECTION).document(user_id).get()
    return snap.to_dict() if snap.exists else None


async def session_ref(db, user_id: str, started_at_ms: int, thread_key: str = K.WHATSAPP_THREAD_KEY):
    return (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
        .document(str(started_at_ms))
    )


async def session_doc(
    db, user_id: str, started_at_ms: int, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> Optional[dict[str, Any]]:
    snap = await (await session_ref(db, user_id, started_at_ms, thread_key)).get()
    return snap.to_dict() if snap.exists else None


async def session_ids(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[str]:
    ref = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
    )
    return sorted([doc.id async for doc in ref.stream()])


async def transcript_rows(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sessions = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
    )
    async for session in sessions.stream():
        async for row in session.reference.collection(
            K.SESSION_TRANSCRIPT_SUBCOLLECTION
        ).stream():
            rows.append({**row.to_dict(), "_sessionId": session.id, "_rowId": row.id})
    return sorted(
        rows, key=lambda row: (row["_sessionId"], row.get("sequence") if row.get("sequence") is not None else -1)
    )


async def gifting_docs(db, user_id: str) -> list[dict[str, Any]]:
    ref = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.GIFTING_SUBCOLLECTION)
    )
    docs = []
    async for snap in ref.stream():
        docs.append({**snap.to_dict(), "_id": snap.id})
    return docs


async def referrer_doc(db, handle: str) -> Optional[dict[str, Any]]:
    snap = await db.collection(K.REFERRERS_COLLECTION).document(handle).get()
    return snap.to_dict() if snap.exists else None


async def campaign_docs(db, handle: str) -> list[dict[str, Any]]:
    ref = (
        db.collection(K.REFERRERS_COLLECTION)
        .document(handle)
        .collection(K.CAMPAIGNS_SUBCOLLECTION)
    )
    return [{**snap.to_dict(), "_id": snap.id} async for snap in ref.stream()]


async def click_count(db, handle: str) -> int:
    ref = (
        db.collection(K.REFERRERS_COLLECTION)
        .document(handle)
        .collection(K.CLICKS_SUBCOLLECTION)
    )
    return len([1 async for _ in ref.stream()])


async def enrollment_ids(db) -> list[str]:
    return sorted([doc.id async for doc in db.collection(K.ENROLLMENTS_COLLECTION).stream()])


async def blocklist_exists(db, user_id: str) -> bool:
    snap = await db.collection(K.BLOCKLIST_COLLECTION).document(user_id).get()
    return snap.exists


async def onboarding_exists(db, sender_id: str) -> bool:
    snap = await db.collection(K.ONBOARDING_COLLECTION).document(sender_id).get()
    return snap.exists
