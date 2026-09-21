"""Grade Flow data-exchange: ping, INIT, and completion forwarding.

README: POST /flows/grade is the encrypted data endpoint; a grade form
completion must fetch the uploaded papers/sheets. This module is what
forwards those slots off the Flow and onto the webhook as
`extension_message_response` params — drop `**payload["data"]` and the
completion arrives empty.

Screen ids are Meta Flow pins, handwritten.
"""

from __future__ import annotations

import pytest

from whatsapp_adapter.app.src.flows.grade import grade_response_payload

pytestmark = pytest.mark.boundary


def test_a_ping_reports_the_endpoint_active():
    assert grade_response_payload({"action": "ping"}) == {"data": {"status": "active"}}


def test_init_opens_on_the_question_paper_screen():
    response = grade_response_payload({"action": "INIT"})

    assert response["screen"] == "QUESTION_PAPER"
    assert response["data"] == {}


def test_data_exchange_completes_the_flow_with_the_uploaded_slots():
    """The webhook later keys on `route: grade` and reads the same slot
    names the Flow collected. A hardcoded token or dropped data would
    grade the wrong turn, or none.
    """
    response = grade_response_payload(
        {
            "action": "data_exchange",
            "flow_token": "grade-turn-9",
            "data": {
                "question_paper": [{"media_id": "qp-1"}],
                "rubric": [],
                "answer_sheets": [{"media_id": "a1"}],
            },
        }
    )

    assert response["screen"] == "SUCCESS"
    params = response["data"]["extension_message_response"]["params"]
    assert params["flow_token"] == "grade-turn-9"
    assert params["route"] == "grade"
    assert params["question_paper"] == [{"media_id": "qp-1"}]
    assert params["rubric"] == []
    assert params["answer_sheets"] == [{"media_id": "a1"}]


def test_an_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="Unsupported grade flow action"):
        grade_response_payload({"action": "COMPLETE"})
