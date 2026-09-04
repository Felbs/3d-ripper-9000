"""EA ``GCsk`` characters (gcrip.formats.ea_cact) - the ``scbm`` mesh members behind the
``Cact`` actors of The Lord of the Rings: The Return of the King / The Third Age ``.scg``
SHOC streams.  One Scene a model, a primitive a (mesh, material), textures matched by name
from the sibling ``txf*`` members - materials are literally texture names (``froface``,
``gimbody``).  Positions are model space at bind pose, so the baked mesh needs no skeleton;
the "05" shadow-volume mesh carries no display list and is skipped."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import ea_cact, ea_txg
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_cact"


def detect(path: str, head: bytes, size: int) -> bool:
    return ea_cact.is_character(head)


def _pictures(src, path: str) -> dict[str, tuple[bytes, object]]:
    """Every texture of the sibling ``txf*`` members of the same archive, by name."""
    out: dict[str, tuple[bytes, object]] = {}
    by_path = getattr(src, "by_path", None) or {}
    folder = posixpath.dirname(path)
    for p in by_path:
        if posixpath.dirname(p) != folder or not posixpath.basename(p).startswith("txf"):
            continue
        try:
            blob = src.get(p)
        except Exception:  # noqa: BLE001 - a missing group leaves the character untextured
            continue
        for t in ea_txg.textures(blob):
            out.setdefault(t.name.lower(), (blob, t))
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    got = ea_cact.model(data)
    if got is None:
        return []
    pictures = _pictures(src, path) if src is not None else {}
    scene = Scene(name=got.name or posixpath.basename(path))
    slots: dict[str, int] = {}
    for mesh in got.meshes:
        if mesh.shadow:
            continue
        for element in mesh.elements:
            for corners in element.strips:
                tri = ea_cact.strip_indices(corners)
                if not len(tri):
                    continue
                if element.name not in slots:
                    texture = None
                    hit = pictures.get(element.name.lower())
                    if hit is not None:
                        rgba = ea_txg.decode(hit[0], hit[1])
                        if rgba is not None:
                            texture = element.name.lower()[:64]
                            scene.textures[texture] = rgba
                    scene.materials.append(MaterialDef(name=element.name, texture=texture))
                    slots[element.name] = len(scene.materials) - 1
                c = corners.astype(np.int64)
                prim = Primitive(
                    material=slots[element.name],
                    positions=np.ascontiguousarray(mesh.positions[c[:, 0]]),
                    indices=tri.ravel().astype(np.uint32),
                )
                if mesh.normals is not None and int(c[:, 1].max()) < len(mesh.normals):
                    prim.normals = np.ascontiguousarray(mesh.normals[c[:, 1]])
                if mesh.uvs is not None and int(c[:, 2].max()) < len(mesh.uvs):
                    prim.uvs = np.ascontiguousarray(mesh.uvs[c[:, 2]])
                scene.primitives.append(prim)
    if not scene.primitives:
        return []
    scene.extras = {
        "format": "ea_cact",
        "meshes": [m.name for m in got.meshes if not m.shadow],
        "skinned": True,
        "bones": len({int(b) for m in got.meshes for b in m.bones.ravel() if b != 0xFF}),
    }
    return [scene]
