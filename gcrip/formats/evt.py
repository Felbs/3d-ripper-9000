"""event_list.dat - Wind Waker cutscene/event scripts (one per stage, in Stage.arc "dat/").

Layout (big-endian, verified against sea/Stage.arc and LinkRM/Stage.arc; field names follow the
zeldaret/tww decompilation: d_event_data.h / d_event_manager.cpp).  The file is a set of
fixed-size tables that the game uses in place (the runtime-state fields inside each entry are
zero on disc and are mutated in memory while an event plays).

Header (0x40 bytes, `event_binary_data_header`):
  0x00 u32 eventTop   0x04 s32 eventNum   - Event table   (0xB0 bytes each)
  0x08 u32 staffTop   0x0C s32 staffNum   - Staff table   (0x50 bytes each)  "actors"
  0x10 u32 cutTop     0x14 s32 cutNum     - Cut table     (0x50 bytes each)  "actions"
  0x18 u32 dataTop    0x1C s32 dataNum    - Data table    (0x40 bytes each)  "properties"
  0x20 u32 fDataTop   0x24 s32 fDataNum   - f32 pool
  0x28 u32 iDataTop   0x2C s32 iDataNum   - s32 pool
  0x30 u32 sDataTop   0x34 s32 sDataNum   - string pool; sDataNum is its BYTE size
  0x38 u8[8] zero
In every retail file the tables follow the header in that order, back to back.

Event (dEvDtEvent_c, 0xB0):
  0x00 char[32] name        0x20 s32 index (== own slot)   0x24 u32 unk (0/1/3 seen)
  0x28 u32 priority         0x2C s32 staff[20] (-1 = empty, used slots first)
  0x7C s32 nStaff           0x80 s32 flagCheckStart[2]     0x88 s32 flagCheckFinish[3]
  0x94 u8  endSound (plays the "riddle" jingle when the event starts)
  0x95..0xB0 zero: runtime (0xA4 is mEventState: NONE/ORDER/PLAY/3/CLOSE)
  The event is finished when every flagCheckFinish id (until the first -1) is set.

Staff (dEvDtStaff_c, 0x50) - a cast member of one event:
  0x00 char[32] name        0x20 s32 tagId (matched against getMyStaffId()'s 3rd arg, ~always 0)
  0x24 s32 index            0x28 s32 flagId (event flag set when this staff is done; unused by
  the manager but unique per entry)   0x2C s32 type (StaffType below)   0x30 s32 firstCut
  0x34..0x50 zero: runtime (curCut, curActionIdx, wipeDir, timer, advance, hasAction...)

Cut (dEvDtCut_c, 0x50) - one action in a staff's singly linked list:
  0x00 char[32] name        0x20 u32 tagId ("duplicate id", 0..4 seen)   0x24 s32 index
  0x28 s32 startFlag[3]     0x34 s32 flagId (set by cutEnd() when the action completes)
  0x38 s32 firstData        0x3C s32 nextCut (-1 = last)    0x40..0x50 zero (runtime)

Data (dEvDtData_c, 0x40) - a named property of a cut, singly linked via nextIdx:
  0x00 char[32] name   0x20 s32 index   0x24 s32 type   0x28 s32 substanceIdx
  0x2C s32 substanceSize   0x30 s32 nextIdx   0x34 u32[3] zero
  type 0 FLOAT : substanceSize floats at fData[substanceIdx]
  type 1 VEC   : substanceSize xyz triples at fData[substanceIdx] (3 floats each)
  type 3 INT   : substanceSize ints at iData[substanceIdx]
  type 4 STRING: NUL-terminated string at sData + substanceIdx; substanceSize is the
                 8-byte-padded length (strings are padded to 8 in the pool)
  (type 2 is reserved in the enum and never appears on disc)

Flags: a 0x2800-bit bitfield (dEvDtFlag_c, cleared on event start).  A cut may start when all
its startFlag ids are set (or, if startFlag[0] == -1, when the previous cut's flagId is set).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HEADER_SIZE = 0x40
EVENT_SIZE = 0xB0
STAFF_SIZE = 0x50
CUT_SIZE = 0x50
DATA_SIZE = 0x40
EVENT_MAX_STAFF = 20

TYPE_FLOAT, TYPE_VEC, TYPE_INT, TYPE_STRING = 0, 1, 3, 4

STAFF_TYPES = {
    0: "NORMAL",  # a stage actor found by name (dStage_searchName), runs its own cut code
    1: "ALL",  # applies to every actor with the given name; manager auto-ends its cuts
    2: "CAMERA",  # dCamera_c::eventCamera (PAUSE/WAIT/TALK/FIXEDPOS/FIXEDFRM/UNITRANS/...)
    3: "EFFECT",
    4: "TIMEKEEPER",  # COUNTDOWN(Timer) / WAIT
    5: "FIVE",
    6: "DIRECTOR",  # WAIT/NEXT/FADE/BGM_START/VIBRATION/SE_START/WIPE/PLAYER_DRAW/PLAYER_NODRAW
    7: "MESSAGE",  # WAIT/CREATE_MSG/PUSHBUTTON/FINISH/CONTINUE/END/DELETE/TELOP_ON/TELOP_OFF
    8: "SOUND",  # WAIT/STRM_PLAY/.../NOMSG_WAIT/RIDDLE/LANDING_DEMO/BGMSTOP
    9: "LIGHT",  # WAIT/CHANGE/ADD_TIME
    10: "TEN",
    11: "PACKAGE",  # WAIT/PLAY/PLAY2 - plays a JStudio .stb demo (dDemo_manager_c)
    12: "CREATE",  # WAIT/CREATE - spawns an actor (MAKECAST/ARG/POS/ANGLE/SCALE)
}


@dataclass
class Property:
    name: str
    type: int  # TYPE_*
    value: Any  # float|list[float] / tuple|list[tuple] / int|list[int] / str
    index: int = -1

    @property
    def type_name(self) -> str:
        return {0: "float", 1: "vec", 3: "int", 4: "string"}.get(self.type, f"type{self.type}")


@dataclass
class Action:
    name: str
    properties: dict[str, Any] = field(default_factory=dict)  # name -> value
    flags: dict[str, Any] = field(default_factory=dict)  # start:[3], end:int, tag:int
    index: int = -1
    props: list[Property] = field(default_factory=list)  # typed, in file order

    @property
    def start_flags(self) -> list[int]:
        return self.flags.get("start", [-1, -1, -1])

    @property
    def end_flag(self) -> int:
        return self.flags.get("end", -1)


@dataclass
class Staff:
    name: str
    type: int
    actions: list[Action] = field(default_factory=list)
    tag_id: int = 0
    flag_id: int = -1
    index: int = -1

    @property
    def type_name(self) -> str:
        return STAFF_TYPES.get(self.type, f"type{self.type}")


@dataclass
class Event:
    name: str
    actors: list[Staff] = field(default_factory=list)
    priority: int = 0
    unk: int = 0
    start_flags: list[int] = field(default_factory=lambda: [-1, -1])
    finish_flags: list[int] = field(default_factory=lambda: [-1, -1, -1])
    end_sound: int = 0
    index: int = -1

    def staff(self, name: str) -> Staff | None:
        return next((s for s in self.actors if s.name == name), None)


@dataclass
class EventList:
    events: list[Event]

    def __getitem__(self, name: str) -> Event:
        for e in self.events:
            if e.name == name:
                return e
        raise KeyError(name)

    def names(self) -> list[str]:
        return [e.name for e in self.events]


def _cstr(buf: bytes, off: int, size: int) -> str:
    raw = buf[off : off + size]
    return raw.split(b"\0", 1)[0].decode("shift_jis", errors="replace")


def parse(data: bytes) -> EventList:
    """Parse event_list.dat bytes into an EventList."""
    if len(data) < HEADER_SIZE:
        raise ValueError("event_list.dat: too short for header")
    h = struct.unpack_from(">14I", data, 0)
    ev_top, n_ev, st_top, n_st, cut_top, n_cut, dt_top, n_dt = h[:8]
    f_top, n_f, i_top, n_i, s_top, s_size = h[8:14]

    floats = list(struct.unpack_from(f">{n_f}f", data, f_top)) if n_f else []
    ints = list(struct.unpack_from(f">{n_i}i", data, i_top)) if n_i else []
    spool = data[s_top : s_top + s_size]

    # properties
    props: list[Property] = []
    prop_next: list[int] = []
    for k in range(n_dt):
        o = dt_top + k * DATA_SIZE
        name = _cstr(data, o, 32)
        idx, typ, sidx, ssize, nxt = struct.unpack_from(">5i", data, o + 0x20)
        if typ == TYPE_FLOAT:
            vals: Any = floats[sidx : sidx + ssize]
            value = vals[0] if ssize == 1 else vals
        elif typ == TYPE_VEC:
            vals = [tuple(floats[sidx + 3 * j : sidx + 3 * j + 3]) for j in range(ssize)]
            value = vals[0] if ssize == 1 else vals
        elif typ == TYPE_INT:
            vals = ints[sidx : sidx + ssize]
            value = vals[0] if ssize == 1 else vals
        elif typ == TYPE_STRING:
            value = spool[sidx:].split(b"\0", 1)[0].decode("shift_jis", errors="replace")
        else:
            raise ValueError(f"event_list.dat: unknown property type {typ} ({name!r})")
        props.append(Property(name, typ, value, idx))
        prop_next.append(nxt)

    # cuts (actions)
    cuts: list[Action] = []
    cut_next: list[int] = []
    for k in range(n_cut):
        o = cut_top + k * CUT_SIZE
        name = _cstr(data, o, 32)
        tag, idx, s0, s1, s2, flag, first_dt, nxt = struct.unpack_from(">8i", data, o + 0x20)
        act = Action(name, flags={"start": [s0, s1, s2], "end": flag, "tag": tag}, index=idx)
        j = first_dt
        seen = 0
        while j != -1:
            if j < 0 or j >= n_dt or seen > n_dt:
                raise ValueError(f"event_list.dat: bad property chain in cut {name!r}")
            p = props[j]
            act.props.append(p)
            act.properties[p.name] = p.value
            j = prop_next[j]
            seen += 1
        cuts.append(act)
        cut_next.append(nxt)

    # staff (actors)
    staff: list[Staff] = []
    for k in range(n_st):
        o = st_top + k * STAFF_SIZE
        name = _cstr(data, o, 32)
        tag, idx, flag, typ, first_cut = struct.unpack_from(">5i", data, o + 0x20)
        s = Staff(name, typ, tag_id=tag, flag_id=flag, index=idx)
        j = first_cut
        seen = 0
        while j != -1:
            if j < 0 or j >= n_cut or seen > n_cut:
                raise ValueError(f"event_list.dat: bad cut chain in staff {name!r}")
            s.actions.append(cuts[j])
            j = cut_next[j]
            seen += 1
        staff.append(s)

    # events
    events: list[Event] = []
    for k in range(n_ev):
        o = ev_top + k * EVENT_SIZE
        name = _cstr(data, o, 32)
        idx, unk, prio = struct.unpack_from(">3i", data, o + 0x20)
        slots = struct.unpack_from(f">{EVENT_MAX_STAFF}i", data, o + 0x2C)
        n_staff, fs0, fs1, ff0, ff1, ff2 = struct.unpack_from(">6i", data, o + 0x7C)
        end_sound = data[o + 0x94]
        ev = Event(name, [], prio, unk, [fs0, fs1], [ff0, ff1, ff2], end_sound, idx)
        for si in slots[:n_staff]:
            if si != -1:
                ev.actors.append(staff[si])
        events.append(ev)
    return EventList(events)


# ---------------------------------------------------------------- JSON ----


def _json_value(v: Any) -> Any:
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, list):
        return [_json_value(x) for x in v]
    return v


def to_dict(evl: EventList) -> list[dict[str, Any]]:
    out = []
    for ev in evl.events:
        out.append(
            {
                "name": ev.name,
                "priority": ev.priority,
                "unk": ev.unk,
                "end_sound": ev.end_sound,
                "start_flags": ev.start_flags,
                "finish_flags": ev.finish_flags,
                "actors": [
                    {
                        "name": s.name,
                        "type": s.type_name,
                        "tag_id": s.tag_id,
                        "flag_id": s.flag_id,
                        "actions": [
                            {
                                "name": a.name,
                                "start_flags": a.start_flags,
                                "end_flag": a.end_flag,
                                "tag": a.flags.get("tag", 0),
                                "properties": {
                                    p.name: {"type": p.type_name, "value": _json_value(p.value)}
                                    for p in a.props
                                },
                            }
                            for a in s.actions
                        ],
                    }
                    for s in ev.actors
                ],
            }
        )
    return out


def dump_json(data: bytes, out_path: str | Path) -> EventList:
    """Parse event_list.dat bytes and write them as JSON to out_path."""
    evl = parse(data)
    Path(out_path).write_text(json.dumps(to_dict(evl), indent=1, ensure_ascii=False), "utf-8")
    return evl


def dump_stage_events(iso: str | Path, stage: str, out_path: str | Path) -> EventList:
    """Read res/Stage/<stage>/Stage.arc -> dat/event_list.dat from a disc image and dump it."""
    from gcrip.stage import _Disc  # local import: stage pulls in the disc/rarc stack

    blob = _Disc(Path(iso)).read_inner(f"res/Stage/{stage}/Stage.arc", "event_list.dat")
    if blob is None:
        raise FileNotFoundError(f"{stage}: no event_list.dat in Stage.arc")
    return dump_json(blob, out_path)


def summary(evl: EventList) -> str:
    """One line per event: name, then actor[type]: action, action..."""
    lines = []
    for ev in evl.events:
        lines.append(f"{ev.name} (prio {ev.priority})")
        for s in ev.actors:
            acts = ", ".join(a.name for a in s.actions)
            lines.append(f"  {s.name} [{s.type_name}]: {acts}")
    return "\n".join(lines)
