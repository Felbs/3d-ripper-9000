"""RenderWare platform-independent texture dictionaries (``rwID_PITEXDICTIONARY`` 0x23) with
``rwID_IMAGE`` (0x18) rasters - what Frogger: Ancient Shadow ships instead of native GameCube
texture dictionaries.  Little-endian chunk headers like every RenderWare stream.

  PITEXDICTIONARY body:  u16 texture count, u16 device id, then per texture:
      u32 mip count
      mip count x IMAGE chunks:  STRUCT { u32 width, u32 height, u32 depth, u32 stride },
          then stride * height pixel bytes, then for depth 4 / 8 a palette of
          (1 << depth) RGBA8 entries; depth 32 pixels are RGBA8
      TEXTURE chunk (0x06):  STRUCT { u32 filter/address }, STRING name, STRING mask
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import rwstream as rw

PITEXDICT = 0x23
IMAGE = 0x18
TEXTURE = 0x06


@dataclass
class PiTexture:
    name: str
    mask: str
    image: np.ndarray | None
    error: str | None = None


def is_pitxd(head: bytes, size: int) -> bool:
    return rw.looks_like_stream(head, size, (PITEXDICT,))


def _image(data: bytes, c: rw.Chunk) -> np.ndarray:
    st = rw.child(data, c, rw.STRUCT)
    if st is None or st.size < 16:
        raise rw.RwError("IMAGE without a struct")
    w, h, depth, stride = struct.unpack_from("<4I", data, st.off)
    if not (0 < w <= 4096 and 0 < h <= 4096) or stride < w * (depth // 8 or 1):
        raise rw.RwError(f"IMAGE {w}x{h} depth {depth} stride {stride}")
    p = st.end
    pixels = data[p : p + stride * h]
    if len(pixels) < stride * h:
        raise rw.RwError("IMAGE pixels run past the chunk")
    p += stride * h
    if depth in (4, 8):
        entries = 1 << depth
        pal = np.frombuffer(data[p : p + entries * 4], dtype=np.uint8)
        if len(pal) < entries * 4:
            raise rw.RwError("IMAGE palette runs past the chunk")
        pal = pal.reshape(entries, 4)
        rows = np.frombuffer(pixels, dtype=np.uint8).reshape(h, stride)
        if depth == 8:
            idx = rows[:, :w]
        else:
            idx = np.empty((h, w), np.uint8)
            packed = rows[:, : (w + 1) // 2]
            idx[:, 0::2] = packed[:, : (w + 1) // 2] >> 4
            idx[:, 1::2] = (packed[:, : w // 2] & 15)
        return pal[idx]
    if depth == 32:
        rows = np.frombuffer(pixels, dtype=np.uint8).reshape(h, stride)
        return np.ascontiguousarray(rows[:, : w * 4].reshape(h, w, 4))
    raise rw.RwError(f"IMAGE depth {depth} unsupported")


def parse(data: bytes) -> list[PiTexture]:
    top = rw.top(data)
    if top.type != PITEXDICT:
        raise rw.RwError(f"not a PI texture dictionary (chunk {top.type:#x})")
    if top.size < 4:
        return []
    count = struct.unpack_from("<H", data, top.off)[0]
    p = top.off + 4
    out: list[PiTexture] = []
    for _ in range(count):
        if p + 4 > top.end:
            break
        mips = struct.unpack_from("<I", data, p)[0]
        p += 4
        image = None
        error = None
        for k in range(min(mips, 16)):
            c = rw.read_chunk(data, p, top.end)
            if c is None or c.type != IMAGE:
                error = "texture without its images"
                break
            if k == 0:
                try:
                    image = _image(data, c)
                except (rw.RwError, ValueError) as exc:
                    error = str(exc)
            p = c.end
        c = rw.read_chunk(data, p, top.end)
        name = mask = ""
        if c is not None and c.type == TEXTURE:
            strings = [k for k in rw.chunks(data, c.off, c.end) if k.type == rw.STRING]
            if strings:
                name = rw.read_string(data, strings[0])
            if len(strings) > 1:
                mask = rw.read_string(data, strings[1])
            p = c.end
        else:
            error = error or "texture without a TEXTURE chunk"
        out.append(PiTexture(name, mask, image, error))
        if c is None:
            break
    return out


def names(data: bytes) -> list[str]:
    try:
        return [t.name for t in parse(data)]
    except (rw.RwError, struct.error):
        return []
