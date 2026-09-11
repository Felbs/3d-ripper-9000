"""The engine-neutral scene that the format parsers produce and its glTF writer consumes:
joints (a hierarchy with rest TRS), one skinned mesh split into per-material primitives,
materials that name a texture, decoded RGBA textures, and sampled animation clips."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Joint:
    name: str
    parent: int | None
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]  # quaternion x y z w
    scale: tuple[float, float, float]


@dataclass
class MaterialDef:
    name: str
    texture: str | None  # key into Scene.textures
    base_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    alpha_blend: bool = False
    #: "OPAQUE" | "MASK" | "BLEND".  MASK is the N64's alpha-test: hair, fences, fabric and
    #: cut-out detail are authored as a texture with holes, and exporting them OPAQUE fills
    #: the holes in - which reads as stray plates and phantom jewellery on a character.
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    double_sided: bool = False
    clamp_u: bool = False
    clamp_v: bool = False
    mirror_u: bool = False
    mirror_v: bool = False
    unlit: bool = False
    #: The second cycle's tile, when the colour combiner samples TEXEL1 - a key into
    #: Scene.textures, like `texture`.  glTF's metallic-roughness model has nowhere to put a
    #: second diffuse tile, so it rides along as an extra image and an `extras` entry rather
    #: than being blended away or dropped.  See n64rip/zobj.py.
    detail_texture: str | None = None
    #: which register weights the blend between the two, by name, or None when the object's
    #: own display list never says - the actor writes it at draw time.
    detail_blend: str | None = None


@dataclass
class Primitive:
    material: int
    positions: np.ndarray  # (N,3) f32
    indices: np.ndarray  # (M,) u32, triangles
    normals: np.ndarray | None = None  # (N,3)
    uvs: np.ndarray | None = None  # (N,2)
    colors: np.ndarray | None = None  # (N,4)
    joints: np.ndarray | None = None  # (N,4) u16
    weights: np.ndarray | None = None  # (N,4) f32
    #: An alternate of another primitive, differing only in its texture - a character's other
    #: expressions.  Exported as its own node so a rigger can switch between them; the name is
    #: the material it stands in for, which is what the Blender add-on groups on.
    variant_of: str | None = None
    variant_texture: str | None = None


@dataclass
class Clip:
    name: str
    frames: int
    fps: float
    # joint index -> (F,3) translations / (F,4) quaternions / (F,3) scales, or absent
    translation: dict[int, np.ndarray] = field(default_factory=dict)
    rotation: dict[int, np.ndarray] = field(default_factory=dict)
    scale: dict[int, np.ndarray] = field(default_factory=dict)
    loop: bool = True


@dataclass
class Scene:
    name: str
    joints: list[Joint] = field(default_factory=list)
    materials: list[MaterialDef] = field(default_factory=list)
    primitives: list[Primitive] = field(default_factory=list)
    textures: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (h,w,4) u8
    clips: list[Clip] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)

    @property
    def triangles(self) -> int:
        return sum(len(p.indices) // 3 for p in self.primitives)

    @property
    def vertices(self) -> int:
        return sum(len(p.positions) for p in self.primitives)
