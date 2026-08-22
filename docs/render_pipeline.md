<title>Render Pipeline Map</title>

# The lighting and shader pipeline

How light and shading flow through the Wind Waker remake, so a change in one place has a
known blast radius. Everything here is what the code does today (ripper `b0d5a10`).

Two hard rules the whole thing rests on:

1. **Physical light units are on.** Every light is in **lux / lumens**, the camera has a real
   **exposure** (ISO 100, f/16, 1/100), and any **unshaded** surface must output **nits** or it
   renders black against a sunlit white of ~31,800 nits.
2. **The sun has one source: the game clock.** Shadows, the visible sun disc, and the toon
   ramp direction all read `Game.sun_direction`. Never let anything else steer it.

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

## 3. The traps, in one place

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

Everything traces back to the two hard rules at the top.
