"""EA Los Angeles 2002 (Medal of Honor: Frontline): ``.msh`` static meshes and ``.cpt``
level compartments (gcrip.formats.ea_la) - one Scene a file, textures decoded from the
``SHPG`` shapes embedded in the material tables; a compartment's geometry file binds through
the level's ``_Art.cpt`` beside it when its own tables carry no shapes."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import ea_la
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_la"


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".msh"):
        return ea_la.is_msh(head, size)
    return low.endswith(".cpt") and ea_la.is_cpt(head, size)


def _art_materials(src, path: str) -> tuple[bytes, list[ea_la.Material]] | None:
    """The ``<level>_Art.cpt`` in the parent level.viv of a comp.viv compartment."""
    if src is None or not hasattr(src, "by_path"):
        return None
    folder = posixpath.dirname(path)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    level = stem.split("_ART", 1)[0].split("_Art", 1)[0]
    candidates = [
        p for p in src.by_path if p.lower().endswith("_art.cpt") and level.lower() in p.lower()
    ]
    candidates.sort(key=lambda p: (posixpath.dirname(p) != folder, len(p)))
    for p in candidates:
        try:
            art = src.get(p)
            model = ea_la.parse(art)
        except Exception:  # noqa: BLE001 - a bad art file leaves the compartment untextured
            continue
        if model.materials:
            return art, model.materials
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = ea_la.parse(data)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scene = Scene(name=stem)
    scene.warnings += model.warnings
    art = None
    if any(m.shared is not None for m in model.materials) and path.lower().endswith(".cpt"):
        art = _art_materials(src, path)
    art_tables: list[list[ea_la.Material]] = [[], []]
    if art is not None:
        for m in art[1]:
            art_tables[m.table].append(m)
    materials: dict[int, int] = {}
    cache: dict[tuple[int, int], str | None] = {}
    for ch in model.chunks:
        if ch.material not in materials:
            key = None
            if 0 <= ch.material < len(model.materials):
                m = model.materials[ch.material]
                blob = data
                if m.shared is not None and art is not None:
                    table = art_tables[m.table]
                    if m.shared < len(table):
                        m, blob = table[m.shared], art[0]
                ck = (id(blob), m.shape)
                if ck not in cache:
                    img = None
                    try:
                        img = ea_la.material_texture(blob, m)
                    except Exception as e:  # noqa: BLE001 - one bad shape, the rest bind
                        scene.warnings.append(f"material {ch.material}: {e}")
                    name = f"shape_{'art_' if blob is not data else ''}{m.shape:x}"
                    if img is not None:
                        scene.textures[name] = img
                    cache[ck] = name if img is not None else None
                key = cache[ck]
            materials[ch.material] = len(scene.materials)
            scene.materials.append(MaterialDef(name=f"material_{ch.material}", texture=key))
        scene.primitives.append(
            Primitive(
                material=materials[ch.material],
                positions=np.ascontiguousarray(ch.positions, dtype=np.float32),
                indices=ch.triangles.reshape(-1).astype(np.uint32),
                normals=ch.normals,
                uvs=ch.uvs,
                colors=ch.colors,
            )
        )
    return [scene] if scene.primitives else []
