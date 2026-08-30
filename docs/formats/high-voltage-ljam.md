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
| `AGG` | `Mesh[1]\r\n{` | **geometry** - 2,114 files |
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
