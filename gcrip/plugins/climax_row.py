"""Climax ``.row`` worlds (gcrip.formats.climax_row): a track a Scene, the node tree's meshes
merged a primitive per texture, patches tessellated, textures by name against the archive's
``.bog`` files (gcrip.plugins.climax_rom does the lookup)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import climax_row
from gcrip.plugins import climax_rom as rom_plugin
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "climax_row"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".row") and climax_row.is_row(head, size)


def extract(data: bytes, path: str, src) -> list[Scene]:
    world = climax_row.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += world.warnings
    groups: dict[int, list] = {}
    for mesh in world.meshes:
        groups.setdefault(mesh.texture, []).append(mesh)
    for ti in sorted(groups):
        name = world.textures[ti] if 0 <= ti < len(world.textures) else ""
        tex = rom_plugin._texture(src, path, name, scene.warnings)
        if tex is not None:
            scene.textures[name] = tex
        slot = len(scene.materials)
        scene.materials.append(
            MaterialDef(name=name or f"texture_{ti}", texture=name if tex is not None else None)
        )
        parts = groups[ti]
        base = 0
        idx = []
        for m in parts:
            idx.append(m.indices + base)
            base += len(m.positions)
        colors = None
        if all(m.colors is not None for m in parts):
            colors = np.concatenate([m.colors for m in parts])
        scene.primitives.append(
            Primitive(
                material=slot,
                positions=np.concatenate([m.positions for m in parts]),
                indices=np.concatenate(idx).astype(np.uint32),
                normals=np.concatenate([m.normals for m in parts]),
                uvs=np.concatenate([m.uvs for m in parts]),
                colors=colors,
            )
        )
    if not scene.primitives:
        return []  # legitimate: a world of markers only
    scene.extras = {
        "format": "climax_row",
        "version": world.version.decode("latin-1"),
        "nodes": world.nodes,
        "patches": sum(m.patches for m in world.meshes),
        "meshes": len(world.meshes),
    }
    return [scene]
