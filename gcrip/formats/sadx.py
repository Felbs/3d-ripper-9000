"""Sonic Adventure DX / Sonic Adventure 2: Battle data inside GameCube ``.rel`` modules,
located with SA Tools' split tables (gcrip.formats.satools) after the module's relocations
are resolved (gcrip.formats.rel).  Big-endian.

- Basic models (SADX, NJS_MODEL "BasicDX"): ``u32 points | u32 normals | u32 count | u32
  meshsets | u32 materials | u16 nmeshsets | u16 nmaterials | f32 center[3] | f32 radius``;
  meshsets are 28 bytes on SADX (``u16 type<<14 | material, u16 count, u32 polys, u32
  attrs, u32 normals, u32 colours, u32 uvs, u32``), materials 20 bytes.
- Chunk models (SA2B characters) and Ginja models (SA2B stage visuals) reuse the SA2B / PSO
  parsers.
- Land tables: SADX ``i16 cols | i16 anims | i16 attrs | i16 flags | f32 far | u32 col list
  | u32 anim list | u32 texture file name | u32 texlist``, COL 0x24 (``bounds[4] | f32 |
  f32 | u32 object | u32 block bits | i32 flags``); SA2B ``i16 cols | i16 chunk count | ...
  | f32 far @0xc | u32 col list @0x10``, COL 0x20 (``bounds[4] | u32 object | f32 | u32 block
  bits | i32 flags``) whose objects are Ginja for the first ``chunk count`` entries and
  Basic (collision) after that.
"""

from __future__ import annotations

import struct

import numpy as np

from gcrip.formats import ninja
from gcrip.formats.ninja import Material, Model, NinjaError, Strip, VertexWrite, _argb
from gcrip.formats import ginja, sa2b


class GcBasicParser(sa2b.GcChunkParser):
    """NJS_MODEL (Basic) in the GameCube byte order; ``dx`` = 28-byte meshsets."""

    def __init__(self, data: bytes, warnings: list[str], dx: bool = True):
        super().__init__(data, warnings)
        self.dx = dx

    def model(self, off: int) -> Model:
        d = self.d
        pts, nrms, npts, msets_p, mats_p, nmsets, nmats, cx, cy, cz, r = struct.unpack_from(
            ">IIIIIHH4f", d, off
        )
        if npts > 100_000 or pts + npts * 12 > len(d):
            raise NinjaError("basic model out of range")
        m = Model(center=(cx, cy, cz), radius=r)
        pos = np.frombuffer(d, ">f4", npts * 3, pts).reshape(npts, 3).astype(np.float32)
        nrm = None
        if nrms and nrms + npts * 12 <= len(d):
            nrm = np.frombuffer(d, ">f4", npts * 3, nrms).reshape(npts, 3).astype(np.float32)
        for i in range(npts):
            m.vertices.append(VertexWrite(i, pos[i], None if nrm is None else nrm[i], None, 1.0, 0))
        mats = []
        for i in range(nmats):
            if mats_p + i * 20 + 20 > len(d):
                break
            dif, _spec, _exp, texid, attr = struct.unpack_from(">IIfII", d, mats_p + i * 20)
            mat = Material(
                diffuse=_argb(dif), texture=texid & 0xFFFF if texid != 0xFFFFFFFF else None
            )
            mat.use_alpha = bool(attr & 0x10)
            mat.double_sided = bool(attr & 0x08)
            mat.flip_u, mat.flip_v = bool(attr & 0x800), bool(attr & 0x400)
            mat.clamp_u, mat.clamp_v = bool(attr & 0x200), bool(attr & 0x100)
            mat.ignore_light = bool(attr & 0x02)
            mat.env_map = bool(attr & 0x2000)
            # the GameCube builds leave NJD_FLAG_USE_TEXTURE (0x2000000) clear on textured
            # materials (SADX question mark: id 7, flags 0x9461a400), so keep the id
            mats.append(mat)
        stride = 28 if self.dx else 24
        for i in range(nmsets):
            o = msets_p + i * stride
            if o + 24 > len(d):
                break
            typ_mat, nb, meshes, _attrs, _mn, vcol, vuv = struct.unpack_from(">HHIIIII", d, o)
            typ, matid = typ_mat >> 14, typ_mat & 0x3FFF
            mat = mats[matid] if matid < len(mats) else Material()
            idx: list[int] = []
            uvs: list[tuple[float, float]] = []
            cols: list[tuple[float, float, float, float]] = []
            p = meshes
            k = 0

            def corner(vi: int, kk: int, vuv: int = vuv, vcol: int = vcol):
                uv = (0.0, 0.0)
                if vuv and vuv + kk * 4 + 4 <= len(d):
                    uv = (self.s16(vuv + kk * 4) / 255.0, self.s16(vuv + kk * 4 + 2) / 255.0)
                col = (1.0, 1.0, 1.0, 1.0)
                if vcol and vcol + kk * 4 + 4 <= len(d):
                    col = _argb(self.u32(vcol + kk * 4))
                return vi, uv, col

            try:
                if typ in (0, 1):
                    n = 3 if typ == 0 else 4
                    for _ in range(nb):
                        cs = [corner(self.u16(p + j * 2), k + j) for j in range(n)]
                        p += n * 2
                        k += n
                        tris = [(0, 1, 2)] if n == 3 else [(0, 1, 2), (0, 2, 3)]
                        for a, b, c in tris:
                            for v in (cs[a], cs[b], cs[c]):
                                idx.append(v[0])
                                uvs.append(v[1])
                                cols.append(v[2])
                else:
                    for _ in range(nb):
                        hdr = self.u16(p)
                        p += 2
                        n, flip = hdr & 0x7FFF, bool(hdr & 0x8000)
                        cs = [corner(self.u16(p + j * 2), k + j) for j in range(n)]
                        p += n * 2
                        k += n
                        if typ == 2:
                            for j in range(2, n):
                                for v in (cs[0], cs[j - 1], cs[j]):
                                    idx.append(v[0])
                                    uvs.append(v[1])
                                    cols.append(v[2])
                        else:
                            for j in range(2, n):
                                a, b, c = cs[j - 2], cs[j - 1], cs[j]
                                if (j % 2 == 1) != flip:
                                    a, b = b, a
                                for v in (a, b, c):
                                    idx.append(v[0])
                                    uvs.append(v[1])
                                    cols.append(v[2])
            except (struct.error, IndexError):
                m.warnings.append(f"meshset {i} truncated")
            if idx and max(idx) < npts:
                m.strips.append(Strip(mat, idx, uvs if vuv else None, cols if vcol else None, None))
        return m


def _tree(parser, off: int) -> ninja.Ninja | None:
    warnings: list[str] = []
    parser.warnings = warnings
    try:
        root = parser.object(off, None)
    except (NinjaError, struct.error, IndexError, ValueError) as e:
        return ninja.Ninja(warnings=[f"object at {off:#x}: {e}"])
    return ninja.Ninja(root=root, objects=parser.objects, kind="chunk", warnings=warnings)


def basic_object(d: bytes, off: int) -> ninja.Ninja | None:
    return _tree(GcBasicParser(d, []), off)


def chunk_object(d: bytes, off: int) -> ninja.Ninja | None:
    return _tree(sa2b.GcChunkParser(d, []), off)


def gc_object(d: bytes, off: int) -> ninja.Ninja | None:
    return _tree(ginja.GinjaParser(d, []), off)


def landtable(d: bytes, off: int, game: str) -> tuple[list[ninja.Ninja], str]:
    """(one Ninja tree per COL entry, texture file name) of a land table."""
    n = len(d)
    if off + 0x24 > n:
        return [], ""
    trees: list[ninja.Ninja] = []
    texname = ""
    if game == "SADX":
        cols, _anims = struct.unpack_from(">2h", d, off)
        col_ptr, _anim_ptr, tex_ptr = struct.unpack_from(">3I", d, off + 0xC)
        if 0 < tex_ptr < n:
            e = d.find(b"\0", tex_ptr)
            texname = d[tex_ptr : e if e >= 0 else n].decode("latin-1", "replace")
        for i in range(max(cols, 0)):
            c = col_ptr + i * 0x24
            if c + 0x24 > n:
                break
            obj = struct.unpack_from(">I", d, c + 0x18)[0]
            if 0 < obj < n:
                t = basic_object(d, obj)
                if t and t.root:
                    trees.append(t)
    else:
        cols, cnk = struct.unpack_from(">2h", d, off)
        col_ptr = struct.unpack_from(">I", d, off + 0x10)[0]
        for i in range(max(cols, 0)):
            c = col_ptr + i * 0x20
            if c + 0x20 > n:
                break
            obj, _wz, _bits, flags = struct.unpack_from(">IfIi", d, c + 0x10)
            if not (0 < obj < n):
                continue
            basic = (i >= cnk) if cnk >= 0 else flags >= 0
            if basic:
                continue  # collision geometry - the visible mesh is the Ginja one
            t = gc_object(d, obj)
            if t and t.root:
                trees.append(t)
    return trees, texname
