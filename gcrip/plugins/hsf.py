"""Hudson HSF models (Mario Party 4-7; gcrip.formats.hsf): one Scene per file with a
primitive per mesh object and material, the object hierarchy as joints and the cenv
envelopes as skin weights."""

from __future__ import annotations

import math
import posixpath

import numpy as np

from gcrip.formats import hsf
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "hsf"


def detect(path: str, head: bytes, size: int) -> bool:
    return hsf.is_hsf(head) and size > 0xB0


def _quat(rx: float, ry: float, rz: float) -> tuple[float, float, float, float]:
    """XYZ Euler (degrees) -> quaternion x, y, z, w."""
    cx, sx = math.cos(math.radians(rx) / 2), math.sin(math.radians(rx) / 2)
    cy, sy = math.cos(math.radians(ry) / 2), math.sin(math.radians(ry) / 2)
    cz, sz = math.cos(math.radians(rz) / 2), math.sin(math.radians(rz) / 2)
    # R = Rz * Ry * Rx applied to column vectors (x first)
    w = cx * cy * cz + sx * sy * sz
    x = sx * cy * cz - cx * sy * sz
    y = cx * sy * cz + sx * cy * sz
    z = cx * cy * sz - sx * sy * cz
    return (x, y, z, w)


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = hsf.parse(data)
    meshes = hsf.meshes(model)
    if not meshes:
        return []
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    scene.joints = [
        Joint(
            o.name or f"obj{i}",
            o.parent if 0 <= o.parent < len(model.objects) and o.parent != i else None,
            tuple(float(v) for v in o.translate),
            _quat(*o.rotate),
            tuple(float(v) if v else 1.0 for v in o.scale),
        )
        for i, o in enumerate(model.objects)
    ]
    skinned = any(m.joints is not None for m in meshes)
    mats: dict[int, int] = {}
    for m in meshes:
        if m.material not in mats:
            ti = hsf.material_texture(model, m.material)
            tex_key = None
            if 0 <= ti < len(model.textures) and model.textures[ti].rgba is not None:
                tex_key = f"{ti}_{model.textures[ti].name}"
                scene.textures.setdefault(tex_key, model.textures[ti].rgba)
            alpha = bool(tex_key) and bool(np.any(scene.textures[tex_key][..., 3] < 255))
            scene.materials.append(
                MaterialDef(
                    name=f"mat{m.material}", texture=tex_key, alpha_blend=alpha, double_sided=True
                )
            )
            mats[m.material] = len(scene.materials) - 1
        joints = weights = None
        if m.joints is not None:
            joints, weights = m.joints, m.weights
        elif skinned:
            joints = np.full((len(m.positions), 4), 0, np.uint16)
            joints[:, 0] = m.object_index
            weights = np.zeros((len(m.positions), 4), np.float32)
            weights[:, 0] = 1.0
        scene.primitives.append(
            Primitive(
                material=mats[m.material],
                positions=m.positions,
                indices=m.indices,
                normals=m.normals,
                uvs=m.uvs,
                colors=m.colors,
                joints=joints,
                weights=weights,
            )
        )
    if not skinned:
        # rigid meshes sit under their object node: bake the node's world transform
        world = _world_matrices(model)
        for prim, m in zip(scene.primitives, meshes, strict=True):
            w = world[m.object_index]
            p = prim.positions @ w[:3, :3].T + w[:3, 3]
            prim.positions = p.astype(np.float32)
            if prim.normals is not None:
                n = prim.normals @ np.linalg.pinv(w[:3, :3])
                ln = np.linalg.norm(n, axis=1, keepdims=True)
                ln[ln == 0] = 1.0
                prim.normals = (n / ln).astype(np.float32)
        scene.joints = []
    scene.extras = {
        "format": "hsf",
        "objects": len(model.objects),
        "meshes": len(meshes),
        "skinned": skinned,
        "textures": len(model.textures),
    }
    return [scene]


def _world_matrices(model: hsf.Hsf) -> list[np.ndarray]:
    n = len(model.objects)
    local = []
    for o in model.objects:
        x, y, z, w = _quat(*o.rotate)
        r = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        m = np.eye(4)
        m[:3, :3] = r @ np.diag([v if v else 1.0 for v in o.scale])
        m[:3, 3] = o.translate
        local.append(m)
    world: list[np.ndarray | None] = [None] * n

    def get(i: int, depth: int = 0) -> np.ndarray:
        if world[i] is None:
            p = model.objects[i].parent
            if 0 <= p < n and p != i and depth < 64:
                world[i] = get(p, depth + 1) @ local[i]
            else:
                world[i] = local[i]
        return world[i]

    return [get(i) for i in range(n)]
