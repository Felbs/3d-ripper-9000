"""EA Sports EBO geometry (NHL 2005/06, NBA Live 2005/06, FIFA 05, 2006 FIFA World Cup,
UEFA Champions League): the ``.ebo`` objects inside EA BIG/VIV archives
(gcrip.formats.ebo).  One Scene per Geometry export (LOD variants, sticks, gloves ... are
separate exports in one file).  Skinned lists carry bone weights against the game's
skeleton objects (``preload/gmisc.viv/bodyskel.ebo`` / ``faceskel.ebo`` / ``handskel.ebo``),
looked up on the disc by name.  Textures are not linked yet (the Material imports name
them - ``gTexture_RMRuntime`` - but the binding lives in the game code)."""

from __future__ import annotations

import contextlib
import os
import posixpath

from gcrip.formats import ebo
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "ebo"

_SKEL_ATTR = "_ebo_skeletons"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".ebo") and ebo.is_ebo(head) and size >= 256


def _skeleton_name(path: str, exports: list[str]) -> str:
    low = path.lower()
    text = " ".join(exports).lower()
    if "face" in low or "face" in text:
        return "faceskel.ebo"
    if "hand" in posixpath.basename(low) or "hand" in text:
        return "handskel.ebo"
    return "bodyskel.ebo"


def _skeleton(src, name: str) -> ebo.Skeleton | None:
    """The skeleton object called ``name`` anywhere on the disc (cached on the source)."""
    if src is None:
        return None
    cache = getattr(src, _SKEL_ATTR, None)
    if cache is None:
        cache = {}
        with contextlib.suppress(Exception):
            setattr(src, _SKEL_ATTR, cache)
    if name in cache:
        return cache[name]
    sk = None
    by_path = getattr(src, "by_path", {}) or {}
    for p in by_path:
        if p.lower().endswith("/" + name) or p.lower() == name:
            try:
                sk = ebo.skeleton(ebo.parse(src.get(p)))
            except Exception:  # noqa: BLE001
                sk = None
            if sk is not None:
                break
    cache[name] = sk
    return sk


def extract(data: bytes, path: str, src) -> list[Scene]:
    obj = ebo.parse(data)
    meshes = ebo.geometry(obj)
    if not meshes:
        return []
    groups: dict[str, list[ebo.Mesh]] = {}
    for m in meshes:
        groups.setdefault(m.name.split("#")[0], []).append(m)
    skinned = [m for m in meshes if m.joints is not None]
    sk = None
    if skinned:
        sk = _skeleton(src, _skeleton_name(path, list(groups)))
        top = max(int(m.joints[m.weights > 0].max()) for m in skinned if (m.weights > 0).any())
        if sk is not None and top >= len(sk.matrices):
            sk = None  # a different rig: keep the geometry, drop the weights
    stem = os.path.basename(path)[:-4]
    scenes = []
    for gname, group in groups.items():
        scene = Scene(name=gname if len(groups) > 1 else stem)
        if sk is not None and any(m.joints is not None for m in group):
            scene.joints = [Joint(n, p, tr, ro, sc) for n, p, tr, ro, sc in ebo.joints(sk)]
        for m in group:
            scene.materials.append(MaterialDef(name=m.name, texture=None, double_sided=True))
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=m.positions,
                    indices=m.indices,
                    normals=m.normals,
                    uvs=m.uvs,
                    colors=m.colors,
                    joints=m.joints if scene.joints else None,
                    weights=m.weights if scene.joints else None,
                )
            )
        scene.extras = {
            "format": "ebo",
            "version": obj.version,
            "file": stem,
            "lists": len(group),
            "skinned": sum(1 for m in group if m.joints is not None),
            "skeleton": (len(sk.matrices) if sk is not None and scene.joints else 0),
        }
        scenes.append(scene)
    return scenes
