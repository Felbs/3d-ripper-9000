"""Rayman 3: Hoodlum Havoc / Rayman Arena levels (Ubisoft OpenSpace / CPA on GameCube):
``<level>.lvl`` + ``.ptr`` memory images, placed through the super-object tree, textured from
the sibling ``<level>_lvl.tpl`` / ``_trans.tpl`` (Nintendo TPL, gcrip.formats.tpl)."""

from __future__ import annotations

import posixpath

import numpy as np

from gcrip.formats import openspace, tpl
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "openspace"


def detect(path: str, head: bytes, size: int) -> bool:
    return openspace.is_level(path, head) and size > 0x1000


def _sibling(src, path: str) -> bytes | None:
    by_path = getattr(src, "by_path", None) or {}
    low = path.lower()
    for p in by_path:
        if p.lower() == low:
            try:
                return src.get(p)
            except Exception:  # noqa: BLE001
                return None
    return None


def _find(src, basename: str) -> bytes | None:
    by_path = getattr(src, "by_path", None) or {}
    for p in by_path:
        if p.lower().rsplit("/", 1)[-1] == basename.lower():
            try:
                return src.get(p)
            except Exception:  # noqa: BLE001
                return None
    return None


def extract(data: bytes, path: str, src) -> list[Scene]:
    folder, _, base = path.rpartition("/")
    stem = base.rsplit(".", 1)[0]
    ptr = (
        _sibling(src, f"{folder}/{stem}.ptr" if folder else f"{stem}.ptr")
        if src is not None
        else None
    )
    if not ptr:
        return []
    pointers = openspace.read_ptr(ptr)
    if not pointers:
        return []
    fix = None
    for cand in (f"{folder}/fix.lvl", f"{folder.rpartition('/')[0]}/fix.lvl"):
        fix = _sibling(src, cand)
        if fix:
            break
    if fix is None:
        fix = _find(src, "fix.lvl")
    arena = False
    lv = openspace.Level(data, fix, pointers, arena=False)
    inst = openspace.instances(lv)
    if not inst:  # Rayman Arena: no i32 after the blend weights / triangles pointer
        arena = True
        lv = openspace.Level(data, fix, pointers, arena=True)
        inst = openspace.instances(lv)
    if not inst:
        return []
    infos, fids = openspace.texture_table(lv)
    dims = [(lv.u16(o + 0x1E), lv.u16(o + 0x1C)) for o in infos]
    # TPL per file id: Rayman 3 keeps level textures (2) in <level>_lvl.tpl and transit ones
    # (6) in <level>_trans.tpl; Rayman Arena puts the whole table in <level>.tpl
    tpl_for: dict[int, list] = {}
    if arena:
        blob = _find(src, f"{stem}.tpl")
        if blob:
            try:
                tpl_for[-1] = tpl.parse(blob)
            except Exception:  # noqa: BLE001
                tpl_for[-1] = []
    else:
        for fid, name in ((2, f"{stem}_lvl.tpl"), (6, f"{stem}_trans.tpl")):
            blob = _find(src, name)
            if blob:
                try:
                    tpl_for[fid] = tpl.parse(blob)
                except Exception:  # noqa: BLE001
                    continue
    lookup: dict[tuple[int, int], object] = {}  # (file id, ordinal in file) -> texture
    groups_by_file: dict[int, list[int]] = {}
    for k, fid in enumerate(fids):
        groups_by_file.setdefault(-1 if arena else fid, []).append(k)
    for fid, ks in groups_by_file.items():
        texs = tpl_for.get(fid)
        if not texs:
            continue
        idx = openspace.align_textures([dims[k] for k in ks], [(t.width, t.height) for t in texs])
        for ordinal, (k, ti) in enumerate(zip(ks, idx, strict=True)):
            if ti >= 0:
                lookup[(fids[k], ordinal)] = texs[ti]
    scene = Scene(name=posixpath.basename(path).rsplit(".", 1)[0])
    mats: dict[object, int] = {}
    groups: dict[int, list] = {}
    for it in inst:
        rot, trans = it.matrix[:3, :3], it.matrix[3, :3]
        for m in it.meshes:
            key = m.tpl if m.tpl else (m.texture or "flat")
            if key not in mats:
                tex = None
                t = lookup.get(m.tpl) if m.tpl else None
                if t is not None:
                    rgba = getattr(t, "rgba", None)
                    if rgba is None and hasattr(t, "decode"):
                        try:
                            rgba = t.decode()
                        except Exception:  # noqa: BLE001
                            rgba = None
                    if rgba is not None:
                        tex = (
                            (m.texture or f"tex{m.tpl[1]:03d}")
                            .replace("\\", "/")
                            .rsplit("/", 1)[-1]
                        )
                        scene.textures.setdefault(tex, rgba)
                alpha = bool(tex) and bool(np.any(scene.textures[tex][..., 3] < 255))
                scene.materials.append(
                    MaterialDef(
                        name=tex or str(key), texture=tex, alpha_blend=alpha, double_sided=True
                    )
                )
                mats[key] = len(scene.materials) - 1
            pos = (m.positions @ rot + trans).astype(np.float32)
            nrm = None
            if m.normals is not None:
                n = m.normals @ rot
                ln = np.linalg.norm(n, axis=1, keepdims=True)
                nrm = (n / np.where(ln > 0, ln, 1)).astype(np.float32)
            groups.setdefault(mats[key], []).append((pos, nrm, m.uvs, m.indices))
    for mi, parts in groups.items():
        base = 0
        idx = []
        for pos, _n, _u, ind in parts:
            idx.append(ind + base)
            base += len(pos)
        has_n = all(p[1] is not None for p in parts)
        has_uv = all(p[2] is not None for p in parts)
        P = np.concatenate([p[0] for p in parts])
        P = np.stack([P[:, 0], P[:, 2], -P[:, 1]], axis=1).astype(np.float32)  # Z-up -> Y-up
        N = None
        if has_n:
            N = np.concatenate([p[1] for p in parts])
            N = np.stack([N[:, 0], N[:, 2], -N[:, 1]], axis=1).astype(np.float32)
        scene.primitives.append(
            Primitive(
                material=mi,
                positions=P,
                indices=np.concatenate(idx).astype(np.uint32),
                normals=N,
                uvs=np.concatenate([p[2] for p in parts]) if has_uv else None,
            )
        )
    if not scene.primitives:
        return []
    scene.extras = {"format": "openspace-lvl", "instances": len(inst), "arena": arena}
    return [scene]
