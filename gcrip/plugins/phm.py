"""Point of View ``PHM`` models, the earlier ``s_model`` versions (gcrip.formats.phm) - Spawn:
Armageddon, The Scorpion King; Smashing Drive's later layout is ``gcrip.plugins.pov_model``.

The file names its own textures inline, so a model comes out with its material named after the
``TIM`` the disc ships rather than as an anonymous slot.
"""

from __future__ import annotations

import posixpath
import re

from gcrip.formats import phm
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "phm"
# the texture names sit in a short block after the bone matrices - SPAWNTPAGE02, SPAWNTEYE
_NAME_RE = re.compile(rb"[A-Z][A-Z0-9_]{3,23}")
NAME_WINDOW = 2048


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".phm") and phm.is_phm(head)


def texture_names(data: bytes) -> list[str]:
    out, seen = [], set()
    for m in _NAME_RE.finditer(data[:NAME_WINDOW]):
        n = m.group().decode("latin-1")
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    mesh = phm.mesh(data)
    if mesh is None or not len(mesh.indices):
        return []
    stem = posixpath.basename(path).rsplit(".", 1)[0] or "model"
    scene = Scene(name=stem)
    names = texture_names(data)
    scene.materials.append(MaterialDef(names[0] if names else stem, None))
    scene.primitives.append(
        Primitive(
            material=0,
            positions=mesh.positions,
            indices=mesh.indices.reshape(-1),
            normals=mesh.normals,
            uvs=mesh.uvs,
        )
    )
    scene.extras = {
        "format": "phm",
        "triangles": len(mesh.indices),
        "textures_named": names,
    }
    return [scene]
