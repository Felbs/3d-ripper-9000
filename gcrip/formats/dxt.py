"""DXT1 / DXT3 / DXT5 (S3TC, PC block order) to RGBA8."""

from __future__ import annotations

import numpy as np


def _rgb565(v: np.ndarray) -> np.ndarray:
    r = ((v >> 11) & 31) * 255 // 31
    g = ((v >> 5) & 63) * 255 // 63
    b = (v & 31) * 255 // 31
    return np.stack([r, g, b], axis=-1).astype(np.int32)


def _color_blocks(c0: np.ndarray, c1: np.ndarray, idx: np.ndarray, dxt1: bool) -> np.ndarray:
    """(N, 4, 4, 4) RGBA from the colour halves of N blocks."""
    n = len(c0)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    pal = np.zeros((n, 4, 4), np.int32)
    pal[:, 0, :3] = p0
    pal[:, 1, :3] = p1
    pal[:, :, 3] = 255
    four = (c0 > c1) | (not dxt1)
    pal[:, 2, :3] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3, :3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    if dxt1:
        pal[~four, 3, 3] = 0
    sel = np.stack([(idx >> (2 * k)) & 3 for k in range(16)], axis=1)  # (N, 16) row-major
    out = pal[np.arange(n)[:, None], sel]  # (N, 16, 4)
    return out.reshape(n, 4, 4, 4).astype(np.uint8)


def decode(data: bytes, width: int, height: int, fmt: str) -> np.ndarray:
    """Decode a PC-order DXT image; fmt in ('DXT1', 'DXT3', 'DXT5')."""
    bw, bh = max(width // 4, 1), max(height // 4, 1)
    n = bw * bh
    bs = 8 if fmt == "DXT1" else 16
    buf = np.frombuffer(data, np.uint8, n * bs).reshape(n, bs)
    if fmt == "DXT1":
        c0 = buf[:, 0].astype(np.uint32) | (buf[:, 1].astype(np.uint32) << 8)
        c1 = buf[:, 2].astype(np.uint32) | (buf[:, 3].astype(np.uint32) << 8)
        idx = (
            buf[:, 4].astype(np.uint32)
            | (buf[:, 5].astype(np.uint32) << 8)
            | (buf[:, 6].astype(np.uint32) << 16)
            | (buf[:, 7].astype(np.uint32) << 24)
        )
        blocks = _color_blocks(c0, c1, idx, True)
    else:
        c0 = buf[:, 8].astype(np.uint32) | (buf[:, 9].astype(np.uint32) << 8)
        c1 = buf[:, 10].astype(np.uint32) | (buf[:, 11].astype(np.uint32) << 8)
        idx = (
            buf[:, 12].astype(np.uint32)
            | (buf[:, 13].astype(np.uint32) << 8)
            | (buf[:, 14].astype(np.uint32) << 16)
            | (buf[:, 15].astype(np.uint32) << 24)
        )
        blocks = _color_blocks(c0, c1, idx, False)
        if fmt == "DXT3":
            a = buf[:, :8].astype(np.uint32)
            nib = np.stack([(a[:, k // 2] >> (4 * (k % 2))) & 15 for k in range(16)], axis=1)
            blocks[..., 3] = (nib * 17).reshape(n, 4, 4).astype(np.uint8)
        else:  # DXT5
            a0 = buf[:, 0].astype(np.int32)
            a1 = buf[:, 1].astype(np.int32)
            bits = np.zeros(n, np.uint64)
            for k in range(6):
                bits |= buf[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
            sel = np.stack(
                [((bits >> np.uint64(3 * k)) & np.uint64(7)).astype(np.int32) for k in range(16)],
                axis=1,
            )
            pal = np.zeros((n, 8), np.int32)
            pal[:, 0], pal[:, 1] = a0, a1
            gt = a0 > a1
            for k in range(1, 7):
                pal[:, k + 1] = np.where(gt, ((7 - k) * a0 + k * a1) // 7, 0)
            for k in range(1, 5):
                pal[~gt, k + 1] = ((5 - k) * a0[~gt] + k * a1[~gt]) // 5
            pal[~gt, 6] = 0
            pal[~gt, 7] = 255
            blocks[..., 3] = pal[np.arange(n)[:, None], sel].reshape(n, 4, 4).astype(np.uint8)
    img = blocks.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.ascontiguousarray(img[:height, :width])
