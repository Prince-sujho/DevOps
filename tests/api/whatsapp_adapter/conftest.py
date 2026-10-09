"""Shared fixtures and fakes for whatsapp_adapter API-level tests.

These tests drive the real FastAPI app (`whatsapp_adapter.app.src.api.app:app`)
through an ASGI test client. Every genuinely external dependency (Meta Graph
API,
Firestore-backed repositories, the turn loop) is replaced by an
in-memory fake wired through a test lifespan that overrides
`app.router.lifespan_context`, per the task's harness instructions.

Expected literal values live in the individual test modules, committed before
the corresponding client call runs, per the "commit before you run" rule.
"""

from __future__ import annotations

import hashlib
import hmac
from contextlib import asynccontextmanager
from functools import partial
from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from whatsapp_adapter.app.src.api.app import app as real_app
from whatsapp_adapter.app.src.api.context import AppState
from whatsapp_adapter.app.src.input import InboundMessage

# --- Fixed test secrets (throwaway, test-only) --------------------------------

VERIFY_TOKEN = "test-verify-token"
APP_SECRET = "test-app-secret"
WRONG_APP_SECRET = "wrong-app-secret"

_RSA_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537, key_size=2048
)
PRIVATE_KEY_PEM = _RSA_PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")
RSA_KEY_SIZE_BYTES = 2048 // 8


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    """Compute the X-Hub-Signature-256 header value Meta would send for `body`.

    Args:
        body: the raw request body bytes to sign.
        secret: the app secret to sign with; defaults to the real test secret.
    Returns:
        The header value, in "sha256=<hex digest>" form.
    Raises:
        None.
    """
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# --- Fakes ----------------------------------------------------------------


class FakeMessageClaimsRepository:
    """In-memory stand-in for the Firestore-backed MessageClaimsRepository."""

    def __init__(self) -> None:
        """No message ids claimed yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.claimed: set[str] = set()
        self.claim_calls: list[str] = []

    async def claim(self, message_id: str) -> bool:
        """Claim a message id; True on first write, mirroring the real repo.

        Args:
            message_id: the Meta message id to claim.
        Returns:
            True if this is the first claim of message_id, False otherwise.
        Raises:
            None.
        """
        self.claim_calls.append(message_id)
        if message_id in self.claimed:
            return False
        self.claimed.add(message_id)
        return True


class FakeTurnLoop:
    """Records every inbound message handed off by the webhook route.

    The route calls `ctx.turns.submit(message)` synchronously before returning
    200, so a bare call recorder is a faithful substitute for route-level
    testing.
    """

    def __init__(self) -> None:
        """No messages submitted yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[InboundMessage] = []

    def submit(self, message: InboundMessage) -> None:
        """Record message as submitted, mirroring the real turn loop's
        synchronous handoff.

        Args:
            message: the inbound message recorded as submitted.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.append(message)


class FakeDeliveryConfirmations:
    """Records `confirm_sent` calls in place of the real
    DeliveryConfirmations."""

    def __init__(self) -> None:
        """No deliveries confirmed yet.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.confirmed: list[str] = []

    def confirm_sent(self, wamid: str) -> None:
        """Record wamid as confirmed.

        Args:
            wamid: WhatsApp message id recorded as confirmed sent.
        Returns:
            None.
        Raises:
            None.
        """
        self.confirmed.append(wamid)


@dataclass
class Harness:
    """Everything a test needs: the client plus every fake, for assertions."""

    client: httpx.AsyncClient
    message_claims: FakeMessageClaimsRepository
    turns: FakeTurnLoop
    confirmations: FakeDeliveryConfirmations


def _build_settings() -> SimpleNamespace:
    """Build a minimal settings namespace exposing only what routes.py reads.

    Args:
        None.
    Returns:
        A settings namespace with the WhatsApp verify token, app secret, and
        flows key.
    Raises:
        None.
    """
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            verify_token=VERIFY_TOKEN,
            app_secret=APP_SECRET,
            phone_number_id="PNID1",
        ),
        flows=SimpleNamespace(private_key_pem=PRIVATE_KEY_PEM),
    )


@asynccontextmanager
async def _adapter_test_lifespan(app, message_claims, turns, confirmations):
    """The app's real lifespan, wired to the fully faked AppState.

    Args:
        app: the FastAPI app whose state is populated.
        message_claims: the fake message-claims repository.
        turns: the fake turn loop.
        confirmations: the fake delivery confirmations.
    Returns:
        None.
    Raises:
        None.
    """
    app.state.ctx = AppState(
        settings=_build_settings(),
        flows_private_key=_RSA_PRIVATE_KEY,
        whatsapp=None,
        users=None,
        message_claims=message_claims,
        turns=turns,
        confirmations=confirmations,
    )
    yield


@pytest_asyncio.fixture
async def harness():
    """Wire the real FastAPI app with a fully faked AppState and yield a
    Harness.

    Args:
        None.
    Returns:
        A Harness with the ASGI client and the faked claims, turns, and
        confirmations.
    Raises:
        None.
    """
    message_claims = FakeMessageClaimsRepository()
    turns = FakeTurnLoop()
    confirmations = FakeDeliveryConfirmations()
    real_app.router.lifespan_context = partial(
        _adapter_test_lifespan,
        message_claims=message_claims,
        turns=turns,
        confirmations=confirmations,
    )

    transport = httpx.ASGITransport(app=real_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        async with real_app.router.lifespan_context(real_app):
            yield Harness(
                client=client,
                message_claims=message_claims,
                turns=turns,
                confirmations=confirmations,
            )
