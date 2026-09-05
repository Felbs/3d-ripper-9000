"""Treyarch NGL "stash" archives (``.ST2``) and their GameCube mesh / texture chunks -
Kelly Slater's Pro Surfer (GKSE52).  Every asset on the disc is a stash: 209 ``.ST2``
(beaches, surfers, boards, ``FRONTEND``, ``SYSTEM``), 174 MB.

Stash layout (big-endian)::

    +00 u32 data_end        directory offset; the file is data_end + count * 64 bytes
    +04 u32 0x5AFE0004      magic
    +08 u32 count           directory entries
    +0C u32 0x40, u32 0x40
    +14 u32 a_end           section A = [0x40, a_end): meshes and textures
    +18 u32 c_off, u32 c_size   section C: more textures (beach wave sets), ANMX animations
    +20 u32 b_off, u32 b_size   section B: entity / script text
    +38 DEADF00D DEADF00D

Directory entry (64 bytes): eight words of packed name hash, ``u32 offset`` (relative to
its section), ``u32 size``, ``u8 kind`` (4 mesh, 6 texture, 5 anim, 1 text), ``u8 sub``,
then runtime pointer slots that overwrite the first twelve characters of the name, so only
``name[12:24]`` survives (``dtop.gct``, ``hadow.gcmesh``).  The chunks are self-describing,
so this module resolves an entry by looking for its tag at each section base.

``GCNT`` texture chunk: the version-3 header Ultimate Spider-Man still ships three years
later (``gcrip/formats/ngl_gc.py`` decodes it): ``GCNT, u32 3, u16 pixel_offset (0x20),
u16 0, u32 pixel_bytes, u16 w, u16 h, u8 gx_format, u8 tlut_format, ...``, pixels, then
the palette for C4 (32 bytes) / C8 (512 bytes) in the header's TLUT format (1 RGB565,
2 RGB5A3).  CMPR carries the menu plates, C8 the board and skin sets.

``GCNM`` mesh chunk, **version 0xA** - the 2002 layout, unrelated to the 0x1D-0x1F
directory-of-objects files of Spider-Man 2 / Ultimate Spider-Man beyond the tag:
``GCNM, u32 0xA, u32 1, u32 size, u32 flags, 0, 0, u32 size-16,
name[32], f32 cx cy cz 1.0 radius, 0, 0, u32 nbones, u32 bones_off, u32 nparts, u32
parts_off, 0``; ``nbones`` 4x4 f32 bind matrices (row vectors, translation in the last
row); ``nparts`` 88-byte part records ``[hdr_off, radius, cx, cy, cz, 1.0, nbones, 0,
nidx, idx_off, nslots, slots_off, hdr2_off, ?, ntris, remap_off, nverts, verts_off,
nnormals, normals_off, nslots2, slots2_off]`` (offsets relative to the chunk).  A part
header is 232 bytes with the part name at +0x10.  Slots are 12-byte ``RGBA8 colour, s16
u, s16 v, pad`` with 9 fractional bits.

Two vertex layouts, told apart by ``remap_off``:

* **rigid** (surfboards): ``nverts`` f32 xyz, ``nnormals`` s16 xyz / 16384, ``nslots2``
  slots, and an index stream of ``(position, normal, slot)`` u16 triples forming one
  triangle strip with doubled-index restarts.
* **skinned** (surfers): ``nslots`` slots, a ``u16 remap`` from slot to a 28-byte record
  ``f32 xyz, s16 normal xyz, u16 nbones, u8 bone[4], u8 weight[4]``, and a strip of single
  u16 slot indices.  Vertices are already in model space; the bind matrices only matter for
  animation.

Identity: every part's arrays tile the chunk exactly (header 232 -> [hdr2 176] -> indices
-> slots -> remap -> records | indices -> positions -> normals -> slots), the last one
ending on the chunk size; the rigid board's strip yields exactly its declared ``ntris``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import hsd, ngl_gc

MAGIC = 0x5AFE0004
MESH_VERSION = 0xA  # Ultimate Spider-Man / Spider-Man 2 GCNM are 0x1D-0x1F (ngl_gc)
HEADER = 0x40
ENTRY = 64
TAG_MESH = b"GCNM"
TAG_TEX = b"GCNT"
PART_HEADER = 0xE8
PART_HEADER2 = 0xB0
RECORD = 28
SLOT = 12
UV_SCALE = 1.0 / 512.0
NORMAL_SCALE = 1.0 / 16384.0
PALETTE_BYTES = {8: 32, 9: 512}


class StashError(ValueError):
    pass


@dataclass
class Entry:
    index: int
    offset: int
    size: int
    kind: int
    sub: int
    name: str  # what survives of it (characters 12..23)


@dataclass
class Stash:
    data_end: int
    count: int
    a_end: int
    b_off: int
    b_size: int
    c_off: int
    c_size: int
    entries: list[Entry]


def is_stash(head: bytes, size: int | None = None) -> bool:
    """Magic at +4, the DEADF00D pair, and (when the size is known) a directory of
    exactly ``count`` 64-byte entries after ``data_end``."""
    if len(head) < HEADER:
        return False
    data_end, magic, count, h0, h1 = struct.unpack_from(">5I", head, 0)
    if magic != MAGIC or h0 != HEADER or h1 != HEADER or head[0x38:0x40] != b"\xde\xad\xf0\x0d" * 2:
        return False
    return size is None or size == data_end + count * ENTRY


def parse(data: bytes) -> Stash:
    if not is_stash(data[:HEADER], len(data)):
        raise StashError("not a Treyarch stash")
    data_end, _, count, _, _, a_end, c_off, c_size, b_off, b_size = struct.unpack_from(
        ">10I", data, 0
    )
    entries = []
    for i in range(count):
        e = data_end + i * ENTRY
        off, size = struct.unpack_from(">II", data, e + 32)
        kind, sub = data[e + 40], data[e + 41]
        name = data[e + 52 : e + 64].split(b"\0")[0].decode("latin1", "replace")
        entries.append(Entry(i, off, size, kind, sub, name))
    return Stash(data_end, count, a_end, b_off, b_size, c_off, c_size, entries)


def chunks(data: bytes, stash: Stash | None = None) -> list[tuple[Entry, int, bytes]]:
    """(entry, absolute offset, tag) for every directory entry that lands on a GCNM /
    GCNT tag in one of the sections, each chunk once."""
    stash = stash or parse(data)
    bases = (HEADER, stash.c_off, stash.b_off)
    seen: set[int] = set()
    out = []
    for e in stash.entries:
        if e.kind not in (4, 6):
            continue
        for base in bases:
            p = base + e.offset
            tag = data[p : p + 4]
            if tag in (TAG_MESH, TAG_TEX) and p not in seen:
                seen.add(p)
                out.append((e, p, tag))
                break
    return out


# -- textures --------------------------------------------------------------------------


@dataclass
class Texture:
    width: int
    height: int
    fmt: int
    tlut_fmt: int
    pixel_bytes: int
    span: int  # tag .. end of palette


def texture_header(data: bytes, off: int) -> Texture:
    """The same ``GCNT`` version 3 header Ultimate Spider-Man ships (``ngl_gc``): the u16
    at +8 is the pixel offset from the tag (0x20 here), the palette follows the tiles."""
    if not ngl_gc.is_gct(data[off : off + 24]):
        raise StashError("not a GCNT chunk")
    doff, pal_flag, pixel_bytes, w, h, fmt, tlut = struct.unpack_from(">HHIHHBB", data, off + 8)
    if pal_flag:
        raise StashError("GCNT with an inline palette (not the stash layout)")
    span = doff + pixel_bytes + PALETTE_BYTES.get(fmt, 0)
    return Texture(w, h, fmt, tlut, pixel_bytes, span)


def decode_texture(data: bytes, off: int = 0) -> np.ndarray:
    t = texture_header(data, off)
    return ngl_gc.decode_gct(data[off : off + t.span])


# -- meshes ----------------------------------------------------------------------------


@dataclass
class Part:
    name: str
    positions: np.ndarray  # (N, 3) f32
    normals: np.ndarray  # (N, 3) f32
    uvs: np.ndarray  # (N, 2) f32
    colors: np.ndarray  # (N, 4) u8
    triangles: np.ndarray  # (M, 3) u32
    declared_triangles: int
    skinned: bool
    joints: np.ndarray | None = None  # (N, 4) u16
    weights: np.ndarray | None = None  # (N, 4) f32
    tiled: bool = True


@dataclass
class Mesh:
    name: str
    size: int
    bones: list[np.ndarray] = field(default_factory=list)  # 4x4, row-vector convention
    parts: list[Part] = field(default_factory=list)

    @property
    def tiled(self) -> bool:
        return all(p.tiled for p in self.parts)

    @property
    def triangles(self) -> int:
        return sum(len(p.triangles) for p in self.parts)


def _align4(n: int) -> int:
    return (n + 3) & ~3


def strip_triangles(idx: np.ndarray, key: np.ndarray | None = None) -> np.ndarray:
    """One GX-style strip with doubled-index restarts -> (M, 3) triangles, parity kept.

    *key* (same length as *idx*) is what decides degeneracy when the stream indexes
    split vertices: the restart doubles repeat a *position* whose slot (uv / colour) may
    differ, so a triangle is dropped when two corners share a key, not an index.
    """
    idx = np.asarray(idx, np.int64)
    key = idx if key is None else np.asarray(key, np.int64)
    n = len(idx)
    if n < 3:
        return np.zeros((0, 3), np.uint32)
    i = np.arange(n - 2)
    a, b, c = idx[i], idx[i + 1], idx[i + 2]
    ka, kb, kc = key[i], key[i + 1], key[i + 2]
    odd = (i & 1) == 1
    tri = np.stack([np.where(odd, b, a), np.where(odd, a, b), c], 1)
    keep = (ka != kb) & (kb != kc) & (ka != kc)
    return tri[keep].astype(np.uint32)


def _position_keys(pos: np.ndarray) -> np.ndarray:
    """An integer key per row that is equal exactly when the positions are equal."""
    _, inv = np.unique(
        np.ascontiguousarray(pos, np.float32).view(np.uint32), axis=0, return_inverse=True
    )
    return inv.reshape(-1)


def _slots(data: bytes, off: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    raw = np.frombuffer(data, np.uint8, n * SLOT, off).reshape(n, SLOT)
    colors = raw[:, :4].copy()
    uv = np.frombuffer(np.ascontiguousarray(raw[:, 4:8]).tobytes(), ">i2").reshape(n, 2)
    return colors, uv.astype(np.float32) * UV_SCALE


def _part(data: bytes, base: int, rec: tuple[int, ...], end: int) -> Part:
    (hdr, _r, _cx, _cy, _cz, _one, _nb, _z, nidx, idx_off, nslots, slots_off, hdr2, _w13, ntris,
     remap_off, nverts, verts_off, nnrm, nrm_off, nslots2, slots2_off) = rec  # fmt: skip
    name = data[base + hdr + 0x10 : base + hdr + 0x30].split(b"\0")[0].decode("latin1", "replace")
    idx = np.frombuffer(data, ">u2", nidx, base + idx_off)
    if remap_off:  # skinned
        colors, uvs = _slots(data, base + slots_off, nslots)
        remap = np.frombuffer(data, ">u2", nslots, base + remap_off).astype(np.int64)
        recs = np.frombuffer(data, np.uint8, nverts * RECORD, base + verts_off).reshape(
            nverts, RECORD
        )
        pos = np.frombuffer(np.ascontiguousarray(recs[:, :12]).tobytes(), ">f4").reshape(nverts, 3)
        nrm = np.frombuffer(np.ascontiguousarray(recs[:, 12:18]).tobytes(), ">i2").reshape(
            nverts, 3
        )
        bones = recs[:, 20:24].astype(np.uint16)
        w = recs[:, 24:28].astype(np.float32)
        wsum = w.sum(1, keepdims=True)
        w = np.where(wsum > 0, w / np.maximum(wsum, 1e-6), np.array([1, 0, 0, 0], np.float32))
        if remap.max(initial=0) >= nverts or idx.max(initial=0) >= nslots:
            raise StashError(f"part {name!r}: index out of range")
        r = remap
        # the second header is a per-bone batch table: word i = strip indices bound to
        # bone i, the batches laid out consecutively without bridging degenerates
        batches = [n for n in struct.unpack_from(">41I", data, base + hdr2) if n]
        if sum(batches) != nidx:
            batches = [nidx]
        slot_key = _position_keys(pos)[r]  # per slot; the stream indexes slots
        tris = []
        start = 0
        for n in batches:
            batch = idx[start : start + n]
            tris.append(strip_triangles(batch, slot_key[batch]))
            start += n
        tiled = (
            hdr + PART_HEADER == hdr2
            and hdr2 + PART_HEADER2 == idx_off
            and _align4(idx_off + nidx * 2) == slots_off
            and slots_off + nslots * SLOT == remap_off
            and _align4(remap_off + nslots * 2) == verts_off
            and verts_off + nverts * RECORD == end
        )
        return Part(
            name,
            pos[r].astype(np.float32),
            nrm[r].astype(np.float32) * NORMAL_SCALE,
            uvs,
            colors,
            np.concatenate(tris) if tris else np.zeros((0, 3), np.uint32),
            ntris,
            True,
            bones[r],
            w[r],
            tiled,
        )
    # rigid: (position, normal, slot) triples
    if nidx % 3:
        raise StashError(f"part {name!r}: rigid index stream not in triples")
    tri_idx = idx.reshape(-1, 3).astype(np.int64)
    pos = np.frombuffer(data, ">f4", nverts * 3, base + verts_off).reshape(nverts, 3)
    nrm = np.frombuffer(data, ">i2", nnrm * 3, base + nrm_off).reshape(nnrm, 3)
    colors, uvs = _slots(data, base + slots2_off, nslots2)
    if tri_idx[:, 0].max(initial=0) >= nverts or tri_idx[:, 1].max(initial=0) >= nnrm:
        raise StashError(f"part {name!r}: index out of range")
    if tri_idx[:, 2].max(initial=0) >= nslots2:
        raise StashError(f"part {name!r}: slot index out of range")
    keys, inv = np.unique(tri_idx, axis=0, return_inverse=True)
    tiled = (
        hdr + PART_HEADER == idx_off
        and _align4(idx_off + nidx * 2) == verts_off
        and verts_off + nverts * 12 == nrm_off
        and _align4(nrm_off + nnrm * 6) == slots2_off
        and slots2_off + nslots2 * SLOT == end
    )
    return Part(
        name,
        pos[keys[:, 0]].astype(np.float32),
        nrm[keys[:, 1]].astype(np.float32) * NORMAL_SCALE,
        uvs[keys[:, 2]],
        colors[keys[:, 2]],
        strip_triangles(inv.reshape(-1), _position_keys(pos)[tri_idx[:, 0]]),
        ntris,
        False,
        tiled=tiled,
    )


def parse_mesh(data: bytes, off: int = 0) -> Mesh:
    if not is_mesh(data[off : off + 16]):
        raise StashError("not a version-0xA GCNM chunk")
    _ver, _one, size = struct.unpack_from(">III", data, off + 4)
    name = data[off + 0x20 : off + 0x40].split(b"\0")[0].decode("latin1", "replace")
    nbones, bones_off, nparts, parts_off = struct.unpack_from(">4I", data, off + 0x5C)
    if off + size > len(data):
        raise StashError(f"GCNM {name!r} truncated")
    bones = [
        np.frombuffer(data, ">f4", 16, off + bones_off + i * 64).reshape(4, 4).astype(np.float64)
        for i in range(nbones)
    ]
    recs = [struct.unpack_from(">22I", data, off + parts_off + i * 88) for i in range(nparts)]
    parts = []
    for i, rec in enumerate(recs):
        end = recs[i + 1][0] if i + 1 < nparts else size
        parts.append(_part(data, off, rec, end))
    return Mesh(name, size, bones, parts)


# -- glTF scene ------------------------------------------------------------------------


def is_mesh(head: bytes) -> bool:
    """Kelly Slater's ``GCNM`` (version 0xA); the later Spider-Man layout is ``ngl_gc``."""
    return (
        head[:4] == TAG_MESH
        and len(head) >= 16
        and struct.unpack_from(">I", head, 4)[0] == MESH_VERSION
    )


def bone_joint(m: np.ndarray, name: str):
    """A row-vector bind matrix (translation in the last row) -> a root Joint."""
    from ripcore.scene import Joint

    a = np.asarray(m, np.float64).T  # column convention
    r = a[:3, :3]
    s = np.linalg.norm(r, axis=0)
    s = np.where(s > 1e-9, s, 1.0)
    rn = r / s
    if np.linalg.det(rn) < 0:
        s[0] = -s[0]
        rn[:, 0] = -rn[:, 0]
    q = hsd.quat_from_matrix(rn) if np.isfinite(rn).all() else (0.0, 0.0, 0.0, 1.0)
    return Joint(
        name=name,
        parent=None,
        translation=tuple(float(x) for x in a[:3, 3]),
        rotation=tuple(float(x) for x in q),
        scale=tuple(float(x) for x in s),
    )


def mesh_scene(mesh: Mesh, name: str | None = None):
    """One Scene: a primitive + material per part, a flat skeleton when the mesh is
    skinned (vertices are model-space, so the bind matrices only carry the joints)."""
    from ripcore.scene import MaterialDef, Primitive, Scene

    scene = Scene(name=name or mesh.name or "gcnm")
    skinned = any(p.skinned for p in mesh.parts) and mesh.bones
    if skinned:
        scene.joints = [bone_joint(m, f"bone_{i:02d}") for i, m in enumerate(mesh.bones)]
    for i, p in enumerate(mesh.parts):
        if not len(p.triangles):
            continue
        scene.materials.append(MaterialDef(name=p.name or f"part{i:02d}", texture=None))
        prim = Primitive(
            material=len(scene.materials) - 1,
            positions=p.positions,
            indices=p.triangles.reshape(-1).astype(np.uint32),
            normals=p.normals,
            uvs=p.uvs,
            colors=p.colors.astype(np.float32) / 255.0,
        )
        if skinned and p.joints is not None:
            prim.joints, prim.weights = p.joints, p.weights
        scene.primitives.append(prim)
        if not p.tiled:
            scene.warnings.append(f"part {p.name!r}: arrays do not tile the chunk")
    scene.extras = {
        "format": "treyarch-ngl",
        "parts": [p.name for p in mesh.parts],
        "declared_triangles": sum(p.declared_triangles for p in mesh.parts),
        "tiled": mesh.tiled,
    }
    return scene


def texture_scene(rgba: np.ndarray, name: str):
    from ripcore.scene import Scene

    scene = Scene(name=name)
    scene.textures[name] = rgba
    scene.extras = {"textures_only": True, "format": "treyarch-ngl"}
    return scene


def member_name(e: Entry, tag: bytes, tex: Texture | None = None) -> str:
    """A stable member path for the manifest: index, the surviving name, the chunk kind."""
    stem = e.name.rsplit(".", 1)[0] if e.name else ""
    stem = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in stem)
    ext = "gcmesh" if tag == TAG_MESH else "gct"
    if tex is not None and not stem:
        stem = f"{tex.width}x{tex.height}"
    return f"{e.index:03d}_{stem}.{ext}" if stem else f"{e.index:03d}.{ext}"


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Every GCNM / GCNT chunk as a member (tag through the end of its arrays)."""
    stash = parse(data)
    out = []
    for e, p, tag in chunks(data, stash):
        if tag == TAG_TEX:
            try:
                t = texture_header(data, p)
            except StashError:
                continue
            out.append((member_name(e, tag, t), data[p : p + t.span]))
        else:
            size = struct.unpack_from(">I", data, p + 12)[0]
            if 0 < size <= len(data) - p:
                out.append((member_name(e, tag), data[p : p + size]))
    return out
