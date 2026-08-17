import json
import struct

import numpy as np

from gcrip import rig
from gcrip.export import gltf
from gcrip.formats import j3d
from gcrip.formats import j3d_anim as ja
from tests.test_j3d_export import _model


def build_bck(joint_tracks, duration=10, loop=2, rot_shift=0):
    """joint_tracks: list (per joint) of dicts {"sx"|"sy"|"sz"|"rx"|.."tz": [(t, v, tan), ...]}.
    Missing tracks are constant (scale 1, rot 0, trans 0)."""
    scales, rots, trans = [1.0], [0], [0.0]
    entries = b""

    def track(keys, table, is_rot):
        if not keys:
            return struct.pack(">HHH", 1, 0, 0)  # index 0 = 1.0 / 0 / 0.0
        if len(keys) == 1:
            table.append(round(keys[0][1] * 32768 / 180) if is_rot else keys[0][1])
            return struct.pack(">HHH", 1, len(table) - 1, 0)
        start = len(table)
        for t, v, tan in keys:
            if is_rot:
                table += [round(t), round(v * 32768 / 180), round(tan * 32768 / 180)]
            else:
                table += [float(t), float(v), float(tan)]
        return struct.pack(">HHH", len(keys), start, 0)

    for jt in joint_tracks:
        for ax in "xyz":
            entries += track(jt.get("s" + ax, []), scales, False)
            entries += track(jt.get("r" + ax, []), rots, True)
            entries += track(jt.get("t" + ax, []), trans, False)
    sc = struct.pack(f">{len(scales)}f", *scales)
    ro = struct.pack(f">{len(rots)}h", *rots)
    tr = struct.pack(f">{len(trans)}f", *trans)
    hdr_len = 0x40
    joint_off = hdr_len
    scale_off = joint_off + len(entries)
    rot_off = scale_off + len(sc)
    trans_off = rot_off + len(ro)
    body = entries + sc + ro + tr
    ank1 = b"ANK1" + struct.pack(
        ">IBBHHHHHIIII",
        hdr_len + len(body),
        loop,
        rot_shift,
        duration,
        len(joint_tracks),
        len(scales),
        len(rots),
        len(trans),
        joint_off,
        scale_off,
        rot_off,
        trans_off,
    )
    ank1 = ank1.ljust(hdr_len, b"\0") + body
    return b"J3D1bck1" + struct.pack(">II", 0x20 + len(ank1), 1) + b"\xff" * 16 + ank1


def build_btp(tracks, duration):
    """tracks: {material name: (slot, [tex index per frame])}"""
    indices = []
    anim = b""
    names = list(tracks)
    for name in names:
        slot, frames = tracks[name]
        anim += struct.pack(">HHBxxx", len(frames), len(indices), slot)
        indices += frames
    idx = struct.pack(f">{len(indices)}H", *indices)
    remap = struct.pack(f">{len(names)}H", *range(len(names)))
    # J3D string table
    strs = b"".join(n.encode() + b"\0" for n in names)
    tab = struct.pack(">HH", len(names), 0xFFFF)
    off = 4 + 4 * len(names)
    for n in names:
        tab += struct.pack(">HH", 0, off)
        off += len(n) + 1
    tab += strs
    hdr = 0x20
    anim_off = hdr
    idx_off = anim_off + len(anim)
    remap_off = idx_off + len(idx)
    name_off = remap_off + len(remap)
    body = anim + idx + remap + tab
    tpt1 = b"TPT1" + struct.pack(
        ">IBBHHHIIII",
        hdr + len(body),
        2,
        0xFF,
        duration,
        len(names),
        len(indices),
        anim_off,
        idx_off,
        remap_off,
        name_off,
    )
    tpt1 = tpt1.ljust(hdr, b"\0") + body
    return b"J3D1btp1" + struct.pack(">II", 0x20 + len(tpt1), 1) + b"\xff" * 16 + tpt1


def test_bck_parse_and_hermite_sampling():
    data = build_bck(
        [
            {},
            {"rz": [(0, 0, 0), (10, 90, 0)], "tx": [(0, 10, 0), (5, 20, 2), (10, 10, 0)]},
        ],
        duration=10,
    )
    b = ja.parse_bck(data, "t")
    assert b.joint_count == 2 and b.duration == 10 and b.loops
    assert not b.joints[0].animated() and b.joints[1].animated()
    rz = b.joints[1].rotation[2]
    assert abs(rz.sample(0) - 0) < 1e-3 and abs(rz.sample(10) - 90) < 0.01
    assert abs(rz.sample(5) - 45) < 0.05  # zero tangents -> smoothstep, symmetric midpoint
    tx = b.joints[1].translation[0]
    assert abs(tx.sample(5) - 20) < 1e-5 and abs(tx.sample(20) - 10) < 1e-5  # clamp past end
    fr = np.arange(0, 11, 1.0)
    assert np.allclose(tx.sample_frames(fr), [tx.sample(f) for f in fr], atol=1e-4)
    # single-key rotation track uses the table value directly
    assert b.joints[0].scale[0].sample(3) == 1.0


def test_btp_parse_states():
    data = build_btp({"eyeL": (0, [1, 1, 2, 2]), "mouth": (0, [5])}, duration=4)
    p = ja.parse_btp(data, "blink")
    assert p.material_names == ["eyeL", "mouth"]
    assert p.tracks[0].at(3) == 2 and p.tracks[1].at(3) == 5
    st = p.states()
    assert [f for f, _ in st] == [0, 2]
    assert st[1][1] == (("eyeL", 0, 2), ("mouth", 0, 5))


def test_euler_quat_matches_matrix():
    q = ja.euler_xyz_to_quat(30, -40, 100)
    rx, ry, rz = np.radians([30, -40, 100])
    j = j3d.Joint(0, "j", None, (1, 1, 1), (rx, ry, rz), (0, 0, 0), 0, (0,) * 3, (0,) * 3)
    q2 = gltf._joint_trs(j)["rotation"]
    assert np.allclose(q, q2, atol=1e-6) or np.allclose(q, -np.array(q2), atol=1e-6)


def test_export_with_animation_and_expressions(tmp_path):
    model = _model()
    # second texture and a BTP that swaps material "m"'s texture to it
    from tests.test_j3d_export import _tex

    alt = _tex("t2")
    alt.data = bytes([255]) * 32  # different image, so it is a real alternate
    model.textures.append(alt)
    bck = ja.parse_bck(build_bck([{}, {"rz": [(0, 0, 0), (10, 90, 0)]}], duration=10), "spin")
    btp = ja.parse_btp(build_btp({"m": (0, [0, 1])}, duration=2), "blink")
    st = gltf.export(model, tmp_path / "a", animations=[bck], patterns=[btp])
    assert st.animations == ["spin"]
    g = json.loads((tmp_path / "a.gltf").read_text())
    an = g["animations"][0]
    assert an["name"] == "spin" and an["extras"]["gcrip_loop"] is True
    rot = [c for c in an["channels"] if c["target"] == {"node": 1, "path": "rotation"}]
    assert len(rot) == 1
    acc = g["accessors"][an["samplers"][rot[0]["sampler"]]["output"]]
    assert acc["count"] == 11  # sampled per frame, 0..10 inclusive
    # expression: hidden clone mesh "m@t2" + KHR_materials_variants preset "blink#1"
    names = [n["name"] for n in g["nodes"]]
    assert "m@t2" in names
    clone = g["nodes"][names.index("m@t2")]
    assert clone["extensions"]["KHR_node_visibility"]["visible"] is False
    assert clone["extras"]["gcrip_variant_of"] == "m"
    assert [v["name"] for v in g["extensions"]["KHR_materials_variants"]["variants"]] == ["blink#1"]
    assert "KHR_materials_variants" in g["extensionsUsed"]
    assert st.expressions == ["blink#1"]


def test_animation_joint_count_mismatch_is_skipped(tmp_path):
    model = _model()
    bck = ja.parse_bck(build_bck([{}, {}, {}], duration=2), "bad")
    st = gltf.export(model, tmp_path / "b", animations=[bck])
    assert st.animations == [] and any("bad" in w for w in st.warnings)


def _humanoid(names_parents):
    js = []
    for i, (n, p) in enumerate(names_parents):
        js.append(j3d.Joint(i, n, p, (1, 1, 1), (0, 0, 0), (0, 0, 0), 0, (0,) * 3, (0,) * 3))
    for j in js:
        if j.parent is not None:
            js[j.parent].children.append(j.index)
    return js


def test_standard_bones_wind_waker_style():
    js = _humanoid(
        [
            ("link_root", None),
            ("center", 0),
            ("body_chn", 1),
            ("stomach_jnt", 2),
            ("chest_jnt", 3),
            ("Lshoulder_jnt", 4),
            ("LarmA_jnt", 5),
            ("LarmB_jnt", 6),
            ("cl_LhandA", 7),
            ("neck_jnt", 4),
            ("head_jnt", 9),
            ("waist_chn", 1),
            ("waist_jnt", 11),
            ("Lclotch_jnt", 12),
            ("LlegA_jnt", 13),
            ("LlegB_jnt", 14),
            ("Lfoot_jnt", 15),
            ("Ltoe_jnt", 16),
            ("Rclotch_jnt", 12),
            ("RlegA_jnt", 18),
            ("RlegB_jnt", 19),
            ("Rfoot_jnt", 20),
            ("hatA_jnt", 10),
        ]
    )
    sb = {js[i].name: n for i, n in rig.standard_bones(js).items()}
    assert sb["center"] == "Hips"
    assert (sb["body_chn"], sb["stomach_jnt"], sb["chest_jnt"]) == ("Spine", "Spine1", "Spine2")
    assert sb["Lshoulder_jnt"] == "LeftShoulder" and sb["LarmA_jnt"] == "LeftArm"
    assert sb["LarmB_jnt"] == "LeftForeArm" and sb["cl_LhandA"] == "LeftHand"
    assert sb["LlegA_jnt"] == "LeftUpLeg" and sb["LlegB_jnt"] == "LeftLeg"
    assert sb["Lfoot_jnt"] == "LeftFoot" and sb["Ltoe_jnt"] == "LeftToeBase"
    assert sb["RlegA_jnt"] == "RightUpLeg" and sb["Rfoot_jnt"] == "RightFoot"
    assert sb["neck_jnt"] == "Neck" and sb["head_jnt"] == "Head"
    assert "Lclotch_jnt" not in sb and "hatA_jnt" not in sb


def test_standard_bones_japanese_and_underscore_styles():
    js = _humanoid(
        [
            ("kosi", None),
            ("mune", 0),
            ("kubi", 1),
            ("head", 2),
            ("udeL1", 1),
            ("udeL2", 4),
            ("udeL3", 5),
            ("handL", 6),
            ("kokaL", 0),
            ("momoL", 8),
            ("suneL1", 9),
            ("suneL2", 10),
            ("asiL", 11),
            ("shoulder_R", 1),
            ("arm_R1", 13),
            ("arm_R2", 14),
            ("hand_R", 15),
            ("leg_R1", 0),
            ("leg_R2", 17),
            ("foot_R", 18),
        ]
    )
    sb = {js[i].name: n for i, n in rig.standard_bones(js).items()}
    assert sb["kosi"] == "Hips" and sb["mune"] == "Spine" and sb["kubi"] == "Neck"
    assert sb["udeL2"] == "LeftArm" and sb["udeL3"] == "LeftForeArm" and sb["handL"] == "LeftHand"
    assert sb["momoL"] == "LeftUpLeg" and sb["suneL1"] == "LeftLeg" and sb["asiL"] == "LeftFoot"
    assert sb["shoulder_R"] == "RightShoulder" and sb["arm_R1"] == "RightArm"
    assert sb["leg_R1"] == "RightUpLeg" and sb["leg_R2"] == "RightLeg"
    assert sb["foot_R"] == "RightFoot"


def test_bone_names_mixamo_option(tmp_path):
    model = _model()
    st = gltf.export(model, tmp_path / "c", bone_names="mixamo")
    assert st.std_bones == {}  # 2-joint test model is not a humanoid
    g = json.loads((tmp_path / "c.gltf").read_text())
    assert g["nodes"][0]["name"] == "root"
