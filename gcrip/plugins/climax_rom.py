"""Climax ``.rom`` models (gcrip.formats.climax_rom) from the ``.bad`` archives of ATV: Quad
Power Racing 2, Hot Wheels World Race and The Italian Job: one Scene a model, a primitive a
mesh, textured by the material's name against the archive's ``.bog`` files."""

from __future__ import annotations

import contextlib
import posixpath

from gcrip.formats import climax_bog, climax_rom
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "climax_rom"
_INDEX_ATTR = "_climax_bog_index"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".rom") and climax_rom.is_rom(head, size)


def _index(src) -> dict[str, list[str]]:
    index = getattr(src, _INDEX_ATTR, None)
    if index is not None:
        return index
    index = {}
    for p in getattr(src, "by_path", {}) or {}:
        if p.lower().endswith(".bog"):
            index.setdefault(p.rsplit("/", 1)[-1][:-4].lower(), []).append(p)
    with contextlib.suppress(Exception):
        setattr(src, _INDEX_ATTR, index)
    return index


def _texture(src, path: str, name: str, warnings: list[str]):
    if src is None or not hasattr(src, "by_path") or not name:
        return None
    folder = posixpath.dirname(path)
    hits = _index(src).get(name.lower(), [])
    for p in sorted(hits, key=lambda p: (not p.startswith(folder), len(p))):
        try:
            rgba = climax_bog.decode(src.get(p))
        except Exception as e:  # noqa: BLE001 - try the next copy
            warnings.append(f"{p}: {e}")
            continue
        if rgba is not None:
            return rgba
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = climax_rom.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    slots: dict[int, int] = {}
    for mesh in model.meshes:
        mi = mesh.material
        if mi not in slots:
            name = model.materials[mi] if 0 <= mi < len(model.materials) else ""
            tex = _texture(src, path, name, scene.warnings)
            if tex is not None:
                scene.textures[name] = tex
            slots[mi] = len(scene.materials)
            scene.materials.append(
                MaterialDef(
                    name=name or f"material_{mi}", texture=name if tex is not None else None
                )
            )
        scene.primitives.append(
            Primitive(
                material=slots[mi],
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
            )
        )
    if not scene.primitives:
        return []  # legitimate: a model of points only (attachment markers)
    scene.extras = {
        "format": "climax_rom",
        "version": model.version.decode("latin-1"),
        "patches": sum(m.patches for m in model.meshes),
        "points": [n for n, _ in model.points],
    }
    return [scene]
