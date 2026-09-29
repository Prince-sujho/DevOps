"""Disk bucket with the GcsBucket methods ConversationMediaStore calls."""

from __future__ import annotations

from pathlib import Path


class EvalMediaBucket:
    """Local-disk stand-in for infra.platform.storage.GcsBucket, for eval runs
    only.
    """

    def __init__(self, root: Path) -> None:
        """Create (if needed) and bind to a local directory as the bucket root.

        Args:
            root: the directory to store objects under.
        Returns:
            None.
        Raises:
            None.
        """
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    async def upload(
        self, object_name: str, data: bytes, content_type: str
    ) -> None:
        """Write data to disk under object_name.

        Args:
            object_name: the object's path relative to root.
            data: the bytes to write.
            content_type: unused here; kept to match GcsBucket's signature.
        Returns:
            None.
        Raises:
            ValueError: data is empty.
        """
        if not data:
            raise ValueError(f"refusing empty upload: {object_name}")
        path = self._root / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def exists(self, object_name: str) -> bool:
        """Whether object_name has been uploaded.

        Args:
            object_name: the object's path relative to root.
        Returns:
            True if the file exists on disk.
        Raises:
            None.
        """
        return (self._root / object_name).is_file()

    async def download(self, object_name: str) -> bytes:
        """Read object_name's bytes back from disk.

        Args:
            object_name: the object's path relative to root.
        Returns:
            The stored bytes.
        Raises:
            FileNotFoundError: object_name was never uploaded.
            ValueError: the stored file is empty.
        """
        path = self._root / object_name
        data = path.read_bytes()
        if not data:
            raise ValueError(f"empty object: {object_name}")
        return data

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every file under prefix.

        Args:
            prefix: the path prefix, relative to root, to delete recursively.
        Returns:
            How many files were deleted (0 if prefix doesn't exist).
        Raises:
            None.
        """
        base = self._root / prefix
        if not base.exists():
            return 0
        paths = [path for path in base.rglob("*") if path.is_file()]
        for path in paths:
            path.unlink()
        return len(paths)

    def public_url(self, object_name: str) -> str:
        """A file:// URL for object_name, matching GcsBucket.public_url's shape.

        Args:
            object_name: the object's path relative to root.
        Returns:
            The absolute file:// URI.
        Raises:
            None.
        """
        return (self._root / object_name).resolve().as_uri()
