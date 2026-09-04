"""Free Radical ``gcr`` character models (gcrip.formats.frd_gcr) - TimeSplitters 2's
``ob/chrs/*.gcr``: one Scene a file, one primitive a display list, textured by the pak's
``textures/%04d.gct`` members the file's slot table names."""

from __future__ import annotations

import posixpath

from gcrip.formats import frd_gcr, frd_gct
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "frd_gcr"


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gcr") and frd_gcr.is_gcr(head, size)


def _gct(src, path: str, gct: int) -> bytes | None:
    """``textures/NNNN.gct`` from the same pak first, then anywhere on the disc."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    want = f"{gct:04d}.gct"
    hits = [p for p in src.by_path if p.lower().endswith(want)]
    hits.sort(key=lambda p: (not p.startswith(folder + "/"), len(p)))
    for p in hits:
        try:
            return src.get(p)
        except Exception:  # noqa: BLE001 - try the next copy
            continue
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = frd_gcr.parse(data)
    if model is None or not model.batches:
        return []  # legitimate: a character file with no readable display list
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    scene.warnings.extend(model.warnings)
    material_of: dict[int, int] = {}
    for b in model.batches:
        if b.slot not in material_of:
            gct = model.textures[b.slot] if b.slot < len(model.textures) else None
            key = None
            if gct is not None:
                key = f"tex_{gct:04d}"
                if key not in scene.textures:
                    blob = _gct(src, path, gct)
                    rgba = None
                    if blob is not None:
                        try:
                            rgba = frd_gct.decode(blob)
                        except Exception as e:  # noqa: BLE001 - untextured is still a model
                            scene.warnings.append(f"{key}: {e}")
                    if rgba is not None:
                        scene.textures[key] = rgba
                if key not in scene.textures:
                    key = None
            scene.materials.append(
                MaterialDef(name=f"slot_{b.slot}" if gct is None else f"tex_{gct:04d}", texture=key)
            )
            material_of[b.slot] = len(scene.materials) - 1
        scene.primitives.append(
            Primitive(
                material=material_of[b.slot],
                positions=b.positions,
                indices=b.indices,
                normals=b.normals,
                uvs=b.uvs,
                colors=b.colors,
            )
        )
    scene.extras = {
        "format": "frd_gcr",
        "nodes": model.records,
        "bones": model.bones,
        "lods": model.lods,
        "textures": model.textures,
        "kinds": sorted({b.kind for b in model.batches}),
    }
    return [scene]
