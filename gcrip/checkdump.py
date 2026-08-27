"""Grade a library against the Redump database: is each disc image a known-good dump?

    gcrip checkdump "D:/roms/gamecube" --dat "Nintendo - GameCube.dat" [-o out/checkdump]
    gcrip checkdump "D:/roms/dreamcast" --dat "Sega - Dreamcast.dat"

The datfile (Logiqx XML from redump.org/datfile/gc/ or /dc/) lists every disc with the
size, CRC32, MD5 and SHA-1 of its image. GameCube .iso files are hashed in full (one read
per disc). Dreamcast Redump zips need no reading at all: a zip stores the CRC32 of every
member in its central directory, so each track's CRC is compared with the datfile's.

Verdicts: MATCH (byte-identical to the Redump entry), SIZE (wrong size - truncated or
scrubbed), HASH (right size, wrong content - modified or damaged dump), UNKNOWN (no entry
with that name and no hash match anywhere in the datfile), UNREADABLE.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DatRom:
    game: str
    name: str
    size: int
    crc: str
    sha1: str


@dataclass
class Dat:
    name: str
    roms: list[DatRom]
    by_sha1: dict[str, DatRom] = field(default_factory=dict)
    by_crc: dict[str, list[DatRom]] = field(default_factory=dict)
    by_name: dict[str, DatRom] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Dat:
        path = Path(path)
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                text = z.read(next(n for n in z.namelist() if n.endswith(".dat")))
        else:
            text = path.read_bytes()
        root = ET.fromstring(text)
        name = root.findtext("header/name") or path.stem
        roms = []
        for g in root.iter("game"):
            for r in g.iter("rom"):
                roms.append(
                    DatRom(
                        game=g.get("name", ""),
                        name=r.get("name", ""),
                        size=int(r.get("size", "0") or 0),
                        crc=(r.get("crc") or "").lower(),
                        sha1=(r.get("sha1") or "").lower(),
                    )
                )
        d = cls(name=name, roms=roms)
        for r in roms:
            if r.sha1:
                d.by_sha1[r.sha1] = r
            if r.crc:
                d.by_crc.setdefault(r.crc, []).append(r)
            d.by_name[_norm(r.name)] = r
        return d


def _norm(name: str) -> str:
    """File name -> comparable key: drop LaunchBox's '-1' suffix, extension, case."""
    base = os.path.basename(name)
    base = re.sub(r"-\d+(\.[A-Za-z0-9]+)$", r"\1", base)
    base = re.sub(r"\.[A-Za-z0-9]+$", "", base)
    return base.lower().strip()


@dataclass
class Verdict:
    file: str
    verdict: str
    detail: str = ""
    redump_name: str = ""
    seconds: float = 0.0


def _sha1_file(path: Path, progress=None) -> tuple[str, str, int]:
    h = hashlib.sha1()
    crc = 0
    n = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(8 << 20)
            if not chunk:
                break
            h.update(chunk)
            crc = zlib.crc32(chunk, crc)
            n += len(chunk)
            if progress:
                progress(n)
    return h.hexdigest(), f"{crc & 0xFFFFFFFF:08x}", n


def check_iso(path: Path, dat: Dat, quiet: bool = True) -> Verdict:
    t0 = time.monotonic()
    expect = dat.by_name.get(_norm(path.name))
    size = path.stat().st_size
    if expect is not None and size != expect.size:
        return Verdict(
            path.name, "SIZE", f"{size} bytes, Redump has {expect.size}", expect.game,
            time.monotonic() - t0,
        )
    if expect is None and not any(r.size == size for r in dat.roms):
        return Verdict(path.name, "SIZE", f"{size} bytes matches no Redump disc", "", 0.0)

    def prog(n: int) -> None:
        if not quiet:
            sys.stderr.write(f"\r  {n >> 20:5d} MB {path.name[:60]:<60}")
            sys.stderr.flush()

    try:
        sha1, crc, _ = _sha1_file(path, prog)
    except OSError as e:
        return Verdict(path.name, "UNREADABLE", str(e), "", time.monotonic() - t0)
    if not quiet:
        sys.stderr.write("\n")
    hit = dat.by_sha1.get(sha1)
    if hit is not None:
        note = "" if expect is None or hit is expect else f"content is {hit.game}"
        return Verdict(path.name, "MATCH", note, hit.game, time.monotonic() - t0)
    if expect is not None:
        return Verdict(
            path.name, "HASH", f"sha1 {sha1} != Redump {expect.sha1}", expect.game,
            time.monotonic() - t0,
        )
    return Verdict(path.name, "UNKNOWN", f"sha1 {sha1} not in datfile", "", time.monotonic() - t0)


def check_zip(path: Path, dat: Dat) -> Verdict:
    """Redump zips (Dreamcast, PS1 ...): every member's stored CRC32 vs the datfile.
    Only data members count (.bin/.iso/.img/.raw); the .gdi/.cue text is a table of
    contents that front-ends rewrite, so a mismatch there is noted, not failed."""
    t0 = time.monotonic()
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        return Verdict(path.name, "UNREADABLE", str(e), "", time.monotonic() - t0)
    bad, notes, unknown = [], [], []
    matched_bytes: dict[str, int] = {}
    for i in infos:
        crc = f"{i.CRC & 0xFFFFFFFF:08x}"
        is_toc = i.filename.lower().endswith((".gdi", ".cue"))
        cands = [r for r in dat.by_crc.get(crc, []) if r.size == i.file_size]
        if cands:
            if not is_toc:
                for r in cands:
                    matched_bytes[r.game] = matched_bytes.get(r.game, 0) + i.file_size
            continue
        expect = dat.by_name.get(_norm(i.filename)) or next(
            (r for r in dat.roms if r.name == os.path.basename(i.filename)), None
        )
        if is_toc:
            notes.append(f"{os.path.basename(i.filename)} differs from Redump's (rewritten TOC)")
        elif expect is None:
            unknown.append(i.filename)
        elif expect.size != i.file_size:
            bad.append(f"{i.filename}: size {i.file_size} != {expect.size}")
        else:
            bad.append(f"{i.filename}: crc {crc} != {expect.crc}")
    game = max(matched_bytes, key=matched_bytes.get) if matched_bytes else ""
    secs = time.monotonic() - t0
    if bad:
        v = "SIZE" if all("size" in b for b in bad) else "HASH"
        return Verdict(path.name, v, "; ".join(bad[:4]), game, secs)
    if unknown and not matched_bytes:
        return Verdict(path.name, "UNKNOWN", "; ".join(unknown[:4]), "", secs)
    if unknown:
        notes.append(f"{len(unknown)} extra file(s) not in datfile")
    return Verdict(path.name, "MATCH", "; ".join(notes), game, secs)


def checkdump(folder: Path, dat_path: Path, out_dir: Path, *, quiet: bool = False) -> list[Verdict]:
    folder, out_dir = Path(folder), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dat = Dat.load(dat_path)
    jsonl = out_dir / "checkdump.jsonl"
    done: dict[str, dict] = {}
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["file"]] = d
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".iso", ".gcm", ".zip"))
    todo = [p for p in files if p.name not in done]
    if not quiet:
        print(f"{dat.name}: {len(dat.roms)} entries; {len(files)} images, {len(todo)} to check")
    with jsonl.open("a", encoding="utf-8") as fh:
        for i, p in enumerate(todo):
            v = check_zip(p, dat) if p.suffix.lower() == ".zip" else check_iso(p, dat, quiet)
            done[p.name] = v.__dict__
            fh.write(json.dumps(v.__dict__, ensure_ascii=False) + "\n")
            fh.flush()
            if not quiet:
                print(
                    f"[{i + 1}/{len(todo)}] {v.verdict:10} {p.name[:58]:58} {v.detail[:50]}",
                    flush=True,
                )
            if (i + 1) % 10 == 0:
                write_summary(out_dir, done, dat.name)
    write_summary(out_dir, done, dat.name)
    return [Verdict(**d) for d in done.values()]


def write_summary(out_dir: Path, done: dict[str, dict], dat_name: str) -> Path:
    rows = sorted(done.values(), key=lambda d: (d["verdict"] == "MATCH", d["file"].lower()))
    counts: dict[str, int] = {}
    for d in rows:
        counts[d["verdict"]] = counts.get(d["verdict"], 0) + 1
    lines = [
        f"# Dump check against {dat_name}",
        "",
        f"{len(rows)} images: " + ", ".join(f"**{k}** {v}" for k, v in sorted(counts.items())),
        "",
        "MATCH = byte-identical to Redump. SIZE = truncated/scrubbed. HASH = right size, wrong",
        "content (modified or damaged). UNKNOWN = no Redump entry (unusual dump or region).",
        "",
        "| verdict | file | Redump entry | detail |",
        "|---|---|---|---|",
    ]
    for d in rows:
        if d["verdict"] == "MATCH" and "rewritten TOC" in d["detail"] and ";" not in d["detail"]:
            continue  # the usual LaunchBox case: data identical, .gdi re-written
        if d["verdict"] == "MATCH" and not d["detail"]:
            continue
        lines.append(f"| {d['verdict']} | {d['file']} | {d['redump_name']} | {d['detail']} |")
    lines += ["", f"{counts.get('MATCH', 0)} clean matches not listed."]
    p = out_dir / "checkdump.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
