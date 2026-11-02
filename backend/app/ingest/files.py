"""Uppackning av uppladdningar och filtypsbestämning (SPEC 6.1.1–2).

Filtyp bestäms från innehållet (magiska bytes), inte från filändelsen. ZIP-arkiv packas upp med skydd mot
sökvägar utanför arkivet och mot orimliga storlekar.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from app.config.settings import load_thresholds

FileKind = Literal["pdf", "image", "dwg", "dxf", "ifc", "zip", "unknown"]


@dataclass(frozen=True)
class InputFile:
    filename: str
    data: bytes
    kind: FileKind

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class UnsafeArchiveError(ValueError):
    """Arkivet innehåller sökvägar utanför sig självt eller överskrider storleksgränserna."""


def detect_kind(data: bytes, filename: str = "") -> FileKind:
    head = data[:64]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"BM", b"II*\x00", b"MM\x00*")):
        return "image"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "image"
    if head.startswith(b"AC10"):
        return "dwg"
    if head.startswith(b"ISO-10303-21"):
        return "ifc"
    text = head.decode("latin-1", errors="ignore").lstrip()
    if text.startswith("0") and "SECTION" in data[:256].decode("latin-1", errors="ignore"):
        return "dxf"
    return "unknown"


def expand(filename: str, data: bytes) -> Iterator[InputFile]:
    """En uppladdad fil som en eller flera indatafiler. ZIP packas upp (ett nivå djupt räcker inte alltid,
    så inbäddade ZIP packas också upp)."""
    kind = detect_kind(data, filename)
    if kind != "zip":
        yield InputFile(filename=filename, data=data, kind=kind)
        return
    th = load_thresholds()
    max_members = int(th.get("ingest.max_zip_members"))
    max_bytes = int(th.get("ingest.max_zip_uncompressed_mb")) * 1024 * 1024
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > max_members:
            raise UnsafeArchiveError(f"{filename}: {len(members)} filer i arkivet, gränsen är {max_members}")
        if sum(m.file_size for m in members) > max_bytes:
            raise UnsafeArchiveError(f"{filename}: arkivet packas upp till mer än {max_bytes // 2**20} MB")
        for member in members:
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise UnsafeArchiveError(f"{filename}: otillåten sökväg i arkivet: {member.filename!r}")
            if path.name.startswith(".") or "__MACOSX" in path.parts:
                continue  # systemfiler från packprogram
            yield from expand(f"{filename}/{member.filename}", zf.read(member))
