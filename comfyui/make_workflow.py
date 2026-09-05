"""Write the two-person mocap workflow for ComfyUI.

    python comfyui/make_workflow.py [--video backyard.mp4] [--people 2] [--name take]

Outputs (next to this script, in comfyui/workflows/):
  gcrip_multi_person_mocap.json      drag into the ComfyUI browser UI (frontend format)
  gcrip_multi_person_mocap_api.json  POST to /prompt for a headless run (API format)

Graph: Load Video -> GCRip Person Masks -> one GVHMR Inference per person (sharing one
Load GVHMR Models) -> one SMPL to BVH per person (+ a BVH viewer each) + the mask preview.
Node dicts for the MotionCapture nodes are copied from that pack's own example workflows,
so the widget layout matches whatever version is installed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MC = Path(r"Z:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-MotionCapture\workflows")


def load_templates():
    tpl = {}
    for f in ("GVHMR.json", "smpl_to_bvh_pipeline.json"):
        d = json.loads((MC / f).read_text(encoding="utf-8"))
        for n in d["nodes"]:
            tpl.setdefault(n["type"], n)
    for k in ("LoadVideo", "LoadGVHMRModels", "GVHMRInference", "SMPLtoBVH", "BVHViewer"):
        if k not in tpl:
            sys.exit(f"template for {k} not found in {MC}")
    return tpl


class Graph:
    def __init__(self):
        self.nodes, self.links, self.nid, self.lid = [], [], 0, 0

    def add(self, node, pos, widgets=None, size=None):
        node = copy.deepcopy(node)
        self.nid += 1
        node["id"] = self.nid
        node["pos"] = list(pos)
        if size:
            node["size"] = list(size)
        node["order"] = self.nid - 1
        node["mode"] = 0
        node["flags"] = {}
        for i in node.get("inputs", []):
            i["link"] = None
        for o in node.get("outputs", []):
            o["links"] = []
        if widgets is not None:
            node["widgets_values"] = widgets
        self.nodes.append(node)
        return node

    def link(self, src, out_name, dst, in_name):
        # match by socket name, else by type (the example files name some outputs by type)
        o = next(
            (i for i, x in enumerate(src["outputs"]) if out_name in (x["name"], x["type"])), None
        )
        i_ = next(
            (i for i, x in enumerate(dst["inputs"]) if in_name in (x["name"], x["type"])), None
        )
        if o is None or i_ is None:
            sys.exit(f"cannot link {src['type']}.{out_name} -> {dst['type']}.{in_name}")
        self.lid += 1
        typ = src["outputs"][o]["type"]
        self.links.append([self.lid, src["id"], o, dst["id"], i_, typ])
        src["outputs"][o]["links"].append(self.lid)
        dst["inputs"][i_]["link"] = self.lid

    def doc(self):
        return {
            "id": "gcrip-multi-person-mocap",
            "revision": 0,
            "last_node_id": self.nid,
            "last_link_id": self.lid,
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {"ds": {"scale": 0.8, "offset": [80, 120]}},
            "version": 0.4,
        }


def plain_node(type_, inputs, outputs, widgets, title=None):
    """A legacy-style node dict for nodes we have no template for."""
    n = {
        "type": type_,
        "inputs": [{"name": a, "type": b, "link": None} for a, b in inputs],
        "outputs": [{"name": a, "type": b, "links": []} for a, b in outputs],
        "properties": {"Node name for S&R": type_},
        "widgets_values": widgets,
        "size": [320, 200],
    }
    if title:
        n["title"] = title
    return n


def build(video: str, people: int, name: str):
    tpl = load_templates()
    g = Graph()
    note = g.add(
        plain_node(
            "Note",
            [],
            [],
            [
                "GCRip: footage of several people -> one BVH per person.\n"
                "1. Load Video: pick your clip (drop it on the node). Static phone, whole "
                "bodies in frame, people not overlapping at the first frame.\n"
                "2. GCRip Person Masks: set 'people' to how many are in the shot; person 1 = "
                "leftmost at the start (or 'largest_first'). Check the preview image.\n"
                "3. Run. BVH files land in ComfyUI/output as <name>_p1.bvh, <name>_p2.bvh ...\n"
                "4. Blender: GCRip Library > spawn a character per person > GCRip Mocap > "
                "pick the BVH > Retarget. Or the gcrip-comfy MCP tool mocap_take does it all."
            ],
        ),
        (-560, -260),
        size=[520, 210],
    )
    note["color"], note["bgcolor"] = "#432", "#653"
    vid = g.add(tpl["LoadVideo"], (-560, 0), widgets=[video, "image"])
    masks = g.add(
        plain_node(
            "GCRipPersonMasks",
            [("video", "VIDEO")],
            [
                ("mask_1", "VIDEO"),
                ("mask_2", "VIDEO"),
                ("mask_3", "VIDEO"),
                ("mask_4", "VIDEO"),
                ("preview", "IMAGE"),
                ("info", "STRING"),
            ],
            [people, "left_to_right", "person_yolov8m-seg.pt", 0.4, 6, name],
        ),
        (-220, 0),
        size=[330, 260],
    )
    g.link(vid, "VIDEO", masks, "video")
    prev = g.add(
        plain_node("PreviewImage", [("images", "IMAGE")], [], []), (-220, 320), size=[330, 260]
    )
    g.link(masks, "preview", prev, "images")
    cfg = g.add(tpl["LoadGVHMRModels"], (-220, -260), widgets=["", "auto", "auto", False])
    for k in range(1, people + 1):
        y = (k - 1) * 340
        inf = g.add(
            tpl["GVHMRInference"], (180, y), widgets=[False, 0, 1.2, "simple_vo", 0.5, 8, 32]
        )
        inf["title"] = f"GVHMR Inference - person {k}"
        g.link(vid, "VIDEO", inf, "video")
        g.link(masks, f"mask_{k}", inf, "video_mask")
        g.link(cfg, "GVHMR_CONFIG", inf, "config")
        bvh = g.add(tpl["SMPLtoBVH"], (520, y), widgets=["", f"{name}_p{k}.bvh", 30, 1.0])
        bvh["title"] = f"SMPL to BVH - person {k}"
        for inp in bvh["inputs"]:  # the pack's example predates the 'filename' rename
            if inp["name"] == "output_path":
                inp["name"] = inp["localized_name"] = "filename"
                if inp.get("widget"):
                    inp["widget"]["name"] = "filename"
        g.link(inf, "npz_path", bvh, "npz_path")
        view = g.add(tpl["BVHViewer"], (820, y), widgets=[""])
        g.link(bvh, "bvh_data", view, "bvh_data")
    return g.doc()


def to_api(doc: dict) -> dict:
    """Frontend workflow -> /prompt payload (widgets by input name, links as [node, slot])."""
    links = {lk[0]: lk for lk in doc["links"]}
    api = {}
    for n in doc["nodes"]:
        if n["type"] in ("Note", "BVHViewer"):
            continue
        inputs = {}
        widgets = list(n.get("widgets_values") or [])
        wi = 0
        for inp in n.get("inputs", []):
            if inp.get("link") is not None:
                lk = links[inp["link"]]
                inputs[inp["name"]] = [str(lk[1]), lk[2]]
                if inp.get("widget"):
                    wi += 1
            elif inp.get("widget") or n["type"] == "GCRipPersonMasks":
                if inp["name"] == "upload":
                    wi += 1
                    continue
                if wi < len(widgets):
                    inputs[inp["name"]] = widgets[wi]
                wi += 1
        if n["type"] == "GCRipPersonMasks":
            names = ["people", "order", "model", "confidence", "dilate", "name"]
            inputs.update(dict(zip(names, widgets, strict=True)))
        api[str(n["id"])] = {"class_type": n["type"], "inputs": inputs}
    # a PreviewImage output keeps the mask node alive in API runs
    return api


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="backyard.mp4")
    ap.add_argument("--people", type=int, default=2)
    ap.add_argument("--name", default="take")
    a = ap.parse_args()
    out = HERE / "workflows"
    out.mkdir(exist_ok=True)
    doc = build(a.video, a.people, a.name)
    (out / "gcrip_multi_person_mocap.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    (out / "gcrip_multi_person_mocap_api.json").write_text(
        json.dumps(to_api(doc), indent=1), encoding="utf-8"
    )
    print("wrote", out / "gcrip_multi_person_mocap.json", "and the _api.json twin")
