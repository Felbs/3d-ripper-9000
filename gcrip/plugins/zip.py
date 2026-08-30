"""Plain ZIP archives shipped as game data (Alien Hominid ``.pak``, Freedom Fighters and
Hitman 2 ``.ZIP`` scene bundles, NFL Blitz ``stadium.zip``, Powerpuff Girls ``Data.zip``,
Wallace & Gromit ``Overlay.zip``, X-Men Legends ``assetsfb.zip``): expanded as a container so
the members reach the format plugins and the structure scanner with their real names."""

from __future__ import annotations

import io
import zipfile

NAME = "zip"

MAGIC = b"PK\x03\x04"
_MAX_MEMBER = 256 << 20


def is_container(name: str, head: bytes) -> bool:
    return head[:4] == MAGIC


def expand(data: bytes) -> list[tuple[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, EOFError):
        return []
    out: list[tuple[str, bytes]] = []
    with zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size == 0 or info.file_size > _MAX_MEMBER:
                continue
            try:
                blob = zf.read(info)
            except Exception:  # noqa: BLE001 - one bad member must not lose the rest
                continue
            out.append((info.filename.replace("\\", "/"), blob))
    return out


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
