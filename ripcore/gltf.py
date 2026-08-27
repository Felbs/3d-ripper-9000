"""Scene -> glTF 2.0 (.gltf + .bin + _tex/*.png), one skinned mesh over a joint hierarchy,
animation clips as per-frame LINEAR samplers. Same output conventions as gcrip so the
Blender add-on and the report treat both modules' files alike."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from gcrip.export import png, thumb
from ripcore.scene import Scene

FLOAT, USHORT, UINT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


@dataclass
class ExportStats:
    triangles: int = 0
    vertices: int = 0
    joints: int = 0
    materials: int = 0
    textures: int = 0
    clips: int = 0
    texture_files: list[str] = field(default_factory=list)
    clip_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # for thumbnails
    positions: np.ndarray | None = None
    triangles_arr: np.ndarray | None = None
    tri_material: np.ndarray | None = None
    uvs: np.ndarray | None = None
    material_textures: list[np.ndarray | None] = field(default_factory=list)
    material_colors: list[tuple[float, float, float]] = field(default_factory=list)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "tex"


class _Buffer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def add(self, arr, ctype, atype, target=None, minmax=False, normalized=False) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        raw = np.ascontiguousarray(arr).tobytes()
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        self.data += raw
        self.views.append(view)
        acc = {
            "bufferView": len(self.views) - 1,
            "componentType": ctype,
            "count": int(arr.shape[0]),
            "type": atype,
        }
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"] = [float(x) for x in np.atleast_1d(arr.min(axis=0))]
            acc["max"] = [float(x) for x in np.atleast_1d(arr.max(axis=0))]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _safe_inv(m: np.ndarray) -> np.ndarray:
    """Inverse bind matrix; a joint scaled to zero (hidden parts) gets a pseudo-inverse."""
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(m)


def _local(j) -> np.ndarray:
    m = np.eye(4)
    x, y, z, w = j.rotation
    r = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    m[:3, :3] = r @ np.diag(j.scale)
    m[:3, 3] = j.translation
    return m


def _sane_parents(scene: Scene) -> list[int | None]:
    """Parent indices that are in range, not self, and acyclic (others become roots)."""
    n = len(scene.joints)
    parents: list[int | None] = []
    for i, j in enumerate(scene.joints):
        p = j.parent
        parents.append(p if (p is not None and 0 <= p < n and p != i) else None)
    for i in range(n):  # break cycles
        seen = {i}
        p = parents[i]
        while p is not None:
            if p in seen:
                parents[i] = None
                break
            seen.add(p)
            p = parents[p]
    return parents


def _rest_world(scene: Scene) -> list[np.ndarray]:
    """World rest matrices in any joint order (parents may come after children)."""
    parents = _sane_parents(scene)
    local = [_local(j) for j in scene.joints]
    world: list[np.ndarray | None] = [None] * len(local)

    def get(i: int) -> np.ndarray:
        if world[i] is None:
            p = parents[i]
            world[i] = local[i] if p is None else get(p) @ local[i]
        return world[i]

    return [get(i) for i in range(len(local))]


def export(scene: Scene, out_base: Path, *, thumbnail: bool = True) -> ExportStats:
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    st = ExportStats(warnings=list(scene.warnings))
    buf = _Buffer()
    gltf: dict = {
        "asset": {"version": "2.0", "generator": "3D Ripper 9000 dcrip"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
    }

    # textures
    tex_dir = out_base.parent / f"{out_base.name}_tex"
    images, samplers, textures = [], [], []
    tex_slot: dict[str, int] = {}
    used = {m.texture for m in scene.materials if m.texture}
    for name in sorted(used):
        img = scene.textures.get(name)
        if img is None:
            st.warnings.append(f"texture {name!r} not found on disc")
            continue
        tex_dir.mkdir(parents=True, exist_ok=True)
        fn = f"{_safe(name)}.png"
        png.write_rgba(tex_dir / fn, img)
        st.texture_files.append(fn)
        images.append({"uri": f"{tex_dir.name}/{fn}"})
        tex_slot[name] = len(images) - 1
    st.textures = len(images)

    def sampler(m) -> int:
        wrap_s = 33071 if m.clamp_u else 33648 if m.mirror_u else 10497
        wrap_t = 33071 if m.clamp_v else 33648 if m.mirror_v else 10497
        s = {"magFilter": 9729, "minFilter": 9987, "wrapS": wrap_s, "wrapT": wrap_t}
        if s not in samplers:
            samplers.append(s)
        return samplers.index(s)

    for m in scene.materials:
        mat: dict = {
            "name": m.name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [float(c) for c in m.base_color],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "doubleSided": bool(m.double_sided),
        }
        if m.texture and m.texture in tex_slot:
            t = {"sampler": sampler(m), "source": tex_slot[m.texture]}
            if t not in textures:
                textures.append(t)
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": textures.index(t)}
            st.material_textures.append(scene.textures[m.texture])
        else:
            st.material_textures.append(None)
        st.material_colors.append(tuple(float(c) for c in m.base_color[:3]))
        if m.alpha_blend:
            mat["alphaMode"] = "BLEND"
        if m.unlit:
            mat["extensions"] = {"KHR_materials_unlit": {}}
        gltf["materials"].append(mat)
    st.materials = len(scene.materials)
    if images:
        gltf["images"] = images
        gltf["samplers"] = samplers
        gltf["textures"] = textures
    if any(m.unlit for m in scene.materials):
        gltf["extensionsUsed"] = ["KHR_materials_unlit"]

    # joints
    rest = _rest_world(scene)
    joint_nodes = []
    for j in scene.joints:
        node = {
            "name": j.name,
            "translation": [float(x) for x in j.translation],
            "rotation": [float(x) for x in j.rotation],
            "scale": [float(x) for x in j.scale],
        }
        gltf["nodes"].append(node)
        joint_nodes.append(len(gltf["nodes"]) - 1)
    parents = _sane_parents(scene)
    for p, ni in zip(parents, joint_nodes, strict=True):
        if p is not None:
            gltf["nodes"][joint_nodes[p]].setdefault("children", []).append(ni)
    roots = [ni for p, ni in zip(parents, joint_nodes, strict=True) if p is None]
    st.joints = len(scene.joints)

    # mesh
    prims = []
    all_pos, all_tri, all_mat, all_uv = [], [], [], []
    vbase = 0
    for p in scene.primitives:
        pos = p.positions.astype(np.float32)
        attrs = {"POSITION": buf.add(pos, FLOAT, "VEC3", ARRAY_BUFFER, True)}
        if p.normals is not None:
            n = p.normals.astype(np.float32)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            n = np.where(ln > 1e-6, n / np.maximum(ln, 1e-6), np.array([0, 0, 1], np.float32))
            attrs["NORMAL"] = buf.add(n, FLOAT, "VEC3", ARRAY_BUFFER)
        if p.uvs is not None:
            attrs["TEXCOORD_0"] = buf.add(p.uvs.astype(np.float32), FLOAT, "VEC2", ARRAY_BUFFER)
        if p.colors is not None:
            attrs["COLOR_0"] = buf.add(p.colors.astype(np.float32), FLOAT, "VEC4", ARRAY_BUFFER)
        if p.joints is not None and scene.joints:
            attrs["JOINTS_0"] = buf.add(p.joints.astype(np.uint16), USHORT, "VEC4", ARRAY_BUFFER)
            attrs["WEIGHTS_0"] = buf.add(p.weights.astype(np.float32), FLOAT, "VEC4", ARRAY_BUFFER)
        idx = p.indices.astype(np.uint32)
        prims.append(
            {
                "attributes": attrs,
                "indices": buf.add(idx, UINT, "SCALAR", ELEMENT_ARRAY_BUFFER),
                "material": p.material,
                "mode": 4,
            }
        )
        tri = idx.reshape(-1, 3)
        all_pos.append(p.positions)
        all_tri.append(tri + vbase)
        all_mat.append(np.full(len(tri), p.material, np.int32))
        all_uv.append(p.uvs if p.uvs is not None else np.zeros((len(p.positions), 2), np.float32))
        vbase += len(p.positions)
        st.triangles += len(tri)
        st.vertices += len(p.positions)
    gltf["meshes"].append({"name": scene.name, "primitives": prims})
    mesh_node = {"name": scene.name, "mesh": 0}
    if scene.joints:
        ibm = np.array([_safe_inv(m).T for m in rest], np.float32)  # column-major
        gltf["skins"] = [
            {
                "name": f"{scene.name}_skin",
                "joints": joint_nodes,
                "inverseBindMatrices": buf.add(ibm.reshape(len(ibm), 16), FLOAT, "MAT4"),
                "skeleton": roots[0] if roots else 0,
            }
        ]
        mesh_node["skin"] = 0
    gltf["nodes"].append(mesh_node)
    gltf["scenes"][0]["nodes"] = [*roots, len(gltf["nodes"]) - 1]

    # animations
    anims = []
    for clip in scene.clips:
        times = (np.arange(clip.frames, dtype=np.float32) / clip.fps).astype(np.float32)
        t_acc = buf.add(times, FLOAT, "SCALAR", None, True)
        samplers_a, channels = [], []
        for path, table, atype in (
            ("translation", clip.translation, "VEC3"),
            ("rotation", clip.rotation, "VEC4"),
            ("scale", clip.scale, "VEC3"),
        ):
            for ji, data in table.items():
                if ji >= len(joint_nodes):
                    continue
                samplers_a.append(
                    {
                        "input": t_acc,
                        "output": buf.add(data.astype(np.float32), FLOAT, atype),
                        "interpolation": "LINEAR",
                    }
                )
                channels.append(
                    {
                        "sampler": len(samplers_a) - 1,
                        "target": {"node": joint_nodes[ji], "path": path},
                    }
                )
        if channels:
            anims.append(
                {
                    "name": clip.name,
                    "samplers": samplers_a,
                    "channels": channels,
                    "extras": {
                        "gcrip_frames": clip.frames,
                        "gcrip_fps": clip.fps,
                        "gcrip_loop": clip.loop,
                    },
                }
            )
            st.clip_names.append(clip.name)
    if anims:
        gltf["animations"] = anims
    st.clips = len(anims)

    gltf["accessors"] = buf.accessors
    gltf["bufferViews"] = buf.views
    bin_name = f"{out_base.name}.bin"
    gltf["buffers"] = [{"byteLength": len(buf.data), "uri": bin_name}]
    if scene.extras:
        gltf["asset"]["extras"] = scene.extras
    (out_base.parent / bin_name).write_bytes(bytes(buf.data))
    out_base.with_suffix(".gltf").write_text(
        json.dumps(gltf, separators=(",", ":")), encoding="utf-8"
    )
    if all_pos:
        st.positions = np.concatenate(all_pos)
        st.triangles_arr = np.concatenate(all_tri)
        st.tri_material = np.concatenate(all_mat)
        st.uvs = np.concatenate(all_uv)
    return st


def thumbnail(st: ExportStats, out_base: Path, size: int = 256) -> Path | None:
    if st.positions is None or st.triangles_arr is None or len(st.triangles_arr) == 0:
        return None
    colors = np.array([st.material_colors[m] for m in st.tri_material], np.float64)
    tri_tex = np.array(
        [m if st.material_textures[m] is not None else -1 for m in st.tri_material], np.int32
    )
    img = thumb.render(
        st.positions,
        st.triangles_arr,
        colors,
        size=size,
        uvs=st.uvs,
        tri_texture=tri_tex,
        textures=st.material_textures,
    )
    out = out_base.parent / f"{out_base.name}_thumb.png"
    png.write_rgba(out, img)
    return out
