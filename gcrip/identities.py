"""Executable identities: the arithmetic that says a format is read correctly.

Every format cracked in this project fell to an *identity* - a number the file states that must
equal a number computed from the file.  A wrong stride cannot hold a column constant across
1,987 records, cannot keep a normal's length at 1.0000, and cannot tile a block to the byte.
That is what separates *plausible* from *correct*, and it is why the notes in `docs/formats/`
quote counts like "200 of 200" and "12 of 12".

Until now those identities lived only in prose in the module docstrings, which means they were
checked **once**, by hand, on the day the format fell.  This module makes them runnable, so a
regression in a reader shows up as an identity that stopped holding rather than as a disc that
quietly produces less.

A format module declares them as a module-level ``IDENTITIES`` list::

    IDENTITIES = [
        Identity(
            "payloads tile the block",
            "data_start + sum(size) == len(block)",
            _check_tiling,
        ),
    ]

Each check takes the format's bytes and returns ``(held, detail)``.  Returning ``None`` for
`held` means *not applicable to this input* - a check that needs a member the sample does not
have should skip rather than fail, because an identity that cries wolf gets ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: (held, detail).  `held` is None when the identity does not apply to this input.
CheckResult = tuple[bool | None, str]


@dataclass(frozen=True)
class Identity:
    """One checkable claim about a format."""

    name: str
    #: the arithmetic, written the way the format note writes it
    formula: str
    check: Callable[[bytes], CheckResult]


@dataclass(frozen=True)
class Result:
    identity: Identity
    held: bool | None
    detail: str

    @property
    def status(self) -> str:
        return "skip" if self.held is None else ("hold" if self.held else "FAIL")

    def __str__(self) -> str:
        return f"[{self.status}] {self.identity.name}: {self.detail}"


def identities_for(module) -> list[Identity]:
    """The identities a format module declares, or ``[]``."""
    return list(getattr(module, "IDENTITIES", ()) or ())


def check(module, data: bytes) -> list[Result]:
    """Run every identity a module declares against one blob.

    A check that raises is reported as a failure rather than propagating: the point is to say
    which claim stopped holding, and an exception is the loudest way for one to stop holding.
    """
    out: list[Result] = []
    for ident in identities_for(module):
        try:
            held, detail = ident.check(data)
        except Exception as ex:  # noqa: BLE001
            held, detail = False, f"{type(ex).__name__}: {ex}"
        out.append(Result(ident, held, detail))
    return out


def failures(results: list[Result]) -> list[Result]:
    return [r for r in results if r.held is False]


def summarise(results: list[Result]) -> str:
    held = sum(1 for r in results if r.held is True)
    bad = sum(1 for r in results if r.held is False)
    skip = sum(1 for r in results if r.held is None)
    return f"{held} hold, {bad} failed, {skip} skipped"
