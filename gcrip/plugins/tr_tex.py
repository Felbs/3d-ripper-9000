"""Terminal Reality ``.TEX`` textures (gcrip.formats.tr_tex): the art inside BloodRayne's and
Blowout's POD archives, decoded as textures-only Scenes."""

from __future__ import annotations

import posixpath

from gcrip.formats import tr_tex
from ripcore.scene import Scene

NAME = "tr_tex"


def detect(path: str, head: bytes, size: int) -> bool:
    # inside a .PKG the textures keep the artist's original ".TIF" name (a real TIFF starts
    # "II*" or "MM" magic and fails the header check, so this stays unambiguous)
    return path.lower().endswith((".tex", ".tif", ".raw")) and tr_tex.is_tex(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    rgba = tr_tex.decode(data)
    if rgba is None:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "tr_tex"}
    return [scene]
