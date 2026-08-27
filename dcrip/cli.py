"""dcrip - Dreamcast asset extractor (3D Ripper 9000, Dreamcast module)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_info(args: argparse.Namespace) -> int:
    from dcrip.disc.gdi import GdImage, clean_title

    with GdImage(args.image) as img:
        h = img.header
        print(f"title:    {clean_title(h.title)}")
        print(f"product:  {h.product}  version {h.version}  {h.date}")
        print(f"company:  {h.company}  region {h.region}  device {h.device}")
        print(f"boot:     {h.boot}")
        for t in img.tracks:
            kind = "data" if t.is_data else "audio"
            loaded = "" if t.number in img._data else "  (not loaded)"
            print(f"track {t.number}: LBA {t.lba:>7} {kind:5} {t.sector_size} {t.filename}{loaded}")
        for e in img.errors:
            print("!", e)
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    from dcrip.disc.gdi import GdImage
    from dcrip.disc.iso9660 import walk

    with GdImage(args.image) as img:
        vol = walk(img)
        print(f"{vol.label}  ({len(vol.files)} files)")
        for e in vol.entries:
            depth = e.path.count("/")
            if args.depth is not None and depth > args.depth:
                continue
            mark = "/" if e.is_dir else f"  {e.size:,}"
            print(f"{'  ' * depth}{e.name}{mark}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    from dcrip.disc.gdi import GdImage
    from dcrip.disc.iso9660 import walk

    out = Path(args.outdir)
    with GdImage(args.image) as img:
        vol = walk(img)
        n = 0
        for e in vol.files:
            if args.filter and args.filter.lower() not in e.path.lower():
                continue
            dst = out / img.header.product.replace("/", "_") / e.path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(img.read(e.lba, e.size))
            n += 1
        print(f"{n} files -> {out}")
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    from dcrip.survey import survey

    done = survey(Path(args.folder), Path(args.output), limit=args.limit, quiet=args.quiet)
    nj = sum(1 for d in done.values() if d["engine"].startswith("Ninja"))
    md = Path(args.output) / "survey.md"
    print(f"{len(done)} discs surveyed, {nj} look like Ninja games -> {md}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dcrip", description="Dreamcast asset extractor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="print the IP.BIN header and track table")
    p.add_argument("image", help=".gdi, or a .zip holding a .gdi and its tracks")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("tree", help="print the ISO 9660 directory tree")
    p.add_argument("image")
    p.add_argument("--depth", type=int, default=None)
    p.set_defaults(fn=cmd_tree)

    p = sub.add_parser("extract", help="extract every file from the disc")
    p.add_argument("image")
    p.add_argument("outdir", nargs="?", default="out/dc")
    p.add_argument("--filter", help="only paths containing this substring")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("survey", help="scan a folder of discs: which formats each game uses")
    p.add_argument("folder", help="folder of .zip/.gdi images")
    p.add_argument("-o", "--output", default="out/dc_survey")
    p.add_argument("--limit", type=int)
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_survey)

    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # disc titles are not always cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
