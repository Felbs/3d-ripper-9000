"""An F3DEX2 display-list interpreter: the N64 equivalent of gcrip's GX display lists.

The RSP consumes a stream of fixed 8-byte commands.  Geometry arrives as batches of vertices
loaded into a 32-entry cache (``G_VTX``) followed by triangles that index that cache
(``G_TRI1`` / ``G_TRI2``), so a display list is a sequence of small indexed draws rather than
one vertex array - the same shape as GX, with a different instruction set.

Addresses inside a display list are **segmented**: the top byte of a pointer selects one of
16 segment bases and the low 24 bits are an offset within it.  Segments 0-6 are set up in the
data (object files, scene and room headers); segments 8-0F are written by actor code at draw
time and are simply not present in a static rip, so pointers into them cannot resolve.  That
is a property of the game, not a bug here: the interpreter records them as unresolved rather
than guessing.

State that matters for geometry is tracked (matrix stack, geometry mode, the current texture
tile and palette); state that only affects shading is decoded far enough to name a material.
"""

from __future__ import annotations

import copy
import struct
from dataclasses import dataclass, field

import numpy as np

# -- opcodes ------------------------------------------------------------------

G_NOOP = 0x00
G_VTX = 0x01
G_MODIFYVTX = 0x02
G_CULLDL = 0x03
G_BRANCH_Z = 0x04
G_TRI1 = 0x05
G_TRI2 = 0x06
G_QUAD = 0x07
G_TEXTURE = 0xD7
G_POPMTX = 0xD8
G_GEOMETRYMODE = 0xD9
G_MTX = 0xDA
G_MOVEWORD = 0xDB
G_MOVEMEM = 0xDC
G_LOAD_UCODE = 0xDD
G_DL = 0xDE
G_ENDDL = 0xDF
G_SETTIMG = 0xFD
G_SETTILE = 0xF5
G_LOADBLOCK = 0xF3
G_LOADTILE = 0xF4
G_LOADTLUT = 0xF0
G_SETTILESIZE = 0xF2
G_SETCOMBINE = 0xFC
G_SETPRIMCOLOR = 0xFA
G_SETENVCOLOR = 0xFB
G_SETOTHERMODE_H = 0xE3
G_SETOTHERMODE_L = 0xE2
G_RDPPIPESYNC = 0xE7

#: the geometry-mode bit that decides whether a vertex's last 4 bytes are a normal or a colour
G_LIGHTING = 0x00020000
G_CULL_FRONT = 0x00000200
G_CULL_BACK = 0x00000400

#: G_MTX parameter bits (the command stores them XORed with G_MTX_PUSH)
G_MTX_PUSH = 0x01
G_MTX_LOAD = 0x02
G_MTX_PROJECTION = 0x04

VERTEX = struct.Struct(">3hHhh4B")  # x y z flag u v r/nx g/ny b/nz a
VERTEX_SIZE = 16
VTX_CACHE = 32
MAX_STEPS = 200_000  # a runaway or mis-detected list must not hang the rip


class F3DError(Exception):
    pass


@dataclass
class TileState:
    """The RDP texture tile a draw samples from."""

    fmt: int = 0  # 0 RGBA, 1 YUV, 2 CI, 3 IA, 4 I
    size: int = 2  # 0 4bpp, 1 8bpp, 2 16bpp, 3 32bpp
    width: int = 0
    height: int = 0
    addr: int | None = None  # segmented address of the texel data
    pal_addr: int | None = None  # segmented address of the TLUT, for CI formats
    palette: int = 0  # CI4 sub-palette index
    #: raw clamp/mirror mode per axis.  gbi packs these as G_TX_MIRROR = 1 (low bit) and
    #: G_TX_CLAMP = 2 (high bit); reading bit 8 as clamp and bit 9 as mirror swaps them,
    #: which turns a clamped face tile into a mirrored one - a second pair of eyes on the jaw.
    cm_s: int = 0
    cm_t: int = 0
    mask_s: int = 0
    mask_t: int = 0
    line: int = 0
    tmem: int = 0
    #: dimensions of the image actually LOADED into TMEM.  width/height above are the
    #: clamp rectangle from G_SETTILESIZE, which is frequently larger - decoding that many
    #: texels runs off the end of the image into whatever bytes follow it.
    img_w: int = 0
    img_h: int = 0
    tex_on: bool = True  # G_TEXTURE's enable bit; an off run is not sampled at all

    @property
    def clamp_s(self) -> bool:
        return self._clamped(self.cm_s, self.mask_s, self.width)

    @property
    def clamp_t(self) -> bool:
        return self._clamped(self.cm_t, self.mask_t, self.height)

    @property
    def mirror_s(self) -> bool:
        return bool(self.cm_s & 1) and not self.clamp_s

    @property
    def mirror_t(self) -> bool:
        return bool(self.cm_t & 1) and not self.clamp_t

    @staticmethod
    def _clamped(cm: int, mask: int, rect: int) -> bool:
        """A tile clamps when it says so, and also when it has no mask to wrap around."""
        return mask == 0 or bool(cm & 2)

    def key(self) -> tuple:
        # a run with texturing disabled is not the same material as one with it on, even
        # when every other field matches
        return (self.addr if self.tex_on else None, self.pal_addr, self.fmt, self.size,
                self.width, self.height, self.palette, self.cm_s, self.cm_t, self.tex_on)


@dataclass
class Batch:
    """One run of triangles sharing a tile, a matrix, a geometry mode and a prim colour."""

    positions: np.ndarray  # (N,3) f32, already transformed by the matrix in force
    uvs: np.ndarray  # (N,2) f32, in texel units before tile scaling
    colors: np.ndarray  # (N,4) u8
    normals: np.ndarray | None  # (N,3) f32 or None when the batch was unlit
    indices: np.ndarray  # (M,) u32
    tile: TileState
    lit: bool
    cull_back: bool = True
    #: G_SETPRIMCOLOR, which the colour combiner multiplies into the texture.  Link's tunic
    #: texture is pale cloth: its green comes from here, not from the image, so dropping it
    #: leaves him in a white tunic.
    prim: tuple[int, int, int, int] = (255, 255, 255, 255)
    #: the render mode in force, and whether the combiner's alpha comes from a texel - the
    #: pair that decides opaque vs alpha-tested vs blended
    other_low: int = 0
    reads_texel_alpha: bool = False
    limb: int | None = None  # set by the skeleton walker, not by the interpreter


@dataclass
class Result:
    batches: list[Batch] = field(default_factory=list)
    unresolved: set[int] = field(default_factory=set)  # segments referenced but not bound
    warnings: list[str] = field(default_factory=list)
    commands: int = 0
    calls: int = 0

    @property
    def triangles(self) -> int:
        return sum(len(b.indices) // 3 for b in self.batches)


class Segments:
    """The 16 segment bases a display list addresses through."""

    def __init__(self, base: dict[int, bytes] | None = None):
        self.bases: dict[int, bytes] = dict(base or {})

    def set(self, index: int, data: bytes) -> None:
        self.bases[index & 0x0F] = data

    def resolve(self, addr: int) -> tuple[bytes, int] | None:
        """(buffer, offset) for a segmented address, or None if that segment is unbound."""
        seg, off = (addr >> 24) & 0x0F, addr & 0x00FFFFFF
        buf = self.bases.get(seg)
        if buf is None or off >= len(buf):
            return None
        return buf, off


def _s8(v: int) -> int:
    """A byte read as a signed 8-bit value (vertex normals are stored that way)."""
    return v - 256 if v > 127 else v


def _mtx_from_fixed(raw: bytes) -> np.ndarray:
    """The RSP's 4x4 matrix: 16.16 fixed point split into integer and fraction halves."""
    ints = np.frombuffer(raw, ">i2", 16).astype(np.int64).reshape(4, 4)
    fracs = np.frombuffer(raw, ">u2", 16, 32).astype(np.int64).reshape(4, 4)
    return ((ints << 16) | fracs).astype(np.float64).view(np.float64).reshape(4, 4) / 65536.0


def _mtx_signed(raw: bytes) -> np.ndarray:
    ints = np.frombuffer(raw, ">i2", 16).reshape(4, 4).astype(np.float64)
    fracs = np.frombuffer(raw, ">u2", 16, 32).reshape(4, 4).astype(np.float64)
    return ints + fracs / 65536.0


def pack_matrix(m: np.ndarray) -> bytes:
    """A 4x4 matrix in the RSP's own layout: 16 signed integer parts, then 16 fractions.

    The inverse of :func:`_mtx_signed`, and transposed the same way, so a matrix written here
    and loaded by ``G_MTX`` comes back unchanged.
    """
    mt = np.asarray(m, dtype=np.float64).T  # RSP matrices are row-major
    ints = np.floor(mt).astype(np.int64)
    fracs = np.rint((mt - ints) * 65536.0).astype(np.int64)
    carry = fracs >= 65536
    ints[carry] += 1
    fracs[carry] -= 65536
    ints = np.clip(ints, -32768, 32767).astype(">i2")
    fracs = np.clip(fracs, 0, 65535).astype(">u2")
    return ints.tobytes() + fracs.tobytes()


def matrix_segment(matrices: list[np.ndarray]) -> bytes:
    """The limb-matrix array a display list reaches through segment 0x0D.

    A Zelda limb's display list selects which matrix applies to each vertex group with
    ``G_MTX 0x0d0000N0``, where N counts 64-byte matrices.  The game fills that array at draw
    time - one entry per limb that actually draws, in draw order - which is why a static rip
    that leaves segment 0x0D unbound piles geometry from different spaces on top of itself.
    """
    return b"".join(pack_matrix(m) for m in matrices)


_BITS = {0: 4, 1: 8, 2: 16, 3: 32}


def _image_size(tile: "TileState", nbytes: int) -> tuple[int, int]:
    """Dimensions of the image a tile samples, from what was loaded rather than the rect.

    Width comes from the tile's TMEM row stride, or from its S mask when it has one (a mask
    of n means the image is 2**n wide).  Height then follows from how many bytes arrived.
    """
    bits = _BITS[tile.size]
    width = (tile.line * 64) // bits if tile.line else 0
    if tile.mask_s:
        width = 1 << tile.mask_s
    if width <= 0:
        return 0, 0
    height = (nbytes * 8 // bits) // width
    if tile.mask_t:
        height = min(height, 1 << tile.mask_t) or height
    return width, max(1, height)


class Interpreter:
    """Walks a display list and collects triangle batches.

    ``matrix`` is the transform in force when the list starts - the skeleton walker uses it
    to place each limb.  Vertices are transformed as they are loaded, which is what the RSP
    does and what makes per-limb rigid skinning fall out naturally.
    """

    def __init__(self, segments: Segments, matrix: np.ndarray | None = None):
        self.seg = segments
        self.result = Result()
        self.mtx = np.eye(4) if matrix is None else np.asarray(matrix, dtype=np.float64)
        self._mtx_stack: list[np.ndarray] = []
        self.tile = TileState()
        self.tiles: dict[int, TileState] = {}
        self.timg: int | None = None        # the DMA source SETTIMG last named
        self.timg_size: int = 2
        self.tmem: dict[int, tuple] = {}    # TMEM address -> (source, size, bytes loaded)
        self.geometry_mode = 0
        self.prim = (255, 255, 255, 255)
        self.other_low = 0          # G_SETOTHERMODE_L: the render mode
        self.reads_texel_alpha = False  # G_SETCOMBINE: does the alpha equation sample a texel
        self._cache: list[tuple | None] = [None] * VTX_CACHE
        self._verts: list[tuple] = []
        self._tris: list[tuple[int, int, int]] = []
        self._batch_tile = TileState()
        self._batch_prim = (255, 255, 255, 255)
        self._batch_other = 0
        self._batch_texel_alpha = False
        self._steps = 0

    # -- batching -------------------------------------------------------------

    def _flush(self) -> None:
        if not self._tris:
            self._verts = []
            return
        pos = np.array([v[0] for v in self._verts], dtype=np.float32)
        uv = np.array([v[1] for v in self._verts], dtype=np.float32)
        col = np.array([v[2] for v in self._verts], dtype=np.uint8)
        lit = bool(self.geometry_mode & G_LIGHTING)
        nrm = np.array([v[3] for v in self._verts], dtype=np.float32) if lit else None
        idx = np.array(self._tris, dtype=np.uint32).ravel()
        self.result.batches.append(
            Batch(
                positions=pos,
                uvs=uv,
                colors=col,
                normals=nrm,
                indices=idx,
                tile=self._batch_tile,
                lit=lit,
                prim=self._batch_prim,
                other_low=self._batch_other,
                reads_texel_alpha=self._batch_texel_alpha,
                cull_back=bool(self.geometry_mode & G_CULL_BACK),
            )
        )
        self._verts = []
        self._tris = []

    def _emit(self, a: int, b: int, c: int) -> None:
        """One triangle from the vertex cache, copied into the batch's own vertex list."""
        out = []
        for slot in (a, b, c):
            v = self._cache[slot] if 0 <= slot < VTX_CACHE else None
            if v is None:
                return  # a triangle referencing an unloaded slot is not geometry
            self._verts.append(v)
            out.append(len(self._verts) - 1)
        self._tris.append((out[0], out[1], out[2]))

    def _tile_changed(self) -> bool:
        """A new tile or a new prim colour both start a new batch - the combiner multiplies
        them together, so a run sharing one but not the other is not one material."""
        return (self.tile.key() != self._batch_tile.key()
                or self.prim != self._batch_prim
                or self.other_low != self._batch_other
                or self.reads_texel_alpha != self._batch_texel_alpha)

    # -- the walk -------------------------------------------------------------

    def run(self, addr: int, depth: int = 0) -> Result:
        if depth > 16:
            self.result.warnings.append("display-list nesting deeper than 16")
            return self.result
        found = self.seg.resolve(addr)
        if found is None:
            self.result.unresolved.add((addr >> 24) & 0x0F)
            return self.result
        data, off = found
        while off + 8 <= len(data):
            if self._steps > MAX_STEPS:
                self.result.warnings.append("command budget exhausted")
                break
            self._steps += 1
            self.result.commands += 1
            op = data[off]
            w0, w1 = struct.unpack_from(">2I", data, off)
            off += 8

            if op == G_ENDDL:
                break
            if op == G_DL:
                self.result.calls += 1
                # bit 0 of the store flag: branch (do not return) rather than call
                branch = (w0 >> 16) & 0xFF
                if branch:
                    nxt = self.seg.resolve(w1)
                    if nxt is None:
                        self.result.unresolved.add((w1 >> 24) & 0x0F)
                        break
                    data, off = nxt
                    continue
                self.run(w1, depth + 1)
                continue
            if op == G_VTX:
                self._op_vtx(w0, w1)
                continue
            if op == G_TRI1:
                self._op_tri1(w0)
                continue
            if op == G_TRI2:
                self._op_tri2(w0, w1)
                continue
            if op == G_QUAD:
                self._op_tri2(w0, w1)
                continue
            if op == G_SETTIMG:
                self._op_settimg(w0, w1)
                continue
            if op == G_SETTILE:
                self._op_settile(w0, w1)
                continue
            if op in (G_LOADBLOCK, G_LOADTILE):
                self._op_load(w0, w1, op == G_LOADBLOCK)
                continue
            if op == G_SETTILESIZE:
                self._op_settilesize(w0, w1)
                continue
            if op == G_SETOTHERMODE_L:
                # shift and length are encoded as 32 - shift - length in the high half
                shift = 32 - (((w0 >> 8) & 0xFF) + ((w0 & 0xFF) + 1))
                length = (w0 & 0xFF) + 1
                mask = ((1 << length) - 1) << shift
                self.other_low = (self.other_low & ~mask) | (w1 & mask)
                continue
            if op == G_SETCOMBINE:
                from n64rip.render_mode import combine_reads_texel_alpha

                self.reads_texel_alpha = combine_reads_texel_alpha(w0, w1)
                continue
            if op == G_TEXTURE:
                # Only the enable bit is honoured.  The S/T scale is NOT applied: every
                # scale-zero command in this ROM is gsSPTexture(..., G_OFF), and applying
                # the scale unconditionally collapses geometry onto a single texel.
                self.tile.tex_on = bool((w0 >> 1) & 0x7F)
                continue
            if op == G_SETPRIMCOLOR:
                self.prim = ((w1 >> 24) & 0xFF, (w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF)
                continue
            if op == G_LOADTLUT:
                self._op_loadtlut(w1)
                continue
            if op == G_GEOMETRYMODE:
                # w0 carries the bits to clear (inverted), w1 the bits to set
                self.geometry_mode = (self.geometry_mode & (w0 & 0x00FFFFFF)) | w1
                continue
            if op == G_MTX:
                self._op_mtx(w0, w1)
                continue
            if op == G_POPMTX:
                if self._mtx_stack:
                    self.mtx = self._mtx_stack.pop()
                continue
            # everything else is shading or sync state we do not need for geometry
        self._flush()
        return self.result

    # -- individual commands --------------------------------------------------

    def _op_vtx(self, w0: int, w1: int) -> None:
        """Load ``count`` vertices into the cache, transformed by the matrix in force.

        The last four bytes of a vertex are a signed unit normal when G_LIGHTING is on and
        a vertex colour when it is off - the same 16 bytes read two ways, decided by state
        rather than by anything in the vertex itself.
        """
        count = (w0 >> 12) & 0xFF
        end = (w0 >> 1) & 0x7F  # index one past the last slot written
        start = end - count
        found = self.seg.resolve(w1)
        if found is None:
            self.result.unresolved.add((w1 >> 24) & 0x0F)
            return
        data, off = found
        if count == 0 or off + count * VERTEX_SIZE > len(data):
            self.result.warnings.append("vertex load runs past the end of its segment")
            return
        lit = bool(self.geometry_mode & G_LIGHTING)
        rot = self.mtx[:3, :3]
        for i in range(count):
            slot = start + i
            if not 0 <= slot < VTX_CACHE:
                continue
            x, y, z, _flag, u, v, a, b, c, d = VERTEX.unpack_from(data, off + i * VERTEX_SIZE)
            p = self.mtx @ np.array([x, y, z, 1.0])
            uv = (u / 32.0, v / 32.0)
            if lit:
                n = rot @ np.array([_s8(a), _s8(b), _s8(c)], dtype=np.float64)
                norm = float(np.linalg.norm(n)) or 1.0
                self._cache[slot] = (
                    (p[0], p[1], p[2]), uv, (255, 255, 255, d), tuple(n / norm)
                )
            else:
                self._cache[slot] = (
                    (p[0], p[1], p[2]), uv, (a, b, c, d), (0.0, 0.0, 0.0)
                )

    def _op_tri1(self, w0: int) -> None:
        if self._tile_changed():
            self._flush()
            self._batch_tile = copy.copy(self.tile)
            self._batch_prim = self.prim
            self._batch_other = self.other_low
            self._batch_texel_alpha = self.reads_texel_alpha
        a = ((w0 >> 16) & 0xFF) // 2
        b = ((w0 >> 8) & 0xFF) // 2
        c = (w0 & 0xFF) // 2
        self._emit(a, b, c)

    def _op_tri2(self, w0: int, w1: int) -> None:
        if self._tile_changed():
            self._flush()
            self._batch_tile = copy.copy(self.tile)
            self._batch_prim = self.prim
            self._batch_other = self.other_low
            self._batch_texel_alpha = self.reads_texel_alpha
        self._emit(((w0 >> 16) & 0xFF) // 2, ((w0 >> 8) & 0xFF) // 2, (w0 & 0xFF) // 2)
        self._emit(((w1 >> 16) & 0xFF) // 2, ((w1 >> 8) & 0xFF) // 2, (w1 & 0xFF) // 2)

    def _op_settimg(self, w0: int, w1: int) -> None:
        """``G_SETTIMG`` names the DMA *source* for the next load - nothing more.

        It does not describe the tile that will be rendered from.  Writing its format and
        address onto the render tile is wrong in the standard LoadTextureBlock + LoadTLUT
        idiom, where the last SETTIMG before the triangles is the **palette**: the 512-byte
        TLUT then gets decoded as if it were the image, which is the speckle on Link's hands,
        scabbard and hilt.
        """
        self.timg = w1
        self.timg_size = (w0 >> 19) & 0x03
        if self.seg.resolve(w1) is None:
            self.result.unresolved.add((w1 >> 24) & 0x0F)

    def _op_load(self, w0: int, w1: int, block: bool) -> None:
        """``G_LOADBLOCK`` / ``G_LOADTILE``: this is what actually puts an image in TMEM.

        Record which source landed at which TMEM address, so a tile can be matched to the
        image it really samples instead of to whatever SETTIMG ran most recently.
        """
        tile_no = (w1 >> 24) & 0x07
        dst = self.tiles.setdefault(tile_no, TileState()).tmem
        bits = _BITS[self.timg_size]
        if block:
            # lrs counts packed units, not texels: for 8bpp it is texels/2 - 1
            units = ((w1 >> 12) & 0xFFF) + 1
            texels = units * (64 // bits) if bits < 16 else units
            self.tmem[dst] = (self.timg, self.timg_size, texels * bits // 8)
        else:
            uls, ult = (w0 >> 12) & 0xFFF, w0 & 0xFFF
            lrs, lrt = (w1 >> 12) & 0xFFF, w1 & 0xFFF
            w = ((lrs - uls) >> 2) + 1
            h = ((lrt - ult) >> 2) + 1
            self.tmem[dst] = (self.timg, self.timg_size, w * h * bits // 8)

    def _op_settile(self, w0: int, w1: int) -> None:
        tile_no = (w1 >> 24) & 0x07
        t = self.tile if tile_no == 0 else self.tiles.setdefault(tile_no, TileState())
        t.fmt = (w0 >> 21) & 0x07
        t.size = (w0 >> 19) & 0x03
        t.line = (w0 >> 9) & 0x1FF
        t.tmem = w0 & 0x1FF
        t.palette = (w1 >> 20) & 0x0F
        t.cm_t = (w1 >> 18) & 0x03
        t.mask_t = (w1 >> 14) & 0x0F
        t.cm_s = (w1 >> 8) & 0x03
        t.mask_s = (w1 >> 4) & 0x0F
        loaded = self.tmem.get(t.tmem)
        if loaded is not None:
            t.addr, _src_size, nbytes = loaded
            t.img_w, t.img_h = _image_size(t, nbytes)
        if tile_no != 0:
            self.tiles[tile_no] = t

    def _op_settilesize(self, w0: int, w1: int) -> None:
        tile_no = (w1 >> 24) & 0x07
        t = self.tile if tile_no == 0 else self.tiles.setdefault(tile_no, TileState())
        # coordinates are 10.2 fixed point; the tile spans lrs-uls inclusive
        uls = (w0 >> 12) & 0xFFF
        ult = w0 & 0xFFF
        lrs = (w1 >> 12) & 0xFFF
        lrt = w1 & 0xFFF
        t.width = ((lrs - uls) >> 2) + 1
        t.height = ((lrt - ult) >> 2) + 1
        if not t.img_w:
            t.img_w, t.img_h = t.width, t.height

    def _op_loadtlut(self, w1: int) -> None:
        if ((w1 >> 24) & 0x07) == 0:
            return
        self.tile.pal_addr = self.timg

    def _op_mtx(self, w0: int, w1: int) -> None:
        """``G_MTX``: the parameters are the LOW byte, XORed with G_MTX_PUSH.

        F3DEX2 encodes this as ``gsDma2p(G_MTX, m, 64, params ^ G_MTX_PUSH, 0)``, so the
        0x38 sitting in bits 19-23 is the length field, not the parameters.  Reading the
        parameters from there makes every load look like a multiply, and multiplying one
        limb's world matrix by another's throws the geometry into spikes.
        """
        params = (w0 & 0xFF) ^ G_MTX_PUSH
        push = bool(params & G_MTX_PUSH)
        load = bool(params & G_MTX_LOAD)
        found = self.seg.resolve(w1)
        if found is None:
            self.result.unresolved.add((w1 >> 24) & 0x0F)
            return
        data, off = found
        if off + 64 > len(data):
            return
        m = _mtx_signed(data[off : off + 64]).T  # RSP matrices are row-major
        if push:
            self._mtx_stack.append(self.mtx.copy())
        self.mtx = m if load else self.mtx @ m


def run(addr: int, segments: Segments, matrix: np.ndarray | None = None) -> Result:
    """Interpret the display list at a segmented address."""
    return Interpreter(segments, matrix).run(addr)
