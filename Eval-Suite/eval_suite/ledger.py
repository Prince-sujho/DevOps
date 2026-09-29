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


def user_row(
    prompt: str, turn_id: str, created_at_ms: int
) -> UserTranscriptMessage:
    """The transcript row for the user's own message in a turn.

    Args:
        prompt: the user's message text.
        turn_id: this turn's id.
        created_at_ms: when the turn started, epoch ms.
    Returns:
        The row.
    Raises:
        None.
    """
    return UserTranscriptMessage(
        createdAtMs=created_at_ms,
        turnId=turn_id,
        content=TextContent(text=prompt),
    )


def trace_rows(
    round: Round, turn_id: str, created_at_ms: int
) -> list[TraceTranscriptMessage]:
    """The transcript rows recording one tool-call round's raw items.

    Args:
        round: one round of the model's tool-call/response loop.
        turn_id: the turn this round happened in.
        created_at_ms: when the turn started, epoch ms.
    Returns:
        One row per item in round.
    Raises:
        None.
    """
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
    """The transcript rows for the assistant's visible reply contents.

    Args:
        contents: the response's visible content items.
        turn_id: this turn's id.
        response_id: the model response id these contents came from, if any.
        created_at_ms: when the turn started, epoch ms.
    Returns:
        One row per item in contents.
    Raises:
        None.
    """
    return [
        AssistantTranscriptMessage(
            createdAtMs=created_at_ms,
            turnId=turn_id,
            responseId=response_id,
            content=content,
        )
        for content in contents
    ]
