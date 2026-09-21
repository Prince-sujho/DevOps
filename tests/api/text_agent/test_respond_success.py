"""Success-path test for POST /respond: plain text reply, no tools invoked.

README Response Format: `contents` (what the adapter delivers), `readIds`,
`actions`, `thought`, `usage`. A no-tool turn has one text content and empty
readIds.
"""

import pytest

from .conftest import auth_headers, respond_body, scripted_turn


@pytest.mark.asyncio
async def test_plain_text_reply_returns_documented_shape(client, fakes):
    fakes.openai.script.append(scripted_turn("Here's the answer...", "resp_fake_001"))

    response = await client.post("/respond", json=respond_body(), headers=auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["contents"] == [{"type": "text", "text": "Here's the answer..."}]
    assert body["readIds"] == []
    assert body["actions"] == []
    assert body["thought"] == {"responseId": "resp_fake_001", "items": []}
    assert body["usage"] == []
