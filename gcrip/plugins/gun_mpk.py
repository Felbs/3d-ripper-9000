"""Neversoft Gun (GameCube) ``.mpk.ngc`` map packs (gcrip.formats.gun_mpk):
the level geometry of the 315 map packs - display-list meshes over the pack's
global vertex arrays, one primitive per material checksum.  Prop objects with
inline arrays and the embedded textures are not extracted yet."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import gun_mpk
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "gun_mpk"
MIN_SIZE = 0x1000  # 918 of the 1,233 .mpk.ngc are 32-byte AB-fill placeholders


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".mpk.ngc") and size >= MIN_SIZE and gun_mpk.is_mpk(head)


def extract(data: bytes, path: str, src) -> list[Scene]:
    level = gun_mpk.parse(data)
    stem = posixpath.basename(path).split(".", 1)[0] or "level"
    scene = Scene(name=stem)

    # one primitive per material checksum
    by_mat: dict[int, list[gun_mpk.Mesh]] = {}
    for mesh in level.meshes:
        by_mat.setdefault(mesh.material, []).append(mesh)

    for material, meshes in sorted(by_mat.items()):
        slot = len(scene.materials)
        scene.materials.append(MaterialDef(f"mat_{material:08x}", None, double_sided=True))
        pos_idx = []
        nrm_idx = []
        col_idx = []
        uv_idx = []
        tris = []
        base = 0
        for m in meshes:
            pi = m.corners["pos"]
            pos_idx.append(pi)
            nrm_idx.append(m.corners.get("nrm"))
            col_idx.append(m.corners.get("col0"))
            uv_idx.append(m.corners.get("tex0"))
            tris.append(m.triangles + base)
            base += len(pi)
        pi = np.concatenate(pos_idx)
        indices = np.concatenate(tris).reshape(-1).astype(np.uint32)
        normals = uvs = colors = None
        if all(x is not None for x in nrm_idx):
            ni = np.clip(np.concatenate(nrm_idx), 0, len(level.normals) - 1)
            normals = level.normals[ni]
        if all(x is not None for x in uv_idx):
            ti = np.clip(np.concatenate(uv_idx), 0, len(level.uvs) - 1)
            uvs = level.uvs[ti]
        if all(x is not None for x in col_idx):
            ci = np.clip(np.concatenate(col_idx), 0, len(level.colors) - 1)
            colors = level.colors[ci].astype(np.float32) / 255.0
        scene.primitives.append(
            Primitive(
                material=slot,
                positions=level.positions[pi],
                indices=indices,
                normals=normals,
                uvs=uvs,
                colors=colors,
            )
        )

    scene.warnings.extend(level.warnings)
    if level.rejected:
        scene.warnings.append(
            f"{level.rejected} prop meshes with inline (non-global) arrays skipped"
        )
    scene.extras = {
        "format": "gun_mpk",
        "meshes": len(level.meshes),
        "triangles": level.triangle_count,
        "materials": len(scene.materials),
        "rejected_prop_meshes": level.rejected,
    }
    return [scene]
