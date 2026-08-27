"""The engine-neutral scene that dcrip's parsers produce and its glTF writer consumes:
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
    double_sided: bool = False
    clamp_u: bool = False
    clamp_v: bool = False
    mirror_u: bool = False
    mirror_v: bool = False
    unlit: bool = False


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
