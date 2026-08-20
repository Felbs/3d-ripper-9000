"""Merge many ripped .gltf models into one level glTF with placed instances.

Each unique model is imported once (geometry buffers appended to a single .bin,
indices rebased); every placement becomes a node that reuses the imported meshes.

Default mode is **flattened**: each model's node transforms are baked into its vertex
positions (bind pose) and all primitives are combined into ONE mesh, so an instance is
a single node - no armatures, no empties. A level with 2,000 placements imports into
Blender in seconds instead of an armature-per-NPC crawl. Pass flatten=False to keep the
full node trees and skins instead (each skinned instance then gets its own joints+skin
sharing the inverse-bind-matrix accessor, because shared joints would draw every
instance in the same spot).

Expression variant meshes (hidden KHR_node_visibility clones) are stripped: a level
wants one visible copy of each model, not its face library. Animations are not
carried over either.
"""

from __future__ import annotations

import copy
import json
import math
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_LISTS = (
    "nodes",
    "meshes",
    "materials",
    "textures",
    "images",
    "samplers",
    "accessors",
    "bufferViews",
    "skins",
)


@dataclass
class _Template:
    roots: list[int]  # node indices (in the merged doc) of the model's scene roots
    nodes: list[int]  # every node index the model brought in
    skins: list[int]  # skin indices used
    mesh: int | None = None  # flattened mode: the one combined mesh
    bounds: tuple | None = None  # flattened mode: (min3, max3) of baked positions
    triangles: int = 0
    instances: int = 0


@dataclass
class LevelStats:
    models: int = 0
    instances: int = 0
    nodes: int = 0
    triangles: int = 0
    by_model: dict[str, int] = field(default_factory=dict)


class LevelBuilder:
    """Accumulates models + placements, then writes <out>.gltf + <out>.bin."""

    def __init__(self, out_path: Path, *, flatten: bool = True):
        self.out_path = Path(out_path)
        self.flatten = flatten
        self.bin = bytearray()
        self.doc: dict = {
            "asset": {"version": "2.0", "generator": "gcrip stage"},
            "scene": 0,
            "scenes": [{"name": self.out_path.stem, "nodes": []}],
        }
        for k in _LISTS:
            self.doc[k] = []
        self._templates: dict[Path, _Template | None] = {}
        self._groups: dict[str, int] = {}  # group name -> node index
        self._instances: list[int] = []  # instance node indices (for recenter)
        self._bmin = np.full(3, np.inf)  # world bounds over all instances
        self._bmax = np.full(3, -np.inf)
        self.stats = LevelStats()

    # -- template import ---------------------------------------------------

    def _load(self, gltf_path: Path) -> _Template | None:
        gltf_path = Path(gltf_path)
        if gltf_path in self._templates:
            return self._templates[gltf_path]
        try:
            src = json.loads(gltf_path.read_text(encoding="utf-8"))
            buffers = src.get("buffers", [])
            blob = b""
            if buffers:
                blob = (gltf_path.parent / buffers[0]["uri"]).read_bytes()
        except (OSError, ValueError, KeyError) as e:
            raise ValueError(f"cannot load {gltf_path}: {e}") from e
        tpl = self._merge(src, blob, gltf_path.parent)
        self._templates[gltf_path] = tpl
        self.stats.models += 1
        return tpl

    def _merge(self, src: dict, blob: bytes, src_dir: Path) -> _Template | None:
        doc = self.doc
        # drop hidden variant/expression clones before rebasing
        drop = {
            i
            for i, n in enumerate(src.get("nodes", []))
            if n.get("extensions", {}).get("KHR_node_visibility", {}).get("visible") is False
        }
        node_map: dict[int, int] = {}
        kept = [i for i in range(len(src.get("nodes", []))) if i not in drop]
        if not kept:
            return None

        base = {k: len(doc[k]) for k in _LISTS}
        while len(self.bin) % 4:
            self.bin.append(0)
        byte_base = len(self.bin)
        self.bin += blob

        for bv in src.get("bufferViews", []):
            bv = dict(bv)
            bv["buffer"] = 0
            bv["byteOffset"] = bv.get("byteOffset", 0) + byte_base
            doc["bufferViews"].append(bv)
        for acc in src.get("accessors", []):
            acc = dict(acc)
            if "bufferView" in acc:
                acc["bufferView"] += base["bufferViews"]
            doc["accessors"].append(acc)
        out_dir = self.out_path.parent.resolve()
        for img in src.get("images", []):
            img = dict(img)
            if "uri" in img:
                abs_png = (src_dir / img["uri"]).resolve()
                img["uri"] = os.path.relpath(abs_png, out_dir).replace(os.sep, "/")
            doc["images"].append(img)
        for smp in src.get("samplers", []):
            doc["samplers"].append(dict(smp))
        for tex in src.get("textures", []):
            tex = dict(tex)
            if "source" in tex:
                tex["source"] += base["images"]
            if "sampler" in tex:
                tex["sampler"] += base["samplers"]
            doc["textures"].append(tex)
        for mat in src.get("materials", []):
            mat = copy.deepcopy(mat)
            _bump_texture_indices(mat, base["textures"])
            doc["materials"].append(mat)

        if self.flatten:
            return self._merge_flat(src, blob, kept, base)

        tris = 0
        mesh_map: dict[int, int] = {}
        used_meshes = sorted(
            {src["nodes"][i]["mesh"] for i in kept if "mesh" in src["nodes"][i]}
        )
        for mi in used_meshes:
            mesh = copy.deepcopy(src["meshes"][mi])
            for prim in mesh.get("primitives", []):
                prim.get("extensions", {}).pop("KHR_materials_variants", None)
                if not prim.get("extensions"):
                    prim.pop("extensions", None)
                for k in prim.get("attributes", {}):
                    prim["attributes"][k] += base["accessors"]
                if "indices" in prim:
                    acc = src["accessors"][prim["indices"]]
                    tris += acc.get("count", 0) // 3
                    prim["indices"] += base["accessors"]
                if "material" in prim:
                    prim["material"] += base["materials"]
            mesh_map[mi] = len(doc["meshes"])
            doc["meshes"].append(mesh)

        for new, old in enumerate(kept):
            node_map[old] = base["nodes"] + new
        skin_map: dict[int, int] = {}
        used_skins = sorted(
            {src["nodes"][i]["skin"] for i in kept if "skin" in src["nodes"][i]}
        )
        for si in used_skins:
            skin = copy.deepcopy(src["skins"][si])
            if "inverseBindMatrices" in skin:
                skin["inverseBindMatrices"] += base["accessors"]
            skin["joints"] = [node_map[j] for j in skin["joints"] if j in node_map]
            if "skeleton" in skin:
                skin["skeleton"] = node_map.get(skin["skeleton"], skin["joints"][0])
            skin_map[si] = len(doc["skins"])
            doc["skins"].append(skin)

        for old in kept:
            n = copy.deepcopy(src["nodes"][old])
            n.pop("extensions", None)
            if "children" in n:
                n["children"] = [node_map[c] for c in n["children"] if c in node_map]
                if not n["children"]:
                    n.pop("children")
            if "mesh" in n:
                n["mesh"] = mesh_map[n["mesh"]]
            if "skin" in n:
                n["skin"] = skin_map[n["skin"]]
            doc["nodes"].append(n)

        scene_nodes = src.get("scenes", [{}])[src.get("scene", 0)].get("nodes", [])
        roots = [node_map[r] for r in scene_nodes if r in node_map]
        return _Template(
            roots=roots,
            nodes=[node_map[i] for i in kept],
            skins=list(skin_map.values()),
            triangles=tris,
        )

    # -- flattened templates -------------------------------------------------

    def _merge_flat(self, src: dict, blob: bytes, kept: list[int], base: dict) -> _Template | None:
        """Bake every mesh node's world transform (bind pose) into its vertices and
        combine all primitives into one mesh; drop skins/joints entirely. Vertices of
        skinned primitives are already model-space, so with joints at bind pose the
        node's world matrix is all that's needed."""
        worlds = _world_matrices(src)
        prims_out: list[dict] = []
        tris = 0
        bmin = np.full(3, np.inf)
        bmax = np.full(3, -np.inf)
        for ni in kept:
            node = src["nodes"][ni]
            if "mesh" not in node:
                continue
            m = worlds[ni]
            skinned = "skin" in node
            for prim in src["meshes"][node["mesh"]].get("primitives", []):
                p = copy.deepcopy(prim)
                p.get("extensions", {}).pop("KHR_materials_variants", None)
                if not p.get("extensions"):
                    p.pop("extensions", None)
                attrs = p.get("attributes", {})
                for k in list(attrs):
                    if k.startswith(("JOINTS", "WEIGHTS")):
                        del attrs[k]
                    else:
                        attrs[k] += base["accessors"]
                # skinned meshes: model space already; static meshes: bake node world
                mat = np.eye(4) if skinned else m
                if "POSITION" in prim.get("attributes", {}):
                    pos = _read_vec3(src, blob, prim["attributes"]["POSITION"])
                    w = pos @ mat[:3, :3].T + mat[:3, 3]
                    if len(w):
                        bmin = np.minimum(bmin, w.min(0))
                        bmax = np.maximum(bmax, w.max(0))
                    attrs["POSITION"] = self._push_vec3(w, with_bounds=True)
                if "NORMAL" in prim.get("attributes", {}):
                    nrm = _read_vec3(src, blob, prim["attributes"]["NORMAL"])
                    lin = np.linalg.inv(mat[:3, :3]).T
                    n2 = nrm @ lin.T
                    n2 /= np.maximum(np.linalg.norm(n2, axis=1, keepdims=True), 1e-12)
                    attrs["NORMAL"] = self._push_vec3(n2)
                if "indices" in p:
                    tris += src["accessors"][prim["indices"]].get("count", 0) // 3
                    p["indices"] += base["accessors"]
                if "material" in p:
                    p["material"] += base["materials"]
                prims_out.append(p)
        if not prims_out:
            return None
        mesh_idx = len(self.doc["meshes"])
        self.doc["meshes"].append({"primitives": prims_out})
        bounds = (bmin, bmax) if np.isfinite(bmin).all() else None
        return _Template(
            roots=[], nodes=[], skins=[], mesh=mesh_idx, bounds=bounds, triangles=tris
        )

    def _push_vec3(self, arr: np.ndarray, *, with_bounds: bool = False) -> int:
        data = np.ascontiguousarray(arr, dtype="<f4")
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin += data.tobytes()
        bv_idx = len(self.doc["bufferViews"])
        self.doc["bufferViews"].append(
            {"buffer": 0, "byteOffset": off, "byteLength": data.nbytes, "target": 34962}
        )
        acc: dict = {
            "bufferView": bv_idx,
            "componentType": 5126,
            "count": len(data),
            "type": "VEC3",
        }
        if with_bounds:
            acc["min"] = [float(x) for x in data.min(0)]
            acc["max"] = [float(x) for x in data.max(0)]
        idx = len(self.doc["accessors"])
        self.doc["accessors"].append(acc)
        return idx

    # -- instancing ----------------------------------------------------------

    def _clone(self, tpl: _Template) -> list[int]:
        """Copy a template's node subtree (sharing meshes/materials) -> new root ids."""
        doc = self.doc
        remap = {old: len(doc["nodes"]) + k for k, old in enumerate(tpl.nodes)}
        for old in tpl.nodes:
            n = copy.deepcopy(doc["nodes"][old])
            if "children" in n:
                n["children"] = [remap[c] for c in n["children"] if c in remap]
            doc["nodes"].append(n)
        for si in tpl.skins:
            skin = copy.deepcopy(doc["skins"][si])
            skin["joints"] = [remap.get(j, j) for j in skin["joints"]]
            if "skeleton" in skin:
                skin["skeleton"] = remap.get(skin["skeleton"], skin["skeleton"])
            new_si = len(doc["skins"])
            doc["skins"].append(skin)
            for old in tpl.nodes:  # retarget cloned mesh nodes to the cloned skin
                nn = doc["nodes"][remap[old]]
                if nn.get("skin") == si:
                    nn["skin"] = new_si
        return [remap[r] for r in tpl.roots]

    def add_instance(
        self,
        gltf_path: Path,
        name: str,
        *,
        translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rot_y_deg: float = 0.0,
        scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
        group: str | None = None,
    ) -> bool:
        tpl = self._load(gltf_path)
        if tpl is None:
            return False
        node: dict = {"name": name}
        if tpl.mesh is not None:  # flattened: the instance node carries the mesh itself
            node["mesh"] = tpl.mesh
        else:
            node["children"] = self._clone(tpl) if tpl.instances else list(tpl.roots)
        tpl.instances += 1
        if any(translation):
            node["translation"] = list(translation)
        if rot_y_deg:
            h = math.radians(rot_y_deg) / 2.0
            node["rotation"] = [0.0, math.sin(h), 0.0, math.cos(h)]
        if scale != (1.0, 1.0, 1.0):
            node["scale"] = list(scale)
        idx = len(self.doc["nodes"])
        self.doc["nodes"].append(node)
        self._attach(idx, group)
        self._instances.append(idx)
        if tpl.bounds is not None:
            mn, mx = tpl.bounds
            corners = np.array([[x, y, z] for x in (mn[0], mx[0])
                                for y in (mn[1], mx[1]) for z in (mn[2], mx[2])])
            corners *= scale
            if rot_y_deg:
                a = math.radians(rot_y_deg)
                c, s = math.cos(a), math.sin(a)
                x, z = corners[:, 0].copy(), corners[:, 2].copy()
                corners[:, 0] = c * x + s * z
                corners[:, 2] = -s * x + c * z
            corners += translation
            self._bmin = np.minimum(self._bmin, corners.min(0))
            self._bmax = np.maximum(self._bmax, corners.max(0))
        self.stats.instances += 1
        key = gltf_path.stem
        self.stats.by_model[key] = self.stats.by_model.get(key, 0) + 1
        self.stats.triangles += tpl.triangles
        return True

    def _attach(self, node_idx: int, group: str | None) -> None:
        scene = self.doc["scenes"][0]["nodes"]
        if group is None:
            scene.append(node_idx)
            return
        gi = self._groups.get(group)
        if gi is None:
            gi = len(self.doc["nodes"])
            self.doc["nodes"].append({"name": group, "children": []})
            self._groups[group] = gi
            scene.append(gi)
        self.doc["nodes"][gi]["children"].append(node_idx)

    # -- output ----------------------------------------------------------------

    def recenter(self) -> tuple[float, float, float]:
        """Shift every instance so the level's footprint is centred at the origin
        (X/Z only - sea level stays at Y=0). Returns the world offset that was
        subtracted, also stored in the scene extras as gcrip_world_offset."""
        if not np.isfinite(self._bmin).all():
            return (0.0, 0.0, 0.0)
        cx = float((self._bmin[0] + self._bmax[0]) / 2)
        cz = float((self._bmin[2] + self._bmax[2]) / 2)
        if abs(cx) < 1.0 and abs(cz) < 1.0:
            return (0.0, 0.0, 0.0)
        for idx in self._instances:
            n = self.doc["nodes"][idx]
            t = n.get("translation", [0.0, 0.0, 0.0])
            n["translation"] = [t[0] - cx, t[1], t[2] - cz]
            if n["translation"] == [0.0, 0.0, 0.0]:
                n.pop("translation")
        self._bmin[0] -= cx
        self._bmax[0] -= cx
        self._bmin[2] -= cz
        self._bmax[2] -= cz
        self.doc["scenes"][0].setdefault("extras", {})["gcrip_world_offset"] = [cx, 0.0, cz]
        return (cx, 0.0, cz)

    def save(self) -> Path:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        bin_name = self.out_path.stem + ".bin"
        (self.out_path.parent / bin_name).write_bytes(self.bin)
        self.doc["buffers"] = [{"uri": bin_name, "byteLength": len(self.bin)}]
        for k in _LISTS:
            if not self.doc[k]:
                del self.doc[k]
        self.stats.nodes = len(self.doc.get("nodes", []))
        self.out_path.write_text(json.dumps(self.doc), encoding="utf-8")
        return self.out_path


def _trs_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in node:
        m = np.diag(list(node["scale"]) + [1.0]) @ m
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        r = np.eye(4)
        r[:3, :3] = [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
        m = r @ m
    if "translation" in node:
        t = np.eye(4)
        t[:3, 3] = node["translation"]
        m = t @ m
    return m


def _world_matrices(src: dict) -> list[np.ndarray]:
    nodes = src.get("nodes", [])
    worlds = [np.eye(4) for _ in nodes]
    seen = [False] * len(nodes)

    def walk(ni: int, parent: np.ndarray) -> None:
        if seen[ni]:
            return
        seen[ni] = True
        worlds[ni] = parent @ _trs_matrix(nodes[ni])
        for c in nodes[ni].get("children", []):
            walk(c, worlds[ni])

    for r in src.get("scenes", [{}])[src.get("scene", 0)].get("nodes", []):
        walk(r, np.eye(4))
    for ni in range(len(nodes)):  # orphans (shouldn't happen): treat as roots
        if not seen[ni]:
            walk(ni, np.eye(4))
    return worlds


_CTYPES = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}


def _read_vec3(src: dict, blob: bytes, acc_idx: int) -> np.ndarray:
    a = src["accessors"][acc_idx]
    bv = src["bufferViews"][a["bufferView"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    count = a["count"]
    fmt = _CTYPES[a["componentType"]]
    item = struct.calcsize(fmt) * 3
    stride = bv.get("byteStride") or item
    if stride == item:
        arr = np.frombuffer(blob, f"<{fmt}", count * 3, off).reshape(count, 3)
    else:
        raw = np.frombuffer(blob, np.uint8, count * stride, off).reshape(count, stride)
        arr = raw[:, :item].copy().view(f"<{fmt}")
    arr = arr.astype(np.float64)
    if a.get("normalized"):
        arr /= np.iinfo(np.dtype(fmt)).max
    return arr


def _bump_texture_indices(obj, base: int) -> None:
    """Bump every {'index': n} texture reference in a material by `base`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("Texture") and isinstance(v, dict) and "index" in v:
                v["index"] += base
            else:
                _bump_texture_indices(v, base)
    elif isinstance(obj, list):
        for v in obj:
            _bump_texture_indices(v, base)
