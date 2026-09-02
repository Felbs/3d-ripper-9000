"""The identities that cracked each format, run as tests.

Until now they lived only in prose in the module docstrings, which means each was checked once,
by hand, on the day the format fell.  A reader that regresses would show up as a disc quietly
producing less - the exact failure mode this session spent its time on.

The point of an identity is that it cannot be satisfied by accident: a wrong stride cannot hold
a column constant, cannot keep a norm at 1.0000, and cannot tile a block to the byte.  So each
test here checks the identity holds on good data **and fails on damaged data** - an identity
that cannot fail is not evidence of anything.
"""

from __future__ import annotations

import struct

import pytest

from gcrip import identities
from gcrip.formats import mula, tr_dfm, tr_skl

from .test_mula import make_gct, make_mula
from .test_tr_dfm import make_dfm
from .test_tr_skl import BIPED, make_skl

MODULES = [mula, tr_skl, tr_dfm]


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_cracked_format_declares_identities(module):
    """A format whose note quotes '200 of 200' should be able to say so in code."""
    assert identities.identities_for(module), f"{module.__name__} declares none"
    for ident in identities.identities_for(module):
        assert ident.name and ident.formula, "an identity must state its arithmetic"


def _good_samples():
    return {
        mula: make_mula(
            [
                ("TEXTURES\\A.GCT", make_gct(64, 64, 14)),
                ("TEXTURES\\B.GCT", make_gct(32, 32, 9)),
                ("TEXTURES\\C.GCT", make_gct(16, 16, 8)),
            ]
        ),
        tr_skl: make_skl(BIPED),
        tr_dfm: make_dfm(
            [
                ("binoculars2", 68, (-0.5, -0.5, -0.2, -0.2, 0.0, 0.3)),
                ("canteen", 32, (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)),
            ]
        ),
    }


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_identities_hold_on_good_data(module):
    data = _good_samples()[module]
    results = identities.check(module, data)
    assert results, "no identities ran"
    assert not identities.failures(results), "\n".join(str(r) for r in results)
    assert any(r.held is True for r in results), "every identity skipped - the sample is wrong"


def test_a_broken_tiling_is_caught():
    """Truncating a MULA block must break the tiling identity, not go unnoticed."""
    data = make_mula([("A.GCT", make_gct(32, 32, 9)), ("B.GCT", make_gct(32, 32, 9))])
    results = identities.check(mula, data)
    assert not identities.failures(results)
    # a block whose last payload is short no longer reaches the end
    hurt = identities.check(mula, data[:-32])
    assert [r.held for r in hurt] != [r.held for r in results], "truncation went unnoticed"


def test_a_forward_parent_is_caught():
    """The identity has to fail on damaged data or it is not evidence."""
    bad = [("Bip01 Pelvis", -1), ("Bip01 Spine", 4), ("a", 0), ("b", 0), ("c", 0)]
    results = {r.identity.name: r for r in identities.check(tr_skl, make_skl(bad))}
    # `bone table fits` still holds - a scattered table is the right SIZE - and that is the
    # point of having several: the one that speaks to ordering is the one that must object
    assert results["bone table fits"].held is True
    assert results["no forward parents"].held is not True, "a scattered parent table looked fine"
    assert results["exactly one root"].held is not True


def test_an_inverted_box_is_caught():
    data = make_dfm([("canteen", 3, (1.0, 1.0, 1.0, -1.0, -1.0, -1.0))])
    results = identities.check(tr_dfm, data)
    assert all(r.held is not True for r in results), "an inverted box looked fine"


def test_check_reports_a_raising_identity_as_a_failure():
    """A claim that explodes has stopped holding; it must not take the run down with it."""

    def boom(_data):
        raise ValueError("nope")

    class Fake:
        IDENTITIES = [identities.Identity("boom", "x == y", boom)]

    results = identities.check(Fake, b"")
    assert results[0].held is False
    assert "ValueError" in results[0].detail


def test_summarise_counts_the_three_outcomes():
    class Fake:
        IDENTITIES = [
            identities.Identity("a", "f", lambda d: (True, "")),
            identities.Identity("b", "f", lambda d: (False, "")),
            identities.Identity("c", "f", lambda d: (None, "")),
        ]

    assert identities.summarise(identities.check(Fake, b"")) == "1 hold, 1 failed, 1 skipped"
