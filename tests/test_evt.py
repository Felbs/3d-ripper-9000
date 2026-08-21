"""event_list.dat parsing (synthetic file built here, layout per gcrip.formats.evt docstring)."""

from __future__ import annotations

import json
import struct

from gcrip.formats import evt


def _name(s: str, n: int = 32) -> bytes:
    return s.encode().ljust(n, b"\0")


def build_event_list(events: list[dict]) -> bytes:
    """events = [{"name", "priority", "staff": [{"name", "type", "cuts": [{"name",
    "start": [3], "props": [(name, type, value)]}]}]}] -> bytes."""
    floats: list[float] = []
    ints: list[int] = []
    spool = bytearray()
    ev_recs, st_recs, cut_recs, dt_recs = [], [], [], []
    flag = 0
    for ev in events:
        staff_idx = []
        for st in ev["staff"]:
            cut_idx = []
            for cut in st["cuts"]:
                prop_idx = []
                for pname, ptype, val in cut["props"]:
                    if ptype == evt.TYPE_FLOAT:
                        vals = val if isinstance(val, list) else [val]
                        sidx, ssize = len(floats), len(vals)
                        floats += vals
                    elif ptype == evt.TYPE_VEC:
                        vals = val if isinstance(val, list) else [val]
                        sidx, ssize = len(floats), len(vals)
                        for v in vals:
                            floats += list(v)
                    elif ptype == evt.TYPE_INT:
                        vals = val if isinstance(val, list) else [val]
                        sidx, ssize = len(ints), len(vals)
                        ints += vals
                    else:
                        raw = val.encode() + b"\0"
                        raw += b"\0" * (-len(raw) % 8)
                        sidx, ssize = len(spool), len(raw)
                        spool += raw
                    prop_idx.append(len(dt_recs))
                    dt_recs.append([pname, len(dt_recs), ptype, sidx, ssize, -1])
                for a, b in zip(prop_idx, prop_idx[1:], strict=False):
                    dt_recs[a][5] = b
                first_dt = prop_idx[0] if prop_idx else -1
                cut_idx.append(len(cut_recs))
                s0, s1, s2 = cut.get("start", [-1, -1, -1])
                cut_recs.append([cut["name"], 0, len(cut_recs), s0, s1, s2, flag, first_dt, -1])
                flag += 1
            for a, b in zip(cut_idx, cut_idx[1:], strict=False):
                cut_recs[a][8] = b
            staff_idx.append(len(st_recs))
            st_recs.append([st["name"], 0, len(st_recs), flag, st["type"], cut_idx[0]])
            flag += 1
            last_cut_flag = cut_recs[cut_idx[-1]][6]
        ev_recs.append((ev["name"], ev.get("priority", 0), staff_idx, last_cut_flag))

    out = bytearray(b"\0" * evt.HEADER_SIZE)
    ev_top = len(out)
    for i, (name, prio, sidx, last_cut_flag) in enumerate(ev_recs):
        slots = sidx + [-1] * (evt.EVENT_MAX_STAFF - len(sidx))
        rec = _name(name) + struct.pack(">3i", i, 1, prio) + struct.pack(">20i", *slots)
        rec += struct.pack(">6i", len(sidx), -1, -1, last_cut_flag, -1, -1) + bytes(0xB0 - 0x94)
        assert len(rec) == evt.EVENT_SIZE
        out += rec
    st_top = len(out)
    for name, tag, idx, fl, typ, first in st_recs:
        out += _name(name) + struct.pack(">5i", tag, idx, fl, typ, first) + bytes(0x1C)
    cut_top = len(out)
    for name, *rest in cut_recs:
        out += _name(name) + struct.pack(">8i", *rest) + bytes(0x10)
    dt_top = len(out)
    for name, *rest in dt_recs:
        out += _name(name) + struct.pack(">5i", *rest) + bytes(0xC)
    f_top = len(out)
    out += struct.pack(f">{len(floats)}f", *floats)
    i_top = len(out)
    out += struct.pack(f">{len(ints)}i", *ints)
    s_top = len(out)
    out += spool
    struct.pack_into(
        ">14I",
        out,
        0,
        ev_top,
        len(ev_recs),
        st_top,
        len(st_recs),
        cut_top,
        len(cut_recs),
        dt_top,
        len(dt_recs),
        f_top,
        len(floats),
        i_top,
        len(ints),
        s_top,
        len(spool),
    )
    return bytes(out)


SAMPLE = [
    {
        "name": "omedeto",
        "priority": 2,
        "staff": [
            {
                "name": "Ls1",
                "type": 0,
                "cuts": [
                    {"name": "WAIT", "props": [("Timer", evt.TYPE_INT, 40)]},
                    {"name": "TALK_MSG", "props": [("msg_num", evt.TYPE_INT, 3001)]},
                ],
            },
            {
                "name": "CAMERA",
                "type": 2,
                "cuts": [
                    {
                        "name": "FIXEDFRM",
                        "start": [0, -1, -1],
                        "props": [
                            ("Eye", evt.TYPE_VEC, (58.0, -76.0, -75.0)),
                            ("Fovy", evt.TYPE_FLOAT, 52.0),
                            ("RelActor", evt.TYPE_STRING, "@STARTER"),
                            ("Color", evt.TYPE_INT, [255, 0, 0, 255]),
                        ],
                    },
                    {"name": "PAUSE", "props": []},
                ],
            },
        ],
    },
    {
        "name": "DEFAULT_TALK",
        "staff": [{"name": "TALKMAN", "type": 10, "cuts": [{"name": "TALK", "props": []}]}],
    },
]


def test_parse_synthetic():
    evl = evt.parse(build_event_list(SAMPLE))
    assert evl.names() == ["omedeto", "DEFAULT_TALK"]
    ev = evl["omedeto"]
    assert ev.priority == 2 and ev.finish_flags == [4, -1, -1]
    assert [s.name for s in ev.actors] == ["Ls1", "CAMERA"]
    ls1 = ev.staff("Ls1")
    assert ls1.type_name == "NORMAL"
    assert [a.name for a in ls1.actions] == ["WAIT", "TALK_MSG"]
    assert ls1.actions[0].properties == {"Timer": 40}
    assert ls1.actions[0].end_flag == 0 and ls1.actions[1].end_flag == 1
    cam = ev.staff("CAMERA")
    assert cam.type_name == "CAMERA"
    fixed = cam.actions[0]
    assert fixed.start_flags == [0, -1, -1]  # waits for Ls1's WAIT to finish
    assert fixed.properties["Eye"] == (58.0, -76.0, -75.0)
    assert fixed.properties["Fovy"] == 52.0
    assert fixed.properties["RelActor"] == "@STARTER"
    assert fixed.properties["Color"] == [255, 0, 0, 255]
    assert [p.type_name for p in fixed.props] == ["vec", "float", "string", "int"]
    assert cam.actions[1].properties == {}
    assert evl["DEFAULT_TALK"].actors[0].type_name == "TEN"


def test_json_roundtrip(tmp_path):
    out = tmp_path / "ev.json"
    evt.dump_json(build_event_list(SAMPLE), out)
    data = json.loads(out.read_text("utf-8"))
    assert [e["name"] for e in data] == ["omedeto", "DEFAULT_TALK"]
    cam = data[0]["actors"][1]
    assert cam["type"] == "CAMERA"
    assert cam["actions"][0]["properties"]["Eye"] == {"type": "vec", "value": [58.0, -76.0, -75.0]}
    assert "omedeto" in evt.summary(evt.parse(build_event_list(SAMPLE)))


def test_bad_type_rejected():
    blob = bytearray(build_event_list(SAMPLE))
    dt_top = struct.unpack_from(">I", blob, 0x18)[0]
    struct.pack_into(">i", blob, dt_top + 0x24, 2)  # reserved type
    try:
        evt.parse(bytes(blob))
    except ValueError as e:
        assert "type 2" in str(e)
    else:
        raise AssertionError("expected ValueError")
