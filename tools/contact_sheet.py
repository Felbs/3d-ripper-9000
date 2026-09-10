"""Build one labelled contact sheet per game so an agent can LOOK at 64 models at once.

The numeric auditor (gcrip/quality.py) finds broken geometry - collapsed, degenerate,
shattered.  It cannot see a model that is intact but the wrong SHAPE: a crumpled pose, a
character squashed flat, limbs fanned out, a mesh inside-out.  Those need an eye.
"""
import json, os, sys, math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path("D:/3d dump/GameCube")
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
MIN_THUMBS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
CELL, COLS = 128, 8
PER_SHEET = COLS * COLS

rep = json.loads((ROOT / "quality_report.json").read_text(encoding="utf-8"))
games = rep["games"]
index = {}
made = 0
for gid, info in sorted(games.items(), key=lambda kv: -kv[1]["models_scored"]):
    rr_path = ROOT / gid / "rip_results.json"
    if not rr_path.is_file():
        continue
    try:
        rr = json.loads(rr_path.read_text(encoding="utf-8"))
    except Exception:
        continue
    ms = rr.get("models", rr) if isinstance(rr, dict) else rr
    cands = [m for m in ms
             if m.get("out_rel") and m.get("thumb") and not m.get("duplicate_of")
             and not m.get("error") and (m.get("triangles") or 0) > 0
             and (ROOT / gid / m["thumb"]).is_file()]
    if len(cands) < MIN_THUMBS:
        continue
    # spread the sample across the size range rather than taking only the biggest
    cands.sort(key=lambda m: -(m.get("triangles") or 0))
    step = max(1, len(cands) // PER_SHEET)
    pick = cands[::step][:PER_SHEET]
    sheet = Image.new("RGB", (COLS * CELL, math.ceil(len(pick) / COLS) * CELL), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)
    cells = []
    for i, m in enumerate(pick):
        x, y = (i % COLS) * CELL, (i // COLS) * CELL
        try:
            im = Image.open(ROOT / gid / m["thumb"]).convert("RGB")
            im.thumbnail((CELL - 4, CELL - 16))
            sheet.paste(im, (x + 2, y + 14))
        except Exception:
            draw.rectangle([x + 2, y + 14, x + CELL - 2, y + CELL - 2], outline=(90, 40, 40))
        draw.text((x + 3, y + 2), f"{i}", fill=(200, 200, 90))
        cells.append({"i": i, "n": os.path.basename(m.get("path") or m["out_rel"]),
                      "tris": m.get("triangles"), "tex": m.get("textures"),
                      "skinned": bool(m.get("skinned")), "out_rel": m["out_rel"]})
    name = f"{gid}.png"
    sheet.save(OUT / name)
    index[gid] = {"title": info["title"], "sheet": str(OUT / name),
                  "models_scored": info["models_scored"], "sampled": len(pick),
                  "of_thumbnailed": len(cands), "cells": cells}
    made += 1
(OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
print(f"{made} sheets written to {OUT}")
