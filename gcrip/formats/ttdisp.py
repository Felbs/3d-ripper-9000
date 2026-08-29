"""Traveller's Tales GameCube ``DISP`` display programs - LEGO Star Wars II and The Chronicles of
Narnia ``.csc`` scenes (big-endian NU2 chunk files with reversed tags) and ``.chg`` characters
(an offset-table wrapper around the same chunk).

Pointers inside DISP are self-relative (target = field position + value).  Header words:
``0 -> source path | 1 | 2 -> command stream | 3 | 4 draw-table count | 5 -> draw table``.
Commands are 8 bytes ``u8 opcode | u8 | u16 | u32 arg``: 0x80 material (pointer into MS00
or the .chg material table; texture index at word 62 and diffuse f32[3] at word 53 for LEGO
Star Wars II records, 60 / 51 for Narnia's), 0x83 node matrix (3x4 f32, translation in
column 3), 0x82 draw mesh, 0x84 / 0x85 / 0x87 / 0x8b / 0x8e state.  The draw table holds
``(count, A, B)`` entries: B lists command indices (stream + id * 8) and A the ``(material
index, ..)`` pair of each of those draws.
Mesh descriptor (0x60 bytes): ``u16 0 | u16 fmt | u16 vertex count |
.. | [4] normals s8[3]/64 | [5] uvs u8[2]/255 | [6] colours RGBA8 | .. | [8] display list |
[9] size | .. | [19] positions s16[3]/1024``.  fmt is a GX-style vertex descriptor: bit 14
matrix index u8, bit 0/3 position index u8/u16, bit 6/8 normal u8/u16, bit 2 colour u8, bit
1/4 uv u8/u16 - one index per enabled attribute in that order per strip row; the display
list is raw GX (0x98 strips, 0x90 lists, 0xa0 fans) padded with zeros.

Textures: ``TST0`` (or the .chg texture table) entries of 0x3c bytes ``u32 | u16 w | u16 h |
u16 GX format | u16 mips | u32 pixels`` (offset relative to its own field); CI8 palettes
(RGB5A3, 0x200 bytes) follow the pixels.  LEGO Star Wars II ``.chg`` entries carry one extra
leading word; Narnia ``.chg`` tables are lists of absolute entry offsets.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

_TAG = re.compile(rb"[A-Z0-9 ]{4}")
_OPS = (0x98, 0x90, 0xA0, 0x80)
SCALE = 1.0 / 1024.0
_GX_FORMATS = {0, 1, 2, 3, 4, 5, 6, 8, 9, 0xA, 0xE}


@dataclass
class Texture:
    width: int
    height: int
    fmt: int
    rgba: np.ndarray | None


@dataclass
class Material:
    offset: int
    texture: int
    diffuse: tuple[float, float, float]


@dataclass
class Mesh:
    material: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None
    fmt: int
    joint: int = -1


@dataclass
class Bone:
    name: str
    parent: int
    bind: np.ndarray  # 4x4, row-vector convention (translation in row 3)


@dataclass
class Model:
    meshes: list[Mesh] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    textures: list[Texture] = field(default_factory=list)
    bones: list[Bone] = field(default_factory=list)
    skipped: int = 0  # draws not attached to any bone (break-apart pieces)


def is_csc(head: bytes) -> bool:
    return head[:4] == b"02UN" and head[0x10:0x14] == b"LBTN"


def is_chg(head: bytes, size: int | None = None) -> bool:
    if len(head) < 0x30:
        return False
    total, two, ntex, textable = struct.unpack_from(">4I", head, 0)
    if size is not None and total != size:
        return False
    return two == 2 and ntex < 1024 and 0x30 <= textable < total


def chunks(d: bytes, start: int = 16) -> dict[str, tuple[int, int]]:
    out = {}
    off = start
    while off + 8 <= len(d):
        tag = d[off : off + 4][::-1]
        size = struct.unpack_from(">I", d, off + 4)[0]
        if not _TAG.fullmatch(tag) or size < 8 or off + size > len(d):
            break
        out.setdefault(tag.decode(), (off, size))
        off += size
    return out


def find_disp(d: bytes) -> tuple[int, int] | None:
    for tag in (b"PSID", b"DISP"):
        p = d.find(tag)
        while p >= 0:
            size = struct.unpack_from(">I", d, p + 4)[0]
            if 0x40 < size <= len(d) - p:
                return p, size
            p = d.find(tag, p + 4)
    return None


# -- textures ------------------------------------------------------------------------


def _entry(d: bytes, e: int) -> tuple[int, int, int, int, int] | None:
    """(w, h, fmt, mips, pixel offset) of a texture entry at e, or None."""
    for shift in (4, 8):
        if e + shift + 12 > len(d):
            continue
        w, h, fmt, mips, off = struct.unpack_from(">HHHHI", d, e + shift)
        if w and h and w <= 2048 and h <= 2048 and fmt in _GX_FORMATS and mips < 16:
            pixels = e + shift + 8 + off
            if 0 < pixels <= len(d):
                return w, h, fmt, mips, pixels
    return None


def _decode(d: bytes, w: int, h: int, fmt: int, pixels: int) -> Texture:
    try:
        size = gx_texture.encoded_size(fmt, w, h)
    except (ValueError, KeyError):
        return Texture(w, h, fmt, None)
    rgba = None
    if size and pixels + size <= len(d):
        try:
            palette = None
            if fmt in (8, 9, 0xA):
                n = 16 if fmt == 8 else 256
                if pixels + size + n * 2 <= len(d):
                    palette = gx_texture.decode_palette(
                        2, d[pixels + size : pixels + size + n * 2], n
                    )
            rgba = gx_texture.decode(fmt, w, h, d[pixels : pixels + size], palette)
        except Exception:  # noqa: BLE001
            rgba = None
    return Texture(w, h, fmt, rgba)


def textures_tst0(d: bytes, off: int, size: int) -> list[Texture]:
    count = struct.unpack_from(">I", d, off + 8)[0]
    out = []
    for k in range(min(count, 512)):
        e = off + 0xC + k * 0x3C
        ent = _entry(d, e) if e + 0x3C <= off + size else None
        if ent is None:
            out.append(Texture(0, 0, 0, None))
            continue
        w, h, fmt, _m, pixels = ent
        out.append(_decode(d, w, h, fmt, pixels))
    return out


def textures_chg(d: bytes) -> list[Texture]:
    ntex, table = struct.unpack_from(">2I", d, 8)
    out = []
    e = table
    for _ in range(min(ntex, 512)):
        ent = _entry(d, e) if e + 0x3C <= len(d) else None
        if ent is None:  # Narnia: a list of absolute entry offsets
            p = table + len(out) * 4
            v = struct.unpack_from(">I", d, p)[0]
            ent = _entry(d, v) if 0x30 < v < len(d) else None
            if ent is None:
                out.append(Texture(0, 0, 0, None))
                continue
            w, h, fmt, _m, pixels = ent
            out.append(_decode(d, w, h, fmt, pixels))
            continue
        w, h, fmt, _m, pixels = ent
        out.append(_decode(d, w, h, fmt, pixels))
        e = pixels + gx_texture.encoded_size(fmt, w, h)
        if fmt in (8, 9, 0xA):
            e += (16 if fmt == 8 else 256) * 2
    return out


# -- .chg skeleton -------------------------------------------------------------------


def chg_skeleton(d: bytes, disp: int, end: int, stream: int) -> tuple[list[Bone], dict[int, int]]:
    """LEGO Star Wars II .chg: bones (0x60-byte records: 4x4 local matrix, name pointer at
    +0x4c, parent index in the top byte of +0x50, 0xff = root) with 4x4 bind matrices, and
    the bone -> mesh descriptor map: list 1 of the header's list table holds one pointer per
    bone to a (.., .., node) triplet; the node record (0xd0 bytes inside DISP) links at +0xb0
    to a (count, A, B) entry whose B array lists command indices (stream + id * 8) of the
    bone's 0x82 draws."""
    n = len(d)
    hdr = struct.unpack_from(">20I", d, 0)
    nb, mtx, bind, lists_ptr = hdr[6], hdr[7], hdr[8], hdr[19]
    if not (0 < nb < 512) or mtx + nb * 0x60 > n or bind + nb * 0x40 > n or hdr[18] < 2:
        return [], {}
    bones = []
    for k in range(nb):
        b = mtx + k * 0x60
        name_ptr, flags = struct.unpack_from(">2I", d, b + 0x4C)
        name = f"bone{k:02d}"
        if 0 < name_ptr < n:
            z = d.find(b"\0", name_ptr)
            name = d[name_ptr : z if z >= 0 else n].decode("latin-1", "replace") or name
        parent = flags >> 24
        m = np.frombuffer(d, ">f4", 16, bind + k * 0x40).reshape(4, 4).astype(np.float32)
        if not np.isfinite(m).all():
            m = np.eye(4, dtype=np.float32)
        bones.append(Bone(name, parent if parent < k else -1, m))

    def u32(a: int) -> int:
        return struct.unpack_from(">I", d, a)[0]

    def rp(a: int) -> int | None:
        v = u32(a)
        t = (a + v) & 0xFFFFFFFF
        return t if v and disp <= t < end else None

    claimed: dict[int, int] = {}
    if lists_ptr + 8 > n:
        return bones, claimed
    l1 = u32(lists_ptr + 4)
    if not (0 < l1 < n - nb * 4):
        return bones, claimed
    for k in range(nb):
        tp = u32(l1 + k * 4)
        if not tp or tp + 12 > n:
            continue
        node = struct.unpack_from(">I", d, tp + 8)[0]
        if not (disp <= node < end - 0xD0):
            continue
        entry = rp(node + 0xB0)
        if entry is None or entry + 12 > n:
            continue
        count = u32(entry)
        ids = rp(entry + 8)
        if ids is None or count > 4096:
            continue
        for i in range(count):
            c = stream + u32(ids + i * 4) * 8
            if c + 8 <= end and d[c] == 0x82:
                desc = rp(c + 4)
                if desc is not None:
                    claimed[desc] = k
    return bones, claimed


# -- geometry ------------------------------------------------------------------------


def _material(d: bytes, m: int, rec: int, ntex: int) -> Material:
    """m = the 0x80 target (record start + 8 in .csc, + 4 in .chg).  LEGO Star Wars II
    records (0x124 / 0x130 bytes) keep the texture index at word 62 and the diffuse colour
    at words 53-55; Narnia's (0x11c / 0x120) at word 60 and 51-53; -1 = untextured."""
    if m + 64 * 4 > len(d):
        return Material(m, -1, (1.0, 1.0, 1.0))
    lsw2 = rec >= 0x124
    tex = struct.unpack_from(">i", d, m + (62 if lsw2 else 60) * 4)[0]
    if not 0 <= tex < ntex:
        tex = -1
    diffuse = (1.0, 1.0, 1.0)
    c = struct.unpack_from(">3f", d, m + (53 if lsw2 else 51) * 4)
    if all(np.isfinite(x) and 0.0 <= x <= 1.0 for x in c) and any(c):
        diffuse = tuple(float(x) for x in c)
    return Material(m, tex, diffuse)


def _record_size(d: bytes, csc: bool) -> int:
    """Material record size: from MS00 (chunk size / count) or the .chg material table."""
    if csc:
        ch = chunks(d).get("MS00")
        if ch:
            count = struct.unpack_from(">I", d, ch[0] + 8)[0]
            if count:
                return ((ch[1] - 12) // count) & ~3
        return 0x124
    nmat, table = struct.unpack_from(">2I", d, 0x10)
    if nmat > 1 and table + 8 <= len(d):
        a, b = struct.unpack_from(">2I", d, table)
        if 0 < b - a < 0x1000:
            return b - a
    return 0x130


def _mesh(d: bytes, desc: int, rp, material: int) -> Mesh | None:
    fmt, cnt = struct.unpack_from(">HH", d, desc + 2)
    dl = rp(desc + 0x20)
    dlsize = struct.unpack_from(">I", d, desc + 0x24)[0]
    ppos, pnrm, puv, pcol = (rp(desc + o) for o in (0x4C, 0x10, 0x14, 0x18))
    if not dl or not ppos or cnt == 0 or ppos + cnt * 6 > len(d):
        return None
    pos = np.frombuffer(d, ">i2", cnt * 3, ppos).reshape(cnt, 3).astype(np.float32) * SCALE
    cols = []  # (name, width)
    if fmt & 0x4000:
        cols.append(("mtx", 1))
    cols.append(("pos", 2 if fmt & 8 else 1))
    if fmt & 0x100:
        cols.append(("nrm", 2))
    elif fmt & 0x40:
        cols.append(("nrm", 1))
    if fmt & 4:
        cols.append(("col", 1))
    if fmt & 0x10:
        cols.append(("uv", 2))
    elif fmt & 2:
        cols.append(("uv", 1))
    stride = sum(w for _, w in cols)
    p, end = dl, min(dl + dlsize, len(d))
    rows_all, tris, base = [], [], 0
    while p + 3 <= end:
        op = d[p]
        if op == 0:
            p += 1
            continue
        if op & 0xF8 not in _OPS:
            break
        n = struct.unpack_from(">H", d, p + 1)[0]
        p += 3
        if n == 0 or p + n * stride > end:
            break
        rows = np.frombuffer(d, np.uint8, n * stride, p).reshape(n, stride)
        p += n * stride
        if op & 0xF8 == 0x98:
            t = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(n - 2)]
        elif op & 0xF8 == 0x90:
            t = [(k, k + 1, k + 2) for k in range(0, n - 2, 3)]
        else:
            t = [(0, k, k + 1) for k in range(1, n - 1)]
        if not t:
            continue
        rows_all.append(rows)
        tris.append(np.array(t, np.uint32).reshape(-1, 3) + base)
        base += n
    if not rows_all:
        return None
    rows = np.concatenate(rows_all).astype(np.int64)
    idx = {}
    c = 0
    for name, w in cols:
        idx[name] = (rows[:, c] << 8 | rows[:, c + 1]) if w == 2 else rows[:, c]
        c += w
    pi = idx["pos"]
    if pi.max() >= cnt:
        return None
    mesh = Mesh(material, pos[pi], np.concatenate(tris).reshape(-1), None, None, None, fmt)
    if "nrm" in idx and pnrm:
        n = int(idx["nrm"].max()) + 1
        if pnrm + n * 3 <= len(d):
            nrm = np.frombuffer(d, np.int8, n * 3, pnrm).reshape(n, 3).astype(np.float32) / 64.0
            mesh.normals = nrm[idx["nrm"]]
    if "uv" in idx and puv:
        n = int(idx["uv"].max()) + 1
        if puv + n * 2 <= len(d):
            uv = np.frombuffer(d, np.uint8, n * 2, puv).reshape(n, 2).astype(np.float32) / 255.0
            mesh.uvs = uv[idx["uv"]]
    if "col" in idx and pcol:
        n = int(idx["col"].max()) + 1
        if pcol + n * 4 <= len(d):
            col = np.frombuffer(d, np.uint8, n * 4, pcol).reshape(n, 4).astype(np.float32) / 255.0
            col = col.copy()
            col[:, 3] = 1.0
            mesh.colors = col[idx["col"]]
    return mesh


def parse(d: bytes) -> Model:
    model = Model()
    found = find_disp(d)
    if not found:
        return model
    D, size = found
    END = D + size
    n = len(d)

    def u32(a: int) -> int:
        return struct.unpack_from(">I", d, a)[0]

    def rp(a: int, anywhere: bool = False) -> int | None:
        v = u32(a)
        t = (a + v) & 0xFFFFFFFF
        if not v or t >= n:
            return None
        return t if anywhere or D <= t < END else None

    csc = is_csc(d[:0x14])
    if csc:
        ch = chunks(d)
        if "TST0" in ch:
            model.textures = textures_tst0(d, *ch["TST0"])
    elif is_chg(d[:0x30], n):
        model.textures = textures_chg(d)
    rec = _record_size(d, csc)
    stream = rp(D + 16)
    if stream is None:
        return model
    claimed: dict[int, int] = {}
    if is_chg(d[:0x30], n):
        try:
            model.bones, claimed = chg_skeleton(d, D, END, stream)
        except (struct.error, IndexError, ValueError):
            model.bones, claimed = [], {}
        if not claimed:
            model.bones = []
    mat_index: dict[int, int] = {}
    # draw table: (count, A -> (material, x) pairs, B -> command indices) entries
    draw_material: dict[int, int] = {}
    n_entries = u32(D + 8 + 16)
    table = rp(D + 8 + 20)
    if table is not None and n_entries < 4096:
        for e in range(n_entries):
            ent = table + e * 12
            if ent + 12 > n:
                break
            count, pa, pb = u32(ent), rp(ent + 4), rp(ent + 8)
            if pa is None or pb is None or count > 4096:
                continue
            for i in range(count):
                if pa + i * 8 + 8 > n or pb + i * 4 + 4 > n:
                    break
                draw_material[u32(pb + i * 4)] = u32(pa + i * 8)
    current = -1
    matrix = np.eye(4, dtype=np.float32)
    p = stream
    while p + 8 <= END:
        op = d[p]
        if op < 0x80 or op > 0x8F:
            break
        if op == 0x80:
            t = rp(p + 4, anywhere=True)
            if t is not None:
                if t not in mat_index:
                    mat_index[t] = len(model.materials)
                    model.materials.append(_material(d, t, rec, len(model.textures)))
                current = mat_index[t]
        elif op == 0x83:
            t = rp(p + 4)
            if t is not None and t + 64 <= n:
                m = np.frombuffer(d, ">f4", 16, t).reshape(4, 4).astype(np.float32)
                if np.isfinite(m).all():
                    matrix = m
        elif op == 0x82:
            t = rp(p + 4)
            if t is not None and t + 0x60 <= n:
                if claimed and t not in claimed:
                    model.skipped += 1
                    p += 8
                    continue
                mat = draw_material.get((p - stream) // 8, current)
                if not 0 <= mat < len(model.materials):
                    mat = current
                mesh = _mesh(d, t, rp, mat)
                if mesh is not None:
                    if t in claimed:  # bone space -> model space through the bind matrix
                        mesh.joint = claimed[t]
                        bm = model.bones[mesh.joint].bind
                        rot, trans = bm[:3, :3].T, bm[3, :3]
                    else:
                        rot, trans = matrix[:3, :3], matrix[:3, 3]
                    mesh.positions = (mesh.positions @ rot.T + trans).astype(np.float32)
                    if mesh.normals is not None:
                        nr = mesh.normals @ rot.T
                        ln = np.linalg.norm(nr, axis=1, keepdims=True)
                        mesh.normals = (nr / np.where(ln > 0, ln, 1)).astype(np.float32)
                    model.meshes.append(mesh)
        p += 8
    return model
