"""RenderWare (Criterion RW 3.x) models on GameCube: DFF / RWS clumps and BSP worlds, textured
from TXD dictionaries. Containers: Sonic Heroes .one archives and Heavy Iron HIP/HOP packs.

Games: Sonic Heroes (models in .one archives + bare .dff/.txd), SpongeBob SquarePants: Battle
for Bikini Bottom (MODL / JSP / RWTX assets in HIP/HOP), and any other RW 3.x GameCube title
whose streams reach the walker.  Formats: gcrip/formats/rwstream.py (chunks, clump, world),
rwgc.py (GameCube native geometry + textures), hip.py, one.py.

Scene assembly: every frame becomes a joint (rest pose from the frame matrices); atomics are
baked into world space and bound rigidly to their frame, skinned atomics carry the Skin PLG's
bone weights (bone -> joint through the HAnim node ids).  A world is one static mesh under a
single joint.  Textures are looked up by name in TXDs from the same archive, its HIP/HOP twin,
the same directory, and finally any TXD on the disc (index built on first miss); a dictionary
holding a single raster is also indexed under its own file name, because Heavy Iron's assets
carry the artist's leftover raster name ("temp") while the material names the asset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import dds, hip, konami_pac, one, rwgc, tga
from gcrip.formats import rwstream as rw
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "renderware"

_TXD_HINTS = (".txd", ".rw3", ".pac")
# Some RenderWare discs ship no dictionaries at all and keep the textures as loose images
# next to the models (MLB SlugFest, Outlaw Golf): material name == image file stem.  SlugFest
# writes palettised TGAs with a ``.tgx`` extension.
_LOOSE_HINTS = (".dds", ".tga", ".tgx")


def detect(path: str, head: bytes, size: int) -> bool:
    return rw.looks_like_stream(head, size, (rw.CLUMP, rw.WORLD))


def is_container(name: str, head: bytes) -> bool:
    return hip.is_hip(head) or one.is_one(name, head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    if hip.is_hip(data[:16]):
        return hip.expand(data)
    return one.expand(data)


# ---------------------------------------------------------------------------
# texture lookup
# ---------------------------------------------------------------------------


def _archive_root(path: str) -> str | None:
    parts = path.split("/")
    for i, p in enumerate(parts[:-1]):
        if p.lower().endswith((".one", ".hip", ".hop")):
            return "/".join(parts[: i + 1])
    return None


def _is_txd_path(path: str) -> bool:
    low = path.lower()
    return low.endswith(_TXD_HINTS) or "/rwtx/" in low


class _TextureIndex:
    """Per-source cache: TXD paths, their texture names, decoded rasters (bounded)."""

    def __init__(self, src):
        self.src = src
        self.paths = [p for p in src.by_path if _is_txd_path(p)]
        self.names: dict[str, list[str]] = {}
        self.decoded: dict[str, dict[str, np.ndarray]] = {}
        self.order: list[str] = []
        self.global_index: dict[str, list[str]] | None = None
        self.loose: dict[str, str] = {}
        for p in src.by_path:
            low = p.lower()
            if low.endswith(_LOOSE_HINTS):
                self.loose.setdefault(low.rsplit("/", 1)[-1].rsplit(".", 1)[0], p)
        self.loose_cache: dict[str, np.ndarray | None] = {}

    @staticmethod
    def _key(path: str, name: str) -> str:
        """Texture key: the raster's own name, or the dictionary's file stem when it is blank
        (SpongeBob RWTX assets carry the name only in the asset table)."""
        if name:
            return name.lower()
        stem = path.rsplit("/", 1)[-1]
        for ext in _TXD_HINTS:
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
        return stem.lower()

    def _names(self, path: str) -> list[str]:
        if path not in self.names:
            try:
                blob = self.src.get(path)
                if konami_pac.is_pack(blob[:16]):
                    names = konami_pac.names(blob)
                else:
                    names = rwgc.texture_names(blob)
                keys = [self._key(path, n) for n in names]
                stem = self._key(path, "")
                if len(names) == 1 and stem not in keys:
                    keys.append(stem)  # Heavy Iron assets: the raster is often called "temp"
                self.names[path] = keys
            except Exception:  # noqa: BLE001 - one bad dictionary must not stop the lookup
                self.names[path] = []
        return self.names[path]

    def _decoded(self, path: str) -> dict[str, np.ndarray]:
        if path not in self.decoded:
            table: dict[str, np.ndarray] = {}
            try:
                blob = self.src.get(path)
                if konami_pac.is_pack(blob[:16]):
                    for kt in konami_pac.parse(blob):
                        if kt.rgba is not None:
                            table[self._key(path, kt.name)] = kt.rgba
                else:
                    rasters = rwgc.parse_txd(blob)
                    for t in rasters:
                        if t.image is not None:
                            table[self._key(path, t.name)] = t.image
                    if len(rasters) == 1 and rasters[0].image is not None:
                        table.setdefault(self._key(path, ""), rasters[0].image)
            except Exception:  # noqa: BLE001
                pass
            self.decoded[path] = table
            self.order.append(path)
            if len(self.order) > 48:
                self.decoded.pop(self.order.pop(0), None)
        return self.decoded[path]

    def _candidates(self, model_path: str) -> list[str]:
        root = _archive_root(model_path)
        out: list[str] = []
        if root is not None:
            out += [p for p in self.paths if p.startswith(root + "/")]
            low = root.lower()
            twin = None
            if low.endswith(".hip"):
                twin = root[:-4] + ".HOP"
            elif low.endswith(".hop"):
                twin = root[:-4] + ".HIP"
            if twin is not None:
                tl = twin.lower() + "/"
                out += [p for p in self.paths if p.lower().startswith(tl)]
            base = root.rsplit("/", 1)[0]
        else:
            base = model_path.rsplit("/", 1)[0]
        out += [p for p in self.paths if p.rsplit("/", 1)[0] == base and p not in out]
        return out

    def find(self, model_path: str, name: str) -> np.ndarray | None:
        key = name.lower()
        for p in self._candidates(model_path):
            if key in self._names(p):
                img = self._decoded(p).get(key)
                if img is not None:
                    return img
        if self.global_index is None:
            self.global_index = {}
            for p in self.paths:
                for n in self._names(p):
                    self.global_index.setdefault(n, []).append(p)
        for p in self.global_index.get(key, []):
            img = self._decoded(p).get(key)
            if img is not None:
                return img
        return self._loose(key)

    def _loose(self, key: str) -> np.ndarray | None:
        """A loose image file named after the texture (``.dds`` / ``.tga`` / ``.png``)."""
        if key in self.loose_cache:
            return self.loose_cache[key]
        path = self.loose.get(key)
        img = None
        if path is not None:
            try:
                blob = self.src.get(path)
                low = path.lower()
                if low.endswith(".dds"):
                    img = dds.decode(blob)
                elif low.endswith((".tga", ".tgx")):  # .tgx is a TGA under another name
                    img = tga.decode(blob)
            except Exception:  # noqa: BLE001
                img = None
        if len(self.loose_cache) > 256:
            self.loose_cache.clear()
        self.loose_cache[key] = img
        return img


_index_cache: dict[tuple[int, int], _TextureIndex] = {}


def _textures_for(src) -> _TextureIndex:
    key = (id(src), id(src.by_path))
    idx = _index_cache.get(key)
    if idx is None or idx.src is not src:
        _index_cache.clear()
        idx = _index_cache[key] = _TextureIndex(src)
    return idx


# ---------------------------------------------------------------------------
# scene assembly
# ---------------------------------------------------------------------------


def _quat(m: np.ndarray) -> tuple[float, float, float, float]:
    t = float(np.trace(m))
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    i = int(np.argmax(np.diag(m)))
    if i == 0:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if i == 1:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


def _frame_local(f: rw.Frame) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = f.rotation.T  # RW rows are the right/up/at axes
    m[:3, 3] = f.position
    return m


def _joint_from(f: rw.Frame, name: str) -> Joint:
    r = f.rotation.T.astype(np.float64)
    scale = np.linalg.norm(r, axis=0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    rn = r / scale
    if np.linalg.det(rn) < 0:
        scale = scale * np.array([1.0, 1.0, -1.0])
        rn = r / scale
    return Joint(
        name=name,
        parent=f.parent,
        translation=tuple(float(x) for x in f.position),
        rotation=_quat(rn),
        scale=tuple(float(x) for x in scale),
    )


@dataclass
class _Bucket:
    material: int
    pos: list[np.ndarray] = field(default_factory=list)
    nrm: list[np.ndarray | None] = field(default_factory=list)
    uv: list[np.ndarray | None] = field(default_factory=list)
    col: list[np.ndarray | None] = field(default_factory=list)
    joints: list[np.ndarray] = field(default_factory=list)
    weights: list[np.ndarray] = field(default_factory=list)
    tri: list[np.ndarray] = field(default_factory=list)
    count: int = 0

    def add(self, pos, tri, nrm, uv, col, joints, weights) -> None:
        self.pos.append(pos)
        self.nrm.append(nrm)
        self.uv.append(uv)
        self.col.append(col)
        self.joints.append(joints)
        self.weights.append(weights)
        self.tri.append(tri + self.count)
        self.count += len(pos)

    def primitive(self) -> Primitive:
        n = self.count

        def cat(parts, width, fill):
            if all(p is None for p in parts):
                return None
            out = []
            for p, ps in zip(parts, self.pos, strict=True):
                out.append(p if p is not None else np.full((len(ps), width), fill, np.float32))
            return np.concatenate(out).astype(np.float32)

        return Primitive(
            material=self.material,
            positions=np.concatenate(self.pos).astype(np.float32)
            if n
            else np.zeros((0, 3), np.float32),
            indices=np.concatenate(self.tri).reshape(-1).astype(np.uint32)
            if self.tri
            else np.zeros(0, np.uint32),
            normals=cat(self.nrm, 3, 0.0),
            uvs=cat(self.uv, 2, 0.0),
            colors=cat(self.col, 4, 1.0),
            joints=np.concatenate(self.joints).astype(np.uint16),
            weights=np.concatenate(self.weights).astype(np.float32),
        )


class _Builder:
    def __init__(self, scene: Scene, path: str, textures: _TextureIndex | None):
        self.scene = scene
        self.path = path
        self.textures = textures
        self.mat_index: dict[tuple, int] = {}
        self.buckets: dict[int, _Bucket] = {}
        self.missing: set[str] = set()

    def material(self, m: rw.Material) -> int:
        key = (m.texture, m.color, m.filter_addr)
        mi = self.mat_index.get(key)
        if mi is not None:
            return mi
        tex_key = None
        alpha = False
        if m.texture:
            img = None
            if m.texture in self.scene.textures:
                img = self.scene.textures[m.texture]
            elif self.textures is not None:
                img = self.textures.find(self.path, m.texture)
                if img is not None:
                    self.scene.textures[m.texture] = img
            if img is not None:
                tex_key = m.texture
                alpha = bool(img.shape[2] == 4 and img[..., 3].min() < 255)
            else:
                self.missing.add(m.texture)
        addr_u = (m.filter_addr >> 8) & 0xF
        addr_v = (m.filter_addr >> 12) & 0xF
        r, g, b, a = m.color
        md = MaterialDef(
            name=m.texture or f"material{len(self.scene.materials)}",
            texture=tex_key,
            base_color=(r / 255.0, g / 255.0, b / 255.0, a / 255.0),
            alpha_blend=alpha or a < 255,
            double_sided=True,
            clamp_u=addr_u == 3,
            clamp_v=addr_v == 3,
            mirror_u=addr_u == 2,
            mirror_v=addr_v == 2,
        )
        mi = len(self.scene.materials)
        self.scene.materials.append(md)
        self.mat_index[key] = mi
        return mi

    def bucket(self, mi: int) -> _Bucket:
        b = self.buckets.get(mi)
        if b is None:
            b = self.buckets[mi] = _Bucket(mi)
        return b

    def finish(self) -> None:
        for mi in sorted(self.buckets):
            b = self.buckets[mi]
            if b.count and len(b.tri):
                self.scene.primitives.append(b.primitive())
        if self.missing:
            names = sorted(self.missing)
            shown = ", ".join(names[:6]) + (" ..." if len(names) > 6 else "")
            self.scene.warnings.append(f"{len(names)} textures not found: {shown}")


def _pad4(idx: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n, k = idx.shape
    if k >= 4:
        order = np.argsort(-w, axis=1)[:, :4]
        idx = np.take_along_axis(idx, order, axis=1)
        w = np.take_along_axis(w, order, axis=1)
    else:
        idx = np.concatenate([idx, np.zeros((n, 4 - k), idx.dtype)], axis=1)
        w = np.concatenate([w, np.zeros((n, 4 - k), w.dtype)], axis=1)
    total = w.sum(axis=1, keepdims=True)
    w = np.where(total > 1e-6, w / np.maximum(total, 1e-6), np.array([1.0, 0, 0, 0], np.float32))
    return idx.astype(np.uint16), w.astype(np.float32)


def _add_geometry(
    b: _Builder,
    g: rw.Geometry,
    world: np.ndarray,
    frame_joint: int,
    bone_joint: list[int],
) -> None:
    rot = world[:3, :3]
    skin = g.skin
    direct = skin is not None and skin.indices is None
    nj = max(len(b.scene.joints), 1)

    def bind(vertex_index: np.ndarray, slots: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
        n = len(vertex_index)
        if skin is not None and skin.indices is not None and bone_joint:
            vi = np.minimum(vertex_index, len(skin.indices) - 1)
            bones = skin.indices[vi]
            bj = np.array(bone_joint + [frame_joint], np.int64)
            joints = bj[np.minimum(bones, len(bj) - 1)]
            return _pad4(joints, skin.weights[vi].copy())
        if direct and slots is not None and bone_joint:
            used = np.array(skin.used_bones or [0], np.int64)
            bones = used[np.minimum(slots, len(used) - 1)]
            bj = np.array(bone_joint + [frame_joint], np.int64)
            joints = bj[np.minimum(bones, len(bj) - 1)]
            j = np.zeros((n, 4), np.uint16)
            j[:, 0] = joints
        else:
            j = np.zeros((n, 4), np.uint16)
            j[:, 0] = frame_joint
        w = np.zeros((n, 4), np.float32)
        w[:, 0] = 1.0
        return np.minimum(j, nj - 1), w

    def xform(pos: np.ndarray) -> np.ndarray:
        return (pos @ rot.T + world[:3, 3]).astype(np.float32)

    def xnrm(nrm: np.ndarray | None) -> np.ndarray | None:
        if nrm is None:
            return None
        n = nrm @ rot.T
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        return (n / np.maximum(ln, 1e-8)).astype(np.float32)

    if g.is_native:
        meshes = rwgc.decode_native(g.native, direct)
        for nm in meshes:
            mat_slot = nm.mesh
            if g.binmesh is not None and nm.mesh < len(g.binmesh.meshes):
                mat_slot = g.binmesh.meshes[nm.mesh][0]
            mat = g.materials[mat_slot] if mat_slot < len(g.materials) else rw.Material()
            mi = b.material(mat)
            joints, weights = bind(nm.vertex_index, nm.matrix_slot)
            b.bucket(mi).add(
                xform(nm.positions),
                nm.triangles,
                xnrm(nm.normals),
                nm.uvs,
                nm.colors,
                joints,
                weights,
            )
        return
    if g.positions is None or g.triangles is None:
        return
    nv = len(g.positions)
    vidx = np.arange(nv)
    joints, weights = bind(vidx, None)
    pos = xform(g.positions)
    nrm = xnrm(g.normals)
    uv = g.uvs[0] if g.uvs else None
    col = g.colors.astype(np.float32) / 255.0 if g.colors is not None else None
    tri = g.triangles
    valid = (tri[:, :3] < nv).all(axis=1)
    tri = tri[valid]
    for mat_slot in np.unique(tri[:, 3]):
        mat = g.materials[mat_slot] if mat_slot < len(g.materials) else rw.Material()
        mi = b.material(mat)
        sel = tri[tri[:, 3] == mat_slot][:, :3].astype(np.int64)
        used, inv = np.unique(sel.reshape(-1), return_inverse=True)
        b.bucket(mi).add(
            pos[used],
            inv.reshape(-1, 3),
            nrm[used] if nrm is not None else None,
            uv[used] if uv is not None else None,
            col[used] if col is not None else None,
            joints[used],
            weights[used],
        )


def clump_scene(
    data: bytes, name: str, path: str = "", textures: _TextureIndex | None = None
) -> Scene:
    clump = rw.parse_clump(data)
    scene = Scene(name=name)
    scene.warnings += clump.warnings
    scene.extras = {"format": "renderware", "rw_version": f"{clump.version:#x}"}
    if not clump.frames:
        clump.frames.append(rw.Frame(np.eye(3, dtype=np.float32), np.zeros(3, np.float32), None))
    world: list[np.ndarray] = []
    id_to_frame: dict[int, int] = {}
    for i, f in enumerate(clump.frames):
        local = _frame_local(f)
        world.append(world[f.parent] @ local if f.parent is not None and f.parent < i else local)
        jname = f.name or (f"bone{f.hanim_id}" if f.hanim_id is not None else f"frame{i}")
        scene.joints.append(_joint_from(f, jname))
        if f.hanim_id is not None:
            id_to_frame.setdefault(f.hanim_id, i)
    bone_joint = [
        id_to_frame.get(bid, min(k + 1, len(clump.frames) - 1))
        for k, (bid, _idx, _fl) in enumerate(clump.bones)
    ]
    b = _Builder(scene, path, textures)
    for ai, at in enumerate(clump.atomics):
        if at.geometry >= len(clump.geometries) or at.frame >= len(clump.frames):
            scene.warnings.append(f"atomic {ai}: bad frame/geometry index")
            continue
        g = clump.geometries[at.geometry]
        scene.warnings += [f"geometry {at.geometry}: {w}" for w in g.warnings]
        if g.skin is not None and not bone_joint:
            bone_joint = list(range(1, min(g.skin.num_bones + 1, len(clump.frames))))
        try:
            _add_geometry(b, g, world[at.frame], at.frame, bone_joint)
        except (rw.RwError, ValueError) as e:
            scene.warnings.append(f"atomic {ai}: {e}")
    b.finish()
    return scene


def world_scene(
    data: bytes, name: str, path: str = "", textures: _TextureIndex | None = None
) -> Scene:
    w = rw.parse_world(data)
    scene = Scene(name=name)
    scene.warnings += w.warnings
    scene.extras = {"format": "renderware", "rw_version": f"{w.version:#x}", "world": True}
    scene.joints.append(
        Joint("world", None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    )
    b = _Builder(scene, path, textures)
    ident = np.eye(4)
    for s in w.sectors:
        g = rw.Geometry(w.flags, 0, s.num_vertices, w.materials, w.version)
        if s.native is not None:
            g.native = s.native
            if s.binmesh is not None:
                g.binmesh = rw.BinMesh(
                    s.binmesh.tristrip, [(m + s.material_base, i) for m, i in s.binmesh.meshes]
                )
        else:
            g.positions, g.normals, g.colors, g.uvs, g.triangles = (
                s.positions,
                s.normals,
                s.colors,
                s.uvs,
                s.triangles,
            )
        try:
            _add_geometry(b, g, ident, 0, [])
        except (rw.RwError, ValueError) as e:
            scene.warnings.append(f"sector: {e}")
    b.finish()
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    c = rw.top(data)
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    textures = _textures_for(src) if src is not None and hasattr(src, "by_path") else None
    if c.type == rw.CLUMP:
        scene = clump_scene(data, name, path, textures)
    elif c.type == rw.WORLD:
        scene = world_scene(data, name, path, textures)
    else:
        return []
    return [scene] if scene.primitives else []
