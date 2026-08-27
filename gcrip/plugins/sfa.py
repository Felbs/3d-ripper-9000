"""Star Fox Adventures (GSAE01): every model in a ``MODELS.bin`` (offsets from the sibling
``MODELS.tab``) -> one Scene each.  Format details in gcrip.formats.sfa.

Skeleton: bones carry a local translation only (rest pose has no rotation); vertices drawn
through a bone's matrix slot are stored in that bone's space (moved to bind space here),
vertices on a coarse-blend slot are in bind space with two bone weights, and vertices on
matrix slot 9 of a model with fine (CPU) skinning are in bind space with the per-vertex
two-bone weights of their fine-skin piece.
Textures come from ``TEX1.bin/.tab`` next to the models, else the disc root's, else any
map's TEX1 that has the id.
"""

from __future__ import annotations

import numpy as np

from gcrip.formats import sfa
from gcrip.formats.j3d import triangulate
from ripcore.scene import Joint, MaterialDef, Primitive, Scene

NAME = "sfa"


def detect(path: str, head: bytes, size: int) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name == "models.bin" and size > 0x40 and sfa.looks_like_models_bin(head)


class _TextureBank:
    """TEX1 tables reachable from `src`, searched in order for a texture id."""

    def __init__(self, src, model_path: str) -> None:
        self.src = src
        self.files: list[tuple[str, str]] = []
        d = model_path.replace("\\", "/").rsplit("/", 1)[0] if "/" in model_path else ""
        cands = [f"{d}/TEX1" if d else "TEX1", "TEX1"]
        by_path = getattr(src, "by_path", None) or {}
        for p in by_path:
            pp = str(p).replace("\\", "/")
            if pp.lower().endswith("/tex1.tab"):
                cands.append(pp[:-4])
        seen: set[str] = set()
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            self.files.append((c + ".tab", c + ".bin"))
        self.loaded: dict[str, tuple[bytes, bytes] | None] = {}
        self.cache: dict[int, tuple[np.ndarray, sfa.Texture] | None] = {}

    def _file(self, tab_path: str, bin_path: str) -> tuple[bytes, bytes] | None:
        if tab_path not in self.loaded:
            try:
                self.loaded[tab_path] = (self.src.get(tab_path), self.src.get(bin_path))
            except Exception:  # noqa: BLE001 - missing sibling: try the next table
                self.loaded[tab_path] = None
        return self.loaded[tab_path]

    def get(self, tex_id: int) -> tuple[np.ndarray, sfa.Texture] | None:
        if tex_id in self.cache:
            return self.cache[tex_id]
        result = None
        for tab_path, bin_path in self.files:
            f = self._file(tab_path, bin_path)
            if f is None:
                continue
            frames = sfa.texture_entries(f[0], f[1], tex_id)
            if not frames:
                continue
            try:
                tex = sfa.parse_texture(sfa.unwrap(frames[0]))
                result = (sfa.decode_texture(tex), tex)
            except sfa.SFAError:
                continue
            break
        self.cache[tex_id] = result
        return result


FINE_SKIN_KEY = -2


def _fine_weights(model, pidx, sel, joints, weights, nj) -> None:
    """Per-vertex two-bone weights for CPU-skinned vertices, by position index."""
    if not model.fine_skins:
        return
    n_pos = len(model.positions)
    table = np.zeros((n_pos, 2), np.uint16)
    wtab = np.zeros((n_pos, 2), np.float32)
    wtab[:, 0] = 1.0
    for fs in model.fine_skins:
        table[fs.first_vertex : fs.first_vertex + fs.count] = (
            min(fs.bone0, nj - 1),
            min(fs.bone1, nj - 1),
        )
        wtab[fs.first_vertex : fs.first_vertex + fs.count] = fs.weights
    joints[sel, 0] = table[pidx[sel], 0]
    joints[sel, 1] = table[pidx[sel], 1]
    weights[sel, 0] = wtab[pidx[sel], 0]
    weights[sel, 1] = wtab[pidx[sel], 1]
    tot = weights[sel].sum(axis=1, keepdims=True)
    weights[sel] = np.where(tot > 0, weights[sel] / np.maximum(tot, 1e-6), weights[sel])


def _joint_world(model: sfa.Model) -> list[np.ndarray]:
    world: list[np.ndarray] = []
    for i, j in enumerate(model.joints):
        t = np.array(j.translation, np.float64)
        if j.parent != 0xFF and j.parent < i:
            t = t + world[j.parent]
        world.append(t)
    return world


def build_scene(model: sfa.Model, name: str, bank: _TextureBank | None) -> Scene:
    scene = Scene(name=name, warnings=list(model.warnings))
    world = _joint_world(model)
    nj = len(model.joints)
    for i, j in enumerate(model.joints):
        parent = j.parent if j.parent != 0xFF and j.parent < i else None
        translation = tuple(float(x) for x in j.translation)
        scene.joints.append(Joint(f"bone{i:02d}", parent, translation, (0, 0, 0, 1), (1, 1, 1)))  # type: ignore[arg-type]

    mat_index: dict[int, int] = {}

    def material_for(si: int) -> int:
        if si in mat_index:
            return mat_index[si]
        sh = model.shaders[si]
        tex = None
        wrap: dict = {}
        for layer in sh.layers:
            if 0 <= layer.texture < len(model.texture_ids):
                tid = model.texture_ids[layer.texture]
                key = f"tex{tid:04d}"
                if key not in scene.textures and bank is not None:
                    got = bank.get(tid)
                    if got is not None:
                        scene.textures[key] = got[0]
                        wrap = {
                            "clamp_u": got[1].wrap_s == 0,
                            "clamp_v": got[1].wrap_t == 0,
                            "mirror_u": got[1].wrap_s == 2,
                            "mirror_v": got[1].wrap_t == 2,
                        }
                    else:
                        scene.warnings.append(f"texture {tid} not found in any TEX1")
                tex = key
                break
        scene.materials.append(
            MaterialDef(
                name=f"shader{si:02d}" + (f"_{tex}" if tex else ""),
                texture=tex,
                double_sided=not (sh.flags & sfa.SHADER_FLAG_CULL_BACK),
                alpha_blend=bool(sh.flags & sfa.SHADER_FLAG_ALPHA_COMPARE),
                unlit=bool(sh.flags & sfa.SHADER_FLAG_UNLIT),
                **wrap,
            )
        )
        mat_index[si] = len(scene.materials) - 1
        return mat_index[si]

    for di, draw in enumerate(model.draws):
        if draw.shader >= len(model.shaders):
            scene.warnings.append(f"draw {di}: shader {draw.shader} out of range")
            continue
        shader = model.shaders[draw.shader]
        if shader.flags & sfa.SHADER_FLAG_HIDDEN:
            continue
        try:
            prims = sfa.parse_display_list(draw)
        except sfa.SFAError as ex:
            scene.warnings.append(f"draw {di}: {ex}")
            continue
        keys_list, tri_list, base = [], [], 0
        vats = []
        for op, vat, arr in prims:
            n = len(arr)
            names = arr.dtype.names or ()
            if "d0" in names:
                slot = np.clip(arr["d0"].astype(np.int64) // 3, 0, 9)
                mk = np.array(draw.matrix_map)[slot]
                if model.fine_skins:
                    # slot 9 = vertices skinned on the CPU: already in bind space
                    mk = np.where(slot == 9, FINE_SKIN_KEY, mk)
            else:
                mk = np.full(n, 0 if nj else -1, np.int64)
            cols = [mk]
            for f in ("pos", "nrm", "clr", "tex0"):
                cols.append(arr[f].astype(np.int64) if f in names else np.full(n, -1))
            keys_list.append(np.stack(cols, 1))
            tris = triangulate(op, n)
            if len(tris):
                tri_list.append(tris + base)
            base += n
            vats.append(vat)
        if not keys_list or not tri_list:
            continue
        keys = np.concatenate(keys_list)
        tris = np.concatenate(tri_list)
        uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
        indices = inverse.reshape(-1)[tris].reshape(-1).astype(np.uint32)
        nv = len(uniq)
        vat = vats[0]
        pidx = np.minimum(uniq[:, 1], max(len(model.positions) - 1, 0))
        positions = sfa.scale_positions(model.positions[pidx], vat).astype(np.float64)
        normals = None
        if (uniq[:, 2] >= 0).all() and len(model.normals):
            nidx = np.minimum(uniq[:, 2], len(model.normals) - 1)
            normals = model.normals[nidx].astype(np.float32) / 64.0
        colors = None
        if (uniq[:, 3] >= 0).all() and len(model.colors):
            cidx = np.minimum(uniq[:, 3], len(model.colors) - 1)
            colors = sfa.rgba4_to_float(model.colors[cidx])
        uvs = None
        if (uniq[:, 4] >= 0).all() and len(model.texcoords):
            tidx = np.minimum(uniq[:, 4], len(model.texcoords) - 1)
            uvs = sfa.scale_texcoords(model.texcoords[tidx], vat)
        joints = weights = None
        if nj:
            joints = np.zeros((nv, 4), np.uint16)
            weights = np.zeros((nv, 4), np.float32)
            weights[:, 0] = 1.0
            for mk in np.unique(uniq[:, 0]):
                sel = uniq[:, 0] == mk
                if mk == FINE_SKIN_KEY:
                    _fine_weights(model, pidx, sel, joints, weights, nj)
                elif mk < nj:
                    positions[sel] += world[mk]
                    joints[sel, 0] = mk
                else:
                    bi = int(mk) - nj
                    if bi >= len(model.blends):
                        scene.warnings.append(f"draw {di}: blend {bi} out of range")
                        continue
                    b = model.blends[bi]
                    joints[sel, 0] = min(b.joint0, nj - 1)
                    joints[sel, 1] = min(b.joint1, nj - 1)
                    weights[sel, 0] = b.weight0
                    weights[sel, 1] = 1.0 - b.weight0
        scene.primitives.append(
            Primitive(
                material=material_for(draw.shader),
                positions=positions.astype(np.float32),
                indices=indices,
                normals=normals,
                uvs=uvs,
                colors=colors,
                joints=joints,
                weights=weights,
            )
        )
    scene.extras = {"format": "sfa_model", "texture_ids": list(model.texture_ids)}
    return scene


def extract(data: bytes, path: str, src) -> list[Scene]:
    norm = path.replace("\\", "/")
    tab_path = norm[: -len("MODELS.bin")] + "MODELS.tab"
    if norm.lower().endswith("models.bin"):
        tab_path = norm[:-4] + ".tab"
    try:
        tab = sfa.read_tab(src.get(tab_path))
    except Exception as ex:  # noqa: BLE001
        raise sfa.SFAError(f"no MODELS.tab next to {path}: {ex}") from ex
    bank = _TextureBank(src, norm)
    scenes = []
    for i, entry in enumerate(tab):
        if entry >> 24 != 0x10:
            continue
        off = entry & 0xFFFFFF
        if off >= len(data):
            continue
        try:
            raw = sfa.unwrap(data[off:])
            model = sfa.parse_model(raw)
            scene = build_scene(model, f"model{i:04d}", bank)
        except sfa.SFAError as ex:
            scene = Scene(name=f"model{i:04d}", warnings=[f"model {i}: {ex}"])
        if scene.primitives:
            scenes.append(scene)
    return scenes
