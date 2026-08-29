"""Sonic Adventure 2: Battle (GameCube) model archives: Sega-PRS-compressed files holding a
table of ``u32 id, u32 offset`` pairs (terminated by 0xffffffff) that point at NJS_OBJECT
trees whose attaches are Ninja chunk models - the same format the Dreamcast games use
(dcrip.formats.ninja) with every field byte-swapped to big-endian: the vertex-chunk header
becomes ``u16 size, u8 flags, u8 type, u16 count, u16 index offset`` and the poly-chunk
header ``u8 flags, u8 type``.  Object/attach/vertex floats and u32s are big-endian.
"""

from __future__ import annotations

import struct

import numpy as np

from dcrip.formats import ninja
from dcrip.formats.ninja import Material, Model, NinjaError, Strip, VertexWrite, _argb, _unpack_vnx

_VTX = ninja._VTX
_STRIP = ninja._STRIP


class GcChunkParser(ninja._ChunkParser):
    """dcrip's chunk parser reading the GameCube byte order."""

    def u16(self, o: int) -> int:
        return struct.unpack_from(">H", self.d, o)[0]

    def s16(self, o: int) -> int:
        return struct.unpack_from(">h", self.d, o)[0]

    def u32(self, o: int) -> int:
        return struct.unpack_from(">I", self.d, o)[0]

    def object(self, off: int, parent: int | None, depth: int = 0):
        if off in self._seen or off + 52 > len(self.d) or depth > 64:
            raise NinjaError(f"object pointer {off:#x} invalid or cyclic")
        self._seen.add(off)
        ev, mdl, px, py, pz, rx, ry, rz, sx, sy, sz, child, sib = struct.unpack_from(
            ">II3f3i3fII", self.d, off
        )
        obj = ninja.Object(
            index=len(self.objects),
            offset=off,
            flags=ev,
            pos=(px, py, pz),
            rot=(rx * ninja.NJ_ANGLE, ry * ninja.NJ_ANGLE, rz * ninja.NJ_ANGLE),
            scale=(sx, sy, sz),
            model=None,
            parent=parent,
        )
        self.objects.append(obj)
        if mdl:
            try:
                obj.model = self.model(mdl)
            except (NinjaError, struct.error, IndexError) as e:
                self.warnings.append(f"{obj.name}: model at {mdl:#x} unreadable: {e}")
        if child:
            obj.children.append(self.object(child, obj.index, depth + 1))
        if sib and parent is not None:
            sibling = self.object(sib, parent, depth)
            self.objects[parent].children.append(sibling)
        elif sib:
            sibling = self.object(sib, None, depth)
            obj.children.append(sibling)
        return obj

    def model(self, off: int) -> Model:
        vlist, plist, cx, cy, cz, r = struct.unpack_from(">II4f", self.d, off)
        m = Model(center=(cx, cy, cz), radius=r)
        if vlist:
            self.vertex_list(vlist, m)
        if plist:
            self.poly_list(plist, m)
        return m

    def vertex_list(self, off: int, m: Model) -> None:
        p = off
        d = self.d
        while p + 4 <= len(d):
            size, flags, t = self.u16(p), d[p + 2], d[p + 3]
            if t == 0xFF:
                return
            if t == 0:
                p += 4
                continue
            if t not in _VTX:
                m.warnings.append(f"unknown vertex chunk {t:#x}")
                p += 4 + size * 4
                continue
            per, has_n, nkind, extra = _VTX[t]
            count, idx_off = self.u16(p + 4), self.u16(p + 6)
            status = flags & 3
            q = p + 8
            end = p + 4 + size * 4
            if q + per * count > len(d) or q + per * count > end + 4:
                raise NinjaError(f"vertex chunk {t:#x} at {p:#x} overruns")
            for i in range(count):
                pos = np.frombuffer(d, dtype=">f4", count=3, offset=q)
                o = q + (16 if t in (0x20, 0x21) else 12)
                normal = None
                if has_n:
                    if nkind == "f4":
                        normal = np.frombuffer(d, dtype=">f4", count=3, offset=o)
                        o += 16
                    elif nkind == "f3":
                        normal = np.frombuffer(d, dtype=">f4", count=3, offset=o)
                        o += 12
                    else:
                        normal = _unpack_vnx(self.u32(o))
                        o += 4
                color = None
                cache_index = idx_off + i
                weight = 1.0
                if extra == "d8":
                    color = np.array(_argb(self.u32(o)), dtype=np.float32)
                elif extra == "nf":
                    nf = self.u32(o)
                    cache_index = idx_off + (nf & 0xFFFF)
                    weight = ((nf >> 16) & 0xFF) / 255.0
                elif extra == "s5":
                    c = self.u16(o)
                    color = np.array(
                        [((c >> 11) & 31) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31, 1.0],
                        dtype=np.float32,
                    )
                elif extra == "s4":
                    c = self.u16(o)
                    color = np.array(
                        [((c >> 8) & 15) / 15, ((c >> 4) & 15) / 15, (c & 15) / 15, (c >> 12) / 15],
                        dtype=np.float32,
                    )
                m.vertices.append(
                    VertexWrite(
                        cache_index,
                        pos.astype(np.float32),
                        None if normal is None else np.asarray(normal, np.float32),
                        color,
                        weight,
                        status,
                    )
                )
                q += per
            p = end
        m.warnings.append("vertex list without end chunk")

    def poly_list(self, off: int, m: Model) -> None:
        p = off
        d = self.d
        mat = Material()
        while p + 2 <= len(d):
            flags, t = d[p], d[p + 1]
            if t == 0xFF:
                return
            if t == 0:
                p += 2
                continue
            if t < 0x08:
                if t == 1:
                    mat.src_blend, mat.dst_blend = (flags >> 3) & 7, flags & 7
                elif t == 4:
                    m.cache_slot = flags
                elif t == 5:
                    m.strips.append(ninja.DrawSlot(flags))
                p += 2
                continue
            if t < 0x10:
                data = self.u16(p + 2)
                mat = Material(**{**mat.__dict__})
                mat.texture = data & 0x1FFF
                mat.clamp_v, mat.clamp_u = bool(flags & 0x10), bool(flags & 0x20)
                mat.flip_v, mat.flip_u = bool(flags & 0x40), bool(flags & 0x80)
                p += 4
                continue
            size = self.u16(p + 2)
            body = p + 4
            end = body + size * 2
            if end > len(d):
                raise NinjaError(f"poly chunk {t:#x} at {p:#x} overruns")
            if 0x10 <= t <= 0x1F:
                mat = Material(**{**mat.__dict__})
                mat.src_blend, mat.dst_blend = (flags >> 3) & 7, flags & 7
                if t & 1:
                    mat.diffuse = _argb(self.u32(body))
            elif 0x40 <= t <= 0x4B:
                smat = Material(**{**mat.__dict__})
                smat.ignore_light = bool(flags & 0x01)
                smat.use_alpha = bool(flags & 0x08)
                smat.double_sided = bool(flags & 0x10)
                smat.env_map = bool(flags & 0x40)
                self.strip_chunk(t, body, end, smat, m)
            elif t != 0x38:
                m.warnings.append(f"unknown poly chunk {t:#x}")
            p = end
        m.warnings.append("poly list without end chunk")

    def _read_strips(self, p, end, nstrips, nuser, per, uvkind, nbytes, has_c, mat):
        d = self.d
        idx: list[int] = []
        uvs: list[tuple[float, float]] = []
        cols: list[tuple[float, float, float, float]] = []
        nrms: list[tuple[float, float, float]] = []
        uvdiv = 256.0 if uvkind == "n" else 1024.0
        for _ in range(nstrips):
            if p + 2 > end:
                return None
            n = self.s16(p)
            p += 2
            flip = n < 0
            n = abs(n)
            corners = []
            for i in range(n):
                if p + per > end:
                    return None
                vi = self.u16(p)
                o = p + 2
                uv = (0.0, 0.0)
                if uvkind:
                    uv = (self.s16(o) / uvdiv, self.s16(o + 2) / uvdiv)
                    o += 4
                nrm = (0.0, 0.0, 1.0)
                if nbytes == 6:
                    nrm = (self.s16(o) / 32767, self.s16(o + 2) / 32767, self.s16(o + 4) / 32767)
                    o += 6
                elif nbytes == 12:
                    nrm = tuple(struct.unpack_from(">3f", d, o))
                    o += 12
                col = (1.0, 1.0, 1.0, 1.0)
                if has_c:
                    col = _argb(self.u32(o))
                    o += 4
                p += per
                if i >= 2:
                    p += 2 * nuser
                corners.append((vi, uv, nrm, col))
            for i in range(2, n):
                a, b, c = corners[i - 2], corners[i - 1], corners[i]
                if (i % 2 == 1) != flip:
                    a, b = b, a
                for v in (a, b, c):
                    idx.append(v[0])
                    uvs.append(v[1])
                    nrms.append(v[2])
                    cols.append(v[3])
        if p != end and end - p >= 4:
            return None
        return Strip(
            material=mat,
            indices=idx,
            uvs=uvs if uvkind else None,
            colors=cols if has_c else None,
            normals=nrms if nbytes else None,
        )


def model_table(d: bytes) -> list[tuple[int, int]]:
    """(id, object offset) pairs of an SA2B model archive, or [] when it is not one."""
    out = []
    p = 0
    n = len(d)
    while p + 8 <= n and p < 0x4000:
        i, o = struct.unpack_from(">2I", d, p)
        p += 8
        if i == 0xFFFFFFFF:
            break
        if i > 0xFFFF or o + 52 > n or o < p:
            return []
        out.append((i, o))
    else:
        return []
    if not out:
        return []
    # the first object must look like an NJS_OBJECT: sane flags and pointers inside the file
    ev, mdl, *_rest = struct.unpack_from(">2I", d, out[0][1])
    child, sib = struct.unpack_from(">2I", d, out[0][1] + 44)
    if ev > 0x3F or mdl >= n or child >= n or sib >= n:
        return []
    return out


def is_model_archive(d: bytes) -> bool:
    return bool(model_table(d))


def parse(d: bytes) -> list[tuple[int, ninja.Ninja]]:
    """[(id, Ninja)] - one tree per table entry."""
    out = []
    for ident, off in model_table(d):
        warnings: list[str] = []
        parser = GcChunkParser(d, warnings)
        try:
            root = parser.object(off, None)
        except (NinjaError, struct.error, IndexError) as e:
            warnings.append(f"model {ident}: {e}")
            continue
        nj = ninja.Ninja(root=root, objects=parser.objects, kind="chunk", warnings=warnings)
        out.append((ident, nj))
    return out
