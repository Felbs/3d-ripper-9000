# Ubisoft on GameCube - engine map (census 2026-08-29, nothing decoded yet)

## Unreal Engine 2 (Ubisoft Shanghai / Montreal GC builds) - 10 discs

Splinter Cell (2003), Pandora Tomorrow, Chaos Theory (x2 dumps), Double Agent (x2), Rainbow
Six 3, Ghost Recon 2, XIII share one container set:
- `.umd` (`files/System/warlins.umd`, 190 MB): `u32 0x00018000 | u32 size | zlib stream`
  that inflates to an archive of Unreal packages (`0_0_2.unr` ... - map/.utx/.usx files);
  `warship.umd` is the INI-style config text.
- `.sm3` / `.lm3` (`files/Sounds/MAPS.SM3`): `u32 7 | u32 0x20 | u32 count | ... ` sound
  maps; `.ss3` / `.ls3` audio streams; `.sb3` / `.s3` sound banks; `.lin` = level data (per
  map, 30-60 files, 130-320 MB); Pandora also has `.usx` (28 static-mesh packages).
Ripping = inflate the umd/lin archives, then a UE2 package reader (names / imports /
exports + StaticMesh / SkeletalMesh / Texture serialisation, GC-endian). Reference:
Gildor's umodel (C++). Multi-day job; parked.

## OpenSpace / CPA (Ubisoft Montpellier) - Rayman 3, Rayman Arena

`.hst` (sound), `.lvl` + `.ptr` (level + pointer relocation), `.hxg`/`.hxd`, `.tpl` (GC
textures, 139 files). Reference implementation: github.com/byvar/raymap (C# Unity loader for
Rayman 2/3/Arena incl. GC). Parked.

## Jade (Ubisoft Montpellier)

Beyond Good & Evil and Prince of Persia: Sands of Time / Warrior Within / The Two Thrones
already rip through the jade plugin (`files/prince.bf` BIG file -> ~2.5k `.bin` members;
Warrior Within check 2026-08-29: 301 members -> 3,067 scenes / 4.19 M triangles). Peter
Jackson's King Kong (GWKE41) is textures-only: its later Jade build is not decoded yet.
