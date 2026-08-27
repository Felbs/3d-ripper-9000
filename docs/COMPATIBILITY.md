# Compatibility

`gcrip survey` + `gcrip dump` over a 638-disc GameCube library (USA set), 2026-08-26. 18 discs processed, 0 errored. No game data is stored here - only counts.

## Games that rip (J3D models -> glTF)

| game | ID | models | dups | failed | clips | animated | expressions | Mixamo rigs | textured % | textures | extras | s | notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| The Legend of Zelda Twilight Princess | GZ2E01 | 2,489 | 1,137 | 0 | 13,822 | 755 | 213 | 257 | 97.5 | 1,704 |  | 658 |  |
| THE LEGEND OF ZELDA The Wind Waker for USA | GZLE01 | 1,856 | 902 | 0 | 4,175 | 432 | 117 | 76 | 95.6 | 1,867 | stages 156, text, streams 76, music 93, cutscenes 48 | 590 |  |
| The Legend of Zelda: Collector's Edition | PZLE01 | 1,710 | 624 | 0 | 4,175 | 432 | 117 | 76 | 95.3 | 1,784 |  | 282 | the Wind Waker demo inside `ZL_WindWakerUSASHOP_*.tgc`; OoT/MM are N64 ROMs (not J3D) |
| Super Mario Sunshine | GMSE01 | 712 | 8,072 | 0 | 10,039 | 633 | 32 | 4 | 90.7 | 754 |  | 483 | byte-identical duplicates skipped (every level .szs repeats the NPC set) |
| PIKMIN2 for GAMECUBE | GPVE01 | 683 | 438 | 0 | 372 | 299 | 0 | 1 | 97.4 | 17,232 |  | 167 |  |
| DONKEY KONG JUNGLE BEAT | GYBE01 | 486 | 6 | 0 | 1,947 | 207 | 22 | 18 | 95.3 | 240 |  | 138 |  |
| Mario Kart Double Dash! | GM4E01 | 387 | 335 | 0 | 199 | 116 | 35 | 2 | 95.1 | 1,090 |  | 53 |  |
| LUIGI'S MANSION | GLME01 | 73 | 37 | 0 | 98 | 56 | 0 | 0 | 100.0 | 1,393 | streams 2 | 31 | few BMDs; rooms/characters use Luigi's Mansion's own `.mdl` + `.bin` formats - future module |
| The Legend of Zelda: Four Swords FOR NINTENDO GAMECUBE | G4SE01 | 63 | 50 | 0 | 0 | 0 | 0 | 0 | 100.0 | 2,593 |  | 24 | GBA-era assets; small BMDs |
| PAC-MAN vs. | PRJE01 | 20 | 0 | 0 | 5 | 3 | 1 | 0 | 100.0 | 189 |  | 9 |  |
| POKeMON BOX RUBY&SAPPHIRE | GPXE01 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 100.0 | 2,017 |  | 4 | 8 Pokémon storage models |

**Total: 11 games, 8,487 unique models, 34,832 animation clips, 0 model failures.**

## Games where only standalone textures come out (TPL/BTI, no J3D models)

Every one of these ran through the full pipeline without error; their models are in
formats gcrip does not parse yet (see the engine guesses below).

| game | ID | textures | engine guess |
|---|---|---:|---|
| James Bond 007(tm): NightFire(tm) | GO7E69 | 2 | EA (BIG/VIV) |
| 2006 FIFA World Cup | G6FE69 | 2 | EA (BIG/VIV) |
| Jimmy Neutron Boy Genius | GJNE78 | 2 | THQ |
| Alien Hominid | GAHEGG | 1 | custom (.pak) |

## Games that produce nothing yet (3)

Walked and manifested without error (disc filesystem, archives), but no format gcrip
knows how to decode. Grouped by the survey's engine guess; each group is a candidate
for a new parser module or the Dolphin capture fork.

| engine / publisher guess | discs | examples |
|---|---:|---|
| EA (BIG/VIV) | 2 | 007: Agent Under Fire (tm), 007: Everything or Nothing |
| custom (.all) | 1 | 18 Wheeler |

## Survey engine guesses (whole library)

| engine / publisher guess | discs |
|---|---:|
| EA (BIG/VIV) | 51 |
| EA | 51 |
| THQ | 47 |
| Activision | 44 |
| Ubisoft | 35 |
| Capcom | 24 |
| custom (.bin) | 23 |
| custom (.tpl) | 22 |
| custom (.dsp) | 21 |
| custom (.dat) | 17 |
| custom (.adp) | 14 |
| custom (.thp) | 13 |
| custom (.(none)) | 12 |
| custom (.h4m) | 11 |
| J3D | 11 |
| Nintendo (DAT) | 9 |
| custom (.bik) | 7 |
| custom (.pak) | 6 |
| custom (.rel) | 6 |
| custom (.str) | 6 |
| custom (.fpk) | 6 |
| custom (.afs) | 6 |
| custom (.hps) | 6 |
| custom (.tex) | 4 |
| Nintendo (RARC/U8, non-J3D) | 4 |
| custom (.gcp) | 4 |
| custom (.sfd) | 4 |
| custom (.spd) | 4 |
| custom (.txt) | 4 |
| custom (.bnr) | 4 |
| custom (.avi) | 4 |
| custom (.ngc) | 3 |
| custom (.pc) | 3 |
| custom (.rcf) | 3 |
| custom (.loc) | 3 |
| custom (.dol) | 3 |
| custom (.wad) | 3 |
| Sega (PRS) | 3 |
| custom (.pod) | 2 |
| custom (.zit) | 2 |
| custom (.rws) | 2 |
| custom (.lmp) | 2 |
| custom (.gct) | 2 |
| custom (.rar) | 2 |
| custom (.res) | 2 |
| custom (.vo) | 2 |
| custom (.bdg) | 2 |
| custom (.rom) | 2 |
| custom (.mid) | 2 |
| custom (.adx) | 2 |
| custom (.bmp) | 2 |
| custom (.png) | 2 |
| custom (.arc) | 2 |
| custom (.mss) | 2 |
| custom (.wav) | 2 |
| custom (.hdr) | 2 |
| Retro (PAK/CMDL) | 2 |
| custom (.dff) | 2 |
| custom (.ssf) | 2 |
| custom (.blt) | 2 |
| custom (.fsys) | 2 |
| custom (.gmf) | 2 |
| custom (.dgc) | 2 |
| custom (.all) | 1 |
| custom (.wgs) | 1 |
| custom (.pik) | 1 |
| custom (.obj) | 1 |
| custom (.lfb) | 1 |
| custom (.mds) | 1 |
| custom (.prd) | 1 |
| custom (.cc2) | 1 |
| custom (.rep) | 1 |
| custom (.zal) | 1 |
| custom (.sgd) | 1 |
| custom (.bgd) | 1 |
| custom (.pal) | 1 |
| custom (.tpf) | 1 |
| custom (.aob) | 1 |
| custom (.cct) | 1 |
| custom (.ani) | 1 |
| custom (.atx) | 1 |
| custom (.dtk) | 1 |
| custom (.dsq) | 1 |
| custom (.w2d) | 1 |
| custom (.chk) | 1 |
| custom (.irx) | 1 |
| custom (.cha) | 1 |
| custom (.ga) | 1 |
| custom (.ggf) | 1 |
| custom (.ast) | 1 |
| custom (.hfs) | 1 |
| custom (.song) | 1 |
| custom (.jam) | 1 |
| custom (.coc) | 1 |
| custom (.aka) | 1 |
| custom (.psc) | 1 |
| custom (.gvr) | 1 |
| custom (.rez) | 1 |
| custom (.asr) | 1 |
| custom (.xmd) | 1 |
| custom (.bgg) | 1 |
| custom (.scp) | 1 |
| custom (.can) | 1 |
| custom (.iff) | 1 |
| custom (.cat) | 1 |
| custom (.lgc) | 1 |
| custom (.wvs) | 1 |
| custom (.ste) | 1 |
| custom (.cgs) | 1 |
| custom (.cam) | 1 |
| custom (.spch) | 1 |
| custom (.blo) | 1 |
| custom (.pvr) | 1 |
| custom (.fbc) | 1 |
| custom (.sph) | 1 |
| custom (.xgc) | 1 |
| custom (.bti) | 1 |
| custom (.gcx) | 1 |
| custom (.bsf) | 1 |
| custom (.d4) | 1 |
| custom (.gtd) | 1 |
| custom (.msf) | 1 |
| custom (.adpcm) | 1 |
| custom (.gcg) | 1 |
| custom (.ssw) | 1 |
| custom (.one) | 1 |
| custom (.har) | 1 |
| custom (.p3d) | 1 |
| custom (.mld) | 1 |
| custom (.pdm) | 1 |
| custom (.bog) | 1 |
| custom (.pcm) | 1 |
| custom (.ilg) | 1 |
| custom (.movie) | 1 |
| custom (.vsp) | 1 |
| custom (.fuc) | 1 |
| custom (.be) | 1 |
| custom (.idsp) | 1 |
| custom (.lz) | 1 |
| custom (.an2) | 1 |
| custom (.slz) | 1 |
| custom (.pck) | 1 |
| custom (.x3g) | 1 |
| custom (.stm) | 1 |
| custom (.bnk) | 1 |
| custom (.gmb) | 1 |
| custom (.h) | 1 |
| custom (.rbb) | 1 |
| custom (.mrg) | 1 |
| custom (.igb) | 1 |
