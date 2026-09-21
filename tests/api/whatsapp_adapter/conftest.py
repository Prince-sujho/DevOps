"""Shared fixtures and fakes for whatsapp_adapter API-level tests.

These tests drive the real FastAPI app (`whatsapp_adapter.app.src.api.app:app`)
through an ASGI test client. Every genuinely external dependency (Meta Graph API,
Firestore-backed repositories, the turn loop) is replaced by an
in-memory fake wired through a test lifespan that overrides
`app.router.lifespan_context`, per the task's harness instructions.

Expected literal values live in the individual test modules, committed before the
corresponding client call runs, per the "commit before you run" rule.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
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

_RSA_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY_PEM = _RSA_PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")
RSA_KEY_SIZE_BYTES = 2048 // 8


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    """Compute the X-Hub-Signature-256 header value Meta would send for `body`."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# --- Fakes ----------------------------------------------------------------


class FakeMessageClaimsRepository:
    """In-memory stand-in for the Firestore-backed MessageClaimsRepository."""

    def __init__(self) -> None:
        self.claimed: set[str] = set()
        self.claim_calls: list[str] = []

    async def claim(self, message_id: str) -> bool:
        """Claim a message id; True on first write, mirroring the real repo."""
        self.claim_calls.append(message_id)
        if message_id in self.claimed:
            return False
        self.claimed.add(message_id)
        return True


class FakeTurnLoop:
    """Records every inbound message handed off by the webhook route.

    The route calls `ctx.turns.submit(message)` synchronously before returning
    200, so a bare call recorder is a faithful substitute for route-level testing.
    """

    def __init__(self) -> None:
        self.calls: list[InboundMessage] = []

    def submit(self, message: InboundMessage) -> None:
        self.calls.append(message)


class FakeDeliveryConfirmations:
    """Records `confirm_sent` calls in place of the real DeliveryConfirmations."""

    def __init__(self) -> None:
        self.confirmed: list[str] = []

    def confirm_sent(self, wamid: str) -> None:
        self.confirmed.append(wamid)


@dataclass
class Harness:
    """Everything a test needs: the client plus every fake, for assertions."""

    client: httpx.AsyncClient
    message_claims: FakeMessageClaimsRepository
    turns: FakeTurnLoop
    confirmations: FakeDeliveryConfirmations


def _build_settings() -> SimpleNamespace:
    """Build a minimal settings namespace exposing only what routes.py reads."""
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            verify_token=VERIFY_TOKEN,
            app_secret=APP_SECRET,
            phone_number_id="PNID1",
        ),
        flows=SimpleNamespace(
            private_key_pem=PRIVATE_KEY_PEM,
        ),
    )


@pytest_asyncio.fixture
async def harness():
    """Wire the real FastAPI app with a fully faked AppState and yield a Harness."""
    message_claims = FakeMessageClaimsRepository()
    turns = FakeTurnLoop()
    confirmations = FakeDeliveryConfirmations()

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.ctx = AppState(
            settings=_build_settings(),
            flows_private_key=_RSA_PRIVATE_KEY,
            whatsapp=None,
            message_claims=message_claims,
            turns=turns,
            confirmations=confirmations,
        )
        yield

    real_app.router.lifespan_context = test_lifespan

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
