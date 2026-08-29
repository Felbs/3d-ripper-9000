"""Radical Entertainment Pure3D files (``.p3d`` / ``P3DZ``): Simpsons Hit & Run, Simpsons
Road Rage, Hulk, The Incredible Hulk, Crash Tag Team Racing, Dark Summit, Monsters Inc,
Godzilla ... (gcrip.formats.p3d).  One Scene per Skin (with its skeleton as joints) and one
Scene with every static Mesh of the file; textures come from the file's own Texture
chunks through the shaders' TEX parameter."""

from __future__ import annotations

import os

import numpy as np

from gcrip.formats import p3d
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "p3d"


def detect(path: str, head: bytes, size: int) -> bool:
    return p3d.is_p3d(head) and size >= 64


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


def _joints(skel: list[p3d.Joint]) -> list[Joint]:
    """Pure3D rest poses are parent-relative, row-vector matrices (translation in row 3)."""
    out = []
    for j in skel:
        m = j.rest.astype(np.float64).T  # column convention
        r = m[:3, :3]
        scale = np.linalg.norm(r, axis=0)
        scale[scale == 0] = 1.0
        rot = r / scale
        if np.linalg.det(rot) < 0:
            scale[0] *= -1
            rot[:, 0] *= -1
        q = np.array(_quat(rot), np.float64)
        q /= np.linalg.norm(q) or 1.0
        out.append(
            Joint(
                j.name,
                j.parent,
                tuple(float(v) for v in m[:3, 3]),
                tuple(float(v) for v in q),
                tuple(float(v) for v in scale),
            )
        )
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    chunks = p3d.parse(data)
    meshes = p3d.meshes(chunks)
    if not meshes:
        return []
    skeletons = p3d.skeletons(chunks)
    shader_tex = p3d.shader_textures(chunks)
    textures = p3d.textures(chunks)
    stem = os.path.basename(path).rsplit(".", 1)[0]

    def fill(scene: Scene, mesh: p3d.Mesh, skinned: bool) -> None:
        for g in mesh.groups:
            tex = shader_tex.get(g.shader)
            if tex is not None and tex in textures:
                scene.textures.setdefault(tex, textures[tex])
            else:
                tex = None
            scene.materials.append(MaterialDef(name=g.shader or mesh.name, texture=tex))
            scene.primitives.append(
                Primitive(
                    material=len(scene.materials) - 1,
                    positions=g.positions,
                    indices=g.indices,
                    normals=g.normals,
                    uvs=g.uvs,
                    colors=g.colors,
                    joints=g.joints if skinned else None,
                    weights=g.weights if skinned else None,
                )
            )

    scenes: list[Scene] = []
    static = Scene(name=stem)
    for mesh in meshes:
        if mesh.skeleton is not None and mesh.skeleton in skeletons:
            scene = Scene(name=f"{stem}_{mesh.name}" if len(meshes) > 1 else stem)
            scene.joints = _joints(skeletons[mesh.skeleton])
            skinned = all(g.joints is not None for g in mesh.groups) and bool(scene.joints)
            if skinned:
                top = max(int(g.joints.max()) for g in mesh.groups)
                skinned = top < len(scene.joints)
            fill(scene, mesh, skinned)
            scene.extras = {"format": "p3d", "skeleton": mesh.skeleton, "skinned": skinned}
            scenes.append(scene)
        else:
            fill(static, mesh, False)
    if static.primitives:
        static.extras = {"format": "p3d", "meshes": sum(1 for m in meshes if m.skeleton is None)}
        scenes.insert(0, static)
    return scenes
