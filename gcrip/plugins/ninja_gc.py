"""Sega Ninja models in the GameCube byte order (Phantasy Star Online Episode I & II /
III ``.nj`` / ``.gj`` files and BML members): ``NJCM`` / ``GJCM`` chunk-model blocks with
little-endian block sizes and big-endian payloads, parsed with the SA2B chunk parser
(gcrip.formats.sa2b) and evaluated by dcrip's Ninja scene builder.  Textures come from the
``NJTL`` / ``GJTL`` name list matched against a sibling GVM (``name.gvm`` or the same stem)."""

from __future__ import annotations

import posixpath
import struct

from dcrip import ninja_eval
from dcrip.formats import ninja
from gcrip.formats import ginja, gvr, sa2b
from ripcore.scene import Scene

NAME = "ninja_gc"
_MODEL = (b"NJCM", b"GJCM")
_TEXLIST = (b"NJTL", b"GJTL")
_BLOCKS = _MODEL + _TEXLIST + (b"NMDM", b"POF0", b"GJMS", b"NJMS")


def detect(path: str, head: bytes, size: int) -> bool:
    if head[:4] not in _MODEL + _TEXLIST or len(head) < 16:
        return False
    # GameCube blocks: little-endian size, big-endian payload (Dreamcast files are all LE)
    lsize = struct.unpack_from("<I", head, 4)[0]
    return 8 <= lsize + 8 <= size


def _blocks(data: bytes):
    p = 0
    while p + 8 <= len(data):
        magic = data[p : p + 4]
        size = struct.unpack_from("<I", data, p + 4)[0]
        if magic not in _BLOCKS or size > len(data) - p - 8:
            break
        yield magic, data[p + 8 : p + 8 + size]
        p += 8 + size


def _texlist(payload: bytes) -> list[str]:
    """NJTL payload (big-endian): u32 pointer to the entry table, u32 count; entries u32
    name pointer, u32, u32 (pointers relative to the payload)."""
    if len(payload) < 8:
        return []
    table, count = struct.unpack_from(">2I", payload, 0)
    names = []
    for i in range(min(count, 256)):
        o = table + i * 12
        if o + 12 > len(payload):
            break
        ptr = struct.unpack_from(">I", payload, o)[0]
        if ptr >= len(payload):
            break
        end = payload.find(b"\0", ptr)
        names.append(payload[ptr : end if end >= 0 else len(payload)].decode("latin-1", "replace"))
    return names


def _sibling_gvm(src, path: str) -> list[gvr.Texture]:
    by_path = getattr(src, "by_path", None) or {}
    stem = path.rsplit(".", 1)[0]
    for cand in (path + ".gvm", stem + ".gvm", stem + ".GVM"):
        if cand in by_path:
            try:
                blob = src.get(cand)
            except Exception:  # noqa: BLE001
                continue
            if gvr.is_gvm(blob[:4]):
                return gvr.gvm_textures(blob)
    return []


def extract(data: bytes, path: str, src) -> list[Scene]:
    name = posixpath.basename(path).rsplit(".", 1)[0]
    warnings: list[str] = []
    texnames: list[str] = []
    root = None
    objects = []
    for magic, payload in _blocks(data):
        if magic in _TEXLIST:
            texnames = _texlist(payload)
        elif magic in _MODEL and root is None:
            parser = (
                ginja.GinjaParser(payload, warnings)
                if magic == b"GJCM"
                else sa2b.GcChunkParser(payload, warnings)
            )
            try:
                root = parser.object(0, None)
            except (ninja.NinjaError, struct.error, IndexError, ValueError) as e:
                warnings.append(f"model block unreadable: {e}")
                continue
            objects = parser.objects
    if root is None:
        return []
    nj = ninja.Ninja(root=root, objects=objects, kind="chunk", warnings=warnings)
    textures = _sibling_gvm(src, path) if src is not None else []
    if textures or texnames:
        nj.texlist = ninja.TexList(texnames if texnames else [t.name for t in textures])
    scene = ninja_eval.evaluate(nj, name)
    if not scene.primitives:
        return []
    rgba = {t.name.lower(): t.rgba for t in textures if t.rgba is not None}
    by_index = [t.rgba for t in textures]
    for m in scene.materials:
        if not m.texture:
            continue
        img = rgba.get(m.texture.lower())
        if img is None and texnames and m.texture in texnames:
            k = texnames.index(m.texture)
            img = by_index[k] if k < len(by_index) else None
        if img is not None:
            scene.textures.setdefault(m.texture, img)
        else:
            m.texture = None
    scene.extras = {"format": "ninja-gc", "objects": len(objects)}
    return [scene]
