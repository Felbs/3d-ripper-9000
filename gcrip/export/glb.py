"""Pack a gcrip .gltf (+ .bin + PNG textures) into one self-contained .glb.

A .glb is the binary form of glTF: one file that carries the JSON, the geometry buffer
and every image, so it can be downloaded or moved on its own and still import into
Blender with all textures. Only external URIs are inlined; anything already embedded is
left as is.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

GLB_MAGIC = 0x46546C67  # 'glTF'
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def pack(gltf_path: Path) -> bytes:
    gltf_path = Path(gltf_path)
    g = json.loads(gltf_path.read_text(encoding="utf-8"))
    base = gltf_path.parent
    buffers = g.get("buffers", [])
    if len(buffers) > 1:
        raise ValueError("pack() supports single-buffer glTF files (gcrip writes one)")
    blob = bytearray()
    if buffers and buffers[0].get("uri"):
        blob += (base / buffers[0]["uri"]).read_bytes()
    elif buffers:
        raise ValueError("buffer already embedded; nothing to pack")
    views = g.setdefault("bufferViews", [])
    for img in g.get("images", []):
        uri = img.get("uri")
        if not uri or uri.startswith("data:"):
            continue
        data = (base / uri).read_bytes()
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        blob += data
        img.pop("uri")
        img["bufferView"] = len(views) - 1
        img["mimeType"] = "image/png" if uri.lower().endswith(".png") else "image/jpeg"
    while len(blob) % 4:
        blob.append(0)
    g["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(g, separators=(",", ":")).encode("utf-8")
    while len(js) % 4:
        js += b" "
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = bytearray(struct.pack("<III", GLB_MAGIC, 2, total))
    out += struct.pack("<II", len(js), CHUNK_JSON) + js
    out += struct.pack("<II", len(blob), CHUNK_BIN) + blob
    return bytes(out)


def write_glb(gltf_path: Path, out_path: Path | None = None) -> Path:
    out_path = Path(out_path) if out_path else Path(gltf_path).with_suffix(".glb")
    out_path.write_bytes(pack(gltf_path))
    return out_path
