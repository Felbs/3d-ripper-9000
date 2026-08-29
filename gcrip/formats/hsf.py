"""Hudson Soft HSF models (``HSFV037``: Mario Party 4-7 on GameCube).  Big-endian.  Layout
after KillzXGaming's MPLibrary.

Header: ``"HSFV037" u8`` then 20 sections of ``u32 offset, u32 count`` from 0x08: fog,
colour, material, attribute, position, normal, texcoord, face, object, texture, palette,
motion, cenv (skinning), skeleton, part, cluster, shape, map attribute, matrix, symbol;
``u32 string table offset, u32 size`` at 0xa8.  Vertex sections are ``count`` component
records ``u32 name, u32 count, u32 data offset`` (offsets relative to the end of the table)
- positions f32 xyz, normals s8 xyz or f32 xyz, colours RGBA8, uvs f32.  Face components
hold 48-byte primitives ``u16 type (2 tri, 3 quad, 4 strip), u16 flags (material = & 0xfff),
4 x (s16 position, normal, colour, uv), [strips: 3 groups + i32 count + u32 index into the
extension table after all primitives], f32 nbt[3]``.  Objects are 0x144 bytes: ``u32 name,
i32 type (2 mesh, 3 root, 4 joint ...), i32 const, i32 render flags, i32 parent, i32
children, i32 symbol, f32 translate/rotate/scale[9], f32 current[9], f32 cull box[6], f32
base morph, f32 morph[32], i32 unknown, i32 face, i32 vertex, i32 normal, i32 colour, i32
texcoord, i32 material data, i32 attribute, u8[4], i32 shape count/symbol, i32 cluster
count/symbol, i32 cenv count, i32 cenv index, i32 cluster pos/normal``.  Materials (0x3c)
reference attributes through the symbol table (``first symbol`` + ``texture count``);
attributes (0x84) end with the texture index; textures are ``u32 name, u32 max lod, u8
format, u8 bpp, u16 w, u16 h, u16 palette entries, u32 tint, i32 palette, u32 pad, u32 data
offset`` with GX pixels (0 I4/I8, 1 I8, 2 IA4, 3 IA8, 4 RGB565, 5 RGB5A3, 6 RGBA8, 7 CMPR,
9-11 C8/C4).  Cenv: single / double / multi binds map bone (object index) to position ranges.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"HSFV"
OBJECT_SIZE = 0x144
MESH, ROOT, JOINT = 2, 3, 4

_SECTIONS = (
    "fog",
    "color",
    "material",
    "attribute",
    "position",
    "normal",
    "texcoord",
    "face",
    "object",
    "texture",
    "palette",
    "motion",
    "cenv",
    "skeleton",
    "part",
    "cluster",
    "shape",
    "mapattr",
    "matrix",
    "symbol",
)


class HsfError(ValueError):
    pass


@dataclass
class Obj:
    name: str
    type: int
    parent: int
    translate: tuple[float, float, float]
    rotate: tuple[float, float, float]
    scale: tuple[float, float, float]
    face: int
    vertex: int
    normal: int
    color: int
    texcoord: int
    cenv_count: int
    cenv_index: int


@dataclass
class Prim:
    material: int
    groups: np.ndarray  # (N,4) s16 rows: position, normal, colour, uv
    tris: np.ndarray  # (M,3) indices into groups


@dataclass
class Texture:
    name: str
    width: int
    height: int
    rgba: np.ndarray | None


@dataclass
class Hsf:
    data: bytes
    sections: dict[str, tuple[int, int]]
    strings: int
    objects: list[Obj]
    positions: list[np.ndarray]
    normals: list[np.ndarray]
    colors: list[np.ndarray]
    texcoords: list[np.ndarray]
    faces: list[list[Prim]]
    materials: list[tuple[int, int]]  # (texture count, first symbol)
    attribute_textures: list[int]
    symbols: list[int]
    textures: list[Texture] = field(default_factory=list)
    skins: list[dict] = field(default_factory=list)  # per cenv: {"single": [...], ...}


def is_hsf(head: bytes) -> bool:
    return head[:4] == MAGIC


def _cstr(d: bytes, o: int) -> str:
    if o >= len(d):
        return ""
    e = d.find(b"\0", o)
    return d[o : e if e >= 0 else len(d)].decode("latin-1", "replace")


def _components(d: bytes, off: int, count: int):
    """[(name offset, element count, absolute data offset, next data offset)]."""
    out = []
    base = off + count * 12
    comps = [struct.unpack_from(">3I", d, off + i * 12) for i in range(count)]
    for i, (name, n, data_off) in enumerate(comps):
        nxt = comps[i + 1][2] if i + 1 < count else None
        out.append((name, n, base + data_off, None if nxt is None else base + nxt))
    return out


def _vertex_section(d: bytes, sec, kind: str) -> list[np.ndarray]:
    off, count = sec
    out = []
    if not off or not count:
        return out
    for _name, n, start, nxt in _components(d, off, count):
        arr = np.zeros((0, 3), np.float32)
        try:
            if kind == "position":
                arr = np.frombuffer(d, ">f4", n * 3, start).reshape(n, 3).astype(np.float32)
            elif kind == "normal":
                span = (nxt - start) if nxt else len(d) - start
                if span >= n * 12 or span >= n * 12 - 8:
                    arr = np.frombuffer(d, ">f4", n * 3, start).reshape(n, 3).astype(np.float32)
                else:
                    arr = np.frombuffer(d, np.int8, n * 3, start).reshape(n, 3) / 127.0
                    arr = arr.astype(np.float32)
            elif kind == "color":
                arr = np.frombuffer(d, np.uint8, n * 4, start).reshape(n, 4) / 255.0
                arr = arr.astype(np.float32)
            elif kind == "texcoord":
                arr = np.frombuffer(d, ">f4", n * 2, start).reshape(n, 2).astype(np.float32)
        except ValueError:
            pass
        out.append(arr)
    return out


def _faces(d: bytes, sec) -> list[list[Prim]]:
    off, count = sec
    out: list[list[Prim]] = []
    if not off or not count:
        return out
    comps = _components(d, off, count)
    ext = off + count * 12 + sum(n for _, n, _, _ in comps) * 48
    for _name, n, start, _nxt in comps:
        prims: list[Prim] = []
        for i in range(n):
            p = start + i * 48
            if p + 48 > len(d):
                break
            ptype, flags = struct.unpack_from(">2H", d, p)
            mat = flags & 0xFFF
            if ptype in (2, 3):
                groups = np.frombuffer(d, ">i2", 16, p + 4).reshape(4, 4).astype(np.int32)
                if ptype == 2:
                    tris = np.array([[0, 1, 2]], np.uint32)
                    groups = groups[:3]
                else:
                    tris = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
            elif ptype == 4:
                head = np.frombuffer(d, ">i2", 12, p + 4).reshape(3, 4).astype(np.int32)
                cnt, idx = struct.unpack_from(">iI", d, p + 28)
                q = ext + idx * 8
                if cnt < 0 or q + cnt * 8 > len(d):
                    continue
                rest = np.frombuffer(d, ">i2", cnt * 4, q).reshape(cnt, 4).astype(np.int32)
                groups = np.concatenate([head, rest])
                m = len(groups)
                t = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(m - 2)]
                tris = np.array(t, np.uint32).reshape(-1, 3)
            else:
                continue
            prims.append(Prim(mat, groups, tris))
        out.append(prims)
    return out


def _objects(d: bytes, sec, strings: int) -> list[Obj]:
    off, count = sec
    out = []
    for i in range(count):
        o = off + i * OBJECT_SIZE
        if o + OBJECT_SIZE > len(d):
            break
        name_off, typ, _c, _rf, parent, _children, _sym = struct.unpack_from(">I6i", d, o)
        trs = struct.unpack_from(">9f", d, o + 0x1C)
        idx = struct.unpack_from(">8i", d, o + 0x100)
        cenv_count, cenv_index = struct.unpack_from(">2i", d, o + 0x134)
        out.append(
            Obj(
                _cstr(d, strings + name_off) if name_off != 0xFFFFFFFF else f"obj{i}",
                typ,
                parent,
                trs[0:3],
                trs[3:6],
                trs[6:9],
                idx[1],
                idx[2],
                idx[3],
                idx[4],
                idx[5],
                cenv_count,
                cenv_index,
            )
        )
    return out


def _textures(d: bytes, sec, pal_sec, strings: int) -> list[Texture]:
    from gcrip.formats import gx_texture

    off, count = sec
    out: list[Texture] = []
    if not off or not count:
        return out
    palettes = []
    poff, pcount = pal_sec
    if poff and pcount:
        pbase = poff + pcount * 16
        for i in range(pcount):
            _n, fmt, num, doff = struct.unpack_from(">IiIi", d, poff + i * 16)
            palettes.append((fmt, d[pbase + doff : pbase + doff + num * 2]))
    base = off + count * 0x20
    for i in range(count):
        o = off + i * 0x20
        if o + 0x20 > len(d):
            break
        name_off, _lod, fmt, bpp, w, h, _pal_n, _tint, pal_idx, _pad, doff = struct.unpack_from(
            ">IIBBHHHIiII", d, o
        )
        name = _cstr(d, strings + name_off) if name_off != 0xFFFFFFFF else f"tex{i}"
        gx = {0: 0 if bpp == 4 else 1, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 14}.get(fmt)
        pal = None
        if fmt in (9, 10, 11):
            gx = 8 if bpp == 4 else 9
            if 0 <= pal_idx < len(palettes):
                pal = palettes[pal_idx]
        rgba = None
        if gx is not None and 0 < w <= 2048 and 0 < h <= 2048:
            need = gx_texture.encoded_size(gx, w, h)
            body = d[base + doff : base + doff + need]
            if len(body) == need:
                try:
                    if pal is not None:
                        pfmt = pal[0] if pal[0] in (0, 1, 2) else 2
                        table = gx_texture.decode_palette(pfmt, pal[1], len(pal[1]) // 2)
                        rgba = gx_texture.decode(gx, w, h, body, palette=table)
                    else:
                        rgba = gx_texture.decode(gx, w, h, body)
                except Exception:  # noqa: BLE001
                    rgba = None
        out.append(Texture(name, w, h, rgba))
    return out


def _skins(d: bytes, sec) -> list[dict]:
    off, count = sec
    out: list[dict] = []
    if not off or not count:
        return out
    rigs = [struct.unpack_from(">9I", d, off + i * 36) for i in range(count)]
    base = off + count * 36
    parsed = []
    end = base
    for _name, s_off, d_off, m_off, s_n, d_n, m_n, _nv, _sb in rigs:
        single = [struct.unpack_from(">i4h", d, base + s_off + k * 12) for k in range(s_n)]
        double = [struct.unpack_from(">4i", d, base + d_off + k * 16) for k in range(d_n)]
        multi = [struct.unpack_from(">i4hi", d, base + m_off + k * 16) for k in range(m_n)]
        parsed.append((single, double, multi))
        end = max(end, base + s_off + s_n * 12, base + d_off + d_n * 16, base + m_off + m_n * 16)
    wbase = end
    for single, double, multi in parsed:
        dw = []
        for b1, b2, n, woff in double:
            for k in range(n):
                w, pi, pc, _ni, _nc = struct.unpack_from(">f4h", d, wbase + woff + k * 12)
                dw.append((b1, b2, w, pi, pc))
        mw = []
        for n, pi, pc, _ni, _nc, woff in multi:
            ws = [struct.unpack_from(">if", d, wbase + woff + k * 8) for k in range(n)]
            mw.append((pi, pc, ws))
        out.append({"single": single, "double": dw, "multi": mw})
    return out


def parse(d: bytes) -> Hsf:
    if not is_hsf(d[:4]) or len(d) < 0xB0:
        raise HsfError("not an HSF model")
    sections = {}
    for i, n in enumerate(_SECTIONS):
        sections[n] = struct.unpack_from(">2I", d, 8 + i * 8)
    strings = struct.unpack_from(">I", d, 0xA8)[0]
    objects = _objects(d, sections["object"], strings)
    positions = _vertex_section(d, sections["position"], "position")
    normals = _vertex_section(d, sections["normal"], "normal")
    colors = _vertex_section(d, sections["color"], "color")
    texcoords = _vertex_section(d, sections["texcoord"], "texcoord")
    faces = _faces(d, sections["face"])
    moff, mcount = sections["material"]
    materials = [struct.unpack_from(">2i", d, moff + i * 0x3C + 0x34) for i in range(mcount)]
    aoff, acount = sections["attribute"]
    attribute_textures = [
        struct.unpack_from(">i", d, aoff + i * 0x84 + 0x80)[0] for i in range(acount)
    ]
    soff, scount = sections["symbol"]
    symbols = list(struct.unpack_from(f">{scount}i", d, soff)) if soff and scount else []
    hsf = Hsf(
        d,
        sections,
        strings,
        objects,
        positions,
        normals,
        colors,
        texcoords,
        faces,
        materials,
        attribute_textures,
        symbols,
    )
    hsf.textures = _textures(d, sections["texture"], sections["palette"], strings)
    hsf.skins = _skins(d, sections["cenv"])
    return hsf


def material_texture(hsf: Hsf, material: int) -> int:
    """Texture index used by a material (its first attribute), or -1."""
    if not (0 <= material < len(hsf.materials)):
        return -1
    n, first = hsf.materials[material]
    if n <= 0 or not (0 <= first < len(hsf.symbols)):
        return -1
    attr = hsf.symbols[first]
    if not (0 <= attr < len(hsf.attribute_textures)):
        return -1
    return hsf.attribute_textures[attr]


@dataclass
class MeshOut:
    object_index: int
    name: str
    material: int
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None
    joints: np.ndarray | None
    weights: np.ndarray | None


def _position_weights(hsf: Hsf, obj: Obj, n: int):
    """(joints (n,4) u16, weights (n,4) f32) per position index, or None."""
    if obj.cenv_index < 0 or obj.cenv_count <= 0:
        return None
    joints = np.zeros((n, 4), np.uint16)
    weights = np.zeros((n, 4), np.float32)
    slot = np.zeros(n, np.int32)

    def add(pi: int, pc: int, bone: int, w: float) -> None:
        lo, hi = max(pi, 0), min(pi + pc, n)
        for v in range(lo, hi):
            s = slot[v]
            if s < 4:
                joints[v, s] = bone
                weights[v, s] = w
                slot[v] = s + 1

    for k in range(obj.cenv_index, min(obj.cenv_index + obj.cenv_count, len(hsf.skins))):
        skin = hsf.skins[k]
        for bone, pi, pc, _ni, _nc in skin["single"]:
            add(pi, pc, bone, 1.0)
        for b1, b2, w, pi, pc in skin["double"]:
            add(pi, pc, b1, w)
            add(pi, pc, b2, 1.0 - w)
        for pi, pc, ws in skin["multi"]:
            for bone, w in ws:
                add(pi, pc, bone, w)
    if not slot.any():
        return None
    tot = weights.sum(axis=1, keepdims=True)
    tot[tot == 0] = 1.0
    return joints, weights / tot


def _pick(arr: np.ndarray | None, idx: np.ndarray) -> np.ndarray | None:
    """Attribute rows for the given indices (-1 = unused; out of range -> row 0)."""
    if arr is None or len(arr) == 0 or (idx < 0).all():
        return None
    idx = np.where((idx >= 0) & (idx < len(arr)), idx, 0)
    return arr[idx]


def meshes(hsf: Hsf) -> list[MeshOut]:
    out: list[MeshOut] = []
    for oi, obj in enumerate(hsf.objects):
        if obj.type != MESH or not (0 <= obj.face < len(hsf.faces)):
            continue
        pos = hsf.positions[obj.vertex] if 0 <= obj.vertex < len(hsf.positions) else None
        if pos is None or len(pos) == 0:
            continue
        nrm = hsf.normals[obj.normal] if 0 <= obj.normal < len(hsf.normals) else None
        col = hsf.colors[obj.color] if 0 <= obj.color < len(hsf.colors) else None
        uv = hsf.texcoords[obj.texcoord] if 0 <= obj.texcoord < len(hsf.texcoords) else None
        skin = _position_weights(hsf, obj, len(pos))
        by_mat: dict[int, list[tuple[np.ndarray, np.ndarray]]] = {}
        for prim in hsf.faces[obj.face]:
            by_mat.setdefault(prim.material, []).append((prim.groups, prim.tris))
        for mat, chunks in by_mat.items():
            rows = []
            tris = []
            base = 0
            for groups, t in chunks:
                rows.append(groups)
                tris.append(t + base)
                base += len(groups)
            rows_a = np.concatenate(rows)
            tris_a = np.concatenate(tris)
            uniq, inverse = np.unique(rows_a, axis=0, return_inverse=True)
            pi = uniq[:, 0]
            ok = (pi >= 0) & (pi < len(pos))
            if not ok.all():
                keep = ok[inverse.reshape(-1)[tris_a.reshape(-1)]].reshape(-1, 3).all(axis=1)
                tris_a = tris_a[keep]
                pi = np.where(ok, pi, 0)
            positions = pos[pi]

            normals = _pick(nrm, uniq[:, 1])
            colors = _pick(col, uniq[:, 2])
            uvs = _pick(uv, uniq[:, 3])
            joints = weights = None
            if skin is not None:
                joints, weights = skin[0][pi], skin[1][pi]
            indices = inverse.reshape(-1)[tris_a.reshape(-1)].astype(np.uint32)
            if len(indices) < 3:
                continue
            out.append(
                MeshOut(
                    oi, obj.name, mat, positions, indices, normals, uvs, colors, joints, weights
                )
            )
    return out
