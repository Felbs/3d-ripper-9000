"""STB cutscene parsing (synthetic file built here, layout per gcrip.formats.stb docstring)."""

from __future__ import annotations

import json
import struct

from gcrip.formats import stb


def _align4(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def seq_wait(frames: int) -> bytes:
    return struct.pack(">I", (0x02 << 24) | frames)


def seq_end() -> bytes:
    return struct.pack(">I", 0)


def para(ptype: int, content: bytes) -> bytes:
    """Short (16-bit) paragraph header: u16 size, u16 type, then padded content."""
    return struct.pack(">HH", len(content), ptype) + _align4(content)


def para_long(ptype: int, content: bytes) -> bytes:
    """Long (32-bit) paragraph header: u16 size-hi|0x8000, u16 size-lo, u32 type."""
    n = len(content)
    return struct.pack(">HHI", 0x8000 | (n >> 16), n & 0xFFFF, ptype) + _align4(content)


def seq_paragraphs(*paras: bytes) -> bytes:
    body = b"".join(paras)
    return struct.pack(">I", (0x80 << 24) | len(body)) + body


def pt(feature: int, op: int) -> int:
    return (feature << 5) | op


def data_record(status: int, values: bytes, count: int | None = None) -> bytes:
    """One TParse_TParagraph_data entry; count != None sets the 0x08 count flag."""
    if count is None:
        return bytes([status]) + values
    return bytes([status | 0x08, count]) + values


def data_paragraph(data_id: int, *records: bytes) -> bytes:
    """A 0x81 data blob: TParagraph {u16 pad, u16 id_size, u8 id[]} then the chain."""
    body = struct.pack(">HH", 0, 4) + struct.pack(">I", data_id)
    return para(0x81, body + b"".join(records) + b"\0")


def block_object(fourcc: bytes, obj_id: bytes, sequence: bytes, flag: int = 0) -> bytes:
    body = struct.pack(">HH", flag, len(obj_id)) + _align4(obj_id) + sequence
    return struct.pack(">I", 8 + len(body)) + fourcc + body


def block_control(sequence: bytes) -> bytes:
    return struct.pack(">II", 8 + len(sequence), 0xFFFFFFFF) + sequence


def fvb_block(ftype: int, *paras: bytes, obj_id: bytes = b"") -> bytes:
    body = _align4(obj_id) + b"".join(paras)
    return struct.pack(">IHH", 8 + len(body), ftype, len(obj_id)) + body


def block_fvb(*blocks: bytes) -> bytes:
    body = b"".join(blocks)
    fvb = struct.pack(">4sHHII", b"FVB\0", 0xFEFF, 0x0100, 0x10 + len(body), len(blocks))
    fvb += body
    return struct.pack(">I", 8 + len(fvb)) + b"JFVB" + fvb


def build_stb(*blocks: bytes, version: int = 3) -> bytes:
    body = b"".join(blocks)
    head = struct.pack(">4sHHII", b"STB\0", 0xFEFF, version, 0x20 + len(body), len(blocks))
    head += b"jstudio\0" + struct.pack(">HHHH", 0, 0, 0, 3)
    assert len(head) == 0x20
    return head + body


def make_file() -> bytes:
    # a hermite curve (stride 3: time, value, tangent) and a constant, in the JFVB block
    hermite = fvb_block(
        6,
        para(0x12, struct.pack(">2f", 0.0, 2.0)),  # range 0..2 s
        para(0x16, struct.pack(">I", 1)),  # linear (ignored by hermite)
        para(
            1, struct.pack(">I", (3 << 28) | 2) + struct.pack(">6f", 0.0, 10.0, 0.0, 2.0, 30.0, 0.0)
        ),
        para(0, b""),
    )
    constant = fvb_block(2, para(1, struct.pack(">f", 7.5)), para(0, b""))
    curves = block_fvb(hermite, constant)

    actor = block_object(
        b"JACT",
        b"Link",
        seq_paragraphs(
            para(pt(12, 0x02), struct.pack(">3f", 1.0, 2.0, 3.0)),  # TRANSLATION_XYZ
            para(pt(58, 0x19), struct.pack(">I", 42)),  # ANIMATION id
            para(pt(48, 0x18), b"Ba1\0"),  # PARENT by name
        )
        + seq_wait(10)
        + seq_paragraphs(
            para(pt(59, 0x12), struct.pack(">I", 0)),  # ANIMATION_FRAME <- curve 0
            data_paragraph(
                1,
                data_record(0x32, struct.pack(">3H", 0x27A, 0x26D, 0x21E), 3),
                data_record(0x31, b"\x04\x02", 2),
            ),
        )
        + seq_wait(5)
        + seq_end(),
    )
    camera = block_object(
        b"JCMR",
        b"camera",
        seq_paragraphs(
            para_long(pt(24, 0x02), struct.pack(">3f", -1.0, 5.0, 9.0)),  # POSITION_XYZ
            para(pt(39, 0x12), struct.pack(">I", 1)),  # FOVY <- curve 1
        )
        + seq_wait(30)
        + seq_end(),
        flag=0x8000,  # starts disabled
    )
    control = block_control(seq_wait(30) + seq_end())
    return build_stb(curves, actor, camera, control)


def test_header_and_blocks():
    s = stb.parse(make_file())
    assert (s.version, s.target, s.target_version) == (3, "jstudio", 3)
    assert s.size == len(make_file())
    assert [b.type_name for b in s.blocks] == ["JFVB", "JACT", "JCMR", "NONE"]
    # the block table must tile the file exactly
    assert s.blocks[0].offset == 0x20
    assert s.blocks[-1].offset + s.blocks[-1].size == s.size
    assert [o.id for o in s.objects] == ["Link", "camera"]
    assert [o.kind for o in s.objects] == ["actor", "camera"]
    assert s.control is not None and s.control.kind == "control"
    assert s.frames == 30 and abs(s.seconds - 1.0) < 1e-9


def test_object_flags_and_timing():
    s = stb.parse(make_file())
    link, camera = s.objects
    assert link.enabled and not camera.enabled  # flag bit 0x8000
    assert link.frames == 15 and camera.frames == 30
    kinds = [c.kind for c in link.commands]
    assert kinds == ["paragraph", "wait", "paragraph", "wait", "end"]
    assert [c.frame for c in link.commands] == [0, 0, 10, 10, 15]


def test_actor_tracks():
    s = stb.parse(make_file())
    tracks = {t.name: t for t in s.objects[0].tracks}
    assert set(tracks) == {"TRANSLATION_XYZ", "ANIMATION", "PARENT", "ANIMATION_FRAME"}

    xyz = tracks["TRANSLATION_XYZ"]
    assert xyz.feature == 12 and xyz.value_indices == (3, 4, 5)
    assert xyz.keys[0].frame == 0 and xyz.keys[0].op_name == "immediate"
    assert xyz.keys[0].value == [1.0, 2.0, 3.0]

    assert tracks["ANIMATION"].keys[0].value == 42
    assert tracks["ANIMATION"].keys[0].op_name == "id"
    assert tracks["PARENT"].keys[0].value == "Ba1"
    frame_key = tracks["ANIMATION_FRAME"].keys[0]
    assert (frame_key.frame, frame_key.op_name, frame_key.value) == (10, "fvr_index", 0)


def test_camera_long_paragraph_header():
    s = stb.parse(make_file())
    tracks = {t.name: t for t in s.objects[1].tracks}
    assert tracks["POSITION_XYZ"].value_indices == (0, 1, 2)
    assert tracks["POSITION_XYZ"].keys[0].value == [-1.0, 5.0, 9.0]
    assert tracks["PROJECTION_FOVY"].keys[0].value == 1  # curve index


def test_data_blob_records():
    s = stb.parse(make_file())
    events = s.objects[0].data_events
    assert len(events) == 1
    frame, data_id, records = events[0]
    assert (frame, data_id) == (10, 1)
    assert [r.elem_size for r in records] == [2, 1]
    assert [r.count for r in records] == [3, 2]
    assert records[0].values == [0x27A, 0x26D, 0x21E]
    assert records[1].values == [4, 2]
    assert not records[0].signed and not records[1].signed
    # a signed record uses the 0x20 kind nibble
    signed = stb.parse_data_records(data_record(0x21, b"\xff\x0a", 2) + b"\0")
    assert signed[0].signed and signed[0].values == [-1, 10]


def test_function_values():
    s = stb.parse(make_file())
    assert [f.kind for f in s.functions] == ["hermite", "constant"]
    herm, const = s.functions
    assert herm.range == (0.0, 2.0)
    assert herm.stride == 3 and len(herm.points) == 2
    assert herm.points[0] == (0.0, 10.0, 0.0)
    assert const.constant == 7.5 and const.value_at(1.0) == 7.5
    # hermite with zero tangents: endpoints exact, smoothstep in between
    assert abs(herm.value_at(0.0) - 10.0) < 1e-5
    assert abs(herm.value_at(2.0) - 30.0) < 1e-5
    assert abs(herm.value_at(1.0) - 20.0) < 1e-5
    assert 10.0 < herm.value_at(0.5) < 20.0


def test_to_dict_is_json_serialisable():
    s = stb.parse(make_file())
    d = stb.to_dict(s)
    text = json.dumps(d, ensure_ascii=False)
    assert '"frames": 30' in text
    assert d["objects"][0]["id"] == "Link"
    assert d["objects"][1]["enabled"] is False
    assert d["functions"][0]["kind"] == "hermite"
    assert d["functions"][0]["points"][1] == [2.0, 30.0, 0.0]
    assert d["objects"][0]["data"][0]["records"][0]["values"] == [0x27A, 0x26D, 0x21E]
    assert "camera" in stb.summary(s)


def test_dump_json(tmp_path):
    out = tmp_path / "tale.json"
    s = stb.dump_json(make_file(), out)
    assert s.frames == 30
    assert json.loads(out.read_text("utf-8"))["target"] == "jstudio"


def test_rejects_bad_files():
    import pytest

    with pytest.raises(ValueError, match="signature"):
        stb.parse(b"JSGF" + bytes(0x40))
    with pytest.raises(ValueError, match="too small"):
        stb.parse(b"STB\0")
    bad_order = bytearray(make_file())
    bad_order[4:6] = b"\xff\xfe"
    with pytest.raises(ValueError, match="byte order"):
        stb.parse(bytes(bad_order))
    bad_size = bytearray(make_file())
    struct.pack_into(">I", bad_size, 0x20, 4)  # first block claims size 4
    with pytest.raises(ValueError, match="bad size"):
        stb.parse(bytes(bad_size))
