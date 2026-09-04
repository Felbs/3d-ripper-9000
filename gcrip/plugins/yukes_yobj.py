"""Yuke's ``YOBJ`` meshes (gcrip.formats.yukes_yobj) - the ``.ymg`` files of the WWE discs.
One Scene a file, one primitive a mesh (X8 / XIX) or a material group (Day of Reckoning,
textured from the sibling ``.tex`` pack's TPLs)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import tpl, yukes_yobj
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "yukes_yobj"

# gradient / mask / normal-ish helper textures a Day of Reckoning material stacks under its
# picture: g_skin, m_face, n_body ...  The picture is the first stage without such a prefix.
HELPER_PREFIXES = ("g_", "m_", "n_")
# Day of Reckoning models are y-down (a wrestler's head at y = -175); a half turn about x
# stands them up without mirroring
UPRIGHT = np.array([1.0, -1.0, -1.0], np.float32)


def detect(path: str, head: bytes, size: int) -> bool:
    return yukes_yobj.is_yobj(head)


def _picture(textures: list[str]) -> str | None:
    for t in textures:
        if not t.lower().startswith(HELPER_PREFIXES):
            return t
    return textures[0] if textures else None


def _texture(src, path: str, name: str) -> bytes | None:
    """``name.tpl`` from the ``.tex`` pack beside this ``.ymg`` (the same stem first)."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    want = f"{name}.tpl".lower()
    hits = [p for p in src.by_path if p.rsplit("/", 1)[-1].lower() == want]
    hits.sort(
        key=lambda p: (
            not p.lower().startswith(f"{folder}/{stem}.tex/".lower()),
            not p.startswith(folder + "/"),
            len(p),
        )
    )
    for p in hits:
        try:
            return src.get(p)
        except Exception:  # noqa: BLE001 - try the next copy
            continue
    return None


class _Binder:
    """Scene materials by YOBJ material index, their picture pulled from the ``.tex`` pack
    on first use."""

    def __init__(self, scene: Scene, materials, path: str, src):
        self.scene, self.materials, self.path, self.src = scene, materials, path, src
        self.index: dict[int, int] = {}

    def __call__(self, material: int) -> int:
        if material in self.index:
            return self.index[material]
        scene = self.scene
        mat = self.materials[material] if material < len(self.materials) else None
        picture = _picture(mat.textures) if mat else None
        key = None
        if picture:
            if picture not in scene.textures:
                blob = _texture(self.src, self.path, picture)
                if blob is not None:
                    try:
                        images = tpl.parse(blob)
                        if images:
                            scene.textures[picture] = images[0].decode()
                    except Exception as e:  # noqa: BLE001 - untextured is still a model
                        scene.warnings.append(f"{picture}.tpl: {e}")
            if picture in scene.textures:
                key = picture
        # the diffuse (0xb2 grey on wrestlers) is what GX lights multiply the picture by; a
        # textured glTF material is left white so viewers do not darken it twice
        diffuse = (
            tuple(c / 255.0 for c in mat.diffuse) if mat and key is None else (1.0, 1.0, 1.0, 1.0)
        )
        scene.materials.append(
            MaterialDef(name=picture or f"material_{material:02d}", texture=key, base_color=diffuse)
        )
        self.index[material] = len(scene.materials) - 1
        return self.index[material]


def _dor(data: bytes, path: str, src) -> list[Scene]:
    model = yukes_yobj.dor_model(data)
    if model is None or not model.groups:
        return []  # legitimate: a version-4 YOBJ with no readable group (warnings say which)
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    scene.warnings.extend(model.warnings)
    bind = _Binder(scene, model.materials, path, src)
    for g in model.groups:
        scene.primitives.append(
            Primitive(
                material=bind(g.material),
                positions=g.positions * UPRIGHT,
                indices=g.indices,
                normals=g.normals * UPRIGHT,
                uvs=g.uvs,
            )
        )
    scene.extras = {
        "format": "yukes_yobj",
        "variant": "dor",
        "upright": "rotated 180 degrees about x: the files are y-down",
        "meshes": model.meshes,
        "groups": len(model.groups),
        "bones": [b.name for b in model.bones],
        "stages": {
            f"material_{i:02d}": m.textures for i, m in enumerate(model.materials) if m.textures
        },
        "agreement": round(
            sum(g.agreement * len(g.indices) for g in model.groups)
            / max(1, sum(len(g.indices) for g in model.groups)),
            3,
        ),
    }
    return [scene]


def extract(data: bytes, path: str, src) -> list[Scene]:
    if yukes_yobj.is_dor(data):
        return _dor(data, path, src)
    found = yukes_yobj.meshes(data)
    if not found:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    materials, _names = yukes_yobj.materials(data)
    bind = _Binder(scene, materials, path, src)
    for i, mesh in enumerate(found):
        if mesh.groups is not None and materials:
            # XIX: one primitive a material, the vertices it touches re-indexed
            tri = mesh.indices.reshape(-1, 3)
            by_material = np.asarray(mesh.groups, np.int64)
            for material in sorted(set(mesh.groups)):
                sub = tri[by_material == material]
                used, local = np.unique(sub.reshape(-1), return_inverse=True)
                scene.primitives.append(
                    Primitive(
                        material=bind(material),
                        positions=mesh.positions[used],
                        indices=local.reshape(-1).astype(np.uint32),
                        normals=mesh.normals[used],
                        uvs=mesh.uvs[used] if mesh.uvs is not None else None,
                        colors=mesh.colors[used] if mesh.colors is not None else None,
                    )
                )
            continue
        scene.materials.append(MaterialDef(name=f"{stem}_{i:04d}", texture=None))
        scene.primitives.append(
            Primitive(
                material=len(scene.materials) - 1,
                positions=mesh.positions,
                indices=mesh.indices,
                normals=mesh.normals,
                uvs=mesh.uvs,
                colors=mesh.colors,
            )
        )
    scene.extras = {
        "format": "yukes_yobj",
        "meshes": len(found),
        "variant": "xix" if any(m.uvs is not None for m in found) else "x8",
        "textures": len(scene.textures),
    }
    return [scene]
