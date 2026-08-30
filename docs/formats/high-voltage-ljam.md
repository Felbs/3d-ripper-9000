# High Voltage `LJAM` archives - Hunter: The Reckoning

The disc reported zero models.  Its 9,068 loose files are animation text (`.aka`, `.akc`),
sound (`.spd`, 565 MB) and SourceSafe leftovers (`.scc`); the game itself is in **35 `.jam`
archives, 304 MB**, and those are `LJAM`.

## Layout - CRACKED

`gcrip/formats/ljam.py` + `gcrip/plugins/ljam.py`.  Little-endian, a directory tree written
depth-first:

    +0   char magic[4]  "LJAM"
    +4   the root node

    node:
        u32 file count
        file count times:  char name[12], u32 offset, u32 size
        u32 directory count
        directory count times:  char name[12], u32 node offset

**A node is its files and then its subdirectories** - two counted tables back to back.  Read as
one table the walk parses the first branch and stops: on `INTROUI.JAM` that gives one script
and none of the 383 KB behind it, including both `TPL` textures.

**A 12-character name fills the field with no terminator.**  A check that insists on a NUL
drops those entries, and dropping one entry in a node's table loses the whole subtree under it -
which is exactly how `GRAPHICS/` lost `LOGOS.TPL` and `LEGALBK.TPL` on the first attempt, since
`HVOLTAGE.TGA` sits between them and is 12 characters long.

## Result

**All 35 archives parse: 22,662 members, 304 of 304 MB accounted for.**  Coverage is the check
here - the members tile the file, so a wrong node stride shows up immediately as a hole.

    TPL 3,865   AGG 2,114   AGM 1,904   AGT 1,733   TXT 1,653   AKC 1,577
    ASD 1,563   AGD 1,561   ASN 1,561   AKA 1,044   ASB   938   AOS   580
    AOT   526   ADR   522   ASE   293   TGA   233

The disc previously yielded 566 loose `TPL`.  The archives hold **3,865 more**, plus 233 `TGA`.

## What the members are

Everything except `TPL` and `TGA` is **plain ASCII**, in a consistent brace-block syntax:

| ext | opens with | what it is |
|---|---|---|
| `AGG` | `Mesh[1]\r\n{` | **geometry - cracked, see below** - 2,114 files |
| `AGT` | `Surface2D[1]` | 2D surfaces / texture bindings |
| `AGS` | `Shader[3]` | shaders |
| `AGM` / `AGD` | `MatAssignment[2]` / `MaterialDatabase[2]` | materials |
| `AGN` | `MatAssignment[2]` | material assignment |
| `AGL` | `Light[4]` | lights |
| `AKA` / `AKC` / `AKW` | `KeyframeSet` / `RotTransCoordSys[5]` / `Weights[1]` | animation and skinning |
| `ASN` / `ASD` / `ASG` / `ASM` | `RotTransCoordSys` / `NodeDatabase` / `SpaceGraph` / `Modifier` | scene graph |
| `ASB` | `BoxBoundingGeometry[2]` | collision |
| `ASE` / `AOE` | `Emitter[2]` | particles |
| `SCN` / `ACN` / `TXT` | `SCENE "MainYrd2"` / `// MainYrd2.ACN` | level scripts |

So this game ships its art as **text**, which is unusual and very good news: there is no codec
to reverse, only a grammar to read.

## Note on the engine

The style names inside (`hvoltage`, `HVOLTAGE.TGA`) confirm **High Voltage Software**, the same
studio as Billy & Mandy and Codename: Kids Next Door, whose `FSTA` / `GMS` formats are still
open ([jam-fsta-hvs.md](jam-fsta-hvs.md)).  Those two discs keep their models in a compressed
`GMS`; if the compressed payload turns out to be the same brace-block text, the grammar written
for `AGG` here reads them as well once the codec falls.

## `AGG` meshes - CRACKED

`gcrip/formats/agg.py` + `gcrip/plugins/agg.py`.  A brace grammar with counted headers:

    Mesh "bak"
    {
        MatAssignment[1] { "sym3" }
        VertexArray[1] { VertexArray {
            VertexFormat { Pos3D BlendWeight 1 DiffuseColor TxtCoord 0 }
            Vertex[371] { -0.064241 2.550890 0.529913 1.000000 0 0 0 255 ... } } }
        IndexArray[1] { IndexArray { Index16Bit Index[1089] { 0 1 2 // 363 Faces ... } } }
        MeshComponent[2] { MeshComponent {
            MatAssignment 0 // "sym3"
            VertexGroup 0 203 168
            IndexedTriangleGroup 0 591 498 // 166 Faces } }
    }

`VertexFormat` declares the columns of every `Vertex` row, so the row width is **stated**:
`Pos3D` 3 floats, `Normal` 3, `BlendWeight n` n, `DiffuseColor` 4 bytes, `TxtCoord n` n pairs.
Across a 421-file sample those five tokens cover every format on the disc - the commonest are
`Pos3D DiffuseColor TxtCoord 1` (183), `Pos3D Normal TxtCoord 1` (162) and
`Pos3D BlendWeight 1 Normal TxtCoord 1` (97).  A token of unknown width is refused rather than
skipped, because skipping one would shift every column after it with no visible sign.

Three things cost time and are worth writing down:

* **`Index16Bit` is a type line, not a block.**  The block after it is `Index[1089]`, and the
  count is **indices**, not faces - the comment beside it says "363 Faces".  A reader that
  looks for `Index16Bit {` finds nothing at all.
* **`IndexedTriangleGroup start count` is also in indices**, while `VertexGroup start count`
  beside it is in vertices.  The two ranges in one component are counted in different units.
* **the mesh name is quoted too**, so taking material names from "the quoted strings above the
  vertex array" returns the mesh's own name.  They come from the `MatAssignment[n]` block.

**Result: 1,984 of 2,114 `AGG` parse - 7,760 parts, 781,658 triangles**, 0.20% degenerate,
median span over median edge 6.1.  7,343 parts carry uvs and 5,287 carry normals.  The 130 that
do not parse are collision maps: `Pos3D` alone with `MathTriangle` and `BspPlane` blocks and no
index array.

Material names survive on the primitives, but binding them to the `TPL` textures needs the
sibling `AGM` / `AGD` material text, which is not read yet.
