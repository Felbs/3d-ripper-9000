"""Ginja - Sega's GameCube-native Ninja models (``GJCM`` blocks: Phantasy Star Online
objects / levels, Billy Hatcher).  Big-endian.  The object tree is the NJS_OBJECT layout
(52 bytes: flags, attach, pos f32[3], rot i32[3], scale f32[3], child, sibling); the attach
is SA Tools' GCAttach: ``u32 vertex sets | u32 skin sets | u32 opaque meshes | u32
translucent meshes | u16 opaque count | u16 translucent count | bounds``.  Vertex sets
(16 B): ``u8 attribute (1 position, 2 normal, 3 colour0, 5 tex0, 0xff end) | u8 struct
size | u16 count | u32 (struct type & 0xf, data type >> 4) | u32 data | u32 pad``; data
types 0-4 u8/s8/u16/s16/f32, 5-10 packed colours.  Meshes (16 B): ``u32 parameters | u32
count | u32 primitives | u32 size``; parameters ``u8 type, pad, u32 data`` - type 1 index
attribute flags (bit 2/3 position 16-bit/present, 4/5 normal, 6/7 colour, 10/11 uv), type
8 texture (id = data & 0xffff).  Primitives are raw GX strips (0x98 / 0x90 / 0xa0) whose
rows hold the present indices in position, normal, colour, uv order.
"""

from __future__ import annotations

import struct

import numpy as np

from dcrip.formats import ninja
from dcrip.formats.ninja import Material, Model, NinjaError, Strip, VertexWrite

_OPS = (0x80, 0x90, 0x98, 0xA0)


class GinjaParser:
    def __init__(self, data: bytes, warnings: list[str]):
        self.d = data
        self.warnings = warnings
        self.objects: list[ninja.Object] = []
        self._seen: set[int] = set()

    def object(self, off: int, parent: int | None, depth: int = 0) -> ninja.Object:
        d = self.d
        if off in self._seen or off + 52 > len(d) or depth > 64:
            raise NinjaError(f"object pointer {off:#x} invalid or cyclic")
        self._seen.add(off)
        ev, mdl, px, py, pz, rx, ry, rz, sx, sy, sz, child, sib = struct.unpack_from(
            ">II3f3i3fII", d, off
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
                obj.model = self.attach(mdl)
            except (NinjaError, struct.error, IndexError, ValueError) as e:
                self.warnings.append(f"{obj.name}: attach at {mdl:#x} unreadable: {e}")
        if child:
            obj.children.append(self.object(child, obj.index, depth + 1))
        if sib and parent is not None:
            self.objects[parent].children.append(self.object(sib, parent, depth))
        elif sib:
            obj.children.append(self.object(sib, None, depth))
        return obj

    # -- attach -------------------------------------------------------------------

    def _vertex_sets(self, off: int) -> dict[int, np.ndarray]:
        d = self.d
        sets: dict[int, np.ndarray] = {}
        p = off
        for _ in range(16):
            if p + 16 > len(d):
                break
            attr, ssize, count, structure, ptr = struct.unpack_from(">BBHII", d, p)
            p += 16
            if attr == 0xFF:
                break
            stype, dtype = structure & 0xF, (structure >> 4) & 0xF
            ncomp = {0: 2, 1: 3, 2: 3, 3: 9, 4: 3, 5: 3, 6: 4, 7: 1, 8: 2}.get(stype, 3)
            if ptr + count * ssize > len(d) or count == 0:
                continue
            if dtype == 4:
                arr = np.frombuffer(d, ">f4", count * ssize // 4, ptr).reshape(count, -1)
                arr = arr[:, :ncomp].astype(np.float32)
            elif dtype == 3:
                arr = np.frombuffer(d, ">i2", count * ssize // 2, ptr).reshape(count, -1)
                arr = arr[:, :ncomp].astype(np.float32) / (256.0 if attr >= 5 else 1.0)
            elif dtype == 2:
                arr = np.frombuffer(d, ">u2", count * ssize // 2, ptr).reshape(count, -1)
                arr = arr[:, :ncomp].astype(np.float32) / (256.0 if attr >= 5 else 1.0)
            elif dtype == 1:
                arr = np.frombuffer(d, np.int8, count * ssize, ptr).reshape(count, -1)
                arr = arr[:, :ncomp].astype(np.float32) / 127.0
            elif dtype == 0:
                arr = np.frombuffer(d, np.uint8, count * ssize, ptr).reshape(count, -1)
                arr = arr[:, :ncomp].astype(np.float32) / 255.0
            elif dtype == 10 and ssize == 4:  # RGBA8
                arr = np.frombuffer(d, np.uint8, count * 4, ptr).reshape(count, 4) / 255.0
                arr = arr.astype(np.float32)
            elif dtype == 5 and ssize == 2:  # RGB565
                v = np.frombuffer(d, ">u2", count, ptr).astype(np.uint32)
                arr = np.stack(
                    [
                        ((v >> 11) & 31) / 31.0,
                        ((v >> 5) & 63) / 63.0,
                        (v & 31) / 31.0,
                        np.ones(count),
                    ],
                    axis=1,
                ).astype(np.float32)
            else:
                continue
            sets[attr] = arr
        return sets

    def attach(self, off: int) -> Model:
        d = self.d
        vp, _sp, op, tp, oc, tc = struct.unpack_from(">4I2H", d, off)
        m = Model(center=(0.0, 0.0, 0.0), radius=0.0)
        sets = self._vertex_sets(vp) if vp else {}
        pos = sets.get(1)
        if pos is None or len(pos) == 0:
            raise NinjaError("attach without positions")
        nrm = sets.get(2)
        col = sets.get(3)
        uv = sets.get(5)
        for i in range(len(pos)):
            m.vertices.append(
                VertexWrite(
                    i,
                    pos[i].astype(np.float32),
                    None if nrm is None or i >= len(nrm) else nrm[i].astype(np.float32),
                    None,
                    1.0,
                    0,
                )
            )
        mat = Material()
        for base, count, translucent in ((op, oc, False), (tp, tc, True)):
            for k in range(count):
                mo = base + k * 16
                if mo + 16 > len(d):
                    break
                mat = self._mesh(mo, m, mat, translucent, len(pos), nrm, col, uv)
        return m

    def _mesh(self, mo, m, mat, translucent, npos, nrm, col, uv) -> Material:
        d = self.d
        pp, pc, prp, prs = struct.unpack_from(">4I", d, mo)
        flags = 0x808  # position + uv by default
        mat = Material(**{**mat.__dict__})
        mat.use_alpha = translucent
        for k in range(min(pc, 64)):
            q = pp + k * 8
            if q + 8 > len(d):
                break
            ptype, data = d[q], struct.unpack_from(">I", d, q + 4)[0]
            if ptype == 1:
                flags = data & 0xFFFF
            elif ptype == 8:
                mat.texture = data & 0xFFFF
                mat.clamp_u = not (data >> 16) & 4
                mat.clamp_v = not (data >> 16) & 8
            elif ptype == 5:
                mat.diffuse = (
                    ((data >> 24) & 255) / 255,
                    ((data >> 16) & 255) / 255,
                    ((data >> 8) & 255) / 255,
                    (data & 255) / 255,
                )
        has = [bool(flags & 8), bool(flags & 0x20), bool(flags & 0x80), bool(flags & 0x800)]
        wide = [bool(flags & 4), bool(flags & 0x10), bool(flags & 0x40), bool(flags & 0x400)]
        stride = sum((2 if w else 1) for h, w in zip(has, wide, strict=True) if h)
        p, end = prp, min(prp + prs, len(d))
        while p + 3 <= end:
            opb = d[p]
            if opb == 0:
                p += 1
                continue
            op = opb & 0xF8
            if op not in _OPS:
                break
            cnt = (d[p + 1] << 8) | d[p + 2]
            p += 3
            if cnt == 0 or p + cnt * stride > end:
                break
            rows = np.frombuffer(d, np.uint8, cnt * stride, p).reshape(cnt, stride)
            p += cnt * stride
            cols = {}
            c = 0
            for name, h, w in zip(("pos", "nrm", "col", "uv"), has, wide, strict=True):
                if not h:
                    continue
                if w:
                    cols[name] = (rows[:, c].astype(np.int64) << 8) | rows[:, c + 1]
                    c += 2
                else:
                    cols[name] = rows[:, c].astype(np.int64)
                    c += 1
            pi = cols.get("pos")
            if pi is None or pi.max() >= npos:
                continue
            corners = []
            for i in range(cnt):
                uvv = (0.0, 0.0)
                if uv is not None and "uv" in cols and cols["uv"][i] < len(uv):
                    uvv = (float(uv[cols["uv"][i]][0]), float(uv[cols["uv"][i]][1]))
                nv = (0.0, 0.0, 1.0)
                if nrm is not None and "nrm" in cols and cols["nrm"][i] < len(nrm):
                    nv = tuple(float(x) for x in nrm[cols["nrm"][i]][:3])
                cv = (1.0, 1.0, 1.0, 1.0)
                if col is not None and "col" in cols and cols["col"][i] < len(col):
                    cv = tuple(float(x) for x in col[cols["col"][i]][:4])
                corners.append((int(pi[i]), uvv, nv, cv))
            tris = []
            if op == 0x98:
                for i in range(2, cnt):
                    a, b, cc = corners[i - 2], corners[i - 1], corners[i]
                    tris.append((a, cc, b) if i % 2 else (a, b, cc))
            elif op == 0x90:
                for i in range(0, cnt - 2, 3):
                    tris.append((corners[i], corners[i + 1], corners[i + 2]))
            elif op == 0xA0:
                for i in range(1, cnt - 1):
                    tris.append((corners[0], corners[i], corners[i + 1]))
            if not tris:
                continue
            idx, uvs, nrms, cs = [], [], [], []
            for t in tris:
                for v in t:
                    idx.append(v[0])
                    uvs.append(v[1])
                    nrms.append(v[2])
                    cs.append(v[3])
            m.strips.append(
                Strip(
                    material=Material(**{**mat.__dict__}),
                    indices=idx,
                    uvs=uvs if uv is not None else None,
                    colors=cs if col is not None else None,
                    normals=nrms if nrm is not None else None,
                )
            )
        return mat
