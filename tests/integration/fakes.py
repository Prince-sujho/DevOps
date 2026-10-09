"""In-process stand-ins for Neo4j and GCS — the only non-Firestore, non-Hubble
deps.

Hubble is mocked at the HTTP transport layer (see ``hubble_http.py``), not here.
Firestore is the real emulator. These fakes exist so DELETE and media cleanup
do not try to open a real Neo4j driver or GCS bucket.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable


class FakeGraphClient:
    """Recording stand-in for ``GraphClient``; ``query`` is the only method
    DELETE uses.
    """

    def __init__(self) -> None:
        """No calls recorded, not closed; the default responder returns no rows.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        self.responder: Callable[
            [str, dict[str, Any]], list[dict[str, Any]]
        ] = lambda text, params: []

    def reset(self) -> None:
        """Clear recorded calls and restore the default no-rows responder.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.calls.clear()
        self.closed = False
        self.responder = lambda text, params: []

    async def query(self, text: str, **params: Any) -> list[dict[str, Any]]:
        """Record the call and return whatever the scripted responder returns
        for it.

        Args:
            text: the Cypher query text.
            params: the query's bound parameters.
        Returns:
            Whatever rows the scripted responder returns for this text and
            params.
        Raises:
            None.
        """
        self.calls.append((text, dict(params)))
        return self.responder(text, params)

    async def close(self) -> None:
        """Mark the client closed.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.closed = True


class FakeGcsBucket:
    """In-memory stand-in for ``GcsBucket``; ``delete_prefix`` is what user
    DELETE hits.
    """

    def __init__(self, bucket_name: str = "fake-bucket") -> None:
        """An empty bucket under the given name.

        Args:
            bucket_name: the fake bucket's name, used only in public_url.
        Returns:
            None.
        Raises:
            None.
        """
        self._bucket = bucket_name
        self.objects: dict[str, bytes] = {}

    def reset(self) -> None:
        """Clear all stored objects.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        self.objects.clear()

    async def upload(
        self, object_name: str, data: bytes, content_type: str
    ) -> None:
        """Store data under object_name in memory.

        Args:
            object_name: the key to store the object under.
            data: the object's bytes.
            content_type: ignored; kept to match GcsBucket's real signature.
        Returns:
            None.
        Raises:
            None.
        """
        self.objects[object_name] = data

    async def download(self, object_name: str) -> bytes:
        """Return the previously uploaded bytes for object_name.

        Args:
            object_name: object key whose stored bytes are returned.
        Returns:
            The bytes previously stored under object_name.
        Raises:
            None.
        """
        return self.objects[object_name]

    def public_url(self, object_name: str) -> str:
        """The fake public URL for object_name, in GcsBucket's real URL shape.

        Args:
            object_name: object key to build a public URL for.
        Returns:
            The fake GCS public URL for object_name in this bucket.
        Raises:
            None.
        """
        return f"https://storage.googleapis.com/{self._bucket}/{object_name}"

    async def list_names(self, prefix: str) -> list[str]:
        """Every stored object name starting with prefix.

        Args:
            prefix: object-name prefix to filter on.
        Returns:
            Stored object names that start with prefix.
        Raises:
            None.
        """
        return [name for name in self.objects if name.startswith(prefix)]

    async def delete(self, object_name: str) -> None:
        """Remove object_name if it exists; no-op otherwise.

        Args:
            object_name: object key to remove if it is stored.
        Returns:
            None.
        Raises:
            None.
        """
        self.objects.pop(object_name, None)

    async def delete_prefix(self, prefix: str) -> None:
        """Remove every stored object whose name starts with prefix.

        Args:
            prefix: object-name prefix; every match is removed.
        Returns:
            None.
        Raises:
            None.
        """
        for name in [n for n in self.objects if n.startswith(prefix)]:
            del self.objects[name]

    async def close(self) -> None:
        """No-op close.

        Args:
            None.
        Returns:
            None.
        Raises:
            None.
        """
        return None
