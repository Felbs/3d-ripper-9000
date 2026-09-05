"""GCRip mocap helpers for ComfyUI.

GCRipPersonMasks: one video of several people in -> one mask video per person out, each
white-person-on-black at the source resolution, exactly what ComfyUI-MotionCapture's GVHMR
Inference wants in its ``video_mask`` socket.  People are found per frame with the YOLOv8
segmentation model the Impact subpack already installed (``models/ultralytics/segm/
person_yolov8m-seg.pt``) and followed through the clip by box overlap / centre distance,
so person 1 stays person 1 even when the two walk around each other.  Frames where a person
is briefly lost keep the last good mask.  Runs in ComfyUI's own Python (torch + ultralytics
+ cv2 are already there); the mask videos land in output/gcrip_masks/.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import numpy as np

_MAX_PEOPLE = 4


def _segm_models():
    import folder_paths

    root = os.path.join(folder_paths.models_dir, "ultralytics", "segm")
    try:
        names = sorted(f for f in os.listdir(root) if f.endswith(".pt"))
    except OSError:
        names = []
    return names or ["person_yolov8m-seg.pt"], root


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _video_path(video) -> str:
    """A filesystem path for a ComfyUI VIDEO (LoadVideo gives a path; in-memory videos are
    written to a temp file)."""
    src = video.get_stream_source()
    if isinstance(src, str):
        return src
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(src.getvalue() if hasattr(src, "getvalue") else src.read())
    return tmp.name


def track_people(path, model_path, conf=0.4, imgsz=640, device=None, progress=None):
    """Detect + follow people through a video.

    Returns (frames_meta, tracks): ``tracks`` = {track_id: {"n": frames seen, "cx": mean
    centre x, "area": mean box area, "masks": {frame: packed uint8 mask}}}, plus the
    frame count / size / fps of the source."""
    import cv2
    import torch
    from ultralytics import YOLO

    model = YOLO(model_path)
    if device is None:
        device = 0 if torch.cuda.is_available() else "cpu"
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    tracks: dict[int, dict] = {}
    live: dict[int, dict] = {}  # id -> {"box", "last"}
    next_id = 1
    t = 0
    w = h = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        res = model.predict(
            frame, classes=[0], conf=conf, imgsz=imgsz, device=device, verbose=False
        )[0]
        dets = []
        if res.masks is not None and len(res.boxes):
            boxes = res.boxes.xyxy.cpu().numpy()
            masks = res.masks.data.cpu().numpy()  # (n, mh, mw) at model scale
            for box, m in zip(boxes, masks, strict=False):
                m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
                dets.append((box, m))
        # greedy match: best IoU with a live track, else nearest centre within 30% of width
        used = set()
        for box, m in sorted(dets, key=lambda d: -(d[0][2] - d[0][0]) * (d[0][3] - d[0][1])):
            best, best_s = None, 0.0
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            for tid, tr in live.items():
                if tid in used or t - tr["last"] > int(fps * 2):
                    continue
                s = _iou(box, tr["box"])
                if s < 0.1:
                    ox, oy = (tr["box"][0] + tr["box"][2]) / 2, (tr["box"][1] + tr["box"][3]) / 2
                    d = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
                    s = 0.1 * max(0.0, 1 - d / (0.3 * w)) if d < 0.3 * w else 0.0
                if s > best_s:
                    best, best_s = tid, s
            if best is None:
                best = next_id
                next_id += 1
                tracks[best] = {"n": 0, "cx": 0.0, "area": 0.0, "masks": {}}
                live[best] = {"box": box, "last": t}
            used.add(best)
            live[best]["box"], live[best]["last"] = box, t
            tr = tracks[best]
            tr["n"] += 1
            tr["cx"] += cx
            tr["area"] += float((box[2] - box[0]) * (box[3] - box[1]))
            tr["masks"][t] = np.packbits(m.astype(bool))
        t += 1
        if progress is not None:
            progress(t, total)
    cap.release()
    for tr in tracks.values():
        if tr["n"]:
            tr["cx"] /= tr["n"]
            tr["area"] /= tr["n"]
    return {"frames": t, "w": w, "h": h, "fps": fps}, tracks


def write_mask_video(meta, track, path, dilate=0):
    """White-on-black mask video for one track; frames without a detection hold the last
    (or first) good mask so the clip never goes empty."""
    import cv2

    w, h, n = meta["w"], meta["h"], meta["frames"]
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), meta["fps"], (w, h))
    keys = sorted(track["masks"])
    if not keys:
        raise RuntimeError("empty track")
    kernel = None
    if dilate > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate + 1, 2 * dilate + 1))
    cur = None
    first = track["masks"][keys[0]]
    for t in range(n):
        if t in track["masks"]:
            cur = track["masks"][t]
        elif cur is None:
            cur = first
        m = np.unpackbits(cur)[: w * h].reshape(h, w) * 255
        m = m.astype(np.uint8)
        if kernel is not None:
            m = cv2.dilate(m, kernel)
        writer.write(cv2.cvtColor(m, cv2.COLOR_GRAY2BGR))
    writer.release()


class GCRipPersonMasks:
    """Track every person in a video and write one white-on-black mask video per person."""

    @classmethod
    def INPUT_TYPES(cls):
        models, _root = _segm_models()
        return {
            "required": {
                "video": ("VIDEO", {"tooltip": "The footage (core Load Video node)."}),
                "people": (
                    "INT",
                    {
                        "default": 2,
                        "min": 1,
                        "max": _MAX_PEOPLE,
                        "tooltip": "How many people to keep (the ones seen in the most frames).",
                    },
                ),
                "order": (
                    ["left_to_right", "largest_first"],
                    {"tooltip": "Which person is mask 1: leftmost on average, or the biggest."},
                ),
                "model": (
                    models,
                    {"tooltip": "YOLOv8 segmentation weights in models/ultralytics/segm."},
                ),
                "confidence": ("FLOAT", {"default": 0.4, "min": 0.05, "max": 0.95, "step": 0.05}),
                "dilate": (
                    "INT",
                    {
                        "default": 6,
                        "min": 0,
                        "max": 64,
                        "tooltip": "Grow each mask by this many pixels.",
                    },
                ),
                "name": (
                    "STRING",
                    {
                        "default": "take",
                        "tooltip": "Prefix of the mask files in output/gcrip_masks.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("VIDEO", "VIDEO", "VIDEO", "VIDEO", "IMAGE", "STRING", "GCRIP_TRACKS")
    RETURN_NAMES = ("mask_1", "mask_2", "mask_3", "mask_4", "preview", "info", "tracks")
    FUNCTION = "run"
    CATEGORY = "GCRip/mocap"
    DESCRIPTION = (
        "Finds and follows each person through the clip (YOLOv8-seg + tracking) and writes "
        "a white-on-black mask video per person for GVHMR Inference's video_mask input. "
        "Person 1 = leftmost (or largest). Preview shows who got which number."
    )

    def run(self, video, people, order, model, confidence, dilate, name):
        import cv2
        import folder_paths
        import torch
        from comfy.utils import ProgressBar
        from comfy_api.latest import InputImpl

        _models, root = _segm_models()
        model_path = os.path.join(root, model)
        if not os.path.isfile(model_path):
            raise RuntimeError(
                f"{model_path} not found - install the Impact subpack (YOLOv8-seg .pt)"
            )
        src = _video_path(video)
        t0 = time.time()
        bar = ProgressBar(max(1, int(cv2.VideoCapture(src).get(cv2.CAP_PROP_FRAME_COUNT) or 1)))
        meta, tracks = track_people(
            src, model_path, conf=confidence, progress=lambda i, n: bar.update_absolute(i)
        )
        good = [tid for tid, tr in tracks.items() if tr["n"] >= max(3, meta["frames"] * 0.2)]
        good.sort(key=lambda tid: -tracks[tid]["n"])
        keep = good[:people]
        if not keep:
            raise RuntimeError(
                f"no person tracked through the clip ({len(tracks)} short detections) - "
                "lower the confidence or check the footage"
            )
        if order == "left_to_right":
            keep.sort(key=lambda tid: tracks[tid]["cx"])
        else:
            keep.sort(key=lambda tid: -tracks[tid]["area"])
        out_dir = os.path.join(folder_paths.get_output_directory(), "gcrip_masks")
        os.makedirs(out_dir, exist_ok=True)
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "take"
        videos, lines = [], []
        for k, tid in enumerate(keep, 1):
            path = os.path.join(out_dir, f"{stem}_p{k}.mp4")
            write_mask_video(meta, tracks[tid], path, dilate=dilate)
            videos.append(InputImpl.VideoFromFile(path))
            tr = tracks[tid]
            lines.append(
                f"person {k}: seen in {tr['n']}/{meta['frames']} frames, "
                f"mean x {tr['cx'] / max(meta['w'], 1):.0%} of width -> {path}"
            )
        while len(videos) < _MAX_PEOPLE:
            videos.append(None)
        # preview: first frame with each kept person outlined + numbered
        cap = cv2.VideoCapture(src)
        ok, frame = cap.read()
        cap.release()
        if ok:
            colours = [(255, 80, 80), (80, 200, 255), (120, 255, 120), (255, 200, 60)]
            for k, tid in enumerate(keep, 1):
                tr = tracks[tid]
                f0 = min(tr["masks"])
                m = np.unpackbits(tr["masks"][f0])[: meta["w"] * meta["h"]].reshape(
                    meta["h"], meta["w"]
                )
                cnts, _ = cv2.findContours(
                    m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                cv2.drawContours(frame, cnts, -1, colours[(k - 1) % 4], 3)
                ys, xs = np.nonzero(m)
                if len(xs):
                    cv2.putText(
                        frame,
                        str(k),
                        (int(xs.mean()) - 20, int(ys.min()) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        2.0,
                        colours[(k - 1) % 4],
                        4,
                    )
            preview = torch.from_numpy(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            )[None]
        else:
            preview = torch.zeros((1, 64, 64, 3))
        info = (
            f"{meta['frames']} frames {meta['w']}x{meta['h']} @ {meta['fps']:.1f} fps, "
            f"{len(tracks)} tracks, kept {len(keep)}, {time.time() - t0:.0f}s\n" + "\n".join(lines)
        )
        print("[gcrip] person masks:\n" + info)
        people_doc = {
            "video": src,
            "frames": meta["frames"],
            "fps": meta["fps"],
            "size": [meta["w"], meta["h"]],
            "people": [
                {
                    "person": k,
                    "first": int(min(tracks[tid]["masks"])),
                    "last": int(max(tracks[tid]["masks"])),
                    "seen": int(tracks[tid]["n"]),
                    "mean_x": round(tracks[tid]["cx"] / max(meta["w"], 1), 3),
                    "mask": os.path.join(out_dir, f"{stem}_p{k}.mp4"),
                }
                for k, tid in enumerate(keep, 1)
            ],
        }
        with open(os.path.join(out_dir, f"{stem}_people.json"), "w", encoding="utf-8") as fh:
            json.dump(people_doc, fh, indent=1)
        tracks_out = {
            "video": src,
            "meta": meta,
            "people": [tracks[tid] for tid in keep],
            "name": stem,
            "out_dir": out_dir,
        }
        return (*videos, preview, info, tracks_out)


def _union_mask_fn(tracks_out):
    """frame -> uint8 union mask of the kept people (last good mask held over gaps)."""
    meta, people = tracks_out["meta"], tracks_out["people"]
    w, h = meta["w"], meta["h"]
    state = [None] * len(people)

    def fn(t):
        out = None
        for i, tr in enumerate(people):
            if t in tr["masks"]:
                state[i] = tr["masks"][t]
            elif state[i] is None and tr["masks"]:
                state[i] = tr["masks"][min(tr["masks"])]
            if state[i] is None:
                continue
            m = np.unpackbits(state[i])[: w * h].reshape(h, w)
            out = m if out is None else np.maximum(out, m)
        return out

    return fn


class GCRipThrowTracker:
    """Find an object thrown by one of the tracked people (static camera)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "tracks": ("GCRIP_TRACKS", {"tooltip": "From GCRip Person Masks."}),
                "colour": (
                    ["bright", "dark", "any"],
                    {"tooltip": "bright (cans, cups, balls), dark, or any moving thing."},
                ),
                "person_height_m": (
                    "FLOAT",
                    {"default": 1.75, "min": 1.0, "max": 2.3, "step": 0.05},
                ),
                "max_events": ("INT", {"default": 3, "min": 1, "max": 10}),
            }
        }

    RETURN_TYPES = ("STRING", "IMAGE", "INT", "INT", "INT")
    RETURN_NAMES = ("throws_json", "preview", "release_frame", "person", "flight_frames")
    FUNCTION = "run"
    CATEGORY = "GCRip/mocap"
    DESCRIPTION = (
        "Static-camera throw finder: small moving blobs outside the people that leave a "
        "person's hand and fall like a projectile. Gives the release frame, who threw, the "
        "2D path and how long it flew - the Blender side uses it to let go of a held prop."
    )

    def run(self, video, tracks, colour, person_height_m, max_events):
        import cv2
        import torch
        from comfy.utils import ProgressBar

        from . import throw

        src = tracks.get("video") or _video_path(video)
        meta = tracks["meta"]
        bar = ProgressBar(max(1, meta["frames"]))
        data = throw.extract_blobs(
            src,
            _union_mask_fn(tracks),
            meta["frames"],
            colour=colour,
            progress=lambda i, n: bar.update_absolute(i),
        )
        events, g_px = throw.link_throws(data, fps=meta["fps"], person_m=person_height_m)
        events = events[:max_events]
        # who threw it: the kept person whose mask is nearest the release point
        for e in events:
            t, (x, y) = e["release_frame"], e["release_xy"]
            best, bd = 0, 1e18
            for i, tr in enumerate(tracks["people"]):
                near = [f for f in tr["masks"] if abs(f - t) <= 5]
                if not near:
                    continue
                f = min(near, key=lambda f: abs(f - t))
                m = np.unpackbits(tr["masks"][f])[: meta["w"] * meta["h"]].reshape(
                    meta["h"], meta["w"]
                )
                ys, xs = np.nonzero(m)
                if len(xs):
                    d = float(np.min((xs - x) ** 2 + (ys - y) ** 2))
                    if d < bd:
                        best, bd = i + 1, d
            e["person"] = best
        top = events[0] if events else None
        cap = cv2.VideoCapture(src)
        if top:
            cap.set(cv2.CAP_PROP_POS_FRAMES, top["release_frame"] + max(1, top["frames"] // 3))
        ok, frame = cap.read()
        cap.release()
        if ok and top:
            throw.draw_throw(frame, top)
        if ok:
            preview = torch.from_numpy(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            )[None]
        else:
            preview = torch.zeros((1, 64, 64, 3))
        doc = {"gravity_px_per_frame2": round(g_px, 2), "fps": meta["fps"], "events": events}
        if tracks.get("out_dir") and tracks.get("name"):  # for headless callers (comfy_mcp)
            base = os.path.join(tracks["out_dir"], tracks["name"])
            with open(base + "_throws.json", "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1)
            if ok:
                cv2.imwrite(base + "_throw.png", frame)
        print(
            f"[gcrip] throws: {len(events)} event(s); best: "
            + (json.dumps({k: v for k, v in top.items() if k != "path"}) if top else "none")
        )
        return (
            json.dumps(doc),
            preview,
            int(top["release_frame"]) if top else -1,
            int(top["person"]) if top else 0,
            int(top["frames"]) if top else 0,
        )


NODE_CLASS_MAPPINGS = {"GCRipPersonMasks": GCRipPersonMasks, "GCRipThrowTracker": GCRipThrowTracker}
NODE_DISPLAY_NAME_MAPPINGS = {
    "GCRipPersonMasks": "GCRip Person Masks (track people)",
    "GCRipThrowTracker": "GCRip Throw Tracker (thrown object)",
}
