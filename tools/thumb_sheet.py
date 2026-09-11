"""Contact sheet of every model's thumbnail, labelled by object id, in pages."""
import json
import pathlib
import sys

from PIL import Image, ImageDraw

ROOT = pathlib.Path(r"D:/3d dump/GameCube/N64_CZLE")
SP = pathlib.Path(r"C:/Users/emane/AppData/Local/Temp/claude/Z--3d-ripper/edbdc273-f8f2-4975-b5df-bb6e79cb36f0/scratchpad")
rip = json.loads((ROOT / "rip_results.json").read_text(encoding="utf-8"))

rows = []
for m in rip["models"]:
    th = m.get("thumb")
    if not th:
        continue
    p = ROOT / th
    if not p.exists():
        continue
    oid = m["path"].split("/")[-1]
    rows.append((oid, m["triangles"], p))
rows.sort()

PER = 40
COLS = 8
CELL = 150
page = int(sys.argv[1]) if len(sys.argv) > 1 else 0
chunk = rows[page * PER:(page + 1) * PER]
if not chunk:
    print("no rows on page", page)
    raise SystemExit
n_rows = (len(chunk) + COLS - 1) // COLS
sheet = Image.new("RGB", (CELL * COLS, (CELL + 16) * n_rows), (18, 18, 22))
d = ImageDraw.Draw(sheet)
for i, (oid, tris, p) in enumerate(chunk):
    r, c = divmod(i, COLS)
    im = Image.open(p).convert("RGB")
    im.thumbnail((CELL - 6, CELL - 6))
    x, y = c * CELL + 3, r * (CELL + 16) + 16
    sheet.paste(im, (x, y))
    d.text((c * CELL + 3, r * (CELL + 16) + 2), f"{oid}  {tris}t", fill=(240, 240, 160))
out = SP / f"thumbs_{page}.png"
sheet.save(out)
print(out, sheet.size, f"{len(chunk)} of {len(rows)} (page {page}, {(len(rows)+PER-1)//PER} pages)")
