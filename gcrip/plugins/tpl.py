"""Loose Nintendo ``TPL`` texture files (gcrip.formats.tpl).

gcrip has read TPL for a long time, but only from inside game-specific plugins (Monkey Ball,
RE4, Rayman, Paper Mario, Wave Race, Fire Emblem).  A TPL that turns up on its own - as a
member of an archive some other plugin expanded, say the ``.jam`` files of Billy & Mandy and
Kids Next Door - was claimed by nothing and fell through to the structure scanner.  This picks
those up wherever they appear.
"""

from __future__ import annotations

import posixpath

from gcrip.formats import tpl
from ripcore.scene import Scene

NAME = "tpl"


def detect(path: str, head: bytes, size: int) -> bool:
    return head[:4] == tpl.MAGIC


def extract(data: bytes, path: str, src) -> list[Scene]:
    if data[:4] != tpl.MAGIC:
        return []
    try:
        images = tpl.parse(data)
    except Exception:  # noqa: BLE001 - a malformed texture must not stop the rip
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "textures"
    scene = Scene(name=stem)
    for i, image in enumerate(images):
        try:
            rgba = image.decode()
        except Exception as e:  # noqa: BLE001 - one bad texture must not lose the rest
            scene.warnings.append(f"texture {i}: {e}")
            continue
        scene.textures[stem if len(images) == 1 else f"{stem}_{i:03d}"] = rgba
    if not scene.textures:
        return []
    scene.extras = {"textures_only": True, "format": "tpl", "count": len(scene.textures)}
    return [scene]
