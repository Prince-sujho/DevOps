"""Session fixtures: local Firestore emulator, the three real services,
fakes."""

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
from .servers import (
    Harness,
    emulator_firestore_client,
    free_port,
    start_harness,
)


# --------------------------------------------------------------------------
# Firestore emulator
# --------------------------------------------------------------------------


def _port_open(host: str, port: int) -> bool:
    """Whether a TCP connect to host:port succeeds right now.

    Args:
        host: hostname to open a TCP connection to.
        port: TCP port to connect to.
    Returns:
        True when a TCP connection to host and port succeeds.
    Raises:
        None.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _spawn_emulator(host_port: str) -> subprocess.Popen:
    """Start the gcloud Firestore emulator process; not yet listening.

    Args:
        host_port: the host:port to bind the emulator to.
    Returns:
        The spawned process.
    Raises:
        None.
    """
    return subprocess.Popen(
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


def _wait_for_emulator(
    process: subprocess.Popen, port: int, host_port: str
) -> None:
    """Block until the emulator is listening; pytest.exit on early death or
    timeout.

    Args:
        process: the spawned emulator process.
        port: the port it should be listening on.
        host_port: the host:port, for error messages.
    Returns:
        None.
    Raises:
        None — failures call pytest.exit directly.
    """
    deadline = time.time() + 90
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            pytest.exit(
                f"Firestore emulator exited early:\n{output}", returncode=1
            )
        if _port_open("127.0.0.1", port):
            return
        time.sleep(0.2)
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    pytest.exit(
        f"Firestore emulator never listened on {host_port}", returncode=1
    )


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    """Run a local Firestore emulator for the whole session; yield its
    host:port.

    Args:
        None.
    Returns:
        The emulator's host:port.
    Raises:
        None.
    """
    if shutil.which("gcloud") is None:
        pytest.exit(
            "gcloud is required for the e2e suite (Firestore emulator). "
            "Install the Google Cloud SDK and the cloud-firestore-emulator "
            "component.",
            returncode=1,
        )
    port = free_port()
    host_port = f"127.0.0.1:{port}"
    process = _spawn_emulator(host_port)
    _wait_for_emulator(process, port, host_port)

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
    """Boot the three real services once for the session.

    Args:
        firestore_emulator: the session Firestore emulator's host:port.
        Yields:
        The running Harness.
    Returns:
        The booted Harness.
    Raises:
        None.
    """
    running = start_harness()
    try:
        yield running
    finally:
        running.adapter.stop()
        running.text_agent.stop()
        running.users.stop()


@pytest.fixture(autouse=True)
def clean_state(firestore_emulator: str, harness: Harness) -> Iterator[None]:
    """Wipe every Firestore document and reset every fake before each test.

    Args:
        firestore_emulator: the session Firestore emulator's host:port.
        harness: the running three-service harness.
    Returns:
        None.
    Raises:
        None.
    """
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
    """The harness fakes, already reset for this test.

    Args:
        harness: the running harness whose fakes are reset and returned.
    Returns:
        The harness fakes, already reset for this test.
    Raises:
        None.
    """
    return harness.fakes


@pytest.fixture
def whatsapp(harness: Harness):
    """The fake Meta Graph API client behind whatsapp_adapter.

    Args:
        harness: the running three-service harness.
    Returns:
        The fake WhatsApp client.
    Raises:
        None.
    """
    return harness.fakes.whatsapp


@pytest.fixture
def openai(harness: Harness):
    """The fake OpenAI Responses client behind text_agent.

    Args:
        harness: the running three-service harness.
    Returns:
        The fake OpenAI client.
    Raises:
        None.
    """
    return harness.fakes.openai


@pytest.fixture
def hubble(harness: Harness):
    """The fake Hubble client behind user_service.

    Args:
        harness: the running three-service harness.
    Returns:
        The fake Hubble client.
    Raises:
        None.
    """
    return harness.fakes.hubble


@pytest_asyncio.fixture
async def db(firestore_emulator: str):
    """A fresh emulator-bound Firestore client on this test's event loop.

    Args:
        firestore_emulator: the session Firestore emulator's host:port.
        Yields:
        The Firestore client.
    Returns:
        A Firestore client bound to the emulator on this test's event loop.
    Raises:
        None.
    """
    client = emulator_firestore_client()
    yield client
    client.close()


# --------------------------------------------------------------------------
# Service clients
# --------------------------------------------------------------------------


class AdapterClient:
    """Posts signed webhooks at the real whatsapp_adapter HTTP port."""

    def __init__(self, base_url: str) -> None:
        """Bind to the running adapter.

        Args:
            base_url: the running whatsapp_adapter's base URL.
        Returns:
            None.
        Raises:
            None.
        """
        self.base_url = base_url

    async def post_webhook(
        self,
        payload: dict[str, Any],
        *,
        secret: str = K.WHATSAPP_APP_SECRET,
        tamper: bool = False,
    ) -> httpx.Response:
        """Sign and POST one webhook body; `tamper` mutates the body after
        signing.

        Args:
            payload: the webhook body to send.
            secret: the app secret to sign with.
            tamper: if True, corrupt the body after signing (signature stays
                valid for the original).
        Returns:
            The raw response.
        Raises:
            None.
        """
        raw = payloads.encode(payload)
        signature = payloads.sign(raw, secret)
        sent = raw.replace(b'"object"', b'"objecT"', 1) if tamper else raw
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=30.0
        ) as client:
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
        """Bind to a running service and its internal secret.

        Args:
            base_url: the running service's base URL.
            secret: the service's internal bearer secret.
        Returns:
            None.
        Raises:
            None.
        """
        self.base_url = base_url
        self._headers = {"Authorization": f"Bearer {secret}"}

    async def request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Call one internal path under the bearer header.

        Args:
            method: the HTTP method.
            path: the request path.
            kwargs: passed through to httpx (json/params/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=60.0
        ) as client:
            return await client.request(
                method, path, headers=self._headers, **kwargs
            )

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """GET path under the bearer header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (params/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        """POST path under the bearer header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (json/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        """PUT path under the bearer header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (json/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """DELETE path under the bearer header.

        Args:
            path: the request path.
            kwargs: passed through to httpx (params/etc).
        Returns:
            The raw response.
        Raises:
            None.
        """
        return await self.request("DELETE", path, **kwargs)


@pytest.fixture
def adapter(harness: Harness) -> AdapterClient:
    """HTTP client for the running whatsapp_adapter.

    Args:
        harness: the running three-service harness.
    Returns:
        The AdapterClient.
    Raises:
        None.
    """
    return AdapterClient(harness.adapter.base_url)


@pytest.fixture
def users_api(harness: Harness) -> InternalClient:
    """HTTP client for user_service's /internal surface.

    Args:
        harness: the running three-service harness.
    Returns:
        The InternalClient.
    Raises:
        None.
    """
    return InternalClient(harness.users.base_url, K.USERS_SERVICE_SECRET)


@pytest.fixture
def text_agent_api(harness: Harness) -> InternalClient:
    """HTTP client for text_agent's internal surface.

    Args:
        harness: the running three-service harness.
    Returns:
        The InternalClient.
    Raises:
        None.
    """
    return InternalClient(
        harness.text_agent.base_url, K.TEXT_AGENT_SERVICE_SECRET
    )


# --------------------------------------------------------------------------
# Firestore read helpers
# --------------------------------------------------------------------------


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


async def collection_ids(db, path: list[str]) -> list[str]:
    """Document ids under one collection path, as a sorted list.

    Args:
        db: the Firestore client.
        path: alternating collection/document segments.
    Returns:
        Sorted document ids.
    Raises:
        None.
    """
    ref = db.collection(path[0])
    for index in range(1, len(path)):
        ref = (
            ref.document(path[index])
            if index % 2
            else ref.collection(path[index])
        )
    return sorted([doc.id async for doc in ref.stream()])


async def session_ids(
    db, user_id: str, thread_key: str = K.WHATSAPP_THREAD_KEY
) -> list[str]:
    """Every session document id for one user's thread.

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


async def session_doc(
    db,
    user_id: str,
    started_at_ms: str,
    thread_key: str = K.WHATSAPP_THREAD_KEY,
) -> dict[str, Any]:
    """One session document body.

    Args:
        db: the Firestore client.
        user_id: the user the session belongs to.
        started_at_ms: the session's start time.
        thread_key: the thread the session is under.
    Returns:
        Its document body.
    Raises:
        None.
    """
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
    """Every transcript row across every session of one thread, in sequence
    order.

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
            rows.append({**row.to_dict(), "_sessionId": session.id})
    return sorted(
        rows, key=lambda row: (row["_sessionId"], row.get("sequence") or 0)
    )


async def all_transcript_row_count(db) -> int:
    """Total transcript rows anywhere in the database.

    Args:
        db: the Firestore client.
    Returns:
        The total row count.
    Raises:
        None.
    """
    total = 0
    async for user in db.collection(K.USERS_COLLECTION).stream():
        async for thread in user.reference.collection(
            K.THREADS_SUBCOLLECTION
        ).stream():
            async for session in thread.reference.collection(
                K.SESSIONS_SUBCOLLECTION
            ).stream():
                async for _ in session.reference.collection(
                    K.SESSION_TRANSCRIPT_SUBCOLLECTION
                ).stream():
                    total += 1
    return total


async def pending_action(db, sender_id: str) -> Optional[dict[str, Any]]:
    """One sender's stored pending onboarding action, or None.

    Args:
        db: the Firestore client.
        sender_id: the sender to look up.
    Returns:
        Its document body, or None.
    Raises:
        None.
    """
    doc = await db.collection(K.ONBOARDING_COLLECTION).document(sender_id).get()
    return doc.to_dict() if doc.exists else None


async def user_doc(db, user_id: str) -> Optional[dict[str, Any]]:
    """One user document body, or None.

    Args:
        db: the Firestore client.
        user_id: the user to look up.
    Returns:
        Its document body, or None.
    Raises:
        None.
    """
    doc = await db.collection(K.USERS_COLLECTION).document(user_id).get()
    return doc.to_dict() if doc.exists else None
