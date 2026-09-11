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


def combine_reads_texel_alpha(w0: int, w1: int) -> bool:
    """Does ``G_SETCOMBINE``'s alpha equation take a texel as an input?

    The alpha multiplexer's sources are packed across both words; we only need to know
    whether TEXEL0/TEXEL1 appear anywhere in it, so every alpha field is checked rather than
    reconstructing the full two-cycle equation.
    """
    fields = (
        (w0 >> 21) & 0x07,  # aA0
        (w0 >> 3) & 0x07,   # aC0
        (w1 >> 12) & 0x07,  # aB0
        (w1 >> 9) & 0x07,   # aD0
        (w0 >> 18) & 0x07,  # aA1
        (w0 >> 0) & 0x07,   # aC1
        (w1 >> 3) & 0x07,   # aB1
        (w1 >> 0) & 0x07,   # aD1
    )
    return any(f in TEXEL_ALPHA_SOURCES for f in fields)
