"""Unreal Engine 2 packages as shipped on GameCube (Ubisoft: Splinter Cell 1 / Pandora
Tomorrow / Chaos Theory / Double Agent, Rainbow Six 3, Ghost Recon 2, XIII) - big-endian
package headers, name / import / export tables and the compact-index encoding.

Header: ``u32 magic 0x9E2A83C1 | u16 licensee << 16 | u16 version | u32 flags | u32 name
count | u32 name offset | u32 export count | u32 export offset | u32 import count | u32
import offset | GUID ...``.  Names: ``u8 length (with NUL) | chars | u32 flags``.  Imports:
``index class package | index class name | i32 package object | index object name``.
Exports: ``index class | index super | i32 package | index name | u32 flags | index size |
index offset``.  Object indexes are UE's compact signed ints; > 0 = export n-1, < 0 =
import -n-1.  Compact index: first byte sign 0x80 / more 0x40 / 6 bits, then
7-bit bytes with more 0x80.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"\x9e\x2a\x83\xc1"
MAGIC_LE = MAGIC[::-1]


@dataclass
class Import:
    class_package: str
    class_name: str
    package: int
    name: str


@dataclass
class Export:
    cls: int  # object index
    super: int
    package: int
    name: str
    flags: int
    size: int
    offset: int
    class_name: str = ""
    package_name: str = ""


@dataclass
class Package:
    version: int
    licensee: int
    order: str = ">"
    names: list[str] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    exports: list[Export] = field(default_factory=list)


class Reader:
    __slots__ = ("d", "p", "o")

    def __init__(self, d: bytes, p: int = 0, order: str = ">"):
        self.d = d
        self.p = p
        self.o = order

    def u8(self) -> int:
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from(self.o + "H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from(self.o + "I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from(self.o + "i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from(self.o + "f", self.d, self.p)[0]
        self.p += 4
        return v

    def index(self) -> int:
        """UE compact index: first byte = sign (0x80) | more (0x40) | 6 data bits, then up to
        four bytes of more (0x80) | 7 data bits."""
        b = self.u8()
        neg = b & 0x80
        v = b & 0x3F
        if b & 0x40:
            shift = 6
            for _ in range(4):
                b = self.u8()
                v |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        return -v if neg else v

    def fstring(self) -> str:
        n = self.index()
        if n <= 0:
            return ""
        s = self.d[self.p : self.p + n - 1]
        self.p += n
        return s.decode("latin-1", "replace")

    def name(self, pkg: Package) -> str:
        i = self.index()
        if 0 <= i < len(pkg.names):
            return pkg.names[i]
        return f"name{i}"


def is_package(head: bytes) -> bool:
    return head[:4] in (MAGIC, MAGIC_LE)


def parse(d: bytes) -> Package:
    order = "<" if d[:4] == MAGIC_LE else ">"
    r = Reader(d, 0, order)
    if r.u32() != 0x9E2A83C1:
        raise ValueError("not an Unreal package")
    vl = r.u32()
    pkg = Package(version=vl & 0xFFFF, licensee=vl >> 16)
    _flags = r.u32()
    n_names, o_names, n_exports, o_exports, n_imports, o_imports = (r.u32() for _ in range(6))
    if max(n_names, n_exports, n_imports) > 1_000_000 or max(o_names, o_exports, o_imports) > len(
        d
    ):
        raise ValueError("implausible package header")
    pkg.order = order
    r.p = o_names
    for _ in range(n_names):
        length = r.index()
        s = d[r.p : r.p + max(length - 1, 0)].decode("latin-1", "replace")
        r.p += max(length, 0)
        r.u32()  # flags
        pkg.names.append(s)
    r.p = o_imports
    for _ in range(n_imports):
        cp = r.name(pkg)
        cn = r.name(pkg)
        pk = r.i32()
        nm = r.name(pkg)
        pkg.imports.append(Import(cp, cn, pk, nm))
    r.p = o_exports
    for _ in range(n_exports):
        cls = r.index()
        sup = r.index()
        pk = r.i32()
        nm = r.name(pkg)
        fl = r.u32()
        size = r.index()
        off = r.index() if size else 0
        pkg.exports.append(Export(cls, sup, pk, nm, fl, size, off))
    for e in pkg.exports:
        e.class_name = object_name(pkg, e.cls) or "Class"
        e.package_name = object_name(pkg, e.package)
    return pkg


def object_name(pkg: Package, index: int) -> str:
    if index > 0 and index - 1 < len(pkg.exports):
        return pkg.exports[index - 1].name
    if index < 0 and -index - 1 < len(pkg.imports):
        return pkg.imports[-index - 1].name
    return ""


def full_name(pkg: Package, index: int) -> str:
    """Outer.Outer.Name for an export / import index."""
    parts = []
    guard = 0
    while index and guard < 16:
        guard += 1
        if index > 0 and index - 1 < len(pkg.exports):
            e = pkg.exports[index - 1]
            parts.append(e.name)
            index = e.package
        elif index < 0 and -index - 1 < len(pkg.imports):
            i = pkg.imports[-index - 1]
            parts.append(i.name)
            index = i.package
        else:
            break
    return ".".join(reversed(parts))


# -- object serialization ------------------------------------------------------------


def read_props(r: Reader, pkg: Package) -> list[tuple]:
    """Tagged property list up to the terminating ``None``: (name, type, struct, size,
    array index, value) tuples.  Type codes: 1 byte, 2 int, 3 bool (value in bit 7 of the
    info byte, no payload), 4 float, 5 object, 6 name, 10 struct, 13 str, 9 array..."""
    out = []
    for _ in range(4096):
        name = r.name(pkg)
        if name == "None":
            break
        info = r.u8()
        ptype = info & 0xF
        size_code = (info >> 4) & 7
        is_array = bool(info & 0x80)
        struct_name = r.name(pkg) if ptype == 10 else None
        size = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}.get(size_code)
        if size is None:
            size = r.u8() if size_code == 5 else (r.u16() if size_code == 6 else r.u32())
        if ptype == 3:  # bool: the value is bit 7 of the info byte, the size field is 0
            out.append((name, ptype, struct_name, 0, 0, is_array))
            r.p += size
            continue
        idx = 0
        if is_array:
            idx = r.u8()
            if idx & 0x80:
                if idx & 0x40:
                    idx = ((idx & 0x3F) << 24) | (r.u8() << 16) | (r.u8() << 8) | r.u8()
                else:
                    idx = ((idx & 0x3F) << 8) | r.u8()
        start = r.p
        if ptype == 4:
            val = r.f32()
        elif ptype == 2:
            val = r.i32()
        elif ptype == 5:
            val = r.index()
        elif ptype == 6:
            val = r.name(pkg)
        elif ptype == 1:
            val = r.u8()
        elif ptype == 13:
            val = r.fstring()
        else:
            val = r.d[start : start + size]
        r.p = start + size
        out.append((name, ptype, struct_name, size, idx, val))
    return out


@dataclass
class Section:
    first_index: int
    min_vertex: int
    max_vertex: int
    faces: int
    triangles: int
    material: int  # object index (import < 0)


@dataclass
class StaticMesh:
    name: str
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    indices: np.ndarray  # strip
    sections: list[Section]


@dataclass
class TextureData:
    name: str
    width: int
    height: int
    fmt: int  # 0 P8, 3 DXT1, 5 RGBA8, 7 DXT3, 8 DXT5
    data: bytes
    palette: int = 0  # object index of the Palette


def static_mesh(pkg: Package, d: bytes, e: Export) -> StaticMesh | None:
    """Ubisoft's simplified UE2 StaticMesh (Splinter Cell family, version 102 / licensee
    33): properties (Materials array), bounding box (f32[6] + u8), sphere (f32[4]), then
    ``index n`` 32-byte vertices ``f32 pos[3] | f32 normal[3] | f32 uv[2]``, ``u32 2 | index
    n`` u16 strip indices, ``u32 4 | index n`` u16 wireframe edges and ``u32 2 | index n``
    sections ``u32 | u16 first index | u16 min vertex | u16 max vertex | u16 faces | u16
    strip triangles | u32 | index material``."""
    o = pkg.order
    r = Reader(d, e.offset, o)
    end = e.offset + e.size
    read_props(r, pkg)
    r.p += 25 + 16
    n = r.index()
    if n <= 0 or r.p + n * 32 > end:
        return None
    verts = np.frombuffer(d, o + "f4", n * 8, r.p).reshape(n, 8).astype(np.float32)
    r.p += n * 32
    r.u32()
    ni = r.index()
    if ni <= 0 or r.p + ni * 2 > end:
        return None
    idx = np.frombuffer(d, o + "u2", ni, r.p).astype(np.uint32)
    r.p += ni * 2
    r.u32()
    nw = r.index()
    r.p += max(nw, 0) * 2
    r.u32()
    ns = r.index()
    sections = []
    for _ in range(max(0, min(ns, 4096))):
        if r.p + 18 > end:
            break
        r.u32()
        fi, mn, mx, faces, tris = (r.u16() for _ in range(5))
        r.u32()
        mat = r.index()
        sections.append(Section(fi, mn, mx, faces, tris, mat))
    return StaticMesh(e.name, verts[:, :3], verts[:, 3:6], verts[:, 6:8], idx, sections)


def texture(pkg: Package, d: bytes, e: Export) -> TextureData | None:
    """UE2 Texture: properties (Format, USize, VSize, Palette) then ``index mips``, each
    ``u32 skip | index size | data | u32 usize | u32 vsize | u8 ubits | u8 vbits``."""
    r = Reader(d, e.offset, pkg.order)
    end = e.offset + e.size
    props = {p[0]: p[5] for p in read_props(r, pkg)}
    fmt = int(props.get("Format", 0) or 0)
    usize = int(props.get("USize", 0) or 0)
    vsize = int(props.get("VSize", 0) or 0)
    palette = int(props.get("Palette", 0) or 0)
    mips = r.index()
    if mips <= 0 or r.p + 8 > end:
        return None
    r.u32()
    size = r.index()
    if size < 0 or r.p + size > end:
        return None
    data = d[r.p : r.p + size]
    r.p += size
    if r.p + 8 <= end:
        w, h = r.u32(), r.u32()
        if 0 < w <= 4096 and 0 < h <= 4096:
            usize, vsize = w, h
    return TextureData(e.name, usize, vsize, fmt, data, palette)


def palette(pkg: Package, d: bytes, e: Export) -> np.ndarray | None:
    """UE2 Palette: properties then ``index count`` BGRA colours."""
    r = Reader(d, e.offset, pkg.order)
    read_props(r, pkg)
    n = r.index()
    if n <= 0 or r.p + n * 4 > e.offset + e.size:
        return None
    pal = np.frombuffer(d, np.uint8, n * 4, r.p).reshape(n, 4)[:, [2, 1, 0, 3]]
    return pal.astype(np.uint8)


def texture_rgba(tex: TextureData, pal: np.ndarray | None = None) -> np.ndarray | None:
    from gcrip.formats import dxt

    w, h = tex.width, tex.height
    try:
        if tex.fmt == 3 and len(tex.data) >= max(w // 4, 1) * max(h // 4, 1) * 8:
            return dxt.decode(tex.data, w, h, "DXT1")
        if tex.fmt == 7 and len(tex.data) >= max(w // 4, 1) * max(h // 4, 1) * 16:
            return dxt.decode(tex.data, w, h, "DXT3")
        if tex.fmt == 8 and len(tex.data) >= max(w // 4, 1) * max(h // 4, 1) * 16:
            return dxt.decode(tex.data, w, h, "DXT5")
        if tex.fmt == 5 and len(tex.data) >= w * h * 4:
            return (
                np.frombuffer(tex.data, np.uint8, w * h * 4)
                .reshape(h, w, 4)[:, :, [2, 1, 0, 3]]
                .copy()
            )
        if tex.fmt == 0 and pal is not None and len(tex.data) >= w * h:
            idx = np.frombuffer(tex.data, np.uint8, w * h).reshape(h, w)
            return pal[np.minimum(idx, len(pal) - 1)]
    except (ValueError, IndexError):
        return None
    return None
