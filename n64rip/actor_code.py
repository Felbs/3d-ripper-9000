"""Reading an actor's own MIPS code to find the textures it points a segment at.

An NPC's face is not reachable from data alone.  Link keeps his eye and mouth textures in a
strided pointer array, so a stride walk finds them - but of 14 sampled NPCs only one is like
that, and several overlays hold no segmented pointer into their object file at all while their
head still asks for a texture on segment 8.  The address is built by the actor's code.

MIPS has no instruction that loads a 32-bit constant, so an address is assembled from a pair:
``lui`` puts the top half in a register and ``addiu``/``ori`` adds the bottom.  A segmented
pointer therefore appears in the instruction stream as ``lui reg, 0x0600`` followed by an
``addiu reg, reg, offset`` - and that is recoverable without simulating anything, by tracking
the last ``lui`` per register and combining it with the next arithmetic on the same register.

The sign matters: ``addiu`` sign-extends its immediate, so ``lui 0x0601`` + ``addiu -0x1000``
is ``0x0600f000``.  Getting that wrong produces addresses that are plausible but off by 64 KB.

This finds candidate pointers; it does not prove any of them is an eye.  Callers filter by
what the display list actually asked for and by whether the bytes decode to something
sensible - see :func:`face_candidates`.
"""

from __future__ import annotations

from dataclasses import dataclass

SEGMENT_SHIFT = 24


@dataclass(frozen=True)
class Pointer:
    """A segmented address the code assembles, and where it did so."""

    addr: int
    at: int  # offset of the completing instruction within the overlay

    @property
    def segment(self) -> int:
        return (self.addr >> SEGMENT_SHIFT) & 0x0F

    @property
    def offset(self) -> int:
        return self.addr & 0x00FFFFFF


def segmented_pointers(code: bytes, segment: int = 6, limit: int | None = None) -> list[Pointer]:
    """Every ``lui``/``addiu`` pair in *code* that assembles an address in *segment*.

    *limit* bounds the offset, so passing the object file's size keeps only pointers that
    could land inside it.
    """
    try:
        from capstone import CS_ARCH_MIPS, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
    except ImportError:  # pragma: no cover - capstone is optional
        return []

    md = Cs(CS_ARCH_MIPS, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    md.detail = True
    pending: dict[str, int] = {}
    out: list[Pointer] = []
    for ins in md.disasm(code, 0):
        mnem = ins.mnemonic
        ops = [o.strip() for o in ins.op_str.split(",")]
        if mnem == "lui" and len(ops) == 2:
            try:
                pending[ops[0]] = int(ops[1], 0) & 0xFFFF
            except ValueError:
                pending.pop(ops[0], None)
            continue
        if mnem in ("addiu", "ori") and len(ops) == 3:
            dst, src, imm = ops
            hi = pending.get(src)
            if hi is None:
                continue
            try:
                low = int(imm, 0)
            except ValueError:
                continue
            if mnem == "addiu":
                # addiu sign-extends; lui 0x0601 + addiu -0x1000 is 0x0600f000, not 0x06011000
                if low >= 0x8000:
                    low -= 0x10000
                addr = ((hi << 16) + low) & 0xFFFFFFFF
            else:
                addr = ((hi << 16) | (low & 0xFFFF)) & 0xFFFFFFFF
            if dst != src:
                pending.pop(dst, None)
            if ((addr >> SEGMENT_SHIFT) & 0x0F) == segment and (addr >> 28) == 0:
                off = addr & 0x00FFFFFF
                if limit is None or off < limit:
                    out.append(Pointer(addr, ins.address))
            continue
        # anything else that writes the register invalidates the pending high half
        if ops:
            pending.pop(ops[0], None)
    return out


def pointer_tables(overlay: bytes, vram_base: int, object_size: int,
                   min_entries: int = 2) -> list[list[int]]:
    """Segment-6 pointer arrays the code takes the address of.

    The common shape is an array of texture pointers - ``sEyeTextures[]`` and friends - which
    the actor indexes by its current expression.  The array's own address is built by the same
    ``lui``/``addiu`` pair, but as a **VRAM** address inside the overlay rather than a
    segmented one.  So: find those, convert to an offset in the overlay, and read consecutive
    segmented pointers there.

    This is what a stride walk cannot do.  It makes no assumption that the textures are evenly
    spaced, which is why it finds NPC eye sets where the stride search found nothing.
    """
    import struct as _struct

    out: list[list[int]] = []
    seen: set[int] = set()
    for p in _vram_pointers(overlay, vram_base):
        off = p - vram_base
        if off < 0 or off + 4 > len(overlay) or off in seen:
            continue
        seen.add(off)
        entries: list[int] = []
        at = off
        while at + 4 <= len(overlay):
            word = _struct.unpack_from(">I", overlay, at)[0]
            if (word >> 24) != 0x06:
                break
            target = word & 0x00FFFFFF
            if target >= object_size:
                break
            entries.append(target)
            at += 4
        if len(entries) >= min_entries:
            out.append(entries)
    return out


def _vram_pointers(code: bytes, vram_base: int) -> list[int]:
    """Addresses the code assembles that land inside its own overlay."""
    try:
        from capstone import CS_ARCH_MIPS, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
    except ImportError:  # pragma: no cover
        return []
    md = Cs(CS_ARCH_MIPS, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    hi_half: dict[str, int] = {}
    out: list[int] = []
    top = vram_base + len(code)
    for ins in md.disasm(code, 0):
        ops = [o.strip() for o in ins.op_str.split(",")]
        if ins.mnemonic == "lui" and len(ops) == 2:
            try:
                hi_half[ops[0]] = int(ops[1], 0) & 0xFFFF
            except ValueError:
                hi_half.pop(ops[0], None)
            continue
        if ins.mnemonic in ("addiu", "ori") and len(ops) == 3:
            dst, src, imm = ops
            hi = hi_half.get(src)
            if hi is None:
                continue
            try:
                low = int(imm, 0)
            except ValueError:
                continue
            if ins.mnemonic == "addiu" and low >= 0x8000:
                low -= 0x10000
            addr = ((hi << 16) + low) & 0xFFFFFFFF
            if dst != src:
                hi_half.pop(dst, None)
            # An overlay in the ROM is NOT relocated: its lui/addiu immediates hold the
            # offset from the overlay's own start, and the loader adds the VRAM base when it
            # loads.  So an internal address appears here either already-based (rare) or, far
            # more often, as a small offset.  Accept both.
            if vram_base <= addr < top:
                out.append(addr)
            elif 0 < addr < len(code):
                out.append(vram_base + addr)
            continue
        if ops:
            hi_half.pop(ops[0], None)
    return out


def face_candidates(
    overlay: bytes, object_size: int, want: set[tuple[int, int, int, int]]
) -> list[int]:
    """Offsets in the object file that this actor's code points a face segment at.

    *want* is the set of ``(fmt, size, width, height)`` tiles the actor's head actually
    requested, taken from its display lists - so a candidate is only kept when the bytes at
    that offset are big enough for a texture the model really asks for.  Ordered by address,
    de-duplicated, so a character's several eye states keep the order the code lists them in.
    """
    if not want:
        return []
    need = max(_texture_bytes(fmt, size, w, h) for fmt, size, w, h in want)
    seen: dict[int, None] = {}
    for p in segmented_pointers(overlay, segment=6, limit=object_size):
        if p.offset + need <= object_size:
            seen.setdefault(p.offset, None)
    return sorted(seen)


def _texture_bytes(fmt: int, size: int, width: int, height: int) -> int:
    bits = {0: 4, 1: 8, 2: 16, 3: 32}.get(size, 8)
    return max(1, width * height * bits // 8)


def texture_runs(overlay: bytes, object_size: int, min_entries: int = 2) -> list[list[int]]:
    """Runs of consecutive segment-6 pointers in an actor's overlay.

    This is the shape that actually finds NPC faces, and it needs neither the disassembler nor
    the relocation table: **segmented pointers are not relocated**, because they are absolute
    segment addresses rather than overlay-internal ones, so an array of texture pointers sits
    in the overlay as raw ``0x06XXXXXX`` words that can simply be read.

    No stride is assumed.  Link's eye textures happen to be evenly spaced and a stride walk
    finds them; almost no NPC's are, which is why the stride search found 2 of 53 face-wanting
    models and this finds 35.
    """
    import struct as _struct

    n = len(overlay) // 4
    if n == 0:
        return []
    words = _struct.unpack_from(f">{n}I", overlay, 0)
    out: list[list[int]] = []
    run: list[int] = []
    for w in words:
        if (w >> 24) == 0x06 and (w & 0x00FFFFFF) < object_size:
            run.append(w & 0x00FFFFFF)
            continue
        if len(run) >= min_entries and len(set(run)) == len(run):
            out.append(run)
        run = []
    if len(run) >= min_entries and len(set(run)) == len(run):
        out.append(run)
    return out


def best_face_run(runs: list[list[int]], obj: bytes, decode, want) -> list[int]:
    """Pick the run whose entries decode as the tile the head asked for.

    Several runs can appear in one overlay - display lists, collision, other texture sets - so
    the choice is made by decoding: an entry must fit, and the image must not be flat.  A
    uniform block is padding or a colour table, not a face.
    """
    import numpy as np

    best: tuple[float, list[int]] = (-1.0, [])
    for run in runs:
        for fmt, size, w, h in want:
            need = w * h * {0: 4, 1: 8, 2: 16, 3: 32}.get(size, 8) // 8
            if any(off + need > len(obj) for off in run):
                continue
            try:
                img = decode(fmt, size, w, h, obj[run[0]:])
            except Exception:  # noqa: BLE001
                continue
            if img is None:
                continue
            spread = float(np.std(img[..., :3]))
            if spread > best[0]:
                best = (spread, run)
    # a flat image is padding, not a face
    return best[1] if best[0] > 4.0 else []

def tile_for(stride: int, bpp: int) -> tuple[int, int] | None:
    """The texture dimensions implied by *stride* bytes at *bpp* bits a texel.

    The display list is not a reliable source for a face texture's size: its tile dimensions
    are derived from how many texels were actually loaded, and for exactly the actors whose
    face is missing nothing was ever loaded on that segment.  The pointer table *is* reliable
    - consecutive entries in one table are spaced by exactly one texture - so the spacing
    measures the size directly.

    The spacing gives a texel count, not a shape, so the shape is the squarest split with
    ``w >= h``: 1024 texels is 32x32 rather than 64x16, 2048 is 64x32.  Measured against the
    actors whose eyes decode correctly, that rule picks the right shape every time.
    """
    if stride <= 0 or bpp <= 0:
        return None
    texels = stride * 8 // bpp
    if texels <= 0 or texels * bpp // 8 != stride:
        return None
    best: tuple[int, int, int] | None = None
    for h in range(1, int(texels ** 0.5) + 1):
        if texels % h:
            continue
        w = texels // h
        if w > 256 or h < 4:
            continue
        score = w // h
        if best is None or score < best[0]:
            best = (score, w, h)
    return (best[1], best[2]) if best else None


def delta_groups(run: list[int]) -> list[list[int]]:
    """Maximal stretches of *run* whose entries advance by one constant positive step.

    Where an actor stores a table's textures back to back, this is the table: the step is one
    texture, so a change of step is the boundary between ``sEyeTextures[]`` and
    ``sMouthTextures[]``.  A step that occurs only once between two other groups is the gap
    *between* tables rather than a table of its own, and is dropped.
    """
    if len(run) < 2:
        return []
    deltas = [b - a for a, b in zip(run, run[1:])]
    spans: list[tuple[int, int, int]] = []  # (first index, count of deltas, delta)
    i = 0
    while i < len(deltas):
        j = i
        while j + 1 < len(deltas) and deltas[j + 1] == deltas[i]:
            j += 1
        spans.append((i, j - i + 1, deltas[i]))
        i = j + 1
    out = []
    for k, (at, count, delta) in enumerate(spans):
        if delta <= 0:
            continue
        # a lone step flanked by other steps is the jump between two tables, not a table
        if count == 1 and 0 < k < len(spans) - 1:
            continue
        out.append(run[at:at + count + 1])
    return out


def texture_tables(run: list[int], bpp: int = 8) -> list[list[int]]:
    """Candidate expression tables inside one pointer run.

    Both shapes occur and neither can be assumed.  Some actors store their eye frames
    consecutively, so the spacing marks the table out; others - the ones whose pointer arrays
    have no constant step at all - simply list scattered offsets, and the whole run is the
    table.  Offering both and letting the caller score them is what recovers each kind
    without breaking the other.
    """
    cands: list[list[int]] = []
    for tb in [run, *delta_groups(run)]:
        if len(tb) >= 2 and tb not in cands:
            cands.append(list(tb))
    return cands


def modal_stride(run: list[int]) -> int:
    """The step *run* takes most often, which is one texture where the entries are packed."""
    from collections import Counter

    steps = [b - a for a, b in zip(run, run[1:]) if b > a]
    return Counter(steps).most_common(1)[0][0] if steps else 0
