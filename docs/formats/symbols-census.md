# Discs that ship their own symbols (census 2026-09-03)

Bratz: Rock Angelz's `Bratz_NGC_M.elf` carried full DWARF 1 debug info, and reading the engine's
struct layouts out of it (`tools/dwarf1.py`) turned a two-day format hunt into an afternoon.
This is every disc in the library whose file list carries an `.elf`, or a linker `.map` / `.sym`
over 200 KB.  A big `.elf` is a debug build with DWARF; a `.map` gives function names and
addresses to pair with the DOL disassembly.  **Read these before guessing at a format.**

| disc | id | ELFs | maps / symbols |
|---|---|---|---|
| Goblet Of Fire | GH4E69 | `gof_f.elf` 277639 KB, `gof_f_us.elf` 5128 KB |  |
| Muppets Party Cruise | GM9E6S | `Muppets.elf` 69817 KB |  |
| Jeremy McGrath SuperCross World | GSCE51 | `sx2002.elf` 60852 KB | `sx2002.MAP` 2600 KB |
| FIFA Soccer 2004 | GXFE69 | `FIFA_a.elf` 46939 KB, `FIFA_d.elf` 55373 KB, `FIFA_p.elf` 42574 KB, `FIFA_z.elf` 7790 KB |  |
| Mario Soccer | G4QE01 | `MarioSoccerP.elf` 20110 KB, `MarioSoccerR.elf` 41814 KB | `MarioSoccerD.MAP` 7029 KB, `MarioSoccerP.MAP` 4589 KB, `MarioSoccerR.MAP` 5087 KB |
| Dinotopia: The Sunstone Odyssey | GD4E6S | `Dinotopia.elf` 27976 KB | `Map05.map` 2278 KB, `Map02.map` 4811 KB, `Map01.map` 5199 KB |
| SpongeBob: CFTKK | GQ4E78 | `SpongeBob_ngc_mfb.elf` 25056 KB |  |
| NASCAR 2005 | GN4E69 | `NASCAR05.ELF` 18293 KB |  |
| GoldenEye Rogue Agent | GOYE69 | `GE2RDVD.ELF` 18189 KB, `LOADRDVD.ELF` 264 KB, `STUBRDVD.ELF` 268 KB |  |
| GoldenEye Rogue Agent | GOYE69 | `GE2RDVD.ELF` 18189 KB, `LOADRDVD.ELF` 264 KB, `STUBRDVD.ELF` 268 KB |  |
| Medal of Honor European Assault | GONE69 | `LOADRDVD.ELF` 337 KB, `MOH4RDVD.ELF` 17877 KB, `STUBRDVD.ELF` 339 KB |  |
| Need for Speed(TM) Underground 2 | GUGE69 | `Speed.elf` 16505 KB |  |
| Smashing Drive | GSDEAF | `smash.elf` 12322 KB |  |
| Disney's Hide & Sneak | GHVE08 | `Mickey2.elf` 11258 KB |  |
| Bratz: Rock Angelz | GR6E78 | `Bratz_NGC_M.elf` 10633 KB |  |
| Midway Arcade Treasures 3 | GE3E5D | `badlands.elf` 1130 KB, `ffe.elf` 1032 KB, `hydro_d.elf` 3808 KB, `movie.elf` 1044 KB |  |
| NFS Underground | GNDE69 | `Speed.elf` 8259 KB |  |
| Aquaman: Battle for Atlantis | GAQE6S | `Aquaman_GCN.elf` 7997 KB |  |
| Mission: Impossible Operation Surma | GMIE70 | `IMF_GC-Final.elf` 7809 KB |  |
| Terminator 3: The Redemption | GT6E70 | `t3game_gc.elf` 7509 KB |  |
| Ty3 | GIZE52 | `Ty3.elf` 7419 KB |  |
| spyro06 | G6SE7D | `spyro06.elf` 7149 KB |  |
| Star Wars : The Clone Wars | GSXE64 | `Clonewars.elf` 7128 KB |  |
| TONKA Rescue Patrol | GTQE6S | `Tonka_gcn.elf` 6864 KB |  |
| Ty2 | GYTE69 | `Ty2.elf` 6841 KB |  |
| MVP Baseball 2005 | GV4E69 | `mvp.elf` 6838 KB |  |
| NBA LIVE 06 | G6NE69 | `nba2006f.elf` 6607 KB |  |
| Ratatouille | GLLE78 | `ratsgc_m.elf` 6290 KB |  |
| Mortal Kombat Deception | GQNE5D | `mk6gc_release.elf` 6255 KB | `mk6gc_release.MAP` 5281 KB |
| The SpongeBob SquarePants Movie | GGVE78 | `sb04gc_nm.elf` 6240 KB |  |
| The Incredibles | GICE78 | `ingc_m.elf` 6217 KB |  |
| The Incredibles 2 | GIQE78 | `in2gc_m.elf` 6166 KB |  |
| Kao the kangaroo | GKOE70 | `kao2gcnF.elf` 6049 KB |  |
| King Kong | GWKE41 | `jadegc_ia2cr.elf` 5899 KB |  |
| Freedom Fighters | GFDE69 | `startup_release.elf` 5756 KB |  |
| MVP Baseball 2004 | GVPE69 | `mvp.elf` 5723 KB |  |
| NHL Hitz 2003 | GN3E5D | `nhlhitzr.elf` 5537 KB |  |
| FIFA 2003 | GFAE69 | `FIFA_z.elf` 5504 KB |  |
| TY the Tasmanian Tiger | GTYE69 | `TY_REL.elf` 5327 KB |  |
| Pac-Man World 3 | GP8EAF | `PMA_GC_M.elf` 5321 KB |  |
| Marvel Nemesis: Rise of the Imperfects | GVLE69 | `GameGC.elf` 5304 KB |  |
| Jimmy Neutron: Jet Fusion | GJFE78 | `Jimmy.elf` 5228 KB |  |
| FIFA 07 | G4FE69 | `elfldr.elf` 211 KB, `fifa_z.elf` 5135 KB |  |
| SpongeBob SquarePants: Battle for Bikini Bottom | GQPE78 | `sbgcM.elf` 5099 KB |  |
| Dark Summit | GDSE78 | `mob2gr.elf` 5069 KB |  |
| 2006 FIFA World Cup | G6FE69 | `elfldr.elf` 211 KB, `fifa_z.elf` 5061 KB, `fifa_zj.elf` 5065 KB |  |
| Cars | GKJE78 | `CarsGCN.elf` 5049 KB |  |
| Fairly OddParents - Breakin' Da Rules | GFWE78 | `Gamecube.elf` 5029 KB |  |
| FIFA 06 | GF6E69 | `elfldr.elf` 211 KB, `fifa_z.elf` 4939 KB |  |
| UEFA Champions League 2004 - 2005 | GUCP69 | `fifa_z.elf` 4858 KB | `fifa_z.map` 2140 KB |
| King Arthur | GKHEA4 | `Arthur.elf` 4749 KB |  |
| The Sims 2 Pets | G4OE69 | `u2_ngc_release_dvd_sku.elf` 4731 KB |  |
| 007: Agent Under Fire (tm) | GW7E69 | `base.elf` 252 KB, `Bond.elf` 4729 KB, `boot.elf` 252 KB, `driving.elf` 3494 KB |  |
| Mortal Kombat Deadly Alliance | GMKE5D | `mk5gc_release.elf` 4718 KB |  |
| RoadKill | GOCE5D | `Hunter.elf` 4656 KB |  |
| The Sims 2 GameCube | G4ZE69 | `u2_ngc_release_dvd.elf` 4645 KB | `u2_ngc_debug.map` 4187 KB, `u2_ngc_release.map` 3867 KB, `u2_ngc_release_dvd.map` 2636 KB |
| Winnie the Pooh | GWHE41 | `winnie.elf` 4640 KB |  |
| FIFA Soccer 2005 | GF5E69 | `fifa_z.elf` 4623 KB | `fifa_z.map` 1883 KB |
| Spyro | G5SE7D | `Spyro.elf` 4492 KB |  |
| FIFA Street 2 | GFYE69 | `fifast2_ntsc.elf` 4397 KB |  |
| The Urbz GameCube | GUBE69 | `tsc3_ngc_release_dvd.elf` 4317 KB |  |
| Piglet's BIG GAME | GPLE9G | `Piglet.elf` 4264 KB |  |
| FIFA Street | GF8E69 | `fifast.elf` 4258 KB |  |
| DISNEY'S PK: OUT OF THE SHADOWS | GPKE41 | `RM_DLL.elf` 4243 KB |  |
| Project Zoo | GWLE6L | `Zoo_GC.elf` 4068 KB |  |
| Army Men Air Combat | GACE5H | `ArmymenGC.elf` 2204 KB, `ArmymenGCDbg.elf` 4029 KB |  |
| Blowout | GWOE5G | `Blowout.elf` 3900 KB |  |
| ZooCube | GZCE51 | `ZooCube.elf` 3849 KB |  |
| Freestyle Metal X | GFXE5D | `FMX_CUBE_Publisher.elf` 3825 KB |  |
| CASPER | GCPE6S | `casperGCN.elf` 3739 KB |  |
| Batman | GINE69 | `Batman.elf` 3689 KB |  |
| BloodRayne | GBDE5G | `bloodrayne.elf` 3687 KB |  |
| NHL HITZ 20-02 | GNHE5d | `nhlhitzr.elf` 3651 KB |  |
| Medal of Honor Rising Sun | GR8E69 | `MOH3RDC.ELF` 3583 KB, `MOH3RDVD.ELF` 3628 KB, `STUBRDVD.ELF` 260 KB |  |
| Medal of Honor Rising Sun | GR8E69 | `MOH3RDC.ELF` 3583 KB, `MOH3RDVD.ELF` 3628 KB, `STUBRDVD.ELF` 260 KB |  |
| Scooby-Doo!(tm) Mystery Mayhem | GC3E78 | `engine_ret.elf` 3608 KB | `engine_ret.MAP` 4595 KB |
| Bratz: Forever Diamondz | GVDE78 | `Bratz_Gamecube Master Fast Build.elf` 3592 KB | `Bratz_Gamecube Master Fast Build.map` 1822 KB |
| Tetris Worlds | GTRE78 | `TWgr.elf` 3583 KB |  |
| BIG AIR FREESTYLE | GMRE70 | `LoadAndParseELF.elf` 3537 KB |  |
| GrooveRider | GVRE7H | `GrooveM.elf` 3516 KB | `Groove.map` 1334 KB, `GrooveD.map` 2267 KB, `GrooveM.map` 1330 KB |
| The Polar Express | GP3E78 | `PolarExpress.elf` 3481 KB |  |
| BysBase07 | GA7E70 | `Mpe.Gcn.Release.elf` 3478 KB |  |
| SX Superstar | GS3E51 | `Supercross.elf` 3460 KB |  |
| Frogger Beyond | GFGEA4 | `Frogger.elf` 3449 KB |  |
| Scaler | GKUE9G | `engine_ret.elf` 3344 KB |  |
| 4x4 Evolution 2 | GE4E7D | `4x4.elf` 3304 KB |  |
| Scooby-Doo! Unmasked | G5DE78 | `engine_ret.elf` 3286 KB |  |
| Sphinx and the Cursed Mummy | GXPE78 | `Sphinx.elf` 3063 KB |  |
| Ice Age 2 The Meltdown | GIAE7D | `IceAge2.elf` 3056 KB |  |
| Nickelodeon Party Blast | GN9E70 | `nGamesGC.elf` 3038 KB |  |
| Smugglers Run Warzones | GSRE7S | `sr.elf` 3017 KB |  |
| James Bond 007(tm): NightFire(tm) | GO7E69 | `BaseGC_Release.elf` 610 KB, `ColdGC_Release.elf` 611 KB, `driving.elf` 2924 KB, `Nightfire.elf` 2170 KB |  |
| Medal of Honor Frontline | GMFE69 | `Moh2RelGC.elf` 2866 KB, `Moh2StubRelGC.elf` 278 KB |  |
| Robots | GZQE7D | `Robots.elf` 2825 KB |  |
| Strike Force Bowling | G5BE4Z | `GCN_bowlR.elf` 2764 KB |  |
| Namco Museum(tm) 50th Anniversary | G5NEAF | `ffe.elf` 2757 KB, `Namco50.elf` 1422 KB |  |
| WarriorBlade | GBNJC0 | `BarbarianGCN.elf` 2700 KB |  |
| Cubix Showdown | GCAE5H | `CubixGameCube.elf` 2557 KB |  |
| UFC Throwdown | GUFE4Z | `GCNDefault.elf` 2408 KB |  |
| Finding Nemo | GNEE78 | `GCNemo.elf` 2355 KB |  |
| The Legend of Zelda: Collector's Edition | PZLE01 | `SIM.elf` 2270 KB, `SIM.elf` 2176 KB | `d_a_npc_people.map` 202 KB, `framework.map` 2000 KB |
| Buffy: Chaos Bleeds | GCQE7D | `Buffy.elf` 2261 KB |  |
| ZOIDS VS.3 | GZVJDA | `zoidR.elf` 2218 KB |  |
| Black & Bruised | G2BE5G | `GCNDefault.elf` 2192 KB |  |
| GEKITUISENKI | GZFJBP | `zc.elf` 2089 KB |  |
| WRECKLESS | GWQE52 | `wreckless.elf` 2084 KB |  |
| Zoids: Battle Legends | GZSE70 | `zoidR.elf` 2018 KB |  |
| Top Gun Combat Zones | GTGE60 | `GCNDefault.elf` 1924 KB |  |
| Crash Bandicoot:The Wrath of Cortex | GCBE7D | `crashwoc.elf` 1755 KB |  |
| Beyblade Super Tournament Battle | GBTE70 | `main.elf` 1752 KB |  |
| Doshin the Giant | GKDP01 | `DolphinDefault.elf` 1725 KB |  |
| ZOIDS VS. | GZOJDA | `zoidR.elf` 1687 KB |  |
| Hot Wheels Velocity X | GHWE78 | `HotWheels.elf` 1410 KB |  |
| takahashi mejin boukenjima | GTNJ18 | `huos.elf` 1394 KB | `huos.MAP` 852 KB |
| NINTENDO PUZZLE COLLECTION | GPZJ01 | `ponagb2m_client.elf` 1198 KB |  |
| Intellivision Lives! | GIVE4Z | `GCNDefault.elf` 1180 KB |  |
| Megaman Collection | G6QE08 | `Megaman.elf` 1058 KB |  |
| danceCRAZE | GR4EMZ | `GCDancer.elf` 746 KB |  |
| 007: Everything or Nothing | GENE69 | `boot.elf` 196 KB |  |
| NHL 2005 | GN5E69 | `nhlload.elf` 147 KB |  |
| NHL06 | GN6E69 | `nhlload.elf` 147 KB |  |
| ZELDA OCARINA MULTI PACK | D43E01 |  | `MultiBootSystem.map` 550 KB, `MultiBootSystemD.map` 880 KB |
| NHL2K3 | G2KE8P |  | `ann.sym` 438 KB, `bro.sym` 1417 KB, `pbp.sym` 839 KB |
| CuriousGeorge | G3JEAF |  | `0C3FB4742C41BD93.map` 4795 KB, `11F651E802B241EB.map` 5980 KB, `1724304818971F67.map` 3971 KB |
| AnimalCrossing | GAFE01 |  | `foresta.map` 4849 KB, `static.map` 552 KB |
| FINAL FANTASY Crystal Chronicles | GCCE01 |  | `game.MAP` 3342 KB |
| Hot Wheels World Race | GHRE78 |  | `HotwheelsFCDntsc.map` 781 KB |
| Legends of Wrestling 2 | GL2E51 |  | `legal.map` 262 KB, `title.map` 524 KB |
| Resident Evil 3 | GLEE08 |  | `map_j.map` 634 KB, `map_u.map` 634 KB |
| FlushedAway | GLHEG9 |  | `5619E900C3FD1AFF.map` 3709 KB, `C183AD4B3177DAC8.map` 535 KB, `FF85AA85DB3C7ED7.map` 11008 KB |
| Tom Clancy's Rainbow Six Lockdown | GLQE41 |  | `m01_sec_01.map` 2308 KB, `m01_sec_02.map` 1955 KB, `m02_sec_01_smg.map` 726 KB |
| Mario Kart Double Dash! | GM4E01 |  | `debugInfoS.MAP` 8122 KB |
| Pikmin | GPIE01 |  | `build.map` 7346 KB |
| P.N.03 | GPNE08 |  | `MEKA.sym` 345 KB |
| PIKMIN2 for GAMECUBE | GPVE01 |  | `pikmin2UP.MAP` 14858 KB |
| DoraTheExplorerJourneyToThePurplePlanet | GQLE9G |  | `1EC52DB72E1E973E.map` 8614 KB, `37F28CA4D341309F.map` 11476 KB, `468979CB0AD7A600.map` 4058 KB |
| SSX Tricky | GSTE69 |  | `alaska.map` 698 KB, `aloha.map` 828 KB, `elysium.map` 1250 KB |
| Ultimate Spider-Man | GUTE52 |  | `symbolgc-final.map` 2375 KB |
| WTA Tour Tennis | GWTEA4 |  | `env.sym` 353 KB |
| The Legend of Zelda Twilight Princess | GZ2E01 |  | `frameworkF.map` 2087 KB |
| THE LEGEND OF ZELDA The Wind Waker for USA | GZLE01 |  | `d_a_npc_md.map` 204 KB, `d_a_npc_people.map` 203 KB, `framework.map` 2007 KB |

141 discs.  Used so far: Bratz (Blitz actors), Muppets Party Cruise (BOLT), The Sims 2 (Edge of
Reality), Mortal Kombat: Deception (SEC), NFS Underground (`Speed.elf`, DWARF 1 + symtab), Super Mario Strikers (`MarioSoccerR.elf` + its map - the DOL matches none of the maps), Medal of Honor: Frontline (`Moh2RelGC.elf` symtab), Rising Sun and GoldenEye: Rogue Agent (`MOH3RDVD.ELF`, `GE2RDVD.ELF` - `TLT_GetRelocationTable`, `RenderMoh3_*` vertex formats), Ultimate Spider-Man (Treyarch NGL - its `symbolgc-final.map`
is a binary `SYM1` table: 16-byte records of address, name start, name end, size, then the
names), and the DOLs of Madden 06, Tiger Woods 2005, Frogger and Billy & Mandy (no symbols -
found by tag immediates and function shape).
