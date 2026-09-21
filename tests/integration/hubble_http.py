"""Hubble partners API double at the httpx transport layer.

The real ``HubbleClient`` is constructed and used. Only the TCP/HTTP hop is
replaced: ``httpx.MockTransport`` answers the documented partners-API paths
(``POST /v1/partners/auth/login``, ``GET /v1/partners/products/{id}``,
``POST /v1/partners/orders``, ``GET /v1/partners/orders/by-reference/{id}``).
No HubbleClient method is stubbed.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Literal, Optional

import httpx

PlaceOrderMode = Literal["respond", "timeout"]


class HubbleHttpDouble:
    """Scriptable Hubble partners-API at the HTTP transport layer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.products: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, Optional[dict[str, Any]]] = {}
        # When set, POST /orders stores this body under the request's referenceId
        # (and optionally then raises TimeoutException, simulating a lost response
        # after Hubble accepted the mint).
        self.place_order_body: Optional[dict[str, Any]] = None
        self.place_order_mode: PlaceOrderMode = "respond"
        self.place_order_calls: list[dict[str, Any]] = []
        self.get_order_calls: list[str] = []
        self.requests: list[tuple[str, str]] = []

    def reset(self) -> None:
        """Clear scripts and recorded calls between tests. Catalogue is re-seeded by the test."""
        with self._lock:
            self.products.clear()
            self.orders.clear()
            self.place_order_body = None
            self.place_order_mode = "respond"
            self.place_order_calls.clear()
            self.get_order_calls.clear()
            self.requests.clear()

    def seed_catalogue(self, products: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self.products = dict(products)

    def set_order(self, reference_id: str, body: Optional[dict[str, Any]]) -> None:
        """``None`` means GET by-reference returns 404."""
        with self._lock:
            self.orders[reference_id] = body

    def handler(self, request: httpx.Request) -> httpx.Response:
        """httpx.MockTransport callback — real request in, real Response out."""
        path = request.url.path
        method = request.method.upper()
        with self._lock:
            self.requests.append((method, path))

        if method == "POST" and path.endswith("/v1/partners/auth/login"):
            return httpx.Response(
                200, json={"token": "test-hubble-token", "expiresInSecs": 3600}
            )

        if method == "GET" and "/v1/partners/products/" in path:
            product_id = path.rsplit("/", 1)[-1]
            with self._lock:
                product = self.products.get(product_id)
            if product is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=product)

        if method == "POST" and path.endswith("/v1/partners/orders"):
            payload = json.loads(request.content.decode("utf-8"))
            with self._lock:
                self.place_order_calls.append(payload)
                body = self.place_order_body
                mode = self.place_order_mode
                if body is not None:
                    self.orders[payload["referenceId"]] = body
            if mode == "timeout":
                # Order is already recorded as created upstream; the client never
                # sees the HTTP response (lost-response settlement case).
                raise httpx.TimeoutException("lost Hubble place_order response")
            if body is None:
                return httpx.Response(500, json={"error": "place_order not scripted"})
            return httpx.Response(200, json=body)

        if method == "GET" and "/v1/partners/orders/by-reference/" in path:
            reference_id = path.rsplit("/", 1)[-1]
            with self._lock:
                self.get_order_calls.append(reference_id)
                order = self.orders[reference_id] if reference_id in self.orders else None
                missing = reference_id not in self.orders
            if missing or order is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=order)

        return httpx.Response(404, json={"error": f"unscripted Hubble path {method} {path}"})
