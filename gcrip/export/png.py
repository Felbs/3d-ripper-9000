"""Minimal PNG writer (RGBA8), no Pillow dependency."""

from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_rgba(img: np.ndarray, level: int = 6) -> bytes:
    """img: (H, W, 4) uint8 -> PNG bytes."""
    if img.ndim != 3 or img.shape[2] != 4 or img.dtype != np.uint8:
        raise ValueError("expected (H, W, 4) uint8")
    h, w = img.shape[:2]
    rows = np.ascontiguousarray(img).reshape(h, w * 4)
    raw = np.concatenate([np.zeros((h, 1), np.uint8), rows], axis=1).tobytes()
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, level))
        + _chunk(b"IEND", b"")
    )


def write_rgba(path, img: np.ndarray) -> None:
    with open(path, "wb") as f:
        f.write(encode_rgba(img))
