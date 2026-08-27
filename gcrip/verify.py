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

from gcrip.disc.image import DiscImage


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
    rip_dir, iso = Path(rip_dir), Path(iso)
    manifest = json.loads((rip_dir / "disc_manifest.json").read_text(encoding="utf-8"))
    game_id = manifest["game"]["id"]
    res = VerifyResult(game_id=game_id)
    t0 = time.monotonic()
    entries = [
        f
        for f in manifest["files"]
        if f.get("depth", 0) == 0 and f.get("sha1") and f.get("disc_offset") is not None
    ]
    res.files = len(entries)
    with DiscImage(iso) as img:
        for i, f in enumerate(entries):
            if not quiet and i % 200 == 0:
                print(f"\r  {i + 1}/{len(entries)} {f['path'][:60]:<60}", end="", flush=True)
            h = hashlib.sha1()
            try:
                for chunk in img.read_chunks(f["disc_offset"], f["size"]):
                    h.update(chunk)
            except OSError as e:
                res.unreadable.append(f"{f['path']}: {e}")
                continue
            res.bytes_read += f["size"]
            if h.hexdigest() == f["sha1"]:
                res.matched += 1
            else:
                res.mismatched.append(f["path"])
    if not quiet:
        print()
    res.seconds = time.monotonic() - t0
    return res
