"""The oracle registry: what can tell a correct read from a wrong one, and what cannot.

Four oracles were tried on the Climax `.bad` codec and every one proved incapable of
distinguishing a good decode from a bad one.  Recording that is worth more than the decoder
variants were, but only if the reason travels with the verdict - "we tried that" is useless on
its own.
"""

from __future__ import annotations

import pytest

from gcrip import oracles


def test_every_oracle_states_its_evidence():
    """A grade without evidence is an opinion."""
    for o in oracles.ORACLES:
        assert o.asks, f"{o.name} does not say what it asks of the data"
        assert len(o.evidence) > 80, f"{o.name} grades itself {o.grade} without saying why"
        assert o.grade in (oracles.PROVEN, oracles.WEAK, oracles.DISCREDITED)


def test_discredited_oracles_record_how_they_failed():
    """The whole point: the next attempt must not re-run these hoping for a different answer."""
    bad = oracles.by_grade(oracles.DISCREDITED)
    assert {o.name for o in bad} == {
        "printable text",
        "input fully consumed",
        "box containment for quantised vertices",
        "quantised axis uses its full range",
        "decoder stopped at the declared length",
        "triangle locality over a candidate position array",
    }
    for o in bad:
        assert any(
            w in o.evidence
            for w in ("wrong", "meaningless", "nothing else", "vacuous", "passes on noise")
        ), (
            f"{o.name} is marked discredited but does not say what it failed to distinguish"
        )


def test_the_proven_set_includes_the_one_that_cracked_a_codec():
    proven = {o.name for o in oracles.by_grade(oracles.PROVEN)}
    assert "known plaintext" in proven
    assert "size identity" in proven
    assert oracles.find("known plaintext").evidence.count("47,114") == 1


def test_weak_oracles_are_not_presented_as_proof():
    for o in oracles.by_grade(oracles.WEAK):
        assert any(
            w in o.evidence.lower()
            for w in ("never conclusive", "not a proof", "invalid as a search", "suggestive")
        ), f"{o.name} is graded weak but its evidence does not say what it cannot do"


@pytest.mark.parametrize("name", ["size identity", "printable text", "known plaintext"])
def test_find_returns_the_named_oracle(name):
    assert oracles.find(name) is not None
    assert oracles.find("no such oracle") is None
