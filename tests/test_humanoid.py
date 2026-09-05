"""The structural humanoid mapper (gcrip.humanoid) on the naming schemes in the library."""

from gcrip.humanoid import guess_bones, humanoid_hint, is_humanoid, tokens


def _rig(spec):
    """'name:parentname' lines -> (names, parents)."""
    names, parents = [], []
    for line in spec.split():
        n, _, p = line.partition(":")
        names.append(n)
        parents.append(names.index(p) if p else None)
    return names, parents


def _named(names, m):
    return {names[i]: v for i, v in m.items()}


def test_tokens_split_camel_side_and_digits():
    assert tokens("LCollarBone") == ["l", "collar", "bone"]
    assert tokens("J_Leg_L2_Knee") == ["j", "leg", "l", "2", "knee"]
    assert tokens("HipR") == ["hip", "r"]
    assert tokens("armL1") == ["arm", "l", "1"]
    assert tokens("RHandEnd") == ["r", "hand", "end"]
    assert tokens("millhouseRight_Foot") == ["millhouse", "right", "foot"]


def test_radical_rig_with_ik_handles_and_twist_helpers():
    # The Simpsons Hit & Run / Hulk (Radical): joint-named, IK handles at the root,
    # a "Forarm" twist between elbow and wrist, name prefix on every joint.
    names, parents = _rig(
        """
        Motion_Root Right_Foot:Motion_Root Handle_R_Foot:Right_Foot Right_Knee:Motion_Root
        Character_Root:Motion_Root Pelvis:Character_Root
        Hip_L:Pelvis Knee_L:Hip_L Ankle_L:Knee_L Ball_L:Ankle_L
        Hip_R:Pelvis Knee_R:Hip_R Ankle_R:Knee_R Ball_R:Ankle_R
        Spine_1:Pelvis Spine_2:Spine_1 Neck:Spine_2 Head:Neck Jaw:Head
        Clavicle_L:Spine_2 Shoulder_L:Clavicle_L Elbow_L:Shoulder_L Forarm_L:Elbow_L
        Wrist_L:Forarm_L Index_Base_L:Wrist_L Shoulder_Con_L:Clavicle_L
        Clavicle_R:Spine_2 Shoulder_R:Clavicle_R Elbow_R:Shoulder_R Forarm_R:Elbow_R
        Wrist_R:Forarm_R headShape:Motion_Root
        """
    )
    m = _named(names, guess_bones(names, parents))
    assert is_humanoid(guess_bones(names, parents))
    assert m == {
        "Pelvis": "Hips",
        "Hip_L": "LeftUpLeg",
        "Knee_L": "LeftLeg",
        "Ankle_L": "LeftFoot",
        "Ball_L": "LeftToeBase",
        "Hip_R": "RightUpLeg",
        "Knee_R": "RightLeg",
        "Ankle_R": "RightFoot",
        "Ball_R": "RightToeBase",
        "Spine_1": "Spine",
        "Spine_2": "Spine1",
        "Neck": "Neck",
        "Head": "Head",
        "Clavicle_L": "LeftShoulder",
        "Shoulder_L": "LeftArm",
        "Elbow_L": "LeftForeArm",
        "Wrist_L": "LeftHand",
        "Clavicle_R": "RightShoulder",
        "Shoulder_R": "RightArm",
        "Elbow_R": "RightForeArm",
        "Wrist_R": "RightHand",
    }


def test_ea_rig_bone_named_with_twists():
    # FIFA / NHL (EA): bone-named, twist bones between the real ones, 3 spine joints.
    names, parents = _rig(
        """
        Hips LowerSpine:Hips MiddleSpine:LowerSpine UpperSpine:MiddleSpine Neck:UpperSpine
        Head:Neck LCollarBone:UpperSpine LArm:LCollarBone LArmTwist:LArm LForearm:LArm
        LForearmTwist:LForearm LHand:LForearm LHandEnd:LHand
        RCollarBone:UpperSpine RArm:RCollarBone RForearm:RArm RHand:RForearm
        LLeg:Hips LShin:LLeg LFoot:LShin LToe:LFoot RLeg:Hips RShin:RLeg RFoot:RShin RToe:RFoot
        """
    )
    m = _named(names, guess_bones(names, parents))
    assert m["Hips"] == "Hips"
    assert (m["LowerSpine"], m["MiddleSpine"], m["UpperSpine"]) == ("Spine", "Spine1", "Spine2")
    assert (m["LCollarBone"], m["LArm"], m["LForearm"], m["LHand"]) == (
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
    )
    assert (m["RLeg"], m["RShin"], m["RFoot"], m["RToe"]) == (
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
        "RightToeBase",
    )
    assert "LArmTwist" not in m and "LHandEnd" not in m
    assert len(m) == 22


def test_j3d_link_matches_the_ripper_map():
    names, parents = _rig(
        """
        link_root center:link_root body_chn:center stomach_jnt:body_chn chest_jnt:stomach_jnt
        Lshoulder_jnt:chest_jnt LarmA_jnt:Lshoulder_jnt LarmB_jnt:LarmA_jnt cl_LhandA:LarmB_jnt
        Rshoulder_jnt:chest_jnt RarmA_jnt:Rshoulder_jnt RarmB_jnt:RarmA_jnt cl_RhandA:RarmB_jnt
        neck_jnt:chest_jnt head_jnt:neck_jnt hair1A_jnt:head_jnt
        waist_chn:center waist_jnt:waist_chn
        Lclotch_jnt:waist_jnt LlegA_jnt:Lclotch_jnt LlegB_jnt:LlegA_jnt Lfoot_jnt:LlegB_jnt
        Ltoe_jnt:Lfoot_jnt
        Rclotch_jnt:waist_jnt RlegA_jnt:Rclotch_jnt RlegB_jnt:RlegA_jnt Rfoot_jnt:RlegB_jnt
        Rtoe_jnt:Rfoot_jnt
        """
    )
    m = _named(names, guess_bones(names, parents))
    assert m["center"] == "Hips"
    assert (m["body_chn"], m["stomach_jnt"], m["chest_jnt"]) == ("Spine", "Spine1", "Spine2")
    assert (m["Lshoulder_jnt"], m["LarmA_jnt"], m["LarmB_jnt"], m["cl_LhandA"]) == (
        "LeftShoulder",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
    )
    assert (m["LlegA_jnt"], m["LlegB_jnt"], m["Lfoot_jnt"], m["Ltoe_jnt"]) == (
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "LeftToeBase",
    )
    assert "waist_jnt" not in m and "Lclotch_jnt" not in m


def test_japanese_joint_names_shoulder_starts_the_arm():
    names, parents = _rig(
        """
        loot hara:loot mune:hara sakotu:mune kubi:sakotu head:kubi
        kata_l:sakotu hiji_l:kata_l tekubi_l:hiji_l kata_r:sakotu hiji_r:kata_r tekubi_r:hiji_r
        momo_l:loot hiza_l:momo_l asikubi_l:hiza_l momo_r:loot hiza_r:momo_r asikubi_r:hiza_r
        """
    )
    m = _named(names, guess_bones(names, parents))
    assert (m["kata_l"], m["hiji_l"], m["tekubi_l"]) == ("LeftArm", "LeftForeArm", "LeftHand")
    assert m["sakotu"] == "LeftShoulder" and m["loot"] == "Hips"
    assert is_humanoid(guess_bones(names, parents))


def test_non_bipeds_and_numbered_joints_give_no_core():
    names = [f"joint_{i:03d}" for i in range(40)]
    parents = [None] + list(range(39))
    assert guess_bones(names, parents) == {}
    assert not humanoid_hint(names)
    # a snake: spine only
    names, parents = _rig("root spine1:root spine2:spine1 spine3:spine2 head:spine3")
    assert not is_humanoid(guess_bones(names, parents))


def test_blender_addon_carries_the_same_mapper():
    """The add-on embeds gcrip/humanoid.py verbatim (it must stay a single file)."""
    from pathlib import Path

    here = Path(__file__).resolve().parent.parent
    src = (here / "gcrip" / "humanoid.py").read_text(encoding="utf-8")
    body = src[src.index("_ROLES: dict[str, str] = {}") :].rstrip() + "\n"
    addon = (here / "blender" / "gcrip_blender.py").read_text(encoding="utf-8")
    a, b = "# BEGIN HUMANOID\n", "# END HUMANOID\n"
    block = addon[addon.index(a) + len(a) : addon.index(b)]
    assert block == body, "run tools/sync_addon_humanoid.py after editing gcrip/humanoid.py"


def test_humanoid_hint_needs_both_hands_feet_and_a_torso():
    assert humanoid_hint(["Pelvis", "HipL", "AnkleL", "AnkleR", "WristLeft", "WristRight"])
    assert not humanoid_hint(["Pelvis", "AnkleL", "AnkleR", "WristLeft"])
    assert not humanoid_hint(["Handle_L_Foot", "Handle_R_Foot", "L_Hand_IK", "R_Hand_IK", "Hips"])
