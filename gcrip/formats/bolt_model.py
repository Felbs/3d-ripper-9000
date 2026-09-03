"""Mass Media models and material lists inside ``BOLT`` archives (Muppets Party Cruise,
Shrek Super Party, Pac-Man Fever).

Read from ``Muppets.elf`` (``MMI::MATERIALLIST::LoadNode``, ``MMI::MESH::Load``,
``MMI::MATERIALLIST::LoadMaterials``, ``MMI::TEXTURE::CreateBuffer``) and from the Shrek and
Pac-Man DOLs, which carry the same functions without names.  Every member opens on a four-byte
version - ``01 09 00 15`` is 1.9 revision 21 - followed by a u8-length group name for a model or
a u32 string-pool size for a material list.  Big-endian.

Two generations of the "distill" exporter are on disc:

* **1.9** (Muppets 1.9.21, Shrek 1.9.18; the Pac-Man DOL wants 1.9.12): the node tree below,
  meshes with fixed-point arrays and a declared corner width, materials with layers.
* **1.3** (Pac-Man Fever's two FST-visible archives): nodes chained by child / sibling flag
  bytes, float arrays, no corner width, an inline-string material list.  The Pac-Man DOL
  loads only 1.9, so these archives are leftovers; the game's real data sits outside the FST.

Model member (1.9)::

  tag, u8 n, name[n]                    "Data_BBoard0_Board0_GCN"
  node                                  recursive

  node := u8 type, body, u16 children, children x node
    0 NODE         -
    1 ANIM         name[16], f32[16] matrix, 12, u16 channels, u8[3], u8 mode,
                   channels x (u16 keys, keys x 32 (mode 0) | 0x34 (mode 1))
    2 ANIMCONTROL  u16, name[16]
    3 BBOX         f32[6], 12, 4
    4 MESH         MESH::Load stream (below)
    5 OBJECT       name[16], u8[4], f32[16] matrix, 12
    7 SKIN         u8
    8 LOD          -

  1.3: node := u8 type, body, u8 child flag (+ node), u8 sibling flag (+ node); ANIM has
  no mode byte (u16 channels, u8, channels x (u16 keys, keys x 32)), ANIMCONTROL has no
  body, OBJECT has one flag byte, and 6 LIGHT is 16 bytes plus a single next-node flag.

Matrices are row vectors with the translation in the last row; a mesh is in the space of
the nearest OBJECT / ANIM above it and those nest.

Mesh stream (``MESH::Load``, 1.9)::

  u16 faces, u16 material (& 0xfff; 0xffff none), u16 n, name[n], u16 flags, u16 vertexType,
  u8 vertexSize, u8 posFrac, u8 nrmFrac, u8 texFrac,
  u16 npos,  npos x (f32[3] if VT & 1 else s16[3] / 2^posFrac)
  u16 nnrm,  nnrm x (s8[3] if VT & 2, s16[3] if VT & 4, else f32[3]; / 2^nrmFrac)
  u16 nclr,  nclr x (2 bytes for VT & 0x70 in (0x10, 0x20), 4 for 0x60)
  u16 ntex,  ntex x (s16[2] if VT & 8 else s8[2]; / 2^texFrac)
  u32 size,  GX display list: u8 opcode (0x80/0x90/0x98/0xa0 | VAT), u16 count, count x corner
  u8 skinned; if 1: u16 n, n x f32[3]; u16 n, n x f32[3]; u8 weights; n*4*weights; n*(weights+1)

A corner is pos index, nrm index (when nnrm), colour (index when nclr, else direct 2 or 4
bytes per the 0x70 bits), tex index (when ntex); an index is a byte unless its array has
more than 256 entries.  ``vertexSize`` is that width and is checked.

  1.3: u16 faces, u16 material, u16 n, name[n], u16 vertexType, u16 npos x f32[3],
  u16 nnrm x f32[3], u16 nclr x RGBA8, u16 ntex x f32[2], u32 size, display list, u8 skinned;
  VT & 1 widens every index to u16, bits 2 / 4 / 8 mark normals / colours / UVs present.

Material list member::

  1.9.21  tag, u32 pool size, pool (NUL strings: list name, texture names, material names),
          u32, u16 nmaterials, u16 nlayers, u16 ntextures, textures, materials
  1.9.18  tag, u32 pool size, pool, u32, u16 ntextures, textures, u16 nmaterials, materials
  texture:  u16 w, u16 h, u8, u8 type, u8 mips, u32 size, [u8 if type in 2 3 4], pixels,
            type 3: u16, 512-byte palette; type 4: u16, 32-byte palette
            type 5 CMPR, 0 RGBA8, 2 RGB5A3, 3 C8 + RGB5A3 palette, 4 C4 + RGB5A3 palette
  material 1.9.21: u8, u8 nlayers, nlayers x (u8 flags, f32[3], u32, u32, u16 ntex,
            ntex x u16 texture index | f32[4] colour when ntex == 0)
  material 1.9.18: u8 flags, f32[4], f32[4], u32, u32, u16 n, n x u16, u16 n, n x u16
  1.3     tag, u8 n, name[n], u16 ntextures, textures (u16 n, name[n], u16 w, u16 h, u8,
          u8 type, [u8 for type 3 4], u8 mips, the mip chain, [u16 size, palette]),
          u16 nmaterials, materials (u16 n, name[n], u16 ntex, ntex x u16)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from gcrip.formats import gx_texture

TAG = bytes((1, 9, 0, 0x15))  # Muppets Party Cruise; the tests build members with it
VERSIONS = {(1, 3), (1, 9)}
LAYERED_LISTS = 0x15  # 1.9 revisions from 21 carry the layer records
HEAD = 0x90  # enough of a member to tell a 1.3 material list from a model

NODE, ANIM, ANIMCONTROL, BBOX, MESH, OBJECT, LIGHT, SKIN, LOD = 0, 1, 2, 3, 4, 5, 6, 7, 8
NAME = 16

PRIMS = {0x80: "quads", 0x90: "triangles", 0x98: "strip", 0xA0: "fan"}

TEX_TYPES = {5: (0xE, 0), 0: (6, 0), 2: (5, 0), 3: (9, 256), 4: (8, 16)}
PALETTE_FMT = 2  # RGB5A3 (GXInitTlutObj format 2)


class BoltModelError(ValueError):
    pass


def version(head: bytes) -> tuple[int, int, int] | None:
    """(major, minor, revision) of a member, or None when the head is not one."""
    if len(head) < 8 or (head[0], head[1]) not in VERSIONS or head[2] != 0:
        return None
    return head[0], head[1], struct.unpack_from(">H", head, 2)[0]


def is_material_list(head: bytes) -> bool:
    v = version(head)
    if v is None:
        return False
    if v[1] == 3:
        # a 1.3 list opens like a model (u8-length name), then u16 textures and a
        # u16-length texture name; a model has a node type byte (< 9) there instead
        n = head[4]
        return 0 < n < 0x80 and len(head) > n + 8 and head[n + 5] == 0 and head[n + 7] == 0
    return head[4] == 0 and head[5] == 0


def is_model(head: bytes) -> bool:
    return version(head) is not None and 0 < head[4] < 0x80 and not is_material_list(head)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.d = data
        self.p = 0

    def need(self, n: int) -> None:
        if self.p + n > len(self.d):
            raise BoltModelError(
                f"member ends at {len(self.d)} inside a {n}-byte field at {self.p}"
            )

    def u8(self) -> int:
        self.need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from(">I", self.d, self.p)[0]
        self.p += 4
        return v

    def raw(self, n: int) -> bytes:
        self.need(n)
        v = self.d[self.p : self.p + n]
        self.p += n
        return v

    def name16(self) -> str:
        return self.raw(NAME).split(b"\0")[0].decode("latin-1")

    def matrix(self) -> np.ndarray:
        return np.frombuffer(self.raw(64), dtype=">f4").reshape(4, 4).astype(np.float32)


@dataclass
class Mesh:
    name: str
    material: int  # -1 none
    faces: int
    vertex_type: int
    positions: np.ndarray  # (N,3) f32, in the object's space
    indices: np.ndarray  # (M,) u32 triangles
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None
    skinned: bool
    node: str
    matrix: np.ndarray  # composed 4x4, row vectors


@dataclass
class Model:
    group: str
    name: str  # the first named node, normally the root object
    version: tuple[int, int, int] = (1, 9, 0x15)
    meshes: list[Mesh] = field(default_factory=list)
    nodes: list[tuple[int, int, str]] = field(default_factory=list)  # depth, type, name
    warnings: list[str] = field(default_factory=list)


def _corner_layout(
    vt: int, npos: int, nnrm: int, nclr: int, ntex: int, byte_max: int = 256
) -> list[tuple[str, int]]:
    layout = [("pos", 2 if npos > byte_max else 1)]
    if nnrm:
        layout.append(("nrm", 2 if nnrm > byte_max else 1))
    if nclr:
        layout.append(("clr", 2 if nclr > byte_max else 1))
    elif vt & 0x70:
        layout.append(("clr_direct", 4 if (vt & 0x70) == 0x60 else 2))
    if ntex:
        layout.append(("tex", 2 if ntex > byte_max else 1))
    return layout


def _colors(raw: bytes, vt: int) -> np.ndarray:
    kind = vt & 0x70
    if kind == 0x60:
        return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 4).copy()
    v = np.frombuffer(raw, dtype=">u2").astype(np.uint16)
    if kind == 0x10:
        return gx_texture._rgb565_to_rgba(v)
    # RGBA4
    r = ((v >> 12) & 0xF).astype(np.uint8)
    g = ((v >> 8) & 0xF).astype(np.uint8)
    b = ((v >> 4) & 0xF).astype(np.uint8)
    a = (v & 0xF).astype(np.uint8)
    return np.stack([(r << 4) | r, (g << 4) | g, (b << 4) | b, (a << 4) | a], axis=-1)


def _triangles(op: int, n: int) -> np.ndarray:
    if op == 0x90:
        return np.arange(n - n % 3).reshape(-1, 3)
    if op == 0x98:
        i = np.arange(max(n - 2, 0))
        b = np.where(i % 2 == 0, i + 1, i + 2)
        c = np.where(i % 2 == 0, i + 2, i + 1)
        return np.stack([i, b, c], axis=1)
    if op == 0xA0:
        i = np.arange(1, max(n - 1, 1))
        return np.stack([np.zeros_like(i), i, i + 1], axis=1)
    q = np.arange(n // 4) * 4
    return np.concatenate(
        [np.stack([q, q + 1, q + 2], axis=1), np.stack([q, q + 2, q + 3], axis=1)]
    )


def _read_mesh(r: _Reader, node: str, matrix: np.ndarray, warnings: list[str]) -> Mesh | None:
    faces = r.u16()
    material = r.u16()
    n = r.u16()
    name = r.raw(n).split(b"\0")[0].decode("latin-1")
    r.u16()  # flags
    vt = r.u16()
    vsize, pos_frac, nrm_frac, tex_frac = r.raw(4)
    npos = r.u16()
    if vt & 1:
        pos = np.frombuffer(r.raw(npos * 12), dtype=">f4").reshape(-1, 3).astype(np.float32)
    else:
        pos = np.frombuffer(r.raw(npos * 6), dtype=">i2").reshape(-1, 3).astype(np.float32) / float(
            1 << pos_frac
        )
    nnrm = r.u16()
    if vt & 2:
        nrm = np.frombuffer(r.raw(nnrm * 3), dtype=np.int8).reshape(-1, 3).astype(
            np.float32
        ) / float(1 << nrm_frac)
    elif vt & 4:
        nrm = np.frombuffer(r.raw(nnrm * 6), dtype=">i2").reshape(-1, 3).astype(np.float32) / float(
            1 << nrm_frac
        )
    else:
        nrm = np.frombuffer(r.raw(nnrm * 12), dtype=">f4").reshape(-1, 3).astype(np.float32)
    nclr = r.u16()
    kind = vt & 0x70
    clr_raw = r.raw(nclr * (4 if kind == 0x60 else 2)) if kind in (0x10, 0x20, 0x60) else b""
    ntex = r.u16()
    if vt & 8:
        uv = np.frombuffer(r.raw(ntex * 4), dtype=">i2").reshape(-1, 2).astype(np.float32) / float(
            1 << tex_frac
        )
    else:
        uv = np.frombuffer(r.raw(ntex * 2), dtype=np.int8).reshape(-1, 2).astype(
            np.float32
        ) / float(1 << tex_frac)
    dl = r.raw(r.u32())
    skinned = r.u8()
    if skinned == 1:
        n2 = r.u16()
        r.raw(n2 * 12)
        n3 = r.u16()
        r.raw(n3 * 12)
        weights = r.u8()
        if weights:
            r.raw(n2 * 4 * weights)
        r.raw(n2 * (weights + 1))
    if not npos or not dl:
        return None  # legitimate: an empty mesh (a placeholder object) has no vertices
    # no sample has an array of exactly 256 entries, so whether the encoder widens at 255
    # or 256 is settled per mesh by the vertexSize it declares
    layout = _corner_layout(vt, npos, nnrm, nclr, ntex)
    width = sum(w for _, w in layout)
    if width != vsize:
        layout = _corner_layout(vt, npos, nnrm, nclr, ntex, byte_max=255)
        width = sum(w for _, w in layout)
    if width != vsize:
        warnings.append(
            f"{name}: corner layout {layout} is {width} bytes against vertexSize {vsize}"
        )
        return None
    clr = _colors(clr_raw, vt) if nclr else np.zeros((0, 4), np.uint8)
    return _assemble(
        name,
        material,
        faces,
        vt,
        layout,
        dl,
        pos,
        nrm,
        uv,
        clr,
        node,
        matrix,
        warnings,
        skinned == 1,
    )


def _assemble(
    name: str,
    material: int,
    faces: int,
    vt: int,
    layout: list[tuple[str, int]],
    dl: bytes,
    pos: np.ndarray,
    nrm: np.ndarray,
    uv: np.ndarray,
    clr: np.ndarray,
    node: str,
    matrix: np.ndarray,
    warnings: list[str],
    skinned: bool = False,
) -> Mesh | None:
    """Corners of every primitive in the display list, resolved through the arrays."""
    width = sum(w for _, w in layout)
    corners: list[np.ndarray] = []
    tris: list[np.ndarray] = []
    base = 0
    p = 0
    while p + 3 <= len(dl):
        op = dl[p]
        if op == 0:
            break
        count = struct.unpack_from(">H", dl, p + 1)[0]
        if (op & 0xF8) not in PRIMS or p + 3 + count * width > len(dl):
            warnings.append(f"{name}: display list breaks at {p} (opcode {op:#x}, {count} corners)")
            break
        rec = np.frombuffer(dl[p + 3 : p + 3 + count * width], dtype=np.uint8).reshape(count, width)
        corners.append(rec)
        tris.append(_triangles(op & 0xF8, count) + base)
        base += count
        p += 3 + count * width
    if not corners:
        warnings.append(f"{name}: display list holds no primitive")
        return None
    rec = np.concatenate(corners)
    cols: dict[str, np.ndarray] = {}
    at = 0
    for key, w in layout:
        seg = rec[:, at : at + w]
        if key == "clr_direct":
            cols[key] = _colors(seg.tobytes(), vt)
        elif w == 2:
            cols[key] = seg[:, 0].astype(np.int64) << 8 | seg[:, 1]
        else:
            cols[key] = seg[:, 0].astype(np.int64)
        at += w
    for key, arr in (("pos", pos), ("nrm", nrm), ("tex", uv), ("clr", clr)):
        if key in cols and cols[key].max(initial=0) >= len(arr):
            warnings.append(f"{name}: {key} index {int(cols[key].max())} past {len(arr)} entries")
            return None
    idx = np.concatenate(tris).astype(np.uint32)
    pidx = cols["pos"]
    good = ~(
        (pidx[idx[:, 0]] == pidx[idx[:, 1]])
        | (pidx[idx[:, 1]] == pidx[idx[:, 2]])
        | (pidx[idx[:, 0]] == pidx[idx[:, 2]])
    )
    idx = idx[good]
    if not len(idx):
        warnings.append(f"{name}: every triangle is degenerate")
        return None
    colors = None
    if "clr_direct" in cols:
        colors = cols["clr_direct"]
    elif "clr" in cols:
        colors = clr[cols["clr"]]
    return Mesh(
        name=name,
        material=-1 if material == 0xFFFF else material & 0xFFF,
        faces=faces,
        vertex_type=vt,
        positions=pos[pidx],
        indices=idx.reshape(-1),
        normals=nrm[cols["nrm"]] if "nrm" in cols else None,
        uvs=uv[cols["tex"]] if "tex" in cols else None,
        colors=colors,
        skinned=skinned,
        node=node,
        matrix=matrix,
    )


def _read_mesh_13(r: _Reader, node: str, matrix: np.ndarray, warnings: list[str]) -> Mesh | None:
    """The 2002 stream: float arrays, RGBA8 colours, indices all a byte or all two."""
    faces = r.u16()
    material = r.u16()
    n = r.u16()
    name = r.raw(n).split(b"\0")[0].decode("latin-1")
    vt = r.u16()
    npos = r.u16()
    pos = np.frombuffer(r.raw(npos * 12), dtype=">f4").reshape(-1, 3).astype(np.float32)
    nnrm = r.u16()
    nrm = np.frombuffer(r.raw(nnrm * 12), dtype=">f4").reshape(-1, 3).astype(np.float32)
    nclr = r.u16()
    clr = np.frombuffer(r.raw(nclr * 4), dtype=np.uint8).reshape(-1, 4).copy()
    ntex = r.u16()
    uv = np.frombuffer(r.raw(ntex * 8), dtype=">f4").reshape(-1, 2).astype(np.float32)
    dl = r.raw(r.u32())
    skinned = r.u8()
    if skinned:
        raise BoltModelError(f"{name}: a skinned 1.3 mesh - not read yet")
    if not npos or not dl:
        return None  # legitimate: an empty mesh (a placeholder object) has no vertices
    w = 2 if vt & 1 else 1
    layout = [("pos", w)] + [(k, w) for k, c in (("nrm", nnrm), ("clr", nclr), ("tex", ntex)) if c]
    return _assemble(
        name, material, faces, vt, layout, dl, pos, nrm, uv, clr, node, matrix, warnings
    )


def _read_node(r: _Reader, model: Model, depth: int, node: str, matrix: np.ndarray) -> None:
    if depth > 64:
        raise BoltModelError("node tree deeper than 64")
    old = model.version[1] == 3
    t = r.u8()
    name = ""
    if t in (NODE, LOD):
        pass
    elif t == ANIM:
        name = r.name16()
        matrix = r.matrix() @ matrix
        r.raw(12)
        channels = r.u16()
        if old:
            r.raw(1)
            mode = 0
        else:
            r.raw(3)
            mode = r.u8()
        if mode not in (0, 1):
            raise BoltModelError(f"animation mode {mode}")
        for _ in range(channels):
            keys = r.u16()
            r.raw(keys * (32 if mode == 0 else 0x34))
        node = name or node
    elif t == ANIMCONTROL:
        if not old:
            r.u16()
            name = r.name16()
    elif t == BBOX:
        r.raw(0x18 + 12 + 4)
    elif t == MESH:
        read = _read_mesh_13 if old else _read_mesh
        mesh = read(r, node, matrix, model.warnings)
        if mesh is not None:
            model.meshes.append(mesh)
    elif t == OBJECT:
        name = r.name16()
        r.raw(1 if old else 4)
        matrix = r.matrix() @ matrix
        r.raw(12)
        node = name or node
    elif t == LIGHT and old:
        r.raw(16)
        model.nodes.append((depth, t, name))
        if r.u8():
            _read_node(r, model, depth + 1, node, matrix)
        return
    elif t == SKIN:
        r.u8()
    else:
        raise BoltModelError(f"node type {t} at {r.p - 1}")
    model.nodes.append((depth, t, name))
    if name and not model.name:
        model.name = name.rstrip(".")
    if old:
        # LoadNode 1.3: a flag byte then the child subtree, a flag byte then the sibling
        if r.u8():
            _read_node(r, model, depth + 1, node, matrix)
        if r.u8():
            _read_node(r, model, depth, node, matrix)
        return
    children = r.u16()
    for _ in range(children):
        _read_node(r, model, depth + 1, node, matrix)


def parse(data: bytes) -> Model:
    """The node tree of a model member; meshes carry the composed matrix of their object."""
    if not is_model(data[:HEAD]):
        raise BoltModelError("not a BOLT model member")
    r = _Reader(data)
    v = version(data[:8])
    r.raw(4)
    group = r.raw(r.u8()).decode("latin-1")
    model = Model(group=group, name="", version=v)
    _read_node(r, model, 0, "", np.eye(4, dtype=np.float32))
    if r.p != len(data):
        model.warnings.append(f"{len(data) - r.p} bytes after the node tree")
    return model


def transform(mesh: Mesh) -> tuple[np.ndarray, np.ndarray | None]:
    """Positions and normals in the model's space."""
    m = mesh.matrix
    pos = mesh.positions @ m[:3, :3] + m[3, :3]
    nrm = None
    if mesh.normals is not None:
        nrm = mesh.normals @ m[:3, :3]
        n = np.linalg.norm(nrm, axis=1)
        n[n == 0] = 1.0
        nrm = nrm / n[:, None]
    return pos.astype(np.float32), None if nrm is None else nrm.astype(np.float32)


# ---------------------------------------------------------------- material lists


@dataclass
class Texture:
    name: str
    width: int
    height: int
    kind: int
    mips: int
    pixels: bytes
    palette: bytes | None

    def decode(self) -> np.ndarray:
        fmt, entries = TEX_TYPES[self.kind]
        pal = None
        if entries:
            if self.palette is None:
                raise BoltModelError(f"{self.name}: palette texture without a palette")
            pal = gx_texture.decode_palette(PALETTE_FMT, self.palette, entries)
        need = gx_texture.encoded_size(fmt, self.width, self.height)
        # a 64x4 level is stored at its true 128 bytes, not the tile-rounded 256
        if len(self.pixels) * 8 < self.width * self.height * gx_texture.BITS_PER_PIXEL[fmt]:
            raise BoltModelError(
                f"{self.name}: {len(self.pixels)} bytes for a {self.width}x{self.height} level"
            )
        return gx_texture.decode(fmt, self.width, self.height, self.pixels[:need], pal)


@dataclass
class Layer:
    flags: int
    textures: list[int]
    color: tuple[float, float, float, float] | None


@dataclass
class Material:
    name: str
    layers: list[Layer]

    @property
    def texture(self) -> int | None:
        for layer in self.layers:
            if layer.textures:
                return layer.textures[0]
        return None

    @property
    def color(self) -> tuple[float, float, float, float] | None:
        for layer in self.layers:
            if layer.color is not None:
                return layer.color
        return None


@dataclass
class MaterialList:
    name: str
    textures: list[Texture]
    materials: list[Material]


def _pool_string(pool: bytes, at: int) -> tuple[str, int]:
    end = pool.find(b"\0", at)
    if end < 0:
        raise BoltModelError("string pool runs out of names")
    return pool[at:end].decode("latin-1"), end + 1


def _read_texture(r: _Reader, name: str) -> Texture:
    w = r.u16()
    h = r.u16()
    r.u8()
    kind = r.u8()
    mips = r.u8()
    size = r.u32()
    if kind not in TEX_TYPES:
        raise BoltModelError(f"{name}: texture type {kind}")
    if kind in (2, 3, 4):
        r.u8()
    pixels = r.raw(size)
    palette = None
    if kind == 3:
        r.u16()
        palette = r.raw(0x200)
    elif kind == 4:
        r.u16()
        palette = r.raw(0x20)
    return Texture(name, w, h, kind, mips, pixels, palette)


def _read_texture_13(r: _Reader) -> Texture:
    name = r.raw(r.u16()).split(b"\0")[0].decode("latin-1")
    w = r.u16()
    h = r.u16()
    r.u8()
    kind = r.u8()
    if kind not in TEX_TYPES:
        raise BoltModelError(f"{name}: texture type {kind}")
    if kind in (3, 4):
        r.u8()  # last palette entry (0xff)
    mips = r.u8()
    fmt = TEX_TYPES[kind][0]
    size = 0
    lw, lh = w, h
    for _ in range(mips):
        size += gx_texture.encoded_size(fmt, max(lw, 1), max(lh, 1))
        lw //= 2
        lh //= 2
    pixels = r.raw(size)
    palette = None
    if kind in (3, 4):
        palette = r.raw(r.u16())
    return Texture(name, w, h, kind, mips, pixels, palette)


def parse_material_list(data: bytes) -> MaterialList:
    if not is_material_list(data[:HEAD]):
        raise BoltModelError("not a BOLT material list")
    r = _Reader(data)
    v = version(data[:8])
    r.raw(4)
    if v[1] == 3:
        name = r.raw(r.u8()).decode("latin-1")
        textures = [_read_texture_13(r) for _ in range(r.u16())]
        materials = []
        for _ in range(r.u16()):
            mname = r.raw(r.u16()).split(b"\0")[0].decode("latin-1")
            refs = [r.u16() for _ in range(r.u16())]
            materials.append(Material(mname, [Layer(0, refs, None)]))
        return MaterialList(name, textures, materials)
    pool = r.raw(r.u32())
    r.u32()  # size of the texture-pointer pool, not stored in the file
    at = 0
    name, at = _pool_string(pool, at)
    layered = v[2] >= LAYERED_LISTS
    if layered:
        nmat = r.u16()
        r.u16()  # layers in total
        ntex = r.u16()
    else:
        ntex = r.u16()
    textures = []
    for _ in range(ntex):
        tname, at = _pool_string(pool, at)
        textures.append(_read_texture(r, tname))
    if not layered:
        nmat = r.u16()
    materials = []
    for _ in range(nmat):
        mname, at = _pool_string(pool, at)
        layers = []
        if layered:
            r.u8()
            for _ in range(r.u8()):
                flags = r.u8()
                r.raw(12 + 4 + 4)
                count = r.u16()
                if count:
                    layers.append(Layer(flags, [r.u16() for _ in range(count)], None))
                else:
                    layers.append(Layer(flags, [], struct.unpack(">4f", r.raw(16))))
        else:
            flags = r.u8()
            color = struct.unpack(">4f", r.raw(16))
            r.raw(16 + 4 + 4)
            first = [r.u16() for _ in range(r.u16())]
            second = [r.u16() for _ in range(r.u16())]
            layers.append(Layer(flags, first + second, None if first else color))
        materials.append(Material(mname, layers))
    return MaterialList(name, textures, materials)
