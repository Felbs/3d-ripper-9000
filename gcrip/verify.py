"""Re-read a disc and compare every top-level file's SHA-1 with what the rip recorded.

    gcrip verify "D:/3d dump/GameCube/GZLE01" --iso "D:/roms/game.iso"

The rip hashes every file as it walks the disc (disc_manifest.json). Reading the disc a
second time and comparing catches a read that came back wrong on either pass - useful
when a drive has shown CRC errors under load. Files inside archives are covered by their
container's hash, so only depth-0 entries are re-read (the whole disc, once).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VerifyResult:
    game_id: str
    files: int = 0
    matched: int = 0
    mismatched: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    bytes_read: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.mismatched and not self.unreadable


def verify(rip_dir: Path, iso: Path, *, quiet: bool = False) -> VerifyResult:
    """Stream the image once from the disk (bypassing the OS cache where possible) and hash
    every top-level file range on the fly, then compare with the manifest."""
    from gcrip.unbuffered import read_chunks

    rip_dir, iso = Path(rip_dir), Path(iso)
    manifest = json.loads((rip_dir / "disc_manifest.json").read_text(encoding="utf-8"))
    game_id = manifest["game"]["id"]
    res = VerifyResult(game_id=game_id)
    t0 = time.monotonic()
    entries = sorted(
        (
            f
            for f in manifest["files"]
            if f.get("depth", 0) == 0 and f.get("sha1") and f.get("disc_offset") is not None
        ),
        key=lambda f: f["disc_offset"],
    )
    res.files = len(entries)
    hashers = [hashlib.sha1() for _ in entries]
    starts = [f["disc_offset"] for f in entries]
    ends = [f["disc_offset"] + f["size"] for f in entries]
    first = 0  # entries before this index are entirely behind the stream position
    pos = 0
    for chunk in read_chunks(iso):
        cend = pos + len(chunk)
        while first < len(entries) and ends[first] <= pos:
            first += 1
        i = first
        while i < len(entries) and starts[i] < cend:
            a = max(starts[i], pos) - pos
            b = min(ends[i], cend) - pos
            if b > a:
                hashers[i].update(chunk[a:b])
            i += 1
        pos = cend
        res.bytes_read = pos
        if not quiet and (pos // len(chunk)) % 32 == 0:
            print(f"\r  {pos >> 20:5d} MB", end="", flush=True)
    for i, (f, h) in enumerate(zip(entries, hashers, strict=True)):
        if ends[i] > pos:
            res.unreadable.append(f"{f['path']}: beyond end of image")
        elif h.hexdigest() == f["sha1"]:
            res.matched += 1
        else:
            res.mismatched.append(f["path"])
    if not quiet:
        print()
    res.seconds = time.monotonic() - t0
    return res
