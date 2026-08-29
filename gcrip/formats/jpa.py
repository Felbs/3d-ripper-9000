"""JPAC1-00 particle banks (.jpc) - JSystem JParticle, as The Wind Waker ships them.

Layouts from the zeldaret/tww decompilation, which has the whole JParticle library matching
(src/JSystem/JParticle/JPAEmitterLoader.cpp drives all of this); field tables recorded in
gcrip/data/ww_particles.json.  Every offset here was checked against that file.

Container (JPAEmitterLoader.cpp:47-101)
  0x00 char[8] "JPAC1-00"   0x08 u16 emtrResNum   0x0A u16 texResNum   payload at 0x20
  then emtrResNum resources back to back, then texResNum TEX1 blocks, to EOF.

Resource header (0x20 bytes, EmitterLoader.cpp:76-86, 130)
  0x0C u32 blockNum   0x14 u8 keyNum   0x15 u8 fldNum   0x16 u8 textureNum   0x18 u16 resID
  resID is the same u16 the game passes to dComIfGp_particle_set, flag bits included.
  +0x10 is NOT a reliable size - walk blocks by blockNum and each block's own size.

Block header: 0x00 magic, 0x04 u32 size (incl. header), 0x08 u32 zero, payload at 0x0C.
Blocks: BEM1 (emitter dynamics), BSP1 (shape, texture, blend, colours), ESP1 (envelopes),
SSP1 (children), ETX1 (indirect), KFA1 (keyframes), FLD1 (fields), TDB1 (texture id table).

Texture block: 0x0C char[0x14] name, then at 0x20 a plain BTI header + image data, which is
why gcrip.formats.bti reads it with no new code.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from gcrip.formats import bti

MAGIC = b"JPAC1-00"

# the blend vocabulary of the retail banks: only these three combinations occur
BLEND_NAMES = {0: "none", 1: "blend", 2: "logic"}


@dataclass
class Shape:
    """BSP1 - everything the renderer needs."""

    flags: int
    base_size: tuple[float, float]
    blend_flags: int
    alpha_flags: int
    alpha_ref0: int
    alpha_ref1: int
    z_flags: int
    texture_flags: int
    texture_index: int  # local slot, resolved through TDB1
    color_flags: int
    prm_color: tuple[int, int, int, int]
    env_color: tuple[int, int, int, int]
    tex_anim_keys: int
    tex_scroll: tuple[float, float]

    @property
    def shape_type(self) -> int:
        return self.flags & 0xF

    @property
    def additive(self) -> bool:
        # mBlendFlags packs src/dst factors: additive banks use dst = ONE (0x1) in the
        # high nibble pair; the only three combos on the disc are alpha / additive / multiply
        dst = (self.blend_flags >> 6) & 0xF
        return dst == 1

    @property
    def multiply(self) -> bool:
        src = (self.blend_flags >> 2) & 0xF
        return src == 0 and ((self.blend_flags >> 6) & 0xF) == 2


@dataclass
class Dynamics:
    """BEM1 - the emitter."""

    flags: int
    volume_size: int
    div_number: int
    rate: float
    rate_rndm: float
    rate_step: int
    max_frame: int
    start_frame: int
    life_time: int
    life_time_rndm: float
    init_vel_omni: float
    init_vel_axis: float
    init_vel_rndm: float
    init_vel_dir: float
    init_vel_ratio: float
    spread: float

    @property
    def volume_type(self) -> int:
        return (self.flags >> 8) & 7


@dataclass
class Envelope:
    """ESP1 - per-particle alpha / scale / spin envelopes."""

    flags: int
    alpha_in_timing: float
    alpha_out_timing: float
    alpha_in_value: float
    alpha_base_value: float
    alpha_out_value: float
    scale_in_timing: float
    scale_out_timing: float
    scale_in_x: float
    scale_out_x: float
    scale_in_y: float
    scale_out_y: float
    random_scale: float
    rotate_angle: float
    rotate_speed: float
    rotate_random_angle: float
    rotate_random_speed: float


@dataclass
class Effect:
    res_id: int
    dynamics: Dynamics | None
    shape: Shape | None
    envelope: Envelope | None
    texture_ids: list[int] = field(default_factory=list)  # TDB1 -> bank texture indices
    block_magics: list[str] = field(default_factory=list)
    has_children: bool = False  # SSP1 present
    has_fields: bool = False  # FLD1 present (gravity / wind / drag)

    @property
    def texture_index(self) -> int | None:
        if self.shape is None or not self.texture_ids:
            return None
        slot = self.shape.texture_index
        return self.texture_ids[slot] if slot < len(self.texture_ids) else None


@dataclass
class Bank:
    effects: list[Effect]
    textures: list[tuple[str, bti.BtiTexture]]

    def find(self, res_id: int) -> Effect | None:
        for e in self.effects:
            if e.res_id == res_id:
                return e
        return None


def _dynamics(d: bytes, o: int) -> Dynamics:
    flags = struct.unpack_from(">I", d, o)[0]
    vsize, vdiv = struct.unpack_from(">HH", d, o + 0x0C)
    rate, rate_rndm = struct.unpack_from(">ff", d, o + 0x10)
    rate_step = d[o + 0x18]
    max_frame, start_frame, life = struct.unpack_from(">hhh", d, o + 0x1A)
    life_rndm, omni, axis, rndm, vdir, ratio = struct.unpack_from(">6f", d, o + 0x20)
    spread = struct.unpack_from(">f", d, o + 0x38)[0]
    return Dynamics(
        flags,
        vsize,
        vdiv,
        rate,
        rate_rndm,
        rate_step,
        max_frame,
        start_frame,
        life,
        life_rndm,
        omni,
        axis,
        rndm,
        vdir,
        ratio,
        spread,
    )


def _shape(d: bytes, o: int) -> Shape:
    flags = struct.unpack_from(">I", d, o)[0]
    bx, by = struct.unpack_from(">ff", d, o + 0x08)
    blend = struct.unpack_from(">H", d, o + 0x12)[0]
    aflags, ref0, ref1, zflags, tflags, tkeys, tindex, cflags = struct.unpack_from(
        ">8B", d, o + 0x14
    )
    prm = tuple(struct.unpack_from(">4B", d, o + 0x20))
    env = tuple(struct.unpack_from(">4B", d, o + 0x24))
    sx, sy = struct.unpack_from(">ff", d, o + 0x40)
    return Shape(
        flags,
        (bx, by),
        blend,
        aflags,
        ref0,
        ref1,
        zflags,
        tflags,
        tindex,
        cflags,
        prm,
        env,
        tkeys,
        (sx, sy),  # type: ignore[arg-type]
    )


def _envelope(d: bytes, o: int) -> Envelope:
    flags = struct.unpack_from(">I", d, o)[0]
    a_in_t, a_out_t, a_in, a_base, a_out = struct.unpack_from(">5f", d, o + 0x08)
    s_in_t, s_out_t, s_in_x, s_out_x, s_in_y, s_out_y, s_rnd = struct.unpack_from(
        ">7f", d, o + 0x2C
    )
    r_ang, r_spd, r_rang, r_rspd = struct.unpack_from(">4f", d, o + 0x4C)
    return Envelope(
        flags,
        a_in_t,
        a_out_t,
        a_in,
        a_base,
        a_out,
        s_in_t,
        s_out_t,
        s_in_x,
        s_out_x,
        s_in_y,
        s_out_y,
        s_rnd,
        r_ang,
        r_spd,
        r_rang,
        r_rspd,
    )


def parse(data: bytes) -> Bank:
    if data[:8] != MAGIC:
        raise ValueError("not a JPAC1-00 bank")
    n_res, n_tex = struct.unpack_from(">HH", data, 8)
    off = 0x20
    effects: list[Effect] = []
    for _ in range(n_res):
        block_num = struct.unpack_from(">I", data, off + 0x0C)[0]
        tex_num = data[off + 0x16]
        res_id = struct.unpack_from(">H", data, off + 0x18)[0]
        bo = off + 0x20
        dyn = shp = env = None
        tex_ids: list[int] = []
        magics: list[str] = []
        children = fields = False
        for _b in range(block_num):
            magic = data[bo : bo + 4].decode("latin-1")
            size = struct.unpack_from(">I", data, bo + 4)[0]
            if size < 0x0C:
                raise ValueError(f"bad block size {size} at {bo:#x}")
            payload = bo + 0x0C
            magics.append(magic)
            if magic == "BEM1":
                dyn = _dynamics(data, payload)
            elif magic == "BSP1":
                shp = _shape(data, payload)
            elif magic == "ESP1":
                env = _envelope(data, payload)
            elif magic == "TDB1":
                tex_ids = list(struct.unpack_from(f">{tex_num}H", data, payload))
            elif magic == "SSP1":
                children = True
            elif magic == "FLD1":
                fields = True
            bo += size
        effects.append(Effect(res_id, dyn, shp, env, tex_ids, magics, children, fields))
        off = bo
    textures: list[tuple[str, bti.BtiTexture]] = []
    for _ in range(n_tex):
        size = struct.unpack_from(">I", data, off + 4)[0]
        name = data[off + 0x0C : off + 0x20].split(b"\0")[0].decode("latin-1", "replace")
        tex = bti.parse(data[off + 0x20 : off + size])
        textures.append((name, tex))
        off += size
    return Bank(effects, textures)
