"""Sonic Adventure DX and Sonic Adventure 2: Battle ``.rel`` modules: models, characters and
stage land tables at the addresses SA Tools documents (gcrip.formats.satools), read from
the relocated module (gcrip.formats.rel) with the big-endian Basic / chunk / Ginja parsers
(gcrip.formats.sadx) and the Ninja scene builder.  Textures: the ``texture=`` name of
an entry -> ``<name>.gvm`` on the disc (SADX) or the stage's ``landtxNN.prs`` (SA2B)."""

from __future__ import annotations

import posixpath

from gcrip import ninja_eval
from gcrip.formats import ninja
from gcrip.formats import gvr, prs, rel, sadx, satools
from ripcore.scene import Primitive, Scene

NAME = "sadx"
_TYPES = ("basicmodel", "chunkmodel", "gcmodel", "landtable", "basicattach")


def detect(path: str, head: bytes, size: int) -> bool:
    if not path.lower().endswith(".rel") or not rel.is_rel(head, size):
        return False
    return bool(satools.for_datafile(path))


def _find(src, folder: str, names: list[str]) -> bytes | None:
    by_path = getattr(src, "by_path", None) or {}
    wanted = {n.lower() for n in names}
    for p in by_path:
        pl = p.lower()
        if not pl.startswith(folder.lower() + "/"):
            continue
        rest = pl[len(folder) + 1 :]
        if rest in wanted:
            try:
                return src.get(p)
            except Exception:  # noqa: BLE001
                return None
    return None


def _textures(src, folder: str, name: str, cache: dict) -> list[gvr.Texture]:
    key = name.lower()
    if key in cache:
        return cache[key]
    out: list[gvr.Texture] = []
    if src is not None and name:
        blob = _find(src, folder, [f"{name}.gvm", f"{name}.prs/payload.bin", f"{name}.prs"])
        if blob is not None:
            if blob[:4] != b"GVMH" and not blob[:4].isalnum():
                try:
                    blob = prs.decompress(blob)
                except Exception:  # noqa: BLE001
                    blob = b""
            if blob[:4] == b"GVMH":
                out = gvr.gvm_textures(blob)
    cache[key] = out
    return out


def _bind(scene: Scene, textures: list[gvr.Texture]) -> None:
    rgba = {t.name.lower(): t.rgba for t in textures if t.rgba is not None}
    for m in scene.materials:
        if not m.texture:
            continue
        img = rgba.get(m.texture.lower())
        if img is not None:
            scene.textures.setdefault(m.texture, img)
        else:
            m.texture = None


def _merge(scenes: list[Scene], name: str) -> Scene:
    out = Scene(name=name)
    for s in scenes:
        base = len(out.materials)
        out.materials += s.materials
        out.textures.update(s.textures)
        out.warnings += s.warnings
        for p in s.primitives:
            out.primitives.append(
                Primitive(p.material + base, p.positions, p.indices, p.normals, p.uvs, p.colors)
            )
    return out


def extract(data: bytes, path: str, src) -> list[Scene]:
    cfgs = satools.for_datafile(path)
    if not cfgs:
        return []
    folder = posixpath.dirname(path)
    stem = posixpath.basename(path).rsplit(".", 1)[0]
    scenes: list[Scene] = []
    texcache: dict = {}
    for cfg in cfgs:
        # relocate against base 0 so every pointer field becomes a plain file offset (SA
        # Tools relocates against the load key and subtracts it again when reading)
        d = bytes(rel.fix_pointers(data, 0))
        for e in cfg.entries:
            if e.type not in _TYPES or e.address <= 0 or e.address >= len(d):
                continue
            label = e.label.replace("/", "_").replace(" ", "_")
            if e.type == "landtable":
                trees, texname = sadx.landtable(d, e.address, cfg.game)
                if not trees:
                    continue
                name = texname or (
                    f"landtx{satools.stage_number(stem)}" if satools.stage_number(stem) else ""
                )
                textures = _textures(src, folder, name, texcache)
                parts = []
                for t in trees:
                    if textures:
                        t.texlist = ninja.TexList([x.name for x in textures])
                    sc = ninja_eval.evaluate(t, label)
                    if sc.primitives:
                        parts.append(sc)
                if not parts:
                    continue
                merged = _merge(parts, f"{stem}_{label}")
                _bind(merged, textures)
                merged.extras = {"format": f"{cfg.game.lower()}-landtable", "cols": len(trees)}
                scenes.append(merged)
                continue
            if e.type == "chunkmodel":
                tree = sadx.chunk_object(d, e.address)
            elif e.type == "gcmodel":
                tree = sadx.gc_object(d, e.address)
            else:
                tree = sadx.basic_object(d, e.address)
            if tree is None or tree.root is None:
                continue
            textures = _textures(src, folder, e.texture, texcache)
            if textures:
                tree.texlist = ninja.TexList([x.name for x in textures])
            sc = ninja_eval.evaluate(tree, f"{stem}_{label}")
            if not sc.primitives:
                continue
            _bind(sc, textures)
            sc.extras = {"format": f"{cfg.game.lower()}-{e.type}", "address": f"{e.address:x}"}
            scenes.append(sc)
    return scenes
