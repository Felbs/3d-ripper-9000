"""Minimal DDS reader: DXT1 / DXT3 / DXT5 and uncompressed 32-bit RGBA, top mip only."""

from __future__ import annotations

import struct

import numpy as np


class DdsError(ValueError):
    pass


def _rgb565(v: np.ndarray) -> np.ndarray:
    r = ((v >> 11) & 31) * 255 // 31
    g = ((v >> 5) & 63) * 255 // 63
    b = (v & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.uint8)


def _dxt1_colors(block: np.ndarray, dxt1: bool) -> tuple[np.ndarray, np.ndarray]:
    """(colours (N,4,3) u8, alpha (N,4) u8) per block from the colour half of a block."""
    c0 = block[:, 0].astype(np.uint16) | (block[:, 1].astype(np.uint16) << 8)
    c1 = block[:, 2].astype(np.uint16) | (block[:, 3].astype(np.uint16) << 8)
    p0, p1 = _rgb565(c0).astype(np.int32), _rgb565(c1).astype(np.int32)
    cols = np.zeros((len(block), 4, 3), np.int32)
    alpha = np.full((len(block), 4), 255, np.uint8)
    cols[:, 0], cols[:, 1] = p0, p1
    four = (c0 > c1) | (not dxt1)
    cols[:, 2] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    cols[:, 3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    alpha[:, 3] = np.where(four, 255, 0)
    return cols.astype(np.uint8), alpha


def _blocks_to_image(w: int, h: int, cols, alpha, idx) -> np.ndarray:
    """Assemble 4x4 blocks: cols (n,4,3), alpha (n,4), idx (n,16) 2-bit selectors."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    n = bw * bh
    cols, alpha, idx = cols[:n], alpha[:n], idx[:n]
    rows = np.arange(n)[:, None]
    rgb = cols[rows, idx]  # (n,16,3)
    a = alpha[rows, idx]  # (n,16)
    img = np.zeros((bh * 4, bw * 4, 4), np.uint8)
    img[..., :3] = rgb.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 3)
    img[..., 3] = a.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return img[:h, :w]


def _selectors(words: np.ndarray) -> np.ndarray:
    """(n,16) 2-bit indices from the 4 selector bytes of each block."""
    out = np.zeros((len(words), 16), np.int64)
    for row in range(4):
        b = words[:, row].astype(np.int64)
        for k in range(4):
            out[:, row * 4 + k] = (b >> (2 * k)) & 3
    return out


def decode(data: bytes) -> np.ndarray:
    """RGBA (h,w,4) u8 of the top mip level."""
    if data[:4] != b"DDS " or len(data) < 128:
        raise DdsError("not a DDS file")
    h, w = struct.unpack_from("<II", data, 12)
    fourcc = data[84:88]
    body = data[128:]
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    n = bw * bh
    if fourcc == b"DXT1":
        blk = np.frombuffer(body, np.uint8, n * 8).reshape(n, 8)
        cols, alpha = _dxt1_colors(blk[:, :4], True)
        return _blocks_to_image(w, h, cols, alpha, _selectors(blk[:, 4:8]))
    if fourcc in (b"DXT3", b"DXT5"):
        blk = np.frombuffer(body, np.uint8, n * 16).reshape(n, 16)
        cols, _ = _dxt1_colors(blk[:, 8:12], False)
        opaque = np.full((n, 4), 255, np.uint8)
        img = _blocks_to_image(w, h, cols, opaque, _selectors(blk[:, 12:16]))
        if fourcc == b"DXT3":
            a4 = np.zeros((n, 16), np.uint8)
            for i in range(8):
                a4[:, 2 * i] = (blk[:, i] & 15) * 17
                a4[:, 2 * i + 1] = (blk[:, i] >> 4) * 17
        else:
            a0, a1 = blk[:, 0].astype(np.int32), blk[:, 1].astype(np.int32)
            bits = np.zeros(n, np.int64)
            for i in range(6):
                bits |= blk[:, 2 + i].astype(np.int64) << (8 * i)
            table = np.zeros((n, 8), np.int32)
            table[:, 0], table[:, 1] = a0, a1
            gt = a0 > a1
            for i in range(2, 8):
                table[:, i] = np.where(
                    gt, ((8 - i) * a0 + (i - 1) * a1) // 7,
                    np.where(i < 6, ((6 - i) * a0 + (i - 1) * a1) // 5, np.where(i == 6, 0, 255)),
                )
            a4 = np.zeros((n, 16), np.uint8)
            for t in range(16):
                a4[:, t] = np.take_along_axis(table, ((bits >> (3 * t)) & 7)[:, None], 1)[:, 0]
        alpha = a4.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)[:h, :w]
        img[..., 3] = alpha
        return img
    bpp = struct.unpack_from("<I", data, 88)[0]
    if bpp == 32:
        px = np.frombuffer(body, np.uint8, w * h * 4).reshape(h, w, 4)
        masks = struct.unpack_from("<IIII", data, 92)
        order = [masks.index(m) for m in (0xFF, 0xFF00, 0xFF0000, 0xFF000000) if m in masks]
        if len(order) == 4:
            return px[..., order].copy()
        return px.copy()
    raise DdsError(f"unsupported DDS {fourcc!r} {bpp} bpp")
