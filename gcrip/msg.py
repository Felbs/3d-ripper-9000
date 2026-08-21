"""Dump every in-game message of a Wind Waker disc to JSON + Markdown.

    gcrip msg out/rip/GZLE01 [--iso PATH]

Reads res/Msg/bmgres.arc (Yaz0 RARC) from the disc image, parses each .bmg inside
(zel_00.bmg on the USA disc) with gcrip.formats.bmg and writes

  <ripdir>/text/messages.json   [{id, index, text, attrs, raw_hex}, ...] in file order
  <ripdir>/text/messages.md     one section per message, tags left readable

The disc is located the same way `gcrip stage` does (disc_manifest.json -> roms/).
"""

from __future__ import annotations

import json
from pathlib import Path

from gcrip.formats import bmg as bmg_mod
from gcrip.stage import _Disc, _find_iso

MSG_ARC = "res/Msg/bmgres.arc"


def read_bmgs(disc: _Disc, arc_path: str = MSG_ARC) -> dict[str, bmg_mod.Bmg]:
    """Every .bmg inside the message archive: inner file name -> parsed Bmg."""
    from gcrip.formats import rarc, yay0, yaz0

    e = disc.entries.get(arc_path)
    if e is None:
        raise FileNotFoundError(f"{arc_path} not on this disc")
    blob = disc.img.read(e.offset, e.size)
    if blob[:4] == b"Yaz0":
        blob = yaz0.decompress(blob)
    elif blob[:4] == b"Yay0":
        blob = yay0.decompress(blob)
    arc = rarc.parse(blob)
    out: dict[str, bmg_mod.Bmg] = {}
    for f in arc.files:
        if f.path.lower().endswith(".bmg"):
            out[Path(f.path).name] = bmg_mod.parse(arc.read(blob, f))
    return out


def _md_escape(text: str) -> str:
    return text.replace("\n", "  \n")


def write_outputs(bmgs: dict[str, bmg_mod.Bmg], out_dir: Path, quiet: bool = False) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    md = ["# Messages", ""]
    for name, b in bmgs.items():
        md += [f"## {name}", "", f"{len(b.messages)} messages, group {b.group_id}", ""]
        for m in b.messages:
            records.append(
                {
                    "file": name,
                    "id": m.id,
                    "index": m.index,
                    "text": m.text,
                    "attrs": m.attrs,
                    "raw_hex": m.raw_bytes.hex(),
                }
            )
            a = m.attrs
            head = f"### {m.id} ({a.get('text_box_type_name', '?')}, {a.get('draw_type_name', '?')}"
            if a.get("next_message_id"):
                head += f", next {a['next_message_id']}"
            if a.get("item_price"):
                head += f", price {a['item_price']}"
            md += [head + ")", "", _md_escape(m.text) or "_(empty)_", ""]
    json_path = out_dir / "messages.json"
    json_path.write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "messages.md").write_text("\n".join(md), encoding="utf-8")
    if not quiet:
        print(f"wrote {len(records)} messages -> {json_path}")
    return json_path


def dump_messages(rip_dir: Path, iso: Path | None = None, quiet: bool = False) -> Path:
    rip_dir = Path(rip_dir)
    disc = _Disc(_find_iso(rip_dir, iso))
    try:
        bmgs = read_bmgs(disc)
    finally:
        disc.close()
    return write_outputs(bmgs, rip_dir / "text", quiet=quiet)
