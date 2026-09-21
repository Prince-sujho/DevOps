"""Firestore emulator + real user_service for persistence integration tests.

Emulator setup
--------------
Requires:

* ``gcloud`` on PATH with the ``cloud-firestore-emulator`` component
  (``gcloud components install cloud-firestore-emulator``).
* A JRE on PATH (the emulator is a Java process). Homebrew OpenJDK is often
  at ``/opt/homebrew/opt/openjdk``; export ``JAVA_HOME`` and prepend
  ``$JAVA_HOME/bin`` to ``PATH`` if ``java -version`` fails.

This session fixture starts one emulator on a free localhost port, sets
``FIRESTORE_EMULATOR_HOST`` and ``GOOGLE_CLOUD_PROJECT``, and yields the
``host:port``. Every test then DELETE-wipes
``/emulator/v1/projects/{project}/databases/(default)/documents`` so tests
do not share documents.

user_service is the real FastAPI app with the real Firestore repositories
bound to that emulator. Hubble is the real ``HubbleClient`` whose httpx
transport is replaced with ``HubbleHttpDouble`` (see ``hubble_http.py``) —
HTTP in, HTTP out; no client-class stub. Neo4j and GCS are in-process fakes
because this suite is not testing those systems.

Do not mock Firestore. A test that mocks a transaction and asserts the mock
was called does not belong here.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from typing import Iterator

import httpx
import pytest
import pytest_asyncio
import uvicorn
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import AsyncClient

from infra.firestore.repos.blocklist import BlocklistRepository
from infra.firestore.repos.campaigns import CampaignsRepository
from infra.firestore.repos.clicks import ClicksRepository
from infra.firestore.repos.enrollments import EnrollmentsRepository
from infra.firestore.repos.gifting import GiftingRepository
from infra.firestore.repos.onboarding import OnboardingRepository
from infra.firestore.repos.referrers import ReferrersRepository
from infra.firestore.repos.threads import ThreadsRepository
from infra.firestore.repos.users import UsersRepository
from infra.firestore import firestore_client
from infra.hubble import HubbleClient
from infra.platform.gcp import GcpIdentity
from user_service.app.src.access import AccessResolver
from user_service.app.src.api.context import AppState
from user_service.app.src.types import Settings

from . import constants as K
from .fakes import FakeGcsBucket, FakeGraphClient
from .helpers import UsersApi
from .hubble_http import HubbleHttpDouble


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_gcp_identity() -> GcpIdentity:
    return GcpIdentity(
        project=K.TEST_PROJECT,
        location=K.TEST_LOCATION,
        credentials=AnonymousCredentials(),
    )


def emulator_firestore_client() -> AsyncClient:
    return AsyncClient(project=K.TEST_PROJECT, credentials=AnonymousCredentials())


# --------------------------------------------------------------------------
# Emulator
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def firestore_emulator() -> Iterator[str]:
    """Run a local Firestore emulator for the whole session; yield its host:port."""
    if shutil.which("gcloud") is None:
        pytest.exit(
            "gcloud is required for tests/integration (Firestore emulator). "
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


# --------------------------------------------------------------------------
# user_service on uvicorn, real Firestore, Hubble via MockTransport
# --------------------------------------------------------------------------


class ServerThread:
    """One uvicorn server on its own thread and event loop."""

    def __init__(self, app, port: int) -> None:
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="user_service"
        )

    def start(self, timeout: float = 30.0) -> None:
        self._thread.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/health", timeout=1.0)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"user_service did not become healthy on port {self.port}")

    def stop(self, timeout: float = 10.0) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=timeout)


@pytest.fixture(scope="session")
def hubble_double() -> HubbleHttpDouble:
    return HubbleHttpDouble()


@pytest.fixture(scope="session")
def users_server(firestore_emulator: str, hubble_double: HubbleHttpDouble) -> Iterator[ServerThread]:
    """Boot the real user_service against the emulator for the whole session."""
    from user_service.app.src.api.app import app as users_app

    graph = FakeGraphClient()
    bucket = FakeGcsBucket(K.CONVERSATION_MEDIA_BUCKET)

    @asynccontextmanager
    async def lifespan(app):
        db = emulator_firestore_client()
        settings = Settings(
            gcp=test_gcp_identity(),
            users_service_secret=K.USERS_SERVICE_SECRET,
            user_id_hmac_secret=K.USERS_USER_ID_HMAC_SECRET,
            public_origin=K.PUBLIC_ORIGIN,
            hubble_api_origin="https://hubble.test",
            hubble_client_id="test-hubble-client-id",
            hubble_client_secret="test-hubble-client-secret",
            conversation_media_bucket=K.CONVERSATION_MEDIA_BUCKET,
            neo4j_uri="bolt://neo4j.invalid:7687",
            neo4j_user="test-neo4j-user",
            neo4j_password="test-neo4j-password",
        )
        users = UsersRepository(db, settings.user_id_hmac_secret)
        blocklist = BlocklistRepository(db)
        hubble = HubbleClient(
            origin=settings.hubble_api_origin,
            client_id=settings.hubble_client_id,
            client_secret=settings.hubble_client_secret,
        )
        # Transport-layer substitution only: same HubbleClient, scripted HTTP.
        original_http = hubble._http
        hubble._http = httpx.AsyncClient(
            base_url="https://hubble.test",
            transport=httpx.MockTransport(hubble_double.handler),
            timeout=None,
        )
        await original_http.aclose()
        app.state.ctx = AppState(
            db=db,
            settings=settings,
            users=users,
            enrollments=EnrollmentsRepository(db),
            threads=ThreadsRepository(db),
            referrers=ReferrersRepository(db),
            clicks=ClicksRepository(db),
            campaigns=CampaignsRepository(db),
            blocklist=blocklist,
            gifting=GiftingRepository(db),
            onboarding=OnboardingRepository(db),
            hubble=hubble,
            access=AccessResolver(users=users, blocklist=blocklist),
            graph=graph,
            media_bucket=bucket,
        )
        yield
        await hubble.close()

    users_app.router.lifespan_context = lifespan
    server = ServerThread(users_app, free_port())
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(autouse=True)
def clean_state(firestore_emulator: str, hubble_double: HubbleHttpDouble, users_server: ServerThread) -> Iterator[None]:
    """Wipe every Firestore document and reset the Hubble double before each test."""
    url = (
        f"http://{firestore_emulator}/emulator/v1/projects/{K.TEST_PROJECT}"
        "/databases/(default)/documents"
    )
    response = httpx.delete(url, timeout=30.0)
    response.raise_for_status()
    hubble_double.reset()
    yield


@pytest_asyncio.fixture
async def db(firestore_emulator: str):
    """A fresh emulator-bound Firestore client on this test's event loop."""
    client = emulator_firestore_client()
    yield client
    client.close()


@pytest_asyncio.fixture
async def api(users_server: ServerThread) -> UsersApi:
    async with httpx.AsyncClient(base_url=users_server.base_url, timeout=60.0) as client:
        yield UsersApi(client)
