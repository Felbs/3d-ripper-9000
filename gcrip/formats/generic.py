"""Format-agnostic container cracking: archive tables and compression streams found by
their structure instead of a known magic.

Most studio archives are one of a handful of shapes - a table of (offset, size) records,
sometimes with a name-hash or flags column, followed by the members - and most studio
compression is zlib, or a GBA/DS-style LZ10/LZ11, or an Okumura LZSS variant.  Recognising
those shapes is enough to open the majority of GameCube containers no plugin knows.

`find_toc` returns members for a blob that carries such a table; `try_decompress` returns
the decompressed payload for a blob that is one compression stream (or None).  Both are
validators as much as parsers: a table must cover most of the file with non-overlapping,
in-order members, and a decompressed stream must inflate to its declared size and look
less random than what it came from.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# archive tables
# ---------------------------------------------------------------------------


@dataclass
class Member:
    name: str
    offset: int
    size: int
    packed: bool = False  # size differs from a second "unpacked size" column


def _table_ok(offs: np.ndarray, sizes: np.ndarray, n: int, table_end: int) -> float:
    """0 if the (offset, size) rows cannot be a member table, else a quality score:
    entry count, boosted when offsets are 16/32-aligned (almost every real archive)."""
    k = len(offs)
    if k < 4:
        return 0.0
    # empty members happen (a zero-size placeholder row); more than a few do not
    if not (np.all(offs >= table_end) and np.all(offs < n) and np.mean(sizes > 0) >= 0.9):
        return 0.0
    ends = offs + sizes
    if np.any(ends > n):
        return 0.0
    order = np.argsort(offs, kind="stable")
    o, e = offs[order], ends[order]
    if np.any(o[1:] < e[:-1]):  # overlapping members
        return 0.0
    if float(sizes.sum()) / max(1, n - table_end) < 0.4:
        return 0.0
    aligned = float(np.mean(offs % 16 == 0))
    if float(np.mean(offs % 4 == 0)) < 0.95:
        return 0.0
    if not _members_plausible(sizes, n - table_end):
        return 0.0
    return k * (1.0 + aligned)


MIN_MEMBER = 16  # bytes: a table whose members are mostly smaller is a number array


def _members_plausible(sizes: np.ndarray, span: int) -> bool:
    """A member table describes files: most members are at least MIN_MEMBER bytes and the
    average member is not tiny (an increasing u32 array - sample offsets, loop points -
    would otherwise pass as thousands of 4-byte "members")."""
    k = len(sizes)
    if k == 0:
        return False
    if float(np.mean(sizes >= MIN_MEMBER)) < 0.75:
        return False
    return float(sizes.sum()) / k >= 64 or k <= 16 and span >= 64 * k


def _header_pointers(data: bytes, n: int) -> list[int]:
    """u32 values in the first 64 bytes (both endians) that point inside the blob: many
    archives put the table offset in their header."""
    out = set()
    head = data[:64]
    for i in range(0, len(head) - 3, 4):
        for endian in ("big", "little"):
            v = int.from_bytes(head[i : i + 4], endian)
            if 8 <= v < n // 2 and v % 4 == 0:
                out.add(v)
    return sorted(out)


#: Work cap per call, counted in (base, stride) pairs examined, NOT in seconds.
#:
#: This used to be a 0.15-second deadline, and that made `expand()` **non-deterministic**: the
#: same bytes gave a different member list depending on machine load.  The manifest walk names a
#: container's members once and the rip fetches them later, so when the two disagreed the model
#: died on a bare `KeyError` on its own path - 36 recorded examples across 8 discs, all of them
#: `generic`'s own `gNNNN` member names.  A container expansion has to be a pure function of its
#: bytes.
TOC_MAX_WORK = 4096


def find_toc(
    data: bytes,
    max_scan: int = 512,
    max_rows: int = 2048,
    max_work: int = TOC_MAX_WORK,
    offset_only: bool = True,
) -> list[Member] | None:
    """Look for an (offset, size) record table near the start of the blob (or where a
    header pointer says).  Tries record strides 4..64 and every pair of u32 columns as
    (offset, size), in either file order or arbitrary order (hash-sorted tables), with
    offsets absolute or relative to the end of the table; a table wins on entry count.
    Falls back to offset-only tables (sizes = gaps).  Returns None when nothing holds."""
    n = len(data)
    if n < 64:
        return None
    limit = min(max_scan, n // 2)
    bases = sorted(set(range(0, limit, 4)) | set(_header_pointers(data, n)))
    # one big-endian u32 view of the head of the blob covers every 4-aligned base/stride
    head_words = min(n // 4, (max(bases) // 4) + max_rows * 16 + 16)
    words = np.frombuffer(data, ">u4", head_words).astype(np.int64)
    best: tuple[float, list[Member]] | None = None
    work = 0
    # base-major: the first bases (where real tables live) see every stride before the
    # work cap can run out
    for base in bases:
        if work >= max_work:
            return best[1] if best else None
        for stride in range(4, 65, 4):
            work += 1
            cols = stride // 4
            b = base // 4
            rows = min(max_rows, (len(words) - b) // cols)
            if rows < 4:
                continue
            m = words[b : b + rows * cols].reshape(rows, cols)
            # an offset column has its first four values inside the blob and distinct;
            # a size column has them positive and inside the blob
            h = m[:4]
            hs = np.sort(h, axis=0)
            head_ok = (h < n).all(axis=0) & (hs[1:] != hs[:-1]).all(axis=0)
            size_ok = ((h > 0) & (h <= n)).all(axis=0)
            if not head_ok.any():
                continue
            size_cols = np.flatnonzero(size_ok)
            for oc in np.flatnonzero(head_ok):
                col = m[:, oc]
                inb = col < n
                k_any = int(np.argmin(inb)) if not inb.all() else len(col)
                if k_any < 4:
                    continue
                for sc in size_cols:
                    if sc == oc:
                        continue
                    sizes_all = m[:k_any, sc]
                    for rel in (0, None):
                        table_end = base + k_any * stride
                        offs = col[:k_any] + (table_end if rel is None else 0)
                        good = (offs >= table_end) & (offs + sizes_all <= n) & (sizes_all >= 0)
                        kk = int(np.argmin(good)) if not good.all() else k_any
                        if kk < 4:
                            continue
                        score = _table_ok(offs[:kk], sizes_all[:kk], n, base + kk * stride)
                        if score > 0 and (best is None or score > best[0]):
                            rows_ = zip(offs[:kk], sizes_all[:kk], strict=True)
                            best = (
                                score,
                                [
                                    Member(f"{i:04d}", int(o), int(s))
                                    for i, (o, s) in enumerate(rows_)
                                ],
                            )
                # offset-only table: sizes are the gaps to the next offset (weak evidence:
                # members must be 16-aligned like real archives, and callers walking the
                # members of a table we found do not get to use it again)
                if not offset_only:
                    continue
                col_k = col[:k_any]
                for rel in (0, None):
                    table_end = base + k_any * stride
                    offs = col_k + (table_end if rel is None else 0)
                    inc = offs[1:] > offs[:-1]
                    kk = int(np.argmin(inc)) + 1 if not inc.all() else len(offs)
                    if kk < 4 or offs[0] < base + kk * stride or offs[kk - 1] >= n:
                        continue
                    o = offs[:kk]
                    if np.mean(o % 16 == 0) < 0.9:
                        continue
                    sizes = np.diff(np.append(o, n))
                    if not _members_plausible(sizes, n - o[0]):
                        continue
                    if float(sizes.sum()) / max(1, n - o[0]) >= 0.9:
                        score = kk * 0.5 * (1.0 + float(np.mean(o % 16 == 0)))
                        if best is None or score > best[0]:
                            rows_ = zip(o, sizes, strict=True)
                            best = (
                                score,
                                [
                                    Member(f"{i:04d}", int(a), int(s))
                                    for i, (a, s) in enumerate(rows_)
                                ],
                            )
    return best[1] if best else None


# ---------------------------------------------------------------------------
# compression
# ---------------------------------------------------------------------------


def _entropy(b: bytes) -> float:
    if not b:
        return 0.0
    c = np.bincount(np.frombuffer(b, np.uint8), minlength=256).astype(np.float64)
    c = c[c > 0] / len(b)
    return float(-(c * np.log2(c)).sum())


def lz10(data: bytes, out_size: int, pos: int = 0) -> bytes:
    """GBA/DS LZ10 body: flag byte, 8 tokens, 2-byte back-refs (len 3..18, dist 1..4096)."""
    out = bytearray()
    n = len(data)
    while len(out) < out_size and pos < n:
        flags = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if len(out) >= out_size or pos >= n:
                break
            if flags & (1 << bit):
                if pos + 1 >= n:
                    raise ValueError("truncated")
                b0, b1 = data[pos], data[pos + 1]
                pos += 2
                length = (b0 >> 4) + 3
                dist = ((b0 & 0xF) << 8 | b1) + 1
                if dist > len(out):
                    raise ValueError("back-reference before start")
                for _ in range(length):
                    out.append(out[-dist])
            else:
                out.append(data[pos])
                pos += 1
    if len(out) != out_size:
        raise ValueError("short output")
    return bytes(out)


def lz11(data: bytes, out_size: int, pos: int = 0) -> bytes:
    """DS LZ11 body: like LZ10 with 2/3/4-byte back-references."""
    out = bytearray()
    n = len(data)
    while len(out) < out_size and pos < n:
        flags = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if len(out) >= out_size or pos >= n:
                break
            if not flags & (1 << bit):
                out.append(data[pos])
                pos += 1
                continue
            b0 = data[pos]
            ind = b0 >> 4
            if ind == 0:
                length = (b0 << 4 | data[pos + 1] >> 4) + 0x11
                dist = ((data[pos + 1] & 0xF) << 8 | data[pos + 2]) + 1
                pos += 3
            elif ind == 1:
                length = ((b0 & 0xF) << 12 | data[pos + 1] << 4 | data[pos + 2] >> 4) + 0x111
                dist = ((data[pos + 2] & 0xF) << 8 | data[pos + 3]) + 1
                pos += 4
            else:
                length = ind + 1
                dist = ((b0 & 0xF) << 8 | data[pos + 1]) + 1
                pos += 2
            if dist > len(out):
                raise ValueError("back-reference before start")
            for _ in range(length):
                out.append(out[-dist])
    if len(out) != out_size:
        raise ValueError("short output")
    return bytes(out)


def lzss_okumura(
    data: bytes,
    out_size: int,
    pos: int = 0,
    *,
    n_bits: int = 12,
    f_bits: int = 4,
    threshold: int = 2,
    init: int = 0x20,
) -> bytes:
    """Classic Okumura LZSS: ring buffer 2^n_bits, flag byte with bit 1 = literal,
    16-bit (position, length-threshold) references.  Used by many GC titles."""
    ring_n = 1 << n_bits
    ring = bytearray([init]) * ring_n
    r = ring_n - ((1 << f_bits) + threshold)
    out = bytearray()
    n = len(data)
    flags = 0
    while len(out) < out_size:
        flags >>= 1
        if not flags & 0x100:
            if pos >= n:
                break
            flags = data[pos] | 0xFF00
            pos += 1
        if flags & 1:
            if pos >= n:
                break
            c = data[pos]
            pos += 1
            out.append(c)
            ring[r] = c
            r = (r + 1) & (ring_n - 1)
        else:
            if pos + 1 >= n:
                break
            b0, b1 = data[pos], data[pos + 1]
            pos += 2
            p = b0 | ((b1 >> f_bits) << 8)
            length = (b1 & ((1 << f_bits) - 1)) + threshold + 1
            for k in range(length):
                c = ring[(p + k) & (ring_n - 1)]
                out.append(c)
                ring[r] = c
                r = (r + 1) & (ring_n - 1)
                if len(out) >= out_size:
                    break
    if len(out) != out_size:
        raise ValueError("short output")
    return bytes(out)


def _plausible_size(v: int, packed: int) -> bool:
    # literal-heavy streams can be ~12% larger than their payload
    return packed * 0.8 < v <= packed * 64 + 4096


def try_zlib(data: bytes, max_out: int = 256 << 20) -> tuple[str, bytes] | None:
    """zlib (header at offset 0..16) or raw deflate (at 0/4/8/16): cheap, C-speed."""
    n = len(data)
    if n < 16:
        return None
    ent_in = _entropy(data[: 1 << 16])

    def ok(out: bytes) -> bool:
        small_enough = 16 <= len(out) <= max_out
        return small_enough and (ent_in <= 6.5 or _entropy(out[: 1 << 16]) <= ent_in)

    for off in range(0, 17):
        if data[off : off + 1] == b"\x78":
            try:
                out = zlib.decompress(data[off:])
            except zlib.error:
                continue
            if ok(out):
                return f"zlib@{off}", out
    for off in (0, 4, 8, 16):
        try:
            d = zlib.decompressobj(-15)
            out = d.decompress(data[off:])
        except zlib.error:
            continue
        if d.eof and ok(out):
            return f"deflate@{off}", out
    return None


def try_decompress(data: bytes, max_out: int = 256 << 20) -> tuple[str, bytes] | None:
    """(scheme, payload) if the whole blob is one compression stream we can open.

    Layouts tried: zlib / raw deflate at offset 0..16; LZ10/LZ11 with the 0x10/0x11 tag
    and 24-bit size; `u32 size` + LZ10/LZ11/LZSS body; LZSS after a 4/8/16-byte header
    whose first u32 (BE or LE) is the output size.  Every hit must reach its declared size
    and be less random than the input."""
    n = len(data)
    if n < 16:
        return None
    ent_in = _entropy(data[: 1 << 16])

    def accept(scheme: str, out: bytes) -> tuple[str, bytes] | None:
        if len(out) < 16 or len(out) > max_out:
            return None
        if _entropy(out[: 1 << 16]) > ent_in + 0.05 and ent_in > 6.5:
            return None
        return scheme, out

    z = try_zlib(data, max_out)
    if z is not None:
        return z

    # LZ10 / LZ11 with tag byte + 24-bit size
    tag = data[0]
    if tag in (0x10, 0x11):
        size = int.from_bytes(data[1:4], "little")
        if _plausible_size(size, n) and size <= max_out:
            try:
                out = (lz10 if tag == 0x10 else lz11)(data, size, 4)
                if r := accept("lz10" if tag == 0x10 else "lz11", out):
                    return r
            except (ValueError, IndexError):
                pass

    # size-prefixed bodies
    for hdr in (4, 8, 16):
        for endian in ("big", "little"):
            size = int.from_bytes(data[:4], endian)
            if not _plausible_size(size, n) or size > max_out:
                continue
            for name, fn in (("lzss", lzss_okumura), ("lz10", lz10), ("lz11", lz11)):
                try:
                    out = fn(data, size, hdr)
                except (ValueError, IndexError):
                    continue
                if r := accept(f"{name}@{hdr}", out):
                    return r
    return None


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """Container-plugin style expansion: a decompressed payload, or the table members."""
    dec = try_decompress(data)
    if dec is not None:
        return [(f"{dec[0]}.bin", dec[1])]
    toc = find_toc(data)
    if toc:
        return [(m.name, data[m.offset : m.offset + m.size]) for m in toc]
    return []


def looks_like_text(head: bytes) -> bool:
    sample = head[:64]
    if not sample:
        return False
    printable = sum(1 for c in sample if 32 <= c < 127 or c in (9, 10, 13))
    return printable / len(sample) > 0.9


_KNOWN_MAGICS = (
    b"THP",
    b"RIFF",
    b"BIK",
    b"HVQM",
    b"\x89PNG",
    b"\xff\xd8",
    b"TPL",
    b"J3D",
    b"RARC",
    b"Yaz0",
    b"Yay0",
    b"U\xaa8-",
    b"AFS\0",
    b"BIGF",
    b"BIG4",
    b"TERF",
    b"SHPI",
    b"RSD6",
)


def worth_trying(head: bytes) -> bool:
    """Cheap pre-filter for the walker: skip text, known media/archives and empty heads."""
    if len(head) < 16 or looks_like_text(head):
        return False
    return not any(head.startswith(m) for m in _KNOWN_MAGICS)
