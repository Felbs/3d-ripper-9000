"""Audio extraction for GameCube JAudio games (Wind Waker's ``Audiores/``).

Currently covers the streamed music: every ``Audiores/Stream/*.afc`` is decoded
with :mod:`gcrip.formats.afc` and written as 16-bit WAV.  The stream names are
cross-referenced with the stream table inside ``JaiInit.aaf`` (AAF chunk type 5,
0x30-byte entries with the file name at +0x10) so each WAV also gets its
in-game stream id.
"""

from __future__ import annotations

import re
import struct
import time
from pathlib import Path

from gcrip.formats import afc
from gcrip.stage import _Disc, _find_iso

STREAM_RE = re.compile(r"^Audiores/Stream/([^/]+)\.afc$", re.IGNORECASE)
AAF_PATH = "Audiores/JaiInit.aaf"
AAF_STREAM_CHUNK = 5


def aaf_stream_names(aaf: bytes) -> list[str]:
    """Stream id -> file name from JaiInit.aaf (JAInter::InitData::checkInitDataOnMemory).

    The AAF is a list of BE u32 chunks: type, then per-type payload.  Types 1
    and 5-8 are (offset, size, flags) triplets; 2 and 3 are zero-terminated
    lists of such triplets; type 0 ends the file.
    """
    words = struct.unpack(f">{len(aaf) // 4}I", aaf[: len(aaf) // 4 * 4])
    i = 0
    while i < len(words):
        kind = words[i]
        i += 1
        if kind == 0:
            break
        if kind in (2, 3):  # zero-terminated lists of (offset, size, flags)
            while words[i]:
                i += 3
            i += 1
            continue
        off, size = words[i], words[i + 1]
        i += 3
        if kind == AAF_STREAM_CHUNK:
            names = []
            for p in range(off, off + size - 0x2F, 0x30):
                raw = aaf[p + 0x10 : p + 0x20]
                names.append(raw.split(b"\0", 1)[0].decode("ascii", "replace"))
            return names
    return []


def dump_streams(rip_dir, iso=None, quiet: bool = False) -> dict:
    """Extract every Stream/*.afc to <rip_dir>/audio/streams/<name>.wav + streams.md."""
    rip_dir = Path(rip_dir)
    out_dir = rip_dir / "audio" / "streams"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    disc = _Disc(_find_iso(rip_dir, iso))
    try:
        ids: dict[str, int] = {}
        if AAF_PATH in disc.entries:
            e = disc.entries[AAF_PATH]
            for n, name in enumerate(aaf_stream_names(disc.img.read(e.offset, e.size))):
                ids.setdefault(name.lower(), n)
        rows = []
        paths = sorted((p for p in disc.entries if STREAM_RE.match(p)), key=str.lower)
        for i, path in enumerate(paths):
            name = STREAM_RE.match(path).group(1)
            e = disc.entries[path]
            data = disc.img.read(e.offset, e.size)
            hdr = afc.parse_header(data)
            rate, ch, pcm = afc.decode(data)
            afc.write_wav(out_dir / f"{name}.wav", rate, pcm)
            rows.append(
                {
                    "name": name,
                    "seconds": round(len(pcm) / rate, 2),
                    "rate": rate,
                    "channels": ch,
                    "loop_start": hdr.loop_start if hdr.loop_flag else None,
                    "stream_id": ids.get((name + ".afc").lower()),
                    "bytes": e.size,
                }
            )
            if not quiet:
                secs = rows[-1]["seconds"]
                print(f"[{i + 1}/{len(paths)}] {name:10} {secs:7.1f}s {rate}Hz", flush=True)
    finally:
        disc.close()

    total = sum(r["seconds"] for r in rows)
    lines = [
        "# Streamed music (Audiores/Stream/*.afc)",
        "",
        f"{len(rows)} streams, {total / 60:.1f} minutes total. Decoded by gcrip.formats.afc "
        "(JAudio AFC ADPCM, stereo). `loop` is the loop-start sample when the stream loops.",
        "",
        "| id | name | seconds | rate | loop |",
        "|---:|------|--------:|-----:|-----:|",
    ]
    for r in rows:
        sid = "" if r["stream_id"] is None else f"0x{r['stream_id']:02X}"
        loop = "" if r["loop_start"] is None else str(r["loop_start"])
        lines.append(f"| {sid} | {r['name']} | {r['seconds']:.1f} | {r['rate']} | {loop} |")
    (rip_dir / "audio" / "streams.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "streams": len(rows),
        "minutes": round(total / 60, 1),
        "out_dir": str(out_dir),
        "seconds_elapsed": round(time.monotonic() - t0, 1),
        "rows": rows,
    }
