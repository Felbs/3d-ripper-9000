"""Sega GVM texture archives and single GVR textures (Sonic Adventure DX / 2 Battle,
Phantasy Star Online, Billy Hatcher): textures-only Scenes (gcrip.formats.gvr)."""

from __future__ import annotations

import posixpath

from gcrip.formats import gvr
from ripcore.scene import Scene

NAME = "gvm"


def detect(path: str, head: bytes, size: int) -> bool:
    return size > 16 and (gvr.is_gvm(head) or gvr.is_gvr(head))


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    if name == "payload":  # the member of a .prs container: name it after the archive
        name = posixpath.basename(posixpath.dirname(path)).rsplit(".", 1)[0]
    if gvr.is_gvm(data[:4]):
        textures = gvr.gvm_textures(data)
    else:
        t = gvr.gvr_texture(data, name)
        textures = [t] if t else []
    scene = Scene(name=name)
    for t in textures:
        if t.rgba is not None:
            scene.textures.setdefault(t.name, t.rgba)
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True, "format": "gvm", "count": len(textures)}
    return [scene]
