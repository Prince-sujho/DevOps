"""Meta webhook payload builders and the X-Hub-Signature-256 helper.

Shapes mirror what
`whatsapp_adapter/app/src/input/webhook.py::_normalize_message` and
`_common_message_fields` actually read.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from . import constants as K


def sign(raw_body: bytes, secret: str = K.WHATSAPP_APP_SECRET) -> str:
    """Compute the Meta X-Hub-Signature-256 header value for one raw body.

    Args:
        raw_body: the exact bytes the signature covers.
        secret: the app secret to sign with.
    Returns:
        The "sha256=..." header value.
    Raises:
        None.
    """
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def encode(payload: dict[str, Any]) -> bytes:
    """Serialize one webhook payload to the exact bytes that will be signed.

    Args:
        payload: webhook payload serialized to the bytes that get signed.
    Returns:
        The JSON encoding of payload as bytes.
    Raises:
        None.
    """
    return json.dumps(payload).encode()


def _envelope(value: dict[str, Any]) -> dict[str, Any]:
    """Wrap one messages 'value' block in the Meta entry/changes envelope.

    Args:
        value: the messages value object placed inside the Meta envelope.
    Returns:
        A WhatsApp webhook envelope whose messages value is value.
    Raises:
        None.
    """
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-entry-id",
                "changes": [{"field": "messages", "value": value}],
            }
        ],
    }


def _value(
    message: dict[str, Any],
    profile_name: str,
    sender_phone: str | None,
    sender_id: str,
) -> dict[str, Any]:
    """Build one messages value block with the contacts index the adapter reads.

    Args:
        message: the raw message to attach.
        profile_name: the sender's profile name.
        sender_phone: the sender's phone, or None if hidden.
        sender_id: the sender's WhatsApp user id.
    Returns:
        The value block.
    Raises:
        None.
    """
    contact: dict[str, Any] = {
        "profile": {"name": profile_name},
        "user_id": sender_id,
    }
    if sender_phone is not None:
        contact["wa_id"] = sender_phone
    return {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": K.PUBLIC_WHATSAPP_NUMBER,
            "phone_number_id": K.WHATSAPP_PHONE_NUMBER_ID,
        },
        "contacts": [contact],
        "messages": [message],
    }


def _message_base(
    message_id: str, sender_id: str, sender_phone: str | None, timestamp: str
) -> dict[str, Any]:
    """Common raw message fields; 'from' is omitted for a hidden number.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone, or None if hidden.
        timestamp: the message's Unix timestamp string.
    Returns:
        The base message fields.
    Raises:
        None.
    """
    base: dict[str, Any] = {
        "id": message_id,
        "from_user_id": sender_id,
        "timestamp": timestamp,
    }
    if sender_phone is not None:
        base["from"] = sender_phone
    return base


def text_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str | None,
    body: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One inbound text message webhook.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone, or None if hidden.
        body: the text body.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "text",
        "text": {"body": body},
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def malformed_text_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """A supported-shaped text message whose required 'text' block is absent.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "text",
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def reaction_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One inbound reaction: a WhatsApp type Sujho does not model as a turn.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "reaction",
        "reaction": {"message_id": "wamid.prior", "emoji": "👍"},
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def unrecognized_type_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
    message_type: str = "order",
) -> dict[str, Any]:
    """One inbound message of a genuinely unrecognized Meta type.

    `"order"` is a real Meta WhatsApp Business message type (a catalog order)
    that `_normalize_message` does not name in any case arm -- unlike
    `"reaction"` (see `reaction_webhook`), which the code deliberately drops and
    returns `None` for, this falls to the wildcard arm and becomes an
    `UnsupportedMessage` that runs one full agent turn via
    `AgentInputBuilder.unsupported()`. This is the case the README's Test
    Matrix "Unsupported message type -> Ignore and return 200" row is
    actually describing.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
        message_type: the unrecognized Meta type string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": message_type,
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def button_reply_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str | None,
    reply_id: str,
    title: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One tap on a reply button.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone, or None if hidden.
        reply_id: the tapped button's id.
        title: the tapped button's title.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": reply_id, "title": title},
        },
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def location_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str,
    latitude: float,
    longitude: float,
    address: str | None = None,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One inbound location share.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone.
        latitude: the shared latitude.
        longitude: the shared longitude.
        address: the shared address text, or None.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    location: dict[str, Any] = {"latitude": latitude, "longitude": longitude}
    if address is not None:
        location["address"] = address
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "location",
        "location": location,
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def contacts_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str | None,
    origin: str,
    shared_phone: str,
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One requested phone share (origin 'contact_request') or forwarded card.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone, or None if hidden.
        origin: how the contact reached the adapter.
        shared_phone: the shared contact's phone number.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "contacts",
        "contacts": [
            {
                "origin": origin,
                "name": {
                    "formatted_name": profile_name,
                    "first_name": profile_name,
                },
                "phones": [
                    {"phone": f"+{shared_phone}", "wa_id": shared_phone}
                ],
            }
        ],
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def flow_completion_webhook(
    *,
    message_id: str,
    sender_id: str,
    sender_phone: str | None,
    response_json: dict[str, Any],
    profile_name: str = "Test User",
    timestamp: str = "1750000000",
) -> dict[str, Any]:
    """One Flow completion delivered as an interactive nfm_reply.

    Args:
        message_id: the message's wamid.
        sender_id: the sender's WhatsApp user id.
        sender_phone: the sender's phone, or None if hidden.
        response_json: the Flow's completion payload.
        profile_name: the sender's profile name.
        timestamp: the message's Unix timestamp string.
    Returns:
        The webhook body.
    Raises:
        None.
    """
    message = {
        **_message_base(message_id, sender_id, sender_phone, timestamp),
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "name": "flow",
                "body": "Sent",
                "response_json": json.dumps(response_json),
            },
        },
    }
    return _envelope(_value(message, profile_name, sender_phone, sender_id))


def student_onboarding_completion(
    *,
    institution: str = "Delhi Public School",
    institution_id: str = "school-dps-001",
    grade: str = "9",
    subjects: list[str] | None = None,
) -> dict[str, Any]:
    """The completion payload the student onboarding Flow's terminal screen
    sends.

    Args:
        institution: the selected school's name.
        institution_id: the selected school's id.
        grade: the student's grade.
        subjects: enrolled subjects, or None for the default.
    Returns:
        The completion payload.
    Raises:
        None.
    """
    return {
        "flow_token": K.ONBOARDING_FLOW_TOKEN,
        "persona": "student",
        "institution": institution,
        "institutionId": institution_id,
        "grade": grade,
        "subjects": subjects
        if subjects is not None
        else ["mathematics", "science"],
    }


def teacher_onboarding_completion(
    *,
    institution: str = "Delhi Public School",
    institution_id: str = "school-dps-001",
    grades: list[str] | None = None,
    subjects: list[str] | None = None,
) -> dict[str, Any]:
    """The completion payload the teacher onboarding Flow's terminal screen
    sends.

    Args:
        institution: the selected school's name.
        institution_id: the selected school's id.
        grades: taught grades, or None for the default.
        subjects: taught subjects, or None for the default.
    Returns:
        The completion payload.
    Raises:
        None.
    """
    return {
        "flow_token": K.ONBOARDING_FLOW_TOKEN,
        "persona": "teacher",
        "institution": institution,
        "institutionId": institution_id,
        "grades": grades if grades is not None else ["9", "10"],
        "subjects": subjects if subjects is not None else ["mathematics"],
    }
