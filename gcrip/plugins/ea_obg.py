"""EA ``OBG`` terrain (gcrip.formats.ea_obg) - the ``ter`` members of the Tiger Woods ``SHOC``
archives.  One Scene a member: the shared position array, indexed by every element's strip."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import ea_obg, ea_txg
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "ea_obg"
MIN_TRIANGLES = 4


def detect(path: str, head: bytes, size: int) -> bool:
    return ea_obg.is_obg(head)


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
        except Exception:  # noqa: BLE001 - a missing group leaves the terrain untextured
            continue
        for t in ea_txg.textures(blob):
            out.setdefault(t.name.lower(), (blob, t))
    return out


def _named(data, found, pos, named, stem, src=None, path="") -> list[Scene]:
    """RotK / Third Age: a primitive a named element, uvs and colours from the typed arrays,
    the picture of the same name from the archive's texture groups."""
    pictures = _pictures(src, path) if src is not None else {}
    uv_at = ea_obg.typed_array(data, ea_obg.UV_TYPE, found)
    col_at = ea_obg.typed_array(data, ea_obg.COLOR_TYPE, found)
    uvs = None
    if uv_at and uv_at[2] == 1:
        uvs = np.frombuffer(data, ">i2", uv_at[1] * 2, uv_at[0]).reshape(-1, 2).astype(np.float32)
        uvs = uvs * ea_obg.UV_SCALE
    colors = None
    if col_at and col_at[2] == 1:
        colors = np.frombuffer(data, np.uint8, col_at[1] * 4, col_at[0]).reshape(-1, 4)
        colors = colors.astype(np.float32) / 255.0
    scene = Scene(name=stem)
    slots: dict[str, int] = {}
    for e in named:
        c = e.corners.astype(np.int64)
        if int(c[:, 0].max()) >= len(pos):
            continue
        a, b, d = c[:-2], c[1:-1], c[2:]
        keep = (a[:, 0] != b[:, 0]) & (b[:, 0] != d[:, 0]) & (a[:, 0] != d[:, 0])
        odd = (np.arange(len(a)) & 1).astype(bool)
        tri = np.where(
            odd[:, None],
            np.arange(len(a))[:, None] + [[1, 0, 2]],
            np.arange(len(a))[:, None] + [[0, 1, 2]],
        )[keep]
        if len(tri) < 1:
            continue
        if e.name not in slots:
            texture = None
            hit = pictures.get(e.name.lower())
            if hit is not None:
                rgba = ea_txg.decode(hit[0], hit[1])
                if rgba is not None:
                    texture = e.name.lower()[:64]
                    scene.textures[texture] = rgba
            scene.materials.append(MaterialDef(name=e.name, texture=texture))
            slots[e.name] = len(scene.materials) - 1
        prim = Primitive(
            material=slots[e.name],
            positions=np.ascontiguousarray(pos[c[:, 0]]).astype(np.float32),
            indices=tri.ravel().astype(np.uint32),
        )
        if uvs is not None and int(c[:, 1].max()) < len(uvs):
            prim.uvs = np.ascontiguousarray(uvs[c[:, 1]])
        if colors is not None and int(c[:, 2].max()) < len(colors):
            prim.colors = np.ascontiguousarray(colors[c[:, 2]])
        scene.primitives.append(prim)
    if not scene.primitives:
        return []
    scene.extras = {"format": "ea_obg", "elements": len(named), "named": True}
    return [scene]


def extract(data: bytes, path: str, src) -> list[Scene]:
    found = ea_obg.chunks(data)
    pos = ea_obg.positions(data, found)
    if pos is None:
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "terrain"
    named = ea_obg.named_elements(data, found)
    if named:
        return _named(data, found, pos, named, stem, src, path)
    tri = ea_obg.triangles(data, len(pos), found)
    if len(tri) < MIN_TRIANGLES:
        return []
    scene = Scene(name=stem)
    scene.materials = [MaterialDef(name=stem, texture=None)]
    scene.primitives = [
        # an index into scene.materials, not the material's name - passing the name raises
        # inside the exporter and cost Tiger Woods 06 all 665 of its terrain meshes
        Primitive(material=0, positions=pos.astype("f4"), indices=tri.astype("u4").ravel())
    ]
    scene.extras = {"format": "ea_obg", "elements": sum(1 for c in found if c.tag == b"ELDA")}
    return [scene]
