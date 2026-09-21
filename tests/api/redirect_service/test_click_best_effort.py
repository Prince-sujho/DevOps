"""GET /go/{handle} — best-effort click logging.

Spec (redirect_service/README.md):
  - "Click logging is scheduled after the redirect response and calls
    POST /internal/referrers/{handle}/click on user_service, which normalizes
    the handle and is a no-op for unregistered ones."
  - "The service knows nothing: it always sends the user to WhatsApp, even if
    click logging fails."

These two tests verify, respectively, that a failing click-log call never
surfaces to the caller, and that a successful one really does record exactly
one call with the handle.

Mechanism note (see UNCERTAINTY report): empirically, httpx's ASGITransport
awaits the whole Starlette `Response.__call__` — including its attached
`BackgroundTasks` — before returning control to the test, so by the time
`async_client.get(...)` returns without error, the background click-logging
call has already run.

That same buffering is a problem for the *failure* case specifically: when
the background task raises, ASGITransport propagates that exception out of
`client.get(...)` instead of handing back the 302 response object — even
though, at the raw ASGI-message level, Starlette's `Response.__call__` had
already sent `http.response.start` (302, correct Location header) and
`http.response.body` (empty body) to the `send` callable *before* it awaited
the background task and let the exception through. That send-then-run-
background ordering is exactly what makes a real deployed server (uvicorn)
client-safe: the client socket already has the 302 by the time the
background task's exception is merely logged server-side. httpx's in-process
ASGITransport doesn't preserve that distinction because it only constructs
an `httpx.Response` after the whole app-call coroutine returns cleanly.

So the failure-path test below drives the ASGI app directly (bypassing
httpx.AsyncClient/ASGITransport) with a manual `receive`/`send` pair and
inspects the raw messages, which is the only way to verify, at the boundary
that actually matters for the "even if click logging fails" contract, that
the 302 was already fully sent before the background exception surfaced.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from .conftest import FakeUsersClient
from .test_redirect import _expected_location

pytestmark = pytest.mark.asyncio

POLL_TIMEOUT_S = 2.0
POLL_INTERVAL_S = 0.05


async def _wait_until(predicate, timeout_s: float = POLL_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(POLL_INTERVAL_S)
    return predicate()


async def test_click_logging_failure_does_not_break_redirect(
    async_client: httpx.AsyncClient,
    fake_users_client: FakeUsersClient,
) -> None:
    """Documents the httpx.ASGITransport limitation: a background-task
    exception propagates out of the client call instead of yielding the 302
    that was already sent at the ASGI level. See module docstring and the
    raw-ASGI test below for the assertion that actually verifies the
    "even if click logging fails" contract.
    """
    fake_users_client.fail_next_click_with(RuntimeError("user_service is down"))

    with pytest.raises(RuntimeError, match="user_service is down"):
        await async_client.get("/go/shreya")


async def test_click_logging_failure_302_already_sent_at_asgi_level(
    app: FastAPI,
    fake_users_client: FakeUsersClient,
) -> None:
    """The real contract check: drive the ASGI app directly so we can see the
    raw messages sent to `send`, proving the 302 (with correct Location) and
    the response body were fully transmitted before the background task's
    exception ever surfaced — i.e. a real client/server would have already
    received the redirect regardless of click-logging failure.
    """
    fake_users_client.fail_next_click_with(RuntimeError("user_service is down"))

    sent_messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/go/shreya",
        "raw_path": b"/go/shreya",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
    }

    async with app.router.lifespan_context(app):
        with pytest.raises(RuntimeError, match="user_service is down"):
            await app(scope, receive, send)

    start_messages = [m for m in sent_messages if m["type"] == "http.response.start"]
    body_messages = [m for m in sent_messages if m["type"] == "http.response.body"]

    assert len(start_messages) == 1
    assert start_messages[0]["status"] == 302
    headers = {k.decode(): v.decode() for k, v in start_messages[0]["headers"]}
    assert headers["location"] == _expected_location("shreya")

    assert len(body_messages) == 1
    assert body_messages[0]["body"] == b""


async def test_click_logging_success_records_exactly_one_call(
    async_client: httpx.AsyncClient,
    fake_users_client: FakeUsersClient,
) -> None:
    response = await async_client.get("/go/shreya")
    assert response.status_code == 302

    completed = await _wait_until(lambda: len(fake_users_client.calls) >= 1)

    assert completed, "click-logging background task never completed within timeout"
    assert fake_users_client.calls == ["shreya"]
