"""Darkened Skye ``SKX`` models (gcrip.formats.skx), the members of its ``PAK`` archives
(gcrip.plugins.skye_pak).  One primitive a mesh directory; the sibling ``GCT`` textures ship
separately and are not bound yet."""

from __future__ import annotations

import posixpath

from gcrip.formats import skx, skye_skel
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "skx"


def detect(path: str, head: bytes, size: int) -> bool:
    return skx.is_skx(head)


def _group_for(data: bytes, src):
    """Joint globals via the group ``.skg`` banks reachable from the source, matched by the
    SKX header's joint count; cached per source."""
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    cache = _skg_cache.get(key)
    if cache is None or cache[0] is not src:
        blobs = []
        for p in src.by_path:
            if p.lower().endswith(".skg"):
                try:
                    blobs.append(src.get(p))
                except Exception:  # noqa: BLE001 - a bad member must not stop the model
                    continue
        _skg_cache.clear()
        cache = _skg_cache[key] = (src, blobs)
    return skye_skel.match_group(data, cache[1])


_skg_cache: dict = {}


def extract(data: bytes, path: str, src) -> list[Scene]:
    group = _group_for(data, src)
    found = skx.meshes(data, skeleton=group[0] if group else None)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "skx"
    scene = Scene(name=stem)
    # `material` indexes scene.materials, so -1 against an empty list is an IndexError at
    # export rather than "no material" - see plugins/xmdl.py.  One material for the scene:
    # SKX carries no per-mesh material and every mesh shares it.
    scene.materials.append(MaterialDef(f"{stem}_mat", None))
    for mesh in found:
        scene.primitives.append(
            Primitive(
                material=0,
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
                joints=mesh.joints4 if group else None,
                weights=mesh.weights4 if group else None,
            )
        )
    if group:
        _, joint_list, skg_blob = group
        for i, (parent, t, q) in enumerate(joint_list):
            scene.joints.append(
                Joint(
                    name=f"joint{i}",
                    parent=parent if 0 <= parent < i else None,
                    translation=tuple(t),
                    rotation=tuple(q),
                    scale=(1.0, 1.0, 1.0),
                )
            )
        scene.clips = skye_skel.skg_clips(skg_blob)
    scene.extras = {"format": "skx", "meshes": len(found)}
    return [scene]
