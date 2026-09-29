"""Webhook HMAC signature verification: valid, wrong secret, tampered body."""

from __future__ import annotations

import pytest

from infra.conversation import TextMessage

from . import constants as K
from . import payloads
from .scripting import create_user, student_profile_input, turn
from .servers import settle, wait_until

pytestmark = pytest.mark.asyncio


def _payload(message_id: str) -> dict:
    """One text-message webhook body, keyed by the given Meta message id.

    Args:
        message_id: the webhook's message wamid.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    return payloads.text_webhook(
        message_id=message_id,
        sender_id="bsuid-sig",
        sender_phone="919700000001",
        body="signature check",
        profile_name="Sig Tester",
    )


async def _claims(db) -> list[str]:
    """Every claimed message id currently recorded.

    Args:
        db: the Firestore client.
    Returns:
        Claimed message ids, in Firestore stream order.
    Raises:
        None.
    """
    return [
        doc.id
        async for doc in db.collection(K.MESSAGE_CLAIMS_COLLECTION).stream()
    ]


async def test_valid_signature_is_accepted_and_processed(
    adapter, whatsapp, openai, db, users_api
):
    """A correctly signed body reaches parsing, claiming and delivery.

    Args:
        adapter: HTTP client for the running whatsapp_adapter.
        whatsapp: the fake Meta Graph API client.
        openai: the fake OpenAI Responses client.
        db: the emulator-bound Firestore client.
        users_api: HTTP client for user_service's internal surface.
    Returns:
        None.
    Raises:
        None.
    """
    await create_user(
        users_api,
        student_profile_input(phone="919700000001", name="Sig Tester"),
    )
    openai.push(
        turn(
            response_id="resp-sig",
            messages=[TextMessage(type="text", text="ok")],
        )
    )

    response = await adapter.post_webhook(_payload("wamid.sig.valid"))
    assert response.status_code == 200

    await wait_until(lambda: len(whatsapp.calls) >= 1)
    await settle()

    assert await _claims(db) == ["wamid.sig.valid"]
    assert len(openai.calls) == 1
    assert whatsapp.kinds() == ["text"]


async def test_wrong_secret_signature_is_rejected(
    adapter, whatsapp, openai, db
):
    """A body signed with the wrong app secret is rejected with 403.

    Args:
        adapter: HTTP client for the running whatsapp_adapter.
        whatsapp: the fake Meta Graph API client.
        openai: the fake OpenAI Responses client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    response = await adapter.post_webhook(
        _payload("wamid.sig.wrong"), secret="not-the-real-app-secret"
    )
    assert response.status_code == 403
    await settle()

    assert await _claims(db) == []
    assert whatsapp.calls == []
    assert openai.calls == []


async def test_tampered_body_signature_is_rejected(
    adapter, whatsapp, openai, db
):
    """A body mutated after signing is rejected with 403.

    Args:
        adapter: HTTP client for the running whatsapp_adapter.
        whatsapp: the fake Meta Graph API client.
        openai: the fake OpenAI Responses client.
        db: the emulator-bound Firestore client.
    Returns:
        None.
    Raises:
        None.
    """
    response = await adapter.post_webhook(
        _payload("wamid.sig.tampered"), tamper=True
    )
    assert response.status_code == 403
    await settle()

    assert await _claims(db) == []
    assert whatsapp.calls == []
    assert openai.calls == []
