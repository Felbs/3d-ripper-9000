"""Every cutscene that raises an event bit, read out of the event data itself.

An event script's PACKAGE staff carries a `PLAY` action with a `FileName` (the .stb) and an
`EventFlag` integer.  `dEvDtStaff_c::specialProcPackage` calls `dComIfGs_onEventBit` on that
integer when the cutscene STARTS (src/d/d_event_data.cpp:797-800), so the pairing is the
authoritative answer to "which bit does this cutscene raise" - stronger than searching src/
for an onEventBit call, because for these there is none.

    python tools/ww_stb_flags.py                 # print the table
    python tools/ww_stb_flags.py --apply         # write the bits into gcrip/data/ww_story_*.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "out" / "rip" / "GZLE01" / "godot" / "events"
DATA = ROOT / "gcrip" / "data"

SOURCE = (
    "event data PACKAGE PLAY EventFlag, raised on cutscene start by "
    "dEvDtStaff_c::specialProcPackage (src/d/d_event_data.cpp:797-800)"
)


def _one(v):
    return v[0] if isinstance(v, list) and v else v


def stb_flags() -> dict[str, tuple[int, list[str]]]:
    out: dict[str, tuple[int, set[str]]] = {}
    for f in sorted(EVENTS.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for ev in data:
            for staff in ev.get("actors", []):
                if staff.get("type") != "PACKAGE":
                    continue
                for cut in staff.get("actions", []):
                    props = cut.get("properties") or {}
                    if "EventFlag" not in props:
                        continue
                    bit = _one(props["EventFlag"].get("value"))
                    name = _one((props.get("FileName") or {}).get("value"))
                    if not bit or not name:
                        continue
                    key = str(name)
                    if not key.endswith(".stb"):
                        key += ".stb"
                    prev, stages = out.get(key, (int(bit), set()))
                    out[key] = (int(bit), stages | {f.stem})
    return {k: (v[0], sorted(v[1])) for k, v in sorted(out.items())}


def apply(table: dict[str, tuple[int, list[str]]]) -> None:
    for path in sorted(DATA.glob("ww_story_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        for step in data.get("steps", []):
            stb = step.get("stb")
            if not stb or stb not in table:
                continue
            bit, _stages = table[stb]
            hexbit = f"0x{bit:04X}"
            sets = step.setdefault("sets_bits", [])
            if any(str(b).upper().startswith(hexbit) for b in sets):
                continue
            sets.append(hexbit)
            step["notes"] = (str(step.get("notes") or "").rstrip() + " ").lstrip() + (
                f"{stb} raises {hexbit} when it starts - {SOURCE}."
            )
            changed += 1
        if changed:
            path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
            print(f"  {path.name}: added {changed} bit(s)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    table = stb_flags()
    print(f"{len(table)} cutscenes raise an event bit:")
    for stb, (bit, stages) in table.items():
        print(f"  {stb:26} 0x{bit:04X}   in {', '.join(stages)}")
    if args.apply:
        print("\napplying to the mined chapters:")
        apply(table)


if __name__ == "__main__":
    main()
