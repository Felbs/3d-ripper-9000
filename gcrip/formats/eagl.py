"""EA Canada EAGL objects on GameCube (FIFA 2003-06, FIFA Street, NBA Live, NHL, MVP,
Def Jam, Fight Night, SSX, GoldenEye RA, Medal of Honor ...): models, skeletons and
animation banks stored as ELF relocatable objects.

A model is split in two archive members: ``<name>.ord`` (the ELF header + ``.data``) and
``<name>.orp`` (a u32 with the ``.ord`` size, then the rest of the ELF: string / symbol /
relocation tables).  The ELF header and tables are little-endian (the tool chain tags the
machine as MIPS), the ``.data`` payload is big-endian GameCube data, and every pointer
inside ``.data`` is a little-endian u32 fixed up by a ``.rel.data`` entry (type 2 against
symbol 1 = the section itself, or against an external such as a shader or a texture).

Symbols name everything: ``__Model:::<name>``, ``__Bone:::<model>.<bone>``,
``__Skeleton:::<model>``, ``__EAGL::TAR:::...SHAPENAME=n,m...`` (texture references),
``__EAGL::GeoPrimState:::...`` (render state) and the undefined externs
``LitTextureEnvIrrad2x_Skin`` / ``Gouraud_Skin`` / ... (shaders).

Geometry lives in *render packets*, one per (mesh part, shader).  After the shader pointer
a packet lists ``(count, pointer)`` pairs: a matrix palette (10 entries of the animation
buffer), the runtime model-view matrix slot, then the vertex attribute streams (all with
the same count = vertex count; the first is positions as s16 xyz, the last is UVs as s16
pairs) and finally the GX display list (count = byte size).  Display-list vertices are
``[posmtx u8][texmtx u8][u16 index per attribute stream]`` - the two matrix bytes are the
skinning slots (multiples of 3 = GX position-matrix indices).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

import numpy as np

ELF_MAGIC = b"\x7fELF"
PRIM_OPS = (0x80, 0x90, 0x98, 0xA0)
POS_SCALE = 1.0 / 256.0
UV_SCALE = 1.0 / 256.0
_SHAPENAME = re.compile(r"SHAPENAME=([A-Za-z0-9_]+),(\d+)")


class EaglError(ValueError):
    pass


@dataclass
class Packet:
    shader: str
    stride: int
    positions: np.ndarray  # (N,3) f32 (scaled)
    indices: np.ndarray  # (M,) u32 triangles
    uvs: np.ndarray | None
    normals: np.ndarray | None
    joints: np.ndarray | None  # (N,4) u16 bone record indices (skinned packets)
    weights: np.ndarray | None  # (N,4) f32
    textures: list[str]  # SHAPENAME shape ids (4-char names) referenced, in order


@dataclass
class Model:
    name: str
    packets: list[Packet] = field(default_factory=list)
    variations: list[str] = field(default_factory=list)


@dataclass
class Bone:
    name: str
    parent: int | None
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]  # quaternion x y z w
    scale: tuple[float, float, float]
    inverse_bind: np.ndarray  # (4,4) f32, row-vector convention (translation in row 3)


@dataclass
class EaglObject:
    models: list[Model]
    bones: list[str]
    warnings: list[str] = field(default_factory=list)
    skeleton: list[Bone] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ELF plumbing
# ---------------------------------------------------------------------------


def is_ord(head: bytes) -> bool:
    """A little-endian relocatable ELF whose e_machine is 8 (EA's tool chain tag)."""
    return (
        len(head) >= 0x34
        and head[:4] == ELF_MAGIC
        and head[5] == 1
        and struct.unpack_from("<HH", head, 0x10) == (1, 8)
    )


def _table_fits(data: bytes) -> bool:
    """Whether the ELF's own section table lands inside ``data``.

    This is the arithmetic that says a join is right: ``e_shoff + e_shnum * e_shentsize`` has to
    be within the joined bytes, and on a correct pair it equals their combined length exactly.
    """
    if len(data) < 0x34 or data[:4] != ELF_MAGIC:
        return False
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize, e_shnum = struct.unpack_from("<HH", data, 0x2E)
    return e_shoff + e_shnum * e_shentsize <= len(data)


def _table_reads(data: bytes) -> bool:
    """Whether the ELF's section table is not merely inside the file but actually *readable*.

    `_table_fits` is arithmetic only, and it passes on a wrong join: append the tail to a 27 KB
    `.ord` whose header declares a 12 KB extent and the table "fits" while pointing at zeros.
    That is how FIFA 2003's 933 player objects parsed to nothing without a single warning.  So a
    candidate join is accepted only when the section names resolve.
    """
    if not _table_fits(data):
        return False
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    if e_shnum == 0 or e_shstrndx >= e_shnum or e_shentsize < 40:
        return False
    try:
        entries = [
            struct.unpack_from("<10I", data, e_shoff + i * e_shentsize) for i in range(e_shnum)
        ]
    except struct.error:
        return False
    str_off, str_size = entries[e_shstrndx][4], entries[e_shstrndx][5]
    if str_size == 0 or str_off + str_size > len(data):
        return False
    named = 0
    for ent in entries:
        at = ent[0]
        if at >= str_size:
            continue
        end = data.find(b"\0", str_off + at, str_off + str_size)
        name = data[str_off + at : end if end >= 0 else str_off + str_size]
        if name and all(32 <= c < 127 for c in name):
            named += 1
    return named >= max(1, e_shnum // 2)


def join(ord_data: bytes, tail: bytes | None) -> bytes:
    """Reassemble the ELF from its two members.

    The tail comes in **two forms**, and which one a disc uses decides whether its models are
    readable at all:

    * ``.orp`` - a ``u32`` holding the ``.ord`` size, then the rest of the ELF.
    * ``.orl`` - **the same remainder with no size prefix**, used by MVP Baseball 2004/2005,
      NHL 2003/2004, FIFA Street 1/2, Def Jam Fight For NY and Fight Night Round 2.  Reading
      only ``.orp`` left every one of those discs raising "section table outside the file" on
      every model - 9,732 of them, and several of the discs reported zero triangles.

    The prefix is detected rather than assumed: a leading word equal to the ``.ord`` length is
    one, anything else is not.  Either way the result is accepted only if the ELF's section
    table then fits, so a wrong pairing fails here instead of parsing to nothing.
    """
    if tail is None or len(tail) < 4:
        return ord_data
    declared = struct.unpack_from(">I", tail, 0)[0]
    declared_le = struct.unpack_from("<I", tail, 0)[0]  # some titles store it LE
    # The leading word is an OFFSET, not a length.  Where it equals the .ord's size an overlay
    # there is the same thing as appending, which is why reading it as a length worked for
    # years; on FIFA 2003 it is 7,840 against a 27,232-byte .ord and the tail belongs *inside*.
    body = tail[4:]
    for at in (declared, declared_le):
        if not 0 < at <= len(ord_data):
            continue
        blob = bytearray(ord_data)
        end = at + len(body)
        if end > len(blob):
            blob.extend(bytes(end - len(blob)))
        blob[at:end] = body
        candidate = bytes(blob)
        if _table_reads(candidate):
            return candidate
    joined = ord_data + (body if len(ord_data) in (declared, declared_le) else tail)
    if not _table_fits(joined):
        raise EaglError(
            f"tail of {len(tail):#x} bytes does not complete a {len(ord_data):#x}-byte .ord"
        )
    return joined


class _Elf:
    def __init__(self, data: bytes):
        if data[:4] != ELF_MAGIC:
            raise EaglError("not an ELF object")
        e_shoff = struct.unpack_from("<I", data, 0x20)[0]
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x2E)
        if e_shoff + e_shnum * e_shentsize > len(data):
            raise EaglError("section table outside the file (missing .orp?)")
        secs = [
            struct.unpack_from("<IIIIIIIIII", data, e_shoff + i * e_shentsize)
            for i in range(e_shnum)
        ]
        shn = secs[e_shstrndx]
        strs = data[shn[4] : shn[4] + shn[5]]
        self.sections = {self._cstr(strs, s[0]): (s[4], s[5]) for s in secs}
        off, size = self.sections.get(".data", (0, 0))
        self.data = data[off : off + size]
        sym = self.sections.get(".symtab")
        strt = self.sections.get(".strtab")
        self.syms: list[tuple[str, int, int, int]] = []  # (name, value, size, shndx)
        if sym and strt:
            st = data[strt[0] : strt[0] + strt[1]]
            for i in range(sym[1] // 16):
                name, value, size_, _info, _other, shndx = struct.unpack_from(
                    "<IIIBBH", data, sym[0] + i * 16
                )
                self.syms.append((self._cstr(st, name), value, size_, shndx))
        rel = self.sections.get(".rel.data")
        self.relocs: dict[int, int] = {}  # .data offset -> symbol index
        if rel:
            for i in range(rel[1] // 8):
                off_, info = struct.unpack_from("<II", data, rel[0] + i * 8)
                self.relocs[off_] = info >> 8

    @staticmethod
    def _cstr(tab: bytes, off: int) -> str:
        end = tab.find(b"\0", off)
        return tab[off : end if end >= 0 else len(tab)].decode("latin-1")

    def ptr(self, off: int) -> int | None:
        """Relocated section-relative pointer at .data offset, or None if it points to an
        external symbol / is not a relocation."""
        s = self.relocs.get(off)
        if s is None or s != 1:
            return None
        return struct.unpack_from("<I", self.data, off)[0]

    def extern(self, off: int) -> str | None:
        s = self.relocs.get(off)
        if s is None or s == 1 or s >= len(self.syms):
            return None
        return self.syms[s][0]

    def u32(self, off: int) -> int:
        return struct.unpack_from(">I", self.data, off)[0]


# ---------------------------------------------------------------------------
# packets
# ---------------------------------------------------------------------------


def _chain(dl: bytes, stride: int) -> list[tuple[int, int, int]] | None:
    """(opcode, count, data offset) for a GX list that must use the whole buffer."""
    p, n, prims = 0, len(dl), []
    while p + 3 <= n:
        op = dl[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            return None
        count = (dl[p + 1] << 8) | dl[p + 2]
        end = p + 3 + count * stride
        if end > n or count == 0:
            return None
        prims.append((op & 0xF8, count, p + 3))
        p = end
    return prims or None


def _triangulate(prims, idx: np.ndarray) -> np.ndarray:
    tris = []
    k = 0
    for op, count, _ in prims:
        v = idx[k : k + count]
        k += count
        if op == 0x90:
            tris.append(v[: count - count % 3].reshape(-1, 3))
        elif op == 0x98:
            for i in range(count - 2):
                a, b, c = v[i], v[i + 1], v[i + 2]
                tris.append(np.array([[a, b, c] if i % 2 == 0 else [b, a, c]], np.uint32))
        elif op == 0xA0:
            for i in range(1, count - 1):
                tris.append(np.array([[v[0], v[i], v[i + 1]]], np.uint32))
        elif op == 0x80:
            q = v[: count - count % 4].reshape(-1, 4)
            tris.append(np.stack([q[:, 0], q[:, 1], q[:, 2]], 1))
            tris.append(np.stack([q[:, 0], q[:, 2], q[:, 3]], 1))
    if not tris:
        return np.zeros(0, np.uint32)
    t = np.concatenate(tris).astype(np.uint32)
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    return t[keep].reshape(-1)


def _packet_entries(elf: _Elf, o_shader: int) -> list[tuple[int, int | None, str | None]]:
    """(count, pointer, extern) list after a shader reference; the first pointer after the
    shader carries no count (it is the matrix palette)."""
    out = []
    o = o_shader + 8
    while o + 8 <= len(elf.data) and len(out) < 32:
        count = elf.u32(o)
        if (o + 4) not in elf.relocs:
            break
        out.append((count, elf.ptr(o + 4), elf.extern(o + 4)))
        o += 8
        if count == 0:
            break
    return out


#: How many matrix index bytes precede a vertex's attribute u16s, in the order tried.
#:
#: Two and none are what shipped; **one** is FIFA's shadow packets, whose vertices are five
#: bytes - `2d 00 00 00 00` - and it is tried LAST on purpose.  A display list that chains at
#: `2*nattr` also chains at `1 + 2*nattr`, so putting one second re-read packets that were
#: already correct and cost two triangles on FIFA 2003.  Order is not cosmetic here.
MATRIX_BYTE_ORDER = (2, 0, 1)


def _streams_after_anchor(ents, i_m: int) -> list:
    """The attribute/display-list streams that follow the matrix anchor.

    A packet can bind **more than one** matrix - FIFA's shadow packets carry
    ``gpModelViewMatrix`` and ``gpViewMatrix`` back to back - and the collection loop stops at
    the first tagged entry.  Anchoring on the first of the run therefore found zero streams and
    dropped the packet, which is what the "0 attribute streams" warning was reporting on 32 of
    FIFA 2003's packets.  Skip the whole run of matrix tags, then collect.
    """
    j = i_m + 1
    while j < len(ents) and ents[j][2] and ents[j][2].startswith("__const MATRIX4"):
        j += 1
    out = []
    while j < len(ents) and ents[j][1] is not None and ents[j][2] is None:
        out.append(ents[j])
        j += 1
    return out


def _display_list_index(streams, d) -> int | None:
    """Which stream is the display list.

    Normally the last one, but not always: FIFA 2003's static objects carry a trailing
    one-entry pointer (the ``__EAGL::TAR`` texture) after it.  Taking ``streams[-1]`` then hands
    a 1-byte "display list" to the opcode check, which fails and returns ``None`` with no
    warning - 14 objects' worth of geometry lost in silence.

    So the display list is chosen by the same test that used to merely validate the choice: it
    has to open on a GX primitive opcode and lie inside ``.data``.  Searching from the end keeps
    the ordinary case identical.
    """
    for k in range(len(streams) - 1, -1, -1):
        size, ptr, _ = streams[k]
        if ptr is None or ptr >= len(d) or ptr + size > len(d):
            continue
        if (d[ptr] & 0xF8) in PRIM_OPS:
            return k
    return None


def _decode_packet(elf: _Elf, o_shader: int, shader: str, warn: list[str]) -> Packet | None:
    d = elf.data
    ents = _packet_entries(elf, o_shader)
    i_m = next((i for i, e in enumerate(ents) if e[2] and e[2].startswith("__const MATRIX4")), None)
    if i_m is None:
        # every one of these used to be silent, and a silent drop reads as "this disc has no
        # geometry" - which is how FIFA 2003 reported a healthy zero for 89 objects
        warn.append(f"packet @{o_shader:#x}: no __const MATRIX4 anchor among {len(ents)} entries")
        return None
    # skin table: the counted pointer right before the const MATRIX4 tag, one row per GX
    # position-matrix slot: 4 f32 weights whose low mantissa byte carries the bone index
    slot_bones = slot_weights = None
    if i_m >= 1:
        cnt, wp, _ = ents[i_m - 1]
        if wp is not None and 1 <= cnt <= 10 and wp + cnt * 16 <= len(d):
            raw = np.frombuffer(d, ">u4", cnt * 4, wp).reshape(cnt, 4)
            slot_bones = (raw & 0xFF).astype(np.uint16)
            slot_weights = (raw & 0xFFFFFF00).astype(">u4").view(">f4").astype(np.float32)
            slot_weights[~np.isfinite(slot_weights)] = 0.0
            slot_weights = np.clip(slot_weights, 0.0, 1.0)
            tot = slot_weights.sum(1, keepdims=True)
            if not (tot > 0).all():
                slot_bones = slot_weights = None
            else:
                slot_weights /= tot
    streams = _streams_after_anchor(ents, i_m)
    if len(streams) < 2:
        warn.append(f"packet @{o_shader:#x}: {len(streams)} attribute streams, need at least 2")
        return None
    # The display list is normally the last stream, but not always: FIFA 2003's static objects
    # carry a trailing one-entry pointer (the `__EAGL::TAR` texture) after it, and taking
    # `streams[-1]` then hands a 1-byte "display list" to the opcode check, which fails and
    # returns None with no warning.  Pick the stream that actually opens on a GX primitive
    # opcode - the same test that validated the choice before, applied as the choice.
    dl_idx = _display_list_index(streams, d)
    if dl_idx is None and len(streams) >= 2 and _v2_preamble(d, streams[-1][1]):
        return _decode_packet_v2(elf, o_shader, shader, ents, streams, slot_bones, slot_weights, warn)
    if dl_idx is None or dl_idx < 1:
        warn.append(
            f"packet @{o_shader:#x}: no display list among {len(streams)} streams"
            if dl_idx is None
            else f"packet @{o_shader:#x}: display list is the only stream"
        )
        return None
    size, dlp, _ = streams[dl_idx]
    attrs = streams[:dl_idx]
    dl = d[dlp : dlp + size]
    nattr = len(attrs)
    # A vertex carries a u16 per attribute stream, preceded by nothing, one matrix index, or
    # two.  FIFA's shadow packets use exactly one - `98 00 07` then seven records of
    # `2d 00 00 00 00`, five bytes each - and trying only 2 and 0 matrix bytes missed them.
    # Order matters: 2 then 0 are what shipped, and one matrix byte is tried only after both,
    # so no display list that already chained can be re-read a different way.  Putting 1 second
    # instead cost two triangles on this disc - a packet that legitimately chains at 2*nattr
    # also chains at 1 + 2*nattr, and the first match wins.
    for matrix_bytes in MATRIX_BYTE_ORDER:
        stride = matrix_bytes + 2 * nattr
        prims = _chain(dl, stride)
        if prims is not None:
            break
    else:
        warn.append(
            f"packet @{o_shader:#x}: display list chains at none of "
            f"{sorted({m + 2 * nattr for m in MATRIX_BYTE_ORDER})}"
        )
        return None
    rows = np.concatenate(
        [
            np.frombuffer(dl, np.uint8, count * stride, off).reshape(count, stride)
            for _, count, off in prims
        ]
    )
    # The attribute u16s start after whatever matrix bytes the record carries, so this has to
    # be the count the stride search actually settled on.  Deriving it from the stride only
    # worked while the choice was two-or-none: with one matrix byte it read the indices a byte
    # early and every one came out enormous ("index 14592 outside 56 vertices").
    f0 = matrix_bytes
    # the skin table is indexed by the position-matrix slot, which only the two-byte form has
    has_mtx = matrix_bytes == 2
    idx = (rows[:, f0].astype(np.uint32) << 8) | rows[:, f0 + 1]
    nv, pos_ptr, _ = attrs[0]
    if idx.max() >= nv or pos_ptr + nv * 6 > len(d):
        warn.append(f"packet @{o_shader:#x}: index {int(idx.max())} outside {nv} vertices")
        return None
    pos = np.frombuffer(d, ">i2", nv * 3, pos_ptr).reshape(nv, 3).astype(np.float32) * POS_SCALE
    tri = _triangulate(prims, idx)
    uvs = normals = None
    if nattr >= 2:
        uv_ptr = attrs[-1][1]
        if uv_ptr + nv * 4 <= len(d):
            k = f0 + 2 * (nattr - 1)
            uv_idx = (rows[:, k].astype(np.uint32) << 8) | rows[:, k + 1]
            uv_all = np.frombuffer(d, ">i2", nv * 2, uv_ptr).reshape(nv, 2).astype(np.float32)
            uv_all *= UV_SCALE
            if uv_idx.max() < nv:
                # per-vertex UV lookup must follow the position index: rebuild per position
                uvs = np.zeros((nv, 2), np.float32)
                uvs[idx] = uv_all[uv_idx]
    if nattr >= 3:
        n_ptr = attrs[-2][1]
        if n_ptr + nv * 3 <= len(d):
            k = f0 + 2 * (nattr - 2)
            n_idx = (rows[:, k].astype(np.uint32) << 8) | rows[:, k + 1]
            n_all = np.frombuffer(d, np.int8, nv * 3, n_ptr).reshape(nv, 3).astype(np.float32)
            n_all /= 127.0
            if n_idx.max() < nv:
                normals = np.zeros((nv, 3), np.float32)
                normals[idx] = n_all[n_idx]
    textures = []
    for _, _, x in ents:
        m = _SHAPENAME.search(x) if x and "TAR" in x else None
        if m:
            textures.append(m.group(1))
    joints = weights = None
    if has_mtx and slot_bones is not None:
        slot = np.minimum(rows[:, 0] // 3, len(slot_bones) - 1)
        joints = np.zeros((nv, 4), np.uint16)
        weights = np.zeros((nv, 4), np.float32)
        joints[idx] = slot_bones[slot]
        weights[idx] = slot_weights[slot]
    return Packet(shader, stride, pos, tri, uvs, normals, joints, weights, textures)


# ---------------------------------------------------------------------------
# the 2004 generation (Def Jam: Fight for NY, NBA Street V3, Fight Night Round 2 ...)
# ---------------------------------------------------------------------------
#
# Same ELF object, same packet entry list, different streams.  Positions are f32 xyz, normals
# s16 with 14 fraction bits, texcoords f32 st, and the display list stream is a single-count
# pointer whose block opens on a preamble - ``ff ff 00 00``, sometimes a pair of 1.0f, then
# zero padding to a 16-byte boundary - before the GX primitives.  It runs up to the packet
# struct (0x20 before the shader pointer).  Vertex records carry two matrix bytes on models
# (one on the planar-shadow skins), then one index per attribute stream: a byte when the
# stream has 256 entries or fewer, two bytes big-endian otherwise, and the last attribute may
# be padded to two bytes.

V2_PREAMBLE = bytes((0xFF, 0xFF, 0, 0))
V2_ONE = bytes((0x3F, 0x80, 0, 0))
NRM_SCALE_V2 = 1.0 / 16384.0


def _v2_preamble(d: bytes, ptr: int | None) -> bool:
    return ptr is not None and d[ptr : ptr + 4] == V2_PREAMBLE


def _v2_dl_start(d: bytes, p: int, end: int) -> int:
    p += 4
    while p + 4 <= end and d[p : p + 4] in (V2_ONE, bytes(4)):
        p += 4
    return p


def _v2_chain(dl: bytes, stride: int) -> list[tuple[int, int, int]]:
    """Primitives from the start of ``dl`` until the first byte that is neither a GX opcode
    nor padding; the packet struct that follows the list is where the walk stops."""
    p, n, prims = 0, len(dl), []
    while p + 3 <= n:
        op = dl[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        count = (dl[p + 1] << 8) | dl[p + 2]
        end = p + 3 + count * stride
        if end > n or count == 0:
            break
        prims.append((op & 0xF8, count, p + 3))
        p = end
    return prims


def _v2_layouts(stride: int, matrix_bytes: int, counts: list[int]) -> list[list[int]]:
    """Candidate index widths per attribute for a record of ``stride`` bytes."""
    n = len(counts)
    rest = stride - matrix_bytes
    out = []
    base = [2 if c > 256 else 1 for c in counts]
    if sum(base) == rest:
        out.append(base)
    if sum(base) + 1 == rest:
        out.append(base[:-1] + [base[-1] + 1])  # last attribute padded / u16
        out.append(base + [0])  # or a trailing pad byte
    if 2 * n == rest:
        out.append([2] * n)
    if n == rest:
        out.append([1] * n)
    return out


def _decode_packet_v2(elf: _Elf, o_shader: int, shader: str, ents, streams, slot_bones, slot_weights, warn: list[str]):
    d = elf.data
    _size, dlp, _ = streams[-1]
    attrs = streams[:-1]
    counts = [c for c, _, _ in attrs]
    # the packet struct follows the last primitive at whatever byte it ends on, so the list
    # cannot be bounded from the far side: chain it greedily and take the stride that reads
    # the most primitives without stepping past a non-opcode
    start = _v2_dl_start(d, dlp, len(d))
    dl = d[start : min(len(d), start + 1 << 20)]
    candidates = []
    for stride in range(1 + len(counts), 3 + 2 * len(counts) + 1):
        prims = _v2_chain(dl, stride)
        if prims:
            candidates.append((sum(c for _, c, _ in prims), stride, prims))
    if not candidates:
        warn.append(f"packet @{o_shader:#x}: v2 display list chains at no stride")
        return None
    # several strides can read the same primitives (a one-strip list ends the walk whatever
    # the stride), so the index layout decides: widest stride first, first layout whose every
    # index stays inside its stream wins
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    chosen = None
    for _total, stride, prims in candidates:
        rows = np.concatenate([np.frombuffer(dl, np.uint8, c * stride, off).reshape(c, stride) for _, c, off in prims])
        for matrix_bytes in (2, 1, 0):
            for widths in _v2_layouts(stride, matrix_bytes, counts):
                cols = []
                q = matrix_bytes
                ok = True
                for k, w in enumerate(widths[: len(counts)]):
                    if w == 1:
                        v = rows[:, q].astype(np.uint32)
                    elif w == 2:
                        v = (rows[:, q].astype(np.uint32) << 8) | rows[:, q + 1]
                    else:
                        ok = False
                        break
                    q += w
                    if v.max() >= counts[k]:
                        ok = False
                        break
                    cols.append(v)
                if ok:
                    chosen = (matrix_bytes, cols, rows, prims, stride)
                    break
            if chosen:
                break
        if chosen:
            break
    if chosen is None:
        warn.append(f"packet @{o_shader:#x}: v2 records fit no index layout for {counts}")
        return None
    matrix_bytes, cols, rows, prims, stride = chosen
    idx = cols[0]
    nv, pos_ptr, _ = attrs[0]
    if pos_ptr + nv * 12 > len(d):
        warn.append(f"packet @{o_shader:#x}: v2 positions past the object")
        return None
    pos = np.frombuffer(d, ">f4", nv * 3, pos_ptr).reshape(nv, 3).astype(np.float32)
    tri = _triangulate(prims, idx)
    uvs = normals = None
    if len(attrs) >= 3:
        nn, n_ptr, _ = attrs[1]
        if n_ptr + nn * 6 <= len(d):
            n_all = np.frombuffer(d, ">i2", nn * 3, n_ptr).reshape(nn, 3).astype(np.float32) * NRM_SCALE_V2
            normals = np.zeros((nv, 3), np.float32)
            normals[idx] = n_all[cols[1]]
    if len(attrs) >= 2:
        nt, t_ptr, _ = attrs[-1]
        if t_ptr + nt * 8 <= len(d):
            uv_all = np.frombuffer(d, ">f4", nt * 2, t_ptr).reshape(nt, 2).astype(np.float32)
            uvs = np.zeros((nv, 2), np.float32)
            uvs[idx] = uv_all[cols[-1]]
    textures = []
    for _, _, x in ents:
        m = _SHAPENAME.search(x) if x and "TAR" in x else None
        if m:
            textures.append(m.group(1))
    joints = weights = None
    if matrix_bytes == 2 and slot_bones is not None:
        slot = np.minimum(rows[:, 0] // 3, len(slot_bones) - 1)
        joints = np.zeros((nv, 4), np.uint16)
        weights = np.zeros((nv, 4), np.float32)
        joints[idx] = slot_bones[slot]
        weights[idx] = slot_weights[slot]
    return Packet(shader, stride, pos, tri, uvs, normals, joints, weights, textures)


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------


_SKEL_MAGIC = bytes.fromhex("c0da01fec0da")  # the shipped tag; see _skeleton_header
_SKEL_MARK = bytes.fromhex("01fe")
_BONE_REC = 112  # scale3 parent quat4 trans3 id | inverse bind 4x4


def _skeleton_header(d: bytes, sk: int) -> bool:
    """Whether a ``__Skeleton`` table starts here.

    The check used to be an exact six-byte magic, ``c0da 01fe c0da``.  FIFA 2003's is
    ``c616 01fe c616`` - the same **shape** with a different tag - and eleven skeletons on that
    disc were thrown away for it.  What is actually constant is the structure: a ``u16`` tag,
    the marker ``01 fe``, then the same ``u16`` tag again.  The bone count that follows is what
    confirms it, and it does: 51, against exactly 51 ``__Bone`` symbols in the same object.
    """
    if sk + 6 > len(d):
        return False
    return d[sk + 2 : sk + 4] == _SKEL_MARK and d[sk : sk + 2] == d[sk + 4 : sk + 6]


def _parse_skeleton(elf: _Elf, warn: list[str]) -> list[Bone]:
    """``__Skeleton`` table: 16-byte header (magic, u32 bone count) then one 112-byte record
    per bone.  ``__Bone`` symbols hold the record index of the bone they name."""
    d = elf.data
    names: dict[int, str] = {}
    for n, v, _s, sh in elf.syms:
        if n.startswith("__Bone:::") and sh and v + 4 <= len(d):
            names[elf.u32(v)] = n.rsplit(".", 1)[-1]
    sk = next((v for n, v, _s, sh in elf.syms if n.startswith("__Skeleton:::") and sh), None)
    if sk is None:
        ident = np.eye(4, dtype=np.float32)
        return [
            Bone(names[k], None, (0, 0, 0), (0, 0, 0, 1), (1, 1, 1), ident) for k in sorted(names)
        ]
    if not _skeleton_header(d, sk):
        warn.append(f"skeleton @{sk:#x}: unknown header {d[sk : sk + 8].hex()}")
        return []
    count = elf.u32(sk + 8)
    if count > 1024 or sk + 16 + count * _BONE_REC > len(d):
        warn.append(f"skeleton @{sk:#x}: {count} bones do not fit")
        return []
    bones = []
    for b in range(count):
        o = sk + 16 + b * _BONE_REC
        f = struct.unpack_from(">28f", d, o)
        parent = struct.unpack_from(">i", d, o + 12)[0]
        bones.append(
            Bone(
                names.get(b, f"bone{b}"),
                parent if 0 <= parent < count and parent != b else None,
                f[8:11],
                f[4:8],
                f[0:3],
                np.array(f[12:28], np.float32).reshape(4, 4),
            )
        )
    return bones


def parse(data: bytes) -> EaglObject:
    elf = _Elf(data)
    warn: list[str] = []
    shader_refs = sorted(
        o
        for o, s in elf.relocs.items()
        if s != 1
        and s < len(elf.syms)
        and elf.syms[s][3] == 0
        and not elf.syms[s][0].startswith("__")
    )
    packets: dict[int, Packet] = {}
    for o in shader_refs:
        pk = _decode_packet(elf, o, elf.syms[elf.relocs[o]][0], warn)
        if pk is not None:
            packets[o - 0x1C] = pk  # packet base = shader pointer - 0x1c
    # every __Model variation of a file points at the same packet run (the variations
    # differ in bone tables / visibility, not geometry), so one Model per object
    variations = [
        n[len("__Model:::") :] for n, _v, _s, sh in elf.syms if n.startswith("__Model:::") and sh
    ]
    stem = variations[0].split(".variation")[0] if variations else "eagl"
    models = [Model(stem, [packets[k] for k in sorted(packets)])] if packets else []
    if models:
        models[0].variations = variations
    skeleton = _parse_skeleton(elf, warn)
    return EaglObject(models, [b.name for b in skeleton], warn, skeleton)
