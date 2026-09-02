"""Find known plaintext: the same asset stored raw somewhere, and packed somewhere else.

This is the technique that broke the Tiger Woods codec open after every decoder-variant search
had failed.  Tiger Woods 06 stores its course `ter` resources **raw**; 2005 stores the same
courses **packed**; the two discs share 58 `.hog` paths.  Taking 16-byte windows from 06's raw
member and searching 2005's packed archive found **435 of 2,080** of them verbatim - and
sixteen-byte coincidences do not happen, so those were the literal runs of the LZ stream.  That
gave aligned plaintext, which gave the literal opcode, which resolved the contradiction the note
had been stuck on.

Nobody does this because it means treating the library as **one corpus** rather than as 638
separate problems.  The same engine ships across years and platforms, and somebody always
shipped one asset uncompressed.

The guarantee this module rests on: index the raw side every `stride` bytes and query the packed
side at every offset, and any shared run of at least ``window + stride - 1`` bytes is certain to
be found.  A shorter run may be missed, which is the price of not holding an entry per byte of a
multi-gigabyte library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: 16 bytes is the length the Tiger Woods result was measured at.  Shorter windows start
#: matching by chance on structured data - a run of zeroes will hit anything.
WINDOW = 16
#: Index every Nth offset on the raw side.  See the module docstring for what this costs.
STRIDE = 16


def _lead(data: bytes, offsets: np.ndarray) -> np.ndarray:
    """The first 8 bytes at each offset, as uint64 - a cheap exact prefix, not a hash.

    Hashing every offset of a 4 MB target with blake2b took minutes; this is eight vectorised
    shifts over the whole buffer.  Candidates are confirmed byte-for-byte afterwards, so the
    prefix only has to be selective, not collision-free.
    """
    a = np.frombuffer(data, np.uint8)
    out = np.zeros(len(offsets), np.uint64)
    for k in range(8):
        out = (out << np.uint64(8)) | a[offsets + k].astype(np.uint64)
    return out


@dataclass
class Match:
    """One window of raw data found verbatim inside a packed blob."""

    source: str
    source_offset: int
    target_offset: int
    length: int


@dataclass
class Index:
    """Windows of known-plaintext, keyed by content."""

    window: int = WINDOW
    stride: int = STRIDE
    sources: dict[str, bytes] = field(default_factory=dict)
    _leads: list[np.ndarray] = field(default_factory=list)
    _where: list[tuple[str, np.ndarray]] = field(default_factory=list)
    _sorted: tuple[np.ndarray, np.ndarray, list[tuple[str, int]]] | None = None

    def add(self, name: str, data: bytes) -> int:
        """Index one raw member.  Returns how many windows were added."""
        self.sources[name] = data
        last = len(data) - self.window
        if last < 0:
            return 0
        offs = np.arange(0, last + 1, self.stride, dtype=np.int64)
        self._leads.append(_lead(data, offs))
        self._where.append((name, offs))
        self._sorted = None
        return len(offs)

    def __len__(self) -> int:
        return sum(len(x) for x in self._leads)

    def _build(self):
        if self._sorted is None:
            leads = np.concatenate(self._leads) if self._leads else np.zeros(0, np.uint64)
            flat = [(n, int(o)) for n, offs in self._where for o in offs]
            order = np.argsort(leads, kind="stable")
            self._sorted = (leads[order], order, flat)
        return self._sorted

    def search(self, target: bytes, min_run: int | None = None) -> list[Match]:
        """Every place a chunk of indexed plaintext appears verbatim in `target`.

        Overlapping hits are merged into runs, because what matters for reading a codec is
        "here is a literal run of N bytes", not "here are N-15 overlapping windows".
        """
        min_run = self.window if min_run is None else min_run
        last = len(target) - self.window
        if last < 0 or not self._leads:
            return []
        keys, order, flat = self._build()
        at = np.arange(0, last + 1, dtype=np.int64)
        vals = _lead(target, at)
        pos = np.searchsorted(keys, vals)
        pos = np.clip(pos, 0, len(keys) - 1)
        hit = keys[pos] == vals
        raw: list[Match] = []
        for t_off, p in zip(at[hit], pos[hit]):
            want = keys[p]
            probe = target[t_off : t_off + self.window]
            # several members can share an 8-byte prefix, so walk the equal run and confirm
            # each one against the full window - the prefix selects, the bytes decide
            q = int(p)
            while q >= 0 and keys[q] == want:
                name, s_off = flat[order[q]]
                if self.sources[name][s_off : s_off + self.window] == probe:
                    raw.append(Match(name, s_off, int(t_off), self.window))
                q -= 1
        return _merge(raw, self.sources, target, min_run)


def _merge(raw: list[Match], sources: dict[str, bytes], target: bytes, min_run: int) -> list[Match]:
    """Grow each hit as far as the bytes agree, then drop duplicates and short runs."""
    grown: dict[tuple[str, int, int], Match] = {}
    for m in raw:
        src = sources.get(m.source)
        if src is None:
            continue
        start_s, start_t = m.source_offset, m.target_offset
        # walk backwards while the bytes still agree
        while start_s > 0 and start_t > 0 and src[start_s - 1] == target[start_t - 1]:
            start_s -= 1
            start_t -= 1
        end_s, end_t = m.source_offset + m.length, m.target_offset + m.length
        while end_s < len(src) and end_t < len(target) and src[end_s] == target[end_t]:
            end_s += 1
            end_t += 1
        run = end_t - start_t
        if run < min_run:
            continue
        grown[(m.source, start_s, start_t)] = Match(m.source, start_s, start_t, run)
    return sorted(grown.values(), key=lambda m: (-m.length, m.target_offset))


def coverage(matches: list[Match], target_len: int) -> float:
    """Fraction of the packed blob that is known plaintext, counting each byte once."""
    if not target_len:
        return 0.0
    covered = bytearray(target_len)
    for m in matches:
        covered[m.target_offset : m.target_offset + m.length] = b"\1" * m.length
    return sum(covered) / target_len
