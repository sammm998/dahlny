"""Fillagring för originalfiler och renderingar (SPEC 4: S3-kompatibel, MinIO lokalt).

`LocalStorage` används i utveckling och tester. S3/MinIO-adaptern läggs till när objektlagringen tas i drift;
gränssnittet är detsamma.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def _safe_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Ogiltig lagringsnyckel: {key!r}")
    return path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*_safe_key(key).parts)

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
