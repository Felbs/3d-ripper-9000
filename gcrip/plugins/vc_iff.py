"""Visual Concepts ``RTXT`` texture banks (gcrip.formats.vc_iff) - the ``.IFF`` members of
``game.dat``.  Stored members are read directly; packed ones are decoded first
(gcrip.formats.vc_pack).  One textures-only Scene a member."""

from __future__ import annotations

import posixpath

from gcrip.formats import vc_iff, vc_pack
from ripcore.scene import Scene

NAME = "vc_iff"


def detect(path: str, head: bytes, size: int) -> bool:
    return vc_iff.is_rtxt(head) or (vc_pack.is_packed(head) and head[18:21] == b"TXT")


def extract(data: bytes, path: str, src) -> list[Scene]:
    warning = None
    if not vc_iff.is_rtxt(data[:64]) and vc_pack.is_packed(data[:64]):
        try:
            data = vc_pack.unpack(data)
        except vc_pack.PackError as exc:
            # the member says how long its output is; failing to reach it is a fact worth
            # reporting, not a silent nothing
            raise vc_pack.PackError(f"{path}: {exc}") from None
    found = vc_iff.textures(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "textures"
    scene = Scene(name=stem)
    for tex in found:
        key = tex.name if tex.name not in scene.textures else f"{tex.name}_{len(scene.textures)}"
        scene.textures[key] = vc_iff.decode(tex)
    if warning:
        scene.warnings.append(warning)
    scene.extras = {"textures_only": True, "format": "vc_iff"}
    return [scene]
