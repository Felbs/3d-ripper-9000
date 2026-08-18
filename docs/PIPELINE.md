# GCRip pipeline

How a GameCube disc image becomes textured, rigged, animated glTF you can play back in Blender.
Five diagrams, from coarse to fine. Module names are the real ones in `gcrip/`.

## 1. End to end

```mermaid
flowchart LR
    ISO["game.iso<br/>(your own dump)"] --> WALK["1  Disc walk<br/>gcrip.disc + gcrip.manifest"]
    WALK --> MAN["disc_manifest.json<br/>every file, format, hash"]
    MAN --> RIP["2  Rip loop<br/>gcrip.rip"]
    RIP --> J3D["3  Model parse<br/>gcrip.formats.j3d"]
    J3D --> ANIM["4  Clip matching<br/>rip._AnimIndex + j3d_anim"]
    ANIM --> GLTF["5  glTF export<br/>gcrip.export.gltf"]
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
    C -->|"RARC magic"| E["expand archive<br/>nodes / files / string table"]
    D --> C
    E --> C
    C -->|"leaf"| F["classify()<br/>magic first, then extension"]
    F --> G["ManifestEntry<br/>path, kind, fmt, sha1,<br/>container, offset, depth"]
    G --> H["disc_manifest.json"]
    style D fill:#e8f0e8,stroke:#5a7d5a
    style E fill:#e8f0e8,stroke:#5a7d5a
```

Kinds that matter downstream: `model` (BMD/BDL), `animation` (BCK/BTP/BVA…), `texture` (BTI/TPL).
Recursion goes eight archives deep; identical files are recognised by SHA-1.

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

## What is heuristic (and where to look when it's wrong)

| step | assumption | if wrong |
|---|---|---|
| base texture | first TEV stage sampling a vertex UV set, identity matrix, colour format | material shows the wrong layer → check `report.html` texture strip |
| detail bake | 2nd texture in the same UV space multiplies the base | odd tint on a face part → `gcrip_composite` extras name the pair |
| clip → model | joint count (+ names for twins), same directory, name affinity | wrong actor animates → `--anim-map ANIM=MODEL` |
| expressions | BTP swaps only the diffuse slot; alternate must match size/format/name family | missing switch → the texture is on another slot / a different TEX1 order |
| bone names | keyword + hierarchy walk from hands/feet/head | unmapped bone → add the token to `rig._KEYWORDS` |
