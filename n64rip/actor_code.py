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
    def keep(r):
        # A repeated pointer is a blink cycle, not a broken table: child Zelda's eyes are
        # `open, half, closed, half, mouth`, and rejecting the run for the repeat threw her
        # whole face away.  The repeat is dropped rather than kept, because an adjacent
        # duplicate scores a perfect 1.0 in frame agreement and would let random bytes as
        # `A, A, B` clear the threshold on the strength of the A-A pair alone.
        seen: dict[int, None] = {}
        for o in r:
            seen.setdefault(o, None)
        deduped = list(seen)
        if len(deduped) >= min_entries:
            out.append(deduped)

    for w in words:
        if (w >> 24) == 0x06 and (w & 0x00FFFFFF) < object_size:
            run.append(w & 0x00FFFFFF)
            continue
        keep(run)
        run = []
    keep(run)
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


# --------------------------------------------------------------------------- code route

#: ``gSPSegment`` writes two words: the command ``0xDB060000 | (segment * 4)`` and the
#: address.  The constant is what the compiler leaves in the instruction stream.
GSP_SEGMENT_HI = 0xDB06

#: How far apart the two halves of one gSPSegment can land.  The compiler interleaves
#: neighbouring calls: on one actor the ``lui 0xdb06`` and its ``ori`` are twelve instructions
#: apart, so a window of ten finds only the first segment and silently misses the rest.
GSP_WINDOW = 24


def gsp_segments(overlay: bytes, vram_base: int, object_size: int,
                 segments=(8, 9, 10), max_entries: int = 16) -> dict[int, list[int]]:
    """What this actor's code binds to each face segment, read from the code itself.

    Everything else in this module reads *data* - a pointer array, a palette, a spacing - and
    guesses what the game does with it.  This reads what the game **does**: the
    ``gSPSegment(gfx, seg, addr)`` calls in the actor's Draw, which are the one place the
    binding is stated rather than implied.

    The macro compiles to a fixed shape.  The command word is built by ``lui r, 0xdb06`` and
    ``ori r, r, seg*4`` and stored at ``0(gfx)``; the address is stored at ``4(gfx)``.  So the
    method is: find a store of a register holding ``0xDB06xxxx``, take the matching store to
    ``4`` of the same base register, and work out where *that* register's value came from.
    Two sources occur.  A **direct** binding builds the segmented address itself
    (``lui 0x0600`` + ``addiu``) - Tektite does this, once per colour variant.  A **table**
    binding loads it (``lw``) from an array whose VRAM address the code builds, indexed by the
    actor's state - the common case, and the table's offset in the overlay is that address
    minus ``vram_base``, because the overlay is linked for its home address.

    Anchoring on the two stores matters.  Pairing a ``0xDB06`` constant with the nearest
    address by distance assigned one pointer to three different segments on the first actor
    tried.

    Returns ``{segment: [offsets into the object]}``.  Every offset is bounds-checked against
    *object_size*, but nothing here judges whether the bytes are a picture - that is the
    caller's job, with the same gates as every other route.
    """
    try:
        from capstone import CS_ARCH_MIPS, CS_MODE_32, CS_MODE_BIG_ENDIAN, Cs
    except ImportError:  # pragma: no cover - capstone is optional
        return {}
    import struct as _struct

    md = Cs(CS_ARCH_MIPS, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    ins = list(md.disasm(overlay, 0))
    if not ins:
        return {}

    def ops(i):
        return [o.strip() for o in i.op_str.split(",")] if i.op_str else []

    def mem(o):
        # "4($v1)" / "($v1)" / "0x10($sp)" -> (offset, base)
        o = o.strip()
        if "(" not in o:
            return None
        off, base = o.split("(", 1)
        base = base.rstrip(")")
        try:
            return (int(off, 0) if off else 0), base
        except ValueError:
            return None

    def imm(s):
        try:
            v = int(s, 0)
        except ValueError:
            return None
        return v

    top = vram_base + len(overlay)

    # Provenance per register.  Three kinds matter:
    #   ("const", v)  a value built from immediates - the gSPSegment command word, a table's
    #                 VRAM address, or a segmented address written out directly;
    #   ("load", a)   a value loaded from VRAM address a - an entry of a pointer table;
    #   None          anything we cannot follow.
    # SEGMENTED_TO_VIRTUAL turns the segmented pointer into the stored address through
    # `and` (mask the offset) and two `addu` (segment base, then 0x80000000).  The pointer
    # itself is the thing we want, so those operations *pass the source through* rather than
    # producing a new value - dropping it at the `and` is what made the first attempt find
    # nothing at all.
    def is_seg(pv):
        return pv is not None and pv[0] == "const" and (pv[1] >> 24) == 0x06

    def is_table(pv):
        return pv is not None and pv[0] == "const" and vram_base <= pv[1] < top

    def carry(a, b):
        """The operand worth keeping through an arithmetic step."""
        # A segmented constant or a table entry is direct evidence; a struct field is a
        # lead to follow; a table base is only useful to a later load.  Rank accordingly -
        # letting a field outrank a constant hid every direct binding behind gSegments[].
        for pv in (a, b):
            if pv is not None and pv[0] == "load":
                return pv
        for pv in (a, b):
            if is_seg(pv):
                return pv
        for pv in (a, b):
            if pv is not None and pv[0] == "field":
                return pv
        for pv in (a, b):
            if is_table(pv):
                return pv
        # any other constant - an address outside the overlay, such as gSegments[] - is kept
        # so that a load through it is recognised as "known, and not ours" rather than
        # mistaken for a field of the actor
        for pv in (a, b):
            if pv is not None and pv[0] == "const":
                return pv
        return None

    prov: dict[str, tuple | None] = {}
    stores: list[tuple[int, int, str, tuple | None]] = []  # (index, offset, base, prov)
    CLOBBER = ("$v0", "$v1", "$a0", "$a1", "$a2", "$a3", "$t0", "$t1", "$t2", "$t3",
               "$t4", "$t5", "$t6", "$t7", "$t8", "$t9")
    NO_WRITE = {"sw", "sd", "sh", "sb", "swc1", "sdc1", "beq", "bne", "beqz", "bnez", "blez",
                "bgtz", "bltz", "bgez", "j", "jal", "jr", "jalr", "b", "nop", "mtc1", "mtc0",
                "mult", "multu", "div", "divu", "mtlo", "mthi", "bc1t", "bc1f", "swl", "swr",
                "sync", "cache", "break", "teq"}

    for k, i in enumerate(ins):
        m, o = i.mnemonic, ops(i)
        if m == "lui" and len(o) == 2:
            v = imm(o[1])
            prov[o[0]] = ("const", (v & 0xFFFF) << 16) if v is not None else None
        elif m in ("addiu", "ori", "daddiu", "xori") and len(o) == 3:
            src = prov.get(o[1])
            v = imm(o[2])
            if src and src[0] == "const" and v is not None:
                if m == "ori":
                    prov[o[0]] = ("const", src[1] | (v & 0xFFFF))
                elif m == "xori":
                    prov[o[0]] = ("const", src[1] ^ (v & 0xFFFF))
                else:
                    if v >= 0x8000:
                        v -= 0x10000
                    prov[o[0]] = ("const", (src[1] + v) & 0xFFFFFFFF)
            elif src and src[0] in ("load", "field"):
                prov[o[0]] = src  # an offset applied to a loaded pointer keeps its source
            else:
                prov[o[0]] = None
        elif m in ("andi",) and len(o) == 3:
            src = prov.get(o[1])
            prov[o[0]] = src if (is_seg(src) or (src and src[0] in ("load", "field"))) else None
        elif m in ("addu", "add", "or", "and", "daddu", "subu") and len(o) == 3:
            prov[o[0]] = carry(prov.get(o[1]), prov.get(o[2]))
        elif m in ("lw", "ld") and len(o) == 2:
            mm = mem(o[1])
            base = prov.get(mm[1]) if mm else None
            if mm and is_table(base):
                prov[o[0]] = ("load", (base[1] + mm[0]) & 0xFFFFFFFF)
            elif mm and base is None and mm[1] not in ("$sp", "$zero"):
                # a field of some struct - usually the actor's own.  Remember which field, so
                # the value can be traced to whatever the actor stored there.
                prov[o[0]] = ("field", mm[0])
            else:
                prov[o[0]] = None
        elif m in ("sw", "sd") and len(o) == 2:
            mm = mem(o[1])
            if mm:
                stores.append((k, mm[0], mm[1], prov.get(o[0])))
        elif m == "move" and len(o) == 2:
            prov[o[0]] = prov.get(o[1])
        elif o and m not in NO_WRITE:
            prov[o[0]] = None
        if m in ("jal", "jalr"):
            for r in CLOBBER:
                prov[r] = None

    out: dict[int, list[int]] = {}
    n = len(overlay)

    def read_table(vaddr):
        off = vaddr - vram_base
        if not 0 <= off < n - 4:
            return []
        vals = []
        for e in range(max_entries):
            if off + 4 * e + 4 > n:
                break
            w = _struct.unpack_from(">I", overlay, off + 4 * e)[0]
            if (w >> 24) != 0x06 or (w & 0xFFFFFF) >= object_size:
                break
            vals.append(w & 0xFFFFFF)
        return vals

    # Second hop: what did the actor store into each of its own fields?  An actor whose
    # Update copies `sEyeTextures[index]` into `this->eyeTexture` and whose Draw binds
    # `this->eyeTexture` never builds the table address in the Draw at all.  Keyed by field
    # offset; only values that trace to a table or a segmented constant are kept.
    field_sources: dict[int, list[tuple]] = {}
    for _k, off, base, pv in stores:
        if base in ("$sp", "$zero") or pv is None:
            continue
        if pv[0] == "load" or is_seg(pv):
            field_sources.setdefault(off, []).append(pv)

    def resolve(pv):
        """Offsets in the object that a stored address provenance names."""
        if pv is None:
            return []
        if is_seg(pv):
            return [pv[1] & 0xFFFFFF]
        if pv[0] == "load":
            return read_table(pv[1])
        if pv[0] == "field":
            found: list[int] = []
            for src in field_sources.get(pv[1], ()):
                for v in resolve(src):
                    if v not in found:
                        found.append(v)
            return found
        return []

    for si, (k, off0, base0, p0) in enumerate(stores):
        if off0 != 0 or not p0 or p0[0] != "const":
            continue
        if (p0[1] >> 16) != GSP_SEGMENT_HI:
            continue
        seg = (p0[1] & 0xFFFF) // 4
        if seg not in segments:
            continue
        # The address store is the one at +4 of the same base.  Prefer the nearest one that
        # FOLLOWS the command store: with two calls interleaved, the nearest by distance can
        # be the previous call's address, which assigned every pointer one segment late.
        mate = None
        for k2, off2, base2, p2 in stores[si + 1:si + 8]:
            if off2 == 4 and base2 == base0 and k2 - k <= GSP_WINDOW:
                mate = p2
                break
        if mate is None:
            for k2, off2, base2, p2 in reversed(stores[max(0, si - 7):si]):
                if off2 == 4 and base2 == base0 and k - k2 <= GSP_WINDOW:
                    mate = p2
                    break
        bucket = out.setdefault(seg, [])
        for v in resolve(mate):
            if v < object_size and v not in bucket:
                bucket.append(v)
    return out
