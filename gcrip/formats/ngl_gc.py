"""Treyarch NGL on the GameCube - Ultimate Spider-Man and Spider-Man 2.

Read with Ultimate Spider-Man's ``symbolgc-final.map`` (26,808 symbols) against its DOL:
``resource_manager::load_amalgapak``, ``resource_directory::un_mash_start`` and the
``mashable_vector`` unmashers for the pack directory, ``nglLoadMeshFileInternal`` /
``nglRebaseMesh`` / ``nglRebaseSection`` for the mesh file, ``nglLoadTextureGCTv3`` for the
textures and ``nglSkinSection`` + ``FastSkinS16`` for the skinned vertices.  Spider-Man 2 is
the earlier build of the same engine: the same mesh, texture and skin data behind 28-byte
names and a shorter directory object.

``amalga_gc.pak`` - the whole game in one file:

  header    versions (5 words on USM, 4 on SM2), [USM: u32], u32 delta, u32 dir offset,
            u32 dir bytes, u32 locations offset, u32 locations bytes, ...
  entry     USM 80 bytes: u32 id, u32 type, u32 offset, u32 size, u32, u32, u32, u32, u32
            index, u32 1, u32, u32, char name[32]
            SM2 56 bytes: char name[28], u32 type, u32 offset, u32 size, u32, u32, u32 index,
            u32 1
  a pack sits at ``delta + offset``.

Pack (a ``resource_pack_header`` and a mashed ``resource_directory``):

  header    versions, u32 0, u32 dir offset (0x30), u32 data base, u32 part-1 end, u32 part-2
            bytes; the data of both parts follows contiguously from ``data base``
  mash      u32 id, u32 flags, u32 bytes, u16 0xffff, u16 0, then the object: mashable_vectors
            {u32 ptr, u16 count, u8 flags, u8}: parents, resources, one per tlresource type,
            [USM: pack groups, allocation pools]; the vector contents follow the object in
            order, each aligned to 8 (parents 4 bytes; USM resource 16: hash, type, offset,
            size; SM2 resource 40: name[28], type, offset, size; USM tlresource 12: hash,
            size << 8 | type, offset; SM2 tlresource 40: hash, name[28], size << 8 | type,
            offset).  tlresource types: 1 texture, 2 mesh file, 3 mesh, 6 material file,
            7 material.

Mesh file ``GCNM`` (version 0x1f on USM, 0x1d on SM2), all offsets from the file start:

  header    "GCNM", u32 version, u32 entries, u32 directory offset, u32 base (0)
  entry     u8 kind (1 material, 2 mesh, 3 morph), u24 bytes, u32 object, u32 name
  name      u32 hash, char[28]                               (tlFixedString)
  material  u32 name, u32 shader name, u32, u32, u32 kind, ... pointers to texture names
            (the diffuse first) at kind-dependent offsets - any word that lands on a
            tlFixedString whose hash is a texture
  mesh      u32 name, u32 flags, u32 sections, u32 section table {u32, u32 section},
            u32 bones, u32 bone matrices (4x4 f32 bind pose, row vectors), u32 lods,
            u32 lod table, f32[4] centre, f32 radius
  section   f32 radius, f32[4] centre, u32 vertices, u32 triangles, u32, u32, u32 draw block,
            u32 skin block, u32, u32 vertex def, u32 material name, ...
  draw      u32, u32 VAT A, B, C (format 0), u32 VAT A, B, C (format 1), u16 extra display
            lists, u16 attributes, u32, u32 attribute table {u8 GX attribute, u8, u16 stride,
            u32 array}, u32 rebase table {u32 count, u32 records (slot << 24 | base index)},
            u32 display-list offsets, u32 display-list sizes, u32 VCD pairs {u32 lo, u32 hi} - one
            per display list, which is how a list past 256 array entries goes index16
  skin      u16 descriptors, u16, u32 descriptor table; 32-byte descriptors: u16 kind,
            u16 vertices, u32 source, u32 weights, u32 program, u32 GQR (frac bits in
            bits 24-29), ...  kind 6 = s16 position + s16 normal records (12 bytes) skinned
            on the CPU by a program of u16 opcodes: 1 A,B <- bones, 2 A <- bone, 3 B <- bone,
            4 n vertices by A, 5 n by B, 6 n blended (weights u8 pair), 7/8/9 n added to an
            earlier vertex (u8 pair, u16 target), 0xa end, 0xb/0xc/0xd/0xf cache traffic

A texture resource is a ``GCNT`` or an ``.IFL`` text listing the frames of an animated
texture (``name.tga`` a line); its name hash is ``h = h * 33 + lower(c)``.

Texture ``GCNT`` version 3: u16 data offset at 8, u16 palette flag, u32 data bytes, u16 width,
u16 height, u8 GX format, u8 palette format, u8 mips; palette (16 or 256 entries) after the
tiles, or at 0x28 with its count at 0x20 when the flag is set.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture, j3d

TL_TEXTURE, TL_MESHFILE, TL_MESH, TL_MATFILE, TL_MATERIAL = 1, 2, 3, 6, 7
KIND_MATERIAL, KIND_MESH, KIND_MORPH = 1, 2, 3
GX_POS, GX_NRM, GX_CLR0, GX_CLR1, GX_TEX0 = 9, 10, 11, 12, 13
DRAW_OPS = frozenset((0x80, 0x88, 0x90, 0x98, 0xA0, 0xA8, 0xB0))
MAX_ENTRIES = 1 << 16


class NglError(ValueError):
    pass


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from(">H", b, o)[0]


def _align(p: int, n: int) -> int:
    return (p + n - 1) // n * n


def name_hash(name: str) -> int:
    """tlFixedString::tlFixedString - h = h * 33 + c over the lower-cased text."""
    h = 0
    for c in name.lower().encode("latin-1", "replace"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def ifl_frames(data: bytes) -> list[str]:
    """An .IFL animated-texture list: one ``name.tga`` a line."""
    out = []
    for line in data.decode("latin-1", "replace").splitlines():
        line = line.strip()
        if line:
            out.append(line.rsplit(".", 1)[0])
    return out


def is_ifl(head: bytes) -> bool:
    text = head[:64]
    return b".tga" in text.lower() and all(32 <= c < 127 or c in (9, 10, 13) for c in text)


def _name(b: bytes, at: int) -> str:
    """A tlFixedString: u32 hash then the text."""
    return b[at + 4 : at + 32].split(b"\0")[0].decode("latin-1")


# ---------------------------------------------------------------------------
# layouts - Ultimate Spider-Man (USM) and Spider-Man 2 (SM2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    versions: int  # version words in the headers
    pak_extra: int  # words between the versions and ``delta`` in the amalgapak header
    entry: int  # amalgapak entry bytes
    entry_name: int  # offset of the name in an entry
    entry_fields: int  # offset of (type, offset, size) in an entry
    name_len: int  # 0: hashes only (USM); 28: names in the pack records (SM2)
    obj_size: int  # sizeof(resource_directory)
    vectors: int  # mashable_vectors in the object


USM = Layout(5, 1, 80, 48, 4, 0, 0x2BC, 15)
SM2 = Layout(4, 0, 56, 0, 28, 28, 0x20C, 10)
LAYOUTS = {0xE: USM, 0xB: SM2}


def layout_of(head: bytes) -> Layout | None:
    if len(head) < 16:
        return None
    return LAYOUTS.get(_u32(head, 0))


def is_amalgapak(head: bytes, size: int) -> bool:
    lay = layout_of(head)
    if lay is None or len(head) < 4 * (lay.versions + lay.pak_extra + 4):
        return False
    w = lay.versions + lay.pak_extra
    delta, diro, dirsz = struct.unpack_from(">III", head, 4 * w)
    return (
        diro == 4 * (w + 8)
        and 0 < dirsz <= lay.entry * MAX_ENTRIES
        and dirsz % lay.entry == 0
        and delta + diro + dirsz <= size
    )


@dataclass
class PakEntry:
    name: str
    kind: int
    offset: int  # absolute in the file
    size: int


def pak_entries(data: bytes) -> list[PakEntry]:
    lay = layout_of(data[:16])
    if lay is None or not is_amalgapak(data[:64], len(data)):
        raise NglError("not an amalgapak")
    w = lay.versions + lay.pak_extra
    delta, diro, dirsz = struct.unpack_from(">III", data, 4 * w)
    out = []
    for p in range(diro, diro + dirsz, lay.entry):
        name = data[p + lay.entry_name : p + lay.entry_name + (lay.name_len or 32)]
        kind, off, size = struct.unpack_from(">III", data, p + lay.entry_fields)
        if size and delta + off + size <= len(data):
            out.append(PakEntry(name.split(b"\0")[0].decode("latin-1"), kind, delta + off, size))
    return out


# ---------------------------------------------------------------------------
# a pack's resource directory
# ---------------------------------------------------------------------------


@dataclass
class Resource:
    hash: int
    name: str
    kind: int  # tlresource type
    offset: int  # from the pack start
    size: int


@dataclass
class Pack:
    layout: Layout
    data_base: int
    textures: list[Resource] = field(default_factory=list)
    mesh_files: list[Resource] = field(default_factory=list)
    material_files: list[Resource] = field(default_factory=list)


def is_pack(head: bytes) -> bool:
    lay = layout_of(head)
    if lay is None or len(head) < 4 * (lay.versions + 4):
        return False
    zero, diro, base = struct.unpack_from(">III", head, 4 * lay.versions)
    return zero == 0 and diro == 0x30 and base > diro + 16


def parse_pack(data: bytes) -> Pack:
    lay = layout_of(data[:16])
    if lay is None or not is_pack(data[:64]):
        raise NglError("not a resource pack")
    _zero, diro, base = struct.unpack_from(">III", data, 4 * lay.versions)
    m = diro
    _mid, _mflags, msize = struct.unpack_from(">III", data, m)
    obj = m + 16
    vectors = [struct.unpack_from(">IHBB", data, obj + 8 * i) for i in range(lay.vectors)]
    p = obj + lay.obj_size
    pack = Pack(lay, base)
    by_kind = {
        TL_TEXTURE: pack.textures,
        TL_MESHFILE: pack.mesh_files,
        TL_MATFILE: pack.material_files,
    }
    for i, (_ptr, count, _flags, _f2) in enumerate(vectors):
        p = _align(p, 8)
        if i == 0:
            esz = 4
        elif i == 1:
            esz = 16 if lay.name_len == 0 else lay.name_len + 12
        else:
            esz = 12 if lay.name_len == 0 else lay.name_len + 12
        if p + count * esz > min(len(data), m + msize + 16):
            raise NglError("resource directory runs past the mash")
        if i >= 2:
            for j in range(count):
                q = p + esz * j
                if lay.name_len == 0:
                    hsh, packed, off = struct.unpack_from(">III", data, q)
                    name = ""
                else:
                    hsh = _u32(data, q)
                    name = data[q + 4 : q + 4 + lay.name_len].split(b"\0")[0].decode("latin-1")
                    packed, off = struct.unpack_from(">II", data, q + 4 + lay.name_len)
                kind = packed & 0xFF
                target = by_kind.get(kind)
                if target is not None and packed >> 8:
                    target.append(Resource(hsh, name, kind, base + off, packed >> 8))
        p += count * esz
        p = _align(p, 4)
    return pack


def resource_bytes(data: bytes, r: Resource) -> bytes:
    return data[r.offset : r.offset + r.size]


# ---------------------------------------------------------------------------
# GCNT textures
# ---------------------------------------------------------------------------

GCT_MAGIC = b"GCNT"


def is_gct(head: bytes) -> bool:
    return head[:4] == GCT_MAGIC and len(head) >= 24 and _u32(head, 4) in (2, 3)


def decode_gct(data: bytes) -> np.ndarray:
    if not is_gct(data[:24]):
        raise NglError("not a GCNT texture")
    doff = _u16(data, 8)
    pal_flag = _u16(data, 0xA)
    dsize = _u32(data, 0xC)
    w, h = _u16(data, 0x10), _u16(data, 0x12)
    fmt, pal_fmt = data[0x14], data[0x15]
    palette = None
    if fmt in (8, 9, 10):
        n = {8: 16, 9: 256, 10: 1024}[fmt]
        if pal_flag:
            n = _u16(data, 0x20) or n
            pal = data[0x28 : 0x28 + 2 * n]
        else:
            pal = data[doff + dsize : doff + dsize + 2 * n]
        if len(pal) < 2 * n:
            raise NglError(f"palette of {n} entries missing")
        palette = gx_texture.decode_palette(pal_fmt if pal_fmt < 3 else 2, pal, n)
    return gx_texture.decode(fmt, w, h, data[doff : doff + dsize], palette)


# ---------------------------------------------------------------------------
# GCNM mesh files
# ---------------------------------------------------------------------------

GCNM_MAGIC = b"GCNM"
VERSIONS = (0x1D, 0x1E, 0x1F)


def is_gcnm(head: bytes, size: int) -> bool:
    if head[:4] != GCNM_MAGIC or len(head) < 20 or size < 0x40:
        return False
    ver, n, diro, base = struct.unpack_from(">4I", head, 4)
    return ver in VERSIONS and 0 < n < 4096 and diro == 0x20 and base == 0 and diro + 12 * n <= size


@dataclass
class Material:
    name: str
    shader: str
    textures: list[tuple[int, str]]  # (hash, name) in record order, the diffuse first


@dataclass
class Section:
    material: str
    positions: np.ndarray  # (N, 3) f32
    triangles: np.ndarray  # (T, 3) int64
    normals: np.ndarray | None = None
    colors: np.ndarray | None = None
    uvs: np.ndarray | None = None
    joints: np.ndarray | None = None  # (N, 4) u16
    weights: np.ndarray | None = None  # (N, 4) f32


@dataclass
class Mesh:
    name: str
    sections: list[Section]
    bones: np.ndarray | None  # (B, 4, 4) f32 bind matrices, row vectors
    center: tuple[float, float, float]
    radius: float


@dataclass
class MeshFile:
    meshes: list[Mesh]
    materials: dict[str, Material]
    warnings: list[str]


def _vat(a: int) -> dict[str, int]:
    return {
        "pos_type": (a >> 1) & 7,
        "pos_frac": (a >> 4) & 0x1F,
        "nrm_type": (a >> 10) & 7,
        "col0_type": (a >> 14) & 7,
        "col1_type": (a >> 18) & 7,
        "tex0_type": (a >> 22) & 7,
        "tex0_frac": (a >> 25) & 0x1F,
    }


_INT = {0: ("u1", 1), 1: ("i1", 1), 2: (">u2", 2), 3: (">i2", 2)}


def _array(f: bytes, off: int, stride: int, n: int, kind: str, typ: int, frac: int) -> np.ndarray:
    """Decode n GX array elements of one attribute."""
    seg = f[off : off + stride * n]
    n = len(seg) // stride
    seg = seg[: n * stride]
    if kind in ("pos", "nrm"):
        if typ == 4:
            v = np.frombuffer(seg, np.uint8).reshape(n, stride)[:, :12].copy()
            return v.view(">f4").astype(np.float32)
        dt, w = _INT[typ]
        v = np.frombuffer(seg, np.uint8).reshape(n, stride)[:, : 3 * w].copy().view(dt)
        if kind == "nrm":
            frac = 6 if w == 1 else 14
        return v.astype(np.float32) / float(1 << frac)
    if kind == "col":
        raw = np.frombuffer(seg, np.uint8).reshape(n, stride)
        if typ == 0:
            return gx_texture._rgb565_to_rgba(raw[:, :2].copy().view(">u2").reshape(-1))
        if typ in (1, 2):
            return np.concatenate([raw[:, :3], np.full((n, 1), 255, np.uint8)], axis=1)
        if typ == 3:
            v = raw[:, :2].copy().view(">u2").reshape(-1).astype(np.uint16)
            return np.stack(
                [((v >> 12) & 15) * 17, ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17],
                axis=1,
            ).astype(np.uint8)
        if typ == 4:  # RGBA6
            v = raw[:, :3].astype(np.uint32)
            packed = (v[:, 0] << 16) | (v[:, 1] << 8) | v[:, 2]
            return (
                np.stack(
                    [(packed >> 18) & 63, (packed >> 12) & 63, (packed >> 6) & 63, packed & 63],
                    axis=1,
                ).astype(np.uint8)
                * 4
            )
        return raw[:, :4].copy()
    if typ == 4:
        return (
            np.frombuffer(seg, np.uint8)
            .reshape(n, stride)[:, :8]
            .copy()
            .view(">f4")
            .astype(np.float32)
        )
    dt, w = _INT[typ]
    v = np.frombuffer(seg, np.uint8).reshape(n, stride)[:, : 2 * w].copy().view(dt)
    return v.astype(np.float32) / float(1 << frac)


def _corner_dtype(vcd_lo: int, vcd_hi: int) -> np.dtype:
    fields = []
    if vcd_lo & 1:
        fields.append(("mtx", "u1"))
    for t in range(8):
        if (vcd_lo >> (1 + t)) & 1:
            fields.append((f"tmtx{t}", "u1"))
    for name, k in (
        ("pos", (vcd_lo >> 9) & 3),
        ("nrm", (vcd_lo >> 11) & 3),
        ("col0", (vcd_lo >> 13) & 3),
        ("col1", (vcd_lo >> 15) & 3),
    ):
        if k:
            fields.append((name, ">u2" if k == 3 else "u1"))
    for t in range(8):
        k = (vcd_hi >> (2 * t)) & 3
        if k:
            fields.append((f"tex{t}", ">u2" if k == 3 else "u1"))
    return np.dtype(fields)


def _display_lists(f: bytes, X: int, extra: int, slots: list[str], warn: list[str]):
    """Corners of every display list of a section (each has its own VCD pair, so its own
    index widths), indices rebased per list; every corner comes back as u4 fields."""
    dlp, dls = _u32(f, X + 0x2C), _u32(f, X + 0x30)
    rebase = _u32(f, X + 0x28)
    vcds = _u32(f, X + 0x34)
    rows, tris = [], []
    base = 0
    names: list[str] = []
    for k in range(extra + 1):
        off, size = _u32(f, dlp + 4 * k), _u32(f, dls + 4 * k)
        vdt = _corner_dtype(*struct.unpack_from(">2I", f, vcds + 8 * k))
        if k == 0:
            names = list(vdt.names)
        elif list(vdt.names) != names:
            warn.append("display list changes its attributes")
            break
        adds = {}
        if k and rebase:
            count, recs = struct.unpack_from(">II", f, rebase + 8 * (k - 1))
            for r in range(count):
                w = _u32(f, recs + 4 * r)
                if (w >> 24) < len(slots):
                    adds[slots[w >> 24]] = w & 0xFFFFFF
        p, end = off, min(off + size, len(f))
        while p + 3 <= end:
            op = f[p]
            if op == 0:
                p += 1
                continue
            if (op & 0xF8) not in DRAW_OPS:
                warn.append(f"display list opcode {op:#x}")
                break
            n = _u16(f, p + 1)
            p += 3
            if p + n * vdt.itemsize > end:
                warn.append("display list truncated")
                break
            arr = np.frombuffer(f, vdt, n, p).astype([(nm, "u4") for nm in names])
            p += n * vdt.itemsize
            for nm, add in adds.items():
                if nm in names:
                    arr[nm] += add
            t = j3d.triangulate(op & 0xF8, n)
            if len(t):
                tris.append(t + base)
            rows.append(arr)
            base += n
    if not rows:
        return None, None
    v = np.concatenate(rows)
    tri = np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)
    return v, tri


# --- CPU skinning -------------------------------------------------------------------------


def skin_program(
    f: bytes, cmds: int, weights: int, nout: int
) -> tuple[list[list[tuple[int, float]]], list[int | None], int]:
    """Run a FastSkinS16 program for its bookkeeping: per output vertex the (bone, weight)
    list and the source record it was written from; returns the records consumed too."""
    p, w, cur, slot = cmds, weights, 0, 0
    A = B = 0
    out: list[list[tuple[int, float]]] = [[] for _ in range(nout)]
    src_of: list[int | None] = [None] * nout
    while p + 2 <= len(f):
        op = _u16(f, p)
        p += 2
        if op == 0xA:
            break
        if op == 1:
            v = _u16(f, p)
            p += 2
            A, B = v >> 8, v & 0xFF
        elif op == 2:
            A = _u16(f, p) & 0xFF
            p += 2
        elif op == 3:
            B = _u16(f, p) & 0xFF
            p += 2
        elif op in (4, 5):
            n = _u16(f, p)
            p += 2
            bone = A if op == 4 else B
            for _ in range(n):
                if slot >= nout:
                    raise NglError("skin program writes past its vertices")
                out[slot].append((bone, 1.0))
                src_of[slot] = cur
                slot += 1
                cur += 1
        elif op in (6, 0xE):
            n = _u16(f, p)
            p += 2
            for _ in range(n):
                if slot >= nout:
                    raise NglError("skin program writes past its vertices")
                wv = _u16(f, w)
                w += 2
                out[slot].append((A, (wv >> 8) / 255.0))
                out[slot].append((B, (wv & 0xFF) / 255.0))
                src_of[slot] = cur
                slot += 1
                cur += 1
        elif op in (7, 8, 9):
            n = _u16(f, p)
            p += 2
            for _ in range(n):
                wv, tgt = struct.unpack_from(">HH", f, w)
                w += 4
                if tgt < nout:
                    if op != 8:
                        out[tgt].append((A, (wv >> 8) / 255.0))
                    if op != 7:
                        out[tgt].append((B, (wv & 0xFF) / 255.0))
                cur += 1
        elif op in (0xB, 0xC, 0xF):
            p += 2
        elif op == 0xD:
            pass
        else:
            raise NglError(f"skin program opcode {op:#x}")
    return out, src_of, cur


def _skinned_vertices(f: bytes, skin: int, warn: list[str]):
    """The skinned position / normal arrays and per-vertex (bone, weight) lists of a section,
    or None when its skin block holds no CPU-skinned descriptor."""
    ndesc = _u16(f, skin)
    descs = _u32(f, skin + 4)
    for i in range(ndesc):
        d = descs + 32 * i
        kind, count = _u16(f, d), _u16(f, d + 2)
        if kind != 6:
            if kind in (2, 3, 4, 5, 7):
                warn.append(f"skin kind {kind} not decoded")
            continue
        src, wts, cmds, gqr = struct.unpack_from(">4I", f, d + 4)
        frac = (gqr >> 24) & 0x3F
        bones, src_of, used = skin_program(f, cmds, wts, count)
        recs = np.frombuffer(f, ">i2", min(used, (len(f) - src) // 12) * 6, src).reshape(-1, 6)
        recs = recs.astype(np.float32)
        pos = np.zeros((count, 3), np.float32)
        nrm = np.zeros((count, 3), np.float32)
        for j, r in enumerate(src_of):
            if r is not None and r < len(recs):
                pos[j] = recs[r, :3] / float(1 << frac)
                nrm[j] = recs[r, 3:] / 16384.0
        return pos, nrm, bones
    return None


def _joint_arrays(bones: list[list[tuple[int, float]]], idx: np.ndarray):
    joints = np.zeros((len(idx), 4), np.uint16)
    weights = np.zeros((len(idx), 4), np.float32)
    for k, i in enumerate(idx):
        best = sorted(bones[i], key=lambda t: -t[1])[:4] if i < len(bones) else []
        for q, (b, w) in enumerate(best):
            joints[k, q] = b
            weights[k, q] = w
    return joints, weights


def _section(f: bytes, sp: int, warn: list[str]) -> Section | None:
    material = _name(f, _u32(f, sp + 0x34))
    X = _u32(f, sp + 0x24)
    skin = _u32(f, sp + 0x28)
    if not X or len(f) < X + 0x38:
        warn.append(f"{material}: no draw block")
        return None
    vat = _vat(_u32(f, X + 4))
    extra, nattr = _u16(f, X + 0x1C), _u16(f, X + 0x1E)
    ap = _u32(f, X + 0x24)
    attrs: dict[int, tuple[int, int]] = {}
    slots = []
    for a in range(nattr):
        w, ptr = struct.unpack_from(">II", f, ap + 8 * a)
        attrs[w >> 24] = (w & 0xFFFF, ptr)
        slots.append(
            {GX_POS: "pos", GX_NRM: "nrm", GX_CLR0: "col0", GX_CLR1: "col1"}.get(
                w >> 24, f"tex{(w >> 24) - GX_TEX0}"
            )
        )
    if GX_POS not in attrs:
        warn.append(f"{material}: no positions")
        return None
    v, tri = _display_lists(f, X, extra, slots, warn)
    if v is None or "pos" not in v.dtype.names:
        warn.append(f"{material}: empty display list")
        return None
    skinned = _skinned_vertices(f, skin, warn) if skin else None

    def take(attr: int, key: str, kind: str, typ: int, frac: int) -> np.ndarray | None:
        """The attribute's array de-indexed for the corners.  Arrays interleave (a 24-byte
        record holds position, normal, binormal and tangent), so the element count comes from
        the corners, not from the gap to the next array."""
        if key not in v.dtype.names or attr not in attrs:
            return None
        st, ptr = attrs[attr]
        idx = v[key].astype(np.int64)
        n = min(int(idx.max()) + 1, (len(f) - ptr) // st if ptr < len(f) else 0)
        if n <= 0:
            warn.append(f"{material}: {key} array past the file")
            return None
        arr = _array(f, ptr, st, n, kind, typ, frac)
        if idx.max() >= len(arr):
            warn.append(f"{material}: {key} index {idx.max()} past {len(arr)}")
            idx = np.minimum(idx, len(arr) - 1)
        return arr[idx]

    pidx = v["pos"].astype(np.int64)
    if skinned is not None:
        pos_arr, nrm_arr, bones = skinned
        if pidx.max() >= len(pos_arr):
            warn.append(f"{material}: skinned index {pidx.max()} past {len(pos_arr)}")
            pidx = np.minimum(pidx, len(pos_arr) - 1)
        positions = pos_arr[pidx]
        normals = nrm_arr[pidx]
        joints, weights = _joint_arrays(bones, pidx)
    else:
        positions = take(GX_POS, "pos", "pos", vat["pos_type"], vat["pos_frac"])
        if positions is None:
            return None
        normals = take(GX_NRM, "nrm", "nrm", vat["nrm_type"], 0)
        joints = weights = None
    colors = take(GX_CLR0, "col0", "col", vat["col0_type"], 0)
    uvs = take(GX_TEX0, "tex0", "tex", vat["tex0_type"], vat["tex0_frac"])
    # a strip's degenerate joins are dropped
    a, b, c = positions[tri[:, 0]], positions[tri[:, 1]], positions[tri[:, 2]]
    good = ~(np.all(a == b, axis=1) | np.all(b == c, axis=1) | np.all(a == c, axis=1))
    return Section(material, positions, tri[good], normals, colors, uvs, joints, weights)


def _material(f: bytes, obj: int, size: int) -> Material:
    """The record's texture references: every word past the shader that lands on a
    tlFixedString.  The diffuse comes first; sphere maps and detail layers follow."""
    name = _name(f, _u32(f, obj))
    shader = _name(f, _u32(f, obj + 4)) if _u32(f, obj + 4) else ""
    textures = []
    for k in range(6, size // 4):
        w = _u32(f, obj + 4 * k)
        if 8 <= w < len(f) - 32 and w % 4 == 0:
            s = f[w + 4 : w + 32].split(b"\0")[0]
            if s and all(32 <= c < 127 for c in s):
                textures.append((_u32(f, w), s.decode("latin-1")))
    return Material(name, shader, textures)


def parse_gcnm(f: bytes) -> MeshFile:
    if not is_gcnm(f[:20], len(f)):
        raise NglError("not a GCNM mesh file")
    _ver, n, diro, _base = struct.unpack_from(">4I", f, 4)
    out = MeshFile([], {}, [])
    for i in range(n):
        e = diro + 12 * i
        kind = f[e]
        size = _u32(f, e) & 0xFFFFFF
        obj = _u32(f, e + 4)
        if obj + 0x40 > len(f):
            out.warnings.append(f"entry {i}: object past the file")
            continue
        if kind == KIND_MATERIAL:
            m = _material(f, obj, size)
            out.materials.setdefault(m.name.lower(), m)
        elif kind == KIND_MESH:
            name = _name(f, _u32(f, obj))
            nsec = _u32(f, obj + 8)
            secs = _u32(f, obj + 0xC)
            nbones = _u32(f, obj + 0x10)
            bones_at = _u32(f, obj + 0x14)
            center = struct.unpack_from(">3f", f, obj + 0x20)
            radius = struct.unpack_from(">f", f, obj + 0x30)[0]
            bones = None
            if nbones and bones_at + 64 * nbones <= len(f):
                bones = (
                    np.frombuffer(f, ">f4", 16 * nbones, bones_at)
                    .reshape(nbones, 4, 4)
                    .astype(np.float32)
                )
            sections = []
            for s in range(min(nsec, 4096)):
                sp = _u32(f, secs + 8 * s + 4)
                if sp + 0x40 > len(f):
                    out.warnings.append(f"{name}: section {s} past the file")
                    continue
                try:
                    sec = _section(f, sp, out.warnings)
                except (struct.error, ValueError, IndexError) as ex:
                    out.warnings.append(f"{name}: section {s}: {ex}")
                    continue
                if sec is not None:
                    sections.append(sec)
            out.meshes.append(Mesh(name, sections, bones, center, radius))
    return out
