"""Copy gcrip/humanoid.py's mapper into the single-file Blender add-on.

    python tools/sync_addon_humanoid.py

The add-on cannot import gcrip (it is installed on its own into Blender), so the humanoid
mapper lives in both files; tests/test_humanoid.py fails when they drift.  Run this after
editing gcrip/humanoid.py.
"""

from pathlib import Path

here = Path(__file__).resolve().parent.parent
src = (here / "gcrip" / "humanoid.py").read_text(encoding="utf-8")
body = src[src.index("_ROLES: dict[str, str] = {}") :].rstrip() + "\n"
addon = here / "blender" / "gcrip_blender.py"
txt = addon.read_text(encoding="utf-8")
a, b = "# BEGIN HUMANOID\n", "# END HUMANOID\n"
i, j = txt.index(a) + len(a), txt.index(b)
if txt[i:j] == body:
    print("add-on already in sync")
else:
    addon.write_text(txt[:i] + body + txt[j:], encoding="utf-8", newline="\n")
    print(f"spliced {body.count(chr(10))} lines into {addon}")
