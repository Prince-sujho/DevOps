"""Influencer campaign spend: base fee plus a capped, stepwise per-block incentive.

Oracle: user_service influencers._campaign_spend docstring. The README gives
the inputs but no formula, so only the bounds are independently statable.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from infra.clients.users import Payout
from user_service.app.src.influencers import _campaign_spend


@pytest.mark.property
@given(
    base=st.integers(min_value=0, max_value=10_000),
    per_block=st.integers(min_value=0, max_value=5_000),
    block_size=st.integers(min_value=1, max_value=50),
    cap=st.integers(min_value=0, max_value=10_000),
    onboards=st.integers(min_value=0, max_value=500),
)
def test_spend_never_below_base_and_never_above_base_plus_cap(
    base: int, per_block: int, block_size: int, cap: int, onboards: int
) -> None:
    """Invariants only, deliberately not a reimplementation of the block arithmetic."""
    terms = Payout(baseInr=base, perBlockInr=per_block, blockSize=block_size, incentiveCapInr=cap)
    spend = _campaign_spend(terms, onboards)
    assert base <= spend <= base + cap
