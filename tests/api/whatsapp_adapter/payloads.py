"""Webhook payload builders shared across whatsapp_adapter API tests.

Shapes follow Meta's documented webhook payload structure and the fields that
`app/src/input/webhook.py` (`extract_inbound_messages` and friends) actually
reads -- read only for field *names*, per the task brief's "signature facts"
carve-out, never for behavioral judgment calls.
"""

from __future__ import annotations

import json
from typing import Any


def text_message_webhook(
    *,
    message_id: str = "wamid.TEST1",
    sender_phone: str = "919876543210",
    sender_id: str = "bsuid-1",
    profile_name: str = "Test User",
    body: str = "hello",
    timestamp: str = "1700000000",
) -> dict[str, Any]:
    """A well-formed inbound text message webhook payload."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID1"},
                            "contacts": [
                                {
                                    "wa_id": sender_phone,
                                    "user_id": sender_id,
                                    "profile": {"name": profile_name},
                                }
                            ],
                            "messages": [
                                {
                                    "from": sender_phone,
                                    "from_user_id": sender_id,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


def text_message_missing_text_object(
    *,
    message_id: str = "wamid.MALFORMED1",
    sender_phone: str = "919876543210",
    sender_id: str = "bsuid-1",
    profile_name: str = "Test User",
    timestamp: str = "1700000000",
) -> dict[str, Any]:
    """A `type: "text"` message with the required `text` object entirely absent.

    This is the README's "Malformed supported payload" row: a genuinely
    supported type whose required body is missing, not an unknown type.
    """
    payload = text_message_webhook(
        message_id=message_id,
        sender_phone=sender_phone,
        sender_id=sender_id,
        profile_name=profile_name,
        timestamp=timestamp,
    )
    del payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]
    return payload


def reaction_message_webhook(
    *,
    message_id: str = "wamid.REACT1",
    sender_phone: str = "919876543210",
    sender_id: str = "bsuid-1",
    profile_name: str = "Test User",
    timestamp: str = "1700000000",
) -> dict[str, Any]:
    """A well-formed `type: "reaction"` message -- a real Meta type that
    `_normalize_message` deliberately drops (returns None), per its own
    in-code comment: "Feedback on a prior message, not a conversational turn."
    This is the README's "Unsupported message type" row.
    """
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID1"},
                            "contacts": [
                                {
                                    "wa_id": sender_phone,
                                    "user_id": sender_id,
                                    "profile": {"name": profile_name},
                                }
                            ],
                            "messages": [
                                {
                                    "from": sender_phone,
                                    "from_user_id": sender_id,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "type": "reaction",
                                    "reaction": {
                                        "message_id": "wamid.ORIGINAL",
                                        "emoji": "👍",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


def unrecognized_message_type_webhook(
    *,
    message_id: str = "wamid.UNRECOGNIZED1",
    sender_phone: str = "919876543210",
    sender_id: str = "bsuid-1",
    profile_name: str = "Test User",
    timestamp: str = "1700000000",
    message_type: str = "order",
) -> dict[str, Any]:
    """A well-formed message of a genuinely unrecognized Meta `type`.

    `"order"` (a real Meta webhook message type -- Meta's WhatsApp Business
    catalog "place an order" message) is not `"reaction"`, not one of
    `CONTENT_MESSAGE_TYPES`, and not `"sticker"` / `"interactive"` /
    `"location"` / `"contacts"` -- so `_normalize_message`'s wildcard arm
    converts it into an `UnsupportedMessage`, which the coordinator turns
    into one full agent turn (`AgentInputBuilder.unsupported()`), not a
    silent drop. This is the case the README's "Unsupported message type ->
    Ignore and return 200" Test Matrix row is actually making a claim about
    for message types outside the fully-supported set; `"reaction"` (see
    `reaction_message_webhook`) is a *different*, already-fully-ignored
    branch that never becomes an `UnsupportedMessage` at all.
    """
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID1"},
                            "contacts": [
                                {
                                    "wa_id": sender_phone,
                                    "user_id": sender_id,
                                    "profile": {"name": profile_name},
                                }
                            ],
                            "messages": [
                                {
                                    "from": sender_phone,
                                    "from_user_id": sender_id,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "type": message_type,
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


def sent_status_webhook(*, wamid: str = "wamid.SENT1") -> dict[str, Any]:
    """A webhook payload reporting one message as 'sent'."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "PNID1"},
                            "statuses": [{"id": wamid, "status": "sent"}],
                        },
                    }
                ]
            }
        ]
    }


def dumps(payload: dict[str, Any]) -> bytes:
    """Serialize a payload to the exact raw bytes an HMAC signature covers."""
    return json.dumps(payload).encode("utf-8")
