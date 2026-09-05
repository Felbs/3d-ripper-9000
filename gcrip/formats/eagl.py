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

**World packets** (FIFA pitch / sky / track / stadium shadows, NHL arena bowls, NBA Street
courts) use the same packet layout with *wider elements*: positions are big-endian f32 xyz
(12 bytes), UVs f32 st (8) or s16/256 (4), and the middle stream is f32 normals (12), s8
normals (3), RGBA8 (4) or RGBA4 (2) vertex colours.  Nothing in the packet declares this -
the GX vertex descriptor lives in game code - but the streams are packed back to back
(padded to at most a 32-byte boundary), so each stream's element size follows from the gap
to the next pointer.  Reading these as s16 produced full-range +-128 point clouds: the
whole EA-ball-sports garbage cluster (~900 models over 10+ discs) of the 2026-09-04
quality audit.
"""

from __future__ import annotations

import itertools
import re
import struct
from dataclasses import dataclass, field

import numpy as np

ELF_MAGIC = b"\x7fELF"
PRIM_OPS = (0x80, 0x90, 0x98, 0xA0)
POS_SCALE = 1.0 / 256.0
UV_SCALE = 1.0 / 256.0
_SHAPENAME = re.compile(r"SHAPENAME=([^,;\s]+),(\d+)")


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
    colors: np.ndarray | None = None  # (N,4) u8 RGBA (EA LA static meshes, world packets)
    world: bool = False  # positions were f32 (stadium/arena/court world packet)


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


#: Attribute streams are packed back to back; the padding between one stream's end and the
#: next pointer stays under a 32-byte boundary (measured 0-24 across FIFA 04-07, UEFA, NHL
#: 2003 and NBA Street V2 world packets).  A candidate element size only counts as a fit
#: when the gap leaves less than this.
_STREAM_PAD = 32


def _stream_gap(d: bytes, ents, ptr: int) -> int:
    """Bytes from ``ptr`` to the next counted pointer of the packet (or the end of .data)."""
    nxt = min((q for _c, q, x in ents if x is None and q is not None and q > ptr), default=len(d))
    return nxt - ptr


def _fits(gap: int, count: int, es: int) -> bool:
    return 0 <= gap - count * es < _STREAM_PAD


def _world_positions(d: bytes, ents, nv: int, ptr: int) -> np.ndarray | None:
    """Positions of a world packet - big-endian f32 xyz - or None when the stream is not one.

    The gap to the next stream has to fit 12-byte elements AND the floats have to read as
    plausible coordinates (finite, 98th percentile between 1e-3 and 1e6).  Both gates matter:
    an s16 stream's gap fits 6, not 12, except on packets of five vertices or fewer, and there
    the float test decides - s16 words reinterpreted as f32 exponents land in denormal or
    astronomic territory, real world meshes (pitches at +-7400, courts at +-80) do not.
    """
    if nv < 3 or ptr + nv * 12 > len(d) or not _fits(_stream_gap(d, ents, ptr), nv, 12):
        return None
    pos = np.frombuffer(d, ">f4", nv * 3, ptr).reshape(nv, 3).astype(np.float32)
    if not np.isfinite(pos).all():
        return None
    p98 = float(np.percentile(np.abs(pos), 98))
    if not 1e-3 < p98 < 1e6:
        return None
    if not (pos != pos[0]).any():
        # every vertex identical is no evidence of world geometry (FIFA 2004's
        # amsterdamshadow placeholder reads as one point at x=150047): keep the legacy read
        return None
    return pos


def _world_attributes(d: bytes, ents, attrs, rows, idx, nv: int, f0: int):
    """(uvs, normals, colors) of a world packet, each stream decoded by its element size.

    The UV stream (last) is f32 st pairs (8) or s16/256 (4); the middle stream is f32
    normals (12: NHL arenas, unit length), s8 normals (3), RGBA8 (4: NBA Street courts,
    alpha 255) or RGBA4 (2: FIFA track/shadow overlays - the '0x77 0x7f constant' of the
    2026-08-28 note was mid-gray at full alpha).  Ambiguity between sizes is resolved by
    the smallest padding, and a stream that fits nothing yields None rather than a guess.
    """
    nattr = len(attrs)
    uvs = normals = colors = None
    if nattr >= 2:
        uv_ptr = attrs[-1][1]
        k = f0 + 2 * (nattr - 1)
        uv_idx = (rows[:, k].astype(np.uint32) << 8) | rows[:, k + 1]
        gap = _stream_gap(d, ents, uv_ptr)
        if uv_idx.max() < nv:
            uv_all = None
            if _fits(gap, nv, 8) and uv_ptr + nv * 8 <= len(d):
                uv_all = np.frombuffer(d, ">f4", nv * 2, uv_ptr).reshape(nv, 2).astype(np.float32)
            elif _fits(gap, nv, 4) and uv_ptr + nv * 4 <= len(d):
                uv_all = np.frombuffer(d, ">i2", nv * 2, uv_ptr).reshape(nv, 2).astype(np.float32)
                uv_all *= UV_SCALE
            if uv_all is not None:
                uvs = np.zeros((nv, 2), np.float32)
                uvs[idx] = uv_all[uv_idx]
    if nattr >= 3:
        m_ptr = attrs[-2][1]
        k = f0 + 2 * (nattr - 2)
        m_idx = (rows[:, k].astype(np.uint32) << 8) | rows[:, k + 1]
        gap = _stream_gap(d, ents, m_ptr)
        sizes = sorted(
            (gap - nv * es, es)
            for es in (12, 4, 3, 2)
            if _fits(gap, nv, es) and m_ptr + nv * es <= len(d)
        )
        if m_idx.max() < nv and sizes:
            es = sizes[0][1]
            if es == 12:
                n_all = np.frombuffer(d, ">f4", nv * 3, m_ptr).reshape(nv, 3).astype(np.float32)
                normals = np.zeros((nv, 3), np.float32)
                normals[idx] = n_all[m_idx]
            elif es == 3:
                n_all = np.frombuffer(d, np.int8, nv * 3, m_ptr).reshape(nv, 3)
                normals = np.zeros((nv, 3), np.float32)
                normals[idx] = n_all[m_idx].astype(np.float32) / 127.0
            else:
                if es == 4:
                    c_all = np.frombuffer(d, np.uint8, nv * 4, m_ptr).reshape(nv, 4)
                else:  # RGBA4: RRRRGGGGBBBBAAAA, expanded x17 to 8 bits
                    w = np.frombuffer(d, ">u2", nv, m_ptr).astype(np.uint16)
                    c_all = (
                        np.stack([(w >> 12) & 15, (w >> 8) & 15, (w >> 4) & 15, w & 15], 1) * 17
                    ).astype(np.uint8)
                colors = np.zeros((nv, 4), np.uint8)
                colors[idx] = c_all[m_idx]
    return uvs, normals, colors


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
    if shader.startswith(LA_SHADER_PREFIX):
        return _decode_packet_la(elf, o_shader, shader, ents, slot_bones, slot_weights, warn)
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
        return _decode_packet_v2(
            elf, o_shader, shader, ents, streams, slot_bones, slot_weights, warn
        )
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
    # World packets (pitch / sky / track / arena / court) carry f32 positions; everything
    # else keeps the s16/256 read, byte for byte.  Reading the f32 family as s16 gave the
    # +-128 saturation clouds of the EA ball-sports garbage cluster (quality audit #6-#15).
    pos = _world_positions(d, ents, nv, pos_ptr)
    world = pos is not None
    if not world:
        pos = np.frombuffer(d, ">i2", nv * 3, pos_ptr).reshape(nv, 3).astype(np.float32)
        pos *= POS_SCALE
    tri = _triangulate(prims, idx)
    uvs = normals = colors = None
    if world:
        uvs, normals, colors = _world_attributes(d, ents, attrs, rows, idx, nv, f0)
    else:
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
    return Packet(shader, stride, pos, tri, uvs, normals, joints, weights, textures, colors, world)


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


def _decode_packet_v2(
    elf: _Elf, o_shader: int, shader: str, ents, streams, slot_bones, slot_weights, warn: list[str]
):
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
        rows = np.concatenate(
            [np.frombuffer(dl, np.uint8, c * stride, off).reshape(c, stride) for _, c, off in prims]
        )
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
            n_all = (
                np.frombuffer(d, ">i2", nn * 3, n_ptr).reshape(nn, 3).astype(np.float32)
                * NRM_SCALE_V2
            )
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
# EA Los Angeles 2003-04 (Medal of Honor: Rising Sun, GoldenEye: Rogue Agent)
# ---------------------------------------------------------------------------
#
# Same ELF object again, with the packet entries threaded through light-block / COORD4
# externs and the streams indexed **separately** (a packet's positions, normals and texcoords
# have different counts).  The first section pointer of a packet is a 16-byte header whose
# first word is the display-list vertex count (Rising Sun: the corners as written; GoldenEye:
# the corners of one merged strip, i.e. corners + primitives - 1) and, on GoldenEye, whose
# second is the normal count.  The attribute streams follow the matrix tags; their element
# sizes come from the gap to the next pointer of the packet: 6 = s16 positions, 3 = s8
# normals, 4 = RGBA8 colours or s16 texcoords (a colour stream first, unless the shader is a
# skin), 16 = f32 x4 normals (GoldenEye, lit on the CPU), 1 = the per-normal matrix slots.
# The display list is not pointed at: it starts after the last stream / constant of the
# packet, and every corner is [posmtx slot u8 (skins)] [pos] [nrm] [clr] [uv0] [uv1 ...] on
# Rising Sun (u16 where a stream has more than 256 entries) and [slot] [pos] [clr] [nrm u16]
# [uv ...] on GoldenEye (its env-map / specular skins repeat the normal index).
#
# Vertex formats from the shipped ELFs' ``RenderMoh3_*`` (``GXSetVtxAttrFmt`` /
# ``SetAttributeFormat``): positions s16 with 8 fraction bits on ``Msh_`` shaders, u16 / 8 on
# ``Cpt_`` compartments (offset by the packet's first COORD4 constant behind the
# GeoPrimState), s16 / 10 on ``Skin_``; texcoords s16 / 10; s8 normals / 64.

LA_SHADER_PREFIX = "Moh3_"
LA_UV_SCALE = 1.0 / 1024.0
_LA_ELEMENT_SIZES = (16, 6, 4, 3, 1)


def _la_streams(ents, header_ptr: int, skin_ptr: int | None) -> list[list[tuple[int, int, int]]]:
    """Per stream, the (count, pointer, element size) candidates - best fit first - for the
    counted section pointers of an EA LA packet: every one before the GeoPrimState / TAR
    externs, only counted (>1) ones behind them (the rest are the packet's constants)."""
    streams = []
    state = False
    for count, ptr, ext in ents:
        if ext and (ext.startswith("__EAGL::GeoPrimState") or ext.startswith("__EAGL::TAR")):
            state = True
        counted = ext is None and ptr is not None and ptr not in (header_ptr, skin_ptr)
        if counted and (count > 1 or not state):
            streams.append((count, ptr))
    ptrs = sorted({ptr for _, ptr, ext in ents if ext is None and ptr is not None})
    out = []
    for count, ptr in streams:
        after = [q for q in ptrs if q > ptr]
        if not after:
            out.append([(count, ptr, es) for es in (6, 3, 4, 16, 1)])
            continue
        gap = after[0] - ptr
        # streams are packed on 4-byte boundaries: the fit leaves at most 3 bytes
        fits = sorted(
            (gap - count * es, es)
            for es in _LA_ELEMENT_SIZES
            if count * es <= gap and gap - count * es < 4
        )
        out.append([(count, ptr, es) for _, es in fits])
    return out


def _la_columns(kinds, shader: str):
    """Corner columns (role, (count, ptr, element size)) for one element-size assignment, or
    None when it names no single position stream."""
    pos = [k for k in kinds if k[2] == 6]
    nrm8 = [k for k in kinds if k[2] == 3]
    nrm16 = [k for k in kinds if k[2] == 16]
    four = [k for k in kinds if k[2] == 4]
    if len(pos) != 1 or len(nrm8) + len(nrm16) > 1:
        return None
    if not nrm8 and not nrm16 and "Color" not in shader:
        # every RenderMoh3_* shader but the flat-colour ones binds GX_VA_NRM, and a tiny
        # normal stream (2 x 3 bytes padded to 8) fits the 4-byte size just as well
        return None
    cols = [("pos", pos[0])]
    if nrm8:
        cols.append(("nrm", nrm8[0]))
    if four and "Skin" not in shader:
        cols.append(("clr", four[0]))
        four = four[1:]
    if nrm16:
        cols.append(("nrm", nrm16[0]))
    cols += [(f"uv{i}", k) for i, k in enumerate(four)]
    return cols


def _la_prims(d: bytes, start: int, stride: int) -> list[tuple[int, int, int]]:
    """(opcode, count, data offset) primitives from ``start`` at ``stride`` bytes a corner,
    up to the first byte that is neither an opcode nor padding."""
    p, prims = start, []
    while p + 3 <= len(d):
        op = d[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        count = (d[p + 1] << 8) | d[p + 2]
        if count == 0 or p + 3 + count * stride > len(d):
            break
        prims.append((op & 0xF8, count, p + 3))
        p += 3 + count * stride
    return prims


def _la_display_list(d: bytes, kinds, cols, want: int):
    """Find the display list behind the streams: the first primitive opcode after the last
    stream whose chain, at some stride, reads exactly the header's corner count and whose
    corner indices all fall inside their streams.  Returns (matrix bytes, index columns,
    rows, prims) or None."""
    lo = max(ptr + count * es for count, ptr, es in kinds)
    counts = [k[0] for _, k in cols]
    nrm16 = any(role == "nrm" and k[2] == 16 for role, k in cols)
    ncol = len(cols)
    for start in range(lo, min(len(d) - 3, lo + 0x200)):
        if (d[start] & 0xF8) not in PRIM_OPS:
            continue
        for stride in range(ncol, 2 * ncol + 4):
            prims = _la_prims(d, start, stride)
            if not prims:
                continue
            total = sum(c for _, c, _ in prims)
            if total != want and total + len(prims) - 1 != want:
                continue
            rows = np.concatenate(
                [
                    np.frombuffer(d, np.uint8, c * stride, off).reshape(c, stride)
                    for _, c, off in prims
                ]
            )
            for matrix_bytes in (0, 1):
                for dup in (0, 1) if nrm16 else (0,):
                    for widths in itertools.product((1, 2), repeat=ncol):
                        if matrix_bytes + sum(widths) + 2 * dup != stride:
                            continue
                        if nrm16 and any(
                            w != 2 for (r, _), w in zip(cols, widths, strict=True) if r == "nrm"
                        ):
                            continue
                        idx = _la_indices(rows, cols, widths, counts, matrix_bytes, dup)
                        if idx is not None:
                            return matrix_bytes, idx, rows, prims
    return None


def _la_indices(rows, cols, widths, counts, matrix_bytes: int, dup: int):
    q, idx = matrix_bytes, []
    for k, (w, count) in enumerate(zip(widths, counts, strict=True)):
        if w == 1:
            v = rows[:, q].astype(np.uint32)
        else:
            v = (rows[:, q].astype(np.uint32) << 8) | rows[:, q + 1]
        q += w
        if v.max() >= count:
            return None
        idx.append(v)
        if dup and cols[k][0] == "nrm":
            v2 = (rows[:, q].astype(np.uint32) << 8) | rows[:, q + 1]
            q += 2
            if not np.array_equal(v, v2):
                return None
    return idx


def _decode_packet_la(
    elf: _Elf, o_shader: int, shader: str, ents, slot_bones, slot_weights, warn: list[str]
):
    d = elf.data
    section = [(c, p) for c, p, x in ents if x is None and p is not None]
    if not section:
        warn.append(f"packet @{o_shader:#x}: EA LA packet with no section pointers")
        return None
    header_ptr = section[0][1]
    want = elf.u32(header_ptr)
    if want < 3:
        return None  # legitimate: nothing to draw
    i_m = next((i for i, e in enumerate(ents) if e[2] and e[2].startswith("__const MATRIX4")), None)
    skin_ptr = None
    if i_m is not None and i_m >= 1 and ents[i_m - 1][2] is None:
        skin_ptr = ents[i_m - 1][1] if ents[i_m - 1][1] != header_ptr else None
    candidates = _la_streams(ents, header_ptr, skin_ptr)
    if not candidates or any(not c for c in candidates):
        warn.append(f"packet @{o_shader:#x}: EA LA streams fit no element size")
        return None
    found = None
    # the assignment with the least padding overall first
    combos = sorted(
        itertools.islice(itertools.product(*candidates), 64),
        key=lambda ks: sum(cands.index(k) for k, cands in zip(ks, candidates, strict=True)),
    )
    for kinds in combos:
        cols = _la_columns(kinds, shader)
        if cols is None:
            continue
        found = _la_display_list(d, kinds, cols, want)
        if found:
            break
    if found is None:
        warn.append(
            f"packet @{o_shader:#x}: no EA LA display list of {want} corners behind "
            f"{len(candidates)} streams"
        )
        return None
    matrix_bytes, idx, rows, prims = found
    n = len(rows)
    compartment = "Cpt_" in shader
    pos_scale = 1.0 / 1024.0 if "Skin" in shader else 1.0 / 256.0
    pos = None
    uvs = normals = colors = None
    for (role, (count, ptr, es)), v in zip(cols, idx, strict=True):
        if role == "pos":
            raw = np.frombuffer(d, ">u2" if compartment else ">i2", count * 3, ptr).reshape(
                count, 3
            )
            pos = raw[v].astype(np.float32) * pos_scale
        elif role == "nrm" and es == 3:
            raw = np.frombuffer(d, np.int8, count * 3, ptr).reshape(count, 3)
            normals = raw[v].astype(np.float32) / 64.0
        elif role == "nrm":
            normals = (
                np.frombuffer(d, ">f4", count * 4, ptr).reshape(count, 4)[v, :3].astype(np.float32)
            )
        elif role == "clr":
            colors = np.frombuffer(d, np.uint8, count * 4, ptr).reshape(count, 4)[v].copy()
        elif role == "uv0":
            raw = np.frombuffer(d, ">i2", count * 2, ptr).reshape(count, 2)
            uvs = raw[v].astype(np.float32) * LA_UV_SCALE
    if compartment:
        # the compartment's u16 positions count from the packet's origin, the first COORD4
        # constant behind the GeoPrimState
        behind = False
        for count, ptr, ext in ents:
            if ext and ext.startswith("__EAGL::GeoPrimState"):
                behind = True
            elif behind and ext is None and ptr is not None and count == 1 and ptr + 12 <= len(d):
                pos = pos + np.frombuffer(d, ">f4", 3, ptr)
                break
    tri = _triangulate(prims, np.arange(n, dtype=np.uint32))
    textures = []
    for _, _, x in ents:
        m = _SHAPENAME.search(x) if x and "TAR" in x else None
        if m:
            textures.append(m.group(1))
    joints = weights = None
    if matrix_bytes and slot_bones is not None:
        slot = np.minimum(rows[:, 0] // 3, len(slot_bones) - 1)
        joints = slot_bones[slot]
        weights = slot_weights[slot]
    return Packet(shader, rows.shape[1], pos, tri, uvs, normals, joints, weights, textures, colors)


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


def _model_bbox(elf: _Elf) -> tuple[float, ...] | None:
    """min xyz, max xyz from the ``__BBOX`` symbol (the first 6 floats; the rest is runtime
    scratch).  Verified against the geometry: FIFA 2004's pitchline f32 span equals it to the
    bit, and the player bodies' raw s16 span x 1/256 does too."""
    for n, v, _s, sh in elf.syms:
        if n.startswith("__BBOX") and sh and v + 24 <= len(elf.data):
            box = struct.unpack_from(">6f", elf.data, v)
            if all(np.isfinite(b) for b in box) and any(box[i + 3] > box[i] for i in range(3)):
                return box
    return None


def _rescale_s16(packets, elf: _Elf) -> None:
    """Fix the s16 quantization of static world objects against the model's ``__BBOX``.

    The GX fraction shift is set by game code per mesh class, not stored in the object:
    player bodies use 8 bits (the shipped ``POS_SCALE`` 1/256), but stadium files quantize
    coarser - Old Trafford's bowl uses **1 bit** (scale 1/2), and reading it at 1/256 left
    the stands 128x too small next to their own f32 pitch and track.  The scale is
    recoverable: ``bbox span / raw s16 span``, which lands on a power of two to 4 decimal
    places on every axis (players 0.00391 x3, the bowl 0.50002/0.50011/0.50002).

    Applied only when every well-measured axis agrees on the same power of two within 5%
    and that power is not 1/256 - so player-class objects (and anything ambiguous) are left
    byte-for-byte alone.  Skinned objects never reach here (the caller gates on an empty
    skeleton): their positions must keep matching the inverse-bind matrices.
    """
    s16 = [pk for pk in packets if not pk.world and len(pk.positions)]
    box = _model_bbox(elf)
    if not s16 or box is None:
        return
    lo = np.min([pk.positions.min(0) for pk in s16], axis=0)
    hi = np.max([pk.positions.max(0) for pk in s16], axis=0)
    raw_span = (hi - lo) / POS_SCALE
    box_span = np.array(box[3:]) - np.array(box[:3])
    ok = (raw_span > 256.0) & (box_span > 0)  # axes with over a unit of raw geometry
    if not ok.any():
        return
    ratio = box_span[ok] / raw_span[ok]
    if ratio.max() > ratio.min() * 1.05:
        return
    snapped = float(2.0 ** np.round(np.log2(np.median(ratio))))
    if abs(np.median(ratio) / snapped - 1.0) > 0.05 or snapped == POS_SCALE:
        return
    for pk in s16:
        pk.positions *= snapped / POS_SCALE


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
    if not skeleton and packets:
        _rescale_s16(packets.values(), elf)
    return EaglObject(models, [b.name for b in skeleton], warn, skeleton)
