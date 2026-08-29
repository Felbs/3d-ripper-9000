"""Sega GVR textures and GVM texture archives (GameCube PVR: Sonic Adventure DX / 2 Battle,
Phantasy Star Online, Billy Hatcher ...).  ``GVRT | u32 LE size | u16 0 | u8 palette flags
| u8 data format | u16 BE width | u16 BE height | pixels`` - the data formats are GX ones
(0 I4, 1 I8, 2 IA4, 3 IA8, 4 RGB565, 5 RGB5A3, 6 RGBA8, 8 C4, 9 C8, 0xe CMPR); an
optional ``GCIX | u32 size | u32 global index`` precedes the chunk.  Palette flags: bit 1 =
internal palette after the header (format in the top nibble: 0 IA8, 1 RGB565, 2 RGB5A3),
bit 3 = external ``.gvp`` palette.  GVM: ``GVMH | u32 LE header size | u16 BE flags | u16
BE count | entries`` (``u16 id`` + name[28] when flag 8 + ``u16 formats`` when flag 4 +
``u16 dims`` when flag 2 + ``u32 global index`` when flag 1) then the GVR chunks.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

GVM = b"GVMH"
GVRT = b"GVRT"
GCIX = b"GCIX"


@dataclass
class Texture:
    name: str
    width: int
    height: int
    rgba: np.ndarray | None


def is_gvm(head: bytes) -> bool:
    return head[:4] == GVM


def is_gvr(head: bytes) -> bool:
    return head[:4] == GVRT or (head[:4] == GCIX and head[16:20] == GVRT)


def decode_gvrt(d: bytes, off: int) -> tuple[int, int, np.ndarray | None, int]:
    """(width, height, rgba, chunk end) of the GVRT chunk at off."""
    from gcrip.formats import gx_texture

    if d[off : off + 4] != GVRT or off + 16 > len(d):
        return 0, 0, None, off + 8
    size = struct.unpack_from("<I", d, off + 4)[0]
    end = off + 8 + size
    pflags, fmt = d[off + 10], d[off + 11]
    w, h = struct.unpack_from(">2H", d, off + 12)
    p = off + 16
    palette = None
    if fmt in (8, 9):
        entries = 16 if fmt == 8 else 256
        if pflags & 0x02:
            pal_fmt = {0: 0, 1: 1, 2: 2}.get(pflags >> 4, 2)
            palette = gx_texture.decode_palette(pal_fmt, d[p : p + entries * 2], entries)
            p += entries * 2
        else:
            palette = np.full((entries, 4), 255, np.uint8)
            palette[:, :3] = np.linspace(0, 255, entries, dtype=np.uint8)[:, None]
    if fmt not in (0, 1, 2, 3, 4, 5, 6, 8, 9, 14) or not (0 < w <= 4096 and 0 < h <= 4096):
        return w, h, None, end
    need = gx_texture.encoded_size(fmt, w, h)
    body = d[p : p + need]
    if len(body) < need:
        return w, h, None, end
    try:
        rgba = gx_texture.decode(fmt, w, h, body, palette=palette)
    except Exception:  # noqa: BLE001
        rgba = None
    return w, h, rgba, end


def gvm_textures(d: bytes) -> list[Texture]:
    if not is_gvm(d[:4]) or len(d) < 16:
        return []
    hsize = struct.unpack_from("<I", d, 4)[0]
    flags, count = struct.unpack_from(">2H", d, 8)
    names = []
    p = 12
    for _ in range(min(count, 4096)):
        p += 2  # id
        name = ""
        if flags & 8:
            name = d[p : p + 28].split(b"\0")[0].decode("latin-1", "replace")
            p += 28
        if flags & 4:
            p += 2
        if flags & 2:
            p += 2
        if flags & 1:
            p += 4
        names.append(name)
    out = []
    p = 8 + hsize
    i = 0
    while p + 8 <= len(d):
        tag = d[p : p + 4]
        if tag == GCIX:
            p += 8 + struct.unpack_from("<I", d, p + 4)[0]
            continue
        if tag != GVRT:
            break
        w, h, rgba, end = decode_gvrt(d, p)
        name = names[i] if i < len(names) and names[i] else f"tex{i:03d}"
        out.append(Texture(name, w, h, rgba))
        i += 1
        p = end
    return out


def gvr_texture(d: bytes, name: str) -> Texture | None:
    off = 0
    if d[:4] == GCIX:
        off = 8 + struct.unpack_from("<I", d, 4)[0]
    if d[off : off + 4] != GVRT:
        return None
    w, h, rgba, _end = decode_gvrt(d, off)
    return Texture(name, w, h, rgba)
