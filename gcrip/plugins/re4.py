"""Resident Evil 4 (Capcom, GameCube G4BE08): DAS/DRS/UDAS containers with their
DAT tables, and the big-endian BIN models with textures from the sibling TPL.

Stage rooms (St?/r???.das) keep their DAT inside a "YZ2" range-coded block that
is not decoded here (see gcrip.formats.re4); enemies (em/*.drs), the player
(etc/pl*.bin), items (ss/*/*.bin) and cutscene props are plain.
"""

from __future__ import annotations

import re

import numpy as np

from gcrip.formats import re4, tpl
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "re4"

_CONTAINER_EXT = (".das", ".drs", ".udas")


_ROOM_DAT = re.compile(r"^r\d{3}_\d{2}\.dat$", re.I)


def is_container(name: str, head: bytes) -> bool:
    low = name.lower()
    if low.endswith(_CONTAINER_EXT):
        return True
    if _ROOM_DAT.match(name) and len(head) >= 16:
        return 0 < int.from_bytes(head[:4], "big") < 0x10000
    return len(head) >= 0x40 and head[:4] == re4.FILLER


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if re4.is_dat(data) and not re4.das_slots(data):
        return re4.dat_entries(data, "dat")
    base = "das"
    return re4.expand_das(data, base)


_MEMBER_RE = re.compile(r"\.(das|drs|udas|dat)/", re.I)


def detect(path: str, head: bytes, size: int) -> bool:
    if not path.lower().endswith(".bin") or size < 0x40:
        return False
    # members of our containers are recorded without an offset by the manifest
    # walker, so their sniffed head is not theirs: go by the path instead
    return re4.is_bin(head, size) or bool(_MEMBER_RE.search(path))


# ---------------------------------------------------------------------------
# fetching member bytes (see detect)
# ---------------------------------------------------------------------------

_expanded: dict[str, dict[str, bytes]] = {}


def _container_bytes(src, container: str) -> bytes:
    payload = getattr(src, "_payload", None)  # gcrip.rip caches whole containers here
    if callable(payload):
        return payload(container)
    return src.get(container)


def _members(src, container: str) -> dict[str, bytes]:
    if container not in _expanded:
        if len(_expanded) >= 2:
            _expanded.pop(next(iter(_expanded)))
        data = _container_bytes(src, container)
        _expanded[container] = dict(expand(data)) if is_container(container, data[:64]) else {}
    return _expanded[container]


def fetch(path: str, src) -> bytes:
    """Bytes of `path`, resolving members of nested DAS/DRS/DAT containers by
    re-expanding the container (cheap: tables and slices)."""
    by_path = getattr(src, "by_path", None) or {}
    entry = by_path.get(path)
    container = getattr(entry, "container", None)
    if container is None:
        m = _MEMBER_RE.search(path)
        if not m:
            return src.get(path)
        container = path[: m.end() - 1]
    rel = path[len(container) + 1 :]
    members = _members(src, container)
    if rel in members:
        return members[rel]
    # nested: the first component is itself a container we expanded
    head, _, tail = rel.partition("/")
    if tail and head in members:
        inner = dict(expand(members[head]))
        if tail in inner:
            return inner[tail]
    raise re4.Re4Error(f"{rel} not found in {container}")


def _sibling_tpl(path: str, src) -> bytes | None:
    """The TPL that goes with a BIN: same stem, else the nearest TPL member in the
    same DAT table (r100_003.BIN -> r100_004.TPL)."""
    by_path = getattr(src, "by_path", None) or {}
    stem = re.sub(r"\.bin$", "", path, flags=re.I)
    cands = [c for c in (stem + ".tpl", stem + ".TPL") if c in by_path]
    m = re.search(r"^(.*)_(\d{3})\.bin$", path, flags=re.I)
    if not cands and m:
        prefix, idx = m.group(1), int(m.group(2))
        best = None
        for p in by_path:
            mm = re.match(re.escape(prefix) + r"_(\d{3})\.tpl$", p, flags=re.I)
            if mm:
                d = int(mm.group(1)) - idx
                if d > 0 and (best is None or d < best[0]):
                    best = (d, p)
        if best is not None:
            cands.append(best[1])
    for cand in cands:
        try:
            data = fetch(cand, src)
        except Exception:  # noqa: BLE001
            continue
        if data[:4] == tpl.MAGIC:
            return data
    return None


def _textures(tpl_data: bytes | None, scene: Scene) -> list[str]:
    names: list[str] = []
    if not tpl_data or tpl_data[:4] != tpl.MAGIC:
        return names
    try:
        images = tpl.parse(tpl_data)
    except Exception as ex:  # noqa: BLE001
        scene.warnings.append(f"tpl: {ex}")
        return names
    for i, img in enumerate(images):
        try:
            scene.textures[f"tex{i:02d}"] = img.decode(0)
            names.append(f"tex{i:02d}")
        except Exception as ex:  # noqa: BLE001
            scene.warnings.append(f"tpl image {i}: {ex}")
            names.append("")
    return names


def model_to_scene(m: re4.BinModel, name: str, tpl_data: bytes | None = None) -> Scene:
    scene = Scene(name=name)
    scene.warnings += m.warnings
    texnames = _textures(tpl_data, scene)
    # skeleton: bones are listed by id, parent 0xFF / self = root
    bone_index = {b.id: i for i, b in enumerate(m.bones)}
    for i, b in enumerate(m.bones):
        parent = bone_index.get(b.parent)
        if parent == i:
            parent = None
        x, y, z = b.position
        scene.joints.append(
            Joint(f"bone{b.id:02d}", parent, (x, y, -z), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        )
    skinned = len(scene.joints) > 1 and len(m.weight_maps) > 0
    pos = m.positions.copy()
    pos[:, 2] *= -1
    nrm = m.normals.copy()
    nrm[:, 2] *= -1
    uv = m.uvs.copy()
    uv[:, 1] = 1.0 - uv[:, 1]
    for mi, mat in enumerate(m.materials):
        faces = mat.faces
        if len(faces) == 0:
            continue
        corners = faces.reshape(-1, 4)
        key = corners if m.colors is not None else corners[:, [0, 1, 3]]
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        pi = np.clip(uniq[:, 0], 0, max(0, len(pos) - 1))
        ni = np.clip(uniq[:, 1], 0, max(0, len(nrm) - 1))
        ui = np.clip(uniq[:, -1], 0, max(0, len(uv) - 1))
        prim = Primitive(
            material=mi,
            positions=pos[pi] if len(pos) else np.zeros((len(uniq), 3), np.float32),
            indices=inv.reshape(-1).astype(np.uint32),
            normals=nrm[ni] if len(nrm) else None,
            uvs=uv[ui] if len(uv) else None,
        )
        if m.colors is not None and len(m.colors):
            ci = np.clip(uniq[:, 2], 0, len(m.colors) - 1)
            prim.colors = m.colors[ci].astype(np.float32) / 255.0
        if skinned and len(pos):
            wi = np.clip(m.weight_index[pi], 0, len(m.weight_maps) - 1)
            wm = m.weight_maps[wi]
            joints = np.zeros((len(uniq), 4), np.uint16)
            weights = np.zeros((len(uniq), 4), np.float32)
            for k in range(3):
                joints[:, k] = np.clip(wm[:, k], 0, max(0, len(scene.joints) - 1))
                weights[:, k] = wm[:, 4 + k]
            total = weights.sum(axis=1)
            total[total == 0] = 1
            weights /= total[:, None]
            prim.joints = joints
            prim.weights = weights
        scene.primitives.append(prim)
        tex = None
        if 0 <= mat.texture < len(texnames) and texnames[mat.texture]:
            tex = texnames[mat.texture]
        scene.materials.append(
            MaterialDef(name=f"mat{mi:02d}", texture=tex, double_sided=True)
        )
    # materials must line up with primitive indices even when a slot had no faces
    while len(scene.materials) < len(m.materials):
        scene.materials.append(MaterialDef(name=f"mat{len(scene.materials):02d}", texture=None))
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    if not re4.is_bin(data):
        data = fetch(path, src)
    m = re4.parse(data)
    if m.triangle_count == 0:
        return []
    name = re.sub(r"\.bin$", "", path.rsplit("/", 1)[-1], flags=re.I)
    return [model_to_scene(m, name, _sibling_tpl(path, src))]
