"""``AGG`` meshes - High Voltage's geometry, shipped as **plain text**.  Hunter: The Reckoning
keeps 2,114 of them inside its ``LJAM`` archives (:mod:`gcrip.formats.ljam`).

There is no codec here, only a grammar - brace blocks with a counted header::

    Mesh[1]
    {
        Mesh "bak"
        {
            MatAssignment[1] { "sym3" }
            VertexArray[1]
            {
                VertexArray
                {
                    VertexFormat { Pos3D BlendWeight 1 DiffuseColor TxtCoord 0 }
                    Vertex[371] { -0.064241 2.550890 0.529913 1.000000 0 0 0 255 ... }
                }
            }
            IndexArray[1]
            {
                IndexArray { Index16Bit Index[1089] { 152 154 153 // 1 3.000000 ... } }
            }
            MeshComponent[2]
            {
                MeshComponent
                {
                    MatAssignment 0 // "sym3"
                    PosTransform 6 0
                    VertexGroup 0 203 168
                    IndexedTriangleGroup 0 591 498 // 166 Faces
                }
            }
        }
    }

``VertexFormat`` declares the columns of every ``Vertex`` row, and the count in brackets says
how many rows to read, so the row width is stated rather than guessed::

    Pos3D            3 floats
    Normal           3 floats
    BlendWeight n    n floats
    DiffuseColor     4 integers, 0-255
    TxtCoord n       n pairs of floats

Across a 421-file sample the formats are `Pos3D DiffuseColor TxtCoord 1` (183),
`Pos3D Normal TxtCoord 1` (162), `Pos3D BlendWeight 1 Normal TxtCoord 1` (97), `Pos3D` alone
(47) and nine rarer combinations - all of them covered by those five tokens.

**A `MeshComponent` is where the material lives**, and its two ranges are counted differently:
``VertexGroup array start count`` is in vertices and ``IndexedTriangleGroup array start count``
is in **indices, not triangles** - the comment beside it says "166 Faces" against a count of
498.  Component indices are relative to the component's own vertex start, so a component is a
self-contained primitive once both ranges are sliced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

HEAD = re.compile(rb"^\s*(Mesh|VertexArray)\s*\[\s*\d+\s*\]")
COMMENT = re.compile(r"//[^\n]*")
COUNTED = re.compile(r"(\w+)\s*\[\s*(\d+)\s*\]\s*\{")
NAMED = re.compile(r'Mesh\s+"([^"]*)"\s*\{')
FORMAT = re.compile(r"VertexFormat\s*\{([^}]*)\}")
INDEX = re.compile(r"Index16Bit\s*Index\s*\[\s*(\d+)\s*\]\s*\{")
VERTEX = re.compile(r"Vertex\s*\[\s*(\d+)\s*\]\s*\{")
GROUP = re.compile(r"(VertexGroup|IndexedTriangleGroup)\s+(\d+)\s+(\d+)\s+(\d+)")
ASSIGN = re.compile(r"MatAssignment\s+(\d+)")
MATLIST = re.compile(r"MatAssignment\s*\[\s*\d+\s*\]\s*\{")
WIDTHS = {"Pos3D": 3, "Normal": 3, "DiffuseColor": 4}
SIZED = {"BlendWeight": 1, "TxtCoord": 2}  # token then a count; TxtCoord counts pairs


@dataclass
class Part:
    name: str
    positions: np.ndarray
    indices: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    colors: np.ndarray | None = None
    material: str | None = None


@dataclass
class Block:
    """One `Name { ... }` region of the text, by offset."""

    start: int
    end: int


@dataclass
class MeshText:
    name: str
    materials: list[str] = field(default_factory=list)
    arrays: list[tuple[list[tuple[str, int]], np.ndarray]] = field(default_factory=list)
    indices: list[np.ndarray] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)


def is_agg(head: bytes) -> bool:
    return HEAD.match(head[:64]) is not None


def _close(text: str, open_at: int) -> int:
    """Offset just past the `}` matching the `{` at ``open_at``."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _columns(spec: str) -> list[tuple[str, int]]:
    """The declared columns as (token, width); the width is what makes a row parseable."""
    out: list[tuple[str, int]] = []
    words = spec.split()
    i = 0
    while i < len(words):
        word = words[i]
        if word in WIDTHS:
            out.append((word, WIDTHS[word]))
            i += 1
        elif word in SIZED and i + 1 < len(words) and words[i + 1].isdigit():
            out.append((word, int(words[i + 1]) * SIZED[word]))
            i += 2
        else:
            return []  # an unknown token would silently shift every column after it
    return out


def _numbers(text: str) -> list[float]:
    return [float(t) for t in text.replace(",", " ").split() if t not in ("{", "}")]


def _mesh(text: str) -> MeshText | None:
    name = NAMED.search(text)
    got = MeshText(name.group(1) if name else "mesh")
    hit = MATLIST.search(text)
    if hit:  # the mesh name is quoted too, so take the names only from this block
        got.materials = re.findall(r'"([^"]*)"', text[hit.end() : _close(text, hit.end() - 1)])

    for fmt in FORMAT.finditer(text):
        cols = _columns(fmt.group(1))
        vtx = VERTEX.search(text, fmt.end())
        if not cols or vtx is None:
            continue
        rows, width = int(vtx.group(1)), sum(w for _, w in cols)
        body = text[vtx.end() : _close(text, vtx.end() - 1) - 1]
        values = _numbers(body)
        if len(values) < rows * width:
            continue
        got.arrays.append((cols, np.array(values[: rows * width], np.float64).reshape(rows, width)))

    for hit in INDEX.finditer(text):
        body = text[hit.end() : _close(text, hit.end() - 1) - 1]
        values = [int(v) for v in _numbers(body)][: int(hit.group(1))]
        got.indices.append(np.array(values[: len(values) - len(values) % 3], np.int64))

    for hit in COUNTED.finditer(text):
        if hit.group(1) != "MeshComponent":
            continue
        block = text[hit.end() : _close(text, hit.end() - 1)]
        for part in re.finditer(r"MeshComponent\s*\{", block):
            body = block[part.end() : _close(block, part.end() - 1) - 1]
            groups = {g[0]: tuple(int(x) for x in g[1:]) for g in GROUP.findall(body)}
            mat = ASSIGN.search(body)
            got.components.append(
                {
                    "material": int(mat.group(1)) if mat else None,
                    "vertices": groups.get("VertexGroup"),
                    "triangles": groups.get("IndexedTriangleGroup"),
                }
            )
    return got if got.arrays and got.indices else None


def _slice(cols, rows, material, name, verts, faces) -> Part | None:
    if not len(faces) or faces.max() >= len(rows):
        return None
    at, out = 0, {}
    for token, width in cols:
        out[token] = rows[:, at : at + width]
        at += width
    positions = out.get("Pos3D")
    if positions is None:
        return None
    uvs = out.get("TxtCoord")
    colors = out.get("DiffuseColor")
    return Part(
        name=name,
        positions=positions.astype(np.float32),
        indices=faces.astype(np.uint32),
        normals=out["Normal"].astype(np.float32) if "Normal" in out else None,
        uvs=uvs[:, :2].astype(np.float32) if uvs is not None and uvs.shape[1] >= 2 else None,
        colors=(colors / 255.0).astype(np.float32) if colors is not None else None,
        material=material,
    )


def parts(data: bytes) -> list[Part]:
    """One Part a MeshComponent, or one a mesh where the file declares no components."""
    if not is_agg(data[:64]):
        return []
    text = COMMENT.sub("", data.decode("latin-1"))
    out: list[Part] = []
    for hit in NAMED.finditer(text):
        body = text[hit.start() : _close(text, hit.end() - 1)]
        got = _mesh(body)
        if got is None:
            continue
        for i, comp in enumerate(got.components):
            vgroup, tgroup = comp["vertices"], comp["triangles"]
            if vgroup is None or tgroup is None:
                continue
            varray, vstart, vcount = vgroup
            iarray, istart, icount = tgroup
            if varray >= len(got.arrays) or iarray >= len(got.indices):
                continue
            cols, rows = got.arrays[varray]
            faces = got.indices[iarray][istart : istart + icount]
            mat = comp["material"]
            name = f"{got.name}_{i:02d}" if len(got.components) > 1 else got.name
            part = _slice(
                cols,
                rows[vstart : vstart + vcount],
                got.materials[mat] if mat is not None and mat < len(got.materials) else None,
                name,
                vcount,
                faces,
            )
            if part is not None:
                out.append(part)
        if not got.components:
            cols, rows = got.arrays[0]
            part = _slice(
                cols,
                rows,
                got.materials[0] if got.materials else None,
                got.name,
                len(rows),
                got.indices[0],
            )
            if part is not None:
                out.append(part)
    return out
