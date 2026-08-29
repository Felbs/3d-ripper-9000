"""Krome Studios MDL3 models (``.mdl`` + ``.mdg`` pairs inside RKV2 archives: Ty the
Tasmanian Tiger 2 / 3, The Legend of Spyro: A New Beginning, King Arthur).  The ``.mdl``
is the entry point; its sibling ``.mdg`` holds the GX geometry and the ``.tex`` files named
by the model's texture table are the textures (gcrip.formats.mdl3)."""

from __future__ import annotations

import posixpath

from gcrip.formats import mdl3
from gcrip.plugins.mdl2 import _gtx_index, scenes
from ripcore.scene import Scene

NAME = "mdl3"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".mdl") and mdl3.is_mdl3(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = path[:-4]
    mdg = None
    for cand in (stem + ".mdg", stem + ".MDG"):
        try:
            mdg = src.get(cand)
            break
        except Exception:  # noqa: BLE001
            continue
    if mdg is None:
        return []
    model = mdl3.parse(data, mdg, posixpath.basename(stem))
    return scenes(model, _gtx_index(src, ".tex"), src, "mdl3")
