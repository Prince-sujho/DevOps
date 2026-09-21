"""Influencer registry, campaigns, and derived reports."""

from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


async def test_create_influencer_shape(client, auth_headers):
    response = await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "@Coolkid", "platform": "instagram"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["handle"] == "coolkid"
    assert body["platform"] == "instagram"
    assert body["kind"] == "influencer"


async def test_create_influencer_422_missing_field(client, auth_headers):
    response = await client.post("/internal/influencers", headers=auth_headers, json={"handle": "x"})
    assert response.status_code == 422


async def test_create_influencer_422_empty_handle(client, auth_headers):
    response = await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "@@@", "platform": "youtube"}
    )
    assert response.status_code == 422


async def test_create_influencer_409_on_collision_with_existing_influencer_handle(client, auth_headers):
    """README: 'Register one influencer (409 if the handle collides in the referrer namespace)'."""
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "dupe", "platform": "instagram"}
    )
    response = await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "dupe", "platform": "youtube"}
    )
    assert response.status_code == 409, (
        f"README documents 409 on handle collision; got {response.status_code}: {response.text}"
    )


async def test_create_influencer_409_on_collision_with_existing_ambassador_handle(
    client, auth_headers, fakes
):
    """README: influencer and ambassador handles share one namespace; a collision either way is 409."""
    fakes.referrers.seed_ambassador("sharedname", user_id="some-user", created_at_ms=1_700_000_000_000)
    response = await client.post(
        "/internal/influencers",
        headers=auth_headers,
        json={"handle": "sharedname", "platform": "instagram"},
    )
    assert response.status_code == 409, (
        f"README documents the @-mention namespace as shared across kinds; "
        f"got {response.status_code}: {response.text}"
    )


async def test_get_influencer_report_404_for_unknown_handle(client, auth_headers):
    response = await client.get("/internal/influencers/no-such-handle", headers=auth_headers)
    assert response.status_code == 404


async def test_get_influencer_report_shape_empty(client, auth_headers):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "reportee", "platform": "youtube"}
    )
    response = await client.get("/internal/influencers/reportee", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["handle"] == "reportee"
    assert body["platform"] == "youtube"
    assert body["campaigns"] == []
    assert body["miscellaneous"] == {"clicks": 0, "started": 0, "onboards": 0, "retained": 0}
    assert body["referrals"] == []


async def test_list_influencers_includes_every_registered_handle(client, auth_headers):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "one", "platform": "instagram"}
    )
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "two", "platform": "youtube"}
    )
    response = await client.get("/internal/influencers", headers=auth_headers)
    assert response.status_code == 200
    handles = {row["handle"] for row in response.json()}
    assert handles == {"one", "two"}


def _payout(base=100, per_block=10, block_size=5, cap=200):
    return {"baseInr": base, "perBlockInr": per_block, "blockSize": block_size, "incentiveCapInr": cap}


async def test_create_campaign_shape(client, auth_headers):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "camper", "platform": "instagram"}
    )
    response = await client.post(
        "/internal/influencers/camper/campaigns",
        headers=auth_headers,
        json={"startMs": 1_000, "endMs": 2_000, "payout": _payout()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["startMs"] == 1_000
    assert body["endMs"] == 2_000
    assert body["payout"] == _payout()


async def test_create_campaign_404_for_unknown_handle(client, auth_headers):
    response = await client.post(
        "/internal/influencers/no-such-handle/campaigns",
        headers=auth_headers,
        json={"startMs": 1_000, "endMs": 2_000, "payout": _payout()},
    )
    assert response.status_code == 404


async def test_create_campaign_422_start_not_before_end(client, auth_headers):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "badwindow", "platform": "instagram"}
    )
    response = await client.post(
        "/internal/influencers/badwindow/campaigns",
        headers=auth_headers,
        json={"startMs": 2_000, "endMs": 2_000, "payout": _payout()},
    )
    assert response.status_code == 422


@pytest_asyncio.fixture
async def influencer_with_campaign(client, auth_headers):
    """One influencer with an existing campaign window [10_000, 20_000]."""
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "windowed", "platform": "instagram"}
    )
    await client.post(
        "/internal/influencers/windowed/campaigns",
        headers=auth_headers,
        json={"startMs": 10_000, "endMs": 20_000, "payout": _payout()},
    )
    return "windowed"


async def test_campaign_overlap_identical_window_is_409(client, auth_headers, influencer_with_campaign):
    """README: 'Create one campaign window (409 on overlap)'."""
    response = await client.post(
        f"/internal/influencers/{influencer_with_campaign}/campaigns",
        headers=auth_headers,
        json={"startMs": 10_000, "endMs": 20_000, "payout": _payout()},
    )
    assert response.status_code == 409, (
        f"identical window must be rejected as an overlap; got {response.status_code}: {response.text}"
    )


async def test_campaign_overlap_partial_at_start_is_409(client, auth_headers, influencer_with_campaign):
    response = await client.post(
        f"/internal/influencers/{influencer_with_campaign}/campaigns",
        headers=auth_headers,
        json={"startMs": 5_000, "endMs": 15_000, "payout": _payout()},
    )
    assert response.status_code == 409, (
        f"window overlapping the start must be rejected; got {response.status_code}: {response.text}"
    )


async def test_campaign_overlap_partial_at_end_is_409(client, auth_headers, influencer_with_campaign):
    response = await client.post(
        f"/internal/influencers/{influencer_with_campaign}/campaigns",
        headers=auth_headers,
        json={"startMs": 15_000, "endMs": 25_000, "payout": _payout()},
    )
    assert response.status_code == 409, (
        f"window overlapping the end must be rejected; got {response.status_code}: {response.text}"
    )


async def test_campaign_overlap_fully_containing_is_409(client, auth_headers, influencer_with_campaign):
    response = await client.post(
        f"/internal/influencers/{influencer_with_campaign}/campaigns",
        headers=auth_headers,
        json={"startMs": 5_000, "endMs": 25_000, "payout": _payout()},
    )
    assert response.status_code == 409, (
        f"a window fully containing the existing one must be rejected; "
        f"got {response.status_code}: {response.text}"
    )


async def test_campaign_adjacent_non_overlapping_window_succeeds(
    client, auth_headers, influencer_with_campaign
):
    """Windows are inclusive [startMs, endMs]; adjacent (start == existing.endMs + 1) must succeed."""
    response = await client.post(
        f"/internal/influencers/{influencer_with_campaign}/campaigns",
        headers=auth_headers,
        json={"startMs": 20_001, "endMs": 30_000, "payout": _payout()},
    )
    assert response.status_code == 200, (
        f"an adjacent, non-overlapping window must succeed; got {response.status_code}: {response.text}"
    )


async def test_delete_campaign_204(client, auth_headers, influencer_with_campaign):
    response = await client.delete(
        f"/internal/influencers/{influencer_with_campaign}/campaigns/10000_20000", headers=auth_headers
    )
    assert response.status_code == 204


async def test_delete_influencer_204_and_report_then_404s(client, auth_headers):
    await client.post(
        "/internal/influencers", headers=auth_headers, json={"handle": "gone-soon", "platform": "instagram"}
    )
    response = await client.delete("/internal/influencers/gone-soon", headers=auth_headers)
    assert response.status_code == 204
    after = await client.get("/internal/influencers/gone-soon", headers=auth_headers)
    assert after.status_code == 404
