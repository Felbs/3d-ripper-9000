"""Resident Evil 4 (Capcom, GameCube G4BE08): DAS/DRS/UDAS containers with their
DAT tables, and the big-endian BIN models with textures from the sibling TPL.

Stage rooms (St?/r???.das) keep their DAT inside a "YZ2" range-coded block
(decoded by gcrip.formats.yz2 when the container is expanded); the room geometry
is the SMD scenarios in there - placed BIN models sharing an embedded TPL - and
comes out as one scene per SMD.  Enemies (em/*.drs), the player (etc/pl*.bin),
items (ss/*/*.bin) and cutscene props are plain BIN + TPL pairs.
"""

from __future__ import annotations

import re
import struct

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
    low = path.lower()
    if low.endswith(".smd") and size >= 0x10:
        return re4.is_smd(head, size) or bool(_MEMBER_RE.search(path))
    if not low.endswith(".bin") or size < 0x40:
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


def _diffuse(mat: re4.Material, texnames: list[str], scene: Scene) -> str | None:
    """The texture to show: params[12], or the second layer (params[14], an I4
    detail map the GX pipeline multiplies with the vertex colours) when the
    first layer is the all-black placeholder that room materials pair it with."""
    tex = None
    if 0 <= mat.texture < len(texnames) and texnames[mat.texture]:
        tex = texnames[mat.texture]
    second = mat.params[14]
    if tex and mat.params[11] & 4 and 0 <= second < len(texnames) and texnames[second]:
        img = scene.textures.get(tex)
        if img is not None and not img[..., :3].any():
            tex = texnames[second]
    return tex


def _add_model(
    scene: Scene,
    m: re4.BinModel,
    texnames: list[str],
    matrix: np.ndarray | None = None,
    prefix: str = "",
) -> None:
    """Append a BIN's primitives and materials to `scene`; `matrix` (RE4 space)
    places it, and the Z flip to glTF space happens after that."""
    skinned = len(scene.joints) > 1 and len(m.weight_maps) > 0 and matrix is None
    pos = m.positions.astype(np.float64)
    nrm = m.normals.astype(np.float64)
    if matrix is not None:
        pos = pos @ matrix[:3, :3].T + matrix[:3, 3]
        nrm = nrm @ np.linalg.inv(matrix[:3, :3]) if len(nrm) else nrm
        ln = np.linalg.norm(nrm, axis=1) if len(nrm) else nrm
        if len(nrm):
            ln[ln == 0] = 1
            nrm = nrm / ln[:, None]
    pos = pos.astype(np.float32)
    nrm = nrm.astype(np.float32)
    pos[:, 2] *= -1
    nrm[:, 2] *= -1
    uv = m.uvs.copy()
    uv[:, 1] = 1.0 - uv[:, 1]
    base = len(scene.materials)
    for mi, mat in enumerate(m.materials):
        faces = mat.faces
        tex = _diffuse(mat, texnames, scene)
        scene.materials.append(
            MaterialDef(name=f"{prefix}mat{mi:02d}", texture=tex, double_sided=True)
        )
        if len(faces) == 0:
            continue
        corners = faces.reshape(-1, 4)
        key = corners if m.colors is not None else corners[:, [0, 1, 3]]
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        pi = np.clip(uniq[:, 0], 0, max(0, len(pos) - 1))
        ni = np.clip(uniq[:, 1], 0, max(0, len(nrm) - 1))
        ui = np.clip(uniq[:, -1], 0, max(0, len(uv) - 1))
        prim = Primitive(
            material=base + mi,
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
    _add_model(scene, m, texnames)
    return scene


def smd_to_scene(smd: re4.Smd, name: str) -> Scene:
    """One scene for a scenario: every placed object baked into world space."""
    scene = Scene(name=name)
    scene.warnings += smd.warnings
    tpl_tex: dict[int, list[str]] = {}
    for ti, tpl_data in enumerate(smd.tpls):
        names = _textures(tpl_data, scene)
        for i, n in enumerate(names):
            if n:
                scene.textures[f"tpl{ti}_{n}"] = scene.textures.pop(n)
                names[i] = f"tpl{ti}_{n}"
        tpl_tex[ti] = names
    models: dict[int, re4.BinModel | None] = {}
    placed = 0
    for ei, e in enumerate(smd.entries):
        if e.shared or e.bin_id >= len(smd.bins):
            continue
        if e.bin_id not in models:
            try:
                models[e.bin_id] = re4.parse(smd.bins[e.bin_id])
            except (re4.Re4Error, ValueError, struct.error) as ex:
                scene.warnings.append(f"bin {e.bin_id}: {ex}")
                models[e.bin_id] = None
        m = models[e.bin_id]
        if m is None or m.triangle_count == 0:
            continue
        _add_model(scene, m, tpl_tex.get(e.tpl_id, []), re4.entry_matrix(e), f"obj{ei:02d}_")
        placed += 1
    scene.extras["objects"] = placed
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    if path.lower().endswith(".smd"):
        if not re4.is_smd(data):
            data = fetch(path, src)
        name = re.sub(r"\.smd$", "", path.rsplit("/", 1)[-1], flags=re.I)
        scene = smd_to_scene(re4.parse_smd(data), name)
        return [scene] if scene.primitives else []
    if not re4.is_bin(data):
        data = fetch(path, src)
    m = re4.parse(data)
    if m.triangle_count == 0:
        return []
    name = re.sub(r"\.bin$", "", path.rsplit("/", 1)[-1], flags=re.I)
    return [model_to_scene(m, name, _sibling_tpl(path, src))]
