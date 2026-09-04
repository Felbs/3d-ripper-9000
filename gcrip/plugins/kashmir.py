"""Kashmir ``.dat`` scenes (gcrip.formats.kashmir): City Racer, Taxi 3, Speed Challenge.
One Scene a file - every node's mesh placed through its parents, a primitive a texture."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import kashmir
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "kashmir"
MAX_TEXTURE_KEY = 64


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".tga"):
        # the discs' standalone pictures carry the same GameCube header as the embedded ones
        return head[1:8] == kashmir.GC_TAG
    return low.endswith(".dat") and kashmir.is_kashmir(head, size)


def _picture(data: bytes, path: str) -> list[Scene]:
    rgba = kashmir.gc_texture(data)
    if rgba is None:
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=name)
    scene.textures[name[:MAX_TEXTURE_KEY]] = rgba
    scene.extras = {"textures_only": True, "format": "kashmir_tga"}
    return [scene]


def _material(
    scene: Scene, slots: dict[str | None, int], sc: kashmir.Scene, name: str | None
) -> int:
    key = name if name in sc.textures else None
    if key in slots:
        return slots[key]
    texture = None
    if key is not None:
        texture = key[:MAX_TEXTURE_KEY]
        scene.textures[texture] = sc.textures[key]
    scene.materials.append(MaterialDef(name=name or "untextured", texture=texture))
    slots[key] = len(scene.materials) - 1
    return slots[key]


def extract(data: bytes, path: str, src) -> list[Scene]:
    if path.lower().endswith(".tga"):
        return _picture(data, path)
    sc = kashmir.parse(data)
    if sc is None or not sc.meshes:
        return []
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    scene.warnings.extend(sc.warnings)
    slots: dict[str | None, int] = {}
    memo: dict = {}
    placed = 0
    for ident, n in sc.nodes.items():
        m = sc.meshes.get(n.mesh)
        if m is None or not len(m.triangles):
            continue
        rot, pos = kashmir.world(sc, ident, memo)
        positions = (m.positions.astype(np.float64) @ rot.T + pos).astype(np.float32)
        placed += 1
        for slot in np.unique(m.materials):
            mat_id = n.materials[slot] if slot < len(n.materials) else None
            name = sc.materials.get(mat_id) if mat_id is not None else None
            material = _material(scene, slots, sc, name)
            pick = m.materials == slot
            tri = m.triangles[pick]
            uvi = m.uv_indices[pick]
            key = tri * (len(m.uvs) + 1) + uvi
            uniq, inverse = np.unique(key.ravel(), return_inverse=True)
            v = uniq // (len(m.uvs) + 1)
            u = uniq % (len(m.uvs) + 1)
            scene.primitives.append(
                Primitive(
                    material=material,
                    positions=np.ascontiguousarray(positions[v]),
                    indices=inverse.reshape(-1).astype(np.uint32),
                    uvs=np.ascontiguousarray(m.uvs[u]),
                )
            )
    if not scene.primitives:
        return []
    scene.extras = {
        "format": "kashmir",
        "meshes": len(sc.meshes),
        "placed": placed,
        "textures_in_file": len(sc.textures),
    }
    return [scene]
