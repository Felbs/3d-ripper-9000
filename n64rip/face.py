"""Face expressions: the eye and mouth textures an actor swaps at runtime.

A Zelda character's face is not painted into its model.  The head's display list samples
segments 8 and 9, and the game points those at one of several textures each frame - which is
why a static rip leaves the face blank, and why "the face is missing" is a *texture* problem
rather than a geometry one.

The tables that hold those textures are findable the same way the object table was: by shape
rather than by name.  Eye textures are a contiguous run of equally-sized images, so the
pointers to them advance by exactly one texture's size.  For Link that is 64x32 CI8 - 0x800
bytes - and 32x32 CI8 for the mouth, 0x400.  A run of segment-6 pointers with a constant
stride of exactly that is not a coincidence.

On Ocarina of Time this finds 9 eye states and 4 mouth states, their tables adjacent in
``code``, exactly as ``sEyeTextures[]`` and ``sMouthTextures[]`` are laid out.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

#: what the head's display list asks for, read from the display list rather than assumed
EYE_SEGMENT = 8
MOUTH_SEGMENT = 9
MIN_RUN = 3  # fewer than this is not a table


@dataclass
class FaceSet:
    """Every expression an actor can wear, as offsets into its own object file."""

    eyes: list[int] = field(default_factory=list)
    mouths: list[int] = field(default_factory=list)
    eye_size: tuple[int, int] = (64, 32)
    mouth_size: tuple[int, int] = (32, 32)

    def __bool__(self) -> bool:
        return bool(self.eyes or self.mouths)


def _runs(words: tuple[int, ...], limit: int, stride: int) -> list[list[int]]:
    """Runs of consecutive segment-6 pointers whose offsets advance by *stride*."""
    ptrs = [(i, w & 0xFFFFFF) for i, w in enumerate(words)
            if (w >> 24) == 0x06 and (w & 0xFFFFFF) < limit]
    out: list[list[int]] = []
    i = 0
    while i < len(ptrs):
        run = [ptrs[i][1]]
        k = i
        while (k + 1 < len(ptrs)
               and ptrs[k + 1][0] == ptrs[k][0] + 1
               and ptrs[k + 1][1] - ptrs[k][1] == stride):
            run.append(ptrs[k + 1][1])
            k += 1
        if len(run) >= MIN_RUN:
            out.append(run)
            i = k
        i += 1
    return out


def find_faces(code: bytes, object_size: int,
               eye_size: tuple[int, int] = (64, 32),
               mouth_size: tuple[int, int] = (32, 32)) -> FaceSet:
    """Eye and mouth texture offsets for an actor whose object file is *object_size* bytes.

    Sizes come from the tile the head's display list requests, so this works for any actor
    that swaps a face, not only for Link - pass the sizes the interpreter reported.
    """
    n = len(code) // 4
    if n < 4:
        return FaceSet()
    words = struct.unpack_from(f">{n}I", code, 0)
    eye_bytes = eye_size[0] * eye_size[1]  # CI8: one byte a texel
    mouth_bytes = mouth_size[0] * mouth_size[1]
    eye_runs = _runs(words, object_size, eye_bytes)
    mouth_runs = _runs(words, object_size, mouth_bytes)
    best_eyes = max(eye_runs, key=len) if eye_runs else []
    best_mouths = max(mouth_runs, key=len) if mouth_runs else []
    return FaceSet(eyes=best_eyes, mouths=best_mouths,
                   eye_size=eye_size, mouth_size=mouth_size)


def segments_for(faces: FaceSet, obj: bytes, eye: int = 0, mouth: int = 0) -> dict[int, bytes]:
    """Bind one expression: ``{8: eyes, 9: mouth}`` as segment bases into the object file."""
    out: dict[int, bytes] = {}
    if faces.eyes:
        out[EYE_SEGMENT] = obj[faces.eyes[min(eye, len(faces.eyes) - 1)]:]
    if faces.mouths:
        out[MOUTH_SEGMENT] = obj[faces.mouths[min(mouth, len(faces.mouths) - 1)]:]
    return out
