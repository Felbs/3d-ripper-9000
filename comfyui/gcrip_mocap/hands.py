"""Hand pose per person per frame with WiLoR (wilor-mini), for wrists the body model
cannot see.

GVHMR gives a body skeleton without hands: the wrist has a position but its twist is a
guess, so anything held comes out wrong.  WiLoR estimates a MANO hand (21 joints, root
orientation) per detected hand in camera space.  Here every hand is assigned to a tracked
person (bbox centre inside their mask) and a side (WiLoR's is_right), and the camera-space
joints are kept so the Blender side can orient the character's hand bones by palm
normal + finger direction, and curl fingers where a rig has them.

Output: {"fps", "stride", "people": {"1": {"<frame>": {"L": HAND, "R": HAND}}}} where
HAND = {"bbox": [x0,y0,x1,y1], "kp3d": 21x3 metres in camera space (root at
pred_cam_t_full), "rot": 3x3 MANO root rotation (camera space), "score": 1}.
"""

from __future__ import annotations

import numpy as np

_PIPE = None


def _pipeline():
    global _PIPE
    if _PIPE is None:
        for a, v in (
            ("bool", bool),
            ("int", int),
            ("float", float),
            ("complex", complex),
            ("object", object),
            ("str", str),
            ("unicode", str),
        ):
            if not hasattr(np, a):  # chumpy (MANO loader) predates numpy 2
                setattr(np, a, v)
        import torch
        from wilor_mini.pipelines.wilor_hand_pose3d_estimation_pipeline import (
            WiLorHandPose3dEstimationPipeline,
        )

        _PIPE = WiLorHandPose3dEstimationPipeline(
            device="cuda" if torch.cuda.is_available() else "cpu",
            dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            verbose=False,
        )
    return _PIPE


def _aa_to_mat(aa):
    aa = np.asarray(aa, dtype=float).reshape(3)
    th = np.linalg.norm(aa)
    if th < 1e-8:
        return np.eye(3)
    k = aa / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def track_hands(video_path, person_mask, frames, *, stride=2, progress=None):
    """``person_mask(t, k)`` -> uint8 mask of person k (1-based) at frame t, or None.
    Returns the document described in the module docstring."""
    import cv2

    pipe = _pipeline()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    people: dict[str, dict] = {}
    t = 0
    n_hands = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if t % stride == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            for h in pipe.predict(rgb):
                x0, y0, x1, y1 = [float(v) for v in h["hand_bbox"]]
                cx, cy = int((x0 + x1) / 2), int((y0 + y1) / 2)
                owner = None
                k = 1
                while True:  # which person's mask holds the bbox centre
                    m = person_mask(t, k)
                    if m is None:
                        break
                    if 0 <= cy < m.shape[0] and 0 <= cx < m.shape[1]:
                        pad = m[max(0, cy - 20) : cy + 21, max(0, cx - 20) : cx + 21]
                        if pad.any():
                            owner = k
                            break
                    k += 1
                if owner is None:
                    continue
                wp = h["wilor_preds"]
                kp = np.asarray(wp["pred_keypoints_3d"])[0] + np.asarray(wp["pred_cam_t_full"])[0]
                side = "R" if float(h["is_right"]) > 0.5 else "L"
                rec = {
                    "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "kp3d": [[round(float(v), 4) for v in p] for p in kp],
                    "rot": [
                        [round(float(v), 5) for v in r]
                        for r in _aa_to_mat(np.asarray(wp["global_orient"])[0, 0])
                    ],
                    "kp2d": [
                        [round(float(v), 1) for v in p]
                        for p in np.asarray(wp["pred_keypoints_2d"])[0]
                    ],
                }
                people.setdefault(str(owner), {}).setdefault(str(t), {})[side] = rec
                n_hands += 1
        t += 1
        if progress is not None:
            progress(t, frames)
    cap.release()
    return {
        "video": video_path,
        "fps": fps,
        "stride": stride,
        "frames": t,
        "hands": n_hands,
        "people": people,
    }


def draw_hands(frame_bgr, hands_at_frame):
    import cv2

    colours = {"L": (80, 200, 255), "R": (255, 120, 80)}
    for side, rec in hands_at_frame.items():
        x0, y0, x1, y1 = [int(v) for v in rec["bbox"]]
        cv2.rectangle(frame_bgr, (x0, y0), (x1, y1), colours[side], 2)
        for x, y in rec.get("kp2d", []):
            cv2.circle(frame_bgr, (int(x), int(y)), 3, colours[side], -1)
        cv2.putText(frame_bgr, side, (x0, y0 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colours[side], 2)
    return frame_bgr
