"""Raw access to GameCube disc images.

Supports plain .iso / .gcm (a 1:1 image of the disc; a full GC disc is
1459978240 bytes, but truncated/scrubbed images work too since we only follow
the FST).

Compressed containers (RVZ, WIA, GCZ, CISO, WBFS) are detected and rejected
with a hint; convert them with DolphinTool first:

    DolphinTool convert -i game.rvz -o game.iso -f iso
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

GC_DISC_MAGIC = 0xC2339F3D  # big-endian u32 at 0x1C
WII_DISC_MAGIC = 0x5D1C9EA3  # big-endian u32 at 0x18


class UnsupportedImageError(Exception):
    pass


_CONTAINER_MAGICS: dict[bytes, str] = {
    b"RVZ\x01": "RVZ",
    b"WIA\x01": "WIA",
    b"\x01\xc0\x0b\xb1": "GCZ",
    b"CISO": "CISO",
    b"WBFS": "WBFS",
}


class DiscImage:
    """Seekable byte-level view of a disc image."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self._fh = open(self.path, "rb")  # noqa: SIM115 - long-lived handle
        self.size = self._fh.seek(0, os.SEEK_END)
        head = self.read(0, 0x20)
        try:
            for magic, name in _CONTAINER_MAGICS.items():
                if head.startswith(magic):
                    raise UnsupportedImageError(
                        f"{self.path.name} is a {name} container. Convert to plain ISO first:\n"
                        f'  DolphinTool convert -i "{self.path}" -o game.iso -f iso'
                    )
            if len(head) < 0x20:
                raise UnsupportedImageError(f"{self.path.name} is too small to be a disc image")
            if int.from_bytes(head[0x18:0x1C], "big") == WII_DISC_MAGIC:
                raise UnsupportedImageError(
                    f"{self.path.name} is a Wii disc; only GameCube discs are supported"
                )
            if int.from_bytes(head[0x1C:0x20], "big") != GC_DISC_MAGIC:
                raise UnsupportedImageError(
                    f"{self.path.name}: GameCube disc magic not found at 0x1C "
                    f"(got {head[0x1C:0x20].hex()})"
                )
        except UnsupportedImageError:
            self.close()
            raise

    def read(self, offset: int, size: int) -> bytes:
        self._fh.seek(offset)
        return self._fh.read(size)

    def read_chunks(self, offset: int, size: int, chunk: int = 4 << 20) -> Iterator[bytes]:
        """Yield the byte range in chunks (hash large files without loading them whole)."""
        end = offset + size
        pos = offset
        while pos < end:
            data = self.read(pos, min(chunk, end - pos))
            if not data:
                break
            yield data
            pos += len(data)

    def close(self) -> None:
        fh = getattr(self, "_fh", None)
        if fh is not None:
            fh.close()
            self._fh = None

    def __enter__(self) -> DiscImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
