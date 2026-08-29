"""STB - JStudio cutscene packages (Wind Waker "demo" scenes, e.g. tale.stb).

An .stb is a whole timeline: a list of objects (actors, cameras, lights, fog, sound,
particles, message boxes) each carrying its own little bytecode "sequence" of wait /
paragraph commands, plus one embedded FVB block holding the animation curves that the
paragraphs point at.  The game plays one at 30 fps through JStudio::TControl::forward();
d_demo.cpp's dDemo_manager_c::create() feeds the raw bytes to JStudio::TParse.  Field
names follow the zeldaret/tww decompilation (JSystem/JStudio/*).

All integers are big-endian.  Every offset below was checked against the 54 .stb files
on the NTSC-U disc (res/Object/Demo*.arc "stb/", res/Stage/*/Stage.arc "stb/").

Header (0x20 bytes, JStudio::stb::data::THeader):
  0x00 char[4] "STB\\0"          (ga4cSignature; NOT "JSGF" - that's a different family)
  0x04 u16     byte order, always 0xFEFF
  0x06 u16     version   (2 or 3 on disc; the runtime accepts 1..3)
  0x08 u32     total file size (matches the real file length in every retail file)
  0x0C u32     block count
  0x10 char[8] target name, "jstudio\\0"
  0x18 u16[3]  zero
  0x1E u16     target version (2..3)
  0x20         first block

Block (JStudio::stb::data::TBlock) - `count` of them, back to back, each 4-aligned:
  0x00 u32 size (whole block, so next = here + size)
  0x04 u32 type, a 4CC: JACT actor, JCMR camera, JABL ambient light, JLIT light,
           JFOG fog, JMSG message, JSND sound, JPTC particle, JFVB function values.
           0xFFFFFFFF (BLOCK_NONE) is the control object: a nameless sequence that
           drives the scene itself (its waits set the total length).
  Object blocks (everything except JFVB) continue (TBlock_object):
  0x08 u16 flag        (bit 0x8000 = start disabled; sequence-op 1 mutates it)
  0x0A u16 id_size
  0x0C u8[id_size] id  - the object's name, matched against the running stage by
           JSGFindObject(); Shift-JIS in a few files.  Padded up to 4 bytes.
       then the sequence bytes, running to the end of the block.

Sequence (JStudio::stb::TObject::process_sequence_), u32 words, 4-aligned.  Each word
is `type = w >> 24`, `param = w & 0xFFFFFF`:
  type 0x00  end of sequence
  type 0x01  flag op: (param >> 16) is 1 OR / 2 AND / 3 XOR, (param & 0xFFFF) the operand
  type 0x02  wait `param` frames  <- this is the only timing there is
  type 0x03  jump: next sequence word = this word's address + sign_extend24(param)
  type 0x04  suspend by sign_extend24(param)
  type 0x80  `param` bytes of paragraphs follow the word (all applied on the same frame)
  (types 0x05..0x7F carry no payload, 0x81+ would carry `param` bytes; only 0x00, 0x02
   and 0x80 occur in the 54 retail files.)

Paragraph header - JGadget::binary::parseVariableUInt_16_32_following:
  read u16 a; if (a & 0x8000) == 0:  size = a,  type = u16 at +2, content at +4
              else:                  size = ((a << 16) & 0x7FFF0000) | u16 at +2,
                                     type = u32 at +4, content at +8
  next paragraph = content + round_up(size, 4)   (or content itself when size == 0)

Paragraph type <= 0xFF is reserved (process_paragraph_reserved_):
  1 flag op (u32, same encoding as sequence op 1), 2 wait (u32), 3 jump (s32),
  0x80 data blob, 0x81 data blob prefixed by a TParagraph id, 0x82 no-op.
Paragraph type > 0xFF addresses the object's adaptor:
  feature   = type >> 5     (what to drive - see FEATURES)
  operation = type & 0x1F   (how the payload is encoded - see OPERATIONS)
    1 VOID       no value (stop driving this channel)
    2 IMMEDIATE  f32 per component, held constant
    3 TIME       f32 per component, multiplied by elapsed time
    0x10 FVR_NAME   function-value referenced by name  (never used in TWW)
    0x12 FVR_INDEX  u32 per component: index into the JFVB block's object list
    0x18 name       NUL-terminated string (JSGFindObject / JSGFindNodeID)
    0x19 id         u32 (animation id, shape id, sound id, message code, emitter id)
  A feature that maps to several adaptor "variable values" (…_XYZ, …_RGBA) carries that
  many components back to back, so size = 4 * len(VALUE_INDICES[kind][feature]).

Data blobs (paragraph 0x80/0x81) are the game-specific side channel -
JSGSetData(id, ptr, size).  0x81 prefixes a TParagraph {u16 pad, u16 id_size, u8 id[]}
padded to 4; in TWW id_size is always 4 and the "id" is a raw u32 command number.  The
payload is a chain of typed arrays (TParse_TParagraph_data), each:
  u8 status; if (status & 0x08) u8 count else count = 1; then count * elem values
  elem size = [0,1,2,4,8,16,32,64][status & 7];  status 0 ends the chain.
  status & 0xF0 is the value kind; 0x20 signed / 0x30 unsigned is what the game asserts
  on (TParseData_fixed<33|49|50|51>); 0x40 (float) and 0x50 never occur on disc, so the
  kind nibble beyond signed/unsigned integers is inferred, not verified.

JFVB block: 8-byte TBlock header then a complete FVB file (JStudio::fvb):
  0x00 char[4] "FVB\\0"   0x04 u16 0xFEFF   0x06 u16 version (0x0100 on disc)
  0x08 u32 size           0x0C u32 block count      0x10 first block
  FVB block: u32 size, u16 type, u16 id_size, id (padded to 4), then paragraphs using
  the same variable-uint header.  type 1 composite, 2 constant, 3 transition, 4 list,
  5 list-parameter, 6 hermite.  Paragraphs: 0 end, 1 data, 0x10 refer-by-name,
  0x11 refer-by-index, 0x12 range (2 f32), 0x13 progress, 0x14 adjust, 0x15 outside
  (2 u16: raw/repeat/turn/clamp), 0x16 interpolation (none/linear/plateau/bspline).
  Data payloads: constant f32; transition 2 f32; list {f32 interval, u32 n, f32 v[n]};
  list-parameter {u32 n, f32 pairs[n][2]}; hermite {u32 (n | stride << 28), f32
  points[n][stride]} with stride 3 (time, value, tangent) or 4 (time, value, in, out).
  Every FVB block on the retail disc has id_size 0, so curves are only ever referenced
  by index (operation 0x12).
"""

from __future__ import annotations

import json
import math
import struct
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAGIC = b"STB\0"
FVB_MAGIC = b"FVB\0"
HEADER_SIZE = 0x20
BLOCK_NONE = 0xFFFFFFFF

#: 4CC block type -> the kind of adaptor JStudio builds for it.
BLOCK_KINDS = {
    b"JACT": "actor",
    b"JCMR": "camera",
    b"JABL": "ambient_light",
    b"JLIT": "light",
    b"JFOG": "fog",
    b"JMSG": "message",
    b"JSND": "sound",
    b"JPTC": "particle",
    b"JFVB": "function_values",
}

#: JStudio::data::TEOperationData - how a paragraph payload is encoded.
OPERATIONS = {
    0x01: "void",
    0x02: "immediate",
    0x03: "time",
    0x10: "fvr_name",
    0x11: "fvr_name_output",
    0x12: "fvr_index",
    0x18: "name",
    0x19: "id",
}

#: paragraph type >> 5.  One shared numbering across every object kind; the names come
#: from the JStage setter each feature ends up calling (JStudio_JStage/object-*.cpp).
FEATURES = {
    9: "TRANSLATION_X",
    10: "TRANSLATION_Y",
    11: "TRANSLATION_Z",
    12: "TRANSLATION_XYZ",
    13: "ROTATION_X",
    14: "ROTATION_Y",
    15: "ROTATION_Z",
    16: "ROTATION_XYZ",
    17: "SCALING_X",
    18: "SCALING_Y",
    19: "SCALING_Z",
    20: "SCALING_XYZ",
    21: "POSITION_X",
    22: "POSITION_Y",
    23: "POSITION_Z",
    24: "POSITION_XYZ",
    25: "TARGET_POSITION_X",
    26: "TARGET_POSITION_Y",
    27: "TARGET_POSITION_Z",
    28: "TARGET_POSITION_XYZ",
    29: "COLOR_R",
    30: "COLOR_G",
    31: "COLOR_B",
    32: "COLOR_A",
    33: "COLOR_RGB",
    34: "COLOR_RGBA",
    35: "DIRECTION_THETA",
    36: "DIRECTION_PHI",
    37: "DIRECTION_THETA_PHI",
    38: "VIEW_ROLL",
    39: "PROJECTION_FOVY",
    40: "PROJECTION_NEAR",
    41: "PROJECTION_FAR",
    42: "PROJECTION_NEAR_FAR",
    43: "FOG_START_Z",
    44: "FOG_END_Z",
    45: "FOG_RANGE",
    46: "BEGIN_FADE_IN",
    47: "END_FADE_OUT",
    48: "PARENT",
    49: "PARENT_NODE",
    50: "PARENT_ENABLE",
    51: "RELATION",
    52: "RELATION_NODE",
    53: "RELATION_ENABLE",
    54: "ENABLE",
    55: "FACULTY",
    56: "LOCATED",
    57: "SHAPE",
    58: "ANIMATION",
    59: "ANIMATION_FRAME",
    60: "SOUND",
    61: "SOUND_VOLUME",
    62: "SOUND_PAN",
    63: "SOUND_PITCH",
    64: "SOUND_TEMPO",
    65: "SOUND_FXMIX",
    66: "MESSAGE",
    67: "ANIMATION_MODE",
    68: "PARTICLE",
    69: "COLOR1_R",
    70: "COLOR1_G",
    71: "COLOR1_B",
    72: "COLOR1_A",
    73: "COLOR1_RGB",
    74: "COLOR1_RGBA",
    75: "ANIMATION_TRANSITION",
    76: "TEXTURE_ANIMATION",
    77: "TEXTURE_ANIMATION_FRAME",
    78: "TEXTURE_ANIMATION_MODE",
}

#: kind -> feature -> the adaptor variable-value slots it writes, exactly as the
#: TObject_*::do_paragraph switches in JSystem/JStudio/JStudio/jstudio-object.cpp map
#: them.  len() is the component count of an IMMEDIATE/TIME/FVR_INDEX payload.
VALUE_INDICES: dict[str, dict[int, tuple[int, ...]]] = {
    "actor": {
        9: (3,),
        10: (4,),
        11: (5,),
        12: (3, 4, 5),
        13: (6,),
        14: (7,),
        15: (8,),
        16: (6, 7, 8),
        17: (9,),
        18: (10,),
        19: (11,),
        20: (9, 10, 11),
        50: (12,),
        53: (13,),
        59: (0,),
        75: (1,),
    },
    "camera": {
        21: (0,),
        22: (1,),
        23: (2,),
        24: (0, 1, 2),
        25: (3,),
        26: (4,),
        27: (5,),
        28: (3, 4, 5),
        38: (7,),
        39: (6,),
        40: (8,),
        41: (9,),
        42: (8, 9),
        50: (10,),
    },
    "ambient_light": {29: (0,), 30: (1,), 31: (2,), 32: (3,), 33: (0, 1, 2), 34: (0, 1, 2, 3)},
    "fog": {
        29: (0,),
        30: (1,),
        31: (2,),
        32: (3,),
        33: (0, 1, 2),
        34: (0, 1, 2, 3),
        43: (4,),
        44: (5,),
        45: (4, 5),
    },
    "light": {
        29: (0,),
        30: (1,),
        31: (2,),
        32: (3,),
        33: (0, 1, 2),
        34: (0, 1, 2, 3),
        21: (4,),
        22: (5,),
        23: (6,),
        24: (4, 5, 6),
        25: (7,),
        26: (8,),
        27: (9,),
        28: (7, 8, 9),
        35: (10,),
        36: (11,),
        37: (10, 11),
        54: (12,),
    },
    "sound": {
        21: (0,),
        22: (1,),
        23: (2,),
        24: (0, 1, 2),
        46: (3,),
        47: (4,),
        56: (5,),
        61: (6,),
        62: (7,),
        63: (8,),
        64: (9,),
        65: (10,),
    },
    "particle": {
        9: (0,),
        10: (1,),
        11: (2,),
        12: (0, 1, 2),
        13: (3,),
        14: (4,),
        15: (5,),
        16: (3, 4, 5),
        17: (6,),
        18: (7,),
        19: (8,),
        20: (6, 7, 8),
        29: (9,),
        30: (10,),
        31: (11,),
        32: (12,),
        33: (9, 10, 11),
        34: (9, 10, 11, 12),
        69: (13,),
        70: (14,),
        71: (15,),
        72: (16,),
        73: (9, 10, 11),
        74: (9, 10, 11, 12),
        46: (18,),
        47: (19,),
        50: (17,),
    },
    "message": {},
}

#: kind -> features that call an adaptor_do_* hook instead of (or as well as) writing a
#: variable value.  These are the "commands" of the format.
COMMAND_FEATURES: dict[str, frozenset[int]] = {
    "actor": frozenset({48, 49, 50, 51, 52, 53, 57, 58, 67, 76, 78}),
    "camera": frozenset({48, 49, 50}),
    "ambient_light": frozenset(),
    "fog": frozenset(),
    "light": frozenset({54, 55}),
    "sound": frozenset({56, 60}),
    "particle": frozenset({48, 49, 50, 68}),
    "message": frozenset({66}),
}

#: JStudio::fvb::TFactory::create - FVB block type -> curve kind.
FVB_KINDS = {
    1: "composite",
    2: "constant",
    3: "transition",
    4: "list",
    5: "list_parameter",
    6: "hermite",
}
COMPOSITE_OPS = {
    0: "none",
    1: "raw",
    2: "index",
    3: "parameter",
    4: "add",
    5: "subtract",
    6: "multiply",
    7: "divide",
}
INTERPOLATIONS = {0: "none", 1: "linear", 2: "plateau", 3: "bspline"}
OUTSIDES = {0: "raw", 1: "repeat", 2: "turn", 3: "clamp"}
PROGRESSES = {0: "forward", 1: "reverse", 2: "reverse_begin", 3: "reverse_end", 4: "reverse_center"}
ADJUSTS = {0: "none", 1: "begin", 2: "end", 3: "center", 4: "range"}

#: gauDataSize_TEParagraph_data - status low 3 bits -> element size.
DATA_ELEM_SIZES = (0, 1, 2, 4, 8, 16, 32, 64)


def _align4(n: int) -> int:
    return (n + 3) & ~3


def _cstr(buf: bytes) -> str:
    return buf.split(b"\0", 1)[0].decode("shift_jis", "replace")


def _var_uint(data: bytes, off: int) -> tuple[int, int, int]:
    """parseVariableUInt_16_32_following -> (size, type, offset of the content)."""
    first = struct.unpack_from(">H", data, off)[0]
    if not first & 0x8000:
        return first, struct.unpack_from(">H", data, off + 2)[0], off + 4
    size = ((first << 16) & 0x7FFF0000) | struct.unpack_from(">H", data, off + 2)[0]
    return size, struct.unpack_from(">I", data, off + 4)[0], off + 8


def _s24(v: int) -> int:
    return v - 0x1000000 if v & 0x800000 else v


# --------------------------------------------------------------------------- data blobs


@dataclass
class DataRecord:
    """One typed array inside a 0x80/0x81 data blob."""

    status: int
    elem_size: int
    count: int
    raw: bytes

    @property
    def signed(self) -> bool:
        return self.status & 0xF0 == 0x20

    @property
    def values(self) -> list[int]:
        code = {1: "b", 2: "h", 4: "i", 8: "q"}.get(self.elem_size)
        if code is None:
            return []
        if not self.signed:
            code = code.upper()
        return list(struct.unpack(f">{self.count}{code}", self.raw))


def parse_data_records(blob: bytes) -> list[DataRecord]:
    """Walk a data-blob payload (TParse_TParagraph_data chain) until the 0 status."""
    out: list[DataRecord] = []
    p = 0
    while p < len(blob):
        status = blob[p]
        if status == 0:
            break
        p += 1
        count = 1
        if status & 0x08:
            count = blob[p]
            p += 1
        size = DATA_ELEM_SIZES[status & 7]
        out.append(DataRecord(status & ~0x08, size, count, blob[p : p + size * count]))
        if size == 0:
            break
        p += size * count
    return out


# ------------------------------------------------------------------------- object model


@dataclass
class Paragraph:
    """One instruction applied to an object on one frame."""

    offset: int
    type: int
    size: int
    raw: bytes
    feature: int = 0
    operation: int = 0
    name: str = ""
    op_name: str = ""
    value: Any = None
    data_id: int | None = None
    records: list[DataRecord] = field(default_factory=list)

    @property
    def reserved(self) -> bool:
        return self.type <= 0xFF


@dataclass
class Command:
    """One sequence word plus, for type 0x80, the paragraphs it carries."""

    offset: int
    frame: int
    type: int
    kind: str
    param: int
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Key:
    """A flattened (frame, how, what) entry of one feature of one object."""

    frame: int
    op_name: str
    value: Any


@dataclass
class Track:
    """Every key written to one feature of one object, in time order."""

    feature: int
    name: str
    value_indices: tuple[int, ...]
    keys: list[Key] = field(default_factory=list)


@dataclass
class Object:
    """One JACT/JCMR/... block: a named target plus its timeline."""

    block_type: str
    kind: str
    flag: int
    id: str
    id_raw: bytes
    offset: int
    size: int
    commands: list[Command] = field(default_factory=list)
    frames: int = 0

    @property
    def enabled(self) -> bool:
        """flag bit 0x8000 makes the runtime skip the object entirely."""
        return not self.flag & 0x8000

    @property
    def tracks(self) -> list[Track]:
        """Paragraphs regrouped per feature, which is what a player wants to sample."""
        by_feature: dict[int, Track] = {}
        for cmd in self.commands:
            for para in cmd.paragraphs:
                if para.reserved:
                    continue
                trk = by_feature.get(para.feature)
                if trk is None:
                    idx = VALUE_INDICES.get(self.kind, {}).get(para.feature, ())
                    trk = by_feature[para.feature] = Track(para.feature, para.name, idx)
                trk.keys.append(Key(cmd.frame, para.op_name, para.value))
        return [by_feature[k] for k in sorted(by_feature)]

    @property
    def data_events(self) -> list[tuple[int, int | None, list[DataRecord]]]:
        """(frame, data id, records) for every 0x80/0x81 paragraph (JSGSetData)."""
        out = []
        for cmd in self.commands:
            for para in cmd.paragraphs:
                if para.type in (0x80, 0x81):
                    out.append((cmd.frame, para.data_id, para.records))
        return out


@dataclass
class Function:
    """One FVB curve.  Objects reference these by their index in this list."""

    index: int
    type: int
    kind: str
    id: str
    offset: int
    range: tuple[float, float] | None = None
    progress: int = 0
    adjust: int = 0
    outside: tuple[int, int] = (0, 0)
    interpolation: int = 0
    refer_names: list[str] = field(default_factory=list)
    refer_indices: list[int] = field(default_factory=list)
    constant: float | None = None
    transition: tuple[float, float] | None = None
    interval: float | None = None
    values: list[float] = field(default_factory=list)
    points: list[tuple[float, ...]] = field(default_factory=list)
    stride: int = 0
    composite_op: str = ""
    composite_operand: Any = None

    def value_at(self, t: float) -> float:
        """Sample the curve at time t (seconds), following JStudio's getValue()."""
        return _sample(self, t)


@dataclass
class Block:
    """Raw block table entry, kept so callers can see the file's real layout."""

    offset: int
    size: int
    type: int
    type_name: str


@dataclass
class Stb:
    """A parsed cutscene package."""

    version: int
    target: str
    target_version: int
    size: int
    blocks: list[Block] = field(default_factory=list)
    objects: list[Object] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    control: Object | None = None

    @property
    def frames(self) -> int:
        """Scene length in frames (30 fps); the control object is the authority."""
        lengths = [o.frames for o in self.objects]
        if self.control is not None:
            lengths.append(self.control.frames)
        return max(lengths, default=0)

    @property
    def seconds(self) -> float:
        return self.frames / 30.0


# ------------------------------------------------------------------------------ parsing


def _parse_paragraph(data: bytes, off: int, kind: str) -> tuple[Paragraph, int]:
    size, ptype, content = _var_uint(data, off)
    raw = data[content : content + size]
    para = Paragraph(offset=off, type=ptype, size=size, raw=raw)
    nxt = content + _align4(size) if size else content

    if ptype <= 0xFF:
        if ptype == 1 and size >= 4:
            v = struct.unpack_from(">I", raw, 0)[0]
            para.name, para.value = "FLAG", (v >> 16, v & 0xFFFF)
        elif ptype == 2 and size >= 4:
            para.name, para.value = "WAIT", struct.unpack_from(">I", raw, 0)[0]
        elif ptype == 3 and size >= 4:
            para.name, para.value = "JUMP", struct.unpack_from(">i", raw, 0)[0]
        elif ptype in (0x80, 0x81):
            para.name = "DATA"
            body = raw
            if ptype == 0x81 and size >= 4:
                id_size = struct.unpack_from(">H", raw, 2)[0]
                para.data_id = int.from_bytes(raw[4 : 4 + id_size], "big") if id_size else None
                body = raw[4 + _align4(id_size) :]
            para.records = parse_data_records(body)
        elif ptype == 0x82:
            para.name = "NOP"
        return para, nxt

    para.feature = ptype >> 5
    para.operation = ptype & 0x1F
    para.name = FEATURES.get(para.feature, f"FEATURE_{para.feature}")
    para.op_name = OPERATIONS.get(para.operation, f"op_{para.operation:#x}")
    n = len(VALUE_INDICES.get(kind, {}).get(para.feature, ())) or 1

    if para.operation in (0x02, 0x03) and size >= 4:
        vals = list(struct.unpack(f">{size // 4}f", raw[: size // 4 * 4]))
        para.value = vals[0] if len(vals) == 1 else vals
    elif para.operation == 0x12 and size >= 4:
        vals = list(struct.unpack(f">{size // 4}I", raw[: size // 4 * 4]))
        para.value = vals[0] if len(vals) == 1 else vals
    elif para.operation == 0x19 and size >= 4:
        para.value = struct.unpack_from(">I", raw, 0)[0]
    elif para.operation in (0x10, 0x11, 0x18):
        para.value = _cstr(raw)
    elif para.operation == 0x01:
        para.value = None
    else:
        para.value = raw
    if para.operation in (0x02, 0x03, 0x12) and n > 1 and not isinstance(para.value, list):
        para.value = [para.value]
    return para, nxt


def _parse_sequence(data: bytes, start: int, end: int, kind: str) -> tuple[list[Command], int]:
    cmds: list[Command] = []
    frame = 0
    p = start
    seen: set[int] = set()
    while p + 4 <= end:
        if p in seen:  # a backwards jump would loop forever; record and stop
            break
        seen.add(p)
        word = struct.unpack_from(">I", data, p)[0]
        ctype, param = word >> 24, word & 0xFFFFFF
        if ctype == 0:
            cmds.append(Command(p, frame, ctype, "end", 0))
            break
        if ctype == 0x01:
            cmds.append(Command(p, frame, ctype, "flag", param))
            p += 4
        elif ctype == 0x02:
            cmds.append(Command(p, frame, ctype, "wait", param))
            frame += param
            p += 4
        elif ctype == 0x03:
            cmds.append(Command(p, frame, ctype, "jump", _s24(param)))
            target = p + _s24(param)
            if not start <= target < end:
                break
            p = target
        elif ctype == 0x04:
            cmds.append(Command(p, frame, ctype, "suspend", _s24(param)))
            p += 4
        elif ctype < 0x80:
            cmds.append(Command(p, frame, ctype, f"unknown_{ctype:#x}", param))
            p += 4
        else:
            cmd = Command(p, frame, ctype, "paragraph", param)
            stop = min(p + 4 + param, end)
            q = p + 4
            while q < stop:
                para, q = _parse_paragraph(data, q, kind)
                cmd.paragraphs.append(para)
                if para.type == 2 and isinstance(para.value, int):
                    frame += para.value
            cmds.append(cmd)
            p = p + 4 + param
    return cmds, frame


def _parse_fvb(data: bytes, base: int) -> list[Function]:
    sig = data[base : base + 4]
    if sig != FVB_MAGIC:
        raise ValueError(f"JFVB block at {base:#x}: bad signature {sig!r}")
    if struct.unpack_from(">H", data, base + 4)[0] != 0xFEFF:
        raise ValueError(f"JFVB block at {base:#x}: bad byte order")
    count = struct.unpack_from(">I", data, base + 0x0C)[0]
    out: list[Function] = []
    p = base + 0x10
    for i in range(count):
        size, ftype, id_size = struct.unpack_from(">IHH", data, p)
        if size < 8:
            raise ValueError(f"FVB block {i} at {p:#x}: size {size}")
        fn = Function(
            index=i,
            type=ftype,
            kind=FVB_KINDS.get(ftype, f"type_{ftype}"),
            id=_cstr(data[p + 8 : p + 8 + id_size]) if id_size else "",
            offset=p,
        )
        end = p + size
        q = p + 8 + _align4(id_size)
        while q < end:
            psize, ptype, content = _var_uint(data, q)
            raw = data[content : content + psize]
            if ptype == 0:
                break
            _fvb_paragraph(fn, ptype, raw)
            q = content + _align4(psize) if psize else content
        out.append(fn)
        p = end
    return out


def _fvb_paragraph(fn: Function, ptype: int, raw: bytes) -> None:
    if ptype == 1:
        _fvb_data(fn, raw)
    elif ptype == 0x10 and len(raw) >= 4:
        n = struct.unpack_from(">I", raw, 0)[0]
        off = 4
        for _ in range(n):
            ln = struct.unpack_from(">I", raw, off)[0]
            fn.refer_names.append(_cstr(raw[off + 4 : off + 4 + ln]))
            off += 4 + _align4(ln)
    elif ptype == 0x11 and len(raw) >= 4:
        n = struct.unpack_from(">I", raw, 0)[0]
        fn.refer_indices = list(struct.unpack_from(f">{n}I", raw, 4))
    elif ptype == 0x12 and len(raw) >= 8:
        fn.range = struct.unpack_from(">2f", raw, 0)
    elif ptype == 0x13 and len(raw) >= 4:
        fn.progress = struct.unpack_from(">I", raw, 0)[0]
    elif ptype == 0x14 and len(raw) >= 4:
        fn.adjust = struct.unpack_from(">I", raw, 0)[0]
    elif ptype == 0x15 and len(raw) >= 4:
        fn.outside = struct.unpack_from(">2H", raw, 0)
    elif ptype == 0x16 and len(raw) >= 4:
        fn.interpolation = struct.unpack_from(">I", raw, 0)[0]


def _fvb_data(fn: Function, raw: bytes) -> None:
    if fn.kind == "constant" and len(raw) >= 4:
        fn.constant = struct.unpack_from(">f", raw, 0)[0]
    elif fn.kind == "transition" and len(raw) >= 8:
        fn.transition = struct.unpack_from(">2f", raw, 0)
    elif fn.kind == "list" and len(raw) >= 8:
        fn.interval = struct.unpack_from(">f", raw, 0)[0]
        n = struct.unpack_from(">I", raw, 4)[0]
        fn.values = list(struct.unpack_from(f">{n}f", raw, 8))
    elif fn.kind == "list_parameter" and len(raw) >= 4:
        n = struct.unpack_from(">I", raw, 0)[0]
        flat = struct.unpack_from(f">{n * 2}f", raw, 4)
        fn.stride = 2
        fn.points = [tuple(flat[i * 2 : i * 2 + 2]) for i in range(n)]
    elif fn.kind == "hermite" and len(raw) >= 4:
        packed = struct.unpack_from(">I", raw, 0)[0]
        n, stride = packed & 0x0FFFFFFF, packed >> 28
        fn.stride = stride
        flat = struct.unpack_from(f">{n * stride}f", raw, 4)
        fn.points = [tuple(flat[i * stride : (i + 1) * stride]) for i in range(n)]
    elif fn.kind == "composite" and len(raw) >= 8:
        op = struct.unpack_from(">I", raw, 0)[0]
        fn.composite_op = COMPOSITE_OPS.get(op, f"op_{op}")
        if fn.composite_op in ("raw", "index"):
            fn.composite_operand = struct.unpack_from(">I", raw, 4)[0]
        else:
            fn.composite_operand = struct.unpack_from(">f", raw, 4)[0]


def parse(data: bytes) -> Stb:
    """Parse an .stb cutscene package."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"stb: file too small ({len(data)} bytes)")
    if data[:4] != MAGIC:
        raise ValueError(f"stb: bad signature {data[:4]!r} (expected {MAGIC!r})")
    order, version, size, count = struct.unpack_from(">HHII", data, 4)
    if order != 0xFEFF:
        raise ValueError(f"stb: byte order {order:#06x} (expected 0xFEFF)")
    if not 1 <= version <= 3:
        raise ValueError(f"stb: unsupported version {version}")
    stb = Stb(
        version=version,
        target=_cstr(data[0x10:0x18]),
        target_version=struct.unpack_from(">H", data, 0x1E)[0],
        size=size,
    )

    p = HEADER_SIZE
    for i in range(count):
        if p + 8 > len(data):
            raise ValueError(f"stb: block {i} starts past the end of the file")
        bsize, btype = struct.unpack_from(">II", data, p)
        if bsize < 8 or p + bsize > len(data):
            raise ValueError(f"stb: block {i} at {p:#x} has bad size {bsize}")
        fourcc = struct.pack(">I", btype)
        name = "NONE" if btype == BLOCK_NONE else fourcc.decode("ascii", "replace")
        stb.blocks.append(Block(p, bsize, btype, name))

        if fourcc == b"JFVB":
            stb.functions.extend(_parse_fvb(data, p + 8))
        elif btype == BLOCK_NONE:
            cmds, frames = _parse_sequence(data, p + 8, p + bsize, "control")
            stb.control = Object("NONE", "control", 0, "", b"", p, bsize, cmds, frames)
        else:
            flag, id_size = struct.unpack_from(">HH", data, p + 8)
            id_raw = data[p + 12 : p + 12 + id_size]
            start = p + 12 + _align4(id_size)
            kind = BLOCK_KINDS.get(fourcc, "unknown")
            cmds, frames = _parse_sequence(data, start, p + bsize, kind)
            stb.objects.append(
                Object(name, kind, flag, _cstr(id_raw), id_raw, p, bsize, cmds, frames)
            )
        p += bsize
    return stb


# --------------------------------------------------------------------- curve evaluation


def _extrapolate(mode: int, value: float, span: float) -> float:
    if mode == 1:  # repeat
        t = math.fmod(value, span) if span else 0.0
        return t + span if t < 0.0 else t
    if mode == 2:  # turn
        two = 2.0 * span
        t = math.fmod(value, two) if two else 0.0
        if t < 0.0:
            t += two
        return two - t if t >= span else t
    if mode == 3:  # clamp
        return 0.0 if value <= 0.0 else min(value, span)
    return value  # raw


def _range_param(fn: Function, t: float) -> float:
    """range_getParameter with progress/adjust applied (adjust 4 needs the data range)."""
    if fn.range is None:
        return t
    begin, end = fn.range
    origin, scale = {
        1: (0.0, -1.0),
        2: (begin, -1.0),
        3: (end, -1.0),
        4: (0.5 * (begin + end), -1.0),
    }.get(fn.progress, (0.0, 1.0))
    t = origin + scale * (t - origin)
    t += {1: begin, 2: end, 3: 0.5 * (begin + end)}.get(fn.adjust, 0.0)
    span = end - begin
    off = t - begin
    if off < 0.0:
        off = _extrapolate(fn.outside[0], off, span)
    elif off >= span:
        off = _extrapolate(fn.outside[1], off, span)
    return off + begin


def _hermite(t: float, t0: float, v0: float, m0: float, t1: float, v1: float, m1: float) -> float:
    a = t - t0
    dt = t1 - t0
    b = a / dt if dt else 0.0
    c = b - 1.0
    d = (3.0 - 2.0 * b) * b * b
    return (1.0 - d) * v0 + d * v1 + c * c * a * m0 + c * a * b * m1


def _bspline_uniform(u: float, p0: float, p1: float, p2: float, p3: float) -> float:
    iu = 1.0 - u
    c0 = iu * iu * iu
    c3 = u * u * u
    b1 = 0.5 * c3 - u * u + 2.0 / 3.0
    b2 = 0.5 * (u + u * u - c3) + 1.0 / 6.0
    return (c0 * p0 + c3 * p3) / 6.0 + b1 * p1 + b2 * p2


def _sample(fn: Function, t: float) -> float:
    """JStudio getValue() for every curve kind except `composite`, which needs the
    curves it refers to and is therefore reported but not evaluated (returns nan)."""
    if fn.kind == "constant":
        return float(fn.constant or 0.0)
    if fn.kind == "transition":
        if fn.transition is None:
            return math.nan
        a, b = fn.transition
        p = _range_param(fn, t)
        begin, end = fn.range or (0.0, 0.0)
        pivot = {2: end, 3: 0.5 * (begin + end)}.get(fn.adjust, begin)
        return float(a if p < pivot else b)
    if fn.kind == "list":
        if not fn.values or not fn.interval:
            return math.nan
        last = len(fn.values) - 1
        idx = _range_param(fn, t) / fn.interval
        if idx < 0.0:
            return float(fn.values[0])
        if idx >= last:
            return float(fn.values[last])
        i = int(math.floor(idx))
        u = idx - i
        if fn.interpolation == 0:
            return float(fn.values[i])
        if fn.interpolation == 3 and len(fn.values) >= 3:
            v0 = 2.0 * fn.values[i] - fn.values[i + 1] if i == 0 else fn.values[i - 1]
            v3 = 2.0 * fn.values[i + 1] - fn.values[i] if i == last - 1 else fn.values[i + 2]
            return _bspline_uniform(u, v0, fn.values[i], fn.values[i + 1], v3)
        if fn.interpolation == 2:
            return _hermite(idx, i, fn.values[i], 0.0, i + 1.0, fn.values[i + 1], 0.0)
        return float(fn.values[i] + (fn.values[i + 1] - fn.values[i]) * u)
    if fn.kind in ("list_parameter", "hermite"):
        pts = fn.points
        if not pts:
            return math.nan
        p = _range_param(fn, t)
        times = [q[0] for q in pts]
        i = bisect_right(times, p)
        if i == 0:
            return float(pts[0][1])
        if i >= len(pts):
            return float(pts[-1][1])
        a, b = pts[i - 1], pts[i]
        if fn.kind == "hermite":
            return _hermite(p, a[0], a[1], a[fn.stride - 1], b[0], b[1], b[2])
        if fn.interpolation == 0:
            return float(a[1])
        if fn.interpolation == 2:
            return _hermite(p, a[0], a[1], 0.0, b[0], b[1], 0.0)
        span = b[0] - a[0]
        u = (p - a[0]) / span if span else 0.0
        if fn.interpolation == 3 and len(pts) >= 3:
            # uniform approximation: the game uses a non-uniform knot vector here
            v0 = 2.0 * a[1] - b[1] if i == 1 else pts[i - 2][1]
            v3 = 2.0 * b[1] - a[1] if i == len(pts) - 1 else pts[i + 1][1]
            return _bspline_uniform(u, v0, a[1], b[1], v3)
        return float(a[1] + (b[1] - a[1]) * u)
    return math.nan


# ------------------------------------------------------------------------- json / dumps


def _json_value(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, tuple):
        return list(v)
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _function_dict(fn: Function) -> dict[str, Any]:
    out: dict[str, Any] = {
        "index": fn.index,
        "kind": fn.kind,
        "interpolation": INTERPOLATIONS.get(fn.interpolation, fn.interpolation),
        "outside": [OUTSIDES.get(o, o) for o in fn.outside],
    }
    if fn.id:
        out["id"] = fn.id
    if fn.range is not None:
        out["range"] = list(fn.range)
    if fn.progress:
        out["progress"] = PROGRESSES.get(fn.progress, fn.progress)
    if fn.adjust:
        out["adjust"] = ADJUSTS.get(fn.adjust, fn.adjust)
    if fn.refer_names:
        out["refer_names"] = fn.refer_names
    if fn.refer_indices:
        out["refer_indices"] = fn.refer_indices
    if fn.constant is not None:
        out["value"] = fn.constant
    if fn.transition is not None:
        out["transition"] = list(fn.transition)
    if fn.interval is not None:
        out["interval"] = fn.interval
        out["values"] = fn.values
    if fn.points:
        out["stride"] = fn.stride
        out["points"] = [list(p) for p in fn.points]
    if fn.composite_op:
        out["composite"] = {"op": fn.composite_op, "operand": fn.composite_operand}
    return out


def _object_dict(obj: Object) -> dict[str, Any]:
    return {
        "id": obj.id,
        "block": obj.block_type,
        "kind": obj.kind,
        "flag": obj.flag,
        "enabled": obj.enabled,
        "frames": obj.frames,
        "tracks": [
            {
                "feature": t.feature,
                "name": t.name,
                "value_indices": list(t.value_indices),
                "keys": [
                    {"frame": k.frame, "op": k.op_name, "value": _json_value(k.value)}
                    for k in t.keys
                ],
            }
            for t in obj.tracks
        ],
        "data": [
            {
                "frame": frame,
                "id": data_id,
                "records": [
                    {
                        "status": hex(r.status),
                        "elem_size": r.elem_size,
                        "count": r.count,
                        "values": r.values,
                        "raw": r.raw.hex(),
                    }
                    for r in recs
                ],
            }
            for frame, data_id, recs in obj.data_events
        ],
    }


def to_dict(stb: Stb) -> dict[str, Any]:
    """JSON-ready view: header, objects with per-feature tracks, and the FVB curves."""
    out: dict[str, Any] = {
        "version": stb.version,
        "target": stb.target,
        "target_version": stb.target_version,
        "size": stb.size,
        "frames": stb.frames,
        "seconds": round(stb.seconds, 4),
        "blocks": [{"offset": b.offset, "size": b.size, "type": b.type_name} for b in stb.blocks],
        "objects": [_object_dict(o) for o in stb.objects],
        "functions": [_function_dict(f) for f in stb.functions],
    }
    if stb.control is not None:
        out["control"] = _object_dict(stb.control)
    return out


def dump_json(data: bytes, out_path: str | Path) -> Stb:
    """Parse .stb bytes and write them as JSON to out_path."""
    stb = parse(data)
    Path(out_path).write_text(json.dumps(to_dict(stb), indent=1, ensure_ascii=False), "utf-8")
    return stb


def summary(stb: Stb) -> str:
    """One line per object: id, kind, frame span and the features it drives."""
    lines = [
        f"STB v{stb.version} target {stb.target} v{stb.target_version}: "
        f"{len(stb.objects)} objects, {len(stb.functions)} curves, "
        f"{stb.frames} frames ({stb.seconds:.2f}s)"
    ]
    for obj in stb.objects:
        feats = ", ".join(t.name for t in obj.tracks)
        flag = "" if obj.enabled else " [disabled]"
        lines.append(f"  {obj.id or '(unnamed)'} [{obj.kind}]{flag} {obj.frames}f: {feats}")
    return "\n".join(lines)
