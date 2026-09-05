"""Find a thrown object in static-camera footage.

A can leaving a hand is far too small for a class detector (YOLO-COCO only glimpses it
mid-air), but with a static camera it is a small foreground blob that is not part of any
person mask and moves like a projectile.  So: median background, frame differencing,
drop everything inside the (dilated) person masks, then link small blobs across frames
with a constant-velocity-plus-gravity prediction.  Chains whose vertical acceleration
matches gravity (scaled from the people's height in pixels) and that start next to a
person are throws: release frame, who threw it, the 2D path, where it stopped or left.

Two passes: ``extract_blobs`` (slow, one read of the video) and ``link_throws`` (fast).
"""

from __future__ import annotations

import numpy as np


def background_median(cap, frames, samples=24):
    import cv2

    idx = np.linspace(0, max(frames - 1, 0), samples).astype(int)
    stack = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok:
            stack.append(f)
    return np.median(np.stack(stack), axis=0).astype(np.uint8)


def _blobs(fg, min_area, max_area):
    import cv2

    n, _labels, stats, cents = cv2.connectedComponentsWithStats(fg, connectivity=8)
    out = []
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        if min_area <= a <= max_area:
            out.append((float(cents[i][0]), float(cents[i][1]), a))
    return out


def extract_blobs(
    video_path,
    person_mask,
    frames,
    *,
    diff_thr=28,
    min_area=10,
    max_area=2500,
    person_pad=14,
    colour="bright",
    progress=None,
):
    """Per frame: small foreground blobs outside the people, the distance-to-person map
    (downsampled x4) and the tallest person's height.  ``person_mask(t)`` -> uint8 (h, w)
    union mask of the tracked people at frame t, or None.  ``colour``: 'bright' keeps
    only light, unsaturated moving pixels (cans, cups, balls - and kills the wind in the
    leaves), 'dark' the opposite, 'any' every moving pixel."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path}")
    bg = background_median(cap, frames)
    bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    k_pad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * person_pad + 1, 2 * person_pad + 1))
    per_frame = []
    heights = []
    t = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        fg = (cv2.absdiff(g, bg_gray) > diff_thr).astype(np.uint8)
        if colour in ("bright", "dark"):
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            if colour == "bright":
                keep = (hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 185)
            else:
                keep = hsv[:, :, 2] < 70
            fg &= keep.astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k_open)
        pm = person_mask(t)
        dist = None
        if pm is not None and pm.any():
            padded = cv2.dilate(pm, k_pad)
            fg[padded > 0] = 0
            small = cv2.resize(
                padded,
                (padded.shape[1] // 4, padded.shape[0] // 4),
                interpolation=cv2.INTER_NEAREST,
            )
            dist = cv2.distanceTransform((small == 0).astype(np.uint8), cv2.DIST_L2, 3) * 4.0
            ys = np.nonzero(pm.any(axis=1))[0]
            if len(ys):
                heights.append(int(ys[-1] - ys[0]))
        per_frame.append((_blobs(fg, min_area, max_area), dist))
        t += 1
        if progress is not None:
            progress(t, frames)
    cap.release()
    return {"frames": per_frame, "person_height": float(np.median(heights)) if heights else 0.0}


def _dist_at(dist, x, y):
    if dist is None:
        return 1e9
    j = min(max(int(y / 4), 0), dist.shape[0] - 1)
    i = min(max(int(x / 4), 0), dist.shape[1] - 1)
    return float(dist[j, i])


def link_throws(
    data,
    *,
    fps=30.0,
    person_m=1.75,
    near_person=45,
    min_len=5,
    min_speed=3.0,
    first_tol=60.0,
    max_travel_heights=3.0,
):
    """Link blobs into projectile chains and keep the ones that fly like a thrown object.
    Gravity in pixels comes from the people's height (``person_m`` metres tall)."""
    frames = data["frames"]
    h_px = data.get("person_height") or 0.0
    g_px = 9.81 * (h_px / person_m) / (fps * fps) if h_px else 3.0
    active, chains = [], []
    for t, (blobs, dist) in enumerate(frames):
        used = set()
        for ch in active:
            lt, lx, ly = ch["pts"][-1]
            gap = t - lt
            px = lx + ch["v"][0] * gap
            py = ly + ch["v"][1] * gap + 0.5 * g_px * gap * gap
            tol = (
                first_tol
                if len(ch["pts"]) == 1
                else 10 + 6 * gap + 0.35 * (abs(ch["v"][0]) + abs(ch["v"][1])) * gap
            )
            best, bd = None, 1e9
            for i, (bx, by, _a) in enumerate(blobs):
                if i in used:
                    continue
                d = ((bx - px) ** 2 + (by - py) ** 2) ** 0.5
                if d < tol and d < bd:
                    best, bd = i, d
            if best is None:
                ch["misses"] += 1
                continue
            bx, by, ba = blobs[best]
            used.add(best)
            nv = ((bx - lx) / gap, (by - ly) / gap + 0.5 * g_px * gap)
            ch["v"] = (
                nv
                if len(ch["pts"]) == 1
                else (0.6 * ch["v"][0] + 0.4 * nv[0], 0.6 * ch["v"][1] + 0.4 * nv[1])
            )
            ch["pts"].append((t, bx, by))
            ch["areas"].append(ba)
            ch["misses"] = 0
        still = []
        for ch in active:
            (chains if ch["misses"] > 3 else still).append(ch)
        active = still
        for i, (bx, by, ba) in enumerate(blobs):
            if i in used:
                continue
            dp = _dist_at(dist, bx, by)
            if dp <= near_person:
                active.append(
                    {
                        "pts": [(t, bx, by)],
                        "v": (0.0, 0.0),
                        "misses": 0,
                        "areas": [ba],
                        "start_dist": dp,
                    }
                )
    chains += active
    events = []
    for ch in chains:
        pts = ch["pts"]
        if len(pts) < min_len:
            continue
        p = np.array(pts, dtype=float)
        tt, xx, yy = p[:, 0] - p[0, 0], p[:, 1], p[:, 2]
        span = max(tt[-1], 1.0)
        travel = float(((xx[-1] - xx[0]) ** 2 + (yy[-1] - yy[0]) ** 2) ** 0.5)
        speed = travel / span
        cy = np.polyfit(tt, yy, 2)
        accel = 2.0 * cy[0]  # px / frame^2, + = downwards
        resid = float(np.std(yy - np.polyval(cy, tt)))
        cx = np.polyfit(tt, xx, 1)
        resid_x = float(np.std(xx - np.polyval(cx, tt)))
        if speed < min_speed:
            continue
        if h_px and travel > max_travel_heights * h_px:  # a can does not cross the yard
            continue
        if not (0.4 * g_px <= accel <= 2.5 * g_px):  # not falling like an object
            continue
        if resid > 0.15 * travel + 6 or resid_x > 0.15 * travel + 6:  # wobbling smoke / leaves
            continue
        # the chain often starts while the object is still in the moving hand; the release
        # is where the rest of the path first free-falls (acceleration = g, tight fit)
        release = 0
        for k in range(len(pts) - 4):
            ck = np.polyfit(tt[k:] - tt[k], yy[k:], 2)
            ak = 2.0 * ck[0]
            rk = float(np.std(yy[k:] - np.polyval(ck, tt[k:] - tt[k])))
            if abs(ak - g_px) <= 0.35 * g_px and rk <= 4.0:
                release = k
                break
        events.append(
            {
                "release_frame": int(pts[release][0]),
                "chain_start_frame": int(pts[0][0]),
                "end_frame": int(pts[-1][0]),
                "frames": int(pts[-1][0] - pts[0][0] + 1),
                "seconds": round((pts[-1][0] - pts[0][0] + 1) / fps, 2),
                "release_xy": [round(xx[release], 1), round(yy[release], 1)],
                "end_xy": [round(xx[-1], 1), round(yy[-1], 1)],
                "velocity_px_per_frame": [round(float(cx[0]), 2), round(float(cy[1]), 2)],
                "gravity_px_per_frame2": round(float(accel), 2),
                "speed_px_per_frame": round(speed, 2),
                "travel_px": round(travel, 1),
                "mean_area_px": int(np.mean(ch["areas"])),
                "start_dist_to_person": round(ch["start_dist"], 1),
                "path": [(int(a), round(b, 1), round(c, 1)) for a, b, c in pts],
            }
        )
    # longest, farthest flight first; something that ends lower than it started (fell to
    # the ground) beats a puff of smoke drifting up
    events.sort(
        key=lambda e: (
            -(e["frames"] * e["travel_px"] * (2.0 if e["end_xy"][1] > e["release_xy"][1] else 1.0))
        )
    )
    return events, g_px


def draw_throw(frame_bgr, event, colour=(0, 200, 255)):
    import cv2

    pts = event["path"]
    for (_, x0, y0), (_, x1, y1) in zip(pts, pts[1:], strict=False):
        cv2.line(frame_bgr, (int(x0), int(y0)), (int(x1), int(y1)), colour, 3)
    cv2.circle(frame_bgr, (int(pts[0][1]), int(pts[0][2])), 12, (0, 255, 0), 3)
    cv2.circle(frame_bgr, (int(pts[-1][1]), int(pts[-1][2])), 12, (0, 0, 255), 3)
    cv2.putText(
        frame_bgr,
        f"throw: person {event.get('person', '?')} f{event['release_frame']}-{event['end_frame']}",
        (int(pts[0][1]) + 16, int(pts[0][2]) - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        colour,
        3,
    )
    return frame_bgr
