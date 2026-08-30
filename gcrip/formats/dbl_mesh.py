"""Avalanche Software GameCube model records (Tak 1-3, Chicken Little, DBZ Sagas, Rugrats: Royal
Ransom) inside the DBL / DBU sub-databases (gcrip.formats.dbl).

Every record is a kind-0xe sub-database; the second header byte tells the record type: 0x82
texture, 0x67 material list, 0x20-0x2f mesh (0x86 / 0x98 model headers, kind 0xb between
models of a merged ``.dbu``, kind 0xa motions).

Mesh payload: ``u32 0x10001 | u32 8`` (missing in the older 0x20 / 0x21 records) then ``u32
flags | f32 sphere[4] | f32 bbox[6] | char name[32] | u32 vertex count | u32 positions | u32 x6 |
u32 rows | u32 dl count | u32 dl list | u32 x2 | u32 normal count | u32 normals | u32 uv count |
u32 uvs | u32 x2 | u32 uvs``; offsets are relative to payload + 8 (i.e. to the flags word).
Arrays are GX-native: positions f32 xyz (s16 in a few records), normals s8 (/64), uvs f32.
The DL list runs from ``dl list`` to the first array: entries ``u32 total | u32 material | u32 |
u32 bone ids (bytes) | u32 | u32 size | u16 rows | u16 triangles | u16 | u16`` each followed by
``size`` bytes of raw GX FIFO: CP loads (0x08 reg u32 - 0x50 VCD_LO / 0x60 VCD_HI; the
2002 records of Rugrats: Royal Ransom omit them and the descriptor is inferred), XF and BP
setup, indexed matrix loads and primitives (0x80-0xb8 | VAT slot) whose rows hold the enabled
index attributes (u8 / u16) in GX order (PNMTXIDX, TEXnMTXIDX, POS, NRM, COL0, COL1, TEX0-7).

Texture tables (record type 0x82, 0x86 for particle sheets): ``u32 count | u32 x5 | char dir[32]``
then 0x48-byte entries ``u32 code | u32 x2 | u32 pixel offset | u16 w | u16 h | u32 x2 | u32
palette offset | u32 x2 | char name[32]`` and the palette / pixel data.  The pixel format follows
from bytes per pixel (0.5 CMPR or CI4, 1 CI8 or I8, 2 RGB5A3, 4 RGBA8; codes seen: 8 CI4, 9 CI8,
0x405 CMPR, 0x41c RGBA8, 0x8000 = a 4-byte-per-entry palette area whose first half is the
RGB5A3 palette).  Material lists (0x67): ``u16 version | u16 1 | u32 header size | ...`` with
ASCII names (texture file names in Tak, Maya material names in Chicken Little); a DL's material
index (1-based in the prefixed records, 0-based in the old ones) binds by name, else by index.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import dbl, gx_texture

BASE = 8
PREFIX = struct.pack(">2I", 0x10001, 8)
_NAME = re.compile(rb"[\x20-\x7e]{2,}")


@dataclass
class Mesh:
    name: str
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    indices: np.ndarray
    material: int = 0
    bones: tuple[int, ...] = ()
    rows: int = 0
    tris: int = 0


@dataclass
class Record:
    name: str
    meshes: list[Mesh] = field(default_factory=list)


@dataclass
class Texture:
    name: str
    width: int
    height: int
    code: int
    rgba: np.ndarray | None


@dataclass
class Model:
    textures: list[Texture] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)


def record_type(data: bytes, block: dbl.Block) -> int:
    """Second byte of the sub-database id (first byte in little-endian ``.dbu`` headers)."""
    return data[block.offset + (0 if block.little else 1)]


def normalize(pay: bytes) -> bytes:
    """Give the older (0x20 / 0x21) mesh records the ``0x10001 | 8`` prefix."""
    if pay[:8] == PREFIX or len(pay) < 0x60:
        return pay
    if pay[0] in range(0x0C, 0x20) and pay[0x30:0x31].isalnum():
        return PREFIX + pay
    return pay


def is_mesh(pay: bytes) -> bool:
    pay = normalize(pay)
    if len(pay) < 0xC0 or pay[:8] != PREFIX:
        return False
    name = pay[0x38:0x58].split(b"\0")[0]
    if not name or not all(32 <= c < 127 for c in name):
        return False
    nv, po = struct.unpack_from(">2I", pay, 0x58)
    return 0 < nv < 200000 and 0 < po + BASE < len(pay)


def _array(pay: bytes, off: int, count: int, next_off: int, comps: int) -> np.ndarray | None:
    """``count`` vectors at ``off``.  The element size follows from the room up to the next
    array: f32 tightly packed (12 bytes for a position), f32 with padding (Rugrats keeps a
    trailing word: 16), or the s16 / s8 forms."""
    start = off + BASE
    if count <= 0 or start >= len(pay):
        return None
    room = (next_off + BASE if next_off > off else len(pay)) - start
    per = room / count
    if per >= 4 * comps:
        stride = 4 * comps
        if next_off > off:
            fitted = int(per) // 4 * 4
            if 4 * comps <= fitted <= 4 * comps + 16:
                stride = fitted
        n = min(count, (len(pay) - start) // stride)
        rec = np.frombuffer(pay, np.uint8, n * stride, start).reshape(n, stride)
        return rec[:, : 4 * comps].copy().view(">f4").reshape(n, comps).astype(np.float32)
    if per >= 2 * comps:
        n = min(count, (len(pay) - start) // (2 * comps))
        return np.frombuffer(pay, ">i2", n * comps, start).reshape(n, comps).astype(np.float32)
    if per >= comps:
        n = min(count, (len(pay) - start) // comps)
        return np.frombuffer(pay, np.int8, n * comps, start).reshape(n, comps).astype(np.float32)
    return None


def _vcd_layout(lo: int, hi: int) -> list[tuple[str, int]] | None:
    """Row columns (name, byte width) for a VCD; None when a real attribute is direct."""
    cols: list[tuple[str, int]] = []
    if lo & 1:
        cols.append(("pnmtx", 1))
    for t in range(8):
        if lo & (2 << t):
            cols.append((f"texmtx{t}", 1))
    for name, shift, reg in (("pos", 9, lo), ("nrm", 11, lo), ("col0", 13, lo), ("col1", 15, lo)):
        mode = (reg >> shift) & 3
        if mode == 1:
            return None
        if mode:
            cols.append((name, 1 if mode == 2 else 2))
    for t in range(8):
        mode = (hi >> (2 * t)) & 3
        if mode == 1:
            return None
        if mode:
            cols.append((f"tex{t}", 1 if mode == 2 else 2))
    return cols


def _vcd(pnmtx: bool, mode: int, color: bool, uv: bool) -> tuple[int, int]:
    """(VCD_LO, VCD_HI) for indexed position / normal / colour / uv (mode 2 = u8, 3 = u16)."""
    lo = 1 if pnmtx else 0
    lo |= mode << 9  # position
    lo |= mode << 11  # normal
    if color:
        lo |= mode << 13
    return lo, (mode if uv else 0)


# Records whose display lists carry no CP loads (Rugrats: Royal Ransom) set the vertex
# descriptor once at load time; these are the layouts worth trying, best score wins.
_IMPLIED_VCDS = (
    _vcd(True, 3, True, True),
    _vcd(True, 3, False, True),
    _vcd(True, 2, True, True),
    _vcd(True, 2, False, True),
    _vcd(False, 3, True, True),
    _vcd(False, 2, True, True),
)


def _infer_vcd(pay: bytes, spans: list[tuple[int, int]], limits: tuple[int, int, int]) -> list[int]:
    """Pick the implied vertex descriptor whose indices stay inside the record's arrays: each
    display list is scored on its own, a list that does not fit simply scores nothing."""
    best = [0, 0]
    best_score = 0
    npos, nnrm, nuv = limits
    for lo, hi in _IMPLIED_VCDS:
        cols = _vcd_layout(lo, hi)
        if cols is None:
            continue
        stride = sum(w for _, w in cols)
        score = 0
        for start, end in spans:
            i = start
            good = 0
            while i + 3 <= end:
                op = pay[i]
                if op == 0:
                    i += 1
                    continue
                if op & 0xF8 not in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8):
                    good = 0
                    break
                n = struct.unpack_from(">H", pay, i + 1)[0]
                i += 3
                if n == 0 or i + n * stride > end:
                    good = 0
                    break
                rows = np.frombuffer(pay, np.uint8, n * stride, i).reshape(n, stride)
                i += n * stride
                c = 0
                fits = True
                for name, wd in cols:
                    v = rows[:, c].astype(np.int64)
                    if wd == 2:
                        v = (v << 8) | rows[:, c + 1]
                    limit = {"pos": npos, "nrm": nnrm, "tex0": nuv}.get(name)
                    if limit and int(v.max()) >= limit:
                        fits = False
                        break
                    c += wd
                if not fits:
                    good = 0
                    break
                good += max(n - 2, 0)
            score += good
        if score > best_score:
            best, best_score = [lo, hi], score
    return best


def parse(pay: bytes) -> Record | None:
    pay = normalize(pay)
    if not is_mesh(pay):
        return None
    w = struct.unpack_from(">42I", pay, 0x58)
    name = pay[0x38:0x58].split(b"\0")[0].decode("latin-1")
    nv, po = w[0], w[1]
    dlt = w[10]
    nn, no = w[13], w[14]
    nu, uo = w[15], w[16]
    rec = Record(name)
    pos = _array(pay, po, nv, no if no > po else uo, 3)
    if pos is None:
        return rec
    nrm = _array(pay, no, nn, uo if uo > no else 0, 3) if nn and no else None
    if nrm is not None and np.abs(nrm).max() > 1.5:
        nrm = nrm / 64.0
    uv = _array(pay, uo, nu, 0, 2) if nu and uo else None
    if uv is not None and np.abs(uv).max() > 256:
        uv = uv / 256.0
    arrays = min(x + BASE for x in (po, no, uo) if x)
    spans: list[tuple[int, int]] = []
    p = dlt + BASE
    while p + 32 <= arrays and p + 32 <= len(pay):
        size = struct.unpack_from(">I", pay, p + 20)[0]
        start = p + 32
        end = min(start + size, arrays, len(pay))
        if size == 0 or end <= start:
            break
        spans.append((start, end))
        p = end
    vcd = [0, 0]  # VCD_LO / VCD_HI persist across a record's display lists
    if spans and pay[spans[0][0]] != 0x08:
        vcd = _infer_vcd(
            pay,
            spans,
            (len(pos), len(nrm) if nrm is not None else 0, len(uv) if uv is not None else 0),
        )
    p = dlt + BASE
    k = 0
    while p + 32 <= arrays and p + 32 <= len(pay):
        _total, material, _z, bones, _run, size, rows, ntris = struct.unpack_from(">5IIHH", pay, p)
        dl_start = p + 32
        dl_end = min(dl_start + size, arrays, len(pay))
        if size == 0 or dl_end <= dl_start:
            break
        mesh = _display_list(pay, dl_start, dl_end, pos, nrm, uv, vcd)
        if mesh is not None:
            mesh.name = f"{name}_{k}"
            mesh.material = material
            mesh.bones = tuple(b for b in bones.to_bytes(4, "big") if b) or (0,)
            mesh.rows = rows
            mesh.tris = ntris
            rec.meshes.append(mesh)
        p = dl_end
        k += 1
    return rec


def _display_list(pay, start, end, pos, nrm, uv, vcd: list[int]) -> Mesh | None:
    i = start
    rows_all: list[np.ndarray] = []
    layouts: list[list[tuple[str, int]]] = []
    tris: list[np.ndarray] = []
    base = 0
    while i < end:
        op = pay[i]
        if op == 0:
            i += 1
        elif op == 0x08:
            if i + 6 > end:
                break
            reg = pay[i + 1]
            val = struct.unpack_from(">I", pay, i + 2)[0]
            if reg == 0x50:
                vcd[0] = val
            elif reg == 0x60:
                vcd[1] = val
            i += 6
        elif op == 0x10:
            n = struct.unpack_from(">H", pay, i + 1)[0] + 1
            i += 5 + 4 * n
        elif op == 0x61 or op in (0x20, 0x28, 0x30, 0x38):
            i += 5
        elif op & 0xF8 in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8):
            cols = _vcd_layout(vcd[0], vcd[1])
            if cols is None:
                return None
            stride = sum(wd for _, wd in cols)
            n = struct.unpack_from(">H", pay, i + 1)[0]
            i += 3
            if n == 0 or stride == 0 or i + n * stride > end:
                break
            rows = np.frombuffer(pay, np.uint8, n * stride, i).reshape(n, stride)
            i += n * stride
            prim = op & 0xF8
            if prim == 0x98:
                t = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(n - 2)]
            elif prim == 0x90:
                t = [(k, k + 1, k + 2) for k in range(0, n - 2, 3)]
            elif prim == 0xA0:
                t = [(0, k, k + 1) for k in range(1, n - 1)]
            elif prim == 0x80:
                t = [(k, k + 1, k + 2) for k in range(0, n - 3, 4)]
                t += [(k, k + 2, k + 3) for k in range(0, n - 3, 4)]
            else:
                continue
            if not t:
                continue
            rows_all.append(rows)
            layouts.append(cols)
            tris.append(np.array(t, np.uint32).reshape(-1, 3) + base)
            base += n
        else:
            break
    if not rows_all:
        return None

    def column(rows: np.ndarray, cols, want: str) -> np.ndarray | None:
        c = 0
        for name, wd in cols:
            if name == want:
                r = rows[:, c].astype(np.int64)
                return (r << 8) | rows[:, c + 1] if wd == 2 else r
            c += wd
        return None

    P, N, U = [], [], []
    for rows, cols in zip(rows_all, layouts, strict=True):
        pi = column(rows, cols, "pos")
        if pi is None or pi.max() >= len(pos):
            return None
        P.append(pos[pi])
        ni = column(rows, cols, "nrm")
        N.append(nrm[ni] if nrm is not None and ni is not None and ni.max() < len(nrm) else None)
        ui = column(rows, cols, "tex0")
        U.append(uv[ui] if uv is not None and ui is not None and ui.max() < len(uv) else None)
    positions = np.concatenate(P)
    normals = np.concatenate(N) if all(x is not None for x in N) else None
    uvs = np.concatenate(U) if all(x is not None for x in U) else None
    return Mesh("", positions, normals, uvs, np.concatenate(tris).reshape(-1))


_ENTRY = 0x48


def _entries(pay: bytes) -> list[tuple[int, int, int, int, int, str]]:
    """(code, pixel offset, width, height, palette offset, name) per texture table entry."""
    if len(pay) < 0x38 + _ENTRY:
        return []
    count = struct.unpack_from(">I", pay, 0)[0]
    if not 0 < count <= 256 or 0x38 + count * _ENTRY > len(pay):
        return []
    out = []
    for k in range(count):
        e = 0x38 + k * _ENTRY
        code, _a, _b, off, dims, _c, _d, pal = struct.unpack_from(">8I", pay, e)
        w, h = dims >> 16, dims & 0xFFFF
        raw = pay[e + 0x28 : e + _ENTRY].split(b"\0")[0]
        if not (0 < w <= 2048 and 0 < h <= 2048 and 0 < off < len(pay)) or not raw.isascii():
            return []
        path = raw.decode("latin-1").replace("\\", "/")
        name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or f"tex{k:03d}"
        out.append((code, off, w, h, pal, name))
    return out


def is_texture(pay: bytes) -> bool:
    return bool(_entries(pay))


def textures(pay: bytes) -> list[Texture]:
    """Decode a texture table; the pixel format follows from bytes per pixel (0.5 CMPR / CI4,
    1 CI8 / I8, 2 RGB5A3, 4 RGBA8) with the palette (RGB5A3) at each entry's palette offset."""
    entries = _entries(pay)
    out: list[Texture] = []
    for k, (code, off, w, h, pal, name) in enumerate(entries):
        end = len(pay)
        if k + 1 < len(entries):
            nxt = entries[k + 1]
            end = nxt[4] if 0 < nxt[4] < nxt[1] else nxt[1]
        avail = max(end - off, 0)
        per = avail / (w * h)
        tex = Texture(name, w, h, code, None)
        out.append(tex)
        low = code & 0xF
        palette = None
        if per >= 4:
            fmt = 6
        elif per >= 2:
            fmt = 5
        elif per >= 1:
            fmt = 9 if (pal or low == 9) else 1
        elif per >= 0.5:
            fmt = 8 if (pal or low == 8) else 14
        else:
            continue
        if fmt in (8, 9):
            n = 16 if fmt == 8 else 256
            p = pal or off - 2 * n
            if p < 0 or p + 2 * n > len(pay):
                continue
            palette = gx_texture.decode_palette(2, pay[p : p + 2 * n], n)
        try:
            tex.rgba = gx_texture.decode(fmt, w, h, pay[off:end], palette)
        except ValueError:
            continue
    return out


def texture(pay: bytes) -> Texture | None:
    found = textures(pay)
    return found[0] if found else None


def is_material_list(pay: bytes) -> bool:
    """``u16 version (2-8) | u16 1 | u32 header size (0xc / 0x10 / 0x14) | ...``."""
    return (
        len(pay) >= 0x20
        and pay[0] == 0
        and 2 <= pay[1] <= 8
        and pay[2:4] == b"\x00\x01"
        and pay[4:7] == b"\x00\x00\x00"
        and pay[7] in (0x0C, 0x10, 0x14)
    )


def material_names(pay: bytes) -> list[str]:
    return [m.group(0).decode("latin-1") for m in _NAME.finditer(pay, 0xC)]


def models(data: bytes) -> list[Model]:
    """Group a DBL / DBU into models: textures, material list, mesh records."""
    out: list[Model] = []
    cur: Model | None = None
    for b in dbl.blocks(data):
        pay = data[b.offset + 0x40 : b.offset + 0x40 + b.size]
        if b.kind == 0xB:
            cur = None
            continue
        if b.kind != 0xE:
            continue
        rtype = record_type(data, b)
        if cur is None:
            cur = Model()
            out.append(cur)
        if rtype in (0x82, 0x86) and is_texture(pay):
            cur.textures.extend(textures(pay))
        elif rtype == 0x67 and is_material_list(pay):
            cur.materials.extend(material_names(pay))
        elif is_mesh(pay):
            rec = parse(pay)
            if rec is not None and rec.meshes:
                cur.records.append(rec)
    return [m for m in out if m.records or m.textures]
