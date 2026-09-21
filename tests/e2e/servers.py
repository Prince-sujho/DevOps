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
    """Reserve one free localhost TCP port and release it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_gcp_identity() -> GcpIdentity:
    """GCP identity pointing at the emulator project with anonymous credentials."""
    return GcpIdentity(
        project=K.TEST_PROJECT,
        location=K.TEST_LOCATION,
        credentials=AnonymousCredentials(),
    )


def emulator_firestore_client() -> AsyncClient:
    """Async Firestore client bound to the local emulator (FIRESTORE_EMULATOR_HOST)."""
    return AsyncClient(project=K.TEST_PROJECT, credentials=AnonymousCredentials())


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
        """Clear every fake's recorded state between tests."""
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
        """Bind a configured uvicorn server to a fixed localhost port."""
        self.port = port
        self.name = name
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True, name=name)

    def start(self, timeout: float = 30.0) -> None:
        """Start the thread and block until the port serves /health."""
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
        raise RuntimeError(f"{self.name} did not become healthy on port {self.port}")

    def stop(self, timeout: float = 10.0) -> None:
        """Ask uvicorn to exit and join the thread."""
        self._server.should_exit = True
        self._thread.join(timeout=timeout)


def build_user_service_lifespan(fakes: Fakes):
    """Test lifespan for user_service: real Firestore repos, faked Hubble/Neo4j/GCS."""
    from user_service.app.src.access import AccessResolver
    from user_service.app.src.api.context import AppState
    from user_service.app.src.types import Settings

    @asynccontextmanager
    async def lifespan(app):
        db = emulator_firestore_client()
        settings = Settings(
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

    return lifespan


def build_text_agent_lifespan(fakes: Fakes, users_base_url: str):
    """Test lifespan for text_agent: real RespondService, faked OpenAI/Neo4j/Gemini."""
    from infra.llm.oai.runtime import OpenAIRuntime
    from text_agent.app.src.api.context import AppState
    from text_agent.app.src.services import RespondService
    from text_agent.app.src.services import respond as respond_mod

    @asynccontextmanager
    async def lifespan(app):
        users = UsersClient(
            base_url=users_base_url,
            service_secret=K.USERS_SERVICE_SECRET,
        )
        respond_mod.OpenAIResponsesClient = lambda runtime, usage: fakes.openai
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
            respond=respond,
            text_agent_service_secret=K.TEXT_AGENT_SERVICE_SECRET,
        )
        yield
        await users.close()
        await runtime.close()

    return lifespan


def build_adapter_lifespan(fakes: Fakes, text_agent_base_url: str, users_base_url: str):
    """Test lifespan for whatsapp_adapter: real turn loop, faked Meta/OpenAI."""
    from infra.llm.oai.runtime import OpenAIRuntime
    from cryptography.hazmat.primitives.asymmetric import rsa
    from whatsapp_adapter.app.src.api.context import AppState
    from whatsapp_adapter.app.src.input import FlowUploadFetcher, MediaFetcher
    from whatsapp_adapter.app.src.output import (
        DeliveryConfirmations,
        FlowLauncher,
        ReplyDelivery,
    )
    from whatsapp_adapter.app.src.service import (
        AgentInputBuilder,
        OnboardingCoordinator,
        ReplyRunner,
        TurnGate,
        TurnLoop,
    )
    from whatsapp_adapter.app.src.types import Settings
    from whatsapp_adapter.app.src.types.settings import (
        ConversionsSettings,
        FlowIds,
        FlowSettings,
        PersonaFlowIds,
        ServiceClientSettings,
        WhatsAppSettings,
    )

    class FakeConversionsReporter:
        def report(self, user, result) -> None:
            return None

        async def close(self) -> None:
            return None

    @asynccontextmanager
    async def lifespan(app):
        db = emulator_firestore_client()
        settings = Settings(
            gcp=test_gcp_identity(),
            openai_api_key="test-openai-api-key",
            whatsapp=WhatsAppSettings(
                verify_token=K.WHATSAPP_VERIFY_TOKEN,
                access_token=K.WHATSAPP_ACCESS_TOKEN,
                phone_number_id=K.WHATSAPP_PHONE_NUMBER_ID,
                api_version=K.WHATSAPP_API_VERSION,
                app_secret=K.WHATSAPP_APP_SECRET,
                public_number=K.PUBLIC_WHATSAPP_NUMBER,
            ),
            conversions=ConversionsSettings(
                access_token="test-capi-token",
                dataset_id="test-capi-dataset",
                page_id="test-capi-page",
            ),
            flows=FlowSettings(
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
                private_key_pem="-----BEGIN TEST KEY-----\nunused\n-----END TEST KEY-----",
            ),
            text_agent=ServiceClientSettings(
                api_origin=text_agent_base_url,
                service_secret=K.TEXT_AGENT_SERVICE_SECRET,
            ),
            users=ServiceClientSettings(
                api_origin=users_base_url,
                service_secret=K.USERS_SERVICE_SECRET,
            ),
            conversation_media_bucket=K.CONVERSATION_MEDIA_BUCKET,
        )
        whatsapp = fakes.whatsapp
        text_agent = TextAgentClient(
            base_url=settings.text_agent.api_origin,
            service_secret=settings.text_agent.service_secret,
        )
        users = UsersClient(
            base_url=settings.users.api_origin,
            service_secret=settings.users.service_secret,
        )
        flows = FlowLauncher(whatsapp, settings.flows.ids)
        openai_runtime = OpenAIRuntime(api_key=settings.openai_api_key)
        inputs = AgentInputBuilder(
            fakes.adapter_bucket,
            MediaFetcher(whatsapp, openai_runtime),
            FlowUploadFetcher(whatsapp),
        )
        pending = OnboardingRepository(db)
        confirmations = DeliveryConfirmations()
        whatsapp.bind_confirmations(confirmations)
        delivery = ReplyDelivery(
            whatsapp=whatsapp,
            flows=flows,
            confirmations=confirmations,
            users=users,
            media_bucket=fakes.adapter_bucket,
        )
        runner = ReplyRunner(
            text_agent=text_agent,
            delivery=delivery,
            users=users,
            whatsapp=whatsapp,
            usage=UsageRepository(db),
            conversions=FakeConversionsReporter(),
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
        app.state.ctx = AppState(
            settings=settings,
            flows_private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
            whatsapp=whatsapp,
            message_claims=MessageClaimsRepository(db),
            turns=TurnLoop(gate.process, runner),
            confirmations=confirmations,
        )
        yield
        await users.close()
        await text_agent.close()
        await openai_runtime.close()

    return lifespan


@dataclass
class Harness:
    """The three running services plus the fakes wired behind them."""

    users: ServerThread
    text_agent: ServerThread
    adapter: ServerThread
    fakes: Fakes


def start_harness() -> Harness:
    """Boot all three services on real localhost ports with test lifespans."""
    from text_agent.app.src.api.app import app as text_agent_app
    from user_service.app.src.api.app import app as users_app
    from whatsapp_adapter.app.src.api.app import app as adapter_app

    users_port = free_port()
    text_agent_port = free_port()
    adapter_port = free_port()
    users_base = f"http://127.0.0.1:{users_port}"
    text_agent_base = f"http://127.0.0.1:{text_agent_port}"

    fakes = Fakes(
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

    users_app.router.lifespan_context = build_user_service_lifespan(fakes)
    text_agent_app.router.lifespan_context = build_text_agent_lifespan(fakes, users_base)
    adapter_app.router.lifespan_context = build_adapter_lifespan(
        fakes, text_agent_base, users_base
    )

    users = ServerThread(users_app, users_port, "user_service")
    text_agent = ServerThread(text_agent_app, text_agent_port, "text_agent")
    adapter = ServerThread(adapter_app, adapter_port, "whatsapp_adapter")
    users.start()
    text_agent.start()
    adapter.start()
    return Harness(users=users, text_agent=text_agent, adapter=adapter, fakes=fakes)


async def wait_until(
    predicate,
    timeout: float = 30.0,
    interval: float = 0.05,
    message: str = "condition not reached",
) -> None:
    """Poll a real observable condition until it holds, or fail loudly."""
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
    """Give the sender queue a grace period so negative assertions are meaningful."""
    await asyncio.sleep(seconds)
