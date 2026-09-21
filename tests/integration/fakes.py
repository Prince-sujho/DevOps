"""In-process stand-ins for Neo4j and GCS — the only non-Firestore, non-Hubble deps.

Hubble is mocked at the HTTP transport layer (see ``hubble_http.py``), not here.
Firestore is the real emulator. These fakes exist so DELETE and media cleanup
do not try to open a real Neo4j driver or GCS bucket.
"""

from __future__ import annotations

from typing import Any, Callable


class FakeGraphClient:
    """Recording stand-in for ``GraphClient``; ``query`` is the only method DELETE uses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.responder: Callable[[str, dict[str, Any]], list[dict[str, Any]]] = (
            lambda text, params: []
        )

    def reset(self) -> None:
        self.calls.clear()
        self.closed = False
        self.responder = lambda text, params: []

    async def query(self, text: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append((text, dict(params)))
        return self.responder(text, params)

    async def close(self) -> None:
        self.closed = True


class FakeGcsBucket:
    """In-memory stand-in for ``GcsBucket``; ``delete_prefix`` is what user DELETE hits."""

    def __init__(self, bucket_name: str = "fake-bucket") -> None:
        self._bucket = bucket_name
        self.objects: dict[str, bytes] = {}

    def reset(self) -> None:
        self.objects.clear()

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        self.objects[object_name] = data

    async def download(self, object_name: str) -> bytes:
        return self.objects[object_name]

    def public_url(self, object_name: str) -> str:
        return f"https://storage.googleapis.com/{self._bucket}/{object_name}"

    async def list_names(self, prefix: str) -> list[str]:
        return [name for name in self.objects if name.startswith(prefix)]

    async def delete(self, object_name: str) -> None:
        self.objects.pop(object_name, None)

    async def delete_prefix(self, prefix: str) -> None:
        for name in [n for n in self.objects if n.startswith(prefix)]:
            del self.objects[name]

    async def close(self) -> None:
        return None
