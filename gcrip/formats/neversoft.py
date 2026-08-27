"""Neversoft (Tony Hawk's Underground, GameCube GTDE52): PRE archives (.prg) and
the GameCube texture files (.tex.ngc / .img.ngc).

PRE (.prg on GameCube, .pre/.prx elsewhere) - big-endian on GameCube:
  u32 total size, u32 version (0xABCD0003), u32 file count, then per file:
  u32 size, u32 packed size (0 = stored), u16 name length, u16 pad, u32 name
  checksum, name (NUL padded to the length), data, padding to 4.  Packed data
  is Okumura LZSS (4 KiB window, 3..18 byte matches, flag bits LSB first, a
  set bit is a literal) - the PC PRE format documented by the THPS modding
  tools, byte-swapped for GameCube.

TEX (.tex.ngc) - big-endian:
  u32 version (1), u32 texture count, then per texture: u32 name checksum,
  u32 width, u32 height, u32 mip levels, u32 flag a, u32 flag b, then per level
  u32 size + data.  Pixels are GX CMPR (size == w*h/2) - the only format seen on
  the disc - and a texture may be followed by extra level chains (same sizes,
  no header) that we skip.  A level count of 0 is an empty placeholder.

IMG (.img.ngc) - big-endian:
  u32 version (2), u32 flags, u32 width, u32 height, u32 bits per pixel, u32 pad,
  u32 width, u32 height, u32 pad, then w*h*bpp/8 bytes of GX RGBA8 tiles.

The scene / model files (.scn.ngc, .mdl.ngc, .skin.ngc, .col.ngc) are the
GameCube port of the format read by io_thps_scene for PC; their GameCube
layout (display lists) is not decoded here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from gcrip.formats import gx_texture

PRE_VERSION = 0xABCD0003


class NeversoftError(ValueError):
    pass


# ---------------------------------------------------------------------------
# PRE
# ---------------------------------------------------------------------------


def is_pre(data: bytes) -> bool:
    if len(data) < 12:
        return False
    total, version, count = struct.unpack_from(">III", data, 0)
    return version == PRE_VERSION and 0 < count < 100000 and total >= 12


def lzss_decompress(src: bytes, out_size: int) -> bytes:
    n_ring = 4096
    ring = bytearray(n_ring)
    r = n_ring - 18
    out = bytearray()
    i = 0
    flags = 0
    n = len(src)
    while len(out) < out_size and i < n:
        flags >>= 1
        if not flags & 0x100:
            flags = src[i] | 0xFF00
            i += 1
        if flags & 1:
            c = src[i]
            i += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & (n_ring - 1)
        else:
            if i + 1 >= n:
                break
            b0, b1 = src[i], src[i + 1]
            i += 2
            off = b0 | ((b1 & 0xF0) << 4)
            ln = (b1 & 0x0F) + 3
            for k in range(ln):
                c = ring[(off + k) & (n_ring - 1)]
                out.append(c)
                ring[r] = c
                r = (r + 1) & (n_ring - 1)
    return bytes(out[:out_size])


def pre_entries(data: bytes) -> list[tuple[str, bytes]]:
    if not is_pre(data):
        raise NeversoftError("not a PRE archive")
    _total, _version, count = struct.unpack_from(">III", data, 0)
    pos = 12
    out = []
    for _ in range(count):
        if pos + 16 > len(data):
            break
        size, packed, name_len, _pad, _crc = struct.unpack_from(">IIHHI", data, pos)
        pos += 16
        name = data[pos : pos + name_len].split(b"\0", 1)[0].decode("latin-1")
        pos += name_len
        stored = packed or size
        blob = data[pos : pos + stored]
        pos = (pos + stored + 3) & ~3
        if packed:
            blob = lzss_decompress(blob, size)
        out.append((name.replace("\\", "/"), blob))
    return out


# ---------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------


@dataclass
class Texture:
    checksum: int
    width: int
    height: int
    levels: list[bytes]
    flag_a: int = 0
    flag_b: int = 0

    def decode(self) -> np.ndarray | None:
        if not self.levels or self.width == 0 or self.height == 0:
            return None
        blob = self.levels[0]
        fmt = 14 if len(blob) * 8 == self.width * self.height * 4 else None
        if fmt is None and len(blob) == self.width * self.height * 4:
            fmt = 6
        if fmt is None and len(blob) == self.width * self.height * 2:
            fmt = 5
        if fmt is None:
            return None
        # stored bottom-up
        return np.ascontiguousarray(gx_texture.decode(fmt, self.width, self.height, blob)[::-1])


def is_tex(data: bytes) -> bool:
    if len(data) < 32:
        return False
    version, count = struct.unpack_from(">II", data, 0)
    if version != 1 or not 0 < count < 4096:
        return False
    _crc, w, h, lv = struct.unpack_from(">IIII", data, 8)
    return w <= 4096 and h <= 4096 and lv <= 16


def parse_tex(data: bytes) -> list[Texture]:
    if not is_tex(data):
        raise NeversoftError("not a THUG .tex.ngc")
    _version, count = struct.unpack_from(">II", data, 0)
    pos = 8
    out = []
    n = len(data)
    for _ in range(count):
        if pos + 24 > n:
            break
        crc, w, h, lv, a, b = struct.unpack_from(">6I", data, pos)
        pos += 24
        levels = []
        for _ in range(lv):
            if pos + 4 > n:
                break
            size = struct.unpack_from(">I", data, pos)[0]
            pos += 4
            levels.append(data[pos : pos + size])
            pos += size
        # extra chains (same level sizes, no header) follow some textures
        first = len(levels[0]) if levels else -1
        while levels and pos + 4 <= n and struct.unpack_from(">I", data, pos)[0] == first:
            for _ in range(lv):
                if pos + 4 > n:
                    break
                size = struct.unpack_from(">I", data, pos)[0]
                pos += 4 + size
        out.append(Texture(crc, w, h, levels, a, b))
    return out


def is_img(data: bytes) -> bool:
    if len(data) < 36:
        return False
    version, _flags, w, h, bpp = struct.unpack_from(">IIIII", data, 0)
    return version == 2 and 0 < w <= 4096 and 0 < h <= 4096 and bpp in (4, 8, 16, 32)


def parse_img(data: bytes) -> Texture:
    if not is_img(data):
        raise NeversoftError("not a THUG .img.ngc")
    _version, _flags, w, h, bpp = struct.unpack_from(">IIIII", data, 0)
    return Texture(0, w, h, [data[36 : 36 + w * h * bpp // 8]])
