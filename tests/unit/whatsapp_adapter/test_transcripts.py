"""Stamping wire objects into transcript rows.

These builders decide three things per row: its role, the response it is
attributed to, and the millisecond that orders it within its turn.
"""

from __future__ import annotations

import pytest

from infra.clients.text_agent import Message
from infra.conversation import TextMessage
from infra.llm import Round
from infra.llm.content import TextContent
from infra.llm.oai.types.trace import ReasoningItem
from whatsapp_adapter.app.src.transcripts import assistant_rows, trace_rows, user_rows

pytestmark = pytest.mark.boundary

TURN_ID = "wamid.TURN1"
RESPONSE_ID = "resp_1"


def reasoning(item_id: str) -> ReasoningItem:
    return ReasoningItem(id=item_id, summary=[], encrypted_content="enc")


def test_each_inbound_part_becomes_one_user_row_in_order():
    message = Message(parts=[TextContent(text="first"), TextContent(text="second")])
    rows = user_rows(message, TURN_ID)

    assert [row.role for row in rows] == ["user", "user"]
    assert [row.content.text for row in rows] == ["first", "second"]


def test_rows_from_one_call_are_one_millisecond_apart_so_they_keep_their_order():
    """The offset is what orders parts of a single turn; equal stamps would not."""
    message = Message(parts=[TextContent(text=str(index)) for index in range(3)])
    stamps = [row.createdAtMs for row in user_rows(message, TURN_ID)]

    assert stamps == [stamps[0], stamps[0] + 1, stamps[0] + 2]


def test_user_rows_are_attributed_to_no_response_because_the_user_wrote_them():
    rows = user_rows(Message(parts=[TextContent(text="hi")]), TURN_ID)
    assert rows[0].responseId is None


def test_every_row_carries_the_inbound_message_id_of_its_turn():
    rows = user_rows(Message(parts=[TextContent(text="hi")]), TURN_ID)
    assert rows[0].turnId == TURN_ID


def test_trace_rows_are_attributed_to_the_round_that_emitted_them():
    round_ = Round(responseId=RESPONSE_ID, items=[reasoning("rs_1"), reasoning("rs_2")])
    rows = trace_rows(round_, TURN_ID)

    assert [row.role for row in rows] == ["trace", "trace"]
    assert [row.responseId for row in rows] == [RESPONSE_ID, RESPONSE_ID]
    assert [row.content.id for row in rows] == ["rs_1", "rs_2"]


def test_assistant_rows_are_attributed_to_the_response_that_spoke_them():
    rows = assistant_rows([TextMessage(type="text", text="here you go")], TURN_ID, RESPONSE_ID)

    assert rows[0].role == "assistant"
    assert rows[0].responseId == RESPONSE_ID


def test_assistant_rows_with_no_response_are_the_ones_no_round_spoke():
    """Canned replies are delivered as assistant rows but belong to no response."""
    rows = assistant_rows([TextMessage(type="text", text="Hi!")], TURN_ID, None)
    assert rows[0].responseId is None


def test_nothing_to_stamp_produces_no_rows():
    assert user_rows(Message(parts=[]), TURN_ID) == []
    assert trace_rows(Round(responseId=RESPONSE_ID, items=[]), TURN_ID) == []
    assert assistant_rows([], TURN_ID, RESPONSE_ID) == []


def test_stamping_does_not_assign_a_sequence_because_the_store_does_that():
    rows = user_rows(Message(parts=[TextContent(text="hi")]), TURN_ID)
    assert rows[0].sequence is None
