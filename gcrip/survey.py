"""Survey a folder of GameCube discs: which engine/format family does each game use?

    gcrip survey D:/roms/gamecube [-o out/survey] [--limit N] [--deep N]

Fast per disc (seconds, not minutes): header + FST, the first bytes of a sample of files
for magic sniffing, and a peek inside a few small compressed archives (Yaz0/Yay0/RARC/U8)
for J3D magic. No hashing, no full archive walk. Results are appended to
<out>/survey.jsonl as they come (resumable) and summarised in <out>/survey.md.

The engine guess is a heuristic on formats seen; "J3D" means gcrip's model pipeline should
apply (BMD/BDL/BCK found), everything else needs a new parser module or Dolphin capture.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gcrip.disc.fst import parse_fst, parse_header
from gcrip.disc.image import DiscImage, UnsupportedImageError
from gcrip.formats import yay0, yaz0

# top-level magics worth reporting (bytes prefix -> label)
_MAGICS: list[tuple[bytes, str]] = [
    (b"J3D2bmd", "BMD"),
    (b"J3D2bdl", "BDL"),
    (b"J3D1bck", "BCK"),
    (b"J3D1btp", "BTP"),
    (b"J3D1btk", "BTK"),
    (b"J3D1brk", "BRK"),
    (b"J3D", "J3D-other"),
    (b"RARC", "RARC"),
    (b"Yaz0", "Yaz0"),
    (b"Yay0", "Yay0"),
    (b"\x55\xaa\x38\x2d", "U8"),
    (b"\x00\x20\xaf\x30", "TPL"),
    (b"\x00\x03\x00\x05", "RetroPAK"),
    (b"HALB", "HAL"),
    (b"THP\x00", "THP"),
    (b"RIFF", "RIFF"),
    (b"BNR1", "BNR"),
    (b"BNR2", "BNR"),
    (b"MDL", "MDL"),
    (b"MOD", "MOD"),
    (b"HSD", "HSD"),
    (b"BIG", "EA-BIG"),
    (b"BIGF", "EA-BIGF"),
    (b"CPRS", "CPRS"),
    (b"LZ77", "LZ77"),
    (b"\x00\x00\x00\x01", "u32:1"),
    (b"NDS", "NDS"),
    (b"CGFX", "CGFX"),
    (b"GTF", "GTF"),
    (b"HGL", "HGL"),
    (b"BMDL", "BMDL"),
    (b"BMSG", "BMSG"),
    (b"BND", "BND"),
    (b"MPB", "MPB"),
    (b"IDX", "IDX"),
    (b"IECS", "IECS"),
]

_ARCHIVE_MAGICS = (b"Yaz0", b"Yay0", b"RARC", b"\x55\xaa\x38\x2d")


@dataclass
class DiscSurvey:
    file: str
    game_id: str = ""
    title: str = ""
    region: str = ""
    maker: str = ""
    size_mb: int = 0
    files: int = 0
    exts: dict[str, int] = field(default_factory=dict)  # top extensions
    magics: dict[str, int] = field(default_factory=dict)  # magic label -> count in sample
    j3d_models: int = 0  # BMD/BDL seen (top level or inside peeked archives)
    j3d_anims: int = 0
    j3d_inside_archives: int = 0  # archives peeked that contain J3D data
    archives_peeked: int = 0
    engine: str = "unknown"
    seconds: float = 0.0
    error: str = ""


def _label(head: bytes) -> str | None:
    for magic, label in _MAGICS:
        if head.startswith(magic):
            return label
    return None


def _peek_archive(blob: bytes) -> tuple[int, int, str]:
    """(models, anims, inner label) found by scanning a decompressed archive blob."""
    if blob[:4] == b"Yaz0":
        blob = yaz0.decompress(blob)
    elif blob[:4] == b"Yay0":
        blob = yay0.decompress(blob)
    inner = _label(blob[:16]) or ""
    models = blob.count(b"J3D2bmd") + blob.count(b"J3D2bdl")
    anims = blob.count(b"J3D1bck") + blob.count(b"J3D1btp")
    return models, anims, inner


def _guess_engine(s: DiscSurvey) -> str:
    m = s.magics
    if s.j3d_models or s.j3d_anims or m.get("BMD") or m.get("BDL"):
        return "J3D"
    if m.get("RetroPAK"):
        return "Retro (PAK/CMDL)"
    if m.get("HAL") or m.get("HSD"):
        return "HAL (DAT/HSD)"
    ext = s.exts
    if m.get("EA-BIG") or m.get("EA-BIGF") or ext.get("viv") or ext.get("big"):
        return "EA (BIG/VIV)"
    if s.maker in ("01",) and (m.get("RARC") or m.get("U8")):
        return "Nintendo (RARC/U8, non-J3D)"
    if s.maker == "8P" and ext.get("prs"):
        return "Sega (PRS)"
    if ext.get("dat") and s.maker == "01":
        return "Nintendo (DAT)"
    if s.maker == "08":
        return "Capcom"
    if s.maker == "52":
        return "Activision"
    if s.maker == "69":
        return "EA"
    if s.maker == "41":
        return "Ubisoft"
    if s.maker == "78":
        return "THQ"
    top = next(iter(ext), "?")
    return f"custom (.{top})"


def survey_disc(path: Path, *, sample: int = 600, deep: int = 24) -> DiscSurvey:
    t0 = time.monotonic()
    s = DiscSurvey(file=path.name, size_mb=path.stat().st_size >> 20)
    try:
        img = DiscImage(path)
    except UnsupportedImageError as e:
        s.error = str(e).splitlines()[0]
        s.seconds = time.monotonic() - t0
        return s
    try:
        hdr = parse_header(img.read(0, 0x2450))
        s.game_id, s.title, s.region, s.maker = hdr.game_id, hdr.title, hdr.region, hdr.maker_code
        entries = [e for e in parse_fst(img.read(hdr.fst_offset, hdr.fst_size)) if not e.is_dir]
        s.files = len(entries)
        exts = Counter()
        for e in entries:
            name = e.name.lower()
            exts[name.rsplit(".", 1)[1] if "." in name else "(none)"] += 1
        s.exts = dict(exts.most_common(8))
        # sample file heads, evenly across the FST
        step = max(1, len(entries) // sample)
        picked = entries[::step][:sample]
        magics = Counter()
        archives = []
        for e in picked:
            if e.size < 4:
                continue
            head = img.read(e.offset, 32)
            lab = _label(head)
            if lab:
                magics[lab] += 1
                if head[:4] in _ARCHIVE_MAGICS and e.size <= 6 << 20:
                    archives.append(e)
        s.magics = dict(magics.most_common(12))
        s.j3d_models = magics.get("BMD", 0) + magics.get("BDL", 0)
        s.j3d_anims = magics.get("BCK", 0) + magics.get("BTP", 0)
        # peek inside archives spread across the size range (the smallest ones alone are
        # layouts/text and would miss the models); mid-sized ones hold characters
        archives = [a for a in archives if a.size <= 8 << 20]
        archives.sort(key=lambda e: e.size)
        stepa = max(1, len(archives) // deep)
        for e in archives[::stepa][:deep]:
            try:
                blob = img.read(e.offset, e.size)
                models, anims, _inner = _peek_archive(blob)
                s.archives_peeked += 1
                if models or anims:
                    s.j3d_inside_archives += 1
                    s.j3d_models += models
                    s.j3d_anims += anims
            except Exception:  # noqa: BLE001
                continue
        s.engine = _guess_engine(s)
    except Exception as e:  # noqa: BLE001
        s.error = f"{type(e).__name__}: {e}"
    finally:
        img.close()
    s.seconds = time.monotonic() - t0
    return s


def survey(folder: Path, out_dir: Path, *, limit: int | None = None, deep: int = 24, quiet=False):
    folder = Path(folder)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "survey.jsonl"
    done: dict[str, dict] = {}
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["file"]] = d
    isos = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in (".iso", ".gcm", ".rvz", ".gcz", ".wia")
    )
    if limit:
        isos = isos[:limit]
    todo = [p for p in isos if p.name not in done]
    if not quiet:
        print(f"{len(isos)} discs, {len(done)} already surveyed, {len(todo)} to go")
    with jsonl.open("a", encoding="utf-8") as fh:
        for i, p in enumerate(todo):
            s = survey_disc(p, deep=deep)
            done[p.name] = asdict(s)
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
            fh.flush()
            if not quiet:
                tag = s.engine if not s.error else "ERR " + s.error[:40]
                line = f"[{i + 1}/{len(todo)}] {s.game_id:6} {s.title[:32]:32} {tag:28}"
                print(f"{line} {s.seconds:4.1f}s", flush=True)
            if (i + 1) % 10 == 0:
                write_summary(out_dir, done)
    write_summary(out_dir, done)
    return done


def write_summary(out_dir: Path, done: dict[str, dict]) -> Path:
    rows = sorted(
        done.values(), key=lambda d: (d["engine"] != "J3D", -d.get("j3d_models", 0), d["file"])
    )
    by_engine = Counter(d["engine"] for d in rows)
    lines = [
        "# GameCube library survey",
        "",
        f"{len(rows)} discs. Engine guesses: "
        + ", ".join(f"**{k}** {v}" for k, v in by_engine.most_common()),
        "",
        "## J3D games (gcrip rip should work)",
        "",
        "| game | ID | files | J3D models | J3D anims | archives w/ J3D | top formats | s |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for d in rows:
        if d["engine"] != "J3D":
            continue
        lines.append(_row(d))
    lines += [
        "",
        "## Everything else",
        "",
        "| game | ID | engine guess | files | top formats | s |",
        "|---|---|---|---:|---|---:|",
    ]
    for d in rows:
        if d["engine"] == "J3D":
            continue
        fmts = _fmts(d)
        err = f" ⚠ {d['error']}" if d.get("error") else ""
        name = d["title"] or d["file"]
        lines.append(
            f"| {name}{err} | {d['game_id']} | {d['engine']} | {d['files']} | {fmts} | "
            f"{d['seconds']:.0f} |"
        )
    p = out_dir / "survey.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _fmts(d: dict) -> str:
    parts = [f"{k}×{v}" for k, v in list(d.get("magics", {}).items())[:4]]
    parts += [f".{k}×{v}" for k, v in list(d.get("exts", {}).items())[:3]]
    return " ".join(parts)


def _row(d: dict) -> str:
    peeked = f"{d['j3d_inside_archives']}/{d['archives_peeked']}"
    return (
        f"| {d['title'] or d['file']} | {d['game_id']} | {d['files']} | {d['j3d_models']} | "
        f"{d['j3d_anims']} | {peeked} | {_fmts(d)} | {d['seconds']:.0f} |"
    )
