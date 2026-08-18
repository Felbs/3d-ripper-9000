"""Build the gcrip demo reel from a finished rip, using Blender headless.

    python tools/reel/make_reel.py --rip out/rip --out out/reel \
        --blender "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe"

Renders each shot in shots() to <out>/sN.mp4 with reel_shot.py (Eevee, 1280x720, 30 fps),
then concatenates them with crossfades into <out>/gcrip_demo_reel.mp4 via reel_concat.py.
Shots reference Wind Waker (GZLE01) and Twilight Princess (GZ2E01) rips; edit shots() for
other games. Only the Blender add-on and the rip output are needed - no game data is
stored here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADDON = HERE.parent.parent / "blender" / "gcrip_blender.py"


def shots(rip: Path) -> list[dict]:
    ww = rip / "GZLE01" / "res" / "Object"
    tp = rip / "GZ2E01" / "res" / "Object"
    ilia = tp / "Yelia.arc/archive/bmdr/yelia.gltf"
    link = str(ww / "Link.arc/archive/bdl/cl.gltf")

    def m(path, clip, name, **kw):
        return dict(path=str(path), clip=clip, name=name, **kw)

    return [
        dict(
            name="s0",
            frames=120,
            title="GCRip",
            subtitle="GameCube disc  ->  textured, rigged, animated glTF.  One command.",
            models=[m(link, "wait", "link")],
            orbit=[-40, 10],
            dist=2.4,
            look_h=0.55,
        ),
        dict(
            name="s1",
            frames=180,
            title="Wind Waker - Link",
            subtitle="594 BCK clips  |  BTP expression switches  |  22/22 Mixamo bones",
            models=[
                m(
                    link,
                    "walk",
                    "link",
                    expressions=["eyeL", "eyeR", "mouth", "mayuL", "mayuR"],
                    expr_step=30,
                )
            ],
            orbit=[-50, 40],
            dist=2.4,
            look_h=0.55,
        ),
        dict(
            name="s2",
            frames=180,
            title="Wind Waker cast",
            subtitle="Tetra  |  Ganondorf  |  Medli  |  Bokoblin  |  Moblin  -  "
            "clips matched across archives, cutscenes included",
            models=[
                m(ww / "Zl.arc/archive/bdlm/zl.gltf", "walk", "tetra", pos=[-250, 0, 0]),
                m(ww / "Gnd.arc/archive/bdlm/gnd.gltf", "wait", "ganon", pos=[-70, 70, 0]),
                m(ww / "Md.arc/archive/bdlm/md.gltf", "md_run", "medli", pos=[70, 0, 0]),
                m(ww / "Bk.arc/archive/bdlm/bk.gltf", "bk_walk", "boko", pos=[190, -10, 0]),
                m(ww / "Mo2.arc/archive/bdlm/mo.gltf", "dash", "moblin", pos=[330, 40, 0]),
            ],
            orbit=[-25, 30],
            dist=1.4,
            lens=40,
            look_h=0.45,
            elev=12,
        ),
        dict(
            name="s3",
            frames=180,
            title="Twilight Princess cast",
            subtitle="Midna  |  Ilia  |  Colin  |  Wolf Link",
            models=[
                m(tp / "Midna.arc/archive/bmdv/s_md.gltf", "md_swaita", "midna", pos=[-230, 0, 0]),
                m(ilia, "yelia_wait_a", "ilia", pos=[-80, 0, 0]),
                m(tp / "Kolin.arc/archive/bmdr/kolin.gltf", "kolin_run", "colin", pos=[70, 0, 0]),
                m(
                    tp / "Demo38_01.arc/archive/bmdr/demo38_wl_cut00_gp_1_o.gltf",
                    "wl_dasha",
                    "wolf",
                    pos=[240, 0, 0],
                ),
            ],
            orbit=[-25, 30],
            dist=1.35,
            lens=40,
            look_h=0.45,
            elev=12,
        ),
        dict(
            name="s4",
            frames=150,
            title="gcrip rip game.iso out/",
            subtitle="Wind Waker: 1,856 models, 4,406 clips in 4.5 min   |   "
            "Twilight Princess: 2,489 models, 14,362 clips in 10 min",
            models=[m(link, "dash", "link")],
            orbit=[30, -30],
            dist=2.4,
            look_h=0.55,
        ),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rip", default="out/rip", help="rip output root (contains <GameID>/)")
    ap.add_argument("--out", default="out/reel")
    ap.add_argument("--blender", default="blender", help="path to blender executable")
    ap.add_argument("--only", help="comma-separated shot names to (re)render, e.g. s2,s3")
    ap.add_argument("--no-concat", action="store_true")
    args = ap.parse_args()
    rip = Path(args.rip).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    mp4s = []
    for shot in shots(rip):
        shot["addon"] = str(ADDON)
        shot["out"] = str(out / f"{shot['name']}.mp4")
        cfg = out / f"{shot['name']}.json"
        cfg.write_text(json.dumps(shot, indent=1), encoding="utf-8")
        mp4s.append(shot["out"])
        if only and shot["name"] not in only:
            continue
        print(f"== {shot['name']}: {shot['title']}", flush=True)
        r = subprocess.run(
            [args.blender, "-b", "--python", str(HERE / "reel_shot.py"), "--", str(cfg)],
            capture_output=True,
            text=True,
        )
        if "SHOT_DONE" not in r.stdout:
            sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
            return 1
    if not args.no_concat:
        final = str(out / "gcrip_demo_reel.mp4")
        r = subprocess.run(
            [args.blender, "-b", "--python", str(HERE / "reel_concat.py"), "--", final, *mp4s],
            capture_output=True,
            text=True,
        )
        if "CONCAT_DONE" not in r.stdout:
            sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
            return 1
        print("reel:", final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
