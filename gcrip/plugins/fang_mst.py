"""Midway Fang ``.mst`` archives (gcrip.formats.fang_mst): Freaky Flyers.  A container of
LZO members named by the table; ``.gtx`` members are GX textures with an 89-byte header and
decode here, the ``.gmo`` models and ``.gmw`` worlds carry plain GX display lists the
fallback scanner reads (25 lists / 2,669 triangles in ``mgs_camera.gmo``, 71 / 18,823 in
``ohtd.gmw``) - their own headers are memory images with absolute pointers, unread."""

from __future__ import annotations

import posixpath
import struct

from gcrip.formats import fang_mst, gx_texture
from ripcore.scene import Scene

NAME = "fang_mst"
GTX_HEADER_AT = 0x18
GTX_SIZE_AT = 0x20
GTX_FORMAT_AT = 0x2C


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".mst") and fang_mst.is_mst(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for e in fang_mst.entries(data):
        blob = fang_mst.member(data, e)
        if blob:
            out.append((e.name, blob))
    return out


def is_gtx(head: bytes, size: int) -> bool:
    if len(head) < 0x30 or head[:GTX_HEADER_AT] != bytes(GTX_HEADER_AT):
        return False
    header = struct.unpack_from(">I", head, GTX_HEADER_AT)[0]
    width, height = struct.unpack_from(">2H", head, GTX_SIZE_AT)
    fmt = struct.unpack_from(">I", head, GTX_FORMAT_AT)[0]
    if fmt not in gx_texture.TILE_DIMS or not (0 < width <= 2048 and 0 < height <= 2048):
        return False
    return header < 4096 and size >= header + gx_texture.encoded_size(fmt, width, height)


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gtx") and is_gtx(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    if not is_gtx(data[:0x30], len(data)):
        return []
    header = struct.unpack_from(">I", data, GTX_HEADER_AT)[0]
    width, height = struct.unpack_from(">2H", data, GTX_SIZE_AT)
    fmt = struct.unpack_from(">I", data, GTX_FORMAT_AT)[0]
    need = gx_texture.encoded_size(fmt, width, height)
    try:
        rgba = gx_texture.decode(fmt, width, height, data[header : header + need])
    except ValueError:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name[:64]] = rgba
    scene.extras = {"textures_only": True, "format": "fang_gtx"}
    return [scene]
