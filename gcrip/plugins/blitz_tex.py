"""Textures in Blitz Games ``.gcp`` packs (gcrip.formats.blitz_tex): the stampless ``common_*``
packs that ``gcrip.plugins.blitz`` cannot split, because they hold a chain of texture
descriptors rather than named members.  Emitted as textures-only Scenes named after the pack."""

from __future__ import annotations

import posixpath

from gcrip.formats import blitz_gcp, blitz_tex
from ripcore.scene import Scene

NAME = "blitz_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    # the descriptor lives at 0x820, far past the 64 bytes a detect() is given, so this can only
    # check the pack header here; textures() does the real validation on the whole file
    return blitz_gcp.is_pack(posixpath.basename(path), head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = blitz_tex.textures(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    for i, tex in enumerate(found):
        name = stem if len(found) == 1 else f"{stem}_{i:02d}"
        scene.textures[name] = blitz_tex.decode(data, tex)
    scene.extras = {
        "textures_only": True,
        "format": "blitz_tex",
        "count": len(found),
        "sizes": [f"{t.width}x{t.height}" for t in found[:16]],
    }
    return [scene]
