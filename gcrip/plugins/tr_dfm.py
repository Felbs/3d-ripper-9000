"""Terminal Reality ``_dfm`` skinned meshes (gcrip.formats.tr_dfm) - BloodRayne, Blowout,
RoadKill, 4x4 Evo 2: one Scene a mesh, the blocks assembled in the skeleton's home pose (the
``.SKL`` the header names, from the same ``.PKG`` first), skinned to its bones, textured by
the material block's ``.TIF``."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import tr_dfm, tr_skl, tr_tex
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "tr_dfm"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".dfm") and tr_dfm.is_dfm(head)


def _find(src, path: str, name: str) -> bytes | None:
    """A member called ``name`` (case-insensitive): the same package first, then anywhere."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    want = name.lower()
    hits = [p for p in src.by_path if p.rsplit("/", 1)[-1].lower() == want]
    hits.sort(key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in hits:
        try:
            return src.get(p)
        except Exception:  # noqa: BLE001 - try the next copy
            continue
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    head = tr_dfm.mesh(data)
    skin = tr_dfm.skin(data)
    blocks = tr_dfm.blocks(data)
    if head is None or skin is None or not blocks:
        return []  # legitimate: not a readable mesh (the identities say which table failed)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    parents = [-1] * head.bone_count
    names = [f"bone_{i}" for i in range(head.bone_count)]
    skl = _find(src, path, head.skeleton) if head.skeleton else None
    bones = tr_skl.bones(skl) if skl else []
    if len(bones) == head.bone_count:
        parents = [b.parent for b in bones]
        names = [b.name for b in bones]
    else:
        scene.warnings.append(
            f"skeleton {head.skeleton!r} not found or {len(bones)} bones for {head.bone_count};"
            " bones are placed by their home translations without a hierarchy"
        )
    world = tr_dfm.home_pose(skin.translations, parents)
    for i in range(head.bone_count):
        parent = parents[i] if 0 <= parents[i] < i else None
        scene.joints.append(
            Joint(
                names[i],
                parent,
                tuple(float(v) for v in skin.translations[i]),
                (0.0, 0.0, 0.0, 1.0),
                (1.0, 1.0, 1.0),
            )
        )
    tex_name = skin.material.rsplit(".", 1)[0] if skin.material else ""
    tex = None
    if tex_name:
        blob = _find(src, path, skin.material)
        if blob is not None:
            try:
                tex = tr_tex.decode(blob)
            except Exception as e:  # noqa: BLE001 - the mesh is still worth having untextured
                scene.warnings.append(f"{skin.material}: {e}")
        if tex is not None:
            scene.textures[tex_name] = tex
    scene.materials.append(
        MaterialDef(name=tex_name or stem, texture=tex_name if tex is not None else None)
    )
    parts = {}
    for k, block in enumerate(blocks):
        v = tr_dfm.vertices(data, block)
        if v is None or not block.triangles:
            scene.warnings.append(f"block {k}: vertex records do not tile")
            continue
        # model space: the weighted sum of each bone-space position moved by its bone
        moved = (
            v.positions
            + world[np.minimum(v.bones, head.bone_count - 1)] * (v.weights > 0)[..., None]
        )
        pos = (moved * v.weights[..., None]).sum(1).astype(np.float32)
        scene.primitives.append(
            Primitive(
                material=0,
                positions=pos,
                indices=tr_dfm.indices(data, block).reshape(-1).astype(np.uint32),
                normals=v.normals,
                uvs=v.uvs,
                joints=v.bones,
                weights=v.weights,
            )
        )
        part = head.parts[block.a].name if block.a < len(head.parts) else f"block_{k}"
        parts[part] = parts.get(part, 0) + block.triangles
    if not scene.primitives:
        return []  # legitimate: every block was refused above, with a warning each
    scene.extras = {
        "format": "tr_dfm",
        "skeleton": head.skeleton,
        "parts": parts,
        "blocks": len(blocks),
    }
    return [scene]
