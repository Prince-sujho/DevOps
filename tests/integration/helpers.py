"""Builders and Firestore readers for the persistence integration suite."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Optional

import httpx

from . import constants as K


def derive_user_id(phone: str) -> str:
    """Recompute user_service's deterministic opaque user id for one phone.

    Args:
        phone: phone number hashed into the opaque user id.
    Returns:
        The first 32 hex characters of the HMAC-SHA256 digest of the phone.
    Raises:
        None.
    """
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
    """Build one student profile request body.

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


def teacher_profile(
    phone: str,
    *,
    name: str = "Mr Rao",
    grades: Optional[list[int]] = None,
    subjects: Optional[list[str]] = None,
    institution_id: Optional[str] = "school-1",
    institution_name: str = "Delhi Public School",
) -> dict[str, Any]:
    """Build one teacher profile request body.

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
    profile: dict[str, Any], pre_onboarding_texts: Optional[list[str]] = None
) -> dict[str, Any]:
    """Build a POST /internal/users request body.

    Args:
        profile: the profile body (from student_profile/teacher_profile).
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


def user_message(
    text: str,
    created_at_ms: int,
    *,
    turn_id: Optional[str] = "turn-1",
    sequence: Optional[int] = None,
) -> dict[str, Any]:
    """Build one user-role transcript message row.

    Args:
        text: the message text.
        created_at_ms: when the message was sent, epoch ms.
        turn_id: the turn this message belongs to.
        sequence: an explicit sequence number, or None to omit it.
    Returns:
        The row dict.
    Raises:
        None.
    """
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
    text: str, created_at_ms: int, *, turn_id: Optional[str] = "turn-1"
) -> dict[str, Any]:
    """Build one assistant-role transcript message row.

    Args:
        text: the message text.
        created_at_ms: when the message was sent, epoch ms.
        turn_id: the turn this message belongs to.
    Returns:
        The row dict.
    Raises:
        None.
    """
    return {
        "role": "assistant",
        "content": {"type": "text", "text": text},
        "createdAtMs": created_at_ms,
        "turnId": turn_id,
    }


def append_body(
    messages: list[dict[str, Any]], *, started_at_ms: Optional[int] = None
) -> dict[str, Any]:
    """Build a transcript-append request body.

    Args:
        messages: the transcript rows to append.
        started_at_ms: pin to this session, or None to open/resolve one.
    Returns:
        The request body dict.
    Raises:
        None.
    """
    return {"messages": messages, "startedAtMs": started_at_ms}


def amazon_product_body() -> dict[str, Any]:
    """An ACTIVE Amazon SKU that offers ₹50 and ₹100 against a ₹100 balance.

    Args:
        None.
    Returns:
        An ACTIVE Amazon product body offering denominations 50 and 100.
    Raises:
        None.
    """
    return {
        "id": K.AMAZON_PRODUCT_ID,
        "status": "ACTIVE",
        "amountRestrictions": {
            "minVoucherAmount": 50,
            "maxVoucherAmount": 1000,
            "denominations": [50, 100],
        },
        "howToUseInstructions": [
            {"instructions": ["Open the app", "Enter the code"]}
        ],
    }


def inactive_product_body(product_id: str) -> dict[str, Any]:
    """An INACTIVE reward product with no redemption path.

    Args:
        product_id: the product's id.
    Returns:
        The product body dict.
    Raises:
        None.
    """
    return {
        "id": product_id,
        "status": "INACTIVE",
        "amountRestrictions": None,
        "howToUseInstructions": [],
    }


def seed_reward_catalogue() -> dict[str, dict[str, Any]]:
    """One ACTIVE Amazon product plus every other reward product INACTIVE.

    Args:
        None.
    Returns:
        The reward catalogue, with Amazon ACTIVE and every other product
        INACTIVE.
    Raises:
        None.
    """
    catalogue = {
        pid: inactive_product_body(pid) for pid in K.ALL_REWARD_PRODUCT_IDS
    }
    catalogue[K.AMAZON_PRODUCT_ID] = amazon_product_body()
    return catalogue


def success_order(
    *,
    card_number: str = "4111-1111",
    card_pin: str = "9999",
    valid_till: str = "2027-12-31",
) -> dict[str, Any]:
    """A SUCCESS Hubble order carrying one voucher.

    Args:
        card_number: the voucher card number.
        card_pin: the voucher PIN.
        valid_till: the voucher expiry date.
    Returns:
        The order body dict.
    Raises:
        None.
    """
    return {
        "status": "SUCCESS",
        "vouchers": [
            {
                "cardNumber": card_number,
                "cardPin": card_pin,
                "validTill": valid_till,
            }
        ],
    }


def processing_order() -> dict[str, Any]:
    """A PROCESSING Hubble order with no vouchers yet.

    Args:
        None.
    Returns:
        A Hubble order body with status PROCESSING and no vouchers.
    Raises:
        None.
    """
    return {"status": "PROCESSING", "vouchers": []}


def empty_success_order() -> dict[str, Any]:
    """A SUCCESS Hubble order with no vouchers — the malformed-response case.

    Args:
        None.
    Returns:
        A Hubble order body with status SUCCESS and no vouchers.
    Raises:
        None.
    """
    return {"status": "SUCCESS", "vouchers": []}


def terminal_failure_order(status: str) -> dict[str, Any]:
    """A terminal (non-SUCCESS, non-PROCESSING) Hubble order with no vouchers.

    Args:
        status: the terminal status to report.
    Returns:
        The order body dict.
    Raises:
        None.
    """
    return {"status": status, "vouchers": []}


def forbidden_counters_present(data: dict[str, Any]) -> set[str]:
    """Stored-field names the Stored-derivations rule forbids.

    Args:
        data: a stored Firestore document.
    Returns:
        The forbidden field names actually present in data.
    Raises:
        None.
    """
    return set(data) & K.FORBIDDEN_STORED_COUNTERS


# ---------------------------------------------------------------------------
# HTTP helpers against the running user_service
# ---------------------------------------------------------------------------


class UsersApi:
    """Bearer-authenticated client for the running user_service."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """A bearer-authenticated wrapper around client, using the users service
        secret.

        Args:
            client: the httpx client requests are sent through.
        Returns:
            None.
        Raises:
            None.
        """
        self._client = client
        self.headers = {"Authorization": f"Bearer {K.USERS_SERVICE_SECRET}"}

    async def post(
        self, path: str, json: Optional[dict[str, Any]] = None
    ) -> httpx.Response:
        """POST path with the bearer auth header.

        Args:
            path: the request path.
            json: the request JSON body, or None.
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self._client.post(path, headers=self.headers, json=json)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """GET path with the bearer auth header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (params/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self._client.get(path, headers=self.headers, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """DELETE path with the bearer auth header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (params/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self._client.delete(path, headers=self.headers, **kwargs)

    async def put(
        self, path: str, json: Optional[dict[str, Any]] = None
    ) -> httpx.Response:
        """PUT path with the bearer auth header.

        Args:
            path: the request path.
            json: the request JSON body, or None.
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self._client.put(path, headers=self.headers, json=json)

    async def create_user(
        self, profile: dict[str, Any], texts: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Create a user via the internal API and return its profile JSON.

        Args:
            profile: the profile body (from student_profile/teacher_profile).
            texts: buffered pre-onboarding texts, or None.
        Returns:
            The created profile JSON.
        Raises:
            httpx.HTTPStatusError: the create call didn't return a success
                status.
        """
        response = await self.post(
            "/internal/users", json=create_user_body(profile, texts)
        )
        response.raise_for_status()
        return response.json()

    async def append(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        *,
        started_at_ms: Optional[int] = None,
        thread_key: str = K.WHATSAPP_THREAD_KEY,
    ) -> httpx.Response:
        """Append transcript messages for user_id's thread, raw response.

        Args:
            user_id: the user whose thread is being appended to.
            messages: the transcript rows to append.
            started_at_ms: pin to this session, or None to open/resolve one.
            thread_key: the thread to append to.
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self.post(
            f"/internal/users/{user_id}/threads/{thread_key}/transcript",
            json=append_body(messages, started_at_ms=started_at_ms),
        )


# ---------------------------------------------------------------------------
# Firestore readers (emulator)
# ---------------------------------------------------------------------------


async def user_doc(db, user_id: str) -> Optional[dict[str, Any]]:
    """The user's Firestore document, or None if it doesn't exist.

    Args:
        db: the Firestore client.
        user_id: the user to look up.
    Returns:
        Its document body, or None.
    Raises:
        None.
    """
    snap = await db.collection(K.USERS_COLLECTION).document(user_id).get()
    return snap.to_dict() if snap.exists else None


async def session_ref(
    db,
    user_id: str,
    started_at_ms: int,
    thread_key: str = K.WHATSAPP_THREAD_KEY,
):
    """The Firestore document reference for one session.

    Args:
        db: the Firestore client.
        user_id: the user the session belongs to.
        started_at_ms: the session's start time.
        thread_key: the thread the session is under.
    Returns:
        The document reference (not yet fetched).
    Raises:
        None.
    """
    return (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
        .document(str(started_at_ms))
    )


async def session_doc(
    db,
    user_id: str,
    started_at_ms: int,
    thread_key: str = K.WHATSAPP_THREAD_KEY,
) -> Optional[dict[str, Any]]:
    """One session's Firestore document, or None if it doesn't exist.

    Args:
        db: the Firestore client.
        user_id: the user the session belongs to.
        started_at_ms: the session's start time.
        thread_key: the thread the session is under.
    Returns:
        Its document body, or None.
    Raises:
        None.
    """
    snap = await (
        await session_ref(db, user_id, started_at_ms, thread_key)
    ).get()
    return snap.to_dict() if snap.exists else None


async def session_ids(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[str]:
    """Every session id under user_id's thread, sorted.

    Args:
        db: the Firestore client.
        user_id: the user whose sessions to list.
        thread_key: the thread to list sessions under.
    Returns:
        Sorted session ids.
    Raises:
        None.
    """
    ref = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
    )
    return sorted([doc.id async for doc in ref.stream()])


def _transcript_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    """Sort by session id, then by sequence (missing sequence sorts first).

    Args:
        row: a transcript row dict with _sessionId and optional sequence.
    Returns:
        The (session_id, sequence) sort key.
    Raises:
        None.
    """
    sequence = row.get("sequence")
    return (row["_sessionId"], sequence if sequence is not None else -1)


async def transcript_rows(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[dict[str, Any]]:
    """Every transcript row across all of user_id's sessions, sorted by session
    then sequence.

    Args:
        db: the Firestore client.
        user_id: the user whose transcript to read.
        thread_key: the thread to read.
    Returns:
        All rows, sorted.
    Raises:
        None.
    """
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
            rows.append(
                {**row.to_dict(), "_sessionId": session.id, "_rowId": row.id}
            )
    return sorted(rows, key=_transcript_sort_key)


async def gifting_docs(db, user_id: str) -> list[dict[str, Any]]:
    """Every gifting subcollection document under user_id.

    Args:
        db: the Firestore client.
        user_id: the user whose gifting docs to list.
    Returns:
        The documents, each with its id under "_id".
    Raises:
        None.
    """
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
    """The referrer's Firestore document, or None if it doesn't exist.

    Args:
        db: the Firestore client.
        handle: the referrer handle to look up.
    Returns:
        Its document body, or None.
    Raises:
        None.
    """
    snap = await db.collection(K.REFERRERS_COLLECTION).document(handle).get()
    return snap.to_dict() if snap.exists else None


async def campaign_docs(db, handle: str) -> list[dict[str, Any]]:
    """Every campaign document under a referrer handle.

    Args:
        db: the Firestore client.
        handle: the referrer handle whose campaigns to list.
    Returns:
        The documents, each with its id under "_id".
    Raises:
        None.
    """
    ref = (
        db.collection(K.REFERRERS_COLLECTION)
        .document(handle)
        .collection(K.CAMPAIGNS_SUBCOLLECTION)
    )
    return [{**snap.to_dict(), "_id": snap.id} async for snap in ref.stream()]


async def click_count(db, handle: str) -> int:
    """How many click documents exist under a referrer handle.

    Args:
        db: the Firestore client.
        handle: the referrer handle to count clicks for.
    Returns:
        The click count.
    Raises:
        None.
    """
    ref = (
        db.collection(K.REFERRERS_COLLECTION)
        .document(handle)
        .collection(K.CLICKS_SUBCOLLECTION)
    )
    return len([1 async for _ in ref.stream()])


async def enrollment_ids(db) -> list[str]:
    """Every enrollment document id, sorted.

    Args:
        db: the Firestore client.
    Returns:
        Sorted enrollment ids.
    Raises:
        None.
    """
    return sorted(
        [
            doc.id
            async for doc in db.collection(K.ENROLLMENTS_COLLECTION).stream()
        ]
    )


async def blocklist_exists(db, user_id: str) -> bool:
    """True if user_id has a blocklist document.

    Args:
        db: the Firestore client.
        user_id: the user to check.
    Returns:
        Whether the blocklist document exists.
    Raises:
        None.
    """
    snap = await db.collection(K.BLOCKLIST_COLLECTION).document(user_id).get()
    return snap.exists


async def onboarding_exists(db, sender_id: str) -> bool:
    """True if sender_id has an onboarding document.

    Args:
        db: the Firestore client.
        sender_id: the sender to check.
    Returns:
        Whether the onboarding document exists.
    Raises:
        None.
    """
    snap = (
        await db.collection(K.ONBOARDING_COLLECTION).document(sender_id).get()
    )
    return snap.exists
