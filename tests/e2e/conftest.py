"""Session fixtures: local Firestore emulator, the three real services, fakes."""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import signal
import socket
import subprocess
import time
from typing import Any, Iterator, Optional

import httpx
import pytest
import pytest_asyncio

from . import constants as K
from . import payloads
from .servers import Harness, emulator_firestore_client, free_port, start_harness


# --------------------------------------------------------------------------
# Firestore emulator
# --------------------------------------------------------------------------


def _port_open(host: str, port: int) -> bool:
    """Whether a TCP connect to host:port succeeds right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    """Run a local Firestore emulator for the whole session; yield its host:port."""
    if shutil.which("gcloud") is None:
        pytest.exit(
            "gcloud is required for the e2e suite (Firestore emulator). "
            "Install the Google Cloud SDK and the cloud-firestore-emulator component.",
            returncode=1,
        )
    port = free_port()
    host_port = f"127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            "gcloud",
            "emulators",
            "firestore",
            "start",
            f"--host-port={host_port}",
            f"--project={K.TEST_PROJECT}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            pytest.exit(f"Firestore emulator exited early:\n{output}", returncode=1)
        if _port_open("127.0.0.1", port):
            break
        time.sleep(0.2)
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        pytest.exit(f"Firestore emulator never listened on {host_port}", returncode=1)

    os.environ["FIRESTORE_EMULATOR_HOST"] = host_port
    os.environ["GOOGLE_CLOUD_PROJECT"] = K.TEST_PROJECT
    os.environ["GOOGLE_CLOUD_LOCATION"] = K.TEST_LOCATION
    try:
        yield host_port
    finally:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        process.wait(timeout=20)


@pytest.fixture(scope="session")
def harness(firestore_emulator: str) -> Iterator[Harness]:
    """Boot the three real services once for the session."""
    running = start_harness()
    try:
        yield running
    finally:
        running.adapter.stop()
        running.text_agent.stop()
        running.users.stop()


@pytest.fixture(autouse=True)
def clean_state(firestore_emulator: str, harness: Harness) -> Iterator[None]:
    """Wipe every Firestore document and reset every fake before each test."""
    url = (
        f"http://{firestore_emulator}/emulator/v1/projects/{K.TEST_PROJECT}"
        "/databases/(default)/documents"
    )
    response = httpx.delete(url, timeout=30.0)
    response.raise_for_status()
    harness.fakes.reset()
    yield


@pytest.fixture
def fakes(harness: Harness):
    """The harness fakes, already reset for this test."""
    return harness.fakes


@pytest.fixture
def whatsapp(harness: Harness):
    """The fake Meta Graph API client behind whatsapp_adapter."""
    return harness.fakes.whatsapp


@pytest.fixture
def openai(harness: Harness):
    """The fake OpenAI Responses client behind text_agent."""
    return harness.fakes.openai


@pytest.fixture
def hubble(harness: Harness):
    """The fake Hubble client behind user_service."""
    return harness.fakes.hubble


@pytest_asyncio.fixture
async def db(firestore_emulator: str):
    """A fresh emulator-bound Firestore client on this test's event loop."""
    client = emulator_firestore_client()
    yield client
    client.close()


# --------------------------------------------------------------------------
# Service clients
# --------------------------------------------------------------------------


class AdapterClient:
    """Posts signed webhooks at the real whatsapp_adapter HTTP port."""

    def __init__(self, base_url: str) -> None:
        """Bind to the running adapter."""
        self.base_url = base_url

    async def post_webhook(
        self,
        payload: dict[str, Any],
        *,
        secret: str = K.WHATSAPP_APP_SECRET,
        tamper: bool = False,
    ) -> httpx.Response:
        """Sign and POST one webhook body; `tamper` mutates the body after signing."""
        raw = payloads.encode(payload)
        signature = payloads.sign(raw, secret)
        sent = raw.replace(b'"object"', b'"objecT"', 1) if tamper else raw
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            return await client.post(
                "/webhook",
                content=sent,
                headers={
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                },
            )


class InternalClient:
    """Calls one service's bearer-guarded internal surface."""

    def __init__(self, base_url: str, secret: str) -> None:
        """Bind to a running service and its internal secret."""
        self.base_url = base_url
        self._headers = {"Authorization": f"Bearer {secret}"}

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Call one internal path under the bearer header."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            return await client.request(method, path, headers=self._headers, **kwargs)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)


@pytest.fixture
def adapter(harness: Harness) -> AdapterClient:
    """HTTP client for the running whatsapp_adapter."""
    return AdapterClient(harness.adapter.base_url)


@pytest.fixture
def users_api(harness: Harness) -> InternalClient:
    """HTTP client for user_service's /internal surface."""
    return InternalClient(harness.users.base_url, K.USERS_SERVICE_SECRET)


@pytest.fixture
def text_agent_api(harness: Harness) -> InternalClient:
    """HTTP client for text_agent's internal surface."""
    return InternalClient(harness.text_agent.base_url, K.TEXT_AGENT_SERVICE_SECRET)


# --------------------------------------------------------------------------
# Firestore read helpers
# --------------------------------------------------------------------------


def derive_user_id(phone: str) -> str:
    """Recompute user_service's deterministic opaque user id for one phone."""
    digest = hmac.new(
        key=K.USERS_USER_ID_HMAC_SECRET.encode("utf-8"),
        msg=phone.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest[:32]


async def collection_ids(db, path: list[str]) -> list[str]:
    """Document ids under one collection path, as a sorted list."""
    ref = db.collection(path[0])
    for index in range(1, len(path)):
        ref = ref.document(path[index]) if index % 2 else ref.collection(path[index])
    return sorted([doc.id async for doc in ref.stream()])


async def session_ids(db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY) -> list[str]:
    """Every session document id for one user's thread."""
    ref = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
    )
    return sorted([doc.id async for doc in ref.stream()])


async def session_doc(
    db, user_id: str, started_at_ms: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> dict[str, Any]:
    """One session document body."""
    ref = (
        db.collection(K.USERS_COLLECTION)
        .document(user_id)
        .collection(K.THREADS_SUBCOLLECTION)
        .document(thread_key)
        .collection(K.SESSIONS_SUBCOLLECTION)
        .document(started_at_ms)
    )
    return (await ref.get()).to_dict()


async def transcript_rows(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[dict[str, Any]]:
    """Every transcript row across every session of one thread, in sequence order."""
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
            rows.append({**row.to_dict(), "_sessionId": session.id})
    return sorted(rows, key=lambda row: (row["_sessionId"], row.get("sequence") or 0))


async def all_transcript_row_count(db) -> int:
    """Total transcript rows anywhere in the database."""
    total = 0
    async for user in db.collection(K.USERS_COLLECTION).stream():
        async for thread in user.reference.collection(K.THREADS_SUBCOLLECTION).stream():
            async for session in thread.reference.collection(
                K.SESSIONS_SUBCOLLECTION
            ).stream():
                async for _ in session.reference.collection(
                    K.SESSION_TRANSCRIPT_SUBCOLLECTION
                ).stream():
                    total += 1
    return total


async def pending_action(db, sender_id: str) -> Optional[dict[str, Any]]:
    """One sender's stored pending onboarding action, or None."""
    doc = await db.collection(K.ONBOARDING_COLLECTION).document(sender_id).get()
    return doc.to_dict() if doc.exists else None


async def user_doc(db, user_id: str) -> Optional[dict[str, Any]]:
    """One user document body, or None."""
    doc = await db.collection(K.USERS_COLLECTION).document(user_id).get()
    return doc.to_dict() if doc.exists else None
