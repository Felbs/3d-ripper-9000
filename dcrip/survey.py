"""Survey a folder of Dreamcast images: which model/texture formats does each game use?

    dcrip survey "D:/roms/dreamcast" [-o out/survey] [--limit N]

Per disc: inflate the data track(s), walk the ISO 9660 tree, sniff the first bytes of every
file (and of the entries inside AFS archives and PRS-compressed files) for the magics that
matter: Ninja models/motions (NJCM/NJBM/GJCM, NMDM), Ninja texture lists (NJTL), PVR
textures (PVRT/GBIX), and the archive/compression wrappers. Results are appended to
<out>/survey.jsonl (resumable) and summarised in <out>/survey.md.

"Ninja" as the engine guess means the model pipeline (once written) should apply;
everything else is grouped by publisher for later parser modules.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dcrip.disc.gdi import GdImage, UnsupportedImageError, clean_title
from dcrip.disc.iso9660 import walk
from dcrip.formats import afs, prs

_MAGICS: list[tuple[bytes, str]] = [
    (b"NJCM", "NJCM"),  # Ninja chunk model
    (b"NJBM", "NJBM"),  # Ninja basic model
    (b"GJCM", "GJCM"),  # Ginja model (SA2/Chao)
    (b"NMDM", "NMDM"),  # Ninja motion
    (b"NJTL", "NJTL"),  # Ninja texture list
    (b"GBIX", "GBIX"),  # PVR global index (texture follows)
    (b"PVRT", "PVRT"),  # PVR texture
    (b"PVMH", "PVM"),  # PVR texture pack
    (b"AFS\x00", "AFS"),
    (b"SEGA SEGAKATANA", "IP.BIN"),
    (b"\x7fELF", "ELF"),
    (b"RIFF", "RIFF"),
    (b"SMLT", "MLT"),  # Manatee sound
    (b"SOSB", "SOSB"),
    (b"SMSB", "SMSB"),
    (b"MDL\x00", "MDL"),
    (b"NUB\x00", "NUB"),
    (b"BINA", "BINA"),
    (b"SFDS", "SFD"),  # Sofdec movie
    (b"MPEG", "MPEG"),
    (b"\x00\x00\x01\xba", "MPEG-PS"),
    (b"GIF8", "GIF"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG", "PNG"),
    (b"BM", "BMP"),
    (b"PK\x03\x04", "ZIP"),
    (b"MIDI", "MIDI"),
    (b"CRI", "CRI"),
    (b"ADX", "ADX"),
    (b"\x80\x00", "ADX?"),
    (b"TEX\x00", "TEX"),
    (b"TXTR", "TXTR"),
    (b"HRND", "HRND"),
    (b"ARCH", "ARCH"),
    (b"MDLS", "MDLS"),
    (b"FPK", "FPK"),
    (b"PACK", "PACK"),
    (b"Pack", "Pack"),
]
_NINJA_MODEL = {"NJCM", "NJBM", "GJCM"}
_NINJA_ANIM = {"NMDM"}
_NINJA_TEX = {"NJTL", "PVRT", "GBIX", "PVM"}


@dataclass
class DiscSurvey:
    file: str
    product: str = ""
    title: str = ""
    company: str = ""
    region: str = ""
    date: str = ""
    size_mb: int = 0
    files: int = 0
    exts: dict[str, int] = field(default_factory=dict)
    magics: dict[str, int] = field(default_factory=dict)
    nj_models: int = 0
    nj_anims: int = 0
    nj_textures: int = 0
    afs_peeked: int = 0
    prs_peeked: int = 0
    engine: str = "unknown"
    seconds: float = 0.0
    error: str = ""


def _label(head: bytes) -> str | None:
    for magic, label in _MAGICS:
        if head.startswith(magic):
            return label
    return None


def _count_ninja(blob: bytes, s: DiscSurvey) -> None:
    s.nj_models += blob.count(b"NJCM") + blob.count(b"NJBM") + blob.count(b"GJCM")
    s.nj_anims += blob.count(b"NMDM")
    s.nj_textures += blob.count(b"NJTL") + blob.count(b"PVRT")


def _guess_engine(s: DiscSurvey) -> str:
    m = s.magics
    ext = s.exts
    if s.nj_models or s.nj_anims or ext.get("nj") or ext.get("njm"):
        return "Ninja (NJ)"
    if s.nj_textures or m.get("PVRT") or m.get("GBIX") or ext.get("pvr") or ext.get("pvm"):
        return "PVR textures only (custom models)"
    co = s.company.upper()
    for key, label in (
        ("SEGA", "Sega (custom)"),
        ("CAPCOM", "Capcom"),
        ("NAMCO", "Namco"),
        ("MIDWAY", "Midway"),
        ("ACCLAIM", "Acclaim"),
        ("UBI", "Ubisoft"),
        ("EIDOS", "Eidos"),
        ("ACTIVISION", "Activision"),
        ("THQ", "THQ"),
        ("INFOGRAMES", "Infogrames"),
        ("INTERPLAY", "Interplay"),
        ("KONAMI", "Konami"),
        ("SNK", "SNK"),
        ("CRAVE", "Crave"),
    ):
        if key in co:
            return label
    top = next(iter(ext), "?")
    return f"custom (.{top})"


def survey_disc(path: Path, *, max_peek: int = 48, sniff_files: int = 4000) -> DiscSurvey:
    t0 = time.monotonic()
    s = DiscSurvey(file=path.name, size_mb=path.stat().st_size >> 20)
    try:
        img = GdImage(path)
    except (UnsupportedImageError, ValueError, OSError, KeyError) as e:
        s.error = str(e).splitlines()[0]
        s.seconds = time.monotonic() - t0
        return s
    try:
        h = img.header
        s.product, s.company, s.region, s.date = h.product, h.company, h.region, h.date
        s.title = clean_title(h.title)
        vol = walk(img)
        files = vol.files
        s.files = len(files)
        exts: Counter = Counter()
        for e in files:
            n = e.name.lower()
            exts[n.rsplit(".", 1)[1] if "." in n else "(none)"] += 1
        s.exts = dict(exts.most_common(8))
        magics: Counter = Counter()
        afs_files = []
        prs_files = []
        step = max(1, len(files) // sniff_files)
        for e in files[::step][:sniff_files]:
            if e.size < 4:
                continue
            try:
                head = img.read(e.lba, 32)
            except ValueError:
                continue
            lab = _label(head)
            if lab:
                magics[lab] += 1
            if lab in _NINJA_MODEL:
                s.nj_models += 1
            elif lab in _NINJA_ANIM:
                s.nj_anims += 1
            elif lab in _NINJA_TEX:
                s.nj_textures += 1
            if lab == "AFS" and e.size <= 64 << 20:
                afs_files.append(e)
            elif prs.looks_like_prs(e.name) and e.size <= 8 << 20:
                prs_files.append(e)
        # peek inside archives spread over the size range
        afs_files.sort(key=lambda e: e.size)
        for e in afs_files[:: max(1, len(afs_files) // max_peek)][:max_peek]:
            try:
                blob = img.read(e.lba, e.size)
                for ent in afs.parse(blob)[:2000]:
                    if ent.size < 4 or ent.offset + ent.size > len(blob):
                        continue
                    lab = _label(blob[ent.offset : ent.offset + 32])
                    if lab:
                        magics[lab] += 1
                    if lab in _NINJA_MODEL:
                        s.nj_models += 1
                    elif lab in _NINJA_ANIM:
                        s.nj_anims += 1
                    elif lab in _NINJA_TEX:
                        s.nj_textures += 1
                s.afs_peeked += 1
            except (ValueError, IndexError):
                continue
        prs_files.sort(key=lambda e: e.size)
        for e in prs_files[:: max(1, len(prs_files) // max_peek)][:max_peek]:
            try:
                blob = prs.decompress(img.read(e.lba, e.size))
                lab = _label(blob[:32])
                if lab:
                    magics[lab] += 1
                _count_ninja(blob, s)
                s.prs_peeked += 1
            except (ValueError, IndexError):
                continue
        s.magics = dict(magics.most_common(12))
        s.engine = _guess_engine(s)
    except Exception as e:  # noqa: BLE001
        s.error = f"{type(e).__name__}: {e}"
    finally:
        img.close()
    s.seconds = time.monotonic() - t0
    return s


def survey(folder: Path, out_dir: Path, *, limit: int | None = None, quiet: bool = False):
    folder, out_dir = Path(folder), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "survey.jsonl"
    done: dict[str, dict] = {}
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["file"]] = d
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".zip", ".gdi"))
    if limit:
        images = images[:limit]
    todo = [p for p in images if p.name not in done]
    if not quiet:
        print(f"{len(images)} discs, {len(done)} already surveyed, {len(todo)} to go")
    with jsonl.open("a", encoding="utf-8") as fh:
        for i, p in enumerate(todo):
            s = survey_disc(p)
            done[p.name] = asdict(s)
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
            fh.flush()
            if not quiet:
                tag = s.engine if not s.error else "ERR " + s.error[:40]
                print(
                    f"[{i + 1}/{len(todo)}] {s.product:10} {s.title[:30]:30} {tag:34} "
                    f"{s.seconds:4.1f}s",
                    flush=True,
                )
            if (i + 1) % 10 == 0:
                write_summary(out_dir, done)
    write_summary(out_dir, done)
    return done


def _fmts(d: dict) -> str:
    parts = [f"{k}×{v}" for k, v in list(d.get("magics", {}).items())[:4]]
    parts += [f".{k}×{v}" for k, v in list(d.get("exts", {}).items())[:3]]
    return " ".join(parts)


def write_summary(out_dir: Path, done: dict[str, dict]) -> Path:
    rows = sorted(
        done.values(),
        key=lambda d: (not d["engine"].startswith("Ninja"), -d.get("nj_models", 0), d["file"]),
    )
    by_engine = Counter(d["engine"] for d in rows)
    lines = [
        "# Dreamcast library survey",
        "",
        f"{len(rows)} discs. Engine guesses: "
        + ", ".join(f"**{k}** {v}" for k, v in by_engine.most_common()),
        "",
        "## Ninja games (NJ models / NMDM motions found)",
        "",
        "| game | product | company | files | NJ models | NJ motions | NJ/PVR textures "
        "| AFS/PRS peeked | top formats | s |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for d in rows:
        if not d["engine"].startswith("Ninja"):
            continue
        lines.append(
            f"| {d['title'] or d['file']} | {d['product']} | {d['company']} | {d['files']} | "
            f"{d['nj_models']} | {d['nj_anims']} | {d['nj_textures']} | "
            f"{d['afs_peeked']}/{d['prs_peeked']} | {_fmts(d)} | {d['seconds']:.0f} |"
        )
    lines += [
        "",
        "## Everything else",
        "",
        "| game | product | company | engine guess | files | top formats | s |",
        "|---|---|---|---|---:|---|---:|",
    ]
    for d in rows:
        if d["engine"].startswith("Ninja"):
            continue
        err = f" ⚠ {d['error']}" if d.get("error") else ""
        lines.append(
            f"| {d['title'] or d['file']}{err} | {d['product']} | {d['company']} | "
            f"{d['engine']} | {d['files']} | {_fmts(d)} | {d['seconds']:.0f} |"
        )
    p = out_dir / "survey.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
