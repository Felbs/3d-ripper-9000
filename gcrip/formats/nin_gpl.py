"""Nintendo Dolphin SDK character pipeline geometry palettes (``.gpl``): the ``GeoPalette`` /
``DisplayObject`` files of Harvest Moon: A Wonderful Life, Zatch Bell!, Def Jam Vendetta,
Doshin the Giant, Lotus Challenge, Ultimate Muscle, Swingerz Golf ...

The layout follows the SDK's ``charPipeline/GeoPalette.h`` and ``DisplayObject.h``; every
pointer inside a display object is an offset **from that display object**, the palette's
own two pointers count from the file start::

    GEOPalette     u32 version (0x005bbc61 / 0x00b749e0), u32 user data size, ptr user data,
                   u32 descriptors, ptr descriptor array
    GEODescriptor  ptr display object, ptr name
    DOLayout       ptr position header, ptr colour header, ptr texture header, ptr lighting
                   header, ptr display header, u8 texture channels, u8, u16
    array header   ptr array, u16 count, u8 quantize (type << 4 | fraction bits), u8
                   components - positions and normals share one interleaved array
                   (6 components each, the normals 6 bytes in); the texture header adds
                   ptr palette name (``<stem>.tpl``), ptr runtime palette
    DODisplayHeader ptr primitive bank, ptr state list, u16 states
    DODisplayState u8 id (1 texture: setting low byte = TPL index; vertex descriptor - id 2
                   on 0x005bbc61 files, 3 on 0x00b749e0 ones: two bits an attribute in GX
                   order - position matrix, position, normal, colour 0, colour 1, texcoord
                   0..7: 2 index8, 3 index16; the other id is the matrix load), u8, u16,
                   u32 setting, ptr GX display list, u32 bytes

The display lists run under the state that precedes them; the corners hold one index per
indexed attribute in GX order.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import j3d

VERSIONS = (0x005BBC61, 0x00B749E0)
STATE_TEXTURE = 1
# the vertex-descriptor state id moved between SDK releases: 3 on the 0x00b749e0 files
# (Doshin the Giant, Def Jam Vendetta ...), 2 on the 0x005bbc61 ones (Harvest Moon ...)
STATE_VCD = {0x005BBC61: 2, 0x00B749E0: 3}
GX_TYPES = {0: "u1", 1: "i1", 2: ">u2", 3: ">i2", 4: ">f4"}
COLOR_SIZES = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}  # GX_RGB565 .. GX_RGBA8
MAX_COUNT = 1 << 16
PRIM_OPS = (0x80, 0x90, 0x98, 0xA0)


class GplError(ValueError):
    pass


@dataclass
class Draw:
    texture: int | None  # index into the TPL, None when no texture state was set
    positions: np.ndarray  # (N,3) f32 per corner
    triangles: np.ndarray  # (T,3)
    normals: np.ndarray | None
    colors: np.ndarray | None
    uvs: np.ndarray | None


@dataclass
class DisplayObject:
    name: str
    tpl: str | None
    draws: list[Draw]


@dataclass
class Palette:
    objects: list[DisplayObject]
    warnings: list[str] = field(default_factory=list)


def is_gpl(head: bytes, size: int) -> bool:
    if len(head) < 20 or size < 24:
        return False
    version, _uds, _ud, count, table = struct.unpack_from(">5I", head, 0)
    return version in VERSIONS and 0 < count <= MAX_COUNT and 20 <= table < size


def _cstr(d: bytes, at: int) -> str:
    end = d.find(b"\0", at)
    return d[at : end if end >= 0 else len(d)].decode("latin-1", "replace")


def _array(d: bytes, base: int, hdr: int, warn: list[str]):
    """(values (count, comps) as float / u8, count) of an array header, or None."""
    if hdr + 8 > len(d):
        return None
    at, count, quant, comps = struct.unpack_from(">IHBB", d, hdr)
    if count == 0 or comps == 0:
        return None
    at += base
    kind = quant >> 4
    frac = quant & 15
    return at, count, kind, frac, comps


def _load(d: bytes, spec, comps_out: int, warn: list[str], what: str) -> np.ndarray | None:
    at, count, kind, frac, comps = spec
    dtype = GX_TYPES.get(kind)
    if dtype is None:
        warn.append(f"{what}: component type {kind}")
        return None
    size = np.dtype(dtype).itemsize
    stride = size * comps
    if at + stride * count > len(d):
        warn.append(f"{what}: array past the file")
        return None
    rows = np.frombuffer(d, np.uint8, stride * count, at).reshape(count, stride)
    vals = np.frombuffer(np.ascontiguousarray(rows[:, : size * comps_out]).tobytes(), dtype)
    vals = vals.reshape(count, comps_out).astype(np.float32)
    if kind != 4:
        vals /= float(1 << frac)
    return vals


def _colors(d: bytes, spec, warn: list[str]) -> np.ndarray | None:
    at, count, kind, _frac, comps = spec
    size = COLOR_SIZES.get(kind)
    if size is None:
        warn.append(f"colours: format {kind}")
        return None
    if at + size * count > len(d):
        warn.append("colours: array past the file")
        return None
    raw = np.frombuffer(d, np.uint8, size * count, at).reshape(count, size)
    out = np.full((count, 4), 255, np.uint8)
    if kind in (1, 4):  # RGB8 / RGBA6 (packed as 3 bytes)
        out[:, :3] = raw[:, :3]
    elif kind in (2, 5):  # RGBX8 / RGBA8
        out[:, :3] = raw[:, :3]
        if kind == 5:
            out[:, 3] = raw[:, 3]
    else:
        v = (raw[:, 0].astype(np.uint16) << 8) | raw[:, 1]
        if kind == 0:  # RGB565
            out[:, 0] = ((v >> 11) & 31) * 255 // 31
            out[:, 1] = ((v >> 5) & 63) * 255 // 63
            out[:, 2] = (v & 31) * 255 // 31
        else:  # RGBA4
            out[:, 0] = ((v >> 12) & 15) * 17
            out[:, 1] = ((v >> 8) & 15) * 17
            out[:, 2] = ((v >> 4) & 15) * 17
            out[:, 3] = (v & 15) * 17
    return out


def _vcd_widths(setting: int) -> list[tuple[str, int]]:
    """(attribute, index width) in GX order from a vertex-descriptor state."""
    names = [
        "pnmtx",
        "pos",
        "nrm",
        "clr0",
        "clr1",
        "tex0",
        "tex1",
        "tex2",
        "tex3",
        "tex4",
        "tex5",
        "tex6",
        "tex7",
    ]
    out = []
    for k, name in enumerate(names):
        mode = (setting >> (2 * k)) & 3
        if mode == 0:
            continue
        out.append((name, {1: 1, 2: 1, 3: 2}[mode]))
    return out


def _display_list(d: bytes, at: int, size: int, widths, warn: list[str]):
    """(attribute -> per-corner index arrays, triangles) for one GX list."""
    stride = sum(w for _, w in widths)
    end = min(len(d), at + size)
    p = at
    cols: dict[str, list[np.ndarray]] = {n: [] for n, _ in widths}
    tris = []
    base = 0
    while p + 3 <= end:
        op = d[p]
        if op == 0:
            p += 1
            continue
        if (op & 0xF8) not in PRIM_OPS:
            break
        count = (d[p + 1] << 8) | d[p + 2]
        if count == 0 or p + 3 + count * stride > end:
            break
        rows = np.frombuffer(d, np.uint8, count * stride, p + 3).reshape(count, stride)
        q = 0
        for name, w in widths:
            v = (
                rows[:, q].astype(np.int64)
                if w == 1
                else (rows[:, q].astype(np.int64) << 8) | rows[:, q + 1]
            )
            cols[name].append(v)
            q += w
        t = j3d.triangulate(op & 0xF8, count)
        if len(t):
            tris.append(t + base)
        base += count
        p += 3 + count * stride
    if not tris:
        return None, None
    return {n: np.concatenate(v) for n, v in cols.items()}, np.concatenate(tris)


def _descriptors(d: bytes) -> tuple[int, int]:
    """(count, table) of the descriptor array.  Two headers exist under the same version:
    the SDK's ``version, user data size, user data, count, table`` and Kuju's (Lotus
    Challenge) ``version, materials, material table, user data size, user data, count,
    table`` - told apart by which table holds pointers into the file."""
    words = struct.unpack_from(">5I", d, 0)
    count, table = words[3], words[4]
    if 0 < count <= MAX_COUNT and table >= 20 and table + 8 <= len(d):
        obj, name_at = struct.unpack_from(">II", d, table)
        if 0 < obj < len(d) and 0 < name_at < len(d):
            return count, table
    if len(d) >= 28:
        count, table = struct.unpack_from(">II", d, 20)
        if 0 < count <= MAX_COUNT and table >= 28 and table + 8 <= len(d):
            raise GplError("Kuju's material-first layout (Lotus Challenge) is not read")
    raise GplError("no descriptor table")


def parse(d: bytes) -> Palette:
    version = struct.unpack_from(">I", d, 0)[0]
    if version not in VERSIONS:
        raise GplError(f"version {version:#x}")
    count, table = _descriptors(d)
    pal = Palette([])
    warn = pal.warnings
    for i in range(min(count, MAX_COUNT)):
        at = table + 8 * i
        if at + 8 > len(d):
            break
        obj, name_at = struct.unpack_from(">II", d, at)
        name = _cstr(d, name_at) if name_at < len(d) else f"object_{i}"
        if obj + 0x20 > len(d):
            warn.append(f"{name}: display object past the file")
            continue
        # Kuju's display object carries two more pointers before the channel word; the five
        # geometry pointers sit first in both layouts
        p_pos, p_clr, p_tex, p_lit, p_disp = struct.unpack_from(">5I", d, obj)
        base = obj
        pos_spec = _array(d, base, base + p_pos, warn) if p_pos else None
        clr_spec = _array(d, base, base + p_clr, warn) if p_clr else None
        tex_spec = _array(d, base, base + p_tex, warn) if p_tex else None
        lit_spec = _array(d, base, base + p_lit, warn) if p_lit else None
        tpl = None
        if p_tex and base + p_tex + 16 <= len(d):
            name_ptr = struct.unpack_from(">I", d, base + p_tex + 8)[0]
            if name_ptr and base + name_ptr < len(d):
                tpl = _cstr(d, base + name_ptr)
        positions = _load(d, pos_spec, 3, warn, f"{name} positions") if pos_spec else None
        normals = _load(d, lit_spec, 3, warn, f"{name} normals") if lit_spec else None
        colors = _colors(d, clr_spec, warn) if clr_spec else None
        uvs = _load(d, tex_spec, 2, warn, f"{name} texcoords") if tex_spec else None
        if positions is None or not p_disp or base + p_disp + 10 > len(d):
            warn.append(f"{name}: no positions or display data")
            continue
        _bank, states, nstates = struct.unpack_from(">IIH", d, base + p_disp)
        draws: list[Draw] = []
        texture = None
        widths = None
        for k in range(min(nstates, MAX_COUNT)):
            st = base + states + 16 * k
            if st + 16 > len(d):
                break
            sid, _p8, _p16, setting, plist, lsize = struct.unpack_from(">BBHIII", d, st)
            if sid == STATE_TEXTURE:
                texture = setting & 0xFF
            elif sid == STATE_VCD[version]:
                widths = _vcd_widths(setting)
            if lsize and widths:
                cols, tri = _display_list(d, base + plist, lsize, widths, warn)
                if cols is None:
                    continue
                pi = cols.get("pos")
                if pi is None or pi.max() >= len(positions):
                    warn.append(f"{name}: corner index outside {len(positions)} positions")
                    continue

                def pick(arr, key, cols=cols):
                    idx = cols.get(key)
                    if arr is None or idx is None or idx.max() >= len(arr):
                        return None
                    return arr[idx]

                draws.append(
                    Draw(
                        texture,
                        positions[pi],
                        tri,
                        pick(normals, "nrm"),
                        pick(colors, "clr0"),
                        pick(uvs, "tex0"),
                    )
                )
        if draws:
            pal.objects.append(DisplayObject(name, tpl, draws))
        else:
            warn.append(f"{name}: no display lists")
    return pal
