"""`Primitive.material` is an INDEX into `scene.materials`, not a name and not a flag.

`material=-1` against an empty materials list is an `IndexError` at export, not "no material".
That single mistake has now cost four plugins their output: `wart_bmsh` (5,651 meshes on
Animaniacs), `res` (62,640), `xmdl` (**6,273 on Home Run King - the largest single failure count
in the library**), `mdgc` (947 on Superman) and `skx` (193 on Darkened Skye).

The per-plugin tests did not catch it because they check the reader, not the export contract.
This one checks the contract itself, across every registered plugin, so the next plugin to make
the mistake fails here rather than on a disc.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PLUGINS = sorted(pathlib.Path("gcrip/plugins").glob("*.py"))


def _material_args(tree: ast.AST) -> list[ast.expr]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Primitive":
            for kw in node.keywords:
                if kw.arg == "material":
                    out.append(kw.value)
    return out


@pytest.mark.parametrize("path", PLUGINS, ids=lambda p: p.name)
def test_no_plugin_passes_a_negative_material_index(path):
    """A literal -1 is always wrong: there is no materials list it can index."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for arg in _material_args(tree):
        if isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
            operand = arg.operand
            assert not (isinstance(operand, ast.Constant) and operand.value == 1), (
                f"{path.name} passes material=-1; it must index a real entry in "
                f"scene.materials (see this module's docstring)"
            )


@pytest.mark.parametrize("path", PLUGINS, ids=lambda p: p.name)
def test_material_is_never_a_string(path):
    """It is an index, so a name is wrong too - that is what broke wart_bmsh and ea_obg."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for arg in _material_args(tree):
        assert not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)), (
            f"{path.name} passes a material NAME; Primitive.material is an index"
        )


def test_a_plugin_using_index_zero_also_creates_a_material():
    """Every plugin that passes a constant index must populate scene.materials somewhere."""
    offenders = []
    for path in PLUGINS:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        args = _material_args(tree)
        constants = [a for a in args if isinstance(a, ast.Constant) and a.value == 0]
        if constants and "MaterialDef" not in src:
            offenders.append(path.name)
    assert offenders == [], f"pass material=0 but never build a MaterialDef: {offenders}"
