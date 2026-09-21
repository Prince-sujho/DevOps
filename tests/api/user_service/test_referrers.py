"""POST /internal/referrers/{handle}/click: kind-agnostic click tracking."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_click_on_registered_influencer_handle_records_one_row(client, auth_headers, fakes):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "clickme", "platform": "instagram"}
    )
    response = await client.post("/internal/referrers/clickme/click", headers=auth_headers)
    assert response.status_code == 204
    assert len(fakes.clicks.rows_for("clickme")) == 1


async def test_click_on_registered_ambassador_handle_records_one_row(client, auth_headers, fakes):
    fakes.referrers.seed_ambassador("ambo-x4k9", user_id="u1", created_at_ms=1_700_000_000_000)
    response = await client.post("/internal/referrers/ambo-x4k9/click", headers=auth_headers)
    assert response.status_code == 204
    assert len(fakes.clicks.rows_for("ambo-x4k9")) == 1


async def test_click_on_unknown_handle_is_a_no_op_but_still_succeeds(client, auth_headers, fakes):
    """README: 'no-op for unknown handle' -- committing to 200-class success regardless."""
    response = await client.post("/internal/referrers/never-registered/click", headers=auth_headers)
    assert response.status_code == 204, (
        f"README says clicks on unknown handles are a no-op, implying the call still succeeds; "
        f"got {response.status_code}"
    )
    assert fakes.clicks.rows_for("never-registered") == [], (
        "an unknown handle must not create a click document"
    )


async def test_click_normalizes_handle_case_and_at_sign(client, auth_headers, fakes):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "MixedCase", "platform": "youtube"}
    )
    response = await client.post("/internal/referrers/@MixedCase/click", headers=auth_headers)
    assert response.status_code == 204
    assert len(fakes.clicks.rows_for("mixedcase")) == 1
