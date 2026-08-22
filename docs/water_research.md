# Water that blows minds — research and design for the Great Sea in Godot 4.7.2

Written 2026-08-22 for the Wind Waker remake at `Z:/3d ripper`. Companion to
`docs/pbr_assessment.md` §5 (the earlier water sketch) and the memRip specs
(`great-sea-streaming.md`, `sailing-spec.md`). Target: Godot **4.7.2 Forward+**, no
hardware ray tracing (4.7 has low-level Vulkan RT plumbing only — no RT reflections,
no path tracer; per `pbr_assessment.md` §2.3). The realistic reflection toolbox is
**SSR-style techniques + sky reflection + ReflectionProbe / community planar reflection**,
and this document designs around exactly that.

Confidence marks used throughout:
- **verified** — I fetched and read the primary source this session
- **reported** — from search-result excerpts of a source I could not read in full
- **confident** — background knowledge I believe strongly but did not re-check
- **speculation** — clearly flagged guesses

---

## 0. Where we start, and the one contract we must not break

The current shader (`out/rip/GZLE01/godot/ocean.gdshader`) is a camera-following 65×65
PlaneMesh whose **vertex shader evaluates the same four cosines the CPU `sea_height()`
uses** — amplitudes 2.5, wavelengths 13600/11200/8800/6400, periods 200/190/210/180
frames, `wave_scale` = the room's eased `wave_max` (0/5/15/30/50). The boat's buoyancy
spring, the camera clamp, and the salvage crane all read `sea_height()`. **The surface
you see is the surface physics uses.** That is the contract, it is the same one the real
game keeps (`daSea_packet_c` renders the very table `daSea_calcWave` interpolates), and
every stage below preserves it. Anything that displaces the visual surface must either
(a) be mirrored on the CPU or (b) be small enough that the boat visibly still sits on
the water (rule of thumb: extra visual-only displacement ≤ ~10 units ≈ the hull's own
bob noise, which is ±25 from the spring alone).

Known state being fixed in parallel: the shader is opaque and unshaded, so water meets
beach as a hard black-ish edge — no depth fade, no transparency. The real game got away
with opaque water because shore foam is **baked into the island textures** and the sea
TEV adds `C2·alpha` haze; we will not get away with it once the camera is free.

The other constraint: the project has **two lighting modes** — "simple" (plain sun, no
physical units) and opt-in physical (lux, exposure, HDRI) — plus the toon-ramp look.
The design in §4 gives every feature a behaviour in all three.

---

## 1. How games learned to draw water (and what each step buys us)

### 1.1 Sum-of-sines / Gerstner — where we already are

GPU Gems ch. 1, *Effective Water Simulation from Physical Models* (Finch/Cyan Worlds,
2004) is the canonical write-up of exactly our architecture: a handful of directional
sinusoids displacing a base mesh in the vertex shader, analytic normals from the
derivatives, plus higher-frequency detail pushed into a **normal map instead of
geometry** (**verified** the chapter exists and says this; the full text is at
[NVIDIA's site](https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-1-effective-water-simulation-physical-models)).
Its two lessons for us:

1. **Gerstner (trochoidal) waves** add a horizontal displacement toward crests, which
   sharpens peaks and is what makes sine seas stop looking like waterbeds. Wind Waker's
   own sea is pure vertical cosine — no choppiness — and at our amplitudes the steepness
   `ka = 2π·A/L` for the sharpest wave (75 over 6400) is only ~0.073, i.e. very gentle
   swell. Adding Gerstner x/z displacement is possible but would **break the
   `sea_height(x,z)` contract** (height would no longer be a function of the queried
   x,z without inversion). Verdict: keep vertical cosines for the gameplay waves;
   sharpen crests visually in the normal/shading domain instead. (**confident**)
2. **Geometry carries the swell; texture carries the ripple.** The four cosines give
   shapes of 6–14 k units; everything smaller (the sparkle, the wind-ruffle) belongs in
   scrolling normal maps. This is the single cheapest "10× better" step available to us
   (§4 Stage B).

### 1.2 FFT spectra — Tessendorf, Black Flag, Sea of Thieves

Tessendorf's *Simulating Ocean Water* (SIGGRAPH course notes, 1999–2004,
[PDF at Clemson](https://jtessen.people.clemson.edu/reports/papers_files/coursenotes2004.pdf))
is the bridge document between film and games (**verified**, I read the fetched
summary): synthesize a height field as the inverse FFT of random Hermitian amplitudes
drawn from an oceanographic **Phillips spectrum**, evolve them with the deep-water
dispersion relation ω² = gk, add "choppy" horizontal displacement via the i·k/|k|
factor, and detect wave folding — foam — where the **Jacobian of the displacement map
goes negative**. One FFT per frame gives you *hundreds of thousands* of statistically
correct waves instead of four.

Who uses it:
- **Assassin's Creed IV: Black Flag** — Ubisoft's ocean, driven by Beaufort-scale
  presets so designers could dial sea state per mission, with ship physics riding the
  simulated surface ([fxguide](https://www.fxguide.com/fxfeatured/5-things-you-need-to-know-about-the-tech-of-assassins-creed-iv-black-flag/), **reported**).
- **Sea of Thieves** (Rare, SIGGRAPH 2018 talk *The Technical Art of Sea of Thieves*,
  [ACM](https://dl.acm.org/doi/10.1145/3214745.3214820)) — an FFT ocean **in a stylized
  game**, which is why it is our best role model. The talk's PDF would not decode for
  me, but the technique is consistently reported across sources
  ([talk PDF](https://history.siggraph.org/wp-content/uploads/2022/09/2018-Talks-Ang_The-Technical-Art-of-Sea-of-Thieves.pdf),
  [breakdown](https://cinder-ember.tumblr.com/post/731521855639437312/can-you-do-one-about-the-sea-of-thieves-water)):
  water colour blends deep colour → **subsurface colour using view angle, sun
  direction, and a wave-peak mask derived from the FFT choppiness displacement**
  (the "glowing backlit crest" that everyone remembers); specular from the sun;
  **cubemap for ambient reflection** (not SSR!); Jacobian foam written into a texture
  that fades over time. (**reported**, multiple agreeing sources)

The stylization lesson from SoT: what reads as "magical" water is *not* mirror
reflection — it's (1) the translucent green crest against the sun, (2) foam in the
right places, (3) a believable spectrum of wave sizes. All three are portable to us,
and none needs the FFT itself — #1 and #2 need only masks.

**JONSWAP/TMA vs Phillips** (**confident**): Phillips is Tessendorf's original,
tends to over-energize small ripples; JONSWAP (fetch-limited seas) and TMA
(depth-attenuated) look better and are what modern implementations use — including
the Godot ones in §3.5.

### 1.3 Flow maps — for rivers and shore, not the open sea

Valve's SIGGRAPH 2010 talk (Vlachos, *Water Flow in Portal 2*,
[PDF](https://cdn.akamai.steamstatic.com/apps/valve/2010/siggraph2010_vlachos_waterflow.pdf),
**verified the PDF exists**, contents **reported**): artists paint a 2D vector field;
the shader advects normal-map UVs along it, cross-fading two phase-shifted samples to
hide the reset. Shipped in L4D2/Portal 2; famously testers took 17% fewer wrong turns
because the water flowed toward the goal. For us: irrelevant to the Great Sea (uniform
wind-driven scroll is right there in the original — the WYURAYURA indirect warp), but
**the right tool later** for island streams, the Forsaken Fortress moat, and making
water visibly flow *around* island shores. Park it.

### 1.4 Reflection: SSR, planar, probe — the real trade

- **Screen-space reflection** marches the depth buffer; it can only reflect what is
  on screen, fails at screen edges and behind occluders, and in Godot is a
  whole-Environment effect that only applies to **opaque** geometry (§3.2). For an
  open ocean under a big sky, SSR contributes little: the important reflection *is
  the sky*, plus islands near the shoreline.
- **Planar reflection** re-renders the scene mirrored about the water plane — perfect
  for flat lakes, increasingly wrong as waves grow (the mirrored image assumes one
  plane). Godot has **no built-in planar reflection** (**verified** via forum/addon
  ecosystem, §3.3); community addons exist.
- **ReflectionProbe / sky sample** — a cubemap. Wrong parallax for nearby objects,
  perfect for the sky and horizon, essentially free.

Sea of Thieves shipping on a **cubemap** is the strongest possible evidence for the
priority order on a wavy stylized sea: **sky first, SSR-ish near-field second, planar
never** (for the ocean; a harbour pond is another story). (**confident**)

### 1.5 Depth-fade shorelines and foam

The standard modern recipe (in every engine): sample the scene depth under the water
pixel, compute `water_depth = linearize(scene_depth) − linearize(surface_depth)`, then
- fade alpha to 0 as depth → 0 (the shore becomes a soft wet edge, killing our black
  seam),
- tint by absorption as depth grows (§2.2),
- paint a **foam band** where depth is below a threshold — optionally an animated,
  noise-broken sine line like the game's baked foam rings.

Godot examples of exactly this are plentiful (StayAtHomeDev's
[single-plane water tutorial](https://stayathomedev.com/tutorials/single-plane-water-shader/),
the [Boujie water shader](https://github.com/Chrisknyfe/boujie_water_shader),
several on godotshaders.com — **verified they exist**). One WW-specific caveat: the
islands already carry **painted foam rings** in their textures. Depth foam + baked foam
= double foam. Stage A therefore ships depth *transparency* always, and depth *foam*
at low intensity, tuned island-side later.

### 1.6 Fake subsurface scattering — the backlit wave tip

The trick (SoT above; also community write-ups, e.g.
[dotcrossdot](https://medium.com/dotcrossdot/water-ocean-shader-9173e0977f98),
gamedev.net threads — **reported**): true SSS is unaffordable, but the *look* is
"crests between me and the sun glow green". So:

```
sss = pow(saturate(dot(VIEW_dir, -sun_dir)), p)      // looking toward the sun
    * saturate(crest_mask)                            // high on wave peaks
    * (1.0 - saturate(dot(N, VIEW)))                  // grazing, not top-down
color += sss_tint * sss
```

with `crest_mask` from relative wave height (`(y − base) / (4·A·scale)`) since we have
the analytic height right in the vertex shader. Cost: a few ALU. Payoff: the single
most "next-gen water" pixel effect that exists, and it *keeps the cel look* if you
quantize `sss` through the toon ramp. (**confident**)

### 1.7 Whitecaps: Jacobian vs sprites

FFT seas get foam "for free" from the Jacobian folding criterion (Tessendorf,
**verified**; temporal accumulation/decay half-life per his
[whitecap paper](https://jtessen.people.clemson.edu/reports/papers_files/whitecap_fraction.pdf),
**reported**). Our cosine sea folds nowhere (steepness 0.07), so Jacobian foam is
meaningless until Stage C. The original game's answer: **300 `usonami` billboard
sprites, scale 300, spawned 20000–22000 units from the camera** — cheap, art-directed,
and authentic. Port those first; they are a particle system, not a shader problem.

### 1.8 The mesh: projected grid vs clipmap vs what we have

- **Projected grid** (Johanson 2004,
  [thesis](https://fileadmin.cs.lth.se/graphics/theses/projects/projgrid/projgrid-lq.pdf),
  **reported**): tessellate in screen space, project onto the sea plane — perfect
  screen-space density, but shimmering/"shuddering" artifacts under camera motion and
  ugly interactions with large vertical displacement.
- **Geometry clipmap / CDLOD**: viewer-centred nested grids, standard for huge oceans
  (tessarakkt's Godot ocean uses quadtree CDLOD, §3.5).
- **Ours**: a camera-following 65×65 grid of 800-unit cells + flat far skirt — i.e.
  the game's own scheme. At 65×65 the *nearest* cells are still 800 units (~8 m) wide,
  which was fine on a CRT but under-tessellates the swell up close today.

Verdict (**confident**): don't adopt projected grid (motion artifacts, breaks the
1:1-with-physics simplicity). Upgrade in place: raise density near the camera —
either a 129×129/257×257 grid with the same footprint (vertex cost is trivial for a
4090: 66 k verts even at 257²), or two rings (fine inner, coarse outer). Keep the
skirt. Snap the grid to whole-cell increments to avoid vertex swimming — the game
does exactly this by rebuilding on the cell lattice.

### 1.9 What Nintendo themselves did — WWHD and BotW

- **Wind Waker HD** (2013): new lighting engine, bloom, higher-res output; the sea
  itself stayed *recognizably the same painterly surface* — Nintendo did not add
  Fresnel mirrors to the Great Sea. They did add real reflection to special flat
  water (the Puppet Ganon boss room reflects everything in HD where the original
  didn't) ([Zelda Wiki](https://zelda.fandom.com/wiki/The_Legend_of_Zelda:_The_Wind_Waker_HD),
  **reported**). Lesson: even the owners of the art style confined "real" reflection
  to flat interior water, and kept the ocean stylized.
- **Breath of the Wild**: cel-shaded diffuse **plus** genuine physical specular,
  sky-driven ambient, and thresholded stylized highlights. It is the proof that
  "toon diffuse + physical specular lobe" — precisely `pbr_assessment.md`'s hybrid
  mode — is the art-safe formula. (**confident**; also see the community
  reconstructions, e.g. [daniel-ilett's BotW cel shader](https://github.com/daniel-ilett/shaders-botw-cel-shading))

---

## 2. How film does water — and what actually transfers

### 2.1 The punchline: film's ocean surface IS our ocean surface

The FFT method in §1.2 *is* the film technique. Tessendorf's notes are course notes
because they taught film TDs: Titanic, Waterworld-era deep ocean through today's shows
use spectral FFT oceans for everything beyond hero interaction (**confident**; the
notes themselves discuss production use). When a game ships an FFT sea it is running
film's surface model in real time. The gap between game water and film water is not
the surface shape — it's **light transport** and **hero interaction**.

### 2.2 Why deep water is blue-green: absorption, not artistic license

Pope & Fry 1997 (*Absorption spectrum (380–700 nm) of pure water*,
[abstract](https://pubmed.ncbi.nlm.nih.gov/18264420/), data mirrored at
[omlc.org](https://omlc.org/spectra/water/abs/index.html) and the
[Ocean Optics Web Book](https://www.oceanopticsbook.info/view/optical-constituents-of-the-ocean/water)):
pure water absorbs red light ~70× faster than blue — a ≈ 0.006 m⁻¹ at 418 nm
(the minimum), ~0.05 m⁻¹ at 550 nm, ~0.4 m⁻¹ at 660 nm (**verified** the sources;
values **reported/confident**). Red dies within metres; green within tens of metres;
blue survives to ~100 m. Add Rayleigh-ish scattering that preferentially returns blue
and you get the ocean's colour *from physics with zero texture*.

The renderable form is **Beer–Lambert**: `T(d) = exp(−σ·d)` per channel, with a
single-scattering "in-scatter" term that fades the refracted scene toward a scatter
colour as depth grows:

```
transmit = exp(-absorb_rgb * water_depth);            // what survives the round trip
refr     = scene_color * transmit;
color    = mix(scatter_color, refr, transmit)          // in practice: refr + scatter*(1-transmit)
```

This one formula is the highest-value transfer from film to our shader: it makes
shallows sand-warm and depths blue-green **continuously**, which no two-colour lerp
does. Film integrates it spectrally along refracted paths; we evaluate it once per
pixel against the depth buffer. Same physics, one sample. (**confident**)

### 2.3 Foam, spray, and hero water

Moana is the reference production: Disney wrote a dedicated water solver ("Splash",
FLIP-based, in Houdini) for wakes/splashes/shorelines, layered FLIP particles over
procedurally generated breaking waves, and taught the Hyperion path tracer to render
water efficiently ([fxguide/creativebloq](https://www.creativebloq.com/features/the-secrets-behind-moanas-water-vfx),
[Hyperion paper](https://dl.acm.org/doi/10.1145/3182159), **reported**). Their ocean
*vistas* still came from spectral ocean rigs — simulation was spent only where water
touches things.

**What does NOT transfer to a 30 fps game** (be explicit):
- **Path-traced light transport** — refraction rays through the surface into a
  participating medium, caustics on the sea floor from wave focusing, god rays
  integrated per pixel. We approximate with: one refracted screen sample, Beer–Lambert,
  a faked caustic texture if ever needed. No hardware RT in Godot 4.7.2 regardless.
- **FLIP/SPH hero simulation** — millions of particles per shot, minutes per frame.
  Our budget for "water reacting to things" is GPU particle *sprites* (bow spray,
  splashes) and shader-domain tricks (wake decals/trails). A real-time FLIP puddle is
  possible in 2026 but never for an open ocean.
- **Spectral rendering** — film integrates absorption per wavelength; we bake it to
  three RGB coefficients. The error is invisible for water.
- **Simulated whitecap dynamics** — film sims foam as particles/geometry advected by
  the surface flow; we stamp textures/sprites where a mask says so.

What DOES transfer: the spectrum-shaped surface (§1.2), Beer–Lambert per-channel
absorption (§2.2), Fresnel with the true F0 (water IOR 1.333 → F0 = 0.02), foam
placement criteria (Jacobian), and the discipline of separating *swell* (geometry),
*ripple* (normal detail), and *sparkle* (specular statistics — §4 Stage B's
distance-roughness is exactly film's "filter your normal detail into roughness",
cf. LEAN/Toksvig, §1.10 sources in §5). (**confident**)

---

## 3. What Godot 4.7.2 actually gives us

### 3.1 Screen-reading shaders — the machinery for depth fade + refraction

**Verified** against the
[official docs](https://docs.godotengine.org/en/stable/tutorials/shaders/screen-reading_shaders.html):

- `uniform sampler2D t : hint_screen_texture` — the rendered opaque scene, sampled at
  `SCREEN_UV`. Basis for refraction.
- `uniform sampler2D t : hint_depth_texture` — the depth buffer (non-linear; reconstruct
  view-space depth via `INV_PROJECTION_MATRIX`). Basis for depth fade/absorption/foam.
- `hint_normal_roughness_texture` — **Forward+ only**.
- **The catch that shapes our whole design:** a material using these hints **is treated
  as transparent** — it renders in the transparent pass, after the single screen/depth
  capture, and *it does not appear in the captured textures* (nor in SSR — §3.2). Also,
  transparent objects (spray sprites, other water) are absent from both textures, so
  depth-based effects see through them.

Consequences: (a) the water can depth-fade and refract everything opaque — islands,
sea floor, the boat hull — which is what we need; (b) once it reads depth it will
**not receive Environment SSR** and will not be refracted/reflected by other
screen-reading materials. Interior flat water and the ocean therefore each do their
own reflection in-shader.

### 3.2 Environment SSR

**Verified** ([docs](https://docs.godotengine.org/en/stable/tutorials/3d/environment_and_post_processing.html)):
Forward+ only; properties `max_steps`, `fade_in`, `fade_out`, `depth_tolerance`;
half-resolution option; reflects **opaque geometry only** — transparent materials
neither receive nor appear in it, and screen-reading shaders are excluded. So engine
SSR is for wet decks and puddles (opaque-ish materials), **not for our depth-reading
ocean**. If we want near-field reflections on the ocean we raymarch the depth texture
ourselves inside the water shader (a mini-SSR; the depth capture happens before the
transparent pass, so the data is there). Stage B treats that as optional garnish.

### 3.3 Planar reflection

Godot has **no built-in planar reflection** (**verified** by ecosystem: forum answers
and the existence of addons —
[SIsilicon's plugin](https://github.com/SIsilicon/Godot-Planar-Reflection-Plugin),
[gd_planar_reflection](https://github.com/RisingThumb/gd_planar_reflection),
[PlanarReflector-CPP](https://godotengine.org/asset-library/asset/4102)). A planar
reflector re-renders the scene per reflector per frame — for our one huge wavy ocean
it is both wrong (waves violate the planar assumption) and expensive (the Great Sea
scene is heavy). Verdict: **not for the ocean**; keep in the toolbox for one or two
flat interior waters (Great Fairy fountains, Puppet Ganon's room — where Nintendo
themselves added reflection in HD, §1.9).

### 3.4 ReflectionProbe and the sky

`ReflectionProbe` gives a local cubemap (once or per-frame). For open sea, the sky
contribution can come even cheaper: the environment's radiance cubemap already exists
for ambient specular — a shaded material with low roughness gets sky reflection *for
free* from the engine's IBL path. This is the strongest argument for making the ocean
a **shaded** material (custom `light()` for the toon-friendly sun) instead of
`unshaded`: sky-Fresnel, physical-mode exposure, and HDRI swaps all arrive without any
code. (**confident**; the ambient-specular-for-custom-light interplay is
`pbr_assessment.md`'s open question #3 — prototype first.)

### 3.5 Existing Godot ocean work — all verified to exist, all MIT where stated

- [**2Retr0/GodotOceanWaves**](https://github.com/2Retr0/GodotOceanWaves) (**verified**,
  README read): FFT via compute (Stockham), **TMA spectrum** with Hasselmann
  directional spreading, **multiple cascades** with per-cascade parameters,
  **Jacobian foam with linear accumulation / exponential dissipation**, GPU-particle
  **sea spray** with dissolve, GGX-based shading, load-balances one cascade update per
  frame. MIT. No buoyancy. This is the best local reference implementation for
  Stage C and for the spray system.
- [**tessarakkt/godot4-oceanfft**](https://github.com/tessarakkt/godot4-oceanfft)
  (**verified**, README read): Tessendorf FFT (ported from achalpandeyy/OceanFFT),
  quadtree **CDLOD** mesh, **basic buoyancy** (mechanism undocumented — inspect before
  trusting), Godot 4.3+, MIT, self-described early WIP.
- [rdgh0st/FFT-Ocean-Godot](https://github.com/rdgh0st/FFT-Ocean-Godot) (**verified**
  exists): JONSWAP with swell bias; reports 60 fps at 1024² on their hardware.

So FFT oceans in Godot 4 are a solved, multiply-implemented problem — the open
question for *us* is only the buoyancy mirror (§4 Stage C).

### 3.6 Particles, VisualShader, misc

- **GPUParticles3D** handles spray/whitecap sprites comfortably (2Retr0 does exactly
  this; their caveat: particle counts give diminishing density because of even
  bounding-box distribution + culling). (**verified** via their README)
- **VisualShader vs code**: everything here is text-shader work. VisualShader adds
  nothing for a shader that must share constants with generated GDScript — `godot.py`
  already emits `ocean.gdshader` from one source of truth, keep it that way.
  (**confident**)
- **Volumetric fog** (Forward+) can give cheap "sea haze" at the horizon in physical
  mode; the original's `uso_umi` fog colour is the simple-mode equivalent.

---

## 4. The design — three stages for OUR shader

Ground rules for every stage:
- The four-cosine vertex displacement and its constants **never change** (contract, §0).
- Every feature has a **simple-mode** behaviour (plain sun, LDR-ish), a
  **physical-mode** behaviour (lux/exposure — output real radiance and let the engine
  tonemap), and a **cel variant** (flat colours, hard steps, but *keeping* the
  depth-fade shore — a cel sea with a soft wet shoreline is both authentic-looking and
  bug-free).
- Cheat toward the game's own vocabulary: UV = world/2000, the indirect-warp scroll,
  `usonami` whitecaps, `dKy_get_seacolor`-fed colours.

### Stage A — the water becomes *water* (days)

Goal: shore fix + volume + foam + sky. This is 80% of the perceptual win.

1. **Convert from `unshaded` to shaded** with a custom `light()` for the sun so the
   toon ramp survives, or (fallback if ambient plumbing misbehaves) stay unshaded and
   sample a sky cubemap uniform manually. Shaded is preferred: physical mode then gets
   exposure/IBL for free. Prototype the ambient-with-custom-`light()` question on one
   mesh first (open question, §6).
2. **Depth fade + Beer–Lambert absorption.** Add `hint_depth_texture`; linearize;
   `water_depth = scene_z − pixel_z` (view-space, then scale to world units — beware
   the global scene scale: **1 game unit ≈ 1 cm**). Then:

   ```glsl
   vec3 transmit = exp(-absorb * water_depth);          // absorb in 1/unit, per channel
   ALPHA = clamp(1.0 - transmit_luma, 0.0, 1.0);        // soft shore: alpha→0 at 0 depth
   ```
   In the cel variant, quantize `transmit` through 2–3 bands instead of using it raw —
   flat colours, same physics deciding *where* the bands fall.
3. **Fresnel to the sky.** `F = 0.02 + 0.98·(1−cos θ)⁵` (Schlick, F0 from IOR 1.333).
   Shaded material: set `ROUGHNESS`/`SPECULAR`, engine IBL does the reflection.
   Face-on the sea stays the painterly `sea_day` colour (F ≈ 0.02 — near-invisible
   reflection, exactly why WW got away with none); at grazing it silvers toward the
   sky. This is self-balancing across lighting modes because the sky *is* the mode.
4. **Depth foam band, gently.** `foam = 1 − smoothstep(0, foam_depth, water_depth)`,
   break it with the existing warp texture, tint white, and in cel mode threshold it
   hard. Ship at low intensity — the islands carry painted foam already (§1.5).
5. **Port the `usonami` whitecap sprites** (300 billboards, scale 300, 20000–22000
   from camera, spawn only when `wave_scale ≥ ~15`). Authentic and cheap.
6. **Crest fake-SSS** (§1.6) using the analytic height as the crest mask — even at our
   gentle steepness the "green glow toward the sun" reads beautifully at sunset. In
   cel mode, run `sss` through the toon ramp for a hard bright band.

Degradations: simple mode = everything above with the plain sun and the procedural
sky; cel mode = flat quantized colours but identical alpha/foam/shore logic.

### Stage B — detail, glint, refraction (days)

1. **Two scrolling detail normal octaves.** Tile at world/2000 (game convention) and
   ~world/450, scrolled by wind direction at ~1/300-per-frame-ish rates, warped by the
   indirect texture like the original's `B_WYURAYURA` trick so it stays "WW-drunk"
   rather than photoreal-linear. Blend into the analytic swell normal. These normals
   drive specular + Fresnel only, never displacement — contract intact.
2. **Distance-driven roughness (the anti-tinfoil clause).** Fold normal detail into
   roughness with distance, LEAN/Toksvig-style in spirit
   ([overview](https://blog.selfshadow.com/2011/07/22/specular-showdown/), **reported**;
   Cox–Munk is the physical grounding — mean-square slope grows with wind, and a
   distant pixel *contains* the whole slope distribution,
   [NOAA explainer](https://psl.noaa.gov/outreach/education/science/glitter/)):

   ```glsl
   float rough = mix(rough_near, rough_far, smoothstep(20000.0, 200000.0, dist));
   rough = max(rough, rough_wind * wave_scale / 50.0);   // stormier = rougher
   ```
   Without this the horizon is a strobing glitter field; with it you get the wide calm
   sun-lane real oceans show. **This single line is the difference between "sea" and
   "foil".**
3. **Sun glint that doesn't alias:** the sun highlight comes from the engine light via
   GGX at the rolled-off roughness; clamp specular energy (`min(spec, glint_max)`) in
   simple mode where there is no auto-exposure to tame it; in physical mode let it be
   genuinely bright and let bloom/exposure handle it — that HDR glint is one of the
   biggest "physical mode looks expensive" wins. Cel mode: threshold the specular into
   a hard white shape, BotW-style (§1.9).
4. **Screen-space refraction.** Offset `SCREEN_UV` by the detail normal
   (`SCREEN_UV + N.xz * refr_strength / max(depth_vs,1)`), **re-check depth at the
   refracted UV** and fall back to the unrefracted sample if the fetched pixel is in
   front of the water (the classic leaking-boat-hull artifact). Apply absorption to
   the refracted colour (§2.2 formula). Simple mode: identical. Cel: optional —
   honestly a cel sea can skip refraction entirely and keep only absorption bands.
5. **Optional in-shader mini-SSR** for island/boat reflections near the shore: a short
   (≤16-step) raymarch of the depth texture, blended by Fresnel and faded at screen
   edges, since Environment SSR cannot serve a depth-reading material (§3.2). Cut it
   without regret if it shimmers — sky + glint + foam already carry the image.
6. **Boat interaction garnish:** the wake/spray emitters from the sailing spec
   (`SHIPWAVE00`/`SHIPTAIL00` thresholds at |v|>11 / >3) plus a fading foam-trail
   ribbon behind the hull. GPUParticles3D; no sim.

### Stage C — the optional FFT upgrade (week+)

Two sub-stages, deliberately ordered so physics can never diverge:

- **C1 — FFT as *detail*, physics untouched.** Run one small FFT cascade (256²,
  TMA/JONSWAP, wavelengths capped below ~800 units so it lives entirely between our
  cosine crests) and use its **normals and foam only** — zero or ≤10-unit vertical
  displacement mixed in. The boat still floats on `sea_height()` exactly; eyes cannot
  tell a 10-unit visual ripple from hull bob. Jacobian whitecap mask replaces/augments
  the sprite whitecaps in rough rooms, with 2Retr0-style accumulate/decay. Crib the
  Stockham compute shader from 2Retr0 (MIT).
- **C2 — full FFT displacement, only with a buoyancy mirror.** If the swell itself
  goes FFT, `sea_height()` must return the *same* surface: either (a) async GPU
  readback of the displacement map (verify Godot 4.7's async readback API and its
  frame latency — flagged in §6; a 2–3 frame stale height under a boat with a
  0.05-stiffness buoyancy spring is probably imperceptible, **speculation**), or
  (b) evaluate a truncated CPU version of the same spectrum (sum the top ~64 waves by
  amplitude on the CPU — deterministic, no latency, ~64 cosines per query is nothing).
  Wind Waker's identity honestly argues we may never need C2: the four huge lazy
  cosines *are* the Great Sea's body language. Do C2 only if C1 leaves the swell
  feeling too regular.

---

## 5. Honesty: what "movie water" we cannot have, and what matters most

**Cannot have, and why:**
- **Path-traced reflection/refraction & caustics** — no hardware RT in Godot 4.7.2
  (Vulkan RT plumbing only, no features, no BLAS refit for animated water anyway —
  `pbr_assessment.md` §2.3). Every reflection we show is sky-cubemap, probe, or a
  screen-space march with an off-screen hole. When the camera looks down at water that
  should reflect an island *behind the camera*, we will show sky. Nobody has solved
  this without RT; SoT shipped with it unsolved.
- **Volumetric light through the surface** — god rays, translucent wave interiors lit
  from behind-and-inside. Our fake-SSS is a screen-facing impostor of it; it fails if
  you look for it (a crest viewed side-on against the sun won't transmit a glow onto
  the water in front of it).
- **Simulated interaction** — breaking shore waves that curl, water displaced by the
  hull, splash physics. FLIP at film scale is minutes/frame (§2.3). Sprites and
  ribbons are our ceiling, and — evidence: every shipped ocean game — they suffice.
- **True transparency ordering** — screen-reading water can't see other transparent
  things (spray, other water sheets), so overlapping water surfaces will misbehave.
  Design layouts so ocean and interior waters never stack on screen.

**The two-or-three perceptual choices that matter most, ranked:**
1. **Shore transparency + absorption gradient.** Humans read water's *edge* first.
   The current black seam is the single loudest wrongness; the sand-through-turquoise
   gradient is the single loudest rightness. (Stage A.2)
2. **A sun glint that behaves** — present, warm, elongating at low sun, and *not
   aliasing*. Distance-roughness + HDR glow. (Stage B.2/B.3)
3. **Horizon roughness / sky Fresnel** — grazing angles silvering to sky sells "vast
   ocean" from the boat's camera height more than any wave detail does. (Stage A.3 +
   B.2)
Foam and fake-SSS are the tier just below; FFT is a tier below that. That ordering is
the budget.

---

## 6. Constants table (starting values, tune by eye)

Scene scale: **1 game unit ≈ 1 cm**; per-meter optical coefficients ÷100 for per-unit.

| constant | start value | source / note |
|---|---|---|
| wave rows (KEEP) | A 2.5 ×scale; L 13600/11200/8800/6400; T 200/190/210/180; φ 0/4000/8000/12000; dirs (0.98,0.20)(0.20,0.98)(−0.98,0.20)(0.20,−0.98) | game code, verified in memRip |
| `wave_scale` (KEEP) | 0/5/15/30/50, eased 1/100 per frame | MULT disc values |
| IOR / F0 | 1.333 / **0.02** | physics; Schlick ⁵ |
| absorb (physical, pure water, per unit) | `vec3(0.0041, 0.0006, 0.000045)` | Pope & Fry per-m (0.41, 0.056, 0.0045) ÷ 100 — **too clear for gameplay**, listed for reference |
| absorb (stylized start, per unit) | `vec3(0.010, 0.004, 0.0015)` | ~e-fold red in 100 u (1 m), blue in ~650 u; tune so a beach reads over 2–4 m |
| scatter colour (day) | `vec3(0.06, 0.30, 0.35)` | toward `sea_day`, greener |
| alpha shore fade | `1 − exp(−water_depth / 60.0)` | ~full opacity by ~2.5 m |
| foam depth band | `foam_depth = 45` units, warp-broken | ~0.5 m; keep weak (baked island foam) |
| crest SSS | `sss_tint = vec3(0.10, 0.55, 0.50)`, power p = 4, mask = relative height | SoT-style |
| rough_near / rough_far | 0.05 / 0.40 | pbr_assessment §5.4 |
| roughness distance ramp | smoothstep(20 000 → 200 000 units) | horizon at 450 000 |
| detail normal UVs | world/2000 (game) + world/450; strength 0.35 / 0.15 | UV=world/2000 is the original's convention |
| indirect warp | strength 0.3, v-scroll 1/300 per frame | original TEV values |
| refraction strength | `N.xz * 0.35 / depth_vs(m)` UV offset, depth-checked | tune vs leaking |
| mini-SSR (optional) | ≤16 steps, edge fade 0.1 UV | garnish only |
| whitecaps | 300 sprites, scale 300, ring 20 000–22 000, only `wave_scale ≥ 15` | original `usonami` |
| FFT cascade (C1) | 256², TMA, L_max ≈ 800 units, displacement ≤ 10 units (normals/foam only) | 2Retr0 as reference impl |
| Jacobian foam (C1) | bias 0.8–1.0, accumulate linear, decay exp half-life ~2 s | Tessendorf + 2Retr0 |
| glint clamp (simple mode) | `min(spec, 4.0 × sun)` | no auto-exposure in simple mode |

---

## 7. Top-5 recommendations (prioritized)

1. **Stage A now**: depth-fade shore + Beer–Lambert absorption + gentle depth foam +
   `usonami` sprites. Fixes the live bug and delivers most of the wow. Days.
2. **Fresnel-to-sky with F0 = 0.02 and the distance-roughness ramp** in the same pass.
   Sky reflection via the shaded/IBL path, not SSR, not planar. The roughness ramp is
   non-negotiable — it is what separates ocean from tinfoil.
3. **Crest fake-SSS + two detail normal octaves with the indirect warp** (Stage B core).
   This is the Sea-of-Thieves look, portable in ~a day, and it quantizes cleanly through
   the toon ramp so the cel mode keeps its identity.
4. **Do reflections the humble way**: engine IBL sky + optional 16-step in-shader
   raymarch; skip Environment SSR for the ocean (incompatible with depth-reading
   transparency — §3.2) and skip planar reflection except for one or two flat interior
   waters (the one place Nintendo themselves added it in HD).
5. **FFT only as C1 (normals/foam, ≤10-unit displacement) unless the swell demands
   more**; if C2 ever happens, ship the CPU spectrum-mirror (top-64 waves) rather than
   GPU readback first. The four cosines are gameplay-sacred and, honestly,
   art-sacred too.

## 8. The three things I'm least sure about

1. **Ambient/IBL specular into a material with a custom `light()`** (needed for
   "toon sun + sky Fresnel" in one shader). Same open question as
   `pbr_assessment.md` #3; if Godot 4.7 doesn't feed ambient specular the way I
   expect, fallback is manual cubemap sampling in `fragment()`. Prototype on one mesh
   before committing Stage A.1.
2. **The exact transparency/SSR interaction chain**: docs verify that screen-reading
   materials are treated as transparent and that SSR reflects only opaque geometry;
   my conclusion that a depth-reading ocean therefore *receives* no Environment SSR is
   an inference (strong, but I found no doc sentence stating the receiving side).
   A 10-minute test scene settles it.
3. **Async GPU readback for C2 buoyancy** — whether Godot 4.7's RenderingDevice async
   readback is ergonomic and what its real frame latency is, and whether a 2–3-frame
   stale height under the 0.05-stiffness buoyancy spring is imperceptible. Untested;
   this is why C2 recommends the CPU spectrum-mirror instead. (Also unverified: the
   internals of tessarakkt's "basic buoyancy".)

Minor extra uncertainty: the Sea of Thieves talk details are **reported** (the PDF
would not decode); the technique description is consistent across three independent
sources but I could not read Rare's own slides.

---

## Sources

Games:
[GPU Gems ch.1 — Effective Water Simulation](https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-1-effective-water-simulation-physical-models) ·
[Tessendorf, Simulating Ocean Water (course notes PDF)](https://jtessen.people.clemson.edu/reports/papers_files/coursenotes2004.pdf) ·
[Tessendorf, Whitecap Phenomenology](https://jtessen.people.clemson.edu/reports/papers_files/whitecap_fraction.pdf) ·
[The Technical Art of Sea of Thieves (SIGGRAPH 2018, ACM)](https://dl.acm.org/doi/10.1145/3214745.3214820) ·
[SoT talk PDF (siggraph history)](https://history.siggraph.org/wp-content/uploads/2022/09/2018-Talks-Ang_The-Technical-Art-of-Sea-of-Thieves.pdf) ·
[SoT water breakdown (cinder-ember)](https://cinder-ember.tumblr.com/post/731521855639437312/can-you-do-one-about-the-sea-of-thieves-water) ·
[AC4 Black Flag tech (fxguide)](https://www.fxguide.com/fxfeatured/5-things-you-need-to-know-about-the-tech-of-assassins-creed-iv-black-flag/) ·
[Vlachos, Water Flow in Portal 2 (SIGGRAPH 2010 PDF)](https://cdn.akamai.steamstatic.com/apps/valve/2010/siggraph2010_vlachos_waterflow.pdf) ·
[Johanson, projected grid thesis](https://fileadmin.cs.lth.se/graphics/theses/projects/projgrid/projgrid-lq.pdf) ·
[Specular Showdown (Toksvig/LEAN overview)](https://blog.selfshadow.com/2011/07/22/specular-showdown/) ·
[NOAA — Cox–Munk glitter](https://psl.noaa.gov/outreach/education/science/glitter/) ·
[Wind Waker HD changes (Zelda Wiki)](https://zelda.fandom.com/wiki/The_Legend_of_Zelda:_The_Wind_Waker_HD) ·
[BotW cel shader reconstruction](https://github.com/daniel-ilett/shaders-botw-cel-shading)

Film / physics:
[Pope & Fry 1997 (PubMed)](https://pubmed.ncbi.nlm.nih.gov/18264420/) ·
[Water absorption compendium (omlc.org)](https://omlc.org/spectra/water/abs/index.html) ·
[Ocean Optics Web Book — water](https://www.oceanopticsbook.info/view/optical-constituents-of-the-ocean/water) ·
[Moana water VFX (Creative Bloq)](https://www.creativebloq.com/features/the-secrets-behind-moanas-water-vfx) ·
[Disney Hyperion renderer (ACM TOG)](https://dl.acm.org/doi/10.1145/3182159)

Godot:
[Screen-reading shaders (docs)](https://docs.godotengine.org/en/stable/tutorials/shaders/screen-reading_shaders.html) ·
[Environment & post-processing / SSR (docs)](https://docs.godotengine.org/en/stable/tutorials/3d/environment_and_post_processing.html) ·
[ReflectionProbe (docs)](https://docs.godotengine.org/en/stable/classes/class_reflectionprobe.html) ·
[2Retr0/GodotOceanWaves](https://github.com/2Retr0/GodotOceanWaves) ·
[tessarakkt/godot4-oceanfft](https://github.com/tessarakkt/godot4-oceanfft) ·
[rdgh0st/FFT-Ocean-Godot](https://github.com/rdgh0st/FFT-Ocean-Godot) ·
[SIsilicon planar reflection plugin](https://github.com/SIsilicon/Godot-Planar-Reflection-Plugin) ·
[StayAtHomeDev single-plane water tutorial](https://stayathomedev.com/tutorials/single-plane-water-shader/) ·
[Boujie water shader](https://github.com/Chrisknyfe/boujie_water_shader)

Project-internal: `Z:/memRip/knowledge/gamecube/great-sea-streaming.md`,
`Z:/memRip/knowledge/gamecube/sailing-spec.md`, `Z:/3d ripper/docs/pbr_assessment.md`,
`Z:/3d ripper/out/rip/GZLE01/godot/ocean.gdshader`.
