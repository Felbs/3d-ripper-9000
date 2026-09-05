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
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "ea_cact"
BBOX_PAD = 0.25


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


def _rig_for(src, path: str) -> ea_cact.Rig | None:
    """The ``rcb`` member of the same index as this ``scbm`` - Frodo's ``scbm_35001`` binds
    ``rcb_35001`` - parsed to a skeleton, or None."""
    if src is None or not getattr(src, "by_path", None):
        return None
    stem = posixpath.basename(path)
    kind, _, index = stem.partition("_")
    if kind.split(".")[0] != "scbm" or not index:
        return None
    sibling = posixpath.join(posixpath.dirname(path), f"rcb_{index}")
    if sibling not in src.by_path:
        return None
    try:
        return ea_cact.rig(src.get(sibling))
    except Exception:  # noqa: BLE001 - a bad rig must not cost the baked mesh
        return None


def _rig_fits(rig: ea_cact.Rig, meshes) -> bool:
    """The gate before a skeleton is attached: the mesh renders correctly with no rig at
    all (positions are baked model space), so a wrong skeleton must never regress it.
    The rig is taken only when every bone byte the vertices carry has a joint, and every
    joint's bind position lands inside the mesh bounding box (padded 25%)."""
    used = [int(b) for m in meshes for b in m.bones.ravel() if b != 0xFF]
    if used and max(used) >= len(rig.joints):
        return False
    pts = np.concatenate([m.positions for m in meshes if len(m.positions)])
    if not len(pts):
        return False
    lo, hi = pts.min(0), pts.max(0)
    pad = (hi - lo) * BBOX_PAD + 1e-3
    world = np.array([j.world for j in rig.joints])
    return bool(np.all((world >= lo - pad) & (world <= hi + pad)))


def extract(data: bytes, path: str, src) -> list[Scene]:
    got = ea_cact.model(data)
    if got is None:
        return []
    pictures = _pictures(src, path) if src is not None else {}
    rig = _rig_for(src, path)
    if rig is not None and not _rig_fits(rig, [m for m in got.meshes if not m.shadow]):
        rig = None
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
                if rig is not None:
                    prim.joints, prim.weights = _skin(mesh, c[:, 0])
                scene.primitives.append(prim)
    if not scene.primitives:
        return []
    if rig is not None:
        for i, j in enumerate(rig.joints):
            scene.joints.append(
                Joint(
                    name=f"joint{i}",
                    parent=j.parent if j.parent >= 0 else None,
                    translation=j.translation,
                    rotation=j.rotation,
                    scale=j.scale,
                )
            )
    scene.extras = {
        "format": "ea_cact",
        "meshes": [m.name for m in got.meshes if not m.shadow],
        "skinned": True,
        "rigged": rig is not None,
        "bones": len({int(b) for m in got.meshes for b in m.bones.ravel() if b != 0xFF}),
    }
    return [scene]


def _skin(mesh, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(N,4) joint indices and weights for the corner rows: bone A at weight/128 and bone B
    at the remainder, ``(A, 0xff)`` meaning A alone at 1.0."""
    a = mesh.bones[rows, 0].astype(np.uint16)
    b = mesh.bones[rows, 1]
    w = mesh.weights[rows].astype(np.float32)
    single = b == 0xFF
    w[single] = 1.0
    joints = np.zeros((len(rows), 4), np.uint16)
    weights = np.zeros((len(rows), 4), np.float32)
    joints[:, 0] = a
    weights[:, 0] = w
    joints[:, 1] = np.where(single, 0, b).astype(np.uint16)
    weights[:, 1] = np.where(single, 0.0, 1.0 - w)
    return joints, weights
