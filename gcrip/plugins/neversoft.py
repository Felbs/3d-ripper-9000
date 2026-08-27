"""Neversoft engine, Tony Hawk's Underground (Activision, GameCube GTDE52):
PRE archives (pre/*.prg) expanded so their .scn/.tex/.skin/.mdl/.col/.img
members reach the manifest, and the GameCube texture files decoded to PNG.
Models are not decoded (see gcrip.formats.neversoft).
"""

from __future__ import annotations

from gcrip.formats import neversoft as nv
from ripcore.scene import MaterialDef, Scene

NAME = "neversoft"


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith((".prg", ".pre", ".prx")) and nv.is_pre(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    return nv.pre_entries(data)


def detect(path: str, head: bytes, size: int) -> bool:
    low = path.lower()
    # PRE members are recorded without an offset by the manifest walker, so
    # their sniffed head is the archive's: go by the name for those
    inside_pre = ".prg/" in low or ".pre/" in low or ".prx/" in low
    if low.endswith(".tex.ngc"):
        return size > 32 and (nv.is_tex(head) or inside_pre)
    if low.endswith(".img.ngc"):
        return size > 36 and (nv.is_img(head) or inside_pre)
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


def extract(data: bytes, path: str, src) -> list[Scene]:
    low = path.lower()
    stem = path.rsplit("/", 1)[-1].split(".", 1)[0]
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
