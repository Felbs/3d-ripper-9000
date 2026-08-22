"""gcrip command line.

gcrip info <disc.iso>                       header summary
gcrip tree <disc.iso | manifest.json>       print the directory tree
gcrip manifest <disc.iso> [-o out.json]     write disc_manifest.json
gcrip extract <disc.iso> <outdir>           dump every file (archives expanded)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from gcrip.disc.fst import APPLOADER_OFFSET, parse_header
from gcrip.disc.image import DiscImage, UnsupportedImageError
from gcrip.manifest import Manifest, ManifestEntry, build_manifest
from gcrip.tree import render_summary, render_tree


def _progress_printer(quiet: bool):
    if quiet:
        return None
    state = {"t": 0.0}

    def report(path: str, i: int, n: int) -> None:
        now = time.monotonic()
        if now - state["t"] > 0.25 or i == n - 1:
            state["t"] = now
            msg = f"\r[{i + 1}/{n}] {path[:70]:<70}"
            sys.stderr.write(msg)
            sys.stderr.flush()

    return report


def _end_progress(quiet: bool) -> None:
    if not quiet:
        sys.stderr.write("\r" + " " * 90 + "\r")
        sys.stderr.flush()


def _load_manifest_json(path: Path) -> Manifest:
    d = json.loads(path.read_text(encoding="utf-8"))
    m = Manifest(
        game=d["game"], image=d["image"], dirs=d.get("dirs", []), errors=d.get("errors", [])
    )
    for f in d["files"]:
        m.files.append(ManifestEntry(**f))
    return m


def _open_or_manifest(path: Path, args: argparse.Namespace) -> Manifest:
    if path.suffix.lower() == ".json":
        return _load_manifest_json(path)
    with DiscImage(path) as img:
        m = build_manifest(
            img,
            recurse=not args.no_archives,
            hash_files=not args.no_hash,
            progress=_progress_printer(args.quiet),
        )
    _end_progress(args.quiet)
    return m


def cmd_info(args: argparse.Namespace) -> int:
    with DiscImage(args.image) as img:
        hdr = parse_header(img.read(0, APPLOADER_OFFSET + 0x20))
    print(f"Game ID:        {hdr.game_id}")
    print(f"Title:          {hdr.title}")
    print(f"Maker:          {hdr.maker_code}")
    print(f"Region:         {hdr.region} ({hdr.region_char})")
    print(f"Disc/rev:       {hdr.disc_number} / {hdr.revision}")
    print(f"Apploader:      {hdr.apploader_date}")
    print(f"Audio stream:   {hdr.audio_streaming} (buffer {hdr.stream_buffer_size})")
    print(f"main.dol:       0x{hdr.dol_offset:08X}")
    print(f"FST:            0x{hdr.fst_offset:08X} size 0x{hdr.fst_size:X}")
    print(f"FST max size:   0x{hdr.fst_max_size:X}")
    print(f"User area:      0x{hdr.user_position:08X} len 0x{hdr.user_length:X}")
    print(f"Image size:     {img.size} bytes")
    return 0


def cmd_tree(args: argparse.Namespace) -> int:
    m = _open_or_manifest(Path(args.image), args)
    kinds = set(args.kinds.split(",")) if args.kinds else None
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        args.ascii = True
    for line in render_tree(
        m, ascii_only=args.ascii, max_depth=args.depth, show_hash=args.hashes, kinds=kinds
    ):
        print(line)
    print()
    for line in render_summary(m):
        print(line)
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    m = _open_or_manifest(Path(args.image), args)
    out = Path(args.output) if args.output else Path(f"disc_manifest_{m.game['id']}.json")
    out.write_text(json.dumps(m.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    for line in render_summary(m):
        print(line)
    print(f"wrote {out}")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    from gcrip.formats import rarc, yay0, yaz0

    outdir = Path(args.outdir)
    with DiscImage(args.image) as img:
        m = build_manifest(
            img, recurse=True, hash_files=False, progress=_progress_printer(args.quiet)
        )
        _end_progress(args.quiet)
        # Top-level entries: read from disc; nested: re-derive from parents.
        # Simple approach: re-walk, writing as we go.
        written = 0

        def write(path: str, data: bytes) -> None:
            nonlocal written
            p = outdir / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            written += 1

        def expand(path: str, data: bytes, depth: int) -> None:
            if yaz0.is_yaz0(data):
                data = yaz0.decompress(data)
            elif yay0.is_yay0(data):
                data = yay0.decompress(data)
            if rarc.is_rarc(data) and depth < 8:
                arc = rarc.parse(data)
                for f in arc.files:
                    expand(f"{path}/{f.path}", data[f.offset : f.offset + f.size], depth + 1)
                if not args.keep_archives:
                    return
            write(path, data)

        for e in m.files:
            if e.depth != 0:
                continue
            data = img.read(e.disc_offset, e.size)
            if e.path.startswith("sys/") or args.raw:
                write(e.path, data)
            else:
                expand(e.path, data, 0)
    print(f"extracted {written} files to {outdir}")
    return 0


def cmd_rip(args: argparse.Namespace) -> int:
    from gcrip.rip import rip

    res = rip(
        Path(args.image),
        Path(args.outdir),
        thumbnails=not args.no_thumbs,
        dedupe=not args.keep_duplicates,
        textures=not args.no_textures,
        quiet=args.quiet,
        limit=args.limit,
        path_filter=args.filter,
        animations=not args.no_anims,
        bone_names=args.bone_names,
        fps=args.fps,
        anim_map=dict(kv.split("=", 1) for kv in (args.anim_map or [])),
        max_anims=args.max_anims,
    )
    ok = sum(1 for m in res.models if m.out_rel)
    dup = sum(1 for m in res.models if m.duplicate_of)
    err = [m for m in res.models if m.error]
    print(f"{res.game_id} {res.title}")
    print(f"models: {ok} exported, {dup} duplicates skipped, {len(err)} failed")
    print(f"textures: {sum(1 for t in res.textures if t.out_rel)} standalone PNGs")
    n_anim = sum(len(m.animations) for m in res.models)
    n_expr = sum(1 for m in res.models if m.expressions)
    print(
        f"animations: {n_anim} clips on {sum(1 for m in res.models if m.animations)} models, "
        f"{n_expr} models with expression switches"
    )
    print(f"time: {res.seconds:.0f}s")
    print(f"report: {res.out_dir / 'report.html'}")
    return 0


def cmd_blend(args: argparse.Namespace) -> int:
    from gcrip.blend import blend

    res = blend(
        Path(args.ripdir),
        blender=args.blender,
        path_filter=args.filter,
        limit=args.limit,
        force=args.force,
        quiet=args.quiet,
    )
    print(
        f".blend files: {res.done} written, {res.skipped} already existed, {len(res.failed)} failed"
    )
    for f in res.failed[:20]:
        print("  !", f)
    print(f"time: {res.seconds:.0f}s")
    print(f"asset library root: {res.library_root}  (add it in Blender > Preferences > File Paths)")
    return 0 if not res.failed else 1


def cmd_pack(args: argparse.Namespace) -> int:
    """Write a self-contained .glb next to every model of a rip."""
    from gcrip.export.glb import write_glb
    from gcrip.rip import load_results, write_report

    game_dir = Path(args.ripdir)
    res = load_results(game_dir)
    n = 0
    for m in res.models:
        if not m.out_rel or (args.filter and args.filter not in m.path):
            continue
        out = write_glb(game_dir / m.out_rel)
        m.glb_rel = str(Path(m.out_rel).with_suffix(".glb").as_posix())
        n += 1
        if not args.quiet and n % 100 == 0:
            print(f"  {n} packed", flush=True)
    (game_dir / "rip_results.json").write_text(
        json.dumps(
            {
                "game_id": res.game_id,
                "title": res.title,
                "seconds": res.seconds,
                "models": [m.__dict__ for m in res.models],
                "textures": [t.__dict__ for t in res.textures],
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_report(res)
    print(f"{n} .glb files written (last: {out if n else '-'})")
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    from gcrip.survey import survey

    done = survey(
        Path(args.folder), Path(args.output), limit=args.limit, deep=args.deep, quiet=args.quiet
    )
    j3d = sum(1 for d in done.values() if d["engine"] == "J3D")
    md = Path(args.output) / "survey.md"
    print(f"{len(done)} discs surveyed, {j3d} look like J3D games -> {md}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    from gcrip.batch import batch

    rows = batch(
        Path(args.folder),
        Path(args.out),
        survey_path=Path(args.survey) if args.survey else None,
        engine=None if args.engine == "any" else args.engine,
        limit=args.limit,
        only=args.only,
        thumbnails=not args.no_thumbs,
        animations=not args.no_anims,
        quiet=args.quiet,
    )
    ok = [r for r in rows if not r.get("error")]
    print(
        f"{len(ok)} games ripped, {sum(r['exported'] for r in ok):,} models, "
        f"{sum(r['clips'] for r in ok):,} clips -> {Path(args.out) / 'batch_matrix.md'}"
    )
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    from gcrip.stage import build_all, build_stage, list_stages

    if args.all:
        build_all(
            Path(args.ripdir),
            iso=Path(args.iso) if args.iso else None,
            layers=args.layers,
            spawns=args.spawns,
            rigs=args.rigs,
            world=args.world,
            layer=args.layer,
        )
        return 0
    if args.list or not args.stage:
        list_stages(Path(args.ripdir), iso=Path(args.iso) if args.iso else None)
        return 0
    rooms = [int(r) for r in args.rooms.split(",")] if args.rooms else None
    for name in args.stage:
        build_stage(
            Path(args.ripdir),
            name,
            iso=Path(args.iso) if args.iso else None,
            rooms=rooms,
            layers=args.layers,
            spawns=args.spawns,
            rigs=args.rigs,
            world=args.world,
            layer=args.layer,
            out_dir=Path(args.out) if args.out else None,
            quiet=args.quiet,
        )
    return 0


def cmd_msg(args: argparse.Namespace) -> int:
    from gcrip.msg import dump_messages

    dump_messages(Path(args.ripdir), iso=Path(args.iso) if args.iso else None, quiet=args.quiet)
    return 0


def cmd_audio(args: argparse.Namespace) -> int:
    from gcrip.audio import dump_streams

    dump_streams(Path(args.ripdir), iso=Path(args.iso) if args.iso else None, quiet=args.quiet)
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    from gcrip.music import dump_music

    dump_music(
        Path(args.ripdir),
        iso=Path(args.iso) if args.iso else None,
        songs=args.songs or None,
        seconds=args.seconds,
        quiet=args.quiet,
    )
    return 0


def cmd_godot(args: argparse.Namespace) -> int:
    from gcrip.godot import export_godot

    export_godot(
        Path(args.ripdir),
        args.stage or None,
        out_dir=Path(args.out) if args.out else None,
        quiet=args.quiet,
        renderer=args.renderer,
        hdri={
            k: Path(v)
            for k, v in {
                "day": args.hdri, "sunset": args.hdri_sunset, "night": args.hdri_night
            }.items()
            if v
        } or None,
        physical=args.physical,
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from gcrip.serve import serve

    return serve(
        Path(args.ripdir), port=args.port, blender=args.blender, open_browser=not args.no_browser
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gcrip", description="GameCube asset extractor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="print disc header")
    p.add_argument("image")
    p.set_defaults(fn=cmd_info)

    def add_walk_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-archives", action="store_true", help="don't descend into archives")
        p.add_argument("--no-hash", action="store_true", help="skip content hashing (faster)")
        p.add_argument("-q", "--quiet", action="store_true")

    p = sub.add_parser("tree", help="print directory tree")
    p.add_argument("image", help="disc image, or a previously written manifest .json")
    p.add_argument("--ascii", action="store_true", help="ASCII box drawing")
    p.add_argument("--depth", type=int, default=None, help="max depth to print")
    p.add_argument("--hashes", action="store_true", help="show hash prefixes")
    p.add_argument("--kinds", help="comma-separated kinds to show, e.g. model,texture")
    add_walk_opts(p)
    p.set_defaults(fn=cmd_tree)

    p = sub.add_parser("manifest", help="write disc_manifest.json")
    p.add_argument("image")
    p.add_argument("-o", "--output")
    add_walk_opts(p)
    p.set_defaults(fn=cmd_manifest)

    p = sub.add_parser("extract", help="extract all files (archives expanded, decompressed)")
    p.add_argument("image")
    p.add_argument("outdir")
    p.add_argument("--raw", action="store_true", help="don't decompress or expand archives")
    p.add_argument("--keep-archives", action="store_true", help="also write expanded archives")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("rip", help="disc image -> glTF models + PNG textures + report.html")
    p.add_argument("image")
    p.add_argument("outdir", nargs="?", default="out")
    p.add_argument("--filter", help="only rip paths containing this substring")
    p.add_argument("--limit", type=int, help="stop after N models (for testing)")
    p.add_argument("--no-thumbs", action="store_true", help="skip thumbnail rendering")
    p.add_argument("--no-textures", action="store_true", help="skip standalone BTI/TPL textures")
    p.add_argument("--keep-duplicates", action="store_true", help="export identical models again")
    p.add_argument("--no-anims", action="store_true", help="skip BCK animations / BTP expressions")
    p.add_argument(
        "--bone-names",
        choices=["original", "mixamo"],
        default="original",
        help="rename recognised humanoid joints to Mixamo names (mixamorig:Hips ...) for "
        "retargeting; 'original' keeps J3D names and stores the Mixamo name in node extras",
    )
    p.add_argument("--fps", type=float, default=30.0, help="frame rate of BCK clips (default 30)")
    p.add_argument(
        "--max-anims",
        type=int,
        metavar="N",
        help="keep at most N clips per model (own archive first); default unlimited",
    )
    p.add_argument(
        "--anim-map",
        action="append",
        metavar="ANIMARC=MODELARC",
        help="attach an animation-only archive to a model archive, e.g. LkAnm=Link (repeatable)",
    )
    p.add_argument("--debug", action="store_true", help="print tracebacks for failed models")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_rip)

    p = sub.add_parser("blend", help="rip folder -> one .blend per model, marked as Blender assets")
    p.add_argument("ripdir", help="out/rip/<GameID> (the folder with rip_results.json)")
    p.add_argument("--blender", help="blender executable (default: auto-detect / $BLENDER)")
    p.add_argument("--filter", help="only models whose disc path contains this")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true", help="rewrite .blend files that already exist")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_blend)

    p = sub.add_parser("pack", help="write a self-contained .glb next to every model")
    p.add_argument("ripdir", help="out/rip/<GameID>")
    p.add_argument("--filter", help="only models whose disc path contains this")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("survey", help="scan a folder of discs: which engine/format each game uses")
    p.add_argument("folder", help="folder of .iso/.gcm images")
    p.add_argument("-o", "--output", default="out/survey")
    p.add_argument("--limit", type=int)
    p.add_argument("--deep", type=int, default=24, help="archives to peek inside per disc")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_survey)

    p = sub.add_parser(
        "batch", help="rip many discs (all J3D games from a survey) into one out folder"
    )
    p.add_argument("folder", help="folder of .iso/.gcm images")
    p.add_argument("--survey", help="survey.jsonl from `gcrip survey` (selects discs by engine)")
    p.add_argument(
        "--engine", default="J3D", help="engine label to select from the survey, or 'any'"
    )
    p.add_argument("--out", default="out/rip")
    p.add_argument("--only", nargs="*", help="only discs whose file name contains one of these")
    p.add_argument("--limit", type=int)
    p.add_argument("--no-thumbs", action="store_true")
    p.add_argument("--no-anims", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_batch)

    p = sub.add_parser(
        "stage", help="recompile a Wind Waker stage into one level glTF (rooms + placed actors)"
    )
    p.add_argument("ripdir", help="finished rip folder, e.g. out/rip/GZLE01")
    p.add_argument("stage", nargs="*", help="stage name(s), e.g. M_NewD2 sea Atorizk")
    p.add_argument("--list", action="store_true", help="list stages on the disc and exit")
    p.add_argument("--all", action="store_true", help="build every stage + stages/stage_matrix.md")
    p.add_argument("--iso", default=None, help="disc image (default: found via disc_manifest)")
    p.add_argument("--rooms", default=None, help="only these room numbers, e.g. 0,1,2")
    p.add_argument(
        "--layers", action="store_true",
        help="(default) place every story layer; each actor records its layer so the engine "
             "can show the set that matches the save's story state",
    )
    p.add_argument(
        "--layer", type=int, default=None,
        help="also place this story layer (default 0 = the game's opening state, where the "
        "villagers are; -1 = none)",
    )
    p.add_argument("--spawns", action="store_true", help="place a Link model at every spawn point")
    p.add_argument(
        "--world",
        action="store_true",
        help="keep the game's world coordinates (default recentres the level at the origin)",
    )
    p.add_argument(
        "--rigs",
        action="store_true",
        help="keep armatures/skins and full node trees (default bakes everything flat; "
        "flat imports far faster)",
    )
    p.add_argument("-o", "--out", default=None, help="output dir (default <ripdir>/stages/<stage>)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_stage)

    p = sub.add_parser("msg", help="dump every Wind Waker message (BMG) to text/messages.json")
    p.add_argument("ripdir", help="finished rip folder, e.g. out/rip/GZLE01")
    p.add_argument("--iso", default=None, help="disc image (default: found via disc_manifest)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_msg)

    p = sub.add_parser("audio", help="decode the streamed music (Audiores/Stream/*.afc) to WAV")
    p.add_argument("ripdir", help="finished rip folder, e.g. out/rip/GZLE01")
    p.add_argument("--iso", default=None, help="disc image (default: found via disc_manifest)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_audio)

    p = sub.add_parser(
        "music", help="render the sequenced music (JaiSeqs.arc + instrument banks) to WAV"
    )
    p.add_argument("ripdir", help="finished rip folder, e.g. out/rip/GZLE01")
    p.add_argument("songs", nargs="*", help="song names (i_link, house, ...); default: all")
    p.add_argument("--seconds", type=float, default=90.0, help="render length per song")
    p.add_argument("--iso", default=None, help="disc image (default: found via disc_manifest)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_music)

    p = sub.add_parser(
        "godot", help="recompiled stages -> a ready-to-open Godot 4 project (walk the levels)"
    )
    p.add_argument("ripdir", help="finished rip folder, e.g. out/rip/GZLE01")
    p.add_argument("stage", nargs="*", help="stage folder names under stages/ (default: all)")
    p.add_argument("-o", "--out", default=None, help="output dir (default <ripdir>/godot)")
    p.add_argument(
        "--renderer", default="forward_plus",
        choices=["forward_plus", "mobile", "gl_compatibility"],
        help="Godot rendering method; forward_plus enables SDFGI/SSR/SSAO (default)",
    )
    p.add_argument(
        "--hdri", default=None,
        help="daytime HDR to light outdoor stages with (hidden behind a stylised sky; used for"
        " ambient and reflections only). The visible sun tracks the game clock.",
    )
    p.add_argument("--hdri-sunset", default=None, help="HDR used at dawn/dusk")
    p.add_argument("--hdri-night", default=None, help="HDR used at night")
    p.add_argument(
        "--physical", dest="physical", action="store_true", default=None,
        help="physical light units, exposure and the HDR sky dome (default: on only with --hdri)",
    )
    p.add_argument("--no-physical", dest="physical", action="store_false",
                   help="force the simple always-visible lighting even with an HDR")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(fn=cmd_godot)

    p = sub.add_parser("serve", help="open report.html locally with 'Open in Blender' buttons")
    p.add_argument("ripdir", help="out/rip/<GameID>")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--blender", help="blender executable (default: auto-detect / $BLENDER)")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except UnsupportedImageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
