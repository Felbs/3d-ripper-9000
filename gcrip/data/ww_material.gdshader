shader_type spatial;
render_mode blend_mix, depth_draw_opaque, cull_back, diffuse_lambert, specular_schlick_ggx;
// gcrip: the lit material for The Wind Waker remake.  One shader, several LOOKS, chosen by
// `look`, so the same surface can be compared across them with F6:
//   0 toon    - the game's own TEV recipe: albedo * mix(C0, K0, ramp(N.L)).  Unlit otherwise.
//   1 hybrid  - that ramp as the diffuse, plus a physical specular / sheen / Fresnel lobe on
//               top, only where the material class asks for it (metal, water, eyes, glass).
//   2 clay    - matte stop-motion clay: a soft wrapped diffuse with a subsurface warm-up in the
//               terminator, high roughness, a faint fingerprint micro-normal, no sharp specular.
//   3 paper   - papercraft: flat albedo on a fibre micro-normal, rim-lit edges, a little
//               translucency (backlight), almost no specular.
//   4 pbr     - straight Burley/GGX, the comparison case the assessment warns about.
//
// Lobes, with the references they come from (the assessment checked each):
//   diffuse     Lambert, or the WW ramp lookup (a hard terminator from toon.bti)
//   specular    GGX / Trowbridge-Reitz NDF (Walter 2007), Smith height-correlated visibility
//               (Heitz 2014), Schlick Fresnel (1994) with F0 = mix(0.08 * specular, albedo, metal)
//   sheen       the Charlie NDF + Ashikhmin visibility from Conty Estevez & Kulla 2017 -
//               exactly what KHR_materials_sheen specifies.  Godot has no sheen lobe of its
//               own, so it is written here.
//   clearcoat   a second GGX lobe at fixed F0 0.04, for lacquered wood / the Picto Box lens.

uniform int look = 1;

// ---- what the surface is made of ---------------------------------------------------------
uniform sampler2D albedo_tex : source_color, filter_linear_mipmap;
uniform vec4 albedo_col : source_color = vec4(1.0);
uniform bool has_tex = true;
uniform float alpha_scissor = 0.0;
uniform float metallic = 0.0;
uniform float roughness = 0.75;
uniform float specular = 0.5;        // dielectric F0 = 0.08 * specular (Godot's convention)
uniform vec3 sheen_color : source_color = vec3(0.0);
uniform float sheen_roughness = 0.35;
uniform float clearcoat = 0.0;
uniform float clearcoat_roughness = 0.05;
uniform float backlight = 0.0;       // paper: light leaking through the sheet
uniform float micro_normal = 0.0;    // clay / paper: strength of the procedural surface grain
uniform float grain_scale = 18.0;

// ---- the toon half, kept byte-identical to toon.gdshader -------------------------------
uniform sampler2D toon_ramp : filter_linear;
uniform vec3 c0 : source_color = vec3(0.42, 0.44, 0.52);   // TEV register 0 - the "ambient"
uniform vec3 k0 : source_color = vec3(1.0, 0.94, 0.82);    // konst 0 - the lit colour
uniform float nits = 1.0;   // physical units: the toon look's emission is luminance

varying vec3 v_world_pos;

// ---- helpers -----------------------------------------------------------------------------
float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

// cheap value noise, for the clay fingerprint / paper fibre micro-normal
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i), b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0)), d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float D_ggx(float NdotH, float a) {
    float a2 = a * a;
    float d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    return a2 / (3.14159265 * d * d);
}

float V_smith_ggx(float NdotV, float NdotL, float a) {
    // Heitz 2014, height-correlated, already divided by 4 NdotL NdotV
    float a2 = a * a;
    float gv = NdotL * sqrt(NdotV * NdotV * (1.0 - a2) + a2);
    float gl = NdotV * sqrt(NdotL * NdotL * (1.0 - a2) + a2);
    return 0.5 / max(gv + gl, 1e-5);
}

vec3 F_schlick(vec3 f0, float VdotH) {
    float f = pow(1.0 - VdotH, 5.0);
    return f0 + (1.0 - f0) * f;
}

// Conty Estevez & Kulla 2017 - the "Charlie" sheen distribution, as KHR_materials_sheen
float D_charlie(float NdotH, float sheen_r) {
    float a = max(sheen_r * sheen_r, 1e-3);
    float inv_a = 1.0 / a;
    float sin2 = 1.0 - NdotH * NdotH;
    return (2.0 + inv_a) * pow(sin2, inv_a * 0.5) / (2.0 * 3.14159265);
}

float V_ashikhmin(float NdotV, float NdotL) {
    return 1.0 / (4.0 * max(NdotL + NdotV - NdotL * NdotV, 1e-5));
}

void vertex() {
    v_world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
    vec4 base = has_tex ? texture(albedo_tex, UV) * albedo_col : albedo_col;
    if (alpha_scissor > 0.0 && base.a < alpha_scissor) {
        discard;
    }
    ALBEDO = base.rgb;
    ALPHA = base.a;
    float rough = roughness;
    float spec = specular;
    if (look == 2) {            // clay: matte, a touch of sheen-like softness, no mirror
        rough = max(roughness, 0.85);
        spec = min(specular, 0.25);
    } else if (look == 3) {     // paper: flatter still, and the fibres are the only texture
        rough = max(roughness, 0.9);
        spec = min(specular, 0.15);
    }
    ROUGHNESS = rough;
    METALLIC = (look == 2 || look == 3) ? 0.0 : metallic;
    SPECULAR = spec;
    if (micro_normal > 0.0) {
        // a procedural grain in world space so it never swims with UV seams: thumbprints on
        // clay, fibres on paper
        vec2 p = v_world_pos.xz * (1.0 / grain_scale) + v_world_pos.y * 0.013;
        float n1 = vnoise(p);
        float n2 = vnoise(p * 2.7 + 11.3);
        float h = (look == 3) ? mix(n1, n2, 0.5) : n1 * 0.7 + n2 * 0.3;
        float dx = vnoise(p + vec2(0.05, 0.0)) - h;
        float dy = vnoise(p + vec2(0.0, 0.05)) - h;
        NORMAL_MAP = normalize(vec3(-dx * micro_normal * 6.0, -dy * micro_normal * 6.0, 1.0)) * 0.5 + 0.5;
        NORMAL_MAP_DEPTH = 1.0;
    }
    if (look == 3 && backlight > 0.0) {
        BACKLIGHT = vec3(backlight);
    }
    if (look == 0) {
        // pure toon: the lighting is the ramp and nothing else; emit it and skip the lights
        vec3 n = normalize(NORMAL);
        vec3 l = normalize(mat3(VIEW_MATRIX) * vec3(-0.55, 0.72, -0.42));
        float d = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
        float toon = texture(toon_ramp, vec2(d, 0.5)).r;
        EMISSION = base.rgb * mix(c0, k0, toon) * nits;
        ALBEDO = vec3(0.0);
        SPECULAR = 0.0;
    }
}

void light() {
    // This replaces Godot's per-light loop for the material.  Everything below is per light.
    vec3 n = normalize(NORMAL);
    vec3 l = normalize(LIGHT);
    vec3 v = normalize(VIEW);
    vec3 h = normalize(l + v);
    float NdotL = dot(n, l);
    float NdotV = max(dot(n, v), 1e-4);
    float NdotH = max(dot(n, h), 0.0);
    float VdotH = max(dot(v, h), 0.0);
    vec3 radiance = LIGHT_COLOR * ATTENUATION;

    // ---- diffuse, by look
    vec3 diff;
    if (look == 1) {
        // the game's own terminator: ramp(N.L) blends C0 and K0, then the albedo multiplies it.
        // Here the lit colour is the LIGHT's own, so the ramp only shapes the falloff.
        float d = clamp(NdotL * 0.5 + 0.5, 0.0, 1.0);
        float toon = texture(toon_ramp, vec2(d, 0.5)).r;
        diff = ALBEDO * mix(c0 * 0.6, vec3(1.0), toon);
    } else if (look == 2) {
        // clay: a wrapped Lambert so the terminator is soft and wide, and the shadowed side
        // warms up the way light scatters a few millimetres into a clay surface
        float w = 0.45;
        float wrapped = clamp((NdotL + w) / (1.0 + w), 0.0, 1.0);
        vec3 sss = vec3(1.0, 0.62, 0.45) * 0.18 * pow(1.0 - wrapped, 2.0);
        diff = ALBEDO * (wrapped + sss);
    } else if (look == 3) {
        // paper: nearly flat - most of the depth comes from the fibre normal and the rim
        float w = 0.3;
        float wrapped = clamp((NdotL + w) / (1.0 + w), 0.0, 1.0);
        float rim = pow(1.0 - NdotV, 3.0) * 0.35;
        diff = ALBEDO * (mix(0.55, 1.0, wrapped) + rim);
    } else {
        diff = ALBEDO * max(NdotL, 0.0);
    }
    float m = (look == 2 || look == 3) ? 0.0 : METALLIC;
    vec3 f0 = mix(vec3(0.08 * SPECULAR_AMOUNT), ALBEDO, m);
    vec3 F = F_schlick(f0, VdotH);
    DIFFUSE_LIGHT += diff * (1.0 - F) * (1.0 - m) * radiance;

    // light() may not `return`, so the lit side is one conditional block
    if (NdotL > 0.0) {
        // ---- specular: GGX + Smith + Schlick
        float a = max(ROUGHNESS * ROUGHNESS, 0.002);
        vec3 specular_lobe = D_ggx(NdotH, a) * V_smith_ggx(NdotV, NdotL, a) * F;
        vec3 out_spec = specular_lobe * NdotL;

        // ---- sheen: Charlie + Ashikhmin (KHR_materials_sheen)
        if (dot(sheen_color, sheen_color) > 0.0 && look != 0) {
            float sd = D_charlie(NdotH, sheen_roughness);
            float sv = V_ashikhmin(NdotV, NdotL);
            out_spec += sheen_color * sd * sv * NdotL;
        }
        // ---- clearcoat: a thin lacquer at F0 0.04
        if (clearcoat > 0.0 && look != 0) {
            float ca = max(clearcoat_roughness * clearcoat_roughness, 0.002);
            float cf = 0.04 + 0.96 * pow(1.0 - VdotH, 5.0);
            out_spec += vec3(clearcoat * D_ggx(NdotH, ca) * V_smith_ggx(NdotV, NdotL, ca) * cf * NdotL);
        }
        SPECULAR_LIGHT += out_spec * radiance;
    }
}
