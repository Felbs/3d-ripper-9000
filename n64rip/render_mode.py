"""The RDP render mode: whether a surface is opaque, alpha-tested or blended.

Everything in a Zelda model is exported OPAQUE unless this is decoded, and that is wrong for
a large minority of it.  The N64 draws hair, fabric, fences, leaves and cut-out detail as a
texture with holes punched by an **alpha test** - so leaving them opaque fills the holes back
in, which is what makes a character appear to be wearing stray plates and earrings.

Two commands decide it.  ``G_SETOTHERMODE_L`` (0xE2) carries the render mode bits; the ones
that matter here are the blender's force-blend flag, the coverage-times-alpha flag, and the
Z mode.  ``G_SETCOMBINE`` (0xFC) decides whether the alpha being tested comes from a texel at
all - and that check is not optional: without it, surfaces bound to intensity-only textures,
whose alpha is their brightness, get punched full of holes.
"""

from __future__ import annotations

# G_SETOTHERMODE_L render-mode bits (low word)
AA_EN = 0x0008
Z_CMP = 0x0010
Z_UPD = 0x0020
IM_RD = 0x0040
CLR_ON_CVG = 0x0080
CVG_DST_MASK = 0x0300
ZMODE_MASK = 0x0C00
ZMODE_OPA = 0x0000
ZMODE_INTER = 0x0400
ZMODE_XLU = 0x0800
ZMODE_DEC = 0x0C00
CVG_X_ALPHA = 0x1000
ALPHA_CVG_SEL = 0x2000
FORCE_BL = 0x4000

#: alpha-compare, the low two bits of the other-mode low word
AC_NONE, AC_THRESHOLD, AC_DITHER = 0, 1, 3

#: combiner alpha sources that mean "the alpha comes from the texture"
TEXEL_ALPHA_SOURCES = {1, 2}  # TEXEL0, TEXEL1 in the alpha multiplexer


def alpha_mode(other_low: int, reads_texel_alpha: bool) -> str:
    """``OPAQUE`` | ``MASK`` | ``BLEND`` for one render mode.

    *reads_texel_alpha* says whether the combiner's alpha equation actually samples a texel.
    It is mandatory: an intensity texture's alpha is its brightness, so testing it turns a
    solid surface into lace.
    """
    zmode = other_low & ZMODE_MASK
    if zmode in (ZMODE_XLU, ZMODE_DEC) and (other_low & FORCE_BL):
        return "BLEND"
    if not reads_texel_alpha:
        return "OPAQUE"
    if (other_low & CVG_X_ALPHA) or (other_low & 0x03) == AC_THRESHOLD:
        return "MASK"
    return "OPAQUE"


#: ``G_SETCOMBINE`` packs sixteen multiplexer selects across two words, and gbi.h does it with
#: no regular stride - the alpha halves of cycle 1 live in *w1*, not *w0*.  Each entry is
#: ``(word, shift, mask)``; the word index is 0 or 1.
#:
#: This layout is not taken on trust.  Adult Link is drawn by two combiners that differ only in
#: bits 5-8 of ``w0`` - ``0xfc127e60`` and ``0xfc127ea0`` - and his 389 skin-and-boot triangles
#: take the first while his 206 tunic triangles take the second.  Read as ``a1 = (w0 >> 5) & 0xF``
#: that is PRIMITIVE (3) against ENVIRONMENT (5), which is exactly the difference between a
#: constant the object list sets and one the actor sets, and it is why the tunic is the piece
#: that loses its colour.  Every other field here is from the same packing.
COMBINE_FIELDS = {
    "a0":  (0, 20, 0x0F), "b0":  (1, 28, 0x0F), "c0":  (0, 15, 0x1F), "d0":  (1, 15, 0x07),
    "a1":  (0,  5, 0x0F), "b1":  (1, 24, 0x0F), "c1":  (0,  0, 0x1F), "d1":  (1,  6, 0x07),
    "Aa0": (0, 12, 0x07), "Ab0": (1, 12, 0x07), "Ac0": (0,  9, 0x07), "Ad0": (1,  9, 0x07),
    "Aa1": (1, 21, 0x07), "Ab1": (1,  3, 0x07), "Ac1": (1, 18, 0x07), "Ad1": (1,  0, 0x07),
}

#: RGB ``a``/``b``/``d`` mux, and the alpha mux, share these source codes for 0-5.
MUX_PRIMITIVE = 3
MUX_ENVIRONMENT = 5

#: The RGB ``c`` mux is five bits wide and has its own table past index 5.
CC_C_PRIMITIVE = 3
CC_C_ENVIRONMENT = 5


def combine_fields(w0: int, w1: int) -> dict[str, int]:
    """Every multiplexer select in one ``G_SETCOMBINE``, by gbi's own field names."""
    words = (w0, w1)
    return {k: (words[i] >> s) & m for k, (i, s, m) in COMBINE_FIELDS.items()}


def combine_reads_texel_alpha(w0: int, w1: int) -> bool:
    """Does ``G_SETCOMBINE``'s alpha equation take a texel as an input?

    We only need to know whether TEXEL0/TEXEL1 appear anywhere in it, so every alpha field is
    checked rather than reconstructing the full two-cycle equation.

    The eight alpha selects are read at the positions :data:`COMBINE_FIELDS` records.  An
    earlier version read four of them out of *w0* at shifts 21, 3, 18 and 0 - which overlap the
    command byte, the RGB ``c1`` field and each other - and this decides OPAQUE against MASK
    against BLEND on every material in the rip, so it was worth getting right.
    """
    f = combine_fields(w0, w1)
    return any(f[k] in TEXEL_ALPHA_SOURCES
               for k in ("Aa0", "Ab0", "Ac0", "Ad0", "Aa1", "Ab1", "Ac1", "Ad1"))


def combine_constant(w0: int, w1: int) -> str | None:
    """Which constant colour register the RGB equation actually reads: ``"env"``, ``"prim"``
    or ``None``.

    The combiner multiplies the texture by a constant, and *which* constant is not a detail:
    731 of this ROM's 3,309 tinted textured triangles - including every one of adult Link's
    tunic triangles, every one of child Link's, and every one of the frog's - take it from
    ENVIRONMENT, not PRIMITIVE.  Assuming PRIMITIVE happens to look right on Link only because
    the object list parks the Kokiri tunic constant in both registers.

    ENVIRONMENT wins a tie: it is the later multiply in a two-cycle chain, and where both are
    named the prim value is usually the white identity.
    """
    f = combine_fields(w0, w1)
    rgb = (f["a0"], f["b0"], f["d0"], f["a1"], f["b1"], f["d1"])
    env = MUX_ENVIRONMENT in rgb or f["c0"] == CC_C_ENVIRONMENT or f["c1"] == CC_C_ENVIRONMENT
    prim = MUX_PRIMITIVE in rgb or f["c0"] == CC_C_PRIMITIVE or f["c1"] == CC_C_PRIMITIVE
    if env:
        return "env"
    return "prim" if prim else None


#: RGB ``c``-mux codes for the registers that weight a two-cycle blend.
CC_C_ENV_ALPHA = 12
CC_C_LOD_FRACTION = 13
CC_C_PRIM_LOD_FRAC = 14

MUX_TEXEL1 = 2
CC_C_TEXEL1 = 2


def combine_uses_texel1(w0: int, w1: int) -> bool:
    """Does the RGB equation sample the SECOND tile?

    1,051 triangles over 11 models are drawn this way and the second texture is present,
    distinct and resolvable in the actor's own file - Volvagia's tile 0 is a bright orange
    flame sheet and tile 1 a dark red molten-rock sheet, both coherent 32x32 RGBA16 of the same
    size, so they are two pieces of art and not two mip levels.  MaterialDef has one texture
    slot, so without this the second one is simply dropped.
    """
    f = combine_fields(w0, w1)
    return (MUX_TEXEL1 in (f["a0"], f["b0"], f["d0"], f["a1"], f["b1"], f["d1"])
            or f["c0"] == CC_C_TEXEL1 or f["c1"] == CC_C_TEXEL1)


def combine_blend_register(w0: int, w1: int) -> str | None:
    """Which register weights the blend between the two tiles, by name, or None.

    Recorded rather than baked.  The weight is ENV_ALPHA on 843 of this ROM's two-tile
    triangles and PRIM_LOD_FRAC on 208, never LOD_FRACTION - and where the object's own
    display list never sets it (object 158's 188 triangles carry no G_SETENVCOLOR or
    G_SETPRIMCOLOR at all) the ACTOR writes it at draw time, which is an overlay-disassembly
    job and not something to guess.  Baking a 50/50 blend produces a render that looks
    convincing and is not derived from anything, which is the failure mode this package keeps
    having to undo.
    """
    f = combine_fields(w0, w1)
    for c in (f["c0"], f["c1"]):
        if c == CC_C_ENV_ALPHA:
            return "env_alpha"
        if c == CC_C_PRIM_LOD_FRAC:
            return "prim_lod_frac"
        if c == CC_C_LOD_FRACTION:
            return "lod_fraction"
    return None
