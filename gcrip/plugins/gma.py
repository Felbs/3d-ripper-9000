"""Amusement Vision GMA models (F-Zero GX, Super Monkey Ball 1 and 2) with their sibling
.tpl texture packs, plus the .lz archives F-Zero GX wraps them in.

One Scene per GMA file: every GCMF becomes a joint (rest pose identity - the models are
authored in stage space) with its meshes rigidly bound to it, so a stage exports as one
glTF whose parts keep their GCMF names. Stitching models (characters) are assembled by
baking each part's bone matrix into the vertices. Skin / effective GCMFs (character
bodies and cloth) are listed in the warnings and skipped: their geometry lives in
engine-private vertex pools that carry no display lists.
"""

from __future__ import annotations

import numpy as np

from gcrip.formats import avlz, gma, gma_tpl, tpl, u8
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "gma"

_LZ_MEMBERS = {"model.gma", "textures.tpl", "data.bin"}


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith(".gma") and gma.looks_like(head, size)


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".lz") and avlz.looks_like(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = avlz.decompress(data)
    if u8.is_u8(out[:0x20]):  # vehicle_parts/parts_all.arc.lz and friends
        return u8.expand(out)
    if gma.looks_like(out):
        inner = "model.gma"
    elif gma_tpl.looks_like(out) or out[:4] == tpl.MAGIC:
        inner = "textures.tpl"
    else:
        inner = "data.bin"
    return [(inner, out)]


def _logical_path(path: str) -> str:
    """'bg/x.gma.lz/model.gma' -> 'bg/x.gma'; plain paths unchanged."""
    head, _, member = path.rpartition("/")
    if member in _LZ_MEMBERS and head.lower().endswith(".lz"):
        return head[:-3]
    return path


def tpl_candidates(path: str) -> list[str]:
    logical = _logical_path(path)
    stem = logical[:-4] if logical.lower().endswith(".gma") else logical
    return [
        f"{stem}.tpl",
        f"{stem}.tpl.lz/textures.tpl",
        f"{stem}.TPL",
        f"{stem}.TPL.lz/textures.tpl",
    ]


def _find_tpl(path: str, by_path) -> str | None:
    cands = tpl_candidates(path)
    for c in cands:
        if c in by_path:
            return c
    lower = {c.lower() for c in cands}
    for key in by_path:
        if key.lower() in lower:
            return key
    # F-Zero GX machines: bfalcon_02.gma / bfalcon_emb.gma share bfalcon.tpl - take the
    # texture pack in the same directory whose stem is the longest prefix of the model's
    logical = _logical_path(path).lower()
    folder, _, fname = logical.rpartition("/")
    stem = fname[:-4] if fname.endswith(".gma") else fname
    best = None
    for key in by_path:
        k = key.lower()
        kf, _, kn = k.rpartition("/")
        if kf != folder:
            continue
        if kn.endswith(".tpl"):
            ks = kn[:-4]
        elif kn == "textures.tpl" and kf.endswith(".tpl.lz"):
            kf2, _, kn2 = kf.rpartition("/")
            if kf2 != folder:
                continue
            ks = kn2[:-7]
        else:
            continue
        if stem.startswith(ks) and (best is None or len(ks) > len(best[0])):
            best = (ks, key)
    return best[1] if best else None


def _read_tpl(src, path: str) -> list:
    data = src.get(path)
    if data[:4] == tpl.MAGIC:
        return list(tpl.parse(data))
    return gma_tpl.parse(data)


def _load_textures(path: str, src) -> tuple[list, list, list[str]]:
    """(sibling TPL textures, shared textures, warnings). The shared pack is F-Zero GX's
    init/race.tpl: machine and part layers flagged 0x20 index past their own TPL into it."""
    warnings: list[str] = []
    by_path = getattr(src, "by_path", {})
    textures: list = []
    tpl_path = _find_tpl(path, by_path)
    if tpl_path is None:
        warnings.append(f"no .tpl next to {_logical_path(path)}: untextured")
    else:
        try:
            textures = _read_tpl(src, tpl_path)
        except Exception as e:  # noqa: BLE001 - a broken texture pack must not lose the model
            warnings.append(f"{tpl_path}: {type(e).__name__}: {e}")
    shared: list = []
    shared_path = next((k for k in by_path if k.lower() == "init/race.tpl"), None)
    if shared_path is not None and "vehicle" in _logical_path(path).lower():
        try:
            shared = _read_tpl(src, shared_path)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{shared_path}: {type(e).__name__}: {e}")
    return textures, shared, warnings


def _assemble(g: gma.Gcmf, mesh: gma.Mesh, s: gma.Strip) -> tuple[np.ndarray, np.ndarray | None]:
    """Stitching models: move a strip's vertices from bone space into model space."""
    pos, nrm = s.positions, s.normals
    if not g.matrices or not g.attrs & gma.ATTR_STITCHING or s.pn_index is None:
        return pos, nrm
    mesh_slots = np.frombuffer(mesh.matrix_indices, np.uint8)
    default_slots = np.frombuffer(g.matrix_indices, np.uint8)
    pos = pos.copy()
    nrm = nrm.copy() if nrm is not None else None
    for slot in np.unique(s.pn_index):
        k = int(slot) - 1
        if not 0 <= k < 8:
            continue
        bone = int(mesh_slots[k])
        if bone == 0xFF:
            bone = int(default_slots[k])
        if bone == 0xFF or bone >= len(g.matrices):
            continue
        m = g.matrices[bone]
        sel = s.pn_index == slot
        pos[sel] = pos[sel] @ m[:, :3].T + m[:, 3]
        if nrm is not None:
            nrm[sel] = nrm[sel] @ m[:, :3].T
    return pos, nrm


def _primitive(g: gma.Gcmf, mesh: gma.Mesh, strips: list[gma.Strip], mat: int, joint: int):
    pos_parts, nrm_parts, uv_parts, col_parts, idx_parts = [], [], [], [], []
    base = 0
    has_nrm = all(s.normals is not None for s in strips)
    has_uv = all(0 in s.uvs for s in strips)
    has_col = all(s.colors is not None for s in strips)
    for s in strips:
        tri = gma.strip_triangles(s)
        if len(tri) == 0:
            continue
        p, n = _assemble(g, mesh, s)
        pos_parts.append(p)
        if has_nrm:
            nrm_parts.append(n)
        if has_uv:
            uv_parts.append(s.uvs[0])
        if has_col:
            col_parts.append(s.colors)
        idx_parts.append(tri + base)
        base += s.count
    if not idx_parts:
        return None
    n = base
    return Primitive(
        material=mat,
        positions=np.concatenate(pos_parts).astype(np.float32),
        indices=np.concatenate(idx_parts).reshape(-1).astype(np.uint32),
        normals=np.concatenate(nrm_parts).astype(np.float32) if has_nrm else None,
        uvs=np.concatenate(uv_parts).astype(np.float32) if has_uv else None,
        colors=np.concatenate(col_parts).astype(np.float32) if has_col else None,
        joints=np.full((n, 4), joint, np.uint16) * np.array([1, 0, 0, 0], np.uint16),
        weights=np.tile(np.array([1.0, 0.0, 0.0, 0.0], np.float32), (n, 1)),
    )


LAYER_SHARED = 0x20  # texture layer flag: index refers to the shared in-race pack


def build_scene(model: gma.Gma, name: str, textures: list, shared: list | None = None) -> Scene:
    scene = Scene(name=name)
    scene.warnings += model.warnings
    decoded: dict[str, np.ndarray | None] = {}
    skipped: list[str] = []
    extras = []
    shared = shared or []
    shared_used = 0

    def decode(key: str, tex) -> str | None:
        if key not in decoded:
            try:
                decoded[key] = tex.decode(0)
            except Exception as e:  # noqa: BLE001
                scene.warnings.append(f"{key}: decode failed: {e}")
                decoded[key] = None
            if decoded[key] is not None:
                scene.textures[key] = decoded[key]
        return key if decoded[key] is not None else None

    def texture_name(layer: gma.TexLayer) -> str | None:
        nonlocal shared_used
        i = layer.tpl_index
        if 0 <= i < len(textures) and textures[i] is not None:
            return decode(f"tex{i:03d}", textures[i])
        if layer.flags & LAYER_SHARED and 0 <= i < len(shared) and shared[i] is not None:
            shared_used += 1
            return decode(f"shared{i:03d}", shared[i])
        return None

    hidden: list[str] = []
    for g in model.models:
        if g.skinned:
            skipped.append(g.name)
            continue
        if not g.meshes:
            continue
        if "NODISP" in g.name.upper():
            # Monkey Ball stage convention: helper volumes the game never draws (fall-out
            # boxes, camera bounds) - hundreds of units across, they would swamp the stage
            hidden.append(g.name)
            continue
        joint = len(scene.joints)
        scene.joints.append(
            Joint(g.name, None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        )
        extras.append({"name": g.name, "origin": [float(v) for v in g.origin], "radius": g.radius})
        for w in g.warnings:
            scene.warnings.append(f"{g.name}: {w}")
        for mi, mesh in enumerate(g.meshes):
            strips = mesh.strips
            double = mesh.double_sided
            if mesh.strips_b:
                if strips:
                    double = True  # the same geometry drawn with the opposite cull mode
                else:
                    strips = mesh.strips_b
            if not strips:
                continue
            layer = None
            slot = mesh.tex_slots[0]
            if 0 <= slot < len(g.layers):
                layer = g.layers[slot]
            tex = texture_name(layer) if layer is not None else None
            r, gg, b, _a = mesh.color
            mat = MaterialDef(
                name=f"{g.name}.m{mi:02d}",
                texture=tex,
                base_color=(r, gg, b, mesh.alpha / 255.0),
                alpha_blend=mesh.translucent or mesh.blended or mesh.alpha < 255,
                double_sided=double,
                clamp_u=layer is not None and not (layer.repeat_u or layer.mirror_u),
                clamp_v=layer is not None and not (layer.repeat_v or layer.mirror_v),
                mirror_u=layer is not None and layer.mirror_u,
                mirror_v=layer is not None and layer.mirror_v,
                unlit=mesh.unlit,
            )
            prim = _primitive(g, mesh, strips, len(scene.materials), joint)
            if prim is None:
                continue
            scene.materials.append(mat)
            scene.primitives.append(prim)
    if shared_used:
        scene.warnings.append(f"{shared_used} layer(s) textured from the shared init/race.tpl")
    if hidden:
        scene.warnings.append(
            f"{len(hidden)} NODISP helper GCMF(s) omitted: " + ", ".join(hidden[:8])
        )
    if skipped:
        scene.warnings.append(
            f"{len(skipped)} skinned GCMF(s) skipped (no display lists): " + ", ".join(skipped[:8])
        )
    scene.extras = {"gcrip_gcmf": extras}
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    model = gma.parse(data)
    textures, shared, tex_warnings = _load_textures(path, src)
    stem = _logical_path(path).rsplit("/", 1)[-1]
    if stem.lower().endswith(".gma"):
        stem = stem[:-4]
    scene = build_scene(model, stem, textures, shared)
    scene.warnings = tex_warnings + scene.warnings
    if not scene.primitives:
        return []
    return [scene]
