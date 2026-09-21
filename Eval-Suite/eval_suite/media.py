"""Disk bucket with the GcsBucket methods ConversationMediaStore calls."""

from __future__ import annotations

from pathlib import Path


class EvalMediaBucket:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        if not data:
            raise ValueError(f"refusing empty upload: {object_name}")
        path = self._root / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def exists(self, object_name: str) -> bool:
        return (self._root / object_name).is_file()

    async def download(self, object_name: str) -> bytes:
        path = self._root / object_name
        data = path.read_bytes()
        if not data:
            raise ValueError(f"empty object: {object_name}")
        return data

    async def delete_prefix(self, prefix: str) -> int:
        base = self._root / prefix
        if not base.exists():
            return 0
        paths = [path for path in base.rglob("*") if path.is_file()]
        for path in paths:
            path.unlink()
        return len(paths)

    def public_url(self, object_name: str) -> str:
        return (self._root / object_name).resolve().as_uri()
