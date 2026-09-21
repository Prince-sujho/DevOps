"""Transcript rows the runner appends around each respond() call."""

from __future__ import annotations

from infra.clients.users import (
    AssistantContent,
    AssistantTranscriptMessage,
    TraceTranscriptMessage,
    UserTranscriptMessage,
)
from infra.llm.content import TextContent
from infra.llm.oai.types.responses import Round


def user_row(prompt: str, turn_id: str, created_at_ms: int) -> UserTranscriptMessage:
    return UserTranscriptMessage(
        createdAtMs=created_at_ms,
        turnId=turn_id,
        content=TextContent(text=prompt),
    )


def trace_rows(round: Round, turn_id: str, created_at_ms: int) -> list[TraceTranscriptMessage]:
    return [
        TraceTranscriptMessage(
            createdAtMs=created_at_ms,
            turnId=turn_id,
            responseId=round.responseId,
            content=item,
        )
        for item in round.items
    ]


def assistant_rows(
    contents: list[AssistantContent],
    turn_id: str,
    response_id: str | None,
    created_at_ms: int,
) -> list[AssistantTranscriptMessage]:
    return [
        AssistantTranscriptMessage(
            createdAtMs=created_at_ms,
            turnId=turn_id,
            responseId=response_id,
            content=content,
        )
        for content in contents
    ]
