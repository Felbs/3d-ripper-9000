"""Dump the story wiring of a stage: which spawn or trigger volume orders which event.

This is the raw material a story graph is mined from.  For each stage it prints the EVNT
table, then every PLYR spawn and every TagEv / AttTag volume with the event each one orders,
the switch that remembers it fired, and the event bit that gates it.

    python tools/ww_story_mine.py MajyuE majroom Mjtower
    python tools/ww_story_mine.py --rooms sea 1 11 13     # only these rooms of a big stage

Decoding (src/d/actor/d_a_tag_event.cpp:18-45):
    getEventNo  = params >> 24     index into the stage's EVNT table
    getSwbit2   = params >> 16     & 0xFF
    getSwbit    = params >> 8      & 0xFF
    getType     = params & 0xFF    daTag_Event_c::Action_e
    rot.z                          required event bit (0 / 0xFFFF = none)
A PLYR spawn carries the same event index in params >> 24 (d_a_player_main.cpp:12321).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RIP = ROOT / "out" / "rip" / "GZLE01"

ACTION_E = {
    0x0: "WAIT",
    0x1: "ARRIVAL",
    0x2: "HUNT",
    0x3: "HUNT2",
    0x4: "READY",
    0x5: "EVENT",
    0x6: "SPE_ARRIVAL",
    0x7: "SPE_HUNT",
    0x8: "SPE_READY",
    0x9: "SPE_EVENT",
    0xA: "MJ_HUNT",
    0xB: "MJ_READY",
}

# every stage carries these; they are engine plumbing, not story
BOILERPLATE = re.compile(
    r"^(DEFAULT_|KNOB_|SHUTTER_|BS_SHUTTER|MBDOOR_|RiddleSound|OPTION_CHAR_|TIMEWARP"
    r"|MapToolCamera|NORMAL_COMEBACK|SHORT_COMEBACK|MAGMA_COMEBACK|TORNADO_COMEBACK"
    r"|fire_o|zenfire|FMASTER_START|TACT_WINDOW|WARPT_OPEN|DUNGEON_WARP|FALL_START"
    r"|barrel2_brk|DUMMY)"
)


def report_for(stage: str) -> dict | None:
    """The report for this stage. Several rips can hold a file of the same name (Outset also
    carries a sea_report.json), so the directory named after the stage wins."""
    named = RIP / "stages" / stage / f"{stage}_report.json"
    if named.exists():
        return json.loads(named.read_text(encoding="utf-8"))
    best = None
    for d in sorted(RIP.glob("stages/*/")):
        for f in d.glob(f"{stage}_report.json"):
            cand = json.loads(f.read_text(encoding="utf-8"))
            if best is None or len(cand.get("spawns") or []) > len(best.get("spawns") or []):
                best = cand
    return best


def events_for(stage: str) -> list[str]:
    f = RIP / "godot" / "events" / f"{stage}.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text(encoding="utf-8"))
    return [str(e.get("name", "")) for e in data]


def show(stage: str, rooms: set[int] | None) -> None:
    rep = report_for(stage)
    if rep is None:
        print(f"== {stage}: no ripped report (build it with `gcrip stage`)")
        return
    table = rep.get("event_table") or []
    scripts = events_for(stage)
    story_scripts = [e for e in scripts if not BOILERPLATE.match(e)]

    print(f"\n{'=' * 78}\n{stage}")
    print(f"  EVNT table ({len(table)}): {', '.join(table) if table else '(none)'}")
    print(f"  event scripts, story-looking ({len(story_scripts)} of {len(scripts)}):")
    print(f"    {', '.join(story_scripts) if story_scripts else '(none)'}")

    def name_of(no: int) -> str:
        return table[no] if 0 <= no < len(table) else f"<no {no} - table has {len(table)}>"

    spawns = [s for s in rep.get("spawns") or [] if rooms is None or s.get("room") in rooms]
    fired = [s for s in spawns if (int(s.get("params", 0)) >> 24) & 0xFF != 0xFF]
    print(f"  PLYR spawns that auto-play an event ({len(fired)} of {len(spawns)}):")
    for s in sorted(fired, key=lambda s: (s.get("room") or 0, s.get("id") or 0)):
        no = (int(s["params"]) >> 24) & 0xFF
        pos = [round(v) for v in s["pos"]]
        print(f"    room {s.get('room')} spawn {s.get('id'):>3}  -> {name_of(no):24} at {pos}")

    tags = [
        t
        for t in rep.get("tags") or []
        if str(t.get("actor", "")).startswith(("TagEv", "AttTag"))
        and (rooms is None or t.get("room") in rooms)
    ]
    print(f"  trigger volumes ({len(tags)}):")
    for t in sorted(tags, key=lambda t: (t.get("room") or 0, t.get("params", 0))):
        p = int(t.get("params", 0))
        no = (p >> 24) & 0xFF
        gate = int(t.get("rot", [0, 0, 0])[2]) & 0xFFFF
        gate_s = "-" if gate in (0, 0xFFFF) else f"0x{gate:04X}"
        pos = [round(v) for v in t["pos"]]
        print(
            f"    room {t.get('room')} layer {t.get('layer'):>3} {t['actor']:7}"
            f" -> {name_of(no):24} type {ACTION_E.get(p & 0xFF, hex(p & 0xFF)):11}"
            f" sw {(p >> 8) & 0xFF:3} gate {gate_s:7} at {pos}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stages", nargs="+")
    ap.add_argument("--rooms", nargs="*", type=int, default=None,
                    help="restrict to these room numbers (for the sea)")
    args = ap.parse_args()
    rooms = set(args.rooms) if args.rooms else None
    for st in args.stages:
        show(st, rooms)


if __name__ == "__main__":
    main()
