"""Neversoft engine, Tony Hawk's Underground (Activision, GameCube GTDE52):
PRE archives (pre/*.prg) expanded so their .scn/.tex/.skin/.mdl/.col/.img
members reach the manifest, the GameCube texture files decoded to PNG, and the
static models (.scn.ngc levels, .mdl.ngc props) turned into textured scenes with
their sibling .tex.ngc matched by name checksum.  Skinned models (.skin.ngc)
keep their vertices in bone space (single-bone groups parse; the weighted block
and the .ske.ngc skeleton do not), so they are not extracted.
"""

from __future__ import annotations

import numpy as np

from gcrip.formats import neversoft as nv
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "neversoft"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith((".prg", ".pre", ".prx")) and nv.is_pre(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return nv.pre_entries(data)


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    if low.endswith(".png"):
        # Pro Skater 3's board and menu pictures come out of its .pre as GCTX, not PNG
        return head[:4] == nv.GCTX_MAGIC and nv.is_gctx(head.ljust(nv.GCTX_HEADER, bytes(1)))
    # PRE members are recorded without an offset by the manifest walker, so
    # their sniffed head is the archive's: go by the name for those
    inside_pre = ".prg/" in low or ".pre/" in low or ".prx/" in low
    if low.endswith(".tex.ngc"):
        return size > 32 and (nv.is_tex(head) or inside_pre)
    if low.endswith(".img.ngc"):
        return size > 36 and (nv.is_img(head) or inside_pre)
    if low.endswith((".mdl.ngc", ".scn.ngc")):
        return size > 0x100 and (nv.is_model(head, size) or inside_pre)
    # .skin.ngc: bone-space vertices, weighted block and skeleton undecoded
    return False


_expanded: dict[str, dict[str, bytes]] = {}


def _fetch(path: str, src) -> bytes:
    """Bytes of a PRE member via the (cached) expanded archive."""
    by_path = getattr(src, "by_path", None) or {}
    container = getattr(by_path.get(path), "container", None)
    if container is None:
        low = path.lower()
        cut = max(low.rfind(".prg/"), low.rfind(".pre/"), low.rfind(".prx/"))
        if cut < 0:
            return src.get(path)
        container = path[: cut + 4]
    if container not in _expanded:
        if len(_expanded) >= 2:
            _expanded.pop(next(iter(_expanded)))
        payload = getattr(src, "_payload", None)
        data = payload(container) if callable(payload) else src.get(container)
        _expanded[container] = dict(nv.pre_entries(data))
    rel = path[len(container) + 1 :]
    members = _expanded[container]
    if rel not in members:
        raise nv.NeversoftError(f"{rel} not found in {container}")
    return members[rel]


def _scene(name: str, textures: dict) -> Scene:
    scene = Scene(name=name)
    scene.textures = textures
    scene.materials = [MaterialDef(name=k, texture=k) for k in textures]
    scene.extras = {"textures_only": True}
    return scene


def _sibling_tex(path: str, src) -> list[nv.Texture]:
    """The .tex.ngc next to a model (same stem, same folder / PRE)."""
    stem = path.rsplit(".", 2)[0]
    for cand in (stem + ".tex.ngc", stem + ".TEX.ngc"):
        try:
            data = _fetch(cand, src)
        except Exception:  # noqa: BLE001
            continue
        if nv.is_tex(data):
            return nv.parse_tex(data)
    return []


def _skin_arrays(obj: nv.ModelObject) -> tuple[np.ndarray, np.ndarray]:
    if not obj.skin:
        return np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32)
    pos = np.concatenate([g.positions for g in obj.skin])
    nrm = np.concatenate([g.normals for g in obj.skin])
    return pos, nrm


def model_to_scene(m: nv.Model, name: str, textures: list[nv.Texture]) -> Scene:
    scene = Scene(name=name)
    scene.warnings += m.warnings
    by_crc = {t.checksum: t for t in textures}
    decoded: dict[int, str | None] = {}

    def texture(crc: int) -> str | None:
        if crc not in decoded:
            key = None
            t = by_crc.get(crc)
            if t is not None:
                img = t.decode()
                if img is not None:
                    key = f"{crc:08x}"
                    scene.textures[key] = img
            decoded[crc] = key
        return decoded[crc]

    mat_index: dict[int, int] = {}
    mats = {mm.checksum: mm for mm in m.materials}
    for obj in m.objects:
        pos, nrm = (m.positions, m.normals) if not obj.skin else _skin_arrays(obj)
        for mesh in obj.meshes:
            if mesh.material not in mat_index:
                mm = mats.get(mesh.material)
                tex = None
                for crc in mm.textures if mm else []:
                    tex = texture(crc)
                    if tex:
                        break
                mat_index[mesh.material] = len(scene.materials)
                scene.materials.append(
                    MaterialDef(name=f"{mesh.material:08x}", texture=tex, double_sided=True)
                )
            c = mesh.corners
            if "pos" not in c or not len(pos):
                continue
            keys = [k for k in ("pos", "nrm", "col0", "tex0") if k in c]
            stacked = np.stack([c[k] for k in keys], axis=1)
            uniq, inv = np.unique(stacked, axis=0, return_inverse=True)
            col = {k: uniq[:, i] for i, k in enumerate(keys)}
            prim = Primitive(
                material=mat_index[mesh.material],
                positions=pos[np.clip(col["pos"], 0, len(pos) - 1)],
                indices=inv.reshape(-1)[mesh.triangles.reshape(-1)].astype(np.uint32),
            )
            if "nrm" in col and len(nrm):
                prim.normals = nrm[np.clip(col["nrm"], 0, len(nrm) - 1)]
            if "tex0" in col and len(m.uvs):
                prim.uvs = m.uvs[np.clip(col["tex0"], 0, len(m.uvs) - 1)]
            if "col0" in col and len(m.colors):
                rgba = m.colors[np.clip(col["col0"], 0, len(m.colors) - 1)].astype(np.float32)
                rgba[:, :3] = np.clip(rgba[:, :3] * (2.0 / 255.0), 0, 1)  # 0x80 = 1.0
                rgba[:, 3] = 1.0
                prim.colors = rgba
            scene.primitives.append(prim)
    if m.skinned:
        scene.warnings.append("skinned: vertices left in bone space (skeleton not decoded)")
        scene.extras["skinned"] = True
    scene.extras["objects"] = len(m.objects)
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    low = path.lower()
    stem = path.rsplit("/", 1)[-1].split(".", 1)[0]
    if low.endswith(".png"):
        if not nv.is_gctx(data):
            data = _fetch(path, src)
        rgba = nv.gctx(data)
        return [_scene(stem, {stem[:64]: rgba})] if rgba is not None else []
    if low.endswith((".mdl.ngc", ".scn.ngc", ".skin.ngc")):
        if not nv.is_model(data):
            data = _fetch(path, src)
        m = nv.parse_model(data)
        if m.triangle_count == 0:
            return []
        scene = model_to_scene(m, stem, _sibling_tex(path, src))
        return [scene] if scene.primitives else []
    textures = {}
    if not (nv.is_img(data) if low.endswith(".img.ngc") else nv.is_tex(data)):
        data = _fetch(path, src)
    if low.endswith(".img.ngc"):
        img = nv.parse_img(data).decode()
        if img is not None:
            textures[stem] = img
    else:
        for t in nv.parse_tex(data):
            img = t.decode()
            if img is not None:
                textures[f"{t.checksum:08x}"] = img
    if not textures:
        return []
    return [_scene(f"{stem}_textures", textures)]
