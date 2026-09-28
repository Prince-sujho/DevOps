"""LLM spend: every model we call is priced, and text pricing follows its tier rules.

Oracle: infra/llm/oai/pricing.py and constants.py. Models come from
``OpenAIModels`` and factors from ``SERVICE_TIER_FACTORS``, so a model switch
or a price row needs no edit here — only a broken rule fails.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from infra.llm import OpenAIModels, TextUsage, price
from infra.llm.oai.constants import LONG_CONTEXT_FROM_TOKENS
from infra.llm.oai.rates import rates_at
from infra.llm.oai.types.usage import TextRates
from infra.utils.time import now_ms

CALLED_MODELS = [value for name, value in vars(OpenAIModels).items() if name.isupper()]
NOW_MS = now_ms()
TEXT_MODELS = [model for model in CALLED_MODELS if isinstance(rates_at(model, NOW_MS), TextRates)]


@pytest.mark.boundary
@pytest.mark.parametrize("model", CALLED_MODELS)
def test_every_model_the_product_calls_has_a_rate_in_force_today(model: str) -> None:
    """A model switch without a rate-card row would make every ledger read fail to price."""
    rates_at(model, NOW_MS)


@st.composite
def text_usage_tokens(draw) -> dict:
    input_tokens = draw(st.integers(min_value=0, max_value=2 * LONG_CONTEXT_FROM_TOKENS))
    cached = draw(st.integers(min_value=0, max_value=input_tokens))
    cache_write = draw(st.integers(min_value=0, max_value=input_tokens - cached))
    return {
        "inputTokens": input_tokens,
        "cachedTokens": cached,
        "cacheWriteTokens": cache_write,
        "outputTokens": draw(st.integers(min_value=0, max_value=200_000)),
        "reasoningTokens": 0,
        "webSearchCalls": draw(st.integers(min_value=0, max_value=20)),
    }


@pytest.mark.property
@given(tokens=text_usage_tokens(), model=st.sampled_from(TEXT_MODELS))
def test_text_pricing_follows_context_and_service_tier_rules(tokens: dict, model: str) -> None:
    """Long tier iff input crosses the threshold; a service tier scales token cost, never the search fee.

    The default/flex ratio is pinned to the literal 0.5 from rates.py's own
    comment ("Flex bills at Batch rates, half of Standard") rather than
    re-derived from SERVICE_TIER_FACTORS: deriving the expectation from the
    same dict the code under test reads would make a change to that dict
    invisible to this assertion.
    """
    default = price(TextUsage(model=model, responseId="r", serviceTier="default", **tokens), NOW_MS)
    flex = price(TextUsage(model=model, responseId="r", serviceTier="flex", **tokens), NOW_MS)
    for row in (default, flex):
        assert row.tier == ("long" if tokens["inputTokens"] > LONG_CONTEXT_FROM_TOKENS else "short")
        assert min(row.input, row.cached, row.cacheWrite, row.output, row.webSearch) >= 0
    assert flex.webSearch == default.webSearch
    assert flex.total - flex.webSearch == pytest.approx((default.total - default.webSearch) * 0.5)
