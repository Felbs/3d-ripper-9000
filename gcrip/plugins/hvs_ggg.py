"""High Voltage ``GGG`` models (Billy & Mandy, Kids Next Door) - one Scene a file, textured
through the archive's ``.AGM`` material database and its High Voltage ``.TPL`` members."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import hvs_agm, hvs_ggg, tpl_hvs
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "hvs_ggg"


def detect(path: str, head: bytes, size: int) -> bool:
    return hvs_ggg.is_ggg(head)


class _Archive:
    """The members beside a model: material databases and textures, fetched lazily."""

    def __init__(self, src, path: str) -> None:
        self.src = src
        self.folder = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        self.members: list[str] = []
        if src is not None and hasattr(src, "by_path"):
            n = len(self.folder)
            self.members = [p for p in src.by_path if p.startswith(self.folder) and "/" not in p[n:]]
        self.bindings: dict[str, str] | None = None
        self.textures: dict[str, np.ndarray | None] = {}

    def binding(self, material: str) -> str | None:
        if self.bindings is None:
            self.bindings = {}
            for p in self.members:
                if p.upper().endswith(".AGM"):
                    try:
                        self.bindings.update(hvs_agm.textures(self.src.get(p).decode("latin-1")))
                    except Exception:  # noqa: BLE001 - one bad database must not stop the model
                        continue
        return self.bindings.get(material)

    def texture(self, name: str) -> np.ndarray | None:
        key = name.upper()
        if key not in self.textures:
            img = None
            for p in self.members:
                if posixpath.basename(p).upper() == key + ".TPL":
                    try:
                        blob = self.src.get(p)
                        images = tpl_hvs.images(blob)
                        if images:
                            img = tpl_hvs.decode(blob, images[0])
                    except Exception:  # noqa: BLE001
                        img = None
                    break
            self.textures[key] = img
        return self.textures[key]


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = hvs_ggg.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=model.nodes[0] if model.nodes and model.nodes[0] else stem)
    archive = _Archive(src, path) if src is not None else None
    names = model.materials or [f"material_{k}" for k in range(len(model.meshes))]
    for i, name in enumerate(names):
        texture = None
        if archive is not None and name:
            tex_name = archive.binding(name)
            if tex_name is not None:
                img = archive.texture(tex_name)
                if img is not None:
                    scene.textures[tex_name] = img
                    texture = tex_name
        scene.materials.append(MaterialDef(name=name or f"material_{i}", texture=texture))
    if not scene.materials:
        scene.materials.append(MaterialDef(name="material", texture=None))
    skipped: list[hvs_ggg.Mesh] = []
    for md in hvs_ggg.meshes(data, model, skipped):
        material = md.material if 0 <= md.material < len(scene.materials) else 0
        scene.primitives.append(
            Primitive(
                material=material,
                positions=np.ascontiguousarray(md.positions, dtype=np.float32),
                indices=md.indices,
                normals=None if md.normals is None else np.ascontiguousarray(md.normals, dtype=np.float32),
                uvs=None if md.uvs is None else np.ascontiguousarray(md.uvs, dtype=np.float32),
                colors=None if md.colors is None else np.ascontiguousarray(md.colors, dtype=np.uint8),
            )
        )
    if skipped:
        scene.warnings.append(f"{len(skipped)} meshes index past the vertex arrays and were left out")
    if not scene.primitives:
        raise hvs_ggg.GggError(f"{path}: no triangles")
    return [scene]
