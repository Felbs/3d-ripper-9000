"""Traveller's Tales NU2 geometry as shipped on GameCube (LEGO Star Wars: The Video Game
``.gsc`` / ``.csc``, and the same vertex stream inside other early TT titles).  The
container is the little-endian ``NU20`` chunk tree (NTBL names, TST0 textures, MS00
materials, OBJ0 objects ...); inside OBJ0 every mesh is a run of tagged blocks:

- ``03 01 00 01 | u8 fmt|0x80 | u8 count | u8 0x6c`` then ``count`` vertices of ``f32 x y z
  nz`` (16 bytes);
- ``01 00 00 05 | u8 | u8 count | u8 0x6d`` then ``count`` x ``s16 u, v, nx, ny`` (/4096);
- ``00 00 00 05 | u8 | u8 count | u8 0x6e`` then ``count`` RGBA8 colours (optional);
- ``04 80 count 65`` a second UV set (optional), ``01 01 00 01 | 00 03 00 14`` end.
Each block is one triangle strip in vertex order (there is no index list).  Material /
texture binding is not decoded yet: meshes come out untextured with UVs and normals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

MARK = re.compile(rb"\x03\x01\x00\x01")
NU20 = b"NU20"
NU20_LE = b"02UN"
GSC0 = b"GSC0"


@dataclass
class Mesh:
    positions: np.ndarray
    normals: np.ndarray | None
    uvs: np.ndarray | None
    colors: np.ndarray | None
    indices: np.ndarray


def is_nu2(head: bytes) -> bool:
    return head[:4] in (NU20, NU20_LE, GSC0)


def meshes(d: bytes) -> list[Mesh]:
    out: list[Mesh] = []
    n = len(d)
    for m in MARK.finditer(d):
        p = m.start() + 4
        if p + 4 > n:
            break
        cnt, kind = d[p + 2], d[p + 3]
        if kind != 0x6C or cnt < 3:
            continue
        q = p + 4
        if q + cnt * 16 > n:
            continue
        v = np.frombuffer(d, "<f4", cnt * 4, q).reshape(cnt, 4)
        if not np.isfinite(v).all() or np.abs(v[:, :3]).max() > 1e6:
            continue
        q += cnt * 16
        uv = nrm = col = None
        if d[q : q + 4] == b"\x01\x00\x00\x05" and d[q + 6] == cnt and d[q + 7] == 0x6D:
            if q + 8 + cnt * 8 <= n:
                a = np.frombuffer(d, "<i2", cnt * 4, q + 8).reshape(cnt, 4).astype(np.float32)
                a /= 4096.0
                uv = a[:, :2].copy()
                nrm = np.stack([a[:, 2], a[:, 3], v[:, 3]], axis=1).astype(np.float32)
                ln = np.linalg.norm(nrm, axis=1, keepdims=True)
                ln[ln == 0] = 1.0
                nrm = (nrm / ln).astype(np.float32)
            q += 8 + cnt * 8
        is_col = d[q : q + 4] == b"\x00\x00\x00\x05" and d[q + 6] == cnt and d[q + 7] == 0x6E
        if is_col and q + 8 + cnt * 4 <= n:
            col = np.frombuffer(d, np.uint8, cnt * 4, q + 8).reshape(cnt, 4) / 255.0
            col = col.astype(np.float32)
        tris = [(k, k + 2, k + 1) if k % 2 else (k, k + 1, k + 2) for k in range(cnt - 2)]
        out.append(
            Mesh(
                v[:, :3].astype(np.float32),
                nrm,
                uv,
                col,
                np.array(tris, np.uint32).reshape(-1),
            )
        )
    return out
