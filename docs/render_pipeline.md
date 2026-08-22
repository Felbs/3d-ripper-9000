<title>Render Pipeline Map</title>

# The lighting and shader pipeline

How light and shading flow through the Wind Waker remake, so a change in one place has a
known blast radius. Everything here is what the code does today (ripper `ad7e65c`).

Three hard rules the whole thing rests on:

1. **There are two lighting worlds, and simple is the default.** Plain `light_energy`, a
   procedural sky, no exposure games, `scene_nits = 1`. The **physical** world (lux, lumens,
   `CameraAttributesPhysical` at ISO 100 f/16 1/100, the HDR sky dome) is opt-in via
   `--physical` or `--hdri`, and `lighting.json` tells the running game which one it is in.
   In the physical world every **unshaded** surface must output **nits** or it renders black
   against a sunlit white of ~31,800. This split exists because the physical rig shipped
   black to a play-tester twice.
2. **The sun has one source: the game clock.** Shadows, the visible sun disc, the toon ramp
   direction and the sea's specular all read `Game.sun_direction`. Never let anything else
   steer it.
3. **The sky and the sea share one palette.** Whatever colour the visible sky is showing this
   hour is pushed into the ocean shader as its reflection colour and night factor. Let them
   compute the hour separately and you get night-dark water under a noon sky, which reads to
   a player as "the water is broken".

---

## 1. Lighting pipeline

```mermaid
flowchart TD
    classDef data fill:#e6f0ff,stroke:#3b6fb0,color:#0b1f2e;
    classDef code fill:#e9f7ec,stroke:#2e7d43,color:#0b1f2e;
    classDef gpu fill:#fff2da,stroke:#a97f13,color:#0b1f2e;
    classDef out fill:#f3e6f7,stroke:#8e44ad,color:#0b1f2e;

    CLOCK["Game clock<br/>day_time, 600 s/day"]:::data
    HDRI["--hdri / --hdri-sunset / --hdri-night<br/>3 Radiance maps"]:::data
    DUNG["dungeons.json<br/>stage type -> indoor/outdoor"]:::data

    HDRI --> WRITEHDRI["_write_hdri (export)<br/>find each map's sun,<br/>write sky_slot.hdr + sky.json"]:::code
    WRITEHDRI --> SKYJSON["sky.json: slots{sun_dir, ratio}"]:::data

    CLOCK --> LTICK["_light_tick (every 30 frames)"]:::code
    DUNG --> SETUP["_setup_lighting (on stage load)"]:::code
    SKYJSON --> SETUP

    SETUP -->|outdoor| DOME["_build_skydome<br/>sphere, follows camera"]:::code
    SETUP -->|indoor| FILL["indoor rig<br/>400 lux fill, flat ambient,<br/>black background, no dome"]:::code

    LTICK --> SUNARC["sun arc from hour<br/>06:00 E, noon 70deg, 18:00 W<br/>5800K noon -> 2600K horizon"]:::code
    SUNARC --> SUNDIR["Game.sun_direction"]:::data
    SUNARC --> SUNLIGHT["DirectionalLight3D<br/>light_intensity_lux, temperature<br/>CASTS SHADOWS"]:::gpu
    LTICK --> NITS["Game.scene_nits = lux * 1.2 / pi"]:::data

    LTICK --> SLOT["_slot_for_hour<br/>night / sunset / day"]:::code
    SLOT --> APPLY["_apply_slot"]:::code
    APPLY --> ENVSKY["Environment.sky = PanoramaSky(HDR)<br/>LIGHTING + REFLECTION only"]:::gpu
    APPLY --> DOMEPAL["dome palette + sun_travel"]:::code

    ENVSKY --> AMBIENT["ambient light + reflections"]:::gpu
    DOME --> HIDE["skybox: hides the HDR,<br/>shows WW gradient + sun disc"]:::gpu
    SUNDIR --> DOMEPAL
    SUNLIGHT --> SHADE
    AMBIENT --> SHADE
    HIDE --> SHADE["what the camera sees"]:::out
    NITS --> DOME
    NITS --> UNSHADED["toon / ocean / fx / dome<br/>multiply by scene_nits"]:::gpu
    UNSHADED --> SHADE

    FLAMES["flames: bonbori/Lamp/Fire<br/>1900-2000K, real lumens, flicker"]:::gpu --> SHADE
    CAMATTR["CameraAttributesPhysical<br/>ISO 100 f/16 1/100, auto-exposure"]:::gpu --> SHADE
```

**The one that bit us twice:** an HDR is **light only**. It is the `Environment.sky` (ambient +
reflection), but the **sky dome** is a skybox drawn in front of it, so it is never the visible
background. The dome must **wrap the camera** (it follows the camera every frame) or it gets
frustum-culled and the HDR shows through — which is exactly what "all I can see is the HDR" was.

---

## 2. Shader pipeline

```mermaid
flowchart TD
    classDef data fill:#e6f0ff,stroke:#3b6fb0,color:#0b1f2e;
    classDef code fill:#e9f7ec,stroke:#2e7d43,color:#0b1f2e;
    classDef gpu fill:#fff2da,stroke:#a97f13,color:#0b1f2e;

    MODE["shade_mode<br/>toon / hybrid / clay / paper / pbr<br/>(F6 cycles, --shade=, saved)"]:::data
    MATS["ww_materials.json<br/>class per (archive, material)"]:::data
    RAMP["toon.bti ramp<br/>hard terminator 119..137"]:::data

    F6["F6 pressed"]:::code --> RESHADE["set_shade_mode + _apply_toon<br/>RE-SHADE IN PLACE (no reload)"]:::code
    MODE --> CLASSIFY["classify_material<br/>curated -> name -> default"]:::code
    MATS --> CLASSIFY
    CLASSIFY --> BUILDMAT["_toon_material / _shade_material<br/>one ShaderMaterial per source"]:::code

    BUILDMAT -->|mode toon| TOONSH["toon.gdshader (unshaded)<br/>albedo * mix(C0,K0,ramp) * nits"]:::gpu
    BUILDMAT -->|mode != toon| WWSH["ww_material.gdshader<br/>look uniform 1..4"]:::gpu
    RAMP --> TOONSH
    RAMP --> WWSH

    WWSH --> DIFF["diffuse by look:<br/>hybrid=ramp, clay=wrapped+SSS,<br/>paper=flat+rim, pbr=Lambert"]:::gpu
    WWSH --> LIGHTFN["light() replaces Godot's loop:<br/>GGX + Smith + Schlick<br/>+ Charlie sheen + clearcoat"]:::gpu
    WWSH --> GRAIN["clay/paper: world-space<br/>grain perturbs NORMAL<br/>(no tangents needed)"]:::gpu

    SUN["Game.sun_direction"]:::data --> TOONSH
    NITS2["Game.scene_nits"]:::data --> TOONSH
    NITS2 --> WWSH
    CLASS2["metallic ONLY from curated list"]:::data --> LIGHTFN
```

**Why toon is the only one that reads right so far:** it is unlit — it just emits the ramp — so
it is immune to whatever the lighting rig is doing. The other four depend entirely on the
lighting being correct, which is the thing we are still tuning. Fix the light and they come
alive; break the light and they go dark. That is not four broken shaders, it is one lighting
rig the lit looks are all downstream of.

---

## 3. Water pipeline

```mermaid
flowchart TD
    classDef data fill:#e6f0ff,stroke:#3b6fb0,color:#0b1f2e;
    classDef code fill:#e9f7ec,stroke:#2e7d43,color:#0b1f2e;
    classDef gpu fill:#fff2da,stroke:#a97f13,color:#0b1f2e;
    classDef out fill:#f3e6f7,stroke:#8e44ad,color:#0b1f2e;

    WAVES["Game.SEA_WAVES<br/>4 rows: amp, wavelength,<br/>phase, dir, period"]:::data
    WMAX["room wave_max<br/>0/5/15/30/50, eased"]:::data
    CLOCK2["Game clock"]:::data

    WAVES --> CPU["Game.sea_height x,z<br/>buoyancy, boat, swim"]:::code
    WAVES --> UNI["_spawn_ocean pushes the<br/>SAME rows as uniforms"]:::code
    UNI --> VERT["ocean.gdshader vertex()<br/>y = 1 + sum amp*scale*cos(...)<br/>+ analytic gradient -> normal"]:::gpu
    WMAX --> VERT
    CPU -.->|"ONE CONTRACT:<br/>never let these diverge"| VERT

    CLOCK2 --> LT["_light_tick simple branch"]:::code
    LT --> PAL["sky palette by hour<br/>day / sunset / night"]:::code
    PAL --> SKYMAT["ProceduralSkyMaterial<br/>(what the player sees)"]:::gpu
    PAL --> OCEANUNI["sky_zenith / sky_horizon / night<br/>pushed into the ocean"]:::data

    DEPTH["DEPTH_TEXTURE<br/>scene depth - own depth"]:::gpu --> THICK["water thickness<br/>along the eye ray"]:::gpu
    THICK --> ABSORB["Beer-Lambert per channel<br/>exp(-thick * 0.010/0.004/0.0015)"]:::gpu
    THICK --> ALPHA["ALPHA = mix(0.06, 0.94, shallow)<br/>THE SHORE IS TRANSPARENT"]:::gpu
    THICK --> FOAM["shore foam band<br/>+ animated value noise"]:::gpu
    VERT --> CREST["crest factor -> whitecaps"]:::gpu
    CREST --> FOAM

    OCEANUNI --> FRES["Schlick Fresnel F0 = 0.02<br/>(IOR 1.333) -> sky reflection"]:::gpu
    OCEANUNI --> ABSORB
    SUN2["Game.sun_direction"]:::data --> GLINT["sun glint, gloss 900 -> 90<br/>with distance"]:::gpu
    RAMP2["toon ramp"]:::data --> BODY["cel-lit water body<br/>(the real TEV had no Fresnel)"]:::gpu
    ABSORB --> BODY
    BODY --> MIXC["mix(body, sky, fresnel)<br/>+ glint + foam"]:::gpu
    FRES --> MIXC
    GLINT --> MIXC
    FOAM --> MIXC
    MIXC --> NITS3["* Game.scene_nits"]:::gpu
    ALPHA --> SEEN["what the camera sees"]:::out
    NITS3 --> SEEN
    SKYMAT --> SEEN

    BAKED["stage's own baked sea<br/>SC_01_mizu + shore sheets"]:::data --> HIDE2["_hide_baked_sea:<br/>material is mizu/nami AND<br/>AABB straddles water level"]:::code
    HIDE2 -->|hidden| SEEN
```

**Why the AABB test matters:** hide every `mizu` mesh by name and the forest pond at y = 768
disappears with the flat sea quad at y = 0. The height test is the whole difference between
"the shore stopped being black" and "interior water vanished".

---

## 4. The traps, in one place

| symptom | cause | fix |
|---|---|---|
| everything black | unshaded shader output not in nits, vs a 31,800-nit white | multiply by `Game.scene_nits` |
| all you see is the HDR | sky dome at origin, frustum-culled | dome follows the camera |
| over-saturated | flat painted sky + no exposure + no sky reflection | PhysicalSky/HDR + CameraAttributesPhysical |
| metal renders dark | nothing to reflect | a real sky in the Environment (HDR or PhysicalSky) |
| F6 crashes | reloaded the whole 1224-actor scene each press | re-shade in place |
| clay/paper shrink-wrapped | NORMAL_MAP needs tangents the meshes lack | perturb NORMAL in world space |
| export fails randomly | OneDrive returns a partial file read | glb.pack retries the read |
| sun and shadow disagree | two sun sources | one source: the clock arc |
| shoreline reads black | opaque ocean + the stage's own baked sea sheet under it | depth-fade alpha, and hide baked sea at water level |
| night water under a noon sky | the sea read the clock, the sky did not | one palette, pushed from the stage into the shader |
| a surface vanishes from one side | cull mode dropped when the ShaderMaterial was built | `cull_disabled` shader twin, chosen per material |
| nothing missing reappears with culling off | the geometry genuinely is not there | build it (the rope bridge span came from PATH data) |
| an actor is built 400k units away | stage data keyed by `current_stage_key()` | key by the SCENE `name` - `sea_r44` has its own origin |
| planks tilt sideways along a span | `rotation` euler order is Y then X | build the Basis from the curve tangent |

Everything traces back to the two hard rules at the top.
