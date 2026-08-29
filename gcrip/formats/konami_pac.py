"""Konami TYO texture packs (Teenage Mutant Ninja Turtles 1-3, GameCube): RenderWare-style
chunk 0x23 whose payload is Konami's own table - ``u32 count`` then per texture ``char
name[16] | 56 bytes of runtime fields | rwID_IMAGE (0x18) chunk`` = ``Struct { u32 width, u32
height, u32 depth, u32 stride }``, ``height * stride`` bytes of one-byte palette indices and a
``2 ** depth`` x RGBA8 palette (depth 4 / 8).  Little-endian like every RenderWare stream."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

PACK = 0x23
IMAGE = 0x18


@dataclass
class Texture:
    name: str
    width: int
    height: int
    rgba: np.ndarray | None


def is_pack(head: bytes) -> bool:
    if len(head) < 16:
        return False
    t, size, lib = struct.unpack_from("<3I", head, 0)
    return t == PACK and size > 16 and (lib & 0xFFFF) == 0xFFFF


def parse(data: bytes) -> list[Texture]:
    if not is_pack(data[:16]):
        return []
    _t, size, lib = struct.unpack_from("<3I", data, 0)
    end = min(12 + size, len(data))
    count = struct.unpack_from("<I", data, 12)[0]
    out: list[Texture] = []
    p = 16
    for _ in range(min(count, 4096)):
        if p + 72 + 28 > end:
            break
        name = data[p : p + 16].split(b"\0")[0].decode("latin-1", "replace")
        c = p + 72
        ctype, csize, clib = struct.unpack_from("<3I", data, c)
        if ctype != IMAGE or clib != lib or c + 12 + csize > end:
            break
        stype, ssize, _ = struct.unpack_from("<3I", data, c + 12)
        w, h, depth, stride = struct.unpack_from("<4I", data, c + 24)
        pix = c + 40
        rgba = None
        if stype == 1 and ssize == 16 and 0 < w <= 4096 and 0 < h <= 4096 and stride >= w:
            npal = 1 << depth if depth <= 8 else 0
            if npal and pix + h * stride + npal * 4 <= c + 12 + csize:
                idx = np.frombuffer(data, np.uint8, h * stride, pix).reshape(h, stride)[:, :w]
                pal = np.frombuffer(data, np.uint8, npal * 4, pix + h * stride).reshape(npal, 4)
                rgba = pal[np.minimum(idx, npal - 1)].copy()
            elif depth == 32 and pix + h * stride <= c + 12 + csize and stride >= w * 4:
                rgba = (
                    np.frombuffer(data, np.uint8, h * stride, pix)
                    .reshape(h, stride)[:, : w * 4]
                    .reshape(h, w, 4)
                    .copy()
                )
        out.append(Texture(name, w, h, rgba))
        p = c + 12 + csize
    return out


def names(data: bytes) -> list[str]:
    return [t.name for t in parse(data)]
