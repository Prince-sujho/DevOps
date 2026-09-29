"""Real uvicorn servers for the three Sujho services, wired for e2e tests.

Each service keeps its real FastAPI app, real routes, real repositories and real
Firestore (against the local emulator). Only the genuinely external systems are
substituted, by replacing each app's lifespan with a test lifespan of the same
shape before the server starts.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from contextlib import asynccontextmanager
from functools import partial
from dataclasses import dataclass
from typing import Optional

import httpx
import uvicorn
from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import AsyncClient

from infra.clients.text_agent import TextAgentClient
from infra.clients.users.client import UsersClient
from infra.firestore import UsageRepository
from infra.firestore.repos.blocklist import BlocklistRepository
from infra.firestore.repos.campaigns import CampaignsRepository
from infra.firestore.repos.clicks import ClicksRepository
from infra.firestore.repos.enrollments import EnrollmentsRepository
from infra.firestore.repos.gifting import GiftingRepository
from infra.firestore.repos.message_claims import MessageClaimsRepository
from infra.firestore.repos.onboarding import OnboardingRepository
from infra.firestore.repos.referrers import ReferrersRepository
from infra.firestore.repos.threads import ThreadsRepository
from infra.firestore.repos.users import UsersRepository
from infra.platform.gcp import GcpIdentity
from infra.skills import SkillLibrary

from . import constants as K
from .fakes import (
    FakeAudioTranscriber,
    FakeDocumentWorkerClient,
    FakeEmbeddingClient,
    FakeGcsBucket,
    FakeGraphClient,
    FakeHubbleClient,
    FakeOpenAIImageClient,
    FakeOpenAIResponsesClient,
    FakeWhatsAppClient,
)


def free_port() -> int:
    """Reserve one free localhost TCP port and release it.

    Args:
        None.
    Returns:
        The ephemeral port the socket was bound to.
    Raises:
        None.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_gcp_identity() -> GcpIdentity:
    """GCP identity pointing at the emulator project with anonymous credentials.

    Args:
        None.
    Returns:
        A GcpIdentity for the test project with anonymous credentials.
    Raises:
        None.
    """
    return GcpIdentity(
        project=K.TEST_PROJECT,
        location=K.TEST_LOCATION,
        credentials=AnonymousCredentials(),
    )


def emulator_firestore_client() -> AsyncClient:
    """Async Firestore client bound to the local emulator
    (FIRESTORE_EMULATOR_HOST).

    Args:
        None.
    Returns:
        A Firestore AsyncClient for the test project with anonymous credentials.
    Raises:
        None.
    """
    return AsyncClient(
        project=K.TEST_PROJECT, credentials=AnonymousCredentials()
    )


@dataclass
class Fakes:
    """Every fake in the harness, so tests can inspect and reset them."""

    whatsapp: FakeWhatsAppClient
    openai: FakeOpenAIResponsesClient
    openai_images: FakeOpenAIImageClient
    transcriber: FakeAudioTranscriber
    embeddings: FakeEmbeddingClient
    agent_graph: FakeGraphClient
    users_graph: FakeGraphClient
    hubble: FakeHubbleClient
    agent_bucket: FakeGcsBucket
    users_bucket: FakeGcsBucket
    adapter_bucket: FakeGcsBucket
    documents: FakeDocumentWorkerClient

    def reset(self) -> None:
        """Clear every fake's recorded state between tests.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        for fake in (
            self.whatsapp,
            self.openai,
            self.openai_images,
            self.transcriber,
            self.embeddings,
            self.agent_graph,
            self.users_graph,
            self.hubble,
            self.agent_bucket,
            self.users_bucket,
            self.adapter_bucket,
            self.documents,
        ):
            fake.reset()


class ServerThread:
    """One uvicorn server running on its own thread and event loop."""

    def __init__(self, app, port: int, name: str) -> None:
        """Bind a configured uvicorn server to a fixed localhost port.

        Args:
            app: the FastAPI app to serve.
            port: the localhost port to bind.
            name: this server's name, used for the thread and error messages.
        Returns:
            None.
        Raises:
            None.
        """
        self.port = port
        self.name = name
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name=name
        )

    def start(self, timeout: float = 30.0) -> None:
        """Start the thread and block until the port serves /health.

        Args:
            timeout: seconds to wait for /health before giving up.
        Returns:
            None.
        Raises:
            RuntimeError: the service never became healthy within timeout.
        """
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
        raise RuntimeError(
            f"{self.name} did not become healthy on port {self.port}"
        )

    def stop(self, timeout: float = 10.0) -> None:
        """Ask uvicorn to exit and join the thread.

        Args:
            timeout: seconds to wait for the thread to join.
        Returns:
            None.
        Raises:
            None.
        """
        self._server.should_exit = True
        self._thread.join(timeout=timeout)


def _user_service_test_settings():
    """Test Settings for user_service, bound to the emulator project.

    Args:
        None.
    Returns:
        Test Settings bound to the emulator project.
    Raises:
        None.
    """
    from user_service.app.src.types import Settings

    return Settings(
        gcp=test_gcp_identity(),
        users_service_secret=K.USERS_SERVICE_SECRET,
        user_id_hmac_secret=K.USERS_USER_ID_HMAC_SECRET,
        public_origin=K.PUBLIC_ORIGIN,
        hubble_api_origin="https://hubble.invalid",
        hubble_client_id="test-hubble-client-id",
        hubble_client_secret="test-hubble-client-secret",
        conversation_media_bucket=K.CONVERSATION_MEDIA_BUCKET,
        neo4j_uri="bolt://neo4j.invalid:7687",
        neo4j_user="test-neo4j-user",
        neo4j_password="test-neo4j-password",
    )


@asynccontextmanager
async def _user_service_lifespan(app, fakes: Fakes):
    """Wire real Firestore repos plus faked Hubble/Neo4j/GCS into AppState.

    Args:
        app: the FastAPI app whose state.ctx is being set.
        fakes: the harness's shared fake collaborators.
    Returns:
        None.
    Raises:
        None.
    """
    from user_service.app.src.access import AccessResolver
    from user_service.app.src.api.context import AppState

    db = emulator_firestore_client()
    settings = _user_service_test_settings()
    users = UsersRepository(db, settings.user_id_hmac_secret)
    blocklist = BlocklistRepository(db)
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
        hubble=fakes.hubble,
        access=AccessResolver(users=users, blocklist=blocklist),
        graph=fakes.users_graph,
        media_bucket=fakes.users_bucket,
    )
    yield


def build_user_service_lifespan(fakes: Fakes):
    """Test lifespan for user_service: real Firestore repos, faked
    Hubble/Neo4j/GCS.

    Args:
        fakes: the harness's shared fake collaborators.
    Returns:
        The lifespan context manager to install on the app's router.
    Raises:
        None.
    """
    return partial(_user_service_lifespan, fakes=fakes)


@asynccontextmanager
async def _text_agent_lifespan(app, fakes: Fakes, users_base_url: str):
    """Wire the real RespondService against faked OpenAI/Neo4j/Gemini clients.

    Args:
        app: the FastAPI app whose state.ctx is being set.
        fakes: the harness's shared fake collaborators.
        users_base_url: the running user_service's base URL.
    Returns:
        None.
    Raises:
        None.
    """
    from infra.llm.oai.runtime import OpenAIRuntime
    from text_agent.app.src.api.context import AppState
    from text_agent.app.src.services import RespondService
    from text_agent.app.src.services import respond as respond_mod

    users = UsersClient(
        base_url=users_base_url, service_secret=K.USERS_SERVICE_SECRET
    )
    respond_mod.OpenAIResponsesClient = lambda runtime, usage, service_tier: (
        fakes.openai
    )
    runtime = OpenAIRuntime(api_key="test-openai-api-key")
    respond = RespondService(
        runtime=runtime,
        users=users,
        media_bucket=fakes.agent_bucket,
        documents=fakes.documents,
        skills=SkillLibrary.load(),
        graph=fakes.agent_graph,
        embeddings=fakes.embeddings,
    )
    app.state.ctx = AppState(
        respond=respond, text_agent_service_secret=K.TEXT_AGENT_SERVICE_SECRET
    )
    yield
    await users.close()
    await runtime.close()


def build_text_agent_lifespan(fakes: Fakes, users_base_url: str):
    """Test lifespan for text_agent: real RespondService, faked
    OpenAI/Neo4j/Gemini.

    Args:
        fakes: the harness's shared fake collaborators.
        users_base_url: the running user_service's base URL.
    Returns:
        The lifespan context manager to install on the app's router.
    Raises:
        None.
    """
    return partial(
        _text_agent_lifespan, fakes=fakes, users_base_url=users_base_url
    )


class FakeConversionsReporter:
    """No-op stand-in for the real Meta Conversions API reporter."""

    def report(self, user, result) -> None:
        """Discard the conversion event.

        Args:
            user: the user the conversion is attributed to (ignored).
            result: the append result the conversion is derived from (ignored).
        Returns:
            None.
        Raises:
            None.
        """
        return None

    async def close(self) -> None:
        """No-op close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return None


def _adapter_flow_settings():
    """Fake student/teacher flow ids and a throwaway flows private key.

    Args:
        None.
    Returns:
        Flow settings with the test flow ids and a throwaway private key.
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.types.settings import (
        FlowIds,
        FlowSettings,
        PersonaFlowIds,
    )

    return FlowSettings(
        ids=FlowIds(
            student=PersonaFlowIds(
                onboarding=K.STUDENT_ONBOARDING_FLOW_ID,
                doc=K.STUDENT_DOC_FLOW_ID,
                grade=K.STUDENT_GRADE_FLOW_ID,
            ),
            teacher=PersonaFlowIds(
                onboarding=K.TEACHER_ONBOARDING_FLOW_ID,
                doc=K.TEACHER_DOC_FLOW_ID,
                grade=K.TEACHER_GRADE_FLOW_ID,
            ),
        ),
        private_key_pem="-----BEGIN TEST KEY-----\nunused\n-----END TEST "
        "KEY-----",
    )


def _whatsapp_test_settings():
    """WhatsApp settings filled from the e2e test constants.

    Args:
        None.
    Returns:
        The WhatsAppSettings.
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.types.settings import WhatsAppSettings

    return WhatsAppSettings(
        verify_token=K.WHATSAPP_VERIFY_TOKEN,
        access_token=K.WHATSAPP_ACCESS_TOKEN,
        phone_number_id=K.WHATSAPP_PHONE_NUMBER_ID,
        api_version=K.WHATSAPP_API_VERSION,
        app_secret=K.WHATSAPP_APP_SECRET,
        public_number=K.PUBLIC_WHATSAPP_NUMBER,
    )


def _adapter_test_settings(text_agent_base_url: str, users_base_url: str):
    """Test Settings for whatsapp_adapter: real shape, fake flow
    ids/keys/tokens.

    Args:
        text_agent_base_url: the running text_agent's base URL.
        users_base_url: the running user_service's base URL.
    Returns:
        The Settings.
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.types import Settings
    from whatsapp_adapter.app.src.types.settings import (
        ConversionsSettings,
        ServiceClientSettings,
    )

    return Settings(
        gcp=test_gcp_identity(),
        openai_api_key="test-openai-api-key",
        whatsapp=_whatsapp_test_settings(),
        conversions=ConversionsSettings(
            access_token="test-capi-token",
            dataset_id="test-capi-dataset",
            page_id="test-capi-page",
        ),
        flows=_adapter_flow_settings(),
        text_agent=ServiceClientSettings(
            api_origin=text_agent_base_url,
            service_secret=K.TEXT_AGENT_SERVICE_SECRET,
        ),
        users=ServiceClientSettings(
            api_origin=users_base_url, service_secret=K.USERS_SERVICE_SECRET
        ),
        conversation_media_bucket=K.CONVERSATION_MEDIA_BUCKET,
    )


def _build_adapter_clients(settings):
    """The three outbound clients the turn loop calls through: text_agent,
    users, OpenAI.

    Args:
        settings: the adapter's test Settings.
    Returns:
        (text_agent, users, openai_runtime).
    Raises:
        None.
    """
    from infra.llm.oai.runtime import OpenAIRuntime

    text_agent = TextAgentClient(
        base_url=settings.text_agent.api_origin,
        service_secret=settings.text_agent.service_secret,
    )
    users = UsersClient(
        base_url=settings.users.api_origin,
        service_secret=settings.users.service_secret,
    )
    openai_runtime = OpenAIRuntime(api_key=settings.openai_api_key)
    return text_agent, users, openai_runtime


def _reply_delivery(whatsapp, flows, confirmations, users, fakes: Fakes):
    """Reply delivery wired to the fake WhatsApp client and adapter bucket.

    Args:
        whatsapp: the fake WhatsApp client.
        flows: the flow launcher.
        confirmations: the delivery confirmations sink.
        users: the UsersClient bound to the running user_service.
        fakes: the harness's shared fake collaborators.
    Returns:
        The ReplyDelivery.
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.output import ReplyDelivery

    return ReplyDelivery(
        whatsapp=whatsapp,
        flows=flows,
        confirmations=confirmations,
        users=users,
        media_bucket=fakes.adapter_bucket,
    )


def _build_adapter_runner(
    db, fakes: Fakes, settings, users, text_agent, openai_runtime
):
    """Wire the reply-side objects (flows, inputs, delivery, runner) behind the
    fakes.

    Args:
        db: the emulator-bound Firestore client.
        fakes: the harness's shared fake collaborators.
        settings: the adapter's test Settings.
        users: the UsersClient bound to the running user_service.
        text_agent: the TextAgentClient bound to the running text_agent.
        openai_runtime: the OpenAIRuntime used for media transcription.
    Returns:
        (runner, flows, inputs, pending, confirmations).
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.input import FlowUploadFetcher, MediaFetcher
    from whatsapp_adapter.app.src.output import (
        DeliveryConfirmations,
        FlowLauncher,
    )
    from whatsapp_adapter.app.src.service import AgentInputBuilder, ReplyRunner

    whatsapp = fakes.whatsapp
    flows = FlowLauncher(whatsapp, settings.flows.ids)
    inputs = AgentInputBuilder(
        fakes.adapter_bucket,
        MediaFetcher(whatsapp, openai_runtime),
        FlowUploadFetcher(whatsapp),
    )
    pending = OnboardingRepository(db)
    confirmations = DeliveryConfirmations()
    whatsapp.bind_confirmations(confirmations)
    delivery = _reply_delivery(whatsapp, flows, confirmations, users, fakes)
    runner = ReplyRunner(
        text_agent=text_agent,
        delivery=delivery,
        users=users,
        whatsapp=whatsapp,
        usage=UsageRepository(db),
        conversions=FakeConversionsReporter(),
    )
    return runner, flows, inputs, pending, confirmations


def _build_adapter_turn_loop(
    db, fakes: Fakes, settings, users, text_agent, openai_runtime
):
    """Wire the real turn loop (gate, onboarding, runner, delivery) behind the
    fakes.

    Args:
        db: the emulator-bound Firestore client.
        fakes: the harness's shared fake collaborators.
        settings: the adapter's test Settings.
        users: the UsersClient bound to the running user_service.
        text_agent: the TextAgentClient bound to the running text_agent.
        openai_runtime: the OpenAIRuntime used for media transcription.
    Returns:
        (turn_loop, confirmations).
    Raises:
        None.
    """
    from whatsapp_adapter.app.src.service import (
        OnboardingCoordinator,
        TurnGate,
        TurnLoop,
    )

    whatsapp = fakes.whatsapp
    runner, flows, inputs, pending, confirmations = _build_adapter_runner(
        db, fakes, settings, users, text_agent, openai_runtime
    )
    onboarding = OnboardingCoordinator(
        users=users,
        whatsapp=whatsapp,
        flows=flows,
        inputs=inputs,
        pending=pending,
    )
    gate = TurnGate(
        users=users,
        whatsapp=whatsapp,
        inputs=inputs,
        onboarding=onboarding,
        pending=pending,
    )
    return TurnLoop(gate.process, runner), confirmations


@asynccontextmanager
async def _adapter_lifespan(
    app, fakes: Fakes, text_agent_base_url: str, users_base_url: str
):
    """Wire the real turn loop against faked WhatsApp/OpenAI/text-agent/users
    clients.

    Args:
        app: the FastAPI app whose state.ctx is being set.
        fakes: the harness's shared fake collaborators.
        text_agent_base_url: the running text_agent's base URL.
        users_base_url: the running user_service's base URL.
    Returns:
        None.
    Raises:
        None.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa
    from whatsapp_adapter.app.src.api.context import AppState

    db = emulator_firestore_client()
    settings = _adapter_test_settings(text_agent_base_url, users_base_url)
    text_agent, users, openai_runtime = _build_adapter_clients(settings)
    turns, confirmations = _build_adapter_turn_loop(
        db, fakes, settings, users, text_agent, openai_runtime
    )
    app.state.ctx = AppState(
        settings=settings,
        flows_private_key=rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        ),
        whatsapp=fakes.whatsapp,
        message_claims=MessageClaimsRepository(db),
        turns=turns,
        confirmations=confirmations,
    )
    yield
    await users.close()
    await text_agent.close()
    await openai_runtime.close()


def build_adapter_lifespan(
    fakes: Fakes, text_agent_base_url: str, users_base_url: str
):
    """Test lifespan for whatsapp_adapter: real turn loop, faked Meta/OpenAI.

    Args:
        fakes: the harness's shared fake collaborators.
        text_agent_base_url: the running text_agent's base URL.
        users_base_url: the running user_service's base URL.
    Returns:
        The lifespan context manager to install on the app's router.
    Raises:
        None.
    """
    return partial(
        _adapter_lifespan,
        fakes=fakes,
        text_agent_base_url=text_agent_base_url,
        users_base_url=users_base_url,
    )


@dataclass
class Harness:
    """The three running services plus the fakes wired behind them."""

    users: ServerThread
    text_agent: ServerThread
    adapter: ServerThread
    fakes: Fakes


def _harness_fakes() -> Fakes:
    """Fresh fakes for one three-service harness.

    Args:
        None.
    Returns:
        The Fakes shared by users, text-agent, and the adapter.
    Raises:
        None.
    """
    return Fakes(
        whatsapp=FakeWhatsAppClient(),
        openai=FakeOpenAIResponsesClient(),
        openai_images=FakeOpenAIImageClient(),
        transcriber=FakeAudioTranscriber(),
        embeddings=FakeEmbeddingClient(),
        agent_graph=FakeGraphClient(),
        users_graph=FakeGraphClient(),
        hubble=FakeHubbleClient(),
        agent_bucket=FakeGcsBucket(K.CONVERSATION_MEDIA_BUCKET),
        users_bucket=FakeGcsBucket(K.CONVERSATION_MEDIA_BUCKET),
        adapter_bucket=FakeGcsBucket(K.CONVERSATION_MEDIA_BUCKET),
        documents=FakeDocumentWorkerClient(),
    )


def start_harness() -> Harness:
    """Boot all three services on real localhost ports with test lifespans.

    Args:
        None.
    Returns:
        The booted users, text-agent, and adapter services plus their fakes.
    Raises:
        None.
    """
    from text_agent.app.src.api.app import app as text_agent_app
    from user_service.app.src.api.app import app as users_app
    from whatsapp_adapter.app.src.api.app import app as adapter_app

    users_port = free_port()
    text_agent_port = free_port()
    adapter_port = free_port()
    users_base = f"http://127.0.0.1:{users_port}"
    text_agent_base = f"http://127.0.0.1:{text_agent_port}"

    fakes = _harness_fakes()

    users_app.router.lifespan_context = build_user_service_lifespan(fakes)
    text_agent_app.router.lifespan_context = build_text_agent_lifespan(
        fakes, users_base
    )
    adapter_app.router.lifespan_context = build_adapter_lifespan(
        fakes, text_agent_base, users_base
    )

    users = ServerThread(users_app, users_port, "user_service")
    text_agent = ServerThread(text_agent_app, text_agent_port, "text_agent")
    adapter = ServerThread(adapter_app, adapter_port, "whatsapp_adapter")
    users.start()
    text_agent.start()
    adapter.start()
    return Harness(
        users=users, text_agent=text_agent, adapter=adapter, fakes=fakes
    )


async def wait_until(
    predicate,
    timeout: float = 30.0,
    interval: float = 0.05,
    message: str = "condition not reached",
) -> None:
    """Poll a real observable condition until it holds, or fail loudly.

    Args:
        predicate: a callable (sync or async) returning a truthy value once the
            condition holds.
        timeout: seconds to keep polling before giving up.
        interval: seconds to sleep between polls.
        message: included in the failure if the condition never holds.
    Returns:
        None.
    Raises:
        AssertionError: the condition never held within timeout.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"wait_until timed out after {timeout}s: {message}")


async def settle(seconds: float = 2.0) -> None:
    """Give the sender queue a grace period so negative assertions are
    meaningful.

    Args:
        seconds: how long to wait.
    Returns:
        None.
    Raises:
        None.
    """
    await asyncio.sleep(seconds)
