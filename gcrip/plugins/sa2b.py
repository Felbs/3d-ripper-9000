"""Sonic Adventure 2: Battle model archives (the ``payload.bin`` of a ``.prs`` whose bytes
start with an id / offset table of NJS_OBJECT trees; gcrip.formats.sa2b).  One Scene per
table entry, evaluated with dcrip's Ninja scene builder (rig from the object tree)."""

from __future__ import annotations

import posixpath

from dcrip import ninja_eval
from dcrip.formats import ninja
from gcrip.formats import gvr, sa2b
from ripcore.scene import Scene

NAME = "sa2b"


def detect(path: str, head: bytes, size: int) -> bool:
    if not path.lower().endswith(".prs/payload.bin") or size < 64:
        return False
    return sa2b.looks_like_table(head, size)  # the full object check runs in extract


def _texture_archive(src, path: str, stem: str) -> list[gvr.Texture]:
    """Textures of the sibling archive named like the model one (``sonicmdl`` ->
    ``sonictex``, ``eggmdl`` -> ``eggtex``, ``e_bom`` -> ``e_bomtex``)."""
    by_path = getattr(src, "by_path", None) or {}
    if not by_path:
        return []
    folder = posixpath.dirname(posixpath.dirname(path))
    low = stem.lower()
    cands = []
    if "mdl" in low:
        cands.append(low.replace("mdl", "tex"))
    cands += [low + "tex", low + "_tex", low.replace("_mdl", "") + "tex"]
    for p in by_path:
        pl = p.lower()
        if not pl.startswith(folder.lower() + "/"):
            continue
        rest = pl[len(folder) + 1 :]
        for c in cands:
            if rest in (f"{c}.prs/payload.bin", f"{c}.gvm", f"{c}.prs"):
                try:
                    blob = src.get(p)
                except Exception:  # noqa: BLE001
                    continue
                if not gvr.is_gvm(blob[:4]):
                    continue
                return gvr.gvm_textures(blob)
    return []


def extract(data: bytes, path: str, src) -> list[Scene]:
    stem = posixpath.basename(posixpath.dirname(path)).rsplit(".", 1)[0]
    textures = _texture_archive(src, path, stem)
    names = [t.name for t in textures]
    rgba = {t.name: t.rgba for t in textures if t.rgba is not None}
    scenes = []
    for ident, nj in sa2b.parse(data):
        if names:
            nj.texlist = ninja.TexList(names)
        scene = ninja_eval.evaluate(nj, f"{stem}_{ident}")
        if scene.primitives:
            for m in scene.materials:
                if m.texture and m.texture in rgba:
                    scene.textures.setdefault(m.texture, rgba[m.texture])
                elif m.texture:
                    m.texture = None
            scene.extras = {"format": "sa2b-chunk", "model_id": ident, "objects": len(nj.objects)}
            scenes.append(scene)
    return scenes
