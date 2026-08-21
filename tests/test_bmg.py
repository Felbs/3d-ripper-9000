"""BMG message files: synthetic file built in-test, no game data."""

from __future__ import annotations

import struct

from gcrip.formats import bmg


def _block(tag: bytes, body: bytes) -> bytes:
    size = 8 + len(body)
    pad = (-size) % 32
    return tag + struct.pack(">I", size + pad) + body + b"\x00" * pad


def build_bmg(messages: list[tuple[int, bytes, dict]], mid1: bool = False) -> bytes:
    """messages: (id, raw text bytes, attr overrides) -> a MESGbmg1 file with 0x18 entries."""
    pool = bytearray(b"\x00")
    entries = bytearray()
    for mid, raw, attrs in messages:
        off = len(pool)
        pool += raw + b"\x00"
        entries += struct.pack(
            ">IHhHHBBBBBBBBBHB",
            off,
            mid,
            attrs.get("item_price", 0),
            attrs.get("next_message_id", 0),
            0,
            attrs.get("text_box_type", 0),
            attrs.get("draw_type", 0),
            0,
            attrs.get("item_image", 0),
            attrs.get("text_alignment", 0),
            attrs.get("initial_sound", 0),
            0,
            0,
            0,
            attrs.get("lines_per_box", 0),
            0,
        )
    inf1 = _block(b"INF1", struct.pack(">HHHBB", len(messages), 0x18, 0, 0, 0) + entries)
    dat1 = _block(b"DAT1", bytes(pool))
    blocks = inf1 + dat1
    n = 2
    if mid1:
        ids = [m[0] for m in messages]
        body = struct.pack(">HBB4x", len(ids), 0, 0) + struct.pack(f">{len(ids)}I", *ids)
        blocks += _block(b"MID1", body)
        n = 3
    size = 0x20 + len(blocks)
    return b"MESGbmg1" + struct.pack(">II", size, n) + b"\x01" + b"\x00" * 15 + blocks


def test_parse_entries_and_attrs():
    data = build_bmg(
        [
            # escape data contains 0x00 bytes: the string scanner must step over them
            (
                101,
                b"\x1a\x05\x00\x00\x00 got a Sword!",
                {"text_box_type": 9, "draw_type": 2, "item_image": 0x38},
            ),
            (3005, b"Hoy, Big Brother!\nCome here.", {"next_message_id": 3006, "item_price": -1}),
        ]
    )
    b = bmg.parse(data)
    assert bmg.is_bmg(data)
    assert b.entry_size == 0x18 and b.encoding == 1
    assert [m.id for m in b.messages] == [101, 3005]
    m0 = b.messages[0]
    assert m0.text == "{name} got a Sword!"
    assert m0.raw_bytes == b"\x1a\x05\x00\x00\x00 got a Sword!"
    assert m0.attrs["text_box_type_name"] == "item_get"
    assert m0.attrs["draw_type_name"] == "slow"
    assert m0.attrs["item_image"] == 0x38
    m1 = b.messages[1]
    assert m1.text == "Hoy, Big Brother!\nCome here."
    assert m1.attrs["next_message_id"] == 3006
    assert m1.attrs["item_price"] == -1
    assert b.by_id()[3005] is m1


def test_escape_decoding():
    raw = (
        b"\x1a\x05\x00\x00\x00! You got a "  # player name
        b"\x1a\x06\xff\x00\x00\x01Treasure Chart\x1a\x06\xff\x00\x00\x00!"  # red .. default
        b"\x1a\x07\x00\x00\x07\x00\x14"  # wait 20 frames
        b"\n\x1a\x05\x00\x00\x08Yes\nNo"  # two-way choice
        b" \x1a\x05\x00\x00\x0a"  # A button icon
        b"\x1a\x07\xff\x00\x01\x00\x96"  # font size 150%
        b"\x1a\x05\x01\x00\x2a"  # sound 42
        b"\x1a\x05\x00\x00\x24"  # auction bid placeholder
        b"\x1a\x06\x07\x12\x34\xab"  # unknown group/code
    )
    text = bmg.decode_text(raw)
    assert text == (
        "{name}! You got a {color:red}Treasure Chart{color:default}!{wait:20}\n"
        "{choice:2}Yes\nNo {icon:a_button}{size:150}{sound:42}{value:auction_bid}"
        "{tag:07:1234:ab}"
    )


def test_truncated_escape_does_not_raise():
    assert bmg.decode_text(b"abc\x1a\x09\x00") == "abc{tag:bad:1a0900}"


def test_mid1_block():
    b = bmg.parse(build_bmg([(7, b"x", {}), (9, b"y", {})], mid1=True))
    assert b.message_ids == [7, 9]


def test_rejects_non_bmg():
    try:
        bmg.parse(b"J3D2bmd3" + b"\x00" * 64)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
