"""Route enumeration shared by every service's auth-boundary test."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.routing import APIRoute

from infra.api import ops_router

PUBLIC_ROUTES = frozenset(
    (method, route.path)
    for route in ops_router.routes
    if isinstance(route, APIRoute)
    for method in route.methods
)


def _concrete(path: str) -> str:
    """Substitute a syntactically plausible dummy value for every {param}."""
    return re.sub(r"\{[^{}]+\}", "x", path)


def guarded_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, concrete path) the app serves, minus the shared public ops routes."""
    pairs = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if (method.upper(), path) not in PUBLIC_ROUTES:
                pairs.append((method.upper(), _concrete(path)))
    return pairs
