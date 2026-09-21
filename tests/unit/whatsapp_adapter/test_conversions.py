"""Which sessions get reported to Meta's Conversions API, and as what.

README only names the CAPI env vars. Independently statable here: report only
when this append opened a session for a user with a click id; `report` must
not await Meta; a failure must not surface on the turn.

Event names (`LeadSubmitted` / `Purchase`) and the `{user}:{ordinal}` natural
key are the reporter's own contract with Meta's Events Manager, not README
sentences. Tests pin them so a silent rename is visible.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from infra.attribution import AdAttribution
from infra.clients.users import AppendTranscriptResult
from whatsapp_adapter.app.src.constants import CONVERSION_CURRENCY, CONVERSION_VALUE
from whatsapp_adapter.app.src.output.conversions import ConversionsReporter

from .factories import student

pytestmark = pytest.mark.asyncio

DATASET_ID = "ds-1"
PAGE_ID = "page-1"
CTWA_CLID = "clid-abc"
STARTED_AT_MS = 1_750_000_000_123


def attributed(ctwa_clid: str | None = CTWA_CLID) -> AdAttribution:
    """One ad click, with or without the click id Meta matches on."""
    return AdAttribution(
        sourceId="ad-1",
        headline="Learn maths on WhatsApp",
        sourceUrl="https://fb.test/ad-1",
        ctwaClid=ctwa_clid,
    )


def opened(ordinal: int | None = 1) -> AppendTranscriptResult:
    """What an append returns; `openedSessionNumber` is None when it opened none."""
    return AppendTranscriptResult(startedAtMs=STARTED_AT_MS, openedSessionNumber=ordinal)


class Wiring:
    """A ConversionsReporter whose transport records requests instead of sending them."""

    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._status = status
        self._error = error
        self.reporter = ConversionsReporter(
            access_token="token", dataset_id=DATASET_ID, page_id=PAGE_ID, api_version="v21.0"
        )
        self.reporter._http = httpx.AsyncClient(
            base_url="https://graph.test/v21.0",
            transport=httpx.MockTransport(self._handle),
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return httpx.Response(self._status, json={"events_received": 1, "fbtrace_id": "tr-1"})

    async def report(self, user=None, result=None) -> None:
        """Report, then let the fire-and-forget task actually run to completion."""
        self.reporter.report(
            user if user is not None else student(attribution=attributed()),
            result if result is not None else opened(1),
        )
        await self.drain()

    async def drain(self) -> None:
        while self.reporter._in_flight:
            await asyncio.gather(*tuple(self.reporter._in_flight))

    @property
    def only_event(self) -> dict:
        """The single posted event, asserting exactly one send happened."""
        assert len(self.requests) == 1, f"expected one POST, got {len(self.requests)}"
        payload = json.loads(self.requests[0].content)
        assert len(payload["data"]) == 1
        return payload["data"][0]


# --------------------------------------------------------------------------
# who gets reported
# --------------------------------------------------------------------------


async def test_an_ad_attributed_user_opening_a_session_is_reported():
    wiring = Wiring()

    await wiring.report()

    assert wiring.only_event["user_data"]["ctwa_clid"] == CTWA_CLID


async def test_an_append_that_opened_no_session_is_not_reported():
    """Only the append that opens a session is a conversion; every later
    append in the same session would double-count it.
    """
    wiring = Wiring()

    await wiring.report(result=opened(None))

    assert wiring.requests == []


async def test_a_user_with_no_ad_attribution_is_not_reported():
    """An organic user has no ad click to attribute the session to."""
    wiring = Wiring()

    await wiring.report(user=student(attribution=None))

    assert wiring.requests == []


async def test_an_ad_click_with_no_click_id_is_not_reported():
    """`ctwaClid` is what Meta matches the conversion back to the ad; without
    it there is nothing to report against.
    """
    wiring = Wiring()

    await wiring.report(user=student(attribution=attributed(ctwa_clid=None)))

    assert wiring.requests == []


# --------------------------------------------------------------------------
# what gets reported
# --------------------------------------------------------------------------


async def test_the_first_session_is_reported_as_a_lead():
    """Meta CAPI name for onboarding. README is silent; pinned so a rename
    in `conversions.py` is visible rather than silently shipping.
    """
    wiring = Wiring()

    await wiring.report(result=opened(1))

    assert wiring.only_event["event_name"] == "LeadSubmitted"


@pytest.mark.parametrize("ordinal", [2, 3, 17])
async def test_every_later_session_is_reported_as_a_purchase(ordinal):
    """Meta CAPI name for a return visit. Distinct from the first-session
    name, which is the independently statable split.
    """
    wiring = Wiring()

    await wiring.report(result=opened(ordinal))

    assert wiring.only_event["event_name"] == "Purchase"


async def test_the_event_time_is_the_session_start_in_whole_seconds():
    """Meta takes Unix seconds; posting milliseconds would date the event
    ~55,000 years out and be rejected as outside the 7-day window.
    """
    wiring = Wiring()

    await wiring.report(result=opened(1))

    assert wiring.only_event["event_time"] == STARTED_AT_MS // 1000


async def test_the_event_id_names_the_user_and_the_session_ordinal():
    """One event per ordinal, so a retry or a duplicate append cannot be
    counted twice: the ordinal alone names the send.
    """
    wiring = Wiring()

    await wiring.report(user=student(user_id="u-9", attribution=attributed()), result=opened(4))

    assert wiring.only_event["event_id"] == "u-9:4"


async def test_the_event_carries_the_page_the_ads_run_under():
    wiring = Wiring()

    await wiring.report()

    assert wiring.only_event["user_data"]["page_id"] == PAGE_ID


async def test_the_event_is_marked_as_business_messaging_on_whatsapp():
    """Meta routes the event by these two fields; a wrong channel silently
    lands the conversion in the wrong ledger.
    """
    wiring = Wiring()

    await wiring.report()

    event = wiring.only_event
    assert event["action_source"] == "business_messaging"
    assert event["messaging_channel"] == "whatsapp"


async def test_every_event_carries_the_constant_value_and_currency():
    """No money changes hands; the value exists only so Meta has a number."""
    wiring = Wiring()

    await wiring.report()

    assert wiring.only_event["custom_data"] == {
        "value": CONVERSION_VALUE,
        "currency": CONVERSION_CURRENCY,
    }


async def test_the_event_is_posted_to_this_datasets_events_endpoint():
    wiring = Wiring()

    await wiring.report()

    assert wiring.requests[0].url.path.endswith(f"/{DATASET_ID}/events")
    assert wiring.requests[0].method == "POST"


# --------------------------------------------------------------------------
# fire-and-forget: reporting never touches the turn
# --------------------------------------------------------------------------


async def test_reporting_does_not_wait_for_meta():
    """`report` is sync on purpose: the turn must not await a reward signal.
    The POST has not happened yet when report returns.
    """
    wiring = Wiring()

    wiring.reporter.report(student(attribution=attributed()), opened(1))

    assert wiring.requests == []

    await wiring.drain()
    assert len(wiring.requests) == 1


async def test_a_scheduled_send_is_held_until_it_settles():
    """asyncio holds tasks weakly, so the reporter keeps its own reference;
    without it the send could be garbage-collected mid-flight.
    """
    wiring = Wiring()

    wiring.reporter.report(student(attribution=attributed()), opened(1))

    assert len(wiring.reporter._in_flight) == 1

    await wiring.drain()
    assert wiring.reporter._in_flight == set()


async def test_a_rejection_from_meta_does_not_raise():
    """This is "the one boundary where failures stop": a rejected conversion
    must not surface anywhere near the turn that triggered it.
    """
    wiring = Wiring(status=400)

    await wiring.report()

    assert len(wiring.requests) == 1


async def test_a_transport_failure_does_not_raise():
    wiring = Wiring(error=httpx.ConnectError("meta unreachable"))

    await wiring.report()

    assert len(wiring.requests) == 1


async def test_a_rejection_is_logged_with_the_event_it_belonged_to(capsys):
    """The log line is the only record a fire-and-forget send leaves, so it
    has to name which event failed.
    """
    wiring = Wiring(error=httpx.ConnectError("meta unreachable"))

    await wiring.report(user=student(user_id="u-9", attribution=attributed()), result=opened(2))

    logged = capsys.readouterr().out
    assert "u-9:2" in logged
    assert "Purchase" in logged
    assert "failed" in logged


async def test_closing_the_reporter_stops_it_from_sending(capsys):
    """Shutdown releases the connection pool, so a later send cannot quietly
    reuse a closed client. It still must not raise -- this is the
    fire-and-forget boundary -- so the refusal shows up as a logged failure.
    """
    wiring = Wiring()

    await wiring.reporter.close()
    await wiring.report()

    assert wiring.requests == []
    assert "failed" in capsys.readouterr().out


async def test_a_successful_send_logs_metas_answer_verbatim(capsys):
    """The body carries fbtrace_id, which is what a Meta support ticket asks
    for; logging a summary instead would lose it.
    """
    wiring = Wiring()

    await wiring.report(result=opened(1))

    logged = capsys.readouterr().out
    assert "tr-1" in logged
    assert "status=200" in logged
