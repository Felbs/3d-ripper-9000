"""Tiny software renderer for model thumbnails (point-splat with z-buffer).

Not pretty, but fully vectorized in numpy and dependency-free; good enough to
recognize a model in report.html and to sanity-check exports.
"""

from __future__ import annotations

import numpy as np


def render(
    positions: np.ndarray,
    triangles: np.ndarray,
    colors: np.ndarray | None = None,
    size: int = 256,
    seed: int = 1,
    uvs: np.ndarray | None = None,
    tri_texture: np.ndarray | None = None,
    textures: list[np.ndarray | None] | None = None,
) -> np.ndarray:
    """positions (N,3), triangles (T,3) int, colors (T,3) float 0..1 per triangle.
    Optional texturing: uvs (N,2) per vertex, tri_texture (T,) int index into
    `textures` (-1 = untextured, use `colors`), textures = list of RGBA arrays.
    Returns (size,size,4) uint8 RGBA, transparent background."""
    img = np.zeros((size, size, 4), np.uint8)
    if len(triangles) == 0 or len(positions) == 0:
        return img
    p = positions.astype(np.float64)
    a, b, c = p[triangles[:, 0]], p[triangles[:, 1]], p[triangles[:, 2]]
    fn = np.cross(b - a, c - a)
    area = np.linalg.norm(fn, axis=1) * 0.5
    ok = area > 0
    a, b, c, fn, area = a[ok], b[ok], c[ok], fn[ok], area[ok]
    if colors is not None:
        colors = colors[ok]
    textured = uvs is not None and tri_texture is not None and textures
    if textured:
        tri_texture = tri_texture[ok]
        tri_ok = triangles[ok]
        ua, ub, uc = uvs[tri_ok[:, 0]], uvs[tri_ok[:, 1]], uvs[tri_ok[:, 2]]
    if len(a) == 0:
        return img
    fn = fn / np.linalg.norm(fn, axis=1, keepdims=True)

    # 3/4 view: rotate 30 deg around Y then 20 deg down around X
    def rot_y(t):
        ct, st = np.cos(t), np.sin(t)
        return np.array([[ct, 0, st], [0, 1, 0], [-st, 0, ct]])

    def rot_x(t):
        ct, st = np.cos(t), np.sin(t)
        return np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]])

    R = rot_x(np.radians(20)) @ rot_y(np.radians(-35))
    allp = np.concatenate([a, b, c])
    center = (allp.min(axis=0) + allp.max(axis=0)) / 2
    va, vb, vc = (a - center) @ R.T, (b - center) @ R.T, (c - center) @ R.T
    vn = fn @ R.T
    extent = np.abs(np.concatenate([va, vb, vc])).max() or 1.0
    scale = (size * 0.46) / extent

    # sample points per triangle proportional to screen area
    screen_area = area * scale * scale
    n_pts = np.clip((screen_area * 2.0).astype(np.int64), 1, 4000)
    total = int(n_pts.sum())
    if total > 3_000_000:
        n_pts = np.maximum(1, (n_pts * (3_000_000 / total)).astype(np.int64))
        total = int(n_pts.sum())
    tri_ids = np.repeat(np.arange(len(a)), n_pts)
    rng = np.random.default_rng(seed)
    r1 = np.sqrt(rng.random(total))
    r2 = rng.random(total)
    w0 = 1 - r1
    w1 = r1 * (1 - r2)
    w2 = r1 * r2
    pts = va[tri_ids] * w0[:, None] + vb[tri_ids] * w1[:, None] + vc[tri_ids] * w2[:, None]
    # also the vertices themselves so thin things show up
    n_tri = len(a)
    pts = np.concatenate([pts, va, vb, vc])
    if textured:
        puv = ua[tri_ids] * w0[:, None] + ub[tri_ids] * w1[:, None] + uc[tri_ids] * w2[:, None]
        puv = np.concatenate([puv, ua, ub, uc])
    tri_ids = np.concatenate([tri_ids, np.arange(n_tri), np.arange(n_tri), np.arange(n_tri)])

    x = (pts[:, 0] * scale + size / 2).astype(np.int64)
    y = (-pts[:, 1] * scale + size / 2).astype(np.int64)
    z = pts[:, 2]
    inb = (x >= 0) & (x < size) & (y >= 0) & (y < size)
    x, y, z, tri_ids = x[inb], y[inb], z[inb], tri_ids[inb]
    if textured:
        puv = puv[inb]
    if len(x) == 0:
        return img

    base = colors if colors is not None else np.full((len(a), 3), 0.75)
    pcol = base[tri_ids].copy()
    keep = np.ones(len(x), dtype=bool)
    if textured:
        ptex = tri_texture[tri_ids]
        for ti in np.unique(ptex):
            if ti < 0 or ti >= len(textures) or textures[ti] is None:
                continue
            tex = textures[ti]
            th, tw = tex.shape[:2]
            sel = ptex == ti
            tx = np.floor(puv[sel, 0] * tw).astype(np.int64) % tw
            ty = np.floor(puv[sel, 1] * th).astype(np.int64) % th
            texel = tex[ty, tx]
            pcol[sel] = texel[:, :3] / 255.0
            # transparent texels don't occlude (approximates alpha test / blending)
            keep[np.flatnonzero(sel)[texel[:, 3] < 96]] = False
    x, y, z, tri_ids, pcol = x[keep], y[keep], z[keep], tri_ids[keep], pcol[keep]
    if len(x) == 0:
        return img

    pix = y * size + x
    zbuf = np.full(size * size, -np.inf)
    np.maximum.at(zbuf, pix, z)
    front = z >= zbuf[pix] - 1e-9
    pix, tri_ids, pcol = pix[front], tri_ids[front], pcol[front]

    light = np.array([0.3, 0.6, 0.75])
    light /= np.linalg.norm(light)
    lam = np.abs(vn @ light)
    shade = 0.35 + 0.65 * lam
    rgb = np.clip(pcol * shade[tri_ids][:, None], 0, 1)
    flat = img.reshape(-1, 4)
    flat[pix, :3] = (rgb * 255).astype(np.uint8)
    flat[pix, 3] = 255
    return img
