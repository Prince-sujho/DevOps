"""Test data for the adapter unit tests. No I/O.

Two sections: raw Meta webhook shapes (field names follow Meta's documented
payload and the keys `app/src/input/webhook.py` reads), and the normalized
objects the service layer consumes. Expected values live in the tests.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from infra.clients.text_agent import GenerateResponse
from infra.clients.users import (
    GiftCardDelivery,
    Institution,
    StudentProfile,
    StudentScope,
    TeacherProfile,
    TeacherScope,
)
from infra.content.types.persist import SourceMeta
from infra.conversation import (
    Button,
    ButtonsMessage,
    Citations,
    DocumentFormMessage,
    DocumentMessage,
    GiftCardMessage,
    GradeFormMessage,
    ImageMessage,
    ListMessage,
    ListRow,
    LocationRequestMessage,
    ProfileFormMessage,
    ReactionRecord,
    SourcesRecord,
    TextMessage,
    UrlMessage,
    WebPage,
)
from infra.conversation import ContactMessage as OutboundContactMessage
from infra.curriculum import Subject
from infra.llm.oai.types.responses import Round
from infra.schools import School

from whatsapp_adapter.app.src.input.message import (
    ContactMessage,
    ContentMessage,
    FlowCompletionMessage,
    InteractiveReplyMessage,
    LocationMessage,
)
from whatsapp_adapter.app.src.types.flows import FlowMediaEncryptionMetadata, FlowMediaRef

PHONE_NUMBER_ID = "PNID1"
SENDER_PHONE = "919876543210"
SENDER_ID = "bsuid-1"
PROFILE_NAME = "Priya"
MESSAGE_ID = "wamid.UNIT1"
TIMESTAMP = "1700000000"

CONTACT = {
    "wa_id": SENDER_PHONE,
    "user_id": SENDER_ID,
    "profile": {"name": PROFILE_NAME},
}


def message(message_type: str, **payload: Any) -> dict[str, Any]:
    """One raw inbound message of the given type, with that type's payload attached."""
    return {
        "from": SENDER_PHONE,
        "from_user_id": SENDER_ID,
        "id": MESSAGE_ID,
        "timestamp": TIMESTAMP,
        "type": message_type,
        **payload,
    }


def without_sender_phone(raw: dict[str, Any]) -> dict[str, Any]:
    """The same message as Meta sends it when the sender's number is hidden."""
    return {key: value for key, value in raw.items() if key != "from"}


def messages_change(
    *messages: dict[str, Any], phone_number_id: str = PHONE_NUMBER_ID
) -> dict[str, Any]:
    """One 'messages' change block carrying inbound messages from our test sender."""
    return {
        "field": "messages",
        "value": {
            "metadata": {"phone_number_id": phone_number_id},
            "contacts": [CONTACT],
            "messages": list(messages),
        },
    }


def statuses_change(*statuses: dict[str, Any]) -> dict[str, Any]:
    """One 'messages' change block carrying outbound delivery statuses."""
    return {
        "field": "messages",
        "value": {
            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
            "statuses": list(statuses),
        },
    }


def envelope(*changes: dict[str, Any]) -> dict[str, Any]:
    """The raw webhook body wrapping change blocks in a single entry."""
    return {"entry": [{"changes": list(changes)}]}


# --------------------------------------------------------------------------
# normalized inbound messages, as the service layer receives them
# --------------------------------------------------------------------------

CREATED_AT_MS = 1_700_000_000_000

CONTENT_FIELDS: dict[str, Any] = {
    "sender_phone": SENDER_PHONE,
    "sender_id": SENDER_ID,
    "profile_name": PROFILE_NAME,
    "message_id": MESSAGE_ID,
    "timestamp": TIMESTAMP,
}


def inbound_text(body: str = "hi", **overrides: Any) -> ContentMessage:
    """One normalized inbound text message."""
    return ContentMessage(type="text", content={"body": body}, **{**CONTENT_FIELDS, **overrides})


def inbound_media(
    kind: str = "image",
    *,
    media_id: str = "media-1",
    mime_type: str = "image/jpeg",
    caption: str = "",
) -> ContentMessage:
    """One normalized inbound media message."""
    content: dict[str, Any] = {"id": media_id, "mime_type": mime_type}
    if caption:
        content["caption"] = caption
    return ContentMessage(type=kind, content=content, **CONTENT_FIELDS)


def jpeg_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """A tiny valid JPEG, so image compression has real pixels to encode."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "jpeg")
    return buffer.getvalue()


def png_bytes(color: tuple[int, int, int] = (0, 0, 255)) -> bytes:
    """A tiny valid PNG, so JPEG conversion is observable (not a JPEG already)."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "png")
    return buffer.getvalue()


def flow_media_ref(media_id: str = "ref-1") -> FlowMediaRef:
    """One encrypted Flow upload reference, as the webhook forwards it."""
    return FlowMediaRef(
        media_id=media_id,
        cdn_url=f"https://cdn.whatsapp.net/{media_id}",
        file_name=f"{media_id}.pdf",
        encryption_metadata=FlowMediaEncryptionMetadata(
            encrypted_hash="eh",
            iv="iv",
            encryption_key="ek",
            hmac_key="hk",
            hmac="h",
            plaintext_hash="ph",
        ),
    )


def inbound_tap(reply_id: str = "difficulty:easy", title: str = "Easy") -> InteractiveReplyMessage:
    """One normalized tap on a reply button or list row."""
    return InteractiveReplyMessage(reply_id=reply_id, title=title, **CONTENT_FIELDS)


def inbound_contact(origin: str = "contact_request") -> ContactMessage:
    """One normalized shared or forwarded contact card."""
    return ContactMessage(origin=origin, **CONTENT_FIELDS)


def inbound_location(
    latitude: float = 12.97,
    longitude: float = 77.59,
    address: str | None = "MG Road, Bengaluru",
) -> LocationMessage:
    """One normalized location share."""
    return LocationMessage(
        latitude=latitude, longitude=longitude, address=address, **CONTENT_FIELDS
    )


def inbound_flow(response_json: dict[str, Any], flow_token: str = "grade") -> FlowCompletionMessage:
    """One normalized Flow completion."""
    return FlowCompletionMessage(
        flow_token=flow_token, response_json=response_json, **CONTENT_FIELDS
    )


STUDENT_ONBOARDING_RESPONSE: dict[str, Any] = {
    "persona": "student",
    "institutionId": "school-1",
    "institution": "Delhi Public School",
    "grade": "8",
    "subjects": ["mathematics"],
}

TEACHER_ONBOARDING_RESPONSE: dict[str, Any] = {
    "persona": "teacher",
    "institutionId": "school-1",
    "institution": "Delhi Public School",
    "grades": ["9", "10"],
    "subjects": ["science"],
}

PROFILE_FLOW_RESPONSE: dict[str, Any] = {
    "institutionId": "",
    "institution": "Delhi Public School",
    "grade": "8",
    "subjects": ["mathematics"],
}


def student(user_id: str = "u-1", **overrides: Any) -> StudentProfile:
    """One onboarded student profile."""
    fields: dict[str, Any] = {
        "userId": user_id,
        "phone": SENDER_PHONE,
        "name": PROFILE_NAME,
        "institution": Institution(name="Delhi Public School"),
        "createdAtMs": CREATED_AT_MS,
        "scope": StudentScope(grade=7, subjects=[Subject.MATHEMATICS]),
    }
    return StudentProfile(**{**fields, **overrides})


# --------------------------------------------------------------------------
# outbound bubbles and generated replies, as the delivery path receives them
# --------------------------------------------------------------------------

GIFT_CARD_ID = "gc-1"


def a_reply(*contents: Any, read_ids: list[str] | None = None) -> GenerateResponse:
    """One generated reply carrying the given contents, in delivery order."""
    return GenerateResponse(
        contents=list(contents),
        readIds=read_ids or [],
        actions=[],
        thought=Round(responseId="resp-1", items=[]),
        usage=[],
    )


def text_bubble(text: str = "Here you go.") -> TextMessage:
    """One outbound text bubble."""
    return TextMessage(type="text", text=text)


def image_bubble(filename: str = "diagram.png", caption: str = "The diagram") -> ImageMessage:
    """One outbound image bubble, referenced by stored filename."""
    return ImageMessage(type="image", filename=filename, caption=caption)


def document_bubble(filename: str = "notes.pdf", caption: str = "Your notes") -> DocumentMessage:
    """One outbound document bubble, referenced by stored filename."""
    return DocumentMessage(type="document", filename=filename, caption=caption)


def buttons_bubble(body: str = "Pick one", *labels: str) -> ButtonsMessage:
    """One outbound bubble with tappable reply buttons."""
    chosen = labels or ("Yes", "No")
    return ButtonsMessage(
        type="buttons",
        body=body,
        buttons=[Button(id=f"btn:{label.lower()}", title=label) for label in chosen],
    )


def list_bubble(body: str = "Choose a chapter", button_label: str = "Chapters") -> ListMessage:
    """One outbound bubble with a tap-to-open selectable list."""
    return ListMessage(
        type="list",
        body=body,
        button_label=button_label,
        rows=[ListRow(id="ch:1", title="Chapter 1", description="Integers")],
    )


def url_bubble(
    body: str = "NCERT page", display_text: str = "Open", url: str = "https://ncert.test/page"
) -> UrlMessage:
    """One outbound bubble with a tappable link button."""
    return UrlMessage(type="url", body=body, display_text=display_text, url=url)


def location_request_bubble(body: str = "Share your location") -> LocationRequestMessage:
    """One outbound prompt asking for the user's location."""
    return LocationRequestMessage(type="location_request", body=body)


def contact_bubble() -> OutboundContactMessage:
    """One outbound contact card."""
    return OutboundContactMessage(type="contact")


def gift_card_bubble(gift_card_id: str = GIFT_CARD_ID) -> GiftCardMessage:
    """One outbound gift-card bubble."""
    return GiftCardMessage(type="gift_card", giftCardId=gift_card_id)


def reaction(emoji: str = "👍") -> ReactionRecord:
    """One delivered emoji reaction record."""
    return ReactionRecord(type="reaction", emoji=emoji)


def a_cited_page(
    name: str = "NCERT Mathematics",
    *,
    page: int = 42,
    unit: str = "Integers",
) -> SourceMeta:
    """One catalog page a reply can rest on."""
    return SourceMeta(
        entry_id="ncert:7:math",
        name=name,
        grade=7,
        subject="mathematics",
        unit=unit,
        page=page,
    )


def sources_record(*urls: str, pages: list[SourceMeta] | None = None) -> SourcesRecord:
    """One validated sources record.

    `pages` are the catalog locators that become the italic rollup; omit them
    to send a sources record that cites only the web.
    """
    cited = list(pages or [])
    return SourcesRecord(
        type="sources",
        citations=Citations(
            curriculum=[page.entry_id for page in cited],
            web=[WebPage(url=url, title=f"Title for {url}") for url in urls],
        ),
        sources=cited,
    )


def document_form(
    body: str = "Tell me more", request_text: str = "practice sheet"
) -> DocumentFormMessage:
    """One outbound document-form launch."""
    return DocumentFormMessage(
        type="form",
        form="document",
        body=body,
        requestText=request_text,
        detailsPrompt="Which chapter?",
        kind="practice",
    )


def grade_form(
    body: str = "Upload the papers", request_text: str = "grade these"
) -> GradeFormMessage:
    """One outbound grade-form launch."""
    return GradeFormMessage(type="form", form="grade", body=body, requestText=request_text)


def profile_form(
    body: str = "Update your profile", request_text: str = "profile"
) -> ProfileFormMessage:
    """One outbound profile-form launch."""
    return ProfileFormMessage(type="form", form="profile", body=body, requestText=request_text)


def gift_card(
    *,
    card_number: str | None = "1234-5678",
    card_pin: str | None = "4321",
    valid_till: str | None = "2027-03-31",
    brand: str = "Amazon",
    amount_inr: int = 500,
) -> GiftCardDelivery:
    """One full gift card as the user service delivers it."""
    return GiftCardDelivery(
        id=GIFT_CARD_ID,
        productId="prod-1",
        brand=brand,
        amountInr=amount_inr,
        status="succeeded",
        createdAtMs=CREATED_AT_MS,
        instructions="Redeem at amazon.in/gc",
        cardNumber=card_number,
        cardPin=card_pin,
        validTill=valid_till,
    )


def teacher(user_id: str = "u-2", **overrides: Any) -> TeacherProfile:
    """One onboarded teacher profile."""
    fields: dict[str, Any] = {
        "userId": user_id,
        "phone": SENDER_PHONE,
        "name": "Anil",
        "institution": Institution(name="Delhi Public School"),
        "createdAtMs": CREATED_AT_MS,
        "scope": TeacherScope(grades=[9, 10], subjects=[Subject.SCIENCE]),
    }
    return TeacherProfile(**{**fields, **overrides})


def school(
    *,
    school_id: str = "school-1",
    name: str = "Delhi Public School",
    locality: str = "Sector 12",
    city: str = "Gurugram",
    state: str = "Haryana",
) -> School:
    """One canonical school, as institution search returns it."""
    return School(
        id=school_id,
        name=name,
        locality=locality,
        city=city,
        state=state,
        address=f"{name}, {locality}, {city}",
    )
