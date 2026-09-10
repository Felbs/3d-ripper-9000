"""An actor object file to a rigged ``ripcore.scene.Scene``.

The whole point of this module is the rig.  A Zelda actor draws by walking its limb tree with
a matrix stack, so if the display list for each limb is interpreted with that limb's world
matrix, and the vertices it produces are tagged with the limb index, what falls out is a
skinned mesh: one bone per limb, every vertex fully weighted to the bone that drew it.

That is *rigid* skinning - no smooth blending across a joint, which is how these models were
authored.  It is exactly what a retargeter needs: the bones move, the mesh follows.

Textures are resolved through the same segment table the display lists address, so a texture
living in the actor's own file is found, and one living in a shared bank (segment 4's
``gameplay_keep``, or a runtime segment written by actor code) is recorded as missing rather
than guessed at.
"""

from __future__ import annotations

import numpy as np

from n64rip import f3dex2, skeleton as skel_mod, texture as tex_mod
from ripcore.scene import Clip, Joint, MaterialDef, Primitive, Scene

#: N64 world units are large; glTF is metres.  Link is ~60 units tall, so this puts a
#: character at roughly human scale without changing any proportions.
SCALE = 0.01


def _translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _decode_tile(tile: f3dex2.TileState, segments: f3dex2.Segments) -> np.ndarray | None:
    """RGBA for a tile, or None when its texels are not reachable in a static rip."""
    if tile.addr is None or tile.width <= 0 or tile.height <= 0:
        return None
    found = segments.resolve(tile.addr)
    if found is None:
        return None
    data, off = found
    tlut = None
    if tile.fmt == tex_mod.FMT_CI:
        if tile.pal_addr is None:
            return None
        pal = segments.resolve(tile.pal_addr)
        if pal is None:
            return None
        pdata, poff = pal
        entries = 16 if tile.size == tex_mod.SIZE_4 else 256
        tlut = tex_mod.decode_tlut(pdata[poff:], entries)
    try:
        return tex_mod.decode(
            tile.fmt, tile.size, tile.width, tile.height,
            data[off:], tlut, tile.palette,
        )
    except tex_mod.TextureError:
        return None


def _quat_from_euler(xyz, order: str = "zyx") -> tuple[float, float, float, float]:
    """The joint's rest rotation as a quaternion, matching anim.rotation_matrix's order."""
    from n64rip.anim import rotation_matrix

    m = rotation_matrix(np.asarray(xyz, dtype=np.float64), order)[:3, :3]
    tr = m.trace()
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    return (float(x), float(y), float(z), float(w))


def build(
    name: str,
    data: bytes,
    skel: skel_mod.Skeleton,
    segments: f3dex2.Segments,
    clips: list[Clip] | None = None,
    world: dict[int, np.ndarray] | None = None,
    rotations: np.ndarray | None = None,
) -> Scene:
    """Walk *skel*'s limbs, interpret each limb's display list, and assemble one Scene.

    *world* supplies a posed set of limb matrices (see ``anim.pose_matrices``).  Without it
    the limbs are placed by their offsets alone, which is the un-posed rig: every chain
    extends along one axis, giving a character arms several times longer than its torso.
    *rotations* are the matching per-limb rest rotations, baked into the exported joints so
    the armature itself carries the pose rather than only the mesh.
    """
    scene = Scene(name=name)
    order = skel.order()

    # -- the armature: one joint per limb, translations relative to the parent
    for limb in skel.limbs:
        x, y, z = limb.translation
        quat = (0.0, 0.0, 0.0, 1.0)
        if rotations is not None and limb.index < len(rotations):
            quat = _quat_from_euler(rotations[limb.index])
        scene.joints.append(
            Joint(
                name=f"limb_{limb.index:02d}",
                parent=limb.parent,
                translation=(x * SCALE, y * SCALE, z * SCALE),
                rotation=quat,
                scale=(1.0, 1.0, 1.0),
            )
        )

    # -- world matrices, following the same walk the game does
    if world is None:
        world = {}
        for i in order:
            limb = skel.limbs[i]
            local = _translate(*limb.translation)
            parent = world.get(limb.parent) if limb.parent is not None else None
            world[i] = local if parent is None else parent @ local

    # -- the limb-matrix array the display lists reach through segment 0x0D.
    # A limb's list selects a matrix per vertex group with G_MTX 0x0d0000N0, where N indexes
    # the limbs that actually draw, in draw order.  The game fills this at draw time; leaving
    # it unbound is what made one limb's geometry arrive in two different spaces at once.
    drawing = [i for i in order if skel.limbs[i].dlist]
    matrix_index = {limb: n for n, limb in enumerate(drawing)}
    segments.set(0x0D, f3dex2.matrix_segment([world[i] for i in drawing]))

    # -- geometry, one interpreter run per limb that draws
    batches: list[f3dex2.Batch] = []
    unresolved: set[int] = set()
    for i in order:
        limb = skel.limbs[i]
        if not limb.dlist:
            continue
        res = f3dex2.run(limb.dlist, segments, world[i])
        unresolved |= res.unresolved
        for b in res.batches:
            b.limb = i
            batches.append(b)
        scene.warnings += res.warnings

    if not batches:
        scene.extras = {"format": "n64_zobj", "limbs": skel.count, "reason": "no geometry"}
        return scene

    # -- materials, one per distinct tile
    by_tile: dict[tuple, int] = {}
    missing = 0
    for b in batches:
        key = b.tile.key()
        if key in by_tile:
            continue
        rgba = _decode_tile(b.tile, segments)
        idx = len(scene.materials)
        if rgba is None:
            missing += 1
            scene.materials.append(
                MaterialDef(name=f"mat_{idx:02d}", texture=None, unlit=not b.lit)
            )
        else:
            tex_name = f"tex_{idx:02d}_{tex_mod.format_name(b.tile.fmt, b.tile.size)}"
            scene.textures[tex_name] = rgba
            scene.materials.append(
                MaterialDef(
                    name=f"mat_{idx:02d}",
                    texture=tex_name,
                    clamp_u=b.tile.clamp_s,
                    clamp_v=b.tile.clamp_t,
                    mirror_u=b.tile.mirror_s,
                    mirror_v=b.tile.mirror_t,
                    double_sided=not b.cull_back,
                    unlit=not b.lit,
                )
            )
        by_tile[key] = idx

    # -- primitives, merged per material so one bone-weighted mesh comes out
    for key, mat in by_tile.items():
        group = [b for b in batches if b.tile.key() == key]
        pos = np.concatenate([b.positions for b in group]) * SCALE
        uvs = np.concatenate([b.uvs for b in group])
        cols = np.concatenate([b.colors for b in group])
        has_normals = all(b.normals is not None for b in group)
        nrm = np.concatenate([b.normals for b in group]) if has_normals else None
        # every vertex is fully weighted to the limb whose display list drew it
        joints = np.zeros((len(pos), 4), dtype=np.uint16)
        weights = np.zeros((len(pos), 4), dtype=np.float32)
        idx_parts, base = [], 0
        for b in group:
            n = len(b.positions)
            joints[base : base + n, 0] = b.limb or 0
            weights[base : base + n, 0] = 1.0
            idx_parts.append(b.indices + base)
            base += n
        # texel coordinates to normalised UVs, using the tile the group shares
        tile = group[0].tile
        if tile.width > 0 and tile.height > 0:
            uvs = uvs / np.array([tile.width, tile.height], dtype=np.float32)
        scene.primitives.append(
            Primitive(
                material=mat,
                positions=pos.astype(np.float32),
                indices=np.concatenate(idx_parts).astype(np.uint32),
                normals=None if nrm is None else nrm.astype(np.float32),
                uvs=uvs.astype(np.float32),
                colors=cols.astype(np.uint8),
                joints=joints,
                weights=weights,
            )
        )

    scene.clips = list(clips or [])
    scene.extras = {
        "format": "n64_zobj",
        "limbs": skel.count,
        "drawn_limbs": len({b.limb for b in batches}),
        "materials": len(scene.materials),
        "textures": len(scene.textures),
        "textures_missing": missing,
        "unresolved_segments": sorted(unresolved),
        "rigid_skin": True,
    }
    if unresolved:
        scene.warnings.append(
            "segments "
            + ", ".join(f"{s:#x}" for s in sorted(unresolved))
            + " are written by actor code at draw time and cannot be resolved statically"
        )
    return scene
