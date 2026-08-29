"""Unreal Engine 2 packages on GameCube (Ubisoft): ``.usx`` static-mesh and ``.utx`` texture
packages (Splinter Cell: Pandora Tomorrow ships them uncompressed, little-endian) through
gcrip.formats.unreal, plus the chunked-zlib ``.umd`` / ``.lin`` archives (Splinter Cell 1,
Chaos Theory, Double Agent, XIII, Rainbow Six 3) as containers whose members are the
embedded packages."""

from __future__ import annotations

import posixpath
import re
import struct
import zlib

import numpy as np

from gcrip.formats import unreal
from ripcore.scene import MaterialDef, Primitive, Scene

NAME = "unreal"
_ENTRY = re.compile(rb"([\x01-\x3f])([A-Za-z0-9_\-]{2,62}\.(?:unr|utx|usx|ukx|uax|u))\x00")


# -- containers ----------------------------------------------------------------------


def _chunked(head: bytes) -> bool:
    if len(head) < 12:
        return False
    usize, csize = struct.unpack_from(">2I", head, 0)
    return (0 < usize <= 0x40000 and 0 < csize <= 0x40000 and head[8] == 0x78) or (
        usize == 0 and 0 < csize <= 0x400000 and head[8] == 0x78
    )


def is_container(name: str, head: bytes) -> bool:
    low = name.lower()
    if low.endswith((".umd", ".lin")):
        return _chunked(head) and not unreal.is_package(head)
    return False


def _inflate(data: bytes) -> list[bytes]:
    """Every zlib segment of a chunked .umd / .lin (segments end with a (0, 0) pair)."""
    segs = []
    cur = bytearray()
    p = 0
    n = len(data)
    while p + 8 <= n:
        usize, csize = struct.unpack_from(">2I", data, p)
        if 0 < csize <= 0x400000 and p + 8 + csize <= n and data[p + 8] == 0x78:
            try:
                cur += zlib.decompress(data[p + 8 : p + 8 + csize])
                p += 8 + csize
                continue
            except zlib.error:
                pass
        if cur:
            segs.append(bytes(cur))
            cur = bytearray()
        q = data.find(b"\x00\x01\x80\x00", p + 1)
        if q < 0:
            q = data.find(b"\x78\x9c", p + 1)
            q = q - 8 if q >= 8 else -1
        if q < 0:
            break
        p = q
    if cur:
        segs.append(bytes(cur))
    return segs


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for si, seg in enumerate(_inflate(data)):
        entries = [
            (m.start(), m.group(2).decode())
            for m in _ENTRY.finditer(seg)
            if m.group(1)[0] == len(m.group(2)) + 1
        ]
        if not entries:
            m = seg.find(unreal.MAGIC)
            ml = seg.find(unreal.MAGIC_LE)
            c = [x for x in (m, ml) if x >= 0]
            if c:
                out.append((f"segment{si:02d}.unr", seg[min(c) :]))
            continue
        for (o, name), nxt in zip(entries, entries[1:] + [(len(seg), "")], strict=True):
            ent = seg[o : nxt[0]]
            m = ent.find(unreal.MAGIC)
            ml = ent.find(unreal.MAGIC_LE)
            c = [x for x in (m, ml) if x >= 0]
            if c:
                out.append((name, ent[min(c) :]))
    return out


# -- packages ------------------------------------------------------------------------


def detect(path: str, head: bytes, size: int) -> bool:
    return path.lower().endswith((".usx", ".utx", ".unr", ".umd", ".ukx")) and unreal.is_package(
        head
    )


_cache: dict[str, dict[str, np.ndarray | None]] = {}


def _package_textures(pkg: unreal.Package, d: bytes) -> dict[str, np.ndarray | None]:
    """name -> RGBA of every Texture export (palettes resolved)."""
    palettes: dict[int, np.ndarray | None] = {}
    out: dict[str, np.ndarray | None] = {}
    for k, e in enumerate(pkg.exports):
        if e.class_name == "Palette":
            try:
                palettes[k + 1] = unreal.palette(pkg, d, e)
            except (struct.error, IndexError, ValueError):
                palettes[k + 1] = None
    for e in pkg.exports:
        if e.class_name != "Texture":
            continue
        try:
            t = unreal.texture(pkg, d, e)
        except (struct.error, IndexError, ValueError):
            t = None
        out[e.name] = unreal.texture_rgba(t, palettes.get(t.palette)) if t else None
    return out


def _sibling_textures(src, package: str) -> dict[str, np.ndarray | None]:
    """Textures of the ``<package>.utx`` found anywhere on the disc (cached per package)."""
    if src is None:
        return {}
    key = package.lower()
    if key in _cache:
        return _cache[key]
    found: dict[str, np.ndarray | None] = {}
    by_path = getattr(src, "by_path", None) or {}
    want = key + ".utx"
    for path in by_path:
        if path.lower().rsplit("/", 1)[-1] == want:
            try:
                blob = src.get(path)
                pkg = unreal.parse(blob)
                found = _package_textures(pkg, blob)
            except Exception:  # noqa: BLE001
                found = {}
            break
    _cache[key] = found
    return found


def _strip_triangles(idx: np.ndarray, first: int, count: int) -> np.ndarray:
    tris = []
    for k in range(count):
        a, b, c = idx[first + k], idx[first + k + 1], idx[first + k + 2]
        if a in (b, c) or b == c:
            continue
        tris.append((a, c, b) if k % 2 else (a, b, c))
    return np.array(tris, np.uint32).reshape(-1, 3)


def _yup(a: np.ndarray) -> np.ndarray:
    """Unreal (X forward, Y right, Z up, left-handed) -> glTF (Y up, right-handed)."""
    return np.ascontiguousarray(a[:, [0, 2, 1]], dtype=np.float32)


def _add_mesh(
    scene: Scene,
    pkg: unreal.Package,
    m: unreal.StaticMesh,
    src,
    own: dict[str, np.ndarray | None],
    mats: dict[str, int],
    xform: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> int:
    """Append the mesh's sections to ``scene`` (materials shared through ``mats``), optionally
    placed by ``xform`` = (scale, rotation matrix, translation, pre-pivot).  Returns the
    number of triangles added."""
    added = 0
    for s in m.sections:
        tris = _strip_triangles(
            m.indices, s.first_index, min(s.triangles, len(m.indices) - s.first_index - 2)
        )
        if len(tris) == 0:
            continue
        tex = None
        key = f"{id(pkg)}:{s.material}"
        if s.material < 0 and -s.material - 1 < len(pkg.imports):
            imp = pkg.imports[-s.material - 1]
            package = unreal.full_name(pkg, imp.package).split(".", 1)[0]
            key = f"{package}.{imp.name}"
            if key not in mats:
                rgba = own.get(imp.name)
                if rgba is None:
                    rgba = _sibling_textures(src, package).get(imp.name)
                if rgba is not None:
                    tex = key
                    scene.textures.setdefault(tex, rgba)
        if key not in mats:
            label = tex or unreal.object_name(pkg, s.material) or f"mat{len(mats)}"
            alpha = bool(tex) and bool(np.any(scene.textures[tex][..., 3] < 255))
            scene.materials.append(
                MaterialDef(name=label, texture=tex, alpha_blend=alpha, double_sided=True)
            )
            mats[key] = len(scene.materials) - 1
        used = np.unique(tris)
        remap = np.zeros(int(used.max()) + 1, np.uint32)
        remap[used] = np.arange(len(used), dtype=np.uint32)
        pos = m.positions[used].astype(np.float64)
        nrm = m.normals[used].astype(np.float64)
        if xform is not None:
            scale, rot, loc, pivot = xform
            pos = ((pos - pivot) * scale) @ rot + loc
            nrm = nrm @ rot
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.divide(nrm, ln, out=np.zeros_like(nrm), where=ln > 0)
        scene.primitives.append(
            Primitive(
                material=mats[key],
                positions=_yup(pos),
                indices=remap[tris[:, [0, 2, 1]].reshape(-1)],
                normals=_yup(nrm),
                uvs=m.uvs[used],
            )
        )
        added += len(tris)
    return added


_pkg_cache: dict[str, tuple[unreal.Package, bytes, dict] | None] = {}


def _sibling_package(src, package: str, ext: str):
    """(Package, bytes, own textures) of ``<package><ext>`` found anywhere on the disc."""
    if src is None:
        return None
    key = package.lower() + ext
    if key in _pkg_cache:
        return _pkg_cache[key]
    found = None
    by_path = getattr(src, "by_path", None) or {}
    for path in by_path:
        if path.lower().rsplit("/", 1)[-1] == key:
            try:
                blob = src.get(path)
                pkg = unreal.parse(blob)
                own = (
                    _package_textures(pkg, blob)
                    if any(e.class_name == "Texture" for e in pkg.exports)
                    else {}
                )
                found = (pkg, blob, own)
            except Exception:  # noqa: BLE001
                found = None
            break
    _pkg_cache[key] = found
    return found


_mesh_cache: dict[str, unreal.StaticMesh | None] = {}
_SKIP_ACTORS = {"CollisionMeshActor"}


def _level(pkg: unreal.Package, data: bytes, name: str, src) -> list[Scene]:
    """Place every actor with a StaticMesh property (StaticMeshActor, Mover, lamps ...) using
    its Location / Rotation / DrawScale / DrawScale3D / PrePivot; meshes come from the
    ``<package>.usx`` siblings.  Collision meshes (CollisionMeshActor, ``Col`` groups) are
    skipped."""
    scene = Scene(name=name)
    mats: dict[str, int] = {}
    placed = missing = tris = 0
    packages: set[str] = set()
    for e in pkg.exports:
        if not e.flags & unreal.RF_HAS_STACK or e.class_name in _SKIP_ACTORS:
            continue
        try:
            props = unreal.actor_props(pkg, data, e)
        except (struct.error, IndexError, ValueError):
            continue
        ref = props.get("StaticMesh")
        if ref is None or ref[0] != 5 or not ref[2]:
            continue
        full = unreal.full_name(pkg, ref[2])
        parts = full.split(".")
        if len(parts) < 2 or "Col" in parts[1:-1] or parts[-1].upper().startswith("COL"):
            continue
        package, mesh_name = parts[0], parts[-1]
        ckey = f"{package}.{mesh_name}".lower()
        if ckey not in _mesh_cache:
            m = None
            found = _sibling_package(src, package, ".usx")
            if found is not None:
                upkg, udata, _own = found
                for ue in upkg.exports:
                    if ue.class_name == "StaticMesh" and ue.name.lower() == mesh_name.lower():
                        try:
                            m = unreal.static_mesh(upkg, udata, ue)
                        except (struct.error, IndexError, ValueError):
                            m = None
                        break
            _mesh_cache[ckey] = m if m is not None and m.sections else None
        m = _mesh_cache[ckey]
        if m is None:
            missing += 1
            continue
        upkg, _udata, own = _sibling_package(src, package, ".usx")
        o = pkg.order
        scale = np.array([props["DrawScale"][2]] * 3 if "DrawScale" in props else [1.0] * 3)
        scale = scale * unreal.vec3(props.get("DrawScale3D"), o, (1.0, 1.0, 1.0))
        rot = unreal.rotation_matrix(*unreal.rotator(props.get("Rotation"), o))
        loc = unreal.vec3(props.get("Location"), o)
        pivot = unreal.vec3(props.get("PrePivot"), o)
        tris += _add_mesh(scene, upkg, m, src, own, mats, (scale, rot, loc, pivot))
        placed += 1
        packages.add(package)
    if not scene.primitives:
        return []
    scene.extras = {
        "format": "unreal-level",
        "version": pkg.version,
        "actors": placed,
        "missing_meshes": missing,
        "triangles": tris,
        "mesh_packages": sorted(packages),
    }
    return [scene]


def extract(data: bytes, path: str, src) -> list[Scene]:
    try:
        pkg = unreal.parse(data)
    except (ValueError, struct.error, IndexError):
        return []
    name = posixpath.basename(path).rsplit(".", 1)[0]
    meshes = [e for e in pkg.exports if e.class_name == "StaticMesh"]
    if not meshes:
        if any(e.flags & unreal.RF_HAS_STACK for e in pkg.exports):
            level = _level(pkg, data, name, src)
            if level:
                return level
        texs = {k: v for k, v in _package_textures(pkg, data).items() if v is not None}
        if not texs:
            return []
        scene = Scene(name=name)
        scene.textures.update(texs)
        scene.extras = {"format": "unreal-utx", "textures_only": True, "version": pkg.version}
        return [scene]
    scenes = []
    own = (
        _package_textures(pkg, data) if any(e.class_name == "Texture" for e in pkg.exports) else {}
    )
    for e in meshes:
        try:
            m = unreal.static_mesh(pkg, data, e)
        except (struct.error, IndexError, ValueError):
            m = None
        if m is None or not m.sections:
            continue
        scene = Scene(name=e.name if len(meshes) > 1 else name)
        _add_mesh(scene, pkg, m, src, own, {})
        if scene.primitives:
            scene.extras = {
                "format": "unreal-staticmesh",
                "version": pkg.version,
                "licensee": pkg.licensee,
            }
            scenes.append(scene)
    return scenes
