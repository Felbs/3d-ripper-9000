"""Free Radical ``gcr`` models (gcrip.formats.frd_gcr) - TimeSplitters 2's characters,
props and guns (``ob/**/*.gcr``), its levels (``bg/level*/level*.gcr``) and Future Perfect's
props: one Scene a file, one primitive a display list, textured by the pak's
``textures/%04d.gct`` members the file's slot table names (TS2) or by the gct the file
embeds (Future Perfect)."""

from __future__ import annotations

import posixpath

from gcrip.formats import frd_gcr, frd_gct
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "frd_gcr"


def detect(path: str, head: bytes, size: int) -> bool:
    """Future Perfect's paks name their members by hash, so the suffix cannot be required;
    the three header shapes are specific enough on their own."""
    return (
        frd_gcr.is_gcr(head, size)
        or frd_gcr.is_level(head, size)
        or frd_gcr.is_fp(head, size)
        or frd_gcr.is_b(head, size)
    )


def _gct(src, path: str, gct: int, hashed: bool = False) -> bytes | None:
    """``textures/NNNN.gct`` (TimeSplitters 2) or the ``HHHHHHHH_NNNN`` member Future
    Perfect names by hash - from the same pak first, then anywhere on the disc."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    if hashed:
        want = f"{gct:08x}_"
        hits = [p for p in src.by_path if p.rsplit("/", 1)[-1].lower().startswith(want)]
    else:
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
    level = frd_gcr.is_level(data[:0x20], len(data))
    arrays = not level and frd_gcr.b_block(data) is not None
    embedded = not level and (arrays or frd_gcr.is_fp(data[:12], len(data)))
    if level:
        model = frd_gcr.parse_level(data)
    elif arrays:
        model = frd_gcr.parse_b(data)
    elif embedded:
        model = frd_gcr.parse_fp(data)
    else:
        model = frd_gcr.parse(data)
    if model is None or not model.batches:
        return []  # legitimate: a file with no readable display list (warnings say why)
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    scene.warnings.extend(model.warnings)
    material_of: dict[int, int] = {}
    for b in model.batches:
        if b.slot not in material_of:
            gct = model.textures[b.slot] if b.slot < len(model.textures) else None
            key = None
            if gct is not None:
                if embedded:
                    key = f"slot_{b.slot}" if gct >= 0 else f"tex_{-gct:08x}"
                else:
                    key = f"tex_{gct:04d}"
                if key not in scene.textures:
                    # Future Perfect embeds its gct behind the slot table or names one by
                    # hash; TS2 names one in the pak by id
                    if embedded:
                        blob = data[gct:] if gct >= 0 else _gct(src, path, -gct, hashed=True)
                    else:
                        blob = _gct(src, path, gct)
                    rgba = None
                    if blob is not None:
                        try:
                            rgba = frd_gct.decode(blob)
                        except Exception as e:  # noqa: BLE001 - untextured is still a model
                            scene.warnings.append(f"{key}: {e}")
                    if rgba is not None:
                        scene.textures[key] = rgba
                name = key
                if key not in scene.textures:
                    key = None
            else:
                name = f"slot_{b.slot}"
            scene.materials.append(MaterialDef(name=name, texture=key))
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
        "flavour": "level"
        if level
        else ("arrays" if arrays else ("future_perfect" if embedded else "character")),
        "nodes": model.records,
        "bones": model.bones,
        "lods": model.lods,
        "textures": model.textures,
        "kinds": sorted({b.kind for b in model.batches}),
    }
    return [scene]
