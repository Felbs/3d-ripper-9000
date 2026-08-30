# GCRip pipeline

How a GameCube disc image becomes textured, rigged, animated glTF you can play back in Blender.
One master chart (1) shows every route a file can take; the later charts zoom into one
stage each. Non-J3D games follow the same walk and export - only the "model parse" box
differs per format - so there is one pipeline, not one per engine. Module names are the
real ones in `gcrip/`.

## 1. End to end

```mermaid
flowchart LR
    ISO["game.iso<br/>(your own dump)"] --> WALK["1  Disc walk<br/>gcrip.disc + gcrip.manifest"]
    WALK --> MAN["disc_manifest.json<br/>every file, format, hash"]
    MAN --> RIP["2  Rip loop<br/>gcrip.rip"]
    RIP -->|"BMD / BDL"| J3D["3  J3D parse<br/>gcrip.formats.j3d"]
    RIP -->|"format a plugin claims<br/>(gcrip.plugins: retro, hsd, gma,<br/>jade, re4, ea, eagl, ebo, p3d, mdl2, mdl3, eurocom, hsf, sa2b, sadx, ninja_gc, billy, nu2, ttdisp, hgo, unreal, openspace, afs, lpac, melee, dbl, blitz, hsd, renderware, …)"| PLUG["3b  Plugin parse<br/>plugin.extract → ripcore Scene"]
    RIP -->|"nothing claims it"| GX["3c  Structure scan (fallback)<br/>gcrip.gxscan: GX display lists,<br/>vertex + index arrays"]
    J3D --> ANIM["4  Clip matching<br/>rip._AnimIndex + j3d_anim"]
    ANIM --> GLTF["5  glTF export<br/>gcrip.export.gltf / ripcore.gltf"]
    PLUG --> GLTF
    GX -->|"raw meshes, no rig/UVs"| GLTF
    GLTF --> OUT["out/&lt;GameID&gt;/&lt;disc path&gt;/<br/>model.gltf + .bin + _tex/*.png"]
    GLTF --> REP["report.html<br/>rip_results.json"]
    OUT --> BL["6  Blender<br/>blender/gcrip_blender.py"]
    BL --> PLAY["actions on the armature<br/>expression switches<br/>Mixamo-named bones"]
```

## 2. Disc walk (`gcrip disc/manifest`)

Every file on the disc is located, decompressed if needed, sniffed for its format, hashed and
recorded. Nothing is written yet; this is the map the rip works from.

```mermaid
flowchart TD
    A["boot.bin header<br/>game ID, title, FST offset"] --> B["FST parse<br/>12-byte entries, Shift-JIS names"]
    B --> C{"each file"}
    C -->|"Yaz0 / Yay0 magic"| D["LZ77 decompress"]
    C -->|"RARC / TGC magic"| E["expand archive<br/>nodes / files / string table"]
    C -->|"a plugin's container<br/>(BIG/VIV, PAK, DAS, RCF…)"| P["plugin.expand()<br/>members walked like RARC"]
    C -->|"no magic anyone knows"| G["generic fallback<br/>formats.generic: zlib/LZ10/LZ11/LZSS<br/>stream? (offset,size) table?"]
    D --> C
    E --> C
    P --> C
    G -->|"members / payload"| C
    G -->|"nothing"| F
    C -->|"leaf"| F["classify()<br/>magic first, then extension"]
    F --> G["ManifestEntry<br/>path, kind, fmt, sha1,<br/>container, offset, depth"]
    G --> H["disc_manifest.json"]
    style D fill:#e8f0e8,stroke:#5a7d5a
    style E fill:#e8f0e8,stroke:#5a7d5a
```

Kinds that matter downstream: `model` (BMD/BDL), `animation` (BCK/BTP/BVA…), `texture` (BTI/TPL).
Recursion goes eight archives deep; identical files are recognised by SHA-1. Plugin containers
are tried in name order and the two fallbacks (`generic`, `gx`) only when no real plugin
claims a file, so a known format always wins over a guess; a member byte-identical to its
container is refused (index-only headers would otherwise recurse forever).

## 3. One model: J3D → glTF

```mermaid
flowchart TD
    BMD["cl.bdl (J3D2bdl4)"] --> INF1["INF1 scene graph"] & VTX1["VTX1 vertex arrays<br/>pos / nrm / colour / 8 UV sets"] & EVP1["EVP1 envelopes<br/>weights + inverse bind"] & DRW1["DRW1 draw matrices<br/>rigid vs weighted"] & JNT1["JNT1 joints<br/>SRT, hierarchy"] & SHP1["SHP1 shapes<br/>display lists"] & MAT3["MAT3 materials<br/>TEV, texgens, tex matrices"] & TEX1["TEX1 textures"]

    SHP1 --> DL["decode display lists<br/>strips / fans / quads → triangles"]
    DL --> BAKE["bake to model space<br/>rigid: joint world matrix<br/>weighted: already model space"]
    JNT1 --> BAKE
    EVP1 --> SKIN["JOINTS_0 / WEIGHTS_0<br/>inverse bind = inv(joint world)"]
    DRW1 --> SKIN
    BAKE --> PRIM["one glTF mesh per shape,<br/>named after its material"]
    SKIN --> PRIM

    TEX1 --> DEC["gx_texture.decode<br/>I4…CMPR, palettes, tiles"] --> PNG["_tex/*.png"]
    MAT3 --> DIFF["diffuse(): pick base texture<br/>identity texmatrix › colour › stage"]
    MAT3 --> DET["detail(): 2nd layer, same UVs"]
    DIFF & DET --> COMP["bake base × detail<br/>eye white × pupil"] --> PNG
    MAT3 --> ALPHA["blend / alpha-test<br/>→ BLEND / MASK / OPAQUE"]

    JNT1 --> NODES["joint nodes<br/>(index == JNT1 order)"]
    NODES --> RIG["rig.standard_bones()<br/>Mixamo names in extras"]
    PRIM & PNG & ALPHA & RIG --> FILE["model.gltf + model.bin"]
```

Alternate face meshes stacked on the same joint (`eyeLdamA`…) are detected by name + bbox and
exported hidden (`KHR_node_visibility`) under `<model>_variants`.

## 4. Animation & expression matching (`rip._AnimIndex`)

Clips live in the same archive as the model, in an animation-only archive (`LkAnm.arc`), or in
cutscene packs (`Demo*.arc`). Byte-identical models are exported once, so a model "lives" in every
archive that holds a copy of it.

```mermaid
flowchart TD
    M["exported model<br/>joint count n, material names, home archives"] --> SAME{"clips in the<br/>model's own archives?"}
    SAME -->|"BCK with n joints"| CLIP["attach clip"]
    SAME -->|"BTP whose materials ⊆ model"| PAT["attach expression pattern"]

    ORPH["archive with clips no local<br/>model can use (LkAnm, AlAnm 35-joint, Demo*)"] --> CAND["candidates: exported models in the<br/>same directory with a matching joint count"]
    CAND --> SCORE["score = (BTP material hits,<br/>archive-name affinity Kolin←Kolin1,<br/>triangle count)"]
    SCORE --> BEST["best per joint count"]
    BEST --> TWIN["+ models with identical joint names<br/>whose archive has no clips of its own<br/>(TP tunics al / bl / ml / zl)"]
    TWIN --> CLIP
    MAP["--anim-map LkAnm=Link"] -.overrides.-> CAND
    SMALL["n < 8 joints needs BTP or<br/>name evidence"] -.guards.-> CAND
```

```mermaid
flowchart LR
    BCK["BCK · ANK1<br/>per joint × axis:<br/>scale / rot / trans keys<br/>hermite tangents"] --> SAMPLE["sample every frame @30 fps<br/>rot: Euler XYZ → quaternion,<br/>sign-continuous"]
    SAMPLE --> CH["glTF animation<br/>channels: rotation, translation,<br/>scale (only if ≠ 1)<br/>extras: loop, frames, fps"]

    BTP["BTP · TPT1<br/>per material: texture index per frame"] --> ST["distinct states<br/>(dedupe identical images,<br/>plausibility: same size/format/name family)"]
    ST --> CLONE["hidden clone mesh per texture<br/>eyeL@eyeh.3  mouth@mouthS3TC.4"]
    ST --> VAR["KHR_materials_variants presets<br/>link_freez, talk#4 … (≤256)"]
```

## 5. Blender side (`blender/gcrip_blender.py`)

```mermaid
sequenceDiagram
    participant U as You
    participant A as GCRip add-on
    participant I as Blender glTF importer
    participant S as Scene
    U->>A: File › Import › GCRip glTF
    A->>I: import_scene.gltf(model.gltf)
    I->>S: armature (bones = JNT1 joints, custom prop gcrip_std_bone)<br/>mesh per shape, materials with PNGs<br/>one action + NLA track per clip
    A->>S: hide meshes with gcrip_variant_of<br/>scene fps = 30<br/>(optional) rename bones → mixamorig:*
    U->>A: N-panel › GCRip › expression buttons
    A->>S: show eyeL@eyeh.3, hide siblings
    U->>S: pick an action (walk, dash…) or retarget a Mixamo clip by bone name
```

## 6. Level recompilation (`gcrip stage`, Wind Waker)

```mermaid
flowchart LR
    subgraph disc [game.iso]
        DZS["Stage.arc › stage.dzs<br/>(MULT room table, stage actors)"]
        DZR["RoomN.arc › room.dzr<br/>(ACTR/SCOB/DOOR/TRES per room)"]
    end
    subgraph rip [out/rip/GameID - already ripped]
        ROOMS["RoomN.arc/*.gltf<br/>room geometry"]
        OBJ["res/Object/*.arc/*.gltf<br/>actor models"]
    end
    DZS -->|"parse chunk table<br/>(formats/dzs.py)"| P[placements]
    DZR --> P
    P -->|"name → archive<br/>data/ww_actors.py table<br/>(mined from noclip.website)"| R{resolve}
    R -->|chests| BOX["Dalways boxa-d<br/>by params bits 20-23"]
    R -->|"KNOB*, door10…"| DOOR2["Knob.arc / the stage's own bdl"]
    R -->|"tags, switches, agb*"| SKIP1[skip: logic - no model]
    R -->|"kusa, flowers, trees"| SKIP2[skip: display lists in the DOL]
    ROOMS -->|"MULT translate+rotY"| M
    OBJ --> M
    BOX --> M
    DOOR2 --> M
    M["gltf_merge.LevelBuilder<br/>meshes imported once,<br/>every placement = node instance<br/>(skinned: own joints+skin, shared IBMs)"]
    M --> OUT["stages/name/name.gltf + .bin<br/>+ _report.json (counts, unresolved)"]
```

Actor positions are world-space; MULT moves only room geometry (verified against the game:
Outset's actors sit at the island's world slot, X≈-200k Z≈+300k). Rotation uses only the
Y angle (x/z fields usually carry parameters), s16 angle units, 0x8000 = 180°.

## 7. Non-J3D formats and the universal fallback

Which studio's disc goes through which container and model parser. Every box on the right
is a `gcrip.plugins` module; the routes all end in the same ripcore Scene → glTF export.
The full ledger with byte-layout notes is [FORMATS.md](FORMATS.md).

```mermaid
flowchart LR
    subgraph EA["Electronic Arts"]
        BIG["BIG / VIV / TERF / ZZDATA<br/>plugins.ea"] --> EAGL["EAGL .ord/.orp<br/>plugins.eagl"]
        BIG --> EBO["EBO .ebo<br/>plugins.ebo"]
    end
    subgraph SEGA["Sega / Sonic Team"]
        PRS["Sega PRS .prs<br/>plugins.segaprs"] --> SA2B["SA2B chunk tables<br/>plugins.sa2b"]
        ONE[".one v0.60 (Shadow)<br/>formats.one"] --> RW["RenderWare DFF/TXD<br/>plugins.renderware"]
        BML["PSO .bml<br/>plugins.bml"] --> NJ["NJCM / GJCM Ninja + Ginja<br/>plugins.ninja_gc"]
        GVM["GVM / GVR<br/>plugins.gvm"]
        REL[".rel modules + SA Tools tables<br/>plugins.sadx"] --> SADX["Basic / Ginja land tables<br/>formats.sadx"]
        PRD["Billy Hatcher .prd (PRS + U:8-)<br/>plugins.billy"] --> BILLY[".arc Ginja trees + skins,<br/>.lnd terrain<br/>formats.billy, billy_lnd"]
    end
    subgraph KROME["Krome (Merkury)"]
        RKV["RKV v1 / RKV2<br/>plugins.rkv"] --> MDL2["MDL2 .gmd<br/>plugins.mdl2"]
        RKV --> MDL3["MDL3 .mdl + .mdg<br/>plugins.mdl3"]
    end
    subgraph EIGHT["Eighting"]
        FPK["FPK + PRS<br/>plugins.fpk"] --> HSD["HAL HSD .dat<br/>plugins.hsd"]
        FPK --> RW
    end
    subgraph KONAMI["Konami (TMNT 1-3)"]
        MELEE["Mutant Melee archive.dat<br/>+ archive.arc index<br/>plugins.melee"] --> RW
        AFS["AFS .DAT archives<br/>plugins.afs"] --> RW
        AFS --> LPAC["LPAC packs (TMNT 2)<br/>plugins.lpac"] --> RW
        AFS --> KPAC["texture packs 0x23<br/>formats.konami_pac"] --> RW
    end
    subgraph EURO["Eurocom (EngineX)"]
        FL["Filelist.bin + .000<br/>plugins.eurocom (sibling hook)"] --> EDB["GEOM .edb v170-252<br/>plugins.eurocom"]
    end
    subgraph HUDSON["Hudson"]
        MPB["Mario Party .bin<br/>plugins.mpbin"] --> HSF["HSF<br/>plugins.hsf"]
    end
    subgraph RADICAL["Radical"]
        RCF["RCF (RADCORE / ATG)<br/>plugins.rcf"] --> P3D["Pure3D P3DZ / LZR<br/>plugins.p3d"]
    end
    subgraph OTHER["Capcom / Ubisoft / Neversoft / Blitz"]
        DAS["RE4 DAS / DRS<br/>plugins.re4"]
        BF["Jade .bf<br/>plugins.jade"]
        PRE["Neversoft PRE<br/>plugins.neversoft"]
        GCP["Blitz .gcp archives<br/>named per-level members<br/>plugins.blitz"] --> GX["structure scan<br/>plugins.gx"]
        NU2["TT NU20 .gsc/.csc (LSW1)<br/>plugins.nu2"]
        HGO["TT .hgo/.nus (Crash WoC, Nemo)<br/>reversed tags<br/>plugins.hgo"]
        TTPK["TT .fpk/.cpk packs<br/>plugins.ttdisp"] --> DISP["DISP programs .csc/.chg<br/>(LSW2, Narnia)<br/>formats.ttdisp"]
        UMD["Ubisoft .umd/.lin<br/>chunked zlib<br/>plugins.unreal"] --> UE2["UE2 packages .usx/.utx/.unr<br/>StaticMesh + Texture + level actors<br/>formats.unreal"]
        LVL["OpenSpace .lvl + .ptr<br/>(Rayman 3 / Arena)<br/>plugins.openspace"] --> CPA["super objects -> GeometricObjects<br/>+ TPL textures<br/>formats.openspace"]
        DBL["Avalanche .dbl/.dbu/.mdb<br/>plugins.dbl"] --> DBLM["mesh records: GX arrays +<br/>FIFO display lists, texture tables<br/>formats.dbl_mesh"]
    end
    EAGL & EBO & SA2B & SADX & BILLY & RW & NJ & MDL2 & MDL3 & HSD & EDB & HSF & P3D & DAS & BF & PRE & NU2 & HGO & DISP & UE2 & CPA & DBLM & GX --> SCENE["ripcore Scene → glTF"]
```


Every plugin turns one file into `ripcore.scene.Scene` objects (joints, materials,
primitives, decoded textures, clips) and hands them to the same exporter, so the chart in
§1 is the whole story for every engine. What differs is only how much a format gives up:

```mermaid
flowchart TD
    F["file no J3D parser wants"] --> D{"plugins_for(path, head, size)"}
    D -->|"retro / hsd / gma / pikmin / lm / sfa / jade /<br/>re4 / neversoft / renderware / ea / eagl / ebo / p3d / mdl2 / mdl3 / eurocom / hsf / sa2b / ninja_gc / billy / ttdisp / unreal / openspace / ttyd / feporr"| R["real parser<br/>meshes + materials + textures<br/>(+ rig, + clips where the format has them)"]
    D -->|"no ordinary plugin"| S["gx (fallback)<br/>entropy < 7.5 → gxscan.scan_blob(budget)"]
    S --> L["GX display lists<br/>opcode · count · index tuples,<br/>stride chained, NOP padding"]
    S --> N["neutral meshes<br/>f32 vertex run + u16 index run"]
    L & N --> SC["geometry score<br/>mean edge / percentile bbox · √N<br/>real ≈ 1-2, spaghetti ≈ 0.5·√N"]
    SC -->|"accepted"| M["Scene: one primitive per mesh,<br/>extras.gxscan = true"]
    R & M --> E["ripcore.gltf.export<br/>+ thumbnail + report row"]
```

EA Canada's EAGL objects (`plugins/eagl.py`: FIFA, NBA Live, NHL, MVP, Def Jam, Fight
Night - `.ord` + `.orp` = one ELF relocatable split in two) are the first non-J3D format
that reaches the exporter with a full rig: the `__Skeleton` table gives every bone its
parent, local TRS and inverse-bind matrix, and each render packet carries one row per GX
position-matrix slot holding up to four blend weights whose low mantissa byte is the bone
index - so the per-vertex `posmtx` byte in the display list becomes glTF `JOINTS_0` /
`WEIGHTS_0`. The 25 `__Model` "variations" of a player all share the same packets; they
are kit toggle sets (`enable_body_Sleeves_Long_r`, `enable_accs_goggles`, ...), so one Scene
per object carries every part and the toggles are left for a later split.

The later EA Sports titles (NHL 2005/06, NBA Live 2005/06, FIFA 05, 2006 FIFA World Cup,
UEFA CL) moved to EBO objects (`plugins/ebo.py`): a little-endian container whose type
and export tables name every serialised class (`Geometry`, `GcDisplayList`,
`GCVertexStream`, `Float3`/`Short3`/`Char3`/`Short2`/`R5G6B5`, or `EaglAnim::*` for
animation banks and skeletons). Each Geometry export is one Scene; its lists are GX strips
whose vertex is `[posmtx][texmtx]` plus one u8/u16 index per stream in GX order, integer
positions are normalised to the Geometry's own bounding box, and the per-list skin table
(weights with the bone index in the low byte, like FIFA) points into the game's skeleton
objects (`preload/gmisc.viv/bodyskel.ebo`, `faceskel.ebo`, `handskel.ebo`), which give
names, parents and inverse-bind matrices - so players export rigged, in T-pose.

Radical Entertainment's Pure3D (`plugins/p3d.py`, `plugins/rcf.py`: Simpsons Hit & Run and
Road Rage, Hulk, The Incredible Hulk, Crash Tag Team Racing, Dark Summit, Monsters Inc,
Godzilla) is a documented chunk tree - in both endians on GameCube - but its geometry is
GX-native: each prim group carries a vertex-attribute descriptor, a big-endian fixed-point
vertex buffer and a display list, which `formats/p3d.py` decodes with the same
index-width search as EBO. Files are usually wrapped in `P3DZ`, Radical's LZR byte-LZ
(`formats/lzr.py`, blocks of 4 KB), and on Hulk/Crash sit inside RCF archives
(`formats/rcf.py`). Skins name their skeleton (`Skeleton`/`SkeletonJoint` rest poses),
shaders name their textures (DXT1 DDS or PNG inside the file).

Krome Studios' Merkury engine (`plugins/rkv.py`, `plugins/mdl2.py`: Ty the Tasmanian Tiger)
keeps everything in one `.rkv` archive whose directory sits at the END of the file
(`formats/rkv.py`). Its `.gmd` models are big-endian MDL2 tables (`formats/mdl2.py`): one
interleaved 28-byte vertex buffer (f32 position, s8 normal, s16 UV /4096, a two-bone weight,
RGBA) and per-mesh GX display lists whose vertices are four u16 indices (position, normal,
colour, uv) into that buffer. Material names are the `.gtx` texture stems (CMPR with mips,
or RGB5A3 for alpha textures); bones are positions only, the hierarchy lives in `.bad` text
files. The later Merkury games (Ty 2 / 3, Spyro: A New Beginning, King Arthur) use RKV2
archives (directory at 0x80, 20-byte entries) and MDL3 pairs (`formats/mdl3.py`,
`plugins/mdl3.py`): the `.mdl` holds the tables - subobjects, texture names, bone
positions and a textures × subobjects grid of offsets into the `.mdg` - and each `.mdg`
block is a GX display list with 9-byte vertices (position index, inline s8 normal, colour
and UV indices) over f32 positions that carry two bone indices and a weight when the model
is rigged. Blitz Games' `.gcp` archives (`plugins/blitz.py`, `formats/blitz_gcp.py`) are split into their
named per-level members and those into packages, so
the fallback scanner can read them.

Eighting's `.fpk` packs (`plugins/fpk.py`: Naruto Clash of Ninja / Gekitou Ninja Taisen,
Bloody Roar: Primal Fury, Zatch Bell!, Battle Stadium D.O.N) only needed a container: the
members are PRS-compressed (GNTool's variant - MSB-first flags, big-endian long copies)
and turn out to be HAL sysdope `.dat` models or RenderWare `.dff`/`.txd`, which the `hsd`
and `renderware` plugins already read. Fallback containers (`generic`) are never applied
to the members of an archive a real plugin opened: their contents are that plugin's own
formats, and guessing tables inside them only manufactures pseudo-files (RE4's `.das`
members became 25 k of them).

Eurocom's EngineX (`plugins/eurocom.py`, `formats/eurocom.py`: Sphinx and the Cursed
Mummy, Buffy: Chaos Bleeds, Spyro: A Hero's Tail, Robots, Batman Begins, Ice Age 2) keeps
the whole game in `Filelist.000` with the directory in the sibling `Filelist.bin` - the
first container whose members cannot be listed from its own bytes, hence the
`NEEDS_SIBLING` / `expand_with` hook the manifest walker and the ripper both honour. The
`GEOM` `.edb` databases inside are relocatable hash-array files (the layouts follow
eurotools' `eurochef`); each mesh entity is f32 positions, s16 texture coordinates scaled
by a per-entity shift, RGBA colours and GX strips with four u16 index columns, and the
field offsets shift with the EDB version (170/182, 240/248, 251/252 are all in the
library). Textures are GX pixels behind a 64-byte header found by scanning the texture
struct for the (size, pointer) pair that lands on one.

Hudson's Mario Party 4-7 (`plugins/mpbin.py`, `plugins/hsf.py`) pack everything into
`.bin` archives of LZSS / slide / RLE members; the `HSFV037` models inside (layout after
KillzXGaming's MPLibrary) are section tables - component arrays for positions, normals,
colours and UVs, 48-byte primitives with four s16 index columns (strips continue in an
extension table), 0x144-byte object nodes with a TRS hierarchy, materials that reach their
texture through the symbol table, and cenv envelopes (single / double / multi binds over
position ranges) that become skin weights on the object-index joints.

Sonic Team's GameCube ports reuse the Dreamcast pipeline: `.prs` files are Sega PRS
streams (`plugins/segaprs.py` unpacks them into a `payload.bin` member), Sonic Adventure
2: Battle's `*mdl.prs` payloads are id/offset tables of NJS_OBJECT trees with Ninja chunk
attaches byte-swapped to big-endian (`formats/sa2b.py` subclasses dcrip's chunk parser and
`dcrip.ninja_eval` builds the rigged scene), `*tex.prs` / `.gvm` archives hold GVR textures
(`plugins/gvm.py`, GX pixel formats behind a `GVRT` header), and Shadow the Hedgehog's
`One Ver 0.60` archives (`formats/one.py`) unpack to RenderWare DFF/TXD for the
`renderware` plugin.
Phantasy Star Online Episode I & II packs its objects in `.bml` archives (`plugins/bml.py`:
PRS-compressed Ninja model + GVM pairs) and ships `.nj` files whose `NJCM` blocks are the
Dreamcast chunk format in GameCube byte order, plus `GJCM` "Ginja" blocks - GX-native
attaches with vertex sets, parameter lists and raw display lists (`formats/ginja.py`);
`plugins/ninja_gc.py` feeds both through dcrip's Ninja scene builder.
Billy Hatcher and the Giant Egg is the same Ginja lineage one step further: its `.prd`
packages are PRS streams over a `U:8-` archive (`formats/prd.py`), the `.arc` members are
Ninja object trees whose pointers are relative to 0x20 (`formats/billy.py` slices the file
and finds the tree roots by the `FDFDFDFD` pad after every NJS_OBJECT), and skinned
characters use the attach's skin-set pointer - bone nodes write `s16` position/normal rows
with weights into the shared GX vertex cache that the mesh node then indexes, which
`formats/ginja.py` now decodes and `dcrip.ninja_eval` evaluates in two passes (all writes,
then draws).  Stage terrain (`stg_*.lnd`, `formats/billy_lnd.py`) is not an object tree:
one vertex pool (f32 positions, RGBA colours, s16 UVs) drawn by ~1,300 raw GX display
lists through batch entries that name the material, whose word 9 indexes the file's texlist
/ GVM.

Traveller's Tales' GameCube titles after LEGO Star Wars 1 (LEGO Star Wars II, The
Chronicles of Narnia) keep their geometry in a `DISP` chunk that is a display *program*
rather than a mesh list (`formats/ttdisp.py`): 8-byte commands select a material, load a
node matrix and draw a mesh descriptor, every pointer is relative to its own position, and
each descriptor is a GX vertex-descriptor word (which index attributes each strip row
carries and at what width) over s16 positions, s8 normals, u8 UVs and RGBA colours.  The
draw table at the head of the chunk maps command indices to materials; `.chg` character
files wrap the same chunk in a skeleton (bone names, parents, bind matrices) whose per-bone
lists name the draws, so LEGO minifigs come out rigged; `.fpk` / `.cpk` packs are plain
28-byte-entry containers.

Ubisoft's Unreal Engine 2 titles (the Splinter Cell series, Rainbow Six 3, Ghost Recon 2,
XIII) are read as Unreal packages (`formats/unreal.py`): the header's name / import /
export tables with UE's compact-index encoding in either byte order, tagged property
lists, and the Splinter Cell-family object layouts - a simplified `StaticMesh` (32-byte
position / normal / UV vertices, a u16 triangle strip, wireframe edges and per-material
sections) and `Texture` mips (DXT1 / DXT3 / DXT5 blocks, palettised P8).  Pandora Tomorrow
ships its `.usx` mesh and `.utx` texture packages uncompressed and little-endian, so
`plugins/unreal.py` rips them directly, binding materials to the texture package named by
each import; the chunked-zlib `.umd` / `.lin` archives of the other titles are expanded to
their member packages, but their big-endian map packages use a table encoding that is not
decoded yet.

Rayman 3 and Rayman Arena (Ubisoft Montpellier's OpenSpace / CPA engine) store each level
as a relocated memory image: `formats/openspace.py` applies the `.ptr` relocation table
(every pointer field's position and target file), walks the super-object tree from the
world down through sectors and IPOs to physical objects and their visual sets, and decodes
the GeometricObjects - on GameCube the plain triangle lists are empty and the geometry
lives in the "optimized" strip / disconnected-triangle indices over vertex and UV mapping
arrays.  Materials point at TextureInfos whose order in the level's texture table gives the
image index inside the sibling Nintendo TPL (`<level>_lvl.tpl` / `_trans.tpl` for Rayman 3,
`<level>.tpl` for Arena), aligned by image size to absorb the console downscales.  The
layouts come from the raymap project (github.com/byvar/raymap), checked against the discs.

Konami's Teenage Mutant Ninja Turtles trilogy turned out to be RenderWare underneath: the
`TMNT.DAT` archives are Sega/CRI AFS containers (`plugins/afs.py` keeps the member names)
holding little-endian RW 3.x clumps, world sectors and animations that the existing
`renderware` plugin already decodes, plus Konami's own texture packs (`formats/konami_pac.py`:
chunk 0x23 = a name table over standard `rwID_IMAGE` palettised images) which the plugin's
texture index now reads next to real TXDs.

The fallback is a map as much as a rip: its hits say where in an archive the models live
and how the vertices are laid out, which is most of what a real plugin needs. Multi-platform
engines that store only vertex/index buffers (Treyarch, Radical P3D) reach the scanner only
after their container - and often their own compression - is opened; `formats.generic`
handles the common table and LZ shapes, the rest is per-studio work in the order the
compatibility list's developer column suggests.

## What is heuristic (and where to look when it's wrong)

| step | assumption | if wrong |
|---|---|---|
| base texture | first TEV stage sampling a vertex UV set, identity matrix, colour format | material shows the wrong layer → check `report.html` texture strip |
| detail bake | 2nd texture in the same UV space multiplies the base | odd tint on a face part → `gcrip_composite` extras name the pair |
| clip → model | joint count (+ names for twins), same directory, name affinity | wrong actor animates → `--anim-map ANIM=MODEL` |
| expressions | BTP swaps only the diffuse slot; alternate must match size/format/name family | missing switch → the texture is on another slot / a different TEX1 order |
| bone names | keyword + hierarchy walk from hands/feet/head | unmapped bone → add the token to `rig._KEYWORDS` |
| eagl skin | weight row = 4 f32 summing to 1 with the bone index in the low mantissa byte; the counted pointer right before the `__const MATRIX4` tag | limbs tear when posed → a packet's slot table is elsewhere in the entry list; compare with `_packet_entries` order |
| ebo streams | a stream is an `i8` record with a 12-byte `{size, stride, offset}` header just before its bytes; kind by stride (12/6/3 positions or normals, 4 UV or RGBA, 8 f32 UV, 2 RGB565); the command buffer is the header-less buffer that chains as GX strips | a list drops out → its stride guess (prefix + index widths) missed; check `_layout` against the stream counts |
| p3d display list | stride = whatever chains through the zero-padded list; column widths (0/1/2 per attribute in GX order) picked by index ranges + compactness | a group drops out → the descriptor's second byte (2 = INDEX8, 3 = INDEX16, 1 = none) disagrees with the chain; check `_best_layout` |
| eurocom entity | version-keyed field table for the strip / vertex / uv / colour pointers and the count block; vertex record 12 or 16 B chosen so the block ends at the UV pointer | a game with an EDB version outside 170-252 → dump the entity words with their relative targets and add a row to `_layout` |
| mdl3 positions | 16-byte records (xyz + bone a, bone b, weight) when the model has bones, else 12; the first size the display-list indices fit wins | a rigged prop comes out as a spray of points → the record size guess flipped; check the block's indices against both sizes |
| mdl2 display list | four u16 index columns per vertex (pos, nrm, col, uv) into the single interleaved buffer; an index beyond the vertex count means "same as position" | wrong UVs → the column order is not GX order for that model; compare `_gather` columns with the vertex count |
| generic table | (offset,size) rows near the start or at a header pointer; 4-aligned, non-overlapping, ≥40 % coverage | members look wrong → the archive has a name/hash column layout `find_toc` mis-picked; write a plugin |
| gx scan | display lists chain at one stride; a position array exists for the biggest index; triangles are compact | slivers / spaghetti → wrong stride or array won the score; raise `_accept` limits or write a plugin |
