# ruff: noqa: E501
"""Build gcrip/data/ww_bgm.json: which sequenced song every Wind Waker stage plays.

Sources (zeldaret/tww decomp, CC0):
  src/JAZelAudio/JAIZelScene.cpp  m_scene_info[] (one row per spot_dir_name[] stage:
                                  bgmNum, bank set, sub-id) and m_isle_info[] (Great Sea
                                  room -> island theme; 0 = the sea theme itself)
  include/JAZelAudio/JAZelAudio_BGM.h  JA_BGM_* ids
  JaiInit.aaf (from the disc)     sound table category 0 -> JaiSeqs.arc file index
Special cases handled by JAIZelBasic::setScene at runtime (Outset's three story
variants, Windfall at night, Dragon Roost after the boss, the sea storm) are recorded
as notes; the default (fresh file) choice is what lands in the table.

usage: python tools/ww_bgm_table.py [tww_src_dir] [rip_dir]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gcrip.formats import aaf, rarc, yay0, yaz0  # noqa: E402
from gcrip.stage import _Disc, _find_iso  # noqa: E402

TWW = Path(sys.argv[1] if len(sys.argv) > 1 else "Z:/memRip/sources/tww")
RIP = Path(sys.argv[2] if len(sys.argv) > 2 else "out/rip/GZLE01")
OUT = Path(__file__).resolve().parents[1] / "gcrip" / "data" / "ww_bgm.json"


def table(src: str, name: str) -> list[list[str]]:
    m = re.search(rf"{name}\[\] = \{{(.*?)\n\}};", src, re.S)
    assert m, name
    rows = []
    for line in m.group(1).splitlines():
        line = re.sub(r"/\*.*?\*/", "", line).strip()
        if not line.startswith("{"):
            continue
        rows.append([p.strip() for p in line.strip("{},").split(",")])
    return rows


def main() -> None:
    scene_src = (TWW / "src/JAZelAudio/JAIZelScene.cpp").read_text(encoding="utf-8", errors="replace")
    # retail build: drop the demo-only rows, keep the #else ones
    scene_src = re.sub(r"#if VERSION == VERSION_DEMO.*?#else\n", "", scene_src, flags=re.S)
    scene_src = re.sub(r"^#(endif|if|else)[^\n]*\n", "", scene_src, flags=re.M)
    bgm_h = (TWW / "include/JAZelAudio/JAZelAudio_BGM.h").read_text(encoding="utf-8", errors="replace")
    ids = {m.group(1): int(m.group(2), 16) for m in re.finditer(r"(JA_BGM_\w+)\s*=\s*(0x[0-9A-Fa-f]+)", bgm_h)}
    names = [s.strip().strip('",') for s in re.search(r"spot_dir_name\[\] = \{(.*?)\n\};", scene_src, re.S).group(1).split("\n") if s.strip()]
    scene = table(scene_src, "m_scene_info")
    isle = table(scene_src, "m_isle_info")

    disc = _Disc(_find_iso(RIP, None))
    raw = disc.img.read(disc.entries["Audiores/JaiInit.aaf"].offset, disc.entries["Audiores/JaiInit.aaf"].size)
    a = aaf.parse(raw)
    blob = disc.img.read(disc.entries["Audiores/Seqs/JaiSeqs.arc"].offset, disc.entries["Audiores/Seqs/JaiSeqs.arc"].size)
    if blob[:4] == b"Yaz0":
        blob = yaz0.decompress(blob)
    elif blob[:4] == b"Yay0":
        blob = yay0.decompress(blob)
    files = [f.path for f in rarc.parse(blob).files]

    def song(bgm_name: str) -> str | None:
        bid = ids.get(bgm_name)
        if not bid:
            return None
        idx = a.sequence_file_index(bid)
        if idx is None or idx >= len(files):
            return None
        return Path(files[idx]).name

    def row(r: list[str]) -> dict:
        tok = r[0].replace("(u16)", "")
        name = tok if tok.startswith("JA_BGM_") else None
        return {"bgm": name, "song": song(name) if name else None,
                "bank_set": int(r[1], 16), "sub": int(r[2], 16)}

    stages = {}
    for i, nm in enumerate(names):
        if i + 1 < len(scene):  # spotNameToId returns index + 1; row 0 = no spot
            stages[nm] = row(scene[i + 1])
    sea_rooms = {}
    for i, r in enumerate(isle):
        d = row(r)
        if d["bgm"] is None:
            d["bgm"], d["song"] = "JA_BGM_SEA", song("JA_BGM_SEA")
        sea_rooms[str(i)] = d
    songs = {n: song(n) for n in ids}
    out = {
        "_source": "zeldaret/tww JAIZelScene.cpp m_scene_info / m_isle_info + JaiInit.aaf sound table",
        "stages": stages,
        "sea_rooms": sea_rooms,
        "bgm_songs": {k: v for k, v in songs.items() if v},
        "notes": {
            "sea/Room44 (Outset)": "JA_BGM_ISLAND_LINK_0 before the pirate ship arrives (event bit), "
                                   "ISLAND_LINK_2 after Aryll is taken, ISLAND_LINK_3 later; "
                                   "ISLAND_LINK is the table default",
            "sea night": "JA_BGM_SEA is silent at night except the storm variant (checkSeaBgmID)",
        },
    }
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    named = sum(1 for v in stages.values() if v["song"])
    print(f"{len(stages)} stages ({named} with a song), {len(sea_rooms)} sea rooms -> {OUT}")


if __name__ == "__main__":
    main()
