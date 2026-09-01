"""Visual Concepts ``RTXT`` texture banks (gcrip.formats.vc_iff) - the ``.IFF`` members of
``game.dat`` that are stored uncompressed.  One textures-only Scene a member."""

from __future__ import annotations

import posixpath

from gcrip.formats import vc_iff
from ripcore.scene import Scene

NAME = "vc_iff"


def detect(path: str, head: bytes, size: int) -> bool:
    return vc_iff.is_rtxt(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = vc_iff.textures(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "textures"
    scene = Scene(name=stem)
    for tex in found:
        key = tex.name if tex.name not in scene.textures else f"{tex.name}_{len(scene.textures)}"
        scene.textures[key] = vc_iff.decode(tex)
    scene.extras = {"textures_only": True, "format": "vc_iff"}
    return [scene]
