# RTX, AI PBR and physical water for the Wind Waker remake — a feasibility assessment

Written 2026-08-21 against the tree at `Z:/3d ripper`, Godot 4.7.2, a rip of GZLE01, and a
machine with 32C/64T, an RTX 4090 and 128 GB of RAM.

Everything below is marked as **measured** (I ran it against this repo), **verified**
(I checked it against primary documentation this session), **confident** (I believe it
strongly but did not re-check), or **speculation**. Where the answer is "no", it says no.

---

## 0. The short version

Three separate asks are tangled together, and they have three very different answers.

| Ask | Answer |
|---|---|
| "RTX shading" meaning **NVIDIA RTX Remix** | **Impossible.** Remix is a `d3d9.dll` replacement for fixed-function D3D8/9. It cannot hook a Godot game, and it cannot hook Dolphin either. Not "hard" — structurally out of scope. |
| "RTX shading" meaning **ray-traced lighting in Godot** | **Not in stock 4.7.2.** 4.7 shipped the low-level Vulkan RT *plumbing*, not a feature. There is an NVIDIA path-tracing **fork** of Godot (GDC 2026) which is real but is a fork, and it changes materials at a low level — i.e. exactly where our custom shaders live. Realistic upgrades today: switch to Forward+ and use SDFGI/SSIL/SSR/SSAO/volumetric fog, none of which we currently have because the project ships the **Compatibility** renderer. |
| **AI PBR maps from albedo** | **Real, offline, and cheap.** The genuinely usable half of RTX Remix — its Toolkit's AI Texture Tools, and the CC0 `PBRify_Remix` model set — run locally with no runtime and no game hook. A full pass over our texture set is hours, not days. |
| **PBR water** | **The best idea in the whole brief**, and it is not blocked on any of the above. |
| **Per-material smoothness / metallic** | **Half automatable.** Name-based classification is measurably weak in this game (see §3). Metallic in particular must be a curated list. |
| **Sheen on cloth** | Godot's `StandardMaterial3D` has no sheen lobe (verified). Custom shader. Expect the visual delta on Link's tunic to be near zero for a reason explained in §4. |

**My recommendation, in one paragraph.** Drop RTX Remix as a runtime idea entirely and keep only
its texture tooling. Do not build "Wind Waker in PBR"; build **"Wind Waker with a physical
specular lobe and real ambient occlusion, sitting on top of the game's own toon ramp"** — a
third shading mode, not a replacement. Do the water first, because it is the one place where
physical shading is unambiguously an improvement, and because *the ocean surface currently does
not render at all* (measured — see §5). And before any of it, parse BTK: one or two days of
work unfreezes every animated water, lava, waterfall and scrolling sky in the game, which will
do more for "this looks alive" than a month of PBR.

---

## 1. The texture and material census (measured)

Run over `Z:/3d ripper/out/rip/GZLE01/res` on 2026-08-21.

### Textures

```
PNG files on disk                15,859        176.7 MB      380.6 megapixels
Unique by SHA-1                   6,277                      189.0 megapixels
```

The 2.5x duplication is because textures are exported per-model into `<model>_tex/` folders
and the same archive texture appears in several models. Any AI pass should be keyed on content
hash, not path — that alone is a 2.5x saving.

Breaking the unique set down:

```
Unique textures                   6,277
  - UI / Msg / Fmap / placename     779   (fonts, map art, icons — do not PBR these)
  - toon-ramp placeholders            38   (the ZA/ZB 8x8 stubs; the real ramp is separate)
  - under 16 px                       85
  = candidate material textures    5,375        184.5 megapixels
```

Size distribution of those 5,375 (by longest side):

| ≤32 px | 64 | 120–128 | 192–256 | 336–512 | 552–1024 |
|---|---|---|---|---|---|
| 496 | 820 | 1,505 | 2,296 | 175 | 83 |

**So "all our textures" is 5,375 images, median around 128–256 px, 184.5 megapixels total.**
That is a small number. A 4x upscale takes it to ~2.95 gigapixels of output, which at four maps
(albedo RGB + normal RGB + ORM RGB, say) is roughly 15–25 GB of PNG on disk before Godot's
import compression. That is fine on this machine; the VRAM cost in-engine is the thing to watch,
not the disk.

### Materials

```
glTF models in the rip            1,856
Materials across them             8,946
Distinct material names           4,310
```

---

## 2. What "RTX" can actually mean here

### 2.1 RTX Remix — cannot be pointed at this project

**Verified this session** against NVIDIA's own compatibility wiki:

- Remix is *"primarily targeting DirectX 8 and 9 games with a fixed function pipeline"*. The
  runtime is `dxvk-remix`, a fork of DXVK, shipped as a **replacement `d3d9.dll`** that the
  game loads.
- *"Remix functions as a DirectX 9 replacer, and by itself cannot interact with OpenGL or
  DirectX 7, 8, etc."*
- Shader-based games are the hard blocker: *"With a shader graphics pipeline, the game can send
  the data in any format… This makes it very difficult to recreate the scene."* Games after
  ~2010 are *"almost certainly not going to work."*
- No support for D3D11, D3D12 or Vulkan.

Godot 4 renders through **Vulkan** (Forward+ / Mobile) or **OpenGL ES 3 / GL 3.3**
(Compatibility). Neither is a fixed-function D3D9 device, and all three are programmable-shader
pipelines by construction. **RTX Remix cannot wrap our remake. There is no configuration,
wrapper or flag that changes this.** Do not budget time for it.

### 2.2 RTX Remix on Dolphin — also no

Two independent reasons, and I want to be clear that the second is the fatal one.

1. **Practical.** A Dolphin forum thread on exactly this reports that when trying Dolphin 4 (the
   last era with a D3D9 backend), the Remix `d3d9.dll` *"doesn't get picked up and Remix never
   activates."* Modern Dolphin has D3D11 / D3D12 / Vulkan / OpenGL backends only — no D3D9 at
   all. **Confident.**
2. **Structural.** Even if a D3D9 Dolphin loaded the DLL, Remix reconstructs a scene by reading
   *fixed-function state*: the transform matrices, the light and material registers, and stable
   per-draw texture hashes. Dolphin has never used fixed function for GameCube TEV — its whole
   architecture is to **compile each TEV recipe into a generated pixel shader**. So Dolphin
   presents Remix with precisely the "shader pipeline, data in any format" case that the
   compatibility page calls the deal-breaker. Wind Waker's toon ramp in particular reaches the
   GPU as a *texture lookup indexed by a colour channel* (`GX_TG_SRTG`), which Remix has no way
   to interpret as lighting. **Confident, reasoned from the architecture rather than tested.**

I looked; I found no credible report of anyone getting Remix working on any emulator. If someone
has, I have not seen it.

### 2.3 Ray tracing inside Godot

**What is actually in stock Godot 4.7 (verified via multiple current reports, medium-high
confidence — I did not read the 4.7 changelog myself):**

- 4.7 landed **low-level Vulkan ray-tracing plumbing** in `RenderingDevice`: build acceleration
  structures, dispatch rays. That is a foundation, not a feature.
- There is **no ray-traced shadow, reflection or GI toggle**, and no path tracer.
- BLAS refit/update is **not exposed**, which means animated geometry cannot go into the
  acceleration structure at all. For a game that is mostly animated characters and a moving
  ocean, that is disqualifying even for a hand-rolled effect.
- There is no DXR path; Godot's RT work is Vulkan-only.

**The NVIDIA fork.** At GDC 2026 NVIDIA released a **path-tracing fork of Godot** (presented by
Leroy Sikkes), Vulkan-based, denoised with DLSS Ray Reconstruction. NVIDIA say they intend to
mature it and open a PR upstream. **Confident it exists; less confident about its current
state.** Two cautions specific to us:

- It is a fork requiring *"low level changes to the rendering system and materials"* — and our
  entire look lives in custom `ShaderMaterial`s. Custom shaders are the single most likely thing
  to break or to be silently ignored by a path tracer that wants BSDF parameters, not arbitrary
  fragment code. A path tracer would very likely render our `unshaded` toon materials as flat
  emissive surfaces, which is the opposite of the goal.
- It is not a build we could stay on. Every gcrip Godot export would be pinned to a fork.

**Verdict:** do not chase hardware RT. It buys nothing that SDFGI + SSR + SSAO + a good sky
probe don't buy for this art style, at a fraction of the integration risk.

### 2.4 The thing we should actually fix first — the renderer

**Measured.** `gcrip/godot.py:10102 _project_godot()` writes:

```
config/features=PackedStringArray("4.2")
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
```

The Compatibility renderer supports **none** of SDFGI, VoxelGI, SSIL, SSR, volumetric fog or
depth-prepass-dependent effects. So the honest statement is: *we currently have no modern
lighting available at all, and nobody has tried turning it on.* Flipping to `forward_plus` is a
two-line change and is the genuine prerequisite for every other item in this document.

That is not free — Forward+ is meaningfully heavier, and the scene as exported is one large
stage with a single `DirectionalLight3D` and a `WorldEnvironment` (`godot.py:9388`) that sets
only `background_mode`, `sky`, `ambient_light_source` and `tonemap_mode`. On a 4090 this is not
a concern; it is a concern if the project is ever meant to run elsewhere.

### 2.5 The wall that makes all of this moot for 55% of the game

`toon.gdshader` declares `render_mode unshaded`. **An unshaded material in Godot receives no
lights, no shadows, no GI, no SSIL and no SSR.** It is a pure fragment program.

Measured from `ww_rendering.json`'s corpus survey: **55% of materials do the toon lookup**
(149/272 use `GX_TG_SRTG` from `COLOR0`; 103/272 bind a `Z*` ramp placeholder).

So: switching on SDFGI today would change nothing for over half the game's surfaces, and would
change the *other* half inconsistently, producing a scene where terrain reacts to light and
characters do not. **PBR here is not a layer you add on top of the toon path. It is a
replacement for it.** This is the crux of §6, and it is why the plan in §7 introduces a third
mode rather than a boolean.

---

## 3. AI PBR generation from albedo

### 3.1 The classic, non-AI derivation

Luminance → height → normal via a Sobel/Scharr gradient, plus a roughness map from some function
of local contrast. This is what **Materialize** (free, Windows, Bounding Box Software) and
**AwesomeBump** (open source) do, and it's a dozen lines of NumPy — it does not need either
tool. It is instant, deterministic, and we could run it over all 5,375 textures in under a
minute on this machine.

It is also **wrong in a specific way that matters enormously for this game.** Luminance-to-normal
assumes brightness ≈ height. Wind Waker's textures are *hand-painted*: the dark band under
Link's hat brim is a painted shadow, not a groove; the light streak on the Master Sword is a
painted highlight, not a ridge. Feed those to a luminance-to-normal and you get a surface whose
bumps are wherever the artist painted light — which will catch real light from the *wrong*
direction and produce the shrink-wrapped, quilted look that gives away amateur remasters.

Worth building anyway as the **baseline to beat**, precisely because it costs an hour. If the
ML output is not visibly better than Sobel-on-luminance, the ML output is not worth 20 GB.

### 3.2 What ML actually gets us, offline, on a 4090

**`PBRify_Remix` (Kim2091) — highest confidence, and my recommendation.** Verified this session:
a set of models that *"1. Upscale 2. Generate Normal Map 3. Generate Roughness Map 4. Generate
Height Map"*, distributed as a **chaiNNer** workflow, **CC0 licensed**, and explicitly *"trained
exclusively on high quality CC0 content from ambientCG"*. Being chaiNNer models means they are
ESRGAN-family `.pth` files, which means **`spandrel`** (the PyPI library chaiNNer's model loading
was extracted into) can load and run them from a plain Python script — no GUI, no chaiNNer, no
network. Verified that `spandrel` does exactly this via `ModelLoader().load_from_file(...)`,
with the caveat that spandrel deliberately ships *no* batching/tiling helper, so we write the
inference loop ourselves (that's maybe 80 lines and we already have `gcrip/export/png.py`).

This is the single cleanest fit: permissive licence, offline, scriptable, small models, and
trained on the kind of tileable surface material we mostly have.

**RTX Remix Toolkit's AI Texture Tools — real, and usable without the runtime.** Verified: the
Toolkit is `NVIDIAGameWorks/toolkit-remix`, **Apache-2.0**. Its AI texture tools *"analyze
low-resolution textures from classic games, generate physically accurate materials — including
normal and roughness maps — and upscale the resolution by up to 4X"*, running on Tensor Cores.
Crucially, NVIDIA's own how-to says: *"go to the AI Texture tab, enter the path to your texture
file, add it to the queue"* — **no capture and no game hook required.** There is also
`NVIDIAGameWorks/ComfyUI-RTX-Remix` (Apache-2.0), which exposes Remix operations as ComfyUI
nodes and ships a **`PBRify_Remix` example workflow that "generates albedo, normal, roughness
and height maps"**; ComfyUI has an HTTP API, so that route batch-scripts headlessly.

**Uncertainties I want to flag honestly here:** NVIDIA's documentation pages returned HTTP 403
to my fetches, so the quotes above come from search-result excerpts of those pages rather than
from my own read of them. I did *not* verify the Toolkit's install footprint (it is an Omniverse
Kit app, which historically means a multi-GB install and an NVIDIA account), whether the AI
Texture queue accepts a directory rather than one file at a time, or its VRAM requirement. If
the Toolkit turns out to be awkward, the `PBRify_Remix` + `spandrel` route gets the same models
with none of the install.

**Academic / commercial single-image SVBRDF.** There is a real research line here —
Deschaintre et al. 2018, *Single-Image SVBRDF Capture with a Rendering-Aware Deep Network*
(SIGGRAPH), and successors — and Adobe's Substance 3D Sampler has an "Image to Material (AI
Powered)" mode. **Confident these exist; not confident either is useful to us.** The research
models are trained on *flash-lit photographs of real materials* and their whole job is to undo a
camera flash. Hand-painted 128×128 cel textures are so far outside that distribution that I
expect garbage, and the released code is old enough that getting it running offline in 2026 is
its own project. Substance is a paid subscription and I am **unsure** whether its AI delighter
is exposed to the Substance Automation Toolkit for batch use. I would not name a HuggingFace
model ID here because I am not confident enough in any specific one to send you looking for it.

### 3.3 Throughput on 5,375 textures / 184.5 megapixels

**This is an estimate, not a benchmark.** I did not run any model. It is anchored on published
Real-ESRGAN figures (roughly 0.5–1 Mpix/s for a full RRDB model on a 3090-class card at fp16,
call it ~1.2 Mpix/s on a 4090; compact/SRVGG architectures run roughly an order of magnitude
faster).

- **Upscale pass** at 1x input resolution: 184.5 Mpix ÷ ~1.2 Mpix/s ≈ **3 minutes**, plus
  per-image overhead (5,375 images × ~50 ms ≈ 4.5 min) → call it **10 minutes**.
- **Normal / roughness / height passes**, if each runs on the *4x-upscaled* image: 2.95 Gpix per
  pass ÷ ~1.2 Mpix/s ≈ **40 minutes each**, so ~2 hours for three.
- **Total: roughly 30 minutes to 3 hours** for a full cold run of all four maps over the whole
  game, with a ±1-order-of-magnitude error bar.

The important design point is not the wall clock, it's that **the run must be incremental and
content-hash keyed**, so a re-rip doesn't redo it and so per-class parameter tweaks only redo
the affected class. That's a cache directory keyed by SHA-1 — which we already compute.

---

## 4. Per-material smoothness, metallic, sheen, and a principled shader

### 4.1 How far automatic classification actually goes — measured, and it is sobering

I swept all 8,946 material names in the rip:

```
Maya-default names (lambertNN / blinnNN / phongNN)   1,728   (19.3%)
Hit any romaji/English material keyword              2,109   (23.6%)
  of which "metal"-ish (kin/tetsu/ken/iron/haga)        87   (1.0%)
Matched nothing                                      5,109   (57.1%)
```

The most common material names in the entire rip are `lambert2_v` (73), `sc_eye` (58),
`lambert3_v` (53), `lambert7_v` (44). **One material name in five is a Maya default, and only
87 materials out of 8,946 look metal by name.** There is no plausible world in which the game's
metal is 1% of its materials — the swords, shields, chests, armour, Gohdan and every gear in the
Tower of the Gods are in the other 99%.

**Conclusion: name-based classification is not viable as the primary signal in this game.**
Anyone who claims otherwise has not counted.

The signals that *are* strong, ranked:

1. **Archive / actor identity — the best handle, and we already have it.**
   `gcrip/data/ww_actors.py` is a 511-line actor → `(archive, model)` table. A material in
   `Object/Link.arc` is Link; one in `Object/Swordss.arc` is a sword. Roughly 150 archives cover
   everything the player ever looks at up close. This turns "classify 8,946 materials" into
   "label ~150 archives", which is an afternoon of work, not a research problem.
2. **The parsed TEV recipe** (now available since the MAT3 work). From the corpus survey:
   - `GX_TG_SRTG` present (55%) → the game itself treats this as a cel-shaded organic/character
     surface. Strong prior for *low* specular.
   - `lighting=off, matSrc=VTX` (39/272) → terrain. Rough, never metal.
   - `blend=BLEND` (100/272) + `zwrite=false` → transparent FX, water, glass. Never metal.
   - `alpha_test on` (65/272) → foliage/cutout. Rough, double-sided, no specular.
   - A non-white `K1` (142/272) is the point-light tint, not a material property — do not read it
     as "coloured metal".
3. **Pixel statistics** — saturation, hue spread, edge density, alpha coverage, whether there is
   a narrow bright streak (painted specular). Useful as a tiebreak, not a decider.
4. **A curated override table.** This is where metallic lives.

### 4.2 Metallic specifically — this must be a hand-curated list

Metallic is close to a binary physical property and getting it wrong is catastrophic rather than
subtle: `metallic = 1` with nothing to reflect renders **black**, and metallic = 1 on something
that isn't metal renders as a coloured mirror. Meanwhile Wind Waker **paints its metal**. The
Master Sword blade texture is a pale grey gradient with a painted white streak; nothing in the
pixels, and nothing in the TEV recipe, distinguishes it from painted stone or painted cloth. Any
classifier that claims to detect metal from a WW albedo is guessing.

The good news is that the list is short and enumerable, because the game's metal is concentrated
in equipment and dungeon machinery:

- Link's sword(s) and shield(s), the Skull Hammer, the Grappling Hook, the Hookshot, the Boomerang
- Treasure chests and their fittings, keys, the Bombs' casings
- Tower of the Gods: the gears, servos and Command Melody statues
- Gohdan, Helmaroc's mask, Darknut armour, Armos, Moblin/Bokoblin weapons
- Ganon's Tower fittings and the Master Sword pedestal

**Recommendation:** a new `gcrip/data/ww_materials.json` keyed by `(archive, material_name)`,
following the pattern already established by `ww_rendering.json` — including its `honesty`
block, since a curated table should say which entries were eyeballed and which were guessed.
Fall back to a classifier for anything not in the table, and have the classifier default to
"dielectric, rough" — the safe direction to be wrong in.

A sane taxonomy for this game, with defaults:

| class | metallic | roughness | notes |
|---|---|---|---|
| `skin` | 0 | 0.55 | subsurface off; WW faces are flat by design |
| `eye` | 0 | 0.15 | the one place a specular dot genuinely helps |
| `cloth` | 0 | 0.75 | sheen candidate (§4.4) |
| `foliage` | 0 | 0.85 | double-sided, alpha-tested, backlight instead of SSS |
| `stone` / `terrain` | 0 | 0.85 | AO is the win here, not specular |
| `wood` | 0 | 0.7 | polished wood (ship hull, furniture) 0.45 |
| `metal` | **1** | 0.25–0.4 | **curated only** |
| `glass` / `gem` | 0 | 0.05 | transmission, not just transparency |
| `water` | 0 | 0.02–0.08 | see §5 |
| `fx` / `emissive` | 0 | — | unshaded, always; never touch these |
| `shadow_blob` | — | — | leave alone entirely (68 materials named `bj_shadow`/`kage`) |

### 4.3 Godot has no sheen — confirmed

**Verified** against the `BaseMaterial3D` class reference. The full feature list is:
`EMISSION`, `NORMAL_MAPPING`, `RIM`, `CLEARCOAT`, `ANISOTROPY`, `AMBIENT_OCCLUSION`,
`HEIGHT_MAPPING`, `SUBSURFACE_SCATTERING`, `SUBSURFACE_TRANSMITTANCE`, `BACKLIGHT`,
`REFRACTION`, `DETAIL`, `BENT_NORMAL_MAPPING`. **There is no `FEATURE_SHEEN`.** So sheen means a
custom `ShaderMaterial`. (I also believe Godot's glTF importer does not implement
`KHR_materials_sheen` — **medium confidence**, worth a five-minute check before relying on it.)

### 4.4 An honest warning about sheen on Link's tunic

Sheen is a grazing-angle retroreflective lobe from *fibres*. It needs a micro-normal to grab
onto. Link's tunic in Wind Waker has **no fabric texture at all** — it is flat green with a
painted fold. Put a Charlie sheen lobe on a smooth flat-green cylinder and what you get is a
uniform brightening toward the silhouette, which is… rim lighting, which Godot already gives you
for free via `FEATURE_RIM`.

The only way to make sheen *read* on WW cloth is to first generate a fabric micro-normal — and
that is precisely the thing the AI normal generator would be inventing out of nothing, on a
texture with no weave in it. That is not "recovering detail", it is "adding detail the art
director deliberately omitted".

**So:** implement sheen (it is genuinely ~15 lines), but spend it where there is real woven
texture — **the sail**, Rito wing feathers, tapestries and banners, the Hero's Charm cloth — and
expect near-zero honest difference on Link himself. If Link's tunic needs to feel like cloth, a
hand-authored 64×64 tiling weave normal at 0.15 strength will beat any AI output, and it is
twenty minutes of work.

### 4.5 The principled shader — a concrete design

We do not need to invent a lobe model; we need to assemble the right four, which is a solved
problem with well-defined references. The ones I am **confident** of:

- **Diffuse / overall structure:** Burley 2012, *Physically-Based Shading at Disney* (the
  "principled"/Disney BRDF that Blender's node is named after).
- **Specular NDF:** GGX / Trowbridge-Reitz, as introduced to graphics by Walter et al. 2007.
- **Visibility:** Smith height-correlated masking-shadowing, Heitz 2014. (Godot's built-in
  `specular_schlick_ggx` mode is already this family.)
- **Fresnel:** Schlick 1994, `F = F0 + (1 - F0)(1 - cos θ)^5`.
- **Sheen:** the **Charlie** distribution from **Conty Estevez & Kulla 2017, *Production
  Friendly Microfacet Sheen BRDF*** (Imageworks, SIGGRAPH 2017 course). **Verified** this
  session that this is exactly what **`KHR_materials_sheen`** specifies — the glTF extension
  cites Conty & Kulla, uses `r = sheenRoughness²`, and pairs the Charlie D term with the
  Ashikhmin visibility term. Using the glTF formulation means our output is a standard other
  tools understand.

One point worth making because the user asked for "Blender's Principled": **Blender 4.0+ does
not use Charlie.** Verified: Blender 4.0 renamed Velvet BSDF to Sheen BSDF and made "Microfiber"
the default, implementing **Zeltner, Burley & Chiang 2022, *Practical Multiple-Scattering Sheen
Using Linearly Transformed Cosines*** — and *"this BSDF is currently only supported in Cycles;
in EEVEE it will be rendered as a diffuse BSDF."* So even Blender's own real-time renderer
does not do the "correct" sheen. For a game shader, **Charlie is the right call**, and matching
glTF is worth more than matching Cycles.

**On "photo-accurate Fresnel".** This deserves a straight answer rather than a yes.

- Schlick's approximation is *already* accurate to well under 1% for dielectrics in the
  IOR 1.3–1.6 range that covers water, skin, cloth, wood and stone. There is no perceptible win
  from the exact Fresnel equations for any of those. Swapping Schlick for exact Fresnel would be
  measurable in a plot and invisible on screen.
- Where Schlick *is* genuinely wrong is **metals**, because conductors have a complex IOR and
  their reflectance changes *hue* toward grazing (gold goes pale, copper goes pink-white).
  Schlick with `F0 = albedo` misses this. The standard fix is an F82-style tint term — I believe
  this is **Kutz et al. 2021, "Novel Aspects of the Adobe Standard Material"** (**medium
  confidence** on the exact citation). Given that our metal list is curated and small, this is a
  nice-to-have, not a blocker.
- **What actually makes a surface read as physically correct at grazing angles is not the
  Fresnel curve — it is having something real to reflect.** A perfect Fresnel term multiplying a
  flat ambient colour looks like a flat ambient colour. The wins, in order of impact: a real sky
  cubemap / `ReflectionProbe`, screen-space reflections for the near field, correct roughness
  *increase with distance* so distant specular doesn't alias, and not clamping the reflection to
  LDR before tonemapping. "Photo-accurate Fresnel" without those is a rounding error.

**Shader skeleton** (`ww_pbr.gdshader`, living beside `toon.gdshader`):

```glsl
shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, specular_schlick_ggx;

// -- shared with toon.gdshader so a material can be swapped between the two --
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap;
uniform vec4  albedo_col : source_color = vec4(1.0);
uniform bool  has_tex = true;
uniform float alpha_scissor = 0.0;

// -- the toon half, kept so "hybrid" mode can use the game's own diffuse --
uniform sampler2D toon_ramp : filter_linear;
uniform vec3  c0 : source_color;      // TEV register 0 - the env "ambient"
uniform vec3  k0 : source_color;      // konst 0        - the env "light"
uniform int   diffuse_mode = 0;       // 0 = WW ramp, 1 = Lambert/Burley

// -- the physical half --
uniform sampler2D normal_tex : hint_normal;
uniform float normal_strength = 0.5;  // per-class; NEVER 1.0 on generated normals
uniform sampler2D orm_tex;            // R = ao, G = roughness, B = metallic
uniform float roughness_min = 0.2;    // per-class clamp on the generated roughness
uniform float roughness_max = 0.9;
uniform float specular = 0.5;         // -> F0 = 0.08 * specular for dielectrics
uniform vec3  sheen_color : source_color = vec3(0.0);
uniform float sheen_roughness = 0.3;
uniform float clearcoat = 0.0;
uniform float clearcoat_roughness = 0.03;
```

with a custom `light()` implementing:

```
F0    = mix(vec3(0.08 * specular), ALBEDO, metallic)
F     = F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0)          // Schlick
D     = GGX(NdotH, roughness)
Vis   = Smith height-correlated (Heitz 2014)
spec  = D * Vis * F
diff  = (diffuse_mode == 0) ? mix(c0, k0, ramp(NdotL)) * ALBEDO   // WW's own diffuse
                            : ALBEDO * NdotL * (1.0 - metallic)
sheen = charlieD(NdotH, sheen_roughness) * ashikhminVis(NdotL, NdotV) * sheen_color
coat  = clearcoat * GGX(NdotH, clearcoat_roughness) * schlick(0.04, VdotH)
DIFFUSE_LIGHT  += diff * (1.0 - F) * ATTENUATION * LIGHT_COLOR
SPECULAR_LIGHT += (spec + sheen + coat) * ATTENUATION * LIGHT_COLOR
```

**Two warnings about `light()` in Godot**, both worth knowing before committing:

1. Writing a `light()` function **replaces Godot's entire per-light loop for that material.**
   Everything the built-in shader did — shadow filtering, light attenuation curves, SSS,
   backlight — becomes ours. That is the price of a custom BRDF and it is not small.
2. `light()` governs *analytic lights only*. The ambient/GI contribution arrives separately via
   `AMBIENT_LIGHT` / `SPECULAR_LIGHT` in `fragment()`, and I am **only medium confident** about
   exactly how 4.7 feeds those for a custom-light material. Prototype this on one object before
   converting anything.

The `hybrid` mode above — **WW's own ramp as the diffuse term, plus a physical specular / sheen /
Fresnel lobe on top** — is, in my view, the single best answer to everything the user has asked
for. It keeps the hard terminator (it *is* the hard terminator, byte-for-byte), and it puts real
physical response exactly where the user wants it: metal, water, glass, eyes, wet stone.

---

## 5. Water

This is the strongest part of the proposal and it should go first. But the current state is not
what one would assume.

### 5.1 Measured current state: there is no ocean surface

`gcrip/godot.py:5174–5234` implements `sea_height(x, z)` — the four-cosine sum with the mined
constants (amplitudes 2.5, wavelengths 13600/11200/8800/6400, phases 0/4000/8000/12000, periods
200/190/210/180 frames), the `wave_max` lookup from MULT (`0/5/15/30/50`, open sea = 30), and the
1/100-per-frame easing of `sea_cur_scale`. All correct, all matching memRip's `sailing-spec.md`.

It is used by `Player.water_surface()`, the camera clamp, the salvage crane and the King of Red
Lions' buoyancy spring and four wave probes. **Nothing renders it.** There is no `PlaneMesh`, no
`ArrayMesh`, no ocean node anywhere in `godot.py`. Sea stages get `water_level = 0.0` and
whatever water geometry happens to be inside the ripped room glTFs.

So the first ticket is not "make the water PBR", it is **"make the water exist"** — and that is
a lucky ordering, because it means the shading decision is made once, at build time, rather than
retrofitted.

### 5.2 What the game actually does (from memRip, high confidence)

`daSea_packet_c::execute(playerPos)` rebuilds a **65 × 65 heightfield of 800-unit cells** centred
on the player (window ±25600), and `draw()` renders that same table — so physics and visuals
agree by construction. Beyond it, a **flat skirt of 225000-unit quads out to ±450000**.
UV = world XZ / 2000. `B_SEA_TEX0AND2` is bound twice (LOD bias −0.9 and +1.0; second layer
scaled 1.5, offset (0.2, −0.2)) with `B_WYURAYURA_TEX1` as an **indirect warp** (matrix 0.3,
v scrolling 1/300 per frame — one cycle per 10 s). TEV: `C0 + K0·tex0 + K1·tex2 + C2·alpha`,
with `K0 = lerp(dif, amb, flat²)` and `K1 = dif · (1 − flat²/10)`, colours from
`dKy_get_seacolor`. **Opaque, additive, no Fresnel, no reflection, no refraction.** Whitecaps
are 300 `usonami` sprites spawned 20000–22000 units from the camera; shoreline foam is *baked
into the island room materials*.

Note what this means: the sea's animation is driven by a **per-frame indirect-matrix update in
code**, not by BTK. So the Great Sea is not one of the BTK-frozen surfaces.

### 5.3 What *is* BTK-frozen: interior and island water

The other water case, measured in `ww_rendering.json`:

- `SC_01_mizu` — `numTevStages: 1`, **zero textures**, entire appearance is konst `(70, 90, 150)`.
  gcrip exported this **white** until the `flat_color()` fix; there were 11 such materials.
- `SC_01_mizuB_v_x` — 4 stages, `Txa_nami_01` bound twice through TEXMTX0/TEXMTX1 plus
  `Txa_sirokuro_a` as a mask. *"colour is just TEVREG0 (white) passed down all four stages; the
  ENTIRE look is in the alpha chain: `alpha = ((wave1.a·K0) + wave2.a·K0) · mask.a · vertexAlpha`."*
  The two TEXMTX translations `(-0.03, -0.97)` and `(0.03, -0.97)` are **the BTK's animated
  scroll frozen at frame 0.**

**This is the actual reason our water is static, and fixing it does not need PBR.** It needs
BTK/TTK1 parsed and a `mat3 tex_mtx[8]` uniform. `ww_rendering.json` records that the BTK layout
has already been validated arithmetically against real files (with the note that only 5 of the
0x36 entry's 9 sub-tracks are read). This is a one-to-two-day job that unfreezes water, lava,
waterfalls, scrolling skies and animated eyes across the entire game. **Highest value-per-hour
item in this whole document, and it is not on the PBR track at all.**

### 5.4 Recommended approach — the Great Sea

Build a **129 × 129 grid mesh (or keep 65 × 65 to match the game exactly) re-centred on the
camera each frame**, evaluate the four-cosine sum **in the vertex shader**, and — critically —
**share the wave constants with the CPU `sea_height()`**, emitted from one place in `godot.py`
so the visual surface and the boat's buoyancy can never drift apart. Analytic normals come free
from the cosine derivatives; the swell needs no normal map at all. A separate ring mesh handles
the skirt.

Then two shading variants behind the same toggle:

**Cel variant** (ships first, matches the game): `C0 + K0·tex0 + K1·tex2`, opaque, the WYURAYURA
scroll as a UV warp, `usonami` whitecap particles.

**PBR variant:**
- `metallic = 0`, `F0 = 0.02` (IOR 1.333 — this is the correct value and it is *low*; water is
  barely reflective face-on and almost fully reflective at grazing, which is the entire visual
  signature of water)
- **Schlick Fresnel against a real sky reflection.** The scene already has a `Sky` sub-resource
  (`godot.py:9385`); a `ReflectionProbe` or a direct sky sample gets us a reflection worth
  Fresnel-ing. Add SSR in Forward+ for the near field, and accept that SSR fails on anything
  off-screen — for an ocean under an empty sky, the sky probe carries almost all of it.
- **Depth-based absorption**: sample `DEPTH_TEXTURE`, tint by `exp(-depth · extinction)` toward
  a deep-blue. This is what turns a blue plane into water with volume, and it is nearly free.
- **Screen-space refraction** via `SCREEN_TEXTURE` for shallows.
- **Shore foam from depth difference** — a `smoothstep` on `(sceneDepth − waterDepth)`. This
  replaces the game's *baked-into-the-island* foam, so island materials may need their painted
  foam suppressed to avoid doubling.
- **Roughness that increases with distance.** I want to flag this loudly: a smooth specular
  ocean at GameCube world scale (units ≈ 1 cm; horizon at 450,000 units) will alias into a field
  of crawling glitter unless the normal variance is folded into roughness with distance — a
  Toksvig/LEAN-style term, or in the cheap version just
  `roughness = mix(base, 0.4, saturate(dist / 200000))`. **This one detail is the difference
  between "looks like the sea" and "looks like tinfoil."** It is also the mistake almost every
  first attempt makes.

### 5.5 Interior water

Don't build a second ocean. After BTK is parsed, interior water is a small `ShaderMaterial`:
two scrolling alpha layers, a mask, vertex alpha, `blend_mix`, `depth_draw` off — i.e. exactly
what the TEV recipe already says, driven by real BTK tracks. Add Fresnel + depth tint only for
the handful of surfaces where it earns its place (the Great Fairy fountains, Jabun's cave, the
Forsaken Fortress moat). Do **not** apply it to every `mizu` material in the game — most of them
are 200 units of decorative pond that nobody looks at, and each one costs a screen-texture read.

---

## 6. The art-direction tension — the part that matters

I have to be blunt here, because I think the obvious version of this project makes the game look
worse and the good version is genuinely exciting.

### 6.1 Why straight PBR fights this specific game

**The textures are already lit.** Wind Waker's albedo maps contain painted ambient occlusion,
painted rim light, painted shadow under Link's hat, a painted specular streak on the sword.
Multiply painted lighting by physical lighting and you get double-darkening in the creases,
grey-brown mud where two shadow terms stack, and a faintly greasy look on skin. This is the
canonical failure mode of stylised-game remasters and it is entirely predictable from the
content of the textures. Any serious PBR path needs a **de-lighting** step in front of it — and
de-lighting a hand-painted texture is a harder problem than generating a normal map from one.

**The generated normals will fight the painted shadows.** Per §3.1: luminance-to-normal turns
every painted shadow into a groove. Those grooves then catch the *dynamic* light from a
different direction than the painted shadow implies. The eye reads the contradiction
immediately, even if it can't name it.

**The geometry is built for flat shading.** Link's face is a few hundred triangles with the
expression in the texture. Under a hard toon ramp that reads as deliberate stylisation. Under a
specular lobe it reads as low-poly — every facet gets its own highlight. The same is true of the
sea: an 800-unit quad grid is invisible as a flat sheet and unmissable once it has a specular
response.

**The toon ramp is not a lighting *modifier*, it is the lighting *model*.** `toon.gdshader` is
`render_mode unshaded`; the ramp is `smoothstep(0.467, 0.537, N·L)` and the two endpoints are
the environment's own C0/K0, rewritten every frame from the Pale table. There is no seam to
insert PBR into. It's replace-or-nothing — hence the third-mode design.

**And the game never had ambient in the normal sense.** *"The game never calls
`GXSetChanAmbColor` at all — Wind Waker's 'ambient' IS TEV register 0."* Turning on SDFGI adds
an ambient term to a game whose art was tuned assuming a single flat authored one. Everything
will get lighter and lower-contrast, and the flatness that is the whole point will soften.

### 6.2 The evidence from people who already tried

- **Wind Waker HD** (Wii U, 2013) is Nintendo's own attempt at exactly this — bloom,
  self-shadowing, real ambient occlusion, higher-contrast lighting. It is **divisive**, with a
  substantial share of players preferring the GameCube original specifically because the added
  lighting flattened the flatness and the bloom washed out the palette. I state this as a widely
  held view, not as fact; but it is the single most relevant data point available, and it comes
  from the people who made the art.
- **Ishiiruka-Dolphin** — a Dolphin fork whose **"material maps"** feature lets HD texture packs
  ship normal and specular maps for GameCube games. This is the closest existing precedent for
  exactly what is being proposed, and it has been available for years. It is instructive that it
  never produced a definitive "PBR Wind Waker" that the community rallied behind. **Confident
  the feature exists; the inference about why nothing definitive came of it is mine.**
- **Henriko Magnifico's Wind Waker 4K pack** and similar community upscales are the popular
  path, and they are notable for what they *don't* do: they upscale and clean, they do not
  re-light. The community consensus revealed by what actually gets downloaded is "sharper, same
  look."
- **Breath of the Wild** is the constructive reference. It is a cel-shaded Zelda with a
  hard-ish terminator that *also* has real physical specular on metal, real reflections, real
  sky-driven ambient and real AO. It is proof the combination works — and note precisely which
  half it kept physical.

### 6.3 The version I would actually build

**Keep the ramp as the diffuse. Add physics only where physics is missing.**

1. **Ambient occlusion and contact shadows first.** These are the things WW paints by hand and
   physically cannot do dynamically — a barrel casting no contact shadow is the most dated thing
   about the original. AO costs nothing stylistically because it darkens where the artist
   already darkened.
2. **Feed the sky into C0.** The toon shader's `c0` is currently a uniform pushed per frame by
   `toon_tick()` from the Pale table. Replace the constant with an SH projection of the actual
   sky and the world starts to feel *lit* — different in a cave, different at sunset — with
   every surface still perfectly flat. This is the biggest "modern lighting" win per unit of
   style risk in the entire document, and it is maybe fifty lines.
3. **Physical specular only on the classes that need it**: metal (curated), water, glass, eyes,
   wet stone, polished wood. That's a few hundred materials out of 8,946.
4. **Sheen only where there's a weave**: the sail, feathers, banners.
5. **Then, and only then**, offer a full-PBR mode as a *comparison* toggle, so the user can look
   at both and decide. That's what §7 builds toward, and I would genuinely like to see it — I
   just don't think it should be the default.

---

## 7. Staged plan

Each phase is independently shippable and independently revertible. The cel path stays
byte-identical throughout — that is a hard requirement, not a nice-to-have.

### Phase 0 — Forward+ (half a day, low risk, unblocks everything)

`gcrip/godot.py:10102 _project_godot()`: `renderer/rendering_method="forward_plus"`, and bump
`config/features` from `"4.2"` to the real target. Extend the `Environment` sub-resource at
`godot.py:9388` with SSAO and a modest glow. New CLI flag `--fx=off|low|high` in
`gcrip/cli.py` so the Compatibility path remains reachable.

*Cost:* Forward+ is heavier; irrelevant on a 4090, relevant if this ever ships elsewhere.
*Risk:* anything implicitly relying on Compatibility behaviour. Screenshot before/after.

### Phase 1 — BTK (1–2 days, highest value in the document, no PBR involved)

Parse TTK1 in `gcrip/formats/j3d_anim.py` (layout already validated arithmetically per
`ww_rendering.json`). Plumb the resulting texture matrices out through
`gcrip/export/gltf.py:263 _material` as `extras`, and into a `mat3 tex_mtx[8]` uniform on the
toon/uber shader in `godot.py`.

*Buys:* animated interior water, lava, waterfalls, scrolling skies, blinking eyes — everywhere.
*Independent of every other phase.*

### Phase 2 — the Great Sea surface (2–3 days)

New sea mesh + vertex-shader wave evaluation sharing `SEA_WAVES` (`godot.py:5176`) with the CPU
`sea_height()`. Cel variant first, matching `C0 + K0·tex0 + K1·tex2`. Then `--water=pbr` adding
Fresnel/sky reflection/depth tint/refraction/foam, with the distance-roughness term from §5.4.

*Buys:* the ocean actually renders. This is currently missing entirely.

### Phase 3 — material taxonomy (2–4 days, mostly curation)

New `gcrip/material.py` (classifier) + `gcrip/data/ww_materials.json` (curated overrides keyed
by `archive` + `material_name`, with an `honesty` block like `ww_rendering.json` has). Inputs:
`WW_ACTORS` archive identity, the parsed TEV recipe, blend/alpha state, pixel statistics. Output:
a `gcrip_class` string emitted into glTF `extras` from `gcrip/export/gltf.py:263`.

Nothing renders differently in this phase. Deliverable is a **contact sheet per class** so the
labels can be eyeballed in an afternoon — which is the only way this stays honest.

*Metallic comes entirely from the curated table. Do not let the classifier invent metal.*

### Phase 4 — the AI PBR bake (1 day plumbing + 0.5–3 h compute)

New `gcrip/pbr.py` and a `gcrip pbr` verb in `gcrip/cli.py`. Loads the `PBRify_Remix` CC0 models
via `spandrel`, walks the **6,277 unique-by-hash** textures, skips the 779 UI + 38 ramps + 85
tiny ones, writes `<name>_n.png` and `<name>_orm.png` beside the albedo, caches by SHA-1 so it's
incremental. The Phase-3 class picks per-class `normal_strength` and clamps the generated
roughness into the class's range — **never take the model's roughness raw.**

Ship the Sobel-on-luminance baseline in the same module behind `--pbr=classic`, so there's an
honest A/B. If ML doesn't beat Sobel visibly, that is a real and useful finding.

### Phase 5 — `ww_pbr.gdshader` (3–5 days)

The shader from §4.5, beside `toon.gdshader` (both emitted from `godot.py` — `_TOON_SHADER` is
at `:7961`, written at `:10768`). Refactor `_toon_material()` (`godot.py:5767`) into
`_shade_material(src, mode)` with three modes: `toon` / `hybrid` / `pbr`. The `_toon_cache`
dictionary is already keyed on the source material, so the swap lands in exactly one place.

Toggle: **F6 cycles three modes instead of flipping a boolean** (`toon_input()` at
`godot.py:5833`, `set_toon()` at `:5816`). CLI becomes `--shade=toon|hybrid|pbr`, with
`--no-toon` kept as an alias for `--shade=pbr` so nothing that exists today breaks. Print the
mode name on switch — with three modes, "on/off" is no longer a useful message.

### Phase 6 — evaluate honestly

Six fixed vantage points (Outset beach, the lookout, open sea at noon, open sea at sunset,
Dragon Roost interior, a Darknut) × three modes, via the existing `--shot=<actor>` harness.
Look at them side by side before deciding what the default is. Per the memory note on
play-test verification: headless smoke tests will not catch this — someone has to look.

### Rough total

Phases 0–2 (Forward+, BTK, the sea): **4–6 days**, and I would do these regardless of any
decision about PBR — they are straight wins.
Phases 3–6 (taxonomy, bake, shader, evaluation): **7–12 days**, and this is the part that is a
genuine bet on the art direction.

---

## 8. Confidence ledger

**Measured by me, this session, against this repo:**
- 15,859 PNGs / 176.7 MB / 380.6 Mpix; 6,277 unique by SHA-1; 5,375 candidate material textures
  at 184.5 Mpix.
- 1,856 glTF models, 8,946 materials, 4,310 distinct material names, 19.3% Maya-default names,
  87 materials matching a metal keyword.
- The project ships `renderer/rendering_method="gl_compatibility"` and
  `config/features=PackedStringArray("4.2")`.
- `toon.gdshader` is `render_mode unshaded`.
- There is **no ocean surface mesh** in the Godot export; `sea_height()` is physics-only.

**Verified against primary documentation this session:**
- RTX Remix targets fixed-function D3D8/9, cannot interact with OpenGL, does not support D3D11/12
  or Vulkan, and fails on shader pipelines.
- `BaseMaterial3D` has no sheen feature.
- `KHR_materials_sheen` uses the Charlie distribution from Conty Estevez & Kulla 2017.
- Blender 4.0+ Principled sheen is Zeltner/Burley/Chiang 2022 microfiber, Cycles-only.
- `PBRify_Remix` is CC0, chaiNNer-based, trained on ambientCG content; `spandrel` loads chaiNNer
  `.pth` models from Python but ships no inference loop.
- `ComfyUI-RTX-Remix` and `toolkit-remix` are both Apache-2.0.

**Confident but not re-checked:** Godot 4.7's RT plumbing details (acceleration structures
exposed, BLAS refit not, no RT effects shipped); the NVIDIA Godot path-tracing fork from GDC
2026; Dolphin having no D3D9 backend and generating pixel shaders from TEV; Ishiiruka's material
maps; Wind Waker HD being divisive.

**The three things I am least sure about, in order:**

1. **Whether the AI-generated normals will look good or terrible on this specific art.** This is
   the load-bearing uncertainty of the entire PBR proposal and I cannot resolve it by reasoning
   — every argument in §6.1 says "bad", but the PBRify models are trained on clean tileable
   surface material and a large share of WW's 5,375 textures *are* clean tileable surface
   material (stone, wood, cloth, sand). It might be fine on terrain and awful on characters.
   **Cheapest way to find out: run Phase 4 on twenty hand-picked textures before building
   anything else.** Half a day, and it de-risks two weeks.
2. **The RTX Remix Toolkit's practical usability offline.** NVIDIA's docs 403'd my fetches, so
   the "enter the path to your texture file, add it to the queue" quote is from a search excerpt
   rather than my own read. I do not know the install footprint (it is an Omniverse Kit app),
   whether it needs an NVIDIA account, its VRAM requirement, or whether the AI Texture queue
   accepts a directory. If it is awkward, the `PBRify_Remix` + `spandrel` route gets the same
   models with none of the install — which is why I recommended that route rather than this one.
3. **How Godot 4.7 feeds ambient/GI to a material with a custom `light()` function.** The whole
   hybrid-shader design assumes we can take over the analytic-light BRDF while still receiving
   sensible `AMBIENT_LIGHT` / `SPECULAR_LIGHT` from SDFGI or a reflection probe. I believe this
   works; I have not confirmed it for 4.7 specifically, and if it doesn't, Phase 5 gets
   noticeably harder. **Prototype on one object first.**

A fourth, smaller one: my throughput estimate in §3.3 is anchored on published Real-ESRGAN
figures, not on anything I ran. Treat the ±1-order-of-magnitude error bar as real.

---

## Sources

- [RTX Remix Compatibility wiki](https://github.com/NVIDIAGameWorks/rtx-remix/wiki/Compatibility)
- [RTX Remix Game Compatibility docs](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/introduction/intro-compatibility.html)
- [RTX Remix AI Texture Tools docs](https://docs.omniverse.nvidia.com/kit/docs/rtx_remix/latest/docs/howto/learning-aitexturetools.html)
- [NVIDIAGameWorks/toolkit-remix](https://github.com/NVIDIAGameWorks/toolkit-remix)
- [NVIDIAGameWorks/ComfyUI-RTX-Remix](https://github.com/NVIDIAGameWorks/ComfyUI-RTX-Remix)
- [Kim2091/PBRify_Remix](https://github.com/Kim2091/PBRify_Remix)
- [chaiNNer-org/spandrel](https://github.com/chaiNNer-org/spandrel)
- [RTX Remix on Dolphin — Dolphin Forums](https://forums.dolphin-emu.org/Thread-rtx-remix)
- [Godot 4.7 Beta — Phoronix](https://www.phoronix.com/news/Godot-4.7-Beta)
- [Godot 4.7 Dev 1 Vulkan RT — Phoronix](https://www.phoronix.com/news/Godot-4.7-Dev-1-Vulkan-RT)
- [Godot ray tracing proposal discussion #5162](https://github.com/godotengine/godot-proposals/discussions/5162)
- [NVIDIA path-tracing fork of Godot — CG Channel](https://www.cgchannel.com/2026/03/get-nvidias-new-path-tracing-fork-of-the-godot-game-engine/)
- [Godot BaseMaterial3D class reference](https://docs.godotengine.org/en/stable/classes/class_basematerial3d.html)
- [Godot global illumination docs](https://docs.godotengine.org/en/stable/tutorials/3d/global_illumination/index.html)
- [KHR_materials_sheen](https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Khronos/KHR_materials_sheen/README.md)
- [Conty Estevez & Kulla 2017, Production Friendly Microfacet Sheen BRDF](https://blog.selfshadow.com/publications/s2017-shading-course/imageworks/s2017_pbs_imageworks_sheen.pdf)
- [Zeltner, Burley & Chiang 2022, Practical Multiple-Scattering Sheen Using LTCs](https://tizianzeltner.com/projects/Zeltner2022Practical/)
- [Blender 4.0 shading release notes](https://developer.blender.org/docs/release_notes/4.0/shading/)
- [Henriko Magnifico — Wind Waker 4K texture pack](https://www.henrikomagnifico.com/wind-waker-4k)

Project-internal references: `Z:/memRip/knowledge/gamecube/toon-rendering.md`,
`Z:/memRip/knowledge/gamecube/sailing-spec.md`,
`Z:/memRip/knowledge/gamecube/great-sea-streaming.md`,
`Z:/3d ripper/gcrip/data/ww_rendering.json`.
