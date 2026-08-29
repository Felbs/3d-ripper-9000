# Konami on GameCube - engine map (census 2026-08-29, nothing decoded)

17 Konami discs without models; no shared engine:
- Teenage Mutant Ninja Turtles 1-3 (Konami TYO): `TMNT.DAT` etc. are Sega-style AFS archives
  (`AFS\0`, 731 members in TMNT 1) whose members start with small LE counts (`23 00 00 00`,
  `10 00 00 00`, `0b 00 00 00`) plus a few PNG/BMP - Konami's own model/scene tables. TMNT:
  Mutant Melee: `archive.dat` (219 MB, `1b 00 00 00 dc 16 00 00`), `.bkt`, `.mcp`.
  (TMNT 2007 is Ubisoft Jade and already rips.)
- Frogger Beyond: `.bin` x35 (238 MB), `.mcp` 66 MB, `.bkt`; Frogger's Adventures similar.
- Yu-Gi-Oh! The Falsebound Kingdom: `.pac` x2 (221 MB), `.mrg` x62 (165 MB).
- Disney Sports Soccer/Football/Basketball, ESPN MLS / Winter Sports (`.irx`, `.sxq`, `.bin`,
  `.rom`), Evolution Skateboarding/Snowboarding (`.bin`, `.fbd`, `.rel`), Winning Eleven 6,
  Captain Tsubasa, WTA Tour Tennis: each its own container.
Priority: low per title; TMNT 1-3 (3 discs, one engine) would be the first to reverse.
