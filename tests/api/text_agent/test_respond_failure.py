"""Failure paths for POST /respond: upstream LLM errors and unsupported media.

There is no try/except around the model call, so an upstream failure must not
report success. `UriMediaContent` is images and documents only — the adapter
transcribes voice notes and degrades video before a row reaches /respond.
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers, respond_body

pytestmark = pytest.mark.asyncio

MEDIA_URI = "https://storage.googleapis.com/sujho-conversation-media/users/u1/abc123"


async def test_llm_failure_does_not_return_success(client, fakes):
    fakes.openai.script.append(RuntimeError("upstream OpenAI Responses API failure"))

    response = await client.post("/respond", json=respond_body(), headers=auth_headers())

    assert response.status_code >= 400


@pytest.mark.parametrize("kind", ["audio", "video"])
async def test_unsupported_media_part_is_rejected_on_respond(client, fakes, kind):
    body = respond_body(
        rows=[
            {
                "role": "user",
                "createdAtMs": 1710000000000,
                "turnId": "wamid.test.1",
                "content": {"type": kind, "uri": MEDIA_URI, "filename": f"abc123.{kind}"},
            }
        ]
    )

    response = await client.post("/respond", json=body, headers=auth_headers())

    assert response.status_code == 422
    assert fakes.openai.calls == []
