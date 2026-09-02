"""``MULA`` texture archives (gcrip.formats.mula) - the Cabela's discs.  One textures-only
Scene an archive, an image a member.

The palette format is not stored anywhere in the ``GCT `` header, so it is chosen by decoding:
`RGB5A3` carries alpha and `RGB565` does not, and a palette whose entries all set the top bit
is `RGB5A3` opaque, which decodes identically either way.  `RGB5A3` is tried first and only
falls back when it raises.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import gx_texture as gx
from gcrip.formats import mula
from ripcore.scene import MaterialDef, Scene

NAME = "mula"

PALETTE_FMT = 2  # RGB5A3


def detect(path: str, head: bytes, size: int) -> bool:
    return mula.is_mula(head)


def _decode(tex: mula.Texture):
    palette = None
    if tex.palette:
        count = len(tex.palette) // 2
        for pal_fmt in (PALETTE_FMT, 1):
            try:
                palette = gx.decode_palette(pal_fmt, tex.palette, count)
                break
            except ValueError:
                continue
        if palette is None:
            return None
    try:
        return gx.decode(tex.fmt, tex.width, tex.height, tex.pixels, palette)
    except ValueError:
        return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = mula.members(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "mula"
    scene = Scene(name=stem)
    for m in found:
        tex = mula.texture(data[m.offset : m.offset + m.size], m.name)
        if tex is None:
            continue
        rgba = _decode(tex)
        if rgba is None:
            continue
        key = posixpath.basename(m.name.replace("\\", "/")) or f"tex{m.offset}"
        if key in scene.textures:
            key = f"{key}_{m.offset}"
        scene.textures[key] = rgba
    if not scene.textures:
        return []
    # a texture no material names is dropped at export - see docs/formats/textures-only-scenes.md
    scene.materials = [MaterialDef(name=k, texture=k) for k in scene.textures]
    scene.extras = {"textures_only": True, "format": "mula", "count": len(scene.textures)}
    return [scene]
