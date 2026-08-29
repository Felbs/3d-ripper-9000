"""BMG message files (JSystem JMessage; Wind Waker's res/Msg/bmgres.arc -> zel_00.bmg).

Layout (all big-endian), verified against the USA disc and the game's own readers
(JSystem/JMessage/data.h, f_op/f_op_msg_mng.cpp, d/d_mesg.cpp in the Wind Waker decomp):

  header (0x20):  "MESGbmg1"  u32 file_size  u32 block_count  u8 encoding  pad
  then block_count blocks, each { fourcc, u32 size (incl. header) } 32-byte aligned:

  INF1  u16 entry_count  u16 entry_size  u16 group_id  u8 default_color  u8 pad
        then entry_count entries of entry_size bytes (0x18 in Wind Waker):
          0x00 u32 text_offset       into DAT1's string pool
          0x04 u16 message_id        the number actors/events ask for (not the index)
          0x06 s16 item_price        shop messages
          0x08 u16 next_message_id   0 = none; chained when the box is dismissed
          0x0A u16 unknown_0a
          0x0C u8  text_box_type     see TEXT_BOX_TYPES; the screen each one loads is
                                     chosen in dMsg_Execute
          0x0D u8  draw_type         0 types out (A/B skips), 1 instant, 2 types out and
                                     CANNOT be skipped
          0x0E u8  text_box_position 0 auto (project the speaker's eye against y=240),
                                     1 bottom, 2 centre, 3 top
          0x0F u8  item_image        icon shown in item-get boxes
          0x10 u8  text_alignment    0, 1 or 3; the USA build forces everything except
                                     exactly 3 (or box type 0xD) to left-aligned
          0x11 u8  initial_sound     voice clip played when the box opens
          0x12 u8  initial_camera
          0x13 u8  initial_animation speaker animation
          0x14 u8  unknown_14
          0x15 u8  unknown_15        0 in every entry on the USA disc
          0x16 u8  lines_per_box     `if (lineCount >= mesgEntry->field_0x16)`
          0x17 u8  unknown_17        0 in every entry on the USA disc
  DAT1  NUL-terminated strings; offset 0 is an empty string.
  MID1  (optional, not in Wind Waker) u16 count u8 format u8 info pad[4] then u32 ids.

Text is single-byte (ASCII in the USA build; Shift-JIS lead bytes in Japanese). Newline
is a plain 0x0A. Escape sequences start with 0x1A:

  1A size group code:u16 data[size-5]

  group 00  Wind Waker control codes (MsgControlCodes in f_op_msg_mng.cpp): player name,
            draw-speed switches, waits (u16 frames), choice boxes, button/arrow icons and
            "print this counter" placeholders (rupee counts, auction bids, ...)
  group 01  play sound effect `code`      group 02  camera cue      group 03  speaker anim
  group FF  JMessage system codes: 00 colour (u8 index into color.bmc / the game's
            9-entry table), 01 font size (u16 percent), 02 ruby/furigana text

This module turns them into readable tags such as {name}, {color:red}, {wait:20},
{choice:2}, {icon:a_button}, {sound:150}, {size:150}; unknown ones become
{tag:GG:CCCC:hexdata}. Both the decoded text and the raw bytes are kept.

Field names follow the Wind Waker randomizer's gclib/bmg.py (LagoLunatic, MIT) where
the decomp has no name; the decoding here is an independent implementation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"MESGbmg1"

# Counts are from the USA disc's zel_00.bmg (4411 entries), so every type here really occurs.
TEXT_BOX_TYPES = {
    0: "dialog",  # 3319
    1: "special",  # 38
    2: "wood",  # 24 - its own MSG2 process and its own palette
    5: "demo",  # 22
    6: "wood2",  # 6  - MSG2, like type 2
    7: "wood3",  # 27 - MSG2, like type 2
    8: "type_8",  # 13 - no separate screen; meaning not established
    9: "item_get",  # 193
    0xA: "talk_unfollowed",  # 550 - an ordinary talk box that does NOT follow the actor
    0xB: "type_b",  # 181 - overrides the colour palette
    0xC: "credits",  # 15
    0xD: "centered",  # 14 - the one type that keeps its own alignment
    0xE: "wind_waker_song",  # 9
}

# draw_type, from the box driver: 0 types out and A/B skips it, 1 draws instantly unless a hard
# wait is pending, 2 types out and cannot be skipped at all.  The old names had 0 and 2 swapped.
DRAW_TYPES = {0: "typed", 1: "instant", 2: "typed_unskippable"}

# text_box_position, dMsg_Execute
BOX_POSITIONS = {0: "auto", 1: "bottom", 2: "center", 3: "top"}

# group 0xFF code 0: an index into the message box's palette.  This is color.bmc's CLT1
# table, NOT d_mesg.cpp's colorTable - that belongs to the other renderer and has different
# values.  Box types 2/6/7, box type 0xB, and messages 0x42-0x4B each override the palette.
# CLT1: FFFFFF, FF6400, 00FF00, 7878FF, FFFF3C, 00FFFF, FF00FF, 828282, FF8000.
# On the disc index 0 is used 2574 times and index 1 2544 times; 2-8 total 114.
COLORS = {
    0: "white",
    1: "orange",
    2: "green",
    3: "blue",
    4: "yellow",
    5: "cyan",
    6: "magenta",
    7: "gray",
    8: "dark_orange",
}

# group 0 codes (f_op_msg_mng.cpp enum MsgControlCodes). Values are (tag name, kind):
# kind "" = bare tag, "u16" = tag carries a u16 argument, "icon" = button/arrow glyph,
# "value" = placeholder the game fills with a number/string at runtime.
_CONTROL: dict[int, tuple[str, str]] = {
    0x00: ("name", ""),
    0x01: ("draw:instant", ""),
    0x02: ("draw:char", ""),
    0x03: ("wait_dismiss_prompt", "u16"),
    0x04: ("wait_dismiss", "u16"),
    0x05: ("dismiss", "u16"),
    0x06: ("dummy", "u16"),
    0x07: ("wait", "u16"),
    0x08: ("choice:2", ""),
    0x09: ("choice:3", ""),
    0x0A: ("a_button", "icon"),
    0x0B: ("b_button", "icon"),
    0x0C: ("c_stick", "icon"),
    0x0D: ("l_button", "icon"),
    0x0E: ("r_button", "icon"),
    0x0F: ("x_button", "icon"),
    0x10: ("y_button", "icon"),
    0x11: ("z_button", "icon"),
    0x12: ("dpad", "icon"),
    0x13: ("main_stick", "icon"),
    0x14: ("arrow_left", "icon"),
    0x15: ("arrow_right", "icon"),
    0x16: ("arrow_up", "icon"),
    0x17: ("arrow_down", "icon"),
    0x18: ("stick_up", "icon"),
    0x19: ("stick_down", "icon"),
    0x1A: ("stick_left", "icon"),
    0x1B: ("stick_right", "icon"),
    0x1C: ("stick_up_down", "icon"),
    0x1D: ("stick_left_right", "icon"),
    0x1E: ("choice_h:left", ""),
    0x1F: ("choice_h:right", ""),
    0x20: ("cannon_balls", "value"),
    0x21: ("broken_vase_payment", "value"),
    0x22: ("auction_character", "value"),
    0x23: ("auction_item", "value"),
    0x24: ("auction_bid", "value"),
    0x25: ("auction_starting_bid", "value"),
    0x26: ("auction_bid_selector", "value"),
    0x27: ("a_button_flashing", "icon"),
    0x28: ("orca_blow_count", "value"),
    0x29: ("pirate_password", "value"),
    0x2A: ("starburst", "icon"),
    0x2B: ("post_game_letter_count", "value"),
    0x2C: ("post_game_rupee_reward", "value"),
    0x2D: ("post_box_letter_count", "value"),
    0x2E: ("remaining_korok_count", "value"),
    0x2F: ("forest_water_time", "value"),
    0x30: ("flight_platform_time", "value"),
    0x31: ("flight_platform_record", "value"),
    0x32: ("beedle_points", "value"),
    0x33: ("marie_pendant_count", "value"),
    0x34: ("marie_pendant_total", "value"),
    0x35: ("pig_game_time", "value"),
    0x36: ("sailing_game_rupee_reward", "value"),
    0x37: ("bomb_capacity", "value"),
    0x38: ("arrow_capacity", "value"),
    0x39: ("heart", "icon"),
    0x3A: ("music_note", "icon"),
    0x3B: ("target_letter_count", "value"),
    0x3C: ("fishman_hit_count", "value"),
    0x3D: ("fishman_rupee_reward", "value"),
    0x3E: ("boko_baba_seed_count", "value"),
    0x3F: ("skull_necklace_count", "value"),
    0x40: ("chu_jelly_count", "value"),
    0x41: ("joy_pendant_count", "value"),
    0x42: ("golden_feather_count", "value"),
    0x43: ("knights_crest_count", "value"),
    0x44: ("beedle_rupee_offer", "value"),
    0x45: ("boko_baba_sell_selector", "value"),
    0x46: ("skull_necklace_sell_selector", "value"),
    0x47: ("chu_jelly_sell_selector", "value"),
    0x48: ("joy_pendant_sell_selector", "value"),
    0x49: ("golden_feather_sell_selector", "value"),
    0x4A: ("knights_crest_sell_selector", "value"),
}

_GROUP_SIMPLE = {1: "sound", 2: "camera", 3: "anim"}


@dataclass
class Message:
    id: int
    text: str  # decoded, escapes rendered as {tag}
    attrs: dict = field(default_factory=dict)
    raw_bytes: bytes = b""  # the NUL-terminated-less string exactly as stored in DAT1
    index: int = 0  # position in INF1


@dataclass
class Bmg:
    encoding: int
    group_id: int
    default_color: int
    entry_size: int
    messages: list[Message]
    message_ids: list[int] | None = None  # MID1, if present

    def by_id(self) -> dict[int, Message]:
        """First message for each id (Wind Waker has a few duplicated ids)."""
        out: dict[int, Message] = {}
        for m in self.messages:
            out.setdefault(m.id, m)
        return out


def is_bmg(data: bytes) -> bool:
    return data[:8] == MAGIC


def _tag(size: int, group: int, code: int, arg: bytes) -> str:
    """Render one escape sequence as a readable {tag}."""
    if group == 0 and code in _CONTROL:
        name, kind = _CONTROL[code]
        if kind == "u16" and len(arg) >= 2:
            return f"{{{name}:{struct.unpack('>H', arg[:2])[0]}}}"
        if kind == "icon":
            return f"{{icon:{name}}}"
        if kind == "value":
            return f"{{value:{name}}}"
        if kind == "" and not arg:
            return f"{{{name}}}"
    elif group in _GROUP_SIMPLE and not arg:
        return f"{{{_GROUP_SIMPLE[group]}:{code}}}"
    elif group == 0xFF:
        if code == 0 and len(arg) == 1:
            return f"{{color:{COLORS.get(arg[0], str(arg[0]))}}}"
        if code == 1 and len(arg) == 2:
            return f"{{size:{struct.unpack('>H', arg)[0]}}}"
        if code == 2 and arg:
            return f"{{ruby:{arg[0]}:{arg[1:].decode('shift_jis', 'replace')}}}"
    return f"{{tag:{group:02X}:{code:04X}:{arg.hex()}}}"


def decode_text(raw: bytes, encoding: str = "shift_jis") -> str:
    """Turn a DAT1 string (without its NUL) into text with {tags} for escape sequences.

    Plain runs are decoded with `encoding` (Shift-JIS is a superset of ASCII, which is
    all the USA text uses). A truncated escape at the end of the string is kept as a
    {tag:..} of whatever bytes remain rather than raising.
    """
    out: list[str] = []
    run = bytearray()
    i, n = 0, len(raw)
    while i < n:
        b = raw[i]
        if b != 0x1A:
            run.append(b)
            i += 1
            continue
        if run:
            out.append(run.decode(encoding, "replace"))
            run.clear()
        size = raw[i + 1] if i + 1 < n else 0
        if size < 5 or i + size > n:
            out.append(f"{{tag:bad:{raw[i:].hex()}}}")
            break
        group = raw[i + 2]
        code = struct.unpack(">H", raw[i + 3 : i + 5])[0]
        out.append(_tag(size, group, code, bytes(raw[i + 5 : i + size])))
        i += size
    if run:
        out.append(run.decode(encoding, "replace"))
    return "".join(out)


def _string_end(pool: bytes, off: int) -> int:
    """Index of the NUL that ends the string at `off`, skipping escape sequences (their
    size/group/code/data bytes are often 0x00 and must not terminate the string)."""
    i, n = off, len(pool)
    while i < n:
        b = pool[i]
        if b == 0:
            return i
        if b == 0x1A and i + 1 < n:
            i += max(pool[i + 1], 1)
        else:
            i += 1
    return n


def _entry_attrs(e: bytes) -> dict:
    """Decode one INF1 entry's attribute bytes (everything after the text offset/id)."""
    if len(e) < 0x18:
        return {"raw": e[4:].hex()}
    (
        price,
        next_id,
        unk_0a,
        box_type,
        draw_type,
        box_pos,
        item_image,
        align,
        sound,
        camera,
        anim,
        unk_14,
        unk_15,
        lines,
        unk_17,
    ) = struct.unpack(">hHHBBBBBBBBBBBB", e[6:0x18])
    attrs = {
        "item_price": price,
        "next_message_id": next_id,
        "unknown_0a": unk_0a,
        "text_box_type": box_type,
        "text_box_type_name": TEXT_BOX_TYPES.get(box_type, f"type_{box_type}"),
        "draw_type": draw_type,
        "draw_type_name": DRAW_TYPES.get(draw_type, f"draw_{draw_type}"),
        "text_box_position": box_pos,
        "text_box_position_name": BOX_POSITIONS.get(box_pos, f"pos_{box_pos}"),
        "item_image": item_image,
        "text_alignment": align,
        "initial_sound": sound,
        "initial_camera": camera,
        "initial_animation": anim,
        "unknown_14": unk_14,
        "unknown_15": unk_15,
        "lines_per_box": lines,
        "unknown_17": unk_17,
    }
    if len(e) > 0x18:
        attrs["extra"] = e[0x18:].hex()
    return attrs


def parse(data: bytes) -> Bmg:
    if data[:8] != MAGIC:
        raise ValueError("not a BMG file (missing MESGbmg1 magic)")
    block_count = struct.unpack(">I", data[0xC:0x10])[0]
    encoding = data[0x10]

    blocks: dict[bytes, bytes] = {}
    off = 0x20
    for _ in range(block_count):
        if off + 8 > len(data):
            break
        tag = data[off : off + 4]
        size = struct.unpack(">I", data[off + 4 : off + 8])[0]
        if size < 8:
            raise ValueError(f"bad block size {size} for {tag!r} at {off:#x}")
        blocks[tag] = data[off + 8 : off + size]
        off += size
    if b"INF1" not in blocks or b"DAT1" not in blocks:
        raise ValueError("BMG lacks INF1/DAT1 blocks")

    inf1 = blocks[b"INF1"]
    count, entry_size, group_id, default_color = struct.unpack(">HHHB", inf1[:7])
    pool = blocks[b"DAT1"]

    messages: list[Message] = []
    for i in range(count):
        e = inf1[8 + i * entry_size : 8 + (i + 1) * entry_size]
        if len(e) < entry_size:
            break
        text_off, msg_id = struct.unpack(">IH", e[:6])
        raw = pool[text_off : _string_end(pool, text_off)]
        messages.append(
            Message(
                id=msg_id,
                text=decode_text(raw),
                attrs=_entry_attrs(e),
                raw_bytes=bytes(raw),
                index=i,
            )
        )

    ids = None
    if b"MID1" in blocks:
        mid = blocks[b"MID1"]
        n = struct.unpack(">H", mid[:2])[0]
        ids = list(struct.unpack(f">{n}I", mid[8 : 8 + 4 * n]))

    return Bmg(
        encoding=encoding,
        group_id=group_id,
        default_color=default_color,
        entry_size=entry_size,
        messages=messages,
        message_ids=ids,
    )
