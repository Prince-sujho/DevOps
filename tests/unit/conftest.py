"""Unit-suite pytest hooks. Registers the required property/boundary markers."""

from __future__ import annotations

import pytest
from hypothesis import settings

settings.register_profile("unit", max_examples=80, deadline=None)
settings.load_profile("unit")


def pytest_configure(config: pytest.Config) -> None:
    """Register the property/boundary markers used across tests/unit.

    Args:
        config: pytest's Config object for this session.
    Returns:
        None.
    Raises:
        None.
    """
    config.addinivalue_line(
        "markers", "property: Hypothesis property-based test"
    )
    config.addinivalue_line(
        "markers", "boundary: hand-written boundary / named-case test"
    )
