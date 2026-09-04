"""Visual Concepts ``SCNE`` scene members (gcrip.formats.vc_scene) - the models inside
``game.dat``'s ``.IFF`` members: players, referees, coaches, the NBA ball, baskets, nets,
icons, the ESPN overlay props.  Also sweeps the member's generic record run for ``RTXT``
texture records living outside texture banks (``GAMEDATA.IFF`` carries 58 crowd/coach
textures that way, and the ``HTXT`` uniform members carry one ``unif`` record each), so it
claims ``HTXT`` members too.

One Scene per scene record that yields meshes, named after the member and the record's
node strings; one textures-only Scene for the inline ``RTXT`` records.  Mesh-to-texture
binding lives in the unmapped node graph, so materials name no texture yet."""

from __future__ import annotations

import posixpath
import re

import numpy as np

from gcrip.formats import vc_iff, vc_pack, vc_scene
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "vc_scene"

TAGS = (b"ENCS", b"HTXT")
#: a node name is a proper C string in the record's string table - NUL-bounded, which the
#: pseudo-words that occur inside geometry bytes essentially never are
_WORD = re.compile(rb"(?<=\x00)[A-Za-z_][A-Za-z0-9_]{3,31}(?=\x00)")


def detect(path: str, head: bytes, size: int) -> bool:
    if len(head) < 21:
        return False
    return head[16:20] in TAGS or (vc_pack.is_packed(head) and head[17:21] in TAGS)


def _label(rec: bytes) -> str:
    """A recognizable name from the record's node strings: the last plain identifiers
    (node names trail the texture paths), skipping the skeleton vocabulary."""
    skip = {b"root", b"locator", b"PADDING"}
    words = [w for w in _WORD.findall(rec) if w not in skip and not w.startswith(b"lambert")]
    return words[-1].decode("latin-1") if words else ""


def extract(data: bytes, path: str, src) -> list[Scene]:
    if data[16:20] not in TAGS and vc_pack.is_packed(data[:64]):
        try:
            data = vc_pack.unpack(data)
        except vc_pack.PackError as exc:
            raise vc_pack.PackError(f"{path}: {exc}") from None
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "scene"
    scenes: list[Scene] = []
    textures = Scene(name=f"{stem}_textures")
    for at, tag, span in vc_scene.records(data):
        rec = data[at : at + span]
        if tag == vc_iff.MAGIC:
            tex = vc_iff._record(rec)
            if tex is not None:
                key = tex.name if tex.name not in textures.textures else f"{tex.name}_{at:x}"
                textures.textures[key] = vc_iff.decode(tex)
            continue
        if tag != vc_scene.MAGIC:
            continue
        meshes = vc_scene.meshes(rec)
        if not meshes:
            continue
        label = _label(rec)
        scene = Scene(name=f"{stem}_{label}" if label else f"{stem}_{at:x}")
        scene.materials.append(MaterialDef(name="material", texture=None, double_sided=True))
        for mesh in meshes:
            scene.primitives.append(
                Primitive(
                    material=0,
                    positions=np.ascontiguousarray(mesh.positions, dtype=np.float32),
                    indices=np.asarray(mesh.indices, dtype=np.uint32).reshape(-1),
                    normals=mesh.normals,
                    uvs=mesh.uvs,
                    colors=mesh.colors,
                )
            )
        scene.extras = {
            "format": "vc_scene",
            "record_offset": at,
            "confidence": [round(m.congruence, 3) for m in meshes],
        }
        scenes.append(scene)
    if textures.textures:
        textures.extras = {"textures_only": True, "format": "vc_scene"}
        scenes.append(textures)
    return scenes
