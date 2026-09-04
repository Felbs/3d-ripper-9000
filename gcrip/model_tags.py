"""Heuristic classification of ripped models into browsable kinds - characters, weapons,
vehicles, level pieces, props, UI, effects.

There is no reliable type flag in the rips: a GameCube model is triangles, textures and a name.
So the kind is inferred from the model's **name and path** (rippers name members after the
engine's own asset names - ``chester.gcp``, ``gun_pistol``, ``level3_terrain``) plus two hard
signals from the geometry: ``skinned`` (a bone-weighted mesh is almost always a character or
creature) and ``animated``.  It is a heuristic and labelled as one; it is meant to make the data
lake searchable ("show me every sword", "characters with rigs"), not to be a ground truth.

`classify` returns one primary ``kind`` from :data:`KINDS`.  ``rigged`` (skinned) and
``animated`` stay separate boolean facets so a rigged character is both a ``character`` and
searchable by "rigged" - the user asked for characters with rigs to be their own filter.
"""

from __future__ import annotations

import re

# primary kinds, in the priority order a name is tested against (first hit wins); "character"
# and the fallbacks come last so a named weapon/vehicle/UI element is not swallowed by a
# character-ish token elsewhere in its path
KINDS = ("ui", "weapon", "vehicle", "effect", "character", "level", "prop", "unknown")

# each token is matched as a whole word against the lowercased "name path" (basename plus its
# folders, non-alphanumerics turned to spaces).  Tokens are chosen for precision - short or
# ambiguous fragments (man, arm, art) are avoided so "command" is not read as a weapon.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ui": (
        "hud", "icon", "menu", "font", "button", "logo", "ui", "gui", "cursor", "title",
        "splash", "loading", "legal", "banner", "portrait", "overlay", "reticle", "crosshair",
        "healthbar", "minimap", "compass", "billboard", "decal2d",
    ),
    "weapon": (
        "gun", "guns", "rifle", "pistol", "shotgun", "revolver", "blaster", "cannon",
        "bazooka", "launcher", "grenade", "missile", "rocket", "bomb", "bullet", "ammo",
        "sword", "swords", "blade", "katana", "sabre", "saber", "machete", "axe", "dagger",
        "knife", "spear", "lance", "halberd", "mace", "hammer", "warhammer", "flail", "club",
        "scythe", "sickle", "bow", "crossbow", "arrow", "staff", "wand", "whip", "shield",
        "weapon", "wpn", "firearm", "sidearm", "melee",
    ),
    "vehicle": (
        "car", "cars", "truck", "vehicle", "veh", "tank", "plane", "jet", "aircraft", "ship",
        "boat", "kart", "bike", "motorcycle", "mech", "chopper", "heli", "helicopter",
        "submarine", "buggy", "racer", "hovercraft", "spaceship", "starship", "wheel", "tire",
        "cockpit", "chassis", "sub", "jeep", "hovercar",
    ),
    "effect": (
        "fx", "vfx", "particle", "particles", "effect", "spark", "flame", "smoke", "explosion",
        "glow", "trail", "decal", "lightmap", "lightray", "flare", "splatter", "muzzle",
    ),
    "character": (
        "char", "chr", "actor", "player", "enemy", "enemies", "npc", "boss", "hero", "villain",
        "creature", "monster", "beast", "zombie", "soldier", "skeleton", "skel", "body", "head",
        "torso", "avatar", "character", "people", "person", "ped", "biped", "human", "humanoid",
        "dude", "warrior", "knight", "ninja", "robot", "droid", "alien", "mutant", "fighter",
    ),
    "level": (
        "level", "map", "world", "stage", "zone", "room", "terrain", "env", "environment",
        "scene", "scenery", "ground", "track", "bsp", "sector", "arena", "building", "house",
        "wall", "floor", "ceiling", "bridge", "road", "skybox", "backdrop", "landscape",
        "tile", "tileset", "dungeon", "cave", "forest", "city", "street", "platform", "geom",
        "collision", "collmesh", "worldmesh", "mapmesh",
    ),
    "prop": (
        "prop", "item", "pickup", "collectible", "coin", "ring", "gem", "crystal", "box",
        "crate", "barrel", "chest", "key", "door", "powerup", "health", "furniture", "chair",
        "table", "lamp", "bottle", "food", "fruit", "torch", "sign", "flag", "gear", "object",
        "obj", "static", "destructible", "trap",
    ),
}

# compiled once: kind -> regex matching any of its whole-word tokens
# long, unambiguous tokens also matched as substrings, so compound asset names hit too
# ("steelsword", "racecar", "gunship" would all miss on word boundaries alone)
_SUBSTRINGS: dict[str, tuple[str, ...]] = {
    "weapon": (
        "sword", "rifle", "pistol", "shotgun", "bazooka", "grenade", "missile", "katana",
        "dagger", "machete", "crossbow", "halberd", "scythe", "weapon",
    ),
    "vehicle": ("racecar", "motorbike", "airplane", "helicopter", "speedboat", "vehicle"),
    "character": ("character", "monster", "zombie", "soldier", "creature"),
    "effect": ("particle", "explosion", "lightmap"),
}


def _compile(kind: str, toks: tuple[str, ...]) -> re.Pattern:
    body = "|".join(re.escape(t) for t in toks)
    pat = r"(?:^|[^a-z0-9])(?:" + body + r")(?:[^a-z0-9]|$)"
    subs = _SUBSTRINGS.get(kind)
    if subs:
        pat += "|" + "|".join(re.escape(t) for t in subs)
    return re.compile(pat)


_PATTERNS: dict[str, re.Pattern] = {k: _compile(k, toks) for k, toks in _KEYWORDS.items()}


def _haystack(name_or_path: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name_or_path or "").lower())


def classify(name_or_path: str, *, skinned: bool = False, animated: bool = False) -> str:
    """The primary kind for one model - one of :data:`KINDS`.

    Name/path tokens are tested in :data:`KINDS` priority order; if none match, a skinned or
    animated mesh is a ``character`` (the rig is the signal), and everything else is ``unknown``.
    """
    hay = _haystack(name_or_path)
    for kind in KINDS[:-1]:  # every kind except the "unknown" sentinel
        if _PATTERNS[kind].search(hay):
            # a bone-weighted mesh that only matched "level"/"prop" by a stray token is still
            # a character - the rig outweighs a weak name hit
            if kind in ("level", "prop") and skinned:
                return "character"
            return kind
    if skinned or animated:
        return "character"
    return "unknown"


def tags(name_or_path: str, *, skinned: bool = False, animated: bool = False) -> dict:
    """Kind plus the independent boolean facets, for one model."""
    return {
        "kind": classify(name_or_path, skinned=skinned, animated=animated),
        "rigged": bool(skinned),
        "animated": bool(animated),
    }
