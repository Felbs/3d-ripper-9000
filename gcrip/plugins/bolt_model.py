"""Mass Media models (``.bmdl`` members of ``BOLT`` archives) - one Scene a member, meshes
placed by their object matrices, materials and textures from the archive's ``.bmat``."""

from __future__ import annotations

import posixpath
import re

import numpy as np

from gcrip.formats import bolt_model
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "bolt_model"
EXT = ".bmdl"
LIST_EXT = ".bmat"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(EXT) and size > 8 and bolt_model.is_model(head)


class _Lists:
    """Material list of each archive in the source, parsed once."""

    def __init__(self, src) -> None:
        self.src = src
        self.cache: dict[str, bolt_model.MaterialList | None] = {}

    def get(self, path: str) -> bolt_model.MaterialList | None:
        folder = posixpath.dirname(path)
        if folder in self.cache:
            return self.cache[folder]
        out = None
        for p in self.src.by_path:
            if posixpath.dirname(p) == folder and p.lower().endswith(LIST_EXT):
                try:
                    out = bolt_model.parse_material_list(self.src.get(p))
                except Exception:  # noqa: BLE001 - a bad list leaves the models untextured
                    out = None
                break
        if len(self.cache) > 64:
            self.cache.clear()
        self.cache[folder] = out
        return out


_cache: dict[int, _Lists] = {}


def _lists(src) -> _Lists | None:
    if src is None or not hasattr(src, "by_path"):
        return None
    key = id(src)
    t = _cache.get(key)
    if t is None or t.src is not src:
        _cache.clear()
        t = _cache[key] = _Lists(src)
    return t


def texture_key(index: int, name: str) -> str:
    """Texture names repeat ("Map #4" several times) and can be Windows paths."""
    base = posixpath.basename(name.replace("\\", "/")).rsplit(".", 1)[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_")
    return f"tex{index:03d}_{stem}" if stem else f"tex{index:03d}"


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = bolt_model.parse(data)
    stem = posixpath.basename(path).split(".")[0]
    scene = Scene(name=f"{stem}_{model.name}" if model.name else stem)
    scene.warnings += model.warnings
    lists = _lists(src)
    matlist = lists.get(path) if lists is not None else None
    materials: dict[int, int] = {}
    for mesh in model.meshes:
        if mesh.material not in materials:
            name = mesh.name or f"material_{mesh.material}"
            tex_key = None
            color = (1.0, 1.0, 1.0, 1.0)
            if matlist is not None and 0 <= mesh.material < len(matlist.materials):
                mat = matlist.materials[mesh.material]
                name = mat.name or name
                ti = mat.texture
                if ti is not None and ti < len(matlist.textures):
                    tex = matlist.textures[ti]
                    tex_key = texture_key(ti, tex.name)
                    if tex_key not in scene.textures:
                        try:
                            scene.textures[tex_key] = tex.decode()
                        except (ValueError, bolt_model.BoltModelError) as e:
                            scene.warnings.append(f"{tex.name}: {e}")
                            tex_key = None
                elif mat.color is not None:
                    color = tuple(float(min(max(c, 0.0), 1.0)) for c in mat.color)
            materials[mesh.material] = len(scene.materials)
            scene.materials.append(MaterialDef(name=name, texture=tex_key, base_color=color))
        pos, nrm = bolt_model.transform(mesh)
        scene.primitives.append(
            Primitive(
                material=materials[mesh.material],
                positions=np.ascontiguousarray(pos, dtype=np.float32),
                indices=mesh.indices,
                normals=None if nrm is None else np.ascontiguousarray(nrm, dtype=np.float32),
                uvs=None if mesh.uvs is None else np.ascontiguousarray(mesh.uvs, dtype=np.float32),
                colors=None
                if mesh.colors is None
                else np.ascontiguousarray(mesh.colors, dtype=np.uint8),
            )
        )
    if not scene.primitives:
        return []
    return [scene]
