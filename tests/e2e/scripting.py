"""Helpers for scripting the faked OpenAI turn and seeding user_service state."""

from __future__ import annotations

from typing import Any, Optional

from infra.conversation import OutboundMessage, TextMessage
from infra.llm.oai.types.messages import AssistantMessage
from infra.llm.oai.types.responses import LlmResponse, Speech

from . import constants as K


def turn(
    *,
    response_id: str,
    messages: Optional[list[OutboundMessage]] = None,
    reaction: Optional[str] = None,
) -> Speech[LlmResponse]:
    """Build one scripted completed model turn: no tool rounds, straight to speech."""
    outbound = messages or [TextMessage(type="text", text="ok")]
    speech_text = next(
        (m.text for m in outbound if getattr(m, "type", None) == "text"),
        "ok",
    )
    return Speech(
        responseId=response_id,
        items=[],
        parsed=LlmResponse(reaction=reaction, messages=outbound),
        message=AssistantMessage(text=speech_text),
        web=[],
    )


TEXTBOOK_CITATION_RECORD: dict[str, Any] = {
    "id": "source:science-9:p42",
    "label": "Source",
    "props": {
        "kind": "textbook_page",
        "content_source": "ncert",
        "grade": 9,
        "subject": "science",
        "page": 42,
        "book_id": "book:science-9",
        "book_title": "Science Class 9",
        "chapter": "Matter in Our Surroundings",
    },
}

# render_sources output for the single record above, then the WhatsApp footer.
EXPECTED_SOURCES_BODY = "_Sources: Science Class 9: Matter in Our Surroundings 42_"


def citations_responder(records: list[dict[str, Any]]):
    """Graph responder that answers the citations query with the given rows,
    but only when it is asked about at least one node id.

    text_agent's citation-rendering path queries the graph client with
    `state.read_ids` even when that list is empty (no tool call performed a
    read this turn). Returning `records` for an empty `ids` list would script
    retrieval the turn never actually performed -- exactly the harness gap
    flagged in tests/outcomes/UNCERTAINTY.md ("real citation content depends
    on tool-driven reads, which no journey in this suite exercises"). This
    fake now matches that: empty ids -> no rows -> no citations -> no Sources
    footer, honestly reflecting that this suite never drives a real read.
    """

    def respond(text: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return records if params.get("ids") else []

    return respond


def student_profile_input(
    *,
    phone: str,
    name: str = "Test Student",
    institution_id: Optional[str] = "school-dps-001",
    institution_name: str = "Delhi Public School",
    grade: int = 9,
    subjects: Optional[list[str]] = None,
) -> dict[str, Any]:
    """A UserProfileInput body for a student."""
    return {
        "persona": "student",
        "phone": phone,
        "name": name,
        "institution": {"id": institution_id, "name": institution_name},
        "scope": {"grade": grade, "subjects": subjects or ["mathematics", "science"]},
    }


def teacher_profile_input(
    *,
    phone: str,
    name: str = "Test Teacher",
    institution_id: Optional[str] = "school-dps-001",
    institution_name: str = "Delhi Public School",
    grades: Optional[list[int]] = None,
    subjects: Optional[list[str]] = None,
) -> dict[str, Any]:
    """A UserProfileInput body for a teacher."""
    return {
        "persona": "teacher",
        "phone": phone,
        "name": name,
        "institution": {"id": institution_id, "name": institution_name},
        "scope": {"grades": grades or [9, 10], "subjects": subjects or ["mathematics"]},
    }


async def create_user(users_api, profile: dict[str, Any], texts: Optional[list[str]] = None):
    """Create one onboarded user through user_service's real internal route."""
    response = await users_api.post(
        "/internal/users",
        json={"profile": profile, "preOnboardingTexts": texts or []},
    )
    response.raise_for_status()
    return response.json()


async def block_user(users_api, user_id: str) -> None:
    """Block one user through user_service's real blocklist route."""
    response = await users_api.put(f"/internal/blocklist/{user_id}")
    response.raise_for_status()


async def append_transcript(
    users_api,
    user_id: str,
    rows: list[dict[str, Any]],
    *,
    previous_response_id: Optional[str] = None,
    started_at_ms: Optional[int] = None,
    read_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Append transcript rows through user_service's real transcript route."""
    response = await users_api.post(
        f"/internal/users/{user_id}/threads/{K.WHATSAPP_THREAD_KEY}/transcript",
        json={
            "messages": rows,
            "readIds": read_ids or [],
            "startedAtMs": started_at_ms,
        },
    )
    response.raise_for_status()
    return response.json()


def user_row(text: str, created_at_ms: int, turn_id: str = "seed-turn") -> dict[str, Any]:
    """One user-role transcript row body."""
    return {
        "role": "user",
        "createdAtMs": created_at_ms,
        "turnId": turn_id,
        "content": {"type": "text", "text": text},
    }
