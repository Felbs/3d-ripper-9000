"""``PNG`` images.  gcrip has treated PNG as a magic to recognise since early on
(:mod:`gcrip.formats.generic` lists it) but has never decoded one, so a PNG handed out by a
container fell through to the fallback and produced nothing.

Nothing here is clever - Pillow does the work.  What this module adds is the bookkeeping the
rest of the pipeline needs: a `detect` that reads only the eight-byte signature (a plugin's
``detect`` sees 64 bytes, no more), a dimension guard so a corrupt header cannot ask for a
gigabyte of pixels, and RGBA output whatever the file's colour type.

The end marker matters as much as the signature: ``IEND`` followed by its four CRC bytes closes
every PNG, which is what makes them safe to **carve** out of a container that has no directory
at all (see :mod:`gcrip.formats.hff`).
"""

from __future__ import annotations

import io
import struct

import numpy as np

MAGIC = b"\x89PNG\r\n\x1a\n"
END = b"IEND\xae\x42\x60\x82"
IHDR_AT = 16  # width and height, after the signature and the IHDR length/type
MAX_DIM = 16384


def is_png(head: bytes) -> bool:
    if len(head) < IHDR_AT + 8 or head[: len(MAGIC)] != MAGIC:
        return False
    width, height = struct.unpack_from(">2I", head, IHDR_AT)
    return 0 < width <= MAX_DIM and 0 < height <= MAX_DIM


def size(head: bytes) -> tuple[int, int] | None:
    return struct.unpack_from(">2I", head, IHDR_AT) if is_png(head) else None


def decode(data: bytes) -> np.ndarray | None:
    """RGBA, top row first."""
    if not is_png(data[: IHDR_AT + 8]):
        return None
    try:
        with io.BytesIO(data) as fh:
            from PIL import Image

            image = Image.open(fh)
            image.load()
            return np.asarray(image.convert("RGBA"))
    except Exception:  # noqa: BLE001 - a broken member must not stop the walk
        return None
