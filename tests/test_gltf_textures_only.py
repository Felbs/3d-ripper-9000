"""A textures-only Scene must still write its images.

Thirteen plugins build a Scene that carries textures and no materials at all - every texture
format that is not attached to geometry.  The exporter only ever wrote the textures some
material named, so all of those decoded correctly and wrote nothing, silently: no warning, an
empty ``_tex`` folder and a glTF with an empty ``images`` array.
"""

import tempfile
from pathlib import Path

import numpy as np

from ripcore import gltf
from ripcore.scene import MaterialDef, Scene


def image(r=255):
    img = np.zeros((8, 8, 4), np.uint8)
    img[..., 0] = r
    img[..., 3] = 255
    return img


def export(scene):
    with tempfile.TemporaryDirectory() as d:
        stats = gltf.export(scene, Path(d) / "t", thumbnail=False)
        return stats, sorted(p.name for p in Path(d).rglob("*.png"))


def test_a_scene_with_no_materials_still_writes_every_texture():
    scene = Scene(name="t")
    scene.textures = {"car": image(), "wheel": image(128)}
    scene.extras = {"textures_only": True}
    stats, pngs = export(scene)
    assert stats.textures == 2
    assert pngs == ["car.png", "wheel.png"]


def test_a_scene_whose_materials_name_textures_keeps_the_narrower_set():
    """Materials still decide when there are any - an unreferenced texture is not dragged in
    alongside the ones a model actually uses."""
    scene = Scene(name="t")
    scene.textures = {"car": image(), "unused": image(9)}
    scene.materials = [MaterialDef(name="a", texture="car")]
    stats, pngs = export(scene)
    assert stats.textures == 1
    assert pngs == ["car.png"]


def test_a_scene_with_neither_writes_nothing():
    stats, pngs = export(Scene(name="t"))
    assert stats.textures == 0 and pngs == []
