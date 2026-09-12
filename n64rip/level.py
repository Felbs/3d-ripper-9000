"""Levels: scenes, their rooms, and everything a room needs to be a place.

A level in Ocarina of Time is a **scene** file plus one or more **room** files.  The scene
holds what is shared - the collision mesh, the lighting, the spawn points, the doors between
rooms, the shared textures and palettes - and each room holds its own geometry and the actors
that stand in it.  Both are a flat list of 8-byte header commands terminated by ``0x14``, and
both are found from ``gSceneTable`` in ``code``, which is located structurally the way
``objects.find_object_table`` is: the only long run of records whose first two words are a
real DMA ``{vromStart, vromEnd}`` pair.

Three facts carry the reassembly, each checked against the whole game rather than assumed:

* **Rooms are already in the scene's world space.**  768 of 778 door placements from the
  *scene* file lie inside the *room* geometry they name; 330 of 334 door-joined room pairs touch
  or overlap, 128 of them on a boundary plane exact to the unit; and the scene's collision
  box matches the decoded room extent on five of six bounds for the first scene and on all six
  for 53 of 100.  So a level is concatenation plus placement - no per-room transform exists.
* **Segment 2 is the scene and segment 3 is the room.**  Proven from the loader's own stores
  into ``gSegments``.  Triangle counts are the same either way, which is exactly why a
  count-only check misses it: 8,940 of 9,504 palette references live on segment 2, so without
  the scene bound nearly every colour-index texture in every room is unpalettable.
* **Alternate headers (command ``0x18``) never change geometry.**  0 of 134 scene and 0 of 251
  room alternates name a different room list or mesh header.  They vary actors, objects,
  lighting and time, and are walked for those only.

What is deliberately NOT here: a route through segments 8-0x0D.  356 ``G_DL`` calls point
into them and every one is a tile-state list the frame builds at draw time; the bytes exist
nowhere on the cartridge and skipping them costs exactly 0 triangles.
"""

from __future__ import annotations

import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from n64rip import collision as col_mod
from n64rip import f3dex2
from n64rip import objects as obj_mod
from n64rip import zobj
from ripcore.scene import Empty, MaterialDef, Primitive, Scene

CMD_END = 0x14
CMD_SPAWNS = 0x00
CMD_ACTORS = 0x01
CMD_COLLISION = 0x03
CMD_ROOMS = 0x04
CMD_WIND = 0x05
CMD_ENTRANCES = 0x06
CMD_KEEP = 0x07
CMD_BEHAVIOUR = 0x08
CMD_MESH = 0x0A
CMD_OBJECTS = 0x0B
CMD_PATHS = 0x0D
CMD_DOORS = 0x0E
CMD_LIGHTS = 0x0F
CMD_TIME = 0x10
CMD_SKYBOX = 0x11
CMD_EXITS = 0x13
CMD_SOUND = 0x15
CMD_ECHO = 0x16
CMD_ALTERNATES = 0x18
MAX_COMMANDS = 64          # the longest real header is 10 commands
SCENE_SEGMENT = 2
ROOM_SEGMENT = 3
SCENE_ENTRY = 0x14          # Ocarina; Majora's Mask uses 0x10 with no config tail
MIN_SCENE_RUN = 24
ACTOR_ENTRY = 16
LIGHT_ENTRY = 22
DOOR_ENTRY = 16
BINANG = 2.0 * np.pi / 65536.0


# -- the header language ------------------------------------------------------------------


@dataclass(frozen=True)
class Cmd:
    op: int
    w0: int
    w1: int

    @property
    def count(self) -> int:
        return (self.w0 >> 16) & 0xFF

    @property
    def offset(self) -> int:
        return self.w1 & 0x00FFFFFF

    @property
    def segment(self) -> int:
        return self.w1 >> 24


def commands(data: bytes, offset: int = 0) -> list[Cmd]:
    """The header at *offset*: 8-byte commands up to and excluding the ``0x14`` terminator.

    The game's executor tests for ``0x14`` before dispatching and silently skips any opcode
    at or above ``0x1A``; both are reproduced.  Raises ``ValueError`` if no terminator
    arrives within :data:`MAX_COMMANDS`, which is what a non-header looks like.
    """
    out: list[Cmd] = []
    for k in range(MAX_COMMANDS):
        off = offset + k * 8
        if off + 8 > len(data):
            raise ValueError("header runs past the file")
        w0, w1 = struct.unpack_from(">II", data, off)
        op = w0 >> 24
        if op == CMD_END:
            return out
        if op >= 0x1A:
            continue
        out.append(Cmd(op, w0, w1))
    raise ValueError("no header terminator")


def by_op(cmds: list[Cmd]) -> dict[int, Cmd]:
    """First command per opcode - every mandatory opcode occurs exactly once in this game."""
    out: dict[int, Cmd] = {}
    for c in cmds:
        out.setdefault(c.op, c)
    return out


def is_header(data: bytes, offset: int, segment: int) -> bool:
    """Does a header start here whose pointer commands all name *segment*?"""
    try:
        cmds = commands(data, offset)
    except ValueError:
        return False
    if not cmds:
        return False
    for c in cmds:
        if c.op in (CMD_SPAWNS, CMD_ACTORS, CMD_COLLISION, CMD_ROOMS, CMD_ENTRANCES, CMD_MESH,
                    CMD_OBJECTS, CMD_PATHS, CMD_DOORS, CMD_LIGHTS, CMD_EXITS):
            if c.segment != segment or c.offset >= len(data):
                return False
    return True


def alternate_headers(data: bytes, cmds: list[Cmd], segment: int) -> list[int]:
    """Offsets of the alternate setups behind command ``0x18``, in slot order.

    The array is NULL-sparse and its length is stored nowhere: for 27 of the 32 scenes that
    carry it, slots 0-2 are zero and the first real pointer is slot 3.  A walk that stops at
    the first word that is not a pointer sees *zero* alternates for those scenes and reports
    "no differences" from an empty loop.  This walk skips NULL slots, stops only on a word
    that is neither NULL nor a header, and trims trailing NULLs.  Slots and headers are not
    the same count - file 1349 declares 13 slots and yields 10 headers.
    """
    alt = by_op(cmds).get(CMD_ALTERNATES)
    if alt is None or alt.segment != segment:
        return []
    out: list[int] = []
    off = alt.offset
    while off + 4 <= len(data):
        w = struct.unpack_from(">I", data, off)[0]
        off += 4
        if w == 0:
            continue
        if w >> 24 != segment or not is_header(data, w & 0xFFFFFF, segment):
            break
        out.append(w & 0xFFFFFF)
    return out


# -- the tables in code -------------------------------------------------------------------


@dataclass(frozen=True)
class SceneEntry:
    index: int
    scene_file: int
    title_file: int | None
    draw_config: int
    unk0: int
    unk2: int


def find_scene_table(rom, code: bytes, stride: int = SCENE_ENTRY) -> tuple[int, list[SceneEntry]]:
    """``(offset in code, entries)`` for ``gSceneTable``, found by structure.

    A record is ``{scene vrom pair, title vrom pair, u8 unk, u8 drawConfig, u8 unk, u8 zero}``
    at *stride* 0x14; the scene pair must be a live DMA file and the title pair either a live
    file or ``{0, 0}``.  The longest such run is the table - 101 records on Ocarina, ending
    exactly where ``gSceneDrawConfigs`` begins.  Never by constant: Master Quest moves every
    ``code`` offset by 0x20, and Majora's Mask changes the stride.
    """
    pairs = {(f.vrom_start, f.vrom_end): f.index for f in rom.files if f.vrom_end > f.vrom_start}

    def record(off: int) -> SceneEntry | None:
        if off + stride > len(code):
            return None
        vs, ve, ts, te = struct.unpack_from(">4I", code, off)
        sf = pairs.get((vs, ve))
        if sf is None:
            return None
        if (ts, te) == (0, 0):
            tf = None
        else:
            tf = pairs.get((ts, te))
            if tf is None:
                return None
        if stride >= SCENE_ENTRY:
            u0, cfg, u2, z = struct.unpack_from(">4B", code, off + 16)
            if z != 0:
                return None
        else:
            u0 = cfg = u2 = 0
        return SceneEntry(0, sf, tf, cfg, u0, u2)

    best_off, best = -1, []
    off = 0
    n = len(code)
    while off + stride <= n:
        r = record(off)
        if r is None:
            off += 4
            continue
        run: list[SceneEntry] = []
        k = off
        while (r := record(k)) is not None:
            run.append(r)
            k += stride
        if len(run) > len(best):
            best_off, best = off, run
        off = k + 4
    if len(best) < MIN_SCENE_RUN:
        return -1, []
    return best_off, [SceneEntry(i, e.scene_file, e.title_file, e.draw_config, e.unk0, e.unk2)
                      for i, e in enumerate(best)]


def find_entrance_table(code: bytes, scene_table_offset: int,
                        floor: int = 0) -> tuple[int, int]:
    """``(offset, record count)`` for ``gEntranceTable``: 4-byte ``{s8 scene, s8 spawn, u16}``
    records running unbroken up to ``gSceneTable``.

    Walked *backwards* from the scene table until a record stops looking like one (scene
    above 110 or spawn above 18), which lands on the last word of ``gObjectTable``.  1,556
    records on Ocarina.  It is a FLAT array indexed by entrance id - not groups of four: the
    game stores ids 0x53, 0x517 and 0x11E as immediates, and an entrance occupies its record
    plus the next three, so consecutive entrances overlap.
    """
    off = scene_table_offset
    while off - 4 >= floor:
        s, sp = struct.unpack_from(">bb", code, off - 4)
        if not (0 <= s <= 110 and 0 <= sp <= 18):
            break
        off -= 4
    # Eight zero bytes of alignment padding sit between gObjectTable's end and the first
    # record, and a zero record passes the test above (scene 0, spawn 0).  The real entrance
    # 0 is ``00 00 41 02``; the padding words are entirely zero and are trimmed.
    while off + 4 <= scene_table_offset and code[off:off + 4] == bytes(4):
        off += 4
    return off, (scene_table_offset - off) // 4


def entrance(code: bytes, table_offset: int, count: int, index: int) -> tuple[int, int] | None:
    if not 0 <= index < count:
        return None
    return struct.unpack_from(">bb", code, table_offset + index * 4)


# -- the pieces of a scene ----------------------------------------------------------------


@dataclass
class ActorEntry:
    id: int
    pos: tuple[int, int, int]
    rot: tuple[int, int, int]   # binary angles, 0x10000 == 360 degrees
    params: int


def actor_entries(data: bytes, offset: int, count: int) -> list[ActorEntry]:
    out = []
    for k in range(count):
        off = offset + k * ACTOR_ENTRY
        if off + ACTOR_ENTRY > len(data):
            break
        aid, x, y, z, rx, ry, rz, params = struct.unpack_from(">H6hH", data, off)
        out.append(ActorEntry(aid, (x, y, z), (rx, ry, rz), params))
    return out


@dataclass
class Door:
    front_room: int
    front_cam: int
    back_room: int
    back_cam: int
    actor_id: int
    pos: tuple[int, int, int]
    rot_y: int
    params: int


def door_entries(data: bytes, offset: int, count: int) -> list[Door]:
    out = []
    for k in range(count):
        off = offset + k * DOOR_ENTRY
        if off + DOOR_ENTRY > len(data):
            break
        fr, fc, br, bc, aid, x, y, z, ry, params = struct.unpack_from(">4bH4hH", data, off)
        out.append(Door(fr, fc, br, bc, aid, (x, y, z), ry, params))
    return out


@dataclass
class LightSetting:
    ambient: tuple[int, int, int]
    light1_dir: tuple[int, int, int]
    light1_color: tuple[int, int, int]
    light2_dir: tuple[int, int, int]
    light2_color: tuple[int, int, int]
    fog_color: tuple[int, int, int]
    fog_near: int
    blend_rate: int
    z_far: int


def light_settings(data: bytes, offset: int, count: int) -> list[LightSetting]:
    """Command ``0x0F``'s array, stride 22 - settled by the last-u16 distinct-value collapse
    (31 values at stride 22 against 315-336 at every neighbour) and pinned by the direction
    triples, of which 2,229 of 2,940 have integer magnitude exactly 126 or 127."""
    out = []
    for k in range(count):
        off = offset + k * LIGHT_ENTRY
        if off + LIGHT_ENTRY > len(data):
            break
        v = struct.unpack_from(">3B3b3B3b3B3BHh", data, off)
        out.append(LightSetting(v[0:3], v[3:6], v[6:9], v[9:12], v[12:15], v[15:18],
                                v[18] & 0x3FF, v[18] >> 10, v[19]))
    return out


def _next_target(cmds: list[Cmd], after: int, segment: int, size: int) -> int:
    """The nearest pointer target in this header past *after* - the only bound the two
    uncounted arrays (entrances, exits) have."""
    best = size
    for c in cmds:
        if c.segment == segment and after < c.offset < best:
            best = c.offset
    return best


# -- mesh headers -------------------------------------------------------------------------


@dataclass
class BgImage:
    source: int
    width: int
    height: int
    fmt: int
    siz: int
    jpeg: bytes | None = None


@dataclass
class Mesh:
    kind: int                                     # 0 flat, 1 background, 2 culled
    entries: list[tuple[int, int]]                # (opa, xlu) segmented pointers, 0 for none
    spheres: list[tuple[int, int, int, int]]      # type 2 only: centre xyz, radius
    backgrounds: list[BgImage] = field(default_factory=list)


def mesh_header(room: bytes, offset: int) -> Mesh:
    """Room command ``0x0A``.  The common head is ``{u8 type; u8 count; u16 pad; u32 a; u32 b}``
    - the pointers are at +4 and +8, NOT +2 and +6; a spec written without the pad produces
    hundreds of bogus stride failures.  Type 1's byte +1 is the background FORMAT, not a count,
    and its +4 word is one extra indirection away from the display lists: reading it as a
    list executes a ``G_CULLDL`` on the entry array and walks into the JPEG.
    """
    kind = room[offset]
    n = room[offset + 1]
    a, b = struct.unpack_from(">II", room, offset + 4)
    if kind in (0, 2):
        start, end = a & 0xFFFFFF, b & 0xFFFFFF
        stride = 8 if kind == 0 else 16
        if end - start != n * stride or end > len(room):
            raise ValueError(f"mesh type {kind}: {n} entries do not span {start:#x}..{end:#x}")
        entries, spheres = [], []
        for k in range(n):
            e = start + k * stride
            if kind == 2:
                cx, cy, cz, r = struct.unpack_from(">3hH", room, e)
                spheres.append((cx, cy, cz, r))
                e += 8
            entries.append(struct.unpack_from(">II", room, e))
        return Mesh(kind, entries, spheres)
    if kind == 1:
        ep = a & 0xFFFFFF
        entries = [struct.unpack_from(">II", room, ep)]
        bgs: list[BgImage] = []
        if n == 1:
            src, _unk, _tlut, w, h, fmt, siz = struct.unpack_from(">IIIHHBB", room, offset + 8)
            bgs.append(BgImage(src, w, h, fmt, siz))
        elif n == 2:
            count = room[offset + 8]
            arr = struct.unpack_from(">I", room, offset + 12)[0] & 0xFFFFFF
            for k in range(count):
                r = arr + k * 0x1C + 4
                src, _unk, _tlut, w, h, fmt, siz = struct.unpack_from(">IIIHHBB", room, r)
                bgs.append(BgImage(src, w, h, fmt, siz))
        else:
            raise ValueError(f"mesh type 1 with format {n}")
        for bg in bgs:
            so = bg.source & 0xFFFFFF
            if bg.source >> 24 == ROOM_SEGMENT and room[so:so + 4] == b"\xff\xd8\xff\xe0":
                end = room.find(b"\xff\xd9", so)
                bg.jpeg = bytes(room[so:end + 2]) if end > 0 else None
        return Mesh(kind, entries, [], bgs)
    raise ValueError(f"mesh header type {kind}")


# -- assembling one level -----------------------------------------------------------------


def _quat_yxz(rx: int, ry: int, rz: int) -> tuple[float, float, float, float]:
    """Actors are placed with the game's translate-rotate-YXZ, so the rotation is Ry Rx Rz.
    Most placements rotate about Y alone (822 of 1,654 non-zero rotY are multiples of
    0x4000), so the order matters for a handful of actors that reuse rotX/rotZ as
    parameters - which is why the raw binary angles are also carried in the extras."""
    ax, ay, az = rx * BINANG, ry * BINANG, rz * BINANG
    cx, sx = np.cos(ax / 2), np.sin(ax / 2)
    cy, sy = np.cos(ay / 2), np.sin(ay / 2)
    cz, sz = np.cos(az / 2), np.sin(az / 2)
    # quaternions as (x, y, z, w); compose Ry * Rx * Rz
    def mul(a, b):
        ax_, ay_, az_, aw = a
        bx, by, bz, bw = b
        return (aw * bx + ax_ * bw + ay_ * bz - az_ * by,
                aw * by - ax_ * bz + ay_ * bw + az_ * bx,
                aw * bz + ax_ * by - ay_ * bx + az_ * bw,
                aw * bw - ax_ * bx - ay_ * by - az_ * bz)
    qy = (0.0, float(sy), 0.0, float(cy))
    qx = (float(sx), 0.0, 0.0, float(cx))
    qz = (0.0, 0.0, float(sz), float(cz))
    q = mul(mul(qy, qx), qz)
    return tuple(float(v) for v in q)


@dataclass
class RoomInfo:
    slot: int
    file: int
    mesh_kind: int
    triangles: int
    actors: list[ActorEntry]
    alt_actors: list[list[ActorEntry]]
    objects: list[int]
    time: tuple[int, int, int]
    behaviour: int
    echo: int
    wind: tuple[int, int, int, int] | None
    unresolved: list[int]


class Level:
    """Everything decoded from one scene, before it becomes a Scene for export."""

    def __init__(self, entry: SceneEntry) -> None:
        self.entry = entry
        self.rooms: list[RoomInfo] = []
        self.collision: col_mod.Collision | None = None
        self.lights: list[LightSetting] = []
        self.alt_lights: list[list[LightSetting]] = []
        self.spawns: list[ActorEntry] = []
        self.entrances: list[tuple[int, int]] = []
        self.doors: list[Door] = []
        self.exits: list[int] = []
        self.keep: int | None = None
        self.skybox: tuple[int, int, int] = (0, 0, 0)
        self.backgrounds: list[tuple[int, int, bytes]] = []   # (room slot, k, jpeg)
        self.warnings: list[str] = []


def decode(rom, table, code: bytes, entry: SceneEntry, *, geometry: bool = True,
           scene_out: Scene | None = None) -> tuple[Level, Scene]:
    """Decode scene *entry* and, if *geometry*, assemble its rooms into one Scene."""
    scene_bytes = rom.read(rom.files[entry.scene_file])
    cmds = commands(scene_bytes)
    ops = by_op(cmds)
    if CMD_ROOMS not in ops:
        raise ValueError("scene has no room list")
    lvl = Level(entry)
    out = scene_out or Scene(name=f"scene_{entry.index:03d}")

    # -- the scene's own parts
    if CMD_KEEP in ops:
        lvl.keep = ops[CMD_KEEP].w1 & 0xFF
    if CMD_SKYBOX in ops:
        w = ops[CMD_SKYBOX].w1
        lvl.skybox = (w >> 24, (w >> 16) & 0xFF, (w >> 8) & 0xFF)
    if CMD_SPAWNS in ops:
        c = ops[CMD_SPAWNS]
        lvl.spawns = actor_entries(scene_bytes, c.offset, c.count)
    if CMD_ENTRANCES in ops:
        c = ops[CMD_ENTRANCES]
        end = _next_target(cmds, c.offset, SCENE_SEGMENT, len(scene_bytes))
        lvl.entrances = [struct.unpack_from(">BB", scene_bytes, c.offset + 2 * k)
                         for k in range((end - c.offset) // 2)]
    if CMD_EXITS in ops:
        c = ops[CMD_EXITS]
        end = _next_target(cmds, c.offset, SCENE_SEGMENT, len(scene_bytes))
        lvl.exits = list(struct.unpack_from(f">{(end - c.offset) // 2}H", scene_bytes, c.offset))
    if CMD_DOORS in ops:
        c = ops[CMD_DOORS]
        lvl.doors = door_entries(scene_bytes, c.offset, c.count)
    if CMD_LIGHTS in ops:
        c = ops[CMD_LIGHTS]
        lvl.lights = light_settings(scene_bytes, c.offset, c.count)
    for alt in alternate_headers(scene_bytes, cmds, SCENE_SEGMENT):
        try:
            aops = by_op(commands(scene_bytes, alt))
        except ValueError:
            continue
        if CMD_LIGHTS in aops:
            c = aops[CMD_LIGHTS]
            lvl.alt_lights.append(light_settings(scene_bytes, c.offset, c.count))
    if CMD_COLLISION in ops:
        try:
            lvl.collision = col_mod.parse(scene_bytes, ops[CMD_COLLISION].offset, SCENE_SEGMENT)
        except ValueError as exc:
            lvl.warnings.append(f"collision: {exc}")

    # -- the segment map, once
    shared = obj_mod.keep_segments(rom, table, field=lvl.keep == obj_mod.FIELD_KEEP,
                                   dungeon=lvl.keep == obj_mod.DUNGEON_KEEP)

    # -- rooms
    rl = ops[CMD_ROOMS]
    total_missing = 0
    for slot in range(rl.count):
        vs, ve = struct.unpack_from(">II", scene_bytes, rl.offset + slot * 8)
        rf = rom.at_vrom(vs)
        if rf is None or rf.vrom_end != ve:
            lvl.warnings.append(f"room {slot}: vrom {vs:#x}..{ve:#x} is not a file")
            continue
        room = rom.read(rf)
        rcmds = commands(room)
        rops = by_op(rcmds)
        actors = alt_actors = []
        if CMD_ACTORS in rops:
            c = rops[CMD_ACTORS]
            actors = actor_entries(room, c.offset, c.count)
        alt_actors = []
        for alt in alternate_headers(room, rcmds, ROOM_SEGMENT):
            try:
                aops = by_op(commands(room, alt))
            except ValueError:
                continue
            if CMD_ACTORS in aops:
                c = aops[CMD_ACTORS]
                alt_actors.append(actor_entries(room, c.offset, c.count))
        objects: list[int] = []
        if CMD_OBJECTS in rops:
            c = rops[CMD_OBJECTS]
            objects = list(struct.unpack_from(f">{c.count}H", room, c.offset))
        tm = rops[CMD_TIME].w1 if CMD_TIME in rops else 0
        time = ((tm >> 24) & 0xFF, (tm >> 16) & 0xFF, (tm >> 8) & 0xFF)
        wind = None
        if CMD_WIND in rops:
            w = rops[CMD_WIND].w1
            wx, wy, wz, ws = struct.unpack(">bbbB", w.to_bytes(4, "big"))
            wind = (wx, wy, wz, ws)
        info = RoomInfo(slot, rf.index, -1, 0, actors, alt_actors, objects, time,
                        rops[CMD_BEHAVIOUR].w1 if CMD_BEHAVIOUR in rops else 0,
                        rops[CMD_ECHO].w1 & 0xFF if CMD_ECHO in rops else 0, wind, [])
        if CMD_MESH not in rops:
            lvl.warnings.append(f"room {slot}: no mesh header")
            lvl.rooms.append(info)
            continue
        try:
            mesh = mesh_header(room, rops[CMD_MESH].offset)
        except ValueError as exc:
            lvl.warnings.append(f"room {slot}: {exc}")
            lvl.rooms.append(info)
            continue
        info.mesh_kind = mesh.kind
        for k, bg in enumerate(mesh.backgrounds):
            if bg.jpeg:
                lvl.backgrounds.append((slot, k, bg.jpeg))
        if geometry:
            segs = f3dex2.Segments({SCENE_SEGMENT: scene_bytes, ROOM_SEGMENT: room, **shared})
            batches: list[f3dex2.Batch] = []
            unresolved: set[int] = set()
            for opa, xlu in mesh.entries:
                for dl in (opa, xlu):
                    if not dl:
                        continue
                    res = f3dex2.run(dl, segs)   # no matrix, no offset: world space already
                    batches.extend(res.batches)
                    unresolved |= res.unresolved
            # Segments 8-0xD are tile-state lists the frame builds at draw time; they are
            # not geometry we are missing and do not count as unresolved.
            info.unresolved = sorted(s for s in unresolved if s not in range(8, 0x0E))
            info.triangles = sum(len(b.indices) // 3 for b in batches)
            if batches:
                total_missing += zobj.assemble(out, batches, segs, group=f"room_{slot:02d}",
                                               prefix=f"r{slot:02d}_", skinned=False)
        lvl.rooms.append(info)

    if geometry and lvl.collision is not None:
        _add_collision(out, lvl.collision)
    if geometry:
        _add_empties(out, lvl, code)
    out.extras = _extras(lvl, code, total_missing)
    out.warnings += lvl.warnings
    return lvl, out


def _add_collision(scene: Scene, c: col_mod.Collision) -> None:
    """The scene's collision on its own node - see collision.add_to_scene."""
    col_mod.add_to_scene(scene, c, zobj.SCALE)


def _add_empties(scene: Scene, lvl: Level, code: bytes) -> None:
    """Every actor placement, spawn and door as a named empty - a placement on the cartridge
    never disappears because we lack a model for it."""
    for r in lvl.rooms:
        for k, a in enumerate(r.actors):
            scene.empties.append(Empty(
                name=f"room_{r.slot:02d}_actor_{k:03d}_id{a.id:03x}",
                translation=tuple(float(v) * zobj.SCALE for v in a.pos),
                rotation=_quat_yxz(*a.rot),
                extras={"actor_id": a.id, "params": a.params, "rot_binang": list(a.rot),
                        "room": r.slot},
            ))
    for k, s in enumerate(lvl.spawns):
        room = next((rm for sp, rm in lvl.entrances if sp == k), None)
        scene.empties.append(Empty(
            name=f"spawn_{k:02d}", translation=tuple(float(v) * zobj.SCALE for v in s.pos),
            rotation=_quat_yxz(*s.rot),
            extras={"params": s.params, "room": room, "rot_binang": list(s.rot)},
        ))
    for k, d in enumerate(lvl.doors):
        scene.empties.append(Empty(
            name=f"door_{k:02d}_rooms_{d.front_room}_{d.back_room}",
            translation=tuple(float(v) * zobj.SCALE for v in d.pos),
            rotation=_quat_yxz(0, d.rot_y, 0),
            extras={"actor_id": d.actor_id, "front_room": d.front_room,
                    "back_room": d.back_room, "params": d.params},
        ))


def _extras(lvl: Level, code: bytes, missing: int) -> dict:
    c = lvl.collision
    return {
        "format": "n64_scene",
        "scene_index": lvl.entry.index,
        "scene_file": lvl.entry.scene_file,
        "title_file": lvl.entry.title_file,
        "draw_config": lvl.entry.draw_config,
        "keep_object": lvl.keep,
        "skybox": {"id": lvl.skybox[0], "config": lvl.skybox[1], "env_light_mode": lvl.skybox[2]},
        "rooms": [
            {"slot": r.slot, "file": r.file, "mesh_type": r.mesh_kind, "triangles": r.triangles,
             "actors": [asdict(a) for a in r.actors],
             "alternate_actors": [[asdict(a) for a in alt] for alt in r.alt_actors],
             "objects": r.objects, "time": list(r.time), "behaviour": r.behaviour,
             "echo": r.echo, "wind": list(r.wind) if r.wind else None,
             "unresolved_segments": r.unresolved}
            for r in lvl.rooms
        ],
        "spawns": [asdict(s) for s in lvl.spawns],
        "entrances": [list(e) for e in lvl.entrances],
        "exits": lvl.exits,
        "doors": [asdict(d) for d in lvl.doors],
        "lights": [asdict(s) for s in lvl.lights],
        "alternate_lights": len(lvl.alt_lights),
        # 47 of the 80 fixed-mode scenes have 4-26 settings and nothing in the file selects
        # among them; index 0 is a choice, and it is labelled as one.
        "light_setting_chosen": 0 if lvl.lights else None,
        "collision": None if c is None else {
            "vertices": int(len(c.vertices)), "polygons": int(len(c.polygons)),
            "surface_types": [list(s) for s in c.surface_types],
            "bounds_declared": [list(c.bounds_declared[0]), list(c.bounds_declared[1])],
            "bounds": [[int(v) for v in c.bounds[0]], [int(v) for v in c.bounds[1]]],
            "water_boxes": [asdict(w) for w in c.water_boxes],
            "cam_data": [{"setting": cd.setting, "count": cd.count,
                          "points": cd.points.tolist()} for cd in c.cam_data],
        },
        "backgrounds": len(lvl.backgrounds),
        "textures_missing": missing,
        "units": "N64 world units * 0.01, Y up, the same scale as the character models",
    }


# -- the whole game -----------------------------------------------------------------------


def extract_levels(rom, table, out_dir: Path, *, progress=None,
                   models_by_object: dict[int, str] | None = None) -> list[dict]:
    """Export every scene in *rom* as one glTF, plus its backgrounds.  Returns rip rows.

    *models_by_object* maps an object id to the rip's model for it (a character's or a prop's
    glTF name), so every actor empty says which model stands there.
    """
    models_by_object = models_by_object or {}
    from n64rip import names
    from ripcore import gltf

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if table is None:
        return rows
    code = rom.read(rom.files[table.file_index])
    table_off, entries = find_scene_table(rom, code)
    if not entries:
        return rows
    ent_off, ent_count = find_entrance_table(code, table_off,
                                             floor=table.offset + 8 * len(table.entries))
    actor_obj = obj_mod.actor_objects(rom, code)
    for n, e in enumerate(entries):
        if progress and n % 10 == 0:
            progress(n, len(entries))
        name = names.scene_name(e.index, "oot")
        row = {"name": name, "file_index": e.scene_file,
               "vrom": f"{rom.files[e.scene_file].vrom_start:#x}", "kind": "level",
               "scene_index": e.index, "limbs": 0, "posed": False, "expressions": [],
               "out_rel": "", "thumb": "", "triangles": 0, "vertices": 0, "textures": 0,
               "textures_missing": 0, "drawn_limbs": 0, "unresolved_segments": [],
               "warnings": [], "error": "", "rooms": 0, "collision_polygons": 0,
               "actors": 0, "backgrounds": []}
        try:
            lvl, sc = decode(rom, table, code, e, scene_out=Scene(name=name))
        except Exception as exc:  # noqa: BLE001 - one bad scene must not stop the rip
            row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            continue
        # the exits, resolved through the entrance table, and each placement's object
        sc.extras["exits_resolved"] = [
            None if x in (0, 0x7FFF, 0xFFFF) else
            (lambda r: None if r is None else {"scene": r[0], "spawn": r[1]})(
                entrance(code, ent_off, ent_count, x))
            for x in lvl.exits
        ]
        for r in sc.extras["rooms"]:
            for a in r["actors"]:
                a["object_id"] = actor_obj.get(a["id"])
                a["model"] = models_by_object.get(a["object_id"])
        for emp in sc.empties:
            aid = emp.extras.get("actor_id")
            if aid is not None:
                emp.extras["object_id"] = actor_obj.get(aid)
                emp.extras["model"] = models_by_object.get(actor_obj.get(aid))
        base = out_dir / name
        for slot, k, jpeg in lvl.backgrounds:
            bg = out_dir / f"{name}_bg_room{slot:02d}_{k}.jpg"
            bg.write_bytes(jpeg)
            row["backgrounds"].append(bg.name)
        try:
            st = gltf.export(sc, base, thumbnail=True)
            thumb = gltf.thumbnail(st, base, size=256)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"export: {type(exc).__name__}: {exc}"
            rows.append(row)
            continue
        room_tris = sum(r.triangles for r in lvl.rooms)
        row.update({
            "out_rel": f"{name}.gltf", "thumb": f"{name}_thumb.png" if thumb else "",
            "triangles": room_tris, "vertices": sc.vertices, "textures": len(sc.textures),
            "textures_missing": int(sc.extras.get("textures_missing", 0)),
            "warnings": list(sc.warnings), "rooms": len(lvl.rooms),
            "collision_polygons": 0 if lvl.collision is None else int(len(lvl.collision.polygons)),
            "actors": sum(len(r.actors) for r in lvl.rooms),
            "unresolved_segments": sorted({s for r in lvl.rooms for s in r.unresolved}),
        })
        rows.append(row)
    return rows
