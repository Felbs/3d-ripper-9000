"""Wind Waker actor-name -> (Object archive, model path) placement table.

Derived from noclip.website's src/ZeldaWindWaker/LegacyActor.ts (MIT), which in turn
credits LordNed, Sage-of-Mirrors & LagoLunatic's Winditor ActorDatabase, plus a few
hand-added aliases. A model path of None means: use the biggest exported model in the
archive. Regenerate with tools/ww_actor_table.py."""

# ruff: noqa: E501

# fmt: off
WW_ACTORS: dict[str, list[tuple[str, str | None]]] = {
    'Pig': [('Kb', 'bdlm/pg.bdl')],
    'ATdoor': [('Atdoor', 'bdl/sdoor01.bdl')],
    'Ac1': [('Ac', 'bdlm/ac.bdl')],
    'Ah': [('Ah', 'bdlm/ah.bdl')],
    'Aj1': [('Aj', 'bdlm/aj.bdl')],
    'Ajav': [('Ajav', 'bdl/ajava.bdl'), ('Ajav', 'bdl/ajavb.bdl'), ('Ajav', 'bdl/ajavc.bdl'), ('Ajav', 'bdl/ajavd.bdl'), ('Ajav', 'bdl/ajave.bdl'), ('Ajav', 'bdl/ajavf.bdl')],
    'AjavW': [('AjavW', 'bdlm/ajavw.bdl')],
    'Ashut': [('Ashut', 'bdl/ashut.bdl')],
    'Auzu': [('Auzu', 'bdlm/auzu.bdl')],
    'Aygr': [('Aygr', 'bdl/aygr.bdl'), ('Aygr', 'bdl/aygrh.bdl')],
    'Ayush': [('Ayush', 'bdlm/ayush.bdl')],
    'BFlower': [('VbakH', 'bdlm/vbakh.bdl'), ('VbakH', 'bdlm/vbakm.bdl')],
    'Ba1': [('Ba', 'bdlm/ba.bdl')],
    'Bb': [('Bb', 'bdlm/bb.bdl')],
    'BigElf': [('bigelf', 'bdlm/dy.bdl')],
    'Bitem': [('Always', 'bdlm/vhutl.bdl')],
    'Bj1': [('Bj', 'bdlm/bj.bdl')],
    'Bj2': [('Bj', 'bdlm/bj.bdl')],
    'Bj3': [('Bj', 'bdlm/bj.bdl')],
    'Bj4': [('Bj', 'bdlm/bj.bdl')],
    'Bj5': [('Bj', 'bdlm/bj.bdl')],
    'Bj6': [('Bj', 'bdlm/bj.bdl')],
    'Bj7': [('Bj', 'bdlm/bj.bdl')],
    'Bj8': [('Bj', 'bdlm/bj.bdl')],
    'Bj9': [('Bj', 'bdlm/bj.bdl')],
    'Bk': [('Bk', 'bdlm/bk.bdl')],
    'Bkm': [('Bmd', 'bmdm/bkm.bmd'), ('Bmd', 'bmdm/bkm_coa.bmd')],
    'Blift': [('Hten1', 'bdl/hten1.bdl')],
    'Bm1': [('Bm', 'bdlm/bm.bdl')],
    'Bm2': [('Bm', 'bdlm/bm.bdl')],
    'Bm3': [('Bm', 'bdlm/bm.bdl')],
    'Bm4': [('Bm', 'bdlm/bm.bdl')],
    'Bm5': [('Bm', 'bdlm/bm.bdl')],
    'Bmcon1': [('Bmcon1', 'bdl/bm.bdl')],
    'Bmcon2': [('Bmcon1', 'bdl/bm.bdl')],
    'Bms1': [('Bms', 'bdl/by1.bdl')],
    'Bms2': [('Bms', 'bdl/by2.bdl')],
    'Bmsw': [('Bmsw', 'bdlm/bm.bdl')],
    'Branch': [('Kwood_00', 'bmdc/ws.bmd')],
    'Bs1': [('Bs', 'bdlm/bs.bdl')],
    'Bs2': [('Bs', 'bdlm/bs.bdl')],
    'Bst': [('Bst', 'bdlm/bst.bdl'), ('Bst', 'bdlm/lhand.bdl'), ('Bst', 'bdlm/rhand.bdl')],
    'Btd': [('Btd', 'bmdm/btd.bmd')],
    'Btsw2': [('Btsw', 'bdlm/bn.bdl')],
    'Bwd': [('Bwd', 'bdlm/bwd.bdl')],
    'Cafelmp': [('Cafelmp', 'bdl/ylamp.bdl')],
    'Canon': [('Bomber', 'bdl/vcank.bdl')],
    'Cb1': [('Cb', 'bdl/cb.bdl')],
    'Co1': [('Co', 'bdlm/co.bdl')],
    'DBLK0': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'DBLK1': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'DKkiba': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Daiocta': [('Daiocta', 'bdlm/do_main1.bdl')],
    'De1': [('De', 'bdl/de.bdl')],
    'Dk': [('Dk', 'bdl/dk.bdl')],
    'DmKmm': [('Demo_Kmm', 'bmd/ka.bmd')],
    'Doguu': [('Doguu', 'bdlm/vgsma.bdl')],
    'Ds1': [('Ds', 'bdlm/ck.bdl')],
    'Dsaku': [('Knsak_00', 'bdl/knsak_00.bdl')],
    'Eayogn': [('Eayogn', 'bdl/eayogn.bdl')],
    'Ebomzo': [('Ebomzo', 'bdl/ebomzo.bdl')],
    'Ebrock': [('Ebrock', 'bdl/ebrock.bdl')],
    'Ebrock2': [('Ebrock', 'bdl/ebrock2.bdl')],
    'Ecube': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Ekao': [('Ekao', 'bdl/ekao.bdl')],
    'Ekskz': [('Ekskz', 'bdl/ekskz.bdl'), ('Ekskz', 'bdlm/yocwd00.bdl')],
    'Esekh': [('Esekh', 'bdl/esekh.bdl')],
    'Esekh2': [('Esekh', 'bdl/esekh2.bdl')],
    'Eskban': [('Eskban', 'bdl/eskban.bdl')],
    'FTree': [('Vmr', 'bdlm/vmrty.bdl')],
    'Fdai': [('Fdai', 'bdl/fdai.bdl')],
    'Fganon': [('Fganon', 'bdlm/bpg.bdl')],
    'Figure': [('Figure', 'bdlm/vf_bs.bdl'), ('Figure0', '${base}.bdl'), ('Figure1', '${base}b.bdl'), ('Figure1', '${base}.bdl'), ('Figure2', 'bdlm/${baseFilename}.bdl'), ('Figure2', '${base}.bdl')],
    'Fkeeth': [('Ki', 'bdlm/fk.bdl')],
    'Fmastr1': [('fm', 'bdl/fm.bdl'), ('fm', 'bdlm/ypit00.bdl')],
    'Fmastr2': [('fm', 'bdl/fm.bdl'), ('fm', 'bdlm/ypit00.bdl')],
    'Gaship1': [('GaShip', 'bdl/gaship.bdl')],
    'Gaship2': [('YakeRom', 'bdl/yakerom.bdl')],
    'Gbrg00': [('Gbrg00', 'bdlm/gbrg00.bdl')],
    'Ghrwp': [('Ghrwp', 'bdlm/ghrwpa00.bdl'), ('Ghrwp', 'bdlm/ghrwpb00.bdl')],
    'GiceL': [('GiceL', 'bdli/gicel00.bdl')],
    'Gk1': [('Gk', 'bdlm/gk.bdl')],
    'Gkai00': [('Gkai00', 'bdlm/gkai00.bdl')],
    'Gp1': [('Gp', 'bdlm/gp.bdl')],
    'Gryw00': [('Gryw00', 'bdlm/gryw00.bdl')],
    'Hbox1': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Hbox2': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Hbox2S': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Hcbh': [('Hcbh', 'bdl/hcbh1a.bdl'), ('Hcbh', 'bdl/hcbh1b.bdl'), ('Hcbh', 'bdl/hcbh1c.bdl'), ('Hcbh', 'bdl/hcbh1d.bdl'), ('Hcbh', 'bdl/hcbh2.bdl')],
    'Hdai1': [('Hdai1', 'bdlm/hdai1.bdl')],
    'Hdai2': [('Hdai1', 'bdlm/hdai1.bdl')],
    'Hdai3': [('Hdai1', 'bdlm/hdai1.bdl')],
    'Hfbot1B': [('Hfbot', 'bdlm/hfbot1.bdl')],
    'Hfbot1C': [('Hfbot', 'bdlm/hfbot1.bdl')],
    'Hfuck1': [('Hfuck1', 'bdl/hfuck1.bdl')],
    'Hha': [('Hha', 'bdlm/hha1.bdl'), ('Hha', 'bdlm/hha2.bdl')],
    'Hhbot1': [('Hhbot', 'bdl/hhbot1.bdl'), ('Hhbot', 'bdl/hhbot2.bdl')],
    'Hhbot1N': [('Hhbot', 'bdl/hhbot1.bdl'), ('Hhbot', 'bdl/hhbot2.bdl')],
    'Hi1': [('Hi', 'bdlm/hi.bdl')],
    'Hjump1': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Hlift': [('Hlift', 'bdl/hlift.bdl')],
    'Hliftb': [('Hlift', 'bdl/hliftb.bdl')],
    'Hmlif': [('Hmlif', 'bdlm/hmlif.bdl')],
    'Hmon1d': [('Hseki', 'bdlm/hmon1.bdl')],
    'Hmon2d': [('Hseki', 'bdlm/hmon2.bdl')],
    'Hmos1': [('Hmos', 'bdl/hmos1.bdl')],
    'Hmos2': [('Hmos', 'bdl/hmos2.bdl')],
    'Hmos3': [('Hmos', 'bdl/hmos3.bdl')],
    'Ho': [('Ho', 'bdlm/ho.bdl')],
    'Hr': [('Hr', 'bdlm/hr.bdl')],
    'Hr2': [('Hr', 'bdlm/hr.bdl')],
    'Hseki2': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Hseki7': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Hsh': [('Hsehi1', 'bdl/hsehi1.bdl')],
    'Hsh2': [('Hsehi2', 'bdl/hsehi2.bdl')],
    'Htetu1': [('Htetu1', 'bdl/htetu1.bdl')],
    'Htobi1': [('Htobi1', 'bdl/htobi1.bdl')],
    'Htoge1': [('Htoge1', 'bdl/htoge1.bdl')],
    'Humi0z': [('Humi', 'bdlm/humi0.bdl')],
    'Humi2z': [('Humi', 'bdlm/humi2.bdl')],
    'Humi3z': [('Humi', 'bdlm/humi3.bdl')],
    'Humi4z': [('Humi', 'bdlm/humi4.bdl')],
    'Humi5z': [('Humi', 'bdlm/humi5.bdl')],
    'HyoiKam': [('Vhyoi', 'bdl/vhyoi.bdl')],
    'Hys': [('Hys', 'bdlm/hys.bdl')],
    'Hys2': [('Hys', 'bdlm/hys.bdl')],
    'Hyuf1': [('Hyuf1', 'bdlm/hyuf1.bdl')],
    'Hyuf2': [('Hyuf2', 'bdlm/hyuf2.bdl')],
    'Ikada': [('IkadaH', 'bdl/vikae.bdl')],
    'Ikari': [('Ikari', 'bdl/s_ikari2.bdl')],
    'Jb1': [('Jb', 'bdlm/jb.bdl')],
    'Ji1': [('Ji', 'bdlm/ji.bdl')],
    'Kamome': [('Kamome', 'bdl/ka.bdl')],
    'Kanat': [('Kanat', 'bdl/kanat.bdl')],
    'Kanban': [('Kanban', 'bdl/kanban.bdl')],
    'KbotaC': [('Kbota_00', 'bdl/kbota_00.bdl')],
    'Kbota_A': [('Kbota_00', 'bdl/kbota_00.bdl')],
    'Kbota_B': [('Kbota_00', 'bdl/kbota_00.bdl')],
    'Kf1': [('Kf', 'bdlm/kf.bdl')],
    'Kg1': [('Kg', 'bdlm/kg.bdl')],
    'Kg2': [('Kg', 'bdlm/kg.bdl')],
    'Kita': [('kita', 'bdl/vhlif_00.bdl')],
    'Kk1': [('Kk', 'bdlm/kk.bdl')],
    'Kkiba': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'KkibaB': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Klft': [('Klft', 'bdlm/lift_00.bdl')],
    'Kmi00': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Kmi02': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Kmtub': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Ko1': [('Ko', 'bdlm/ko.bdl')],
    'Ko2': [('Ko', 'bdlm/ko.bdl')],
    'Kokiie': [('Kokiie', 'bdl/koki_00.bdl')],
    'Kp1': [('Kp', 'bdlm/kp.bdl')],
    'Kryu00': [('Kryu', 'bdl/ryu_00.bdl')],
    'Ksaku': [('Ksaku_00', 'bdl/ksaku_00.bdl')],
    'Ktaru': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Ktaruo': [('Ktaru_01', 'bdl/ktaru_01.bdl')],
    'Ktarur': [('Ktaru_00', 'bdlm/ktaru_00.bdl')],
    'Ktarux': [('Ktaru_01', 'bdl/ktaru_01.bdl')],
    'Kui': [('Kui', 'bdl/obi_ropetag.bdl')],
    'Lamp': [('Lamp', 'bmd/lamp_00.bmd')],
    'Ls': [('Ls', 'bdlm/ls.bdl')],
    'Ls1': [('Ls', 'bdlm/ls.bdl')],
    'MKanok2': [('Mkanoke', None)],
    'MKoppu': [('Mshokki', 'bdl/koppu.bdl')],
    'MOsara': [('Mshokki', 'bdl/osara.bdl')],
    'MPot': [('Mshokki', 'bdl/pot.bdl')],
    'Md1': [('Md', 'bdlm/md.bdl')],
    'Mflft': [('Mflft', 'bdl/mflft.bdl')],
    'MhmrSW0': [('MhmrSW', 'bdl/mhmrsw.bdl')],
    'Mhsg15': [('Mhsg', 'bdl/mhsg15.bdl')],
    'Mhsg4h': [('Mhsg', 'bdl/mhsg4h.bdl')],
    'Mhsg9': [('Mhsg', 'bdl/mhsg9.bdl')],
    'MjDoor': [('S_MSPDo', 'bdl/s_mspdo.bdl')],
    'Mk': [('Mk', 'bdlm/mk.bdl')],
    'MkieBB': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Mmrr': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'Mn': [('Mn', 'bdlm/mn.bdl')],
    'MpwrB': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'MsuSWB': [('Mmirror', 'bdlm/msusw.bdl')],
    'Mswing': [('Msw', 'bdl/mswng.bdl')],
    'Mt': [('Niten', 'bdlm/mt.bdl')],
    'MtoriSU': [('MtoriSU', 'bdl/mtorisu.bdl')],
    'MtryB': [('MtryB', 'bdl/mtryb.bdl')],
    'NpcSo': [('So', 'bdlm/so.bdl')],
    'Nzfall': [('Pfall', 'bdl/nz.bdl')],
    'Ob1': [('Ob', 'bdl/ob.bdl')],
    'Ocanon': [('WallBom', 'bdl/wallbom.bdl')],
    'Ockun': [('Vdoku', None)],
    'Ocloud': [('BVkumo', 'bdlm/bvkumo.bdl')],
    'Odokuro': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Ohatch': [('Ohatch', 'bdl/ohatch.bdl')],
    'Ojtree': [('Ojtree', 'bdl/ojtree.bdl')],
    'Okioke': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Olift': [('Olift', 'bdl/olift.bdl')],
    'Oq': [('Oq', 'bmdm/oq.bmd')],
    'Oqw': [('Oq', 'bmdm/red_oq.bmd')],
    'Oship': [('Oship', 'bdl/vbtsp.bdl')],
    'Ospbox': [('Ospbox', 'bdl/ospbox.bdl')],
    'Ostool': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Otana': [('Otana', 'bdl/otana.bdl')],
    'Otble': [('Okmono', 'bdl/otable.bdl')],
    'OtbleL': [('Okmono', 'bdl/otablel.bdl')],
    'Oyashi': [('Oyashi', 'bdl/oyashi.bdl')],
    'P1a': [('P1', 'bdl/p1.bdl')],
    'P1b': [('P1', 'bdl/p1.bdl')],
    'P1c': [('P1', 'bdl/p1.bdl')],
    'P2a': [('P2', 'bdl/p2.bdl')],
    'P2b': [('P2', 'bdl/p2.bdl')],
    'P2c': [('P2', 'bdl/p2.bdl')],
    'Paper': [('Opaper', 'bdl/opaper.bdl')],
    'Pbka': [('Pbka', 'bdl/pbka.bdl')],
    'Pf1': [('Pf', 'bdlm/pf.bdl')],
    'Pirates': [('Kaizokusen', 'bdl/oba_kaizoku_a.bdl')],
    'Pitfall': [('Aana', 'bdl/aana.bdl')],
    'Piwa': [('Piwa', 'bdl/piwa.bdl')],
    'Plant': [('Plant', 'bdl/yrmwd.bdl')],
    'Po': [('Po', 'bdlm/po.bdl')],
    'Ppos': [('Ppos', 'bdl/ppos.bdl')],
    'Ptco': [('Ptc', 'bdl/ptco.bdl')],
    'Ptcu': [('Ptc', 'bdl/ptcu.bdl')],
    'Ptubo': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'Puti': [('Pt', 'bdlm/pt.bdl')],
    'Qdghd': [('Qdghd', 'bdl/qdghd.bdl')],
    'Qtkhd': [('Qtkhd', 'bdl/qtkhd.bdl')],
    'Rcloud': [('BVkumo', 'bdlm/bvkumo.bdl')],
    'Rdead1': [('Rd', 'bdlm/rd.bdl')],
    'Rdead2': [('Rd', 'bdlm/rd.bdl')],
    'Rflw': [('Rflw', 'bdl/phana.bdl')],
    'RopeR': [('Vrope', 'bdl/vrope.bdl')],
    'Roten2': [('Roten', 'bdl/roten02.bdl')],
    'Roten3': [('Roten', 'bdl/roten03.bdl')],
    'Roten4': [('Roten', 'bdl/roten04.bdl')],
    'RotenA': [('Ro', 'bdlm/ro.bdl')],
    'RotenB': [('Ro', 'bdlm/ro.bdl')],
    'RotenC': [('Ro', 'bdlm/ro.bdl')],
    'Rsh1': [('Rsh', 'bdlm/rs.bdl')],
    'SMBdor': [('Mbdoor', 'bdl/s_mbdfu.bdl'), ('Mbdoor', 'bdl/s_mbd_l.bdl'), ('Mbdoor', 'bdl/s_mbd_r.bdl'), ('Mbdoor', 'bdl/s_mbdto.bdl')],
    'SMtoge': [('Mtoge', 'bmd/s_mtoge.bmd')],
    'SPitem': [('VshiN', 'bdl/vshin.bdl'), ('Vbelt', 'bdl/vbelt.bdl')],
    'Sa1': [('Sa', 'bdl/sa.bdl')],
    'Sa2': [('Sa', 'bdl/sa.bdl')],
    'Sa3': [('Sa', 'bdl/sa.bdl')],
    'Sa4': [('Sa', 'bdl/sa.bdl')],
    'Sa5': [('Sa', 'bdl/sa.bdl')],
    'Sarace': [('Sarace', 'bdl/sa.bdl')],
    'Search': [('Search', 'bdl/s_search.bdl')],
    'Sfairy': [('Always', 'bdl/fa.bdl')],
    'Shmrgrd': [('Shmrgrd', 'bdl/shmrgrd.bdl')],
    'Skanran': [('Skanran', 'bdl/skanran.bdl')],
    'Ss': [('Ss', 'bdl/sw.bdl')],
    'Sss': [('Sss', 'bmd/sss_hand.bmd')],
    'Stal': [('St', 'bdlm/st.bdl')],
    'Stoudai': [('Skanran', 'bdl/stoudai.bdl')],
    'Svsp': [('IkadaH', 'bdl/vsvsp.bdl')],
    'Table': [('Table', 'bdl/ytble.bdl'), ('Table', 'bdl/qcfis.bdl')],
    'Tn': [('Tn', 'bmdm/tn_main.bmd')],
    'Tpost': [('Toripost', 'bdl/vpost.bdl')],
    'TrFlag': [('Trflag', 'bdl/ethata.bdl')],
    'Trap': [('Trap', 'bdlm/htora1.bdl')],
    'Tt': [('Tt', 'bdlm/tt.bdl')],
    'Turu': [('Sk', 'bdl/turu_00.bdl')],
    'Turu2': [('Sk2', 'bdlm/ksylf_00.bdl')],
    'Turu3': [('Sk2', 'bdlm/ksylf_01.bdl')],
    'Ub1': [('Ub', 'bdl/ub.bdl')],
    'Ub2': [('Ub', 'bdl/ub.bdl')],
    'Ub3': [('Ub', 'bdl/ub.bdl')],
    'Ub4': [('Ub', 'bdl/ub.bdl')],
    'Ug1': [('Ug', 'bdl/ug.bdl')],
    'Ug2': [('Ug', 'bdl/ug.bdl')],
    'UkB': [('Uk', 'bdlm/uk.bdl')],
    'UkC': [('Uk', 'bdlm/uk.bdl')],
    'UkD': [('Uk', 'bdlm/uk.bdl')],
    'Um1': [('Um', 'bdl/um.bdl')],
    'Um2': [('Um', 'bdl/um.bdl')],
    'Um3': [('Um', 'bdl/um.bdl')],
    'Uo1': [('Uo', 'bdl/uo.bdl')],
    'Uo2': [('Uo', 'bdl/uo.bdl')],
    'Uo3': [('Uo', 'bdl/uo.bdl')],
    'Uw1': [('Uw', 'bdl/uw.bdl')],
    'Uw2': [('Uw', 'bdl/uw.bdl')],
    'VbakH': [('VbakH', 'bdlm/vbakh.bdl'), ('VbakH', 'bdlm/vbakm.bdl')],
    'Vdora': [('Vdora', 'bdl/vdora.bdl')],
    'Vds': [('Vds', 'bdlm/vdswt0.bdl'), ('Vds', 'bdlm/vdswt1.bdl')],
    'VigaH': [('VigaH', 'bdl/vigah.bdl')],
    'VmsDZ': [('VmsDZ', 'bdl/vmsdz.bdl')],
    'VmsMS': [('VmsMS', 'bdl/vmsms.bdl')],
    'Vochi': [('Vochi', 'bdl/vochi.bdl')],
    'Vpbot': [('Vpbot_00', 'bdl/vpbot_00.bdl')],
    'Vtil1': [('Vtil', 'bdl/vtil1.bdl')],
    'Vtil2': [('Vtil', 'bdl/vtil2.bdl')],
    'Vtil3': [('Vtil', 'bdl/vtil3.bdl')],
    'Vtil4': [('Vtil', 'bdl/vtil4.bdl')],
    'Vtil5': [('Vtil', 'bdl/vtil5.bdl')],
    'Vyasi': [('Vyasi', 'bdl/vyasi.bdl')],
    'Wall': [('Hbw1', 'bdl/hbw1.bdl')],
    'Warpgm': [('Gmjwp', 'bdlm/gmjwp00.bdl')],
    'Warpmj': [('Gmjwp', 'bdlm/gmjwp00.bdl')],
    'Warpnt': [('ltubw', 'bdl/itubw.bdl')],
    'Warpt': [('ltubw', 'bdl/itubw.bdl')],
    'Warpts1': [('ltubw', 'bdl/itubw.bdl')],
    'Warpts2': [('ltubw', 'bdl/itubw.bdl')],
    'Warpts3': [('ltubw', 'bdl/itubw.bdl')],
    'X_tower': [('X_tower', 'bdl/x_tower.bdl')],
    'YLzou': [('YLzou', 'bdl/ylzou.bdl')],
    'Yboil00': [('Yboil', 'bdlm/yboil00.bdl')],
    'Yfire00': [('Yfire_00', 'bmdm/yfire_00.bmd'), ('Yfire_00', 'bmdm/yfirb_00.bmd')],
    'Yfrct00': [('frLt', None)],
    'Ykzyg': [('Ykzyg', 'bdlm/qkzyg.bdl')],
    'Yllic': [('Yllic', 'bdl/yllic.bdl')],
    'Ylsic': [('Ylsic', 'bdl/ylsic.bdl')],
    'Ym1': [('Ym', 'bdlm/ym.bdl')],
    'Ym2': [('Ym', 'bdlm/ym.bdl')],
    'Yswdr00': [('Yswdr00', 'bdlm/yswdr00.bdl')],
    'Ytrnd00': [('Trnd', 'bdlm/ytrnd00.bdl'), ('Trnd', 'bdlm/ywuwt00.bdl')],
    'Yw1': [('Yw', 'bdl/yw.bdl')],
    'Ywarp00': [('Ywarp00', 'bmdm/ywarp00.bmd')],
    'Zk1': [('Zk', 'bdlm/zk.bdl')],
    'amos': [('Am', 'bdl/am.bdl')],
    'amos2': [('Am2', 'bdlm/am2.bdl')],
    'bable': [('Bl', 'bdlm/bl.bdl')],
    'bbaba': [('Bo', 'bdlm/bo_sita1.bdl')],
    'big_pow': [('Bpw', 'bdlm/bpw.bdl')],
    'c_black': [('Cc', 'bmdm/cc.bmd')],
    'c_blue': [('Cc', 'bmdm/cc.bmd')],
    'c_green': [('Cc', 'bmdm/cc.bmd')],
    'c_kiiro': [('Cc', 'bmdm/cc.bmd')],
    'c_red': [('Cc', 'bmdm/cc.bmd')],
    'dmgroom': [('dmgroom', 'bdlm/dmgroom.bdl')],
    'dragon': [('Dr', 'bmd/dr1.bmd')],
    'gmos': [('Gm', 'bdlm/gm.bdl')],
    'ikada': [('IkadaH', None)],
    'ikadaS': [('IkadaH', 'bdl/vikah.bdl')],
    'ikada_h': [('IkadaH', 'bdl/vtsp.bdl')],
    'ikada_u': [('IkadaH', 'bdl/vtsp2.bdl')],
    'item': [('Always', 'bdl/vhrtl.bdl'), ('Always', 'bdlm/vlupl.bdl'), ('Always', 'bdlm/mpoda.bdl'), ('Always', 'bdlm/mpodb.bdl'), ('Always', 'bdl/vkeyl.bdl'), ('Always', 'bdl/vhapl.bdl')],
    'itemDek': [('Deku', 'bdlm/vlfdm.bdl')],
    'jbaba': [('Jbo', 'bmdm/jh.bmd')],
    'kani': [('Kn', 'bdl/kn.bdl')],
    'keeth': [('Ki', 'bdlm/ki.bdl')],
    'koisi1': [('Always', 'bdl/obm_koisi1.bdl')],
    'kotubo': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'lwood': [('Lwood', 'bdl/alwd.bdl')],
    'magtail': [('Mt', 'bdlm/mg_head.bdl')],
    'mo2': [('Mo2', 'bdlm/mo.bdl')],
    'moZOU': [('Mozo', 'bdlm/moz.bdl')],
    'nezuana': [('Nzg', 'bdl/kana_00.bdl')],
    'nezumi': [('Nz', 'bdlm/nz.bdl')],
    'ootubo1': [('Always', 'bdl/obm_kotubo1.bdl'), ('Always', 'bdl/obm_ootubo1.bdl'), ('Kmtub_00', 'bdl/kmtub_00.bdl'), ('Ktaru_01', 'bdl/ktaru_01.bdl'), ('Okmono', 'bdl/ostool.bdl'), ('Odokuro', 'bdl/odokuro.bdl')],
    'osiBLK': [('Osiblk', None)],
    'osiBLK0': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'osiBLK1': [('Kkiba_00', 'bdl/kkiba_00.bdl'), ('Osiblk', 'bdl/obm_osihikiblk1.bdl'), ('Osiblk', 'bdl/obm_osihikiblk2.bdl'), ('MpwrB', 'bdl/mpwrb.bdl'), ('Hbox2', 'bdl/hbox2.bdl'), ('Hjump', 'bdl/hbox1.bdl')],
    'p_hat': [('Sh', 'bmdm/shb.bmd'), ('Sh', 'bmdm/shp.bmd'), ('Ph', 'bdlm/phb.bdl'), ('Ph', 'bdlm/php.bdl')],
    'p_zelda': [('Pz', 'bdlm/pz.bdl')],
    'pow': [('Pw', 'bdlm/pw.bdl')],
    's_turu': [('Ssk', 'bdl/turu_02.bdl')],
    'wiz_r': [('Wz', 'bdlm/wz.bdl')],
    'zouK': [('VzouK', 'bdl/vzouk.bdl')],
    'zouK1': [('VzouK', 'bdl/vzouk.bdl')],
    'zouK2': [('VzouK', 'bdl/vzouk.bdl')],
    'zouK3': [('VzouK', 'bdl/vzouk.bdl')],
    'zouK4': [('VzouK', 'bdl/vzouk.bdl')],

    # --- resolved from d_stage.cpp's OBJNAME table (name -> fpcNm_* profile), then
    # --- c_dylink.cpp (profile -> d_a_*.cpp) -> the archive that actor loads.
    # Obj_Mtest: char* Act_c::M_arcname[Type_Max] (d_a_obj_mtest.cpp:14-23); the
    # OBJNAME sub-type picks cube vs cylinder (d_stage.cpp:895-902).
    'Mcube': [('Mtest', 'bmdc/mcube.bmd')],
    'Mcube10': [('Mtest', 'bmdc/mcube.bmd')],
    'MygnSB': [('Mtest', 'bmdc/mcube.bmd')],
    'Mcyln': [('Mtest', 'bmdc/mcyln.bmd')],
    'Mcyln10': [('Mtest', 'bmdc/mcyln.bmd')],
    'VmcBS': [('Vmc', 'bdl/vmcbs.bdl')],           # d_a_obj_vmc.cpp -> res/Object/Vmc.h
    'SieFlag': [('Eshata', 'bdl/eshata.bdl')],     # d_a_sie_flag.cpp:61 M_arcname (pole;
                                                   # the banner itself is Cloth, tex only)
    'Mori1': [('Mdoor', 'bdl/mori1.bdl')],         # fpcNm_MDOOR_e, d_stage.cpp:459
    'MkieBA': [('MkieB', 'bdl/mkieb.bdl')],        # d_a_obj_mkie.cpp:11 M_arcname
    'MkieBAB': [('MkieB', 'bdl/mkieb.bdl')],
    'SWtact': [('Itact', 'bdl/itact.bdl')],        # d_a_swtact.cpp -> res/Object/Itact.h
    'SWtactB': [('Itact', 'bdl/itact.bdl')],
    'keyS12': [('door12', None)],                  # fpcNm_DOOR12_e, d_stage.cpp:479-480
    'ZenS12': [('door12', None)],
    'doorKD': [('DoorBs', 'bdl/doorkd.bdl')],      # fpcNm_KDDOOR_e, d_stage.cpp:460-464
    'doorSH': [('DoorBs', 'bdl/doorkd.bdl')],
    'Fmaster': [('fm', 'bdl/fm.bdl')],             # fpcNm_FM_e, d_stage.cpp:801
    'Warpf': [('Ysbwp00', 'bdlm/ysbwp00.bdl'), ('Gtfglow', 'bdlm/gtfglow00.bdl')],
    'Warpgn': [('Gmjwp', 'bdlm/gmjwp00.bdl')],     # d_a_warpgn.cpp -> res/Object/Gmjwp.h
    'Gnbtaki': [('Gnnbtltaki', 'bdlm/gnn_btl_taki.bdl')],
    'Gntakis': [('Gnndemotakis', 'bdlm/gnn_demo_taki_s.bdl')],
    'Gntakie': [('Gnndemotakie', 'bdlm/gnn_demo_taki_e.bdl')],
    'Yfrlt00': [('frLt', 'bdlm/yfrlt00.bdl')],     # fpcNm_Komore_e (light shaft)
    'Ygush01': [('Ygush00', 'bdlm/ygush00.bdl')],  # fpcNm_Obj_Ygush00_e, d_stage.cpp:1163
    'Ygush02': [('Ygush00', 'bdlm/ygush00.bdl')],
    'Xfuta': [('X_futa', 'bdl/x_futa.bdl')],
    'MtryBCr': [('MtryB', 'bdl/mtryb.bdl')],       # fpcNm_Obj_Tribox_e sub 1 (sub 0 = MtryB)
    'Nh': [('Always', 'bdlm/nh.bdl')],             # d_a_nh.cpp:113 getObjectRes("Always", NH)
    'Rforce': [('StpTetu', 'bdl/stptetu.bdl')],    # d_a_obj_rforce.cpp:21
    'Hfbot1A': [('Hfbot', 'bdlm/hfbot1.bdl')],     # Obj_Swflat sub 0; 1/2 = Hfbot1B/C
    'Hsen2': [('Hsen1', 'bdlm/hsen1.bdl')],        # d_a_fan.cpp:17 m_arcname[3]
    'MsuSW': [('Mmirror', 'bdlm/msusw.bdl')],      # d_a_obj_swlight.cpp -> res/Object/Mmirror.h
    'Hmon1': [('Hseki', 'bdlm/hmon1.bdl')],        # fpcNm_Obj_Try_e; cf. Hmon1d/Hmon2d
    'Hmon2': [('Hseki', 'bdlm/hmon2.bdl')],
    'Tide3': [('Gmtw', 'bdlm/gmtw00.bdl'), ('Humi', None)],  # d_a_obj_tide.cpp:19-20
    'MegamiD': [('Doguu', 'bdlm/vgshd.bdl')],      # Obj_Doguu subs 1/2/3, d_stage.cpp:968-970
    'MegamiF': [('Doguu', 'bdlm/vgshf.bdl')],
    'MegamiN': [('Doguu', 'bdlm/vgshn.bdl')],
    'KGBdor': [('Gbdoor', 'bdl/v_gbdfu.bdl')],     # d_a_mbdoor.cpp:47-49 (sub 1 -> Gbdoor)
    'Ypit00': [('Aana', 'bdl/aana.bdl')],          # d_a_obj_hole.cpp:21 m_arc_name
    'HamiY': [('Hami1', 'bdl/hami1.bdl')],         # d_a_amiprop.cpp -> res/Object/Hami1.h
    'Auction': [('Pspl', 'bdl/pspl.bdl')],         # d_a_auction.cpp resLoad("Pspl")
    'Throck': [('Aisi', 'bdlm/aisi.bdl')],         # d_throwstone.cpp:15,25 M_arcname
    'GBoard': [('Kaisen', 'bdl/akbod.bdl')],       # d_a_mgameboard.h -> d_seafightgame.h
    'DmKmm2': [('Demo_Kmm', 'bmd/ka.bmd')],        # fpcNm_DEMO_KMM_e sub 1 (sub 0 = DmKmm)
}
# fmt: on

# Actors drawn from display lists embedded in the game executable (d_flower.o /
# d_wood.o / d_grass.o symbol data) or pure effects - no archive model exists.
CODE_DRAWN_PREFIXES = (
    "kusa", "flwr", "pflwr", "flower", "pflower", "swood", "woodb",
    "bonbori", "zenfire", "zenshut", "salvag", "salvfm", "swslvg", "pitfall",
    "fire", "magma", "akabe", "kuro_", "ykgr", "ygstp", "mwtrsb", "mtflag", "quake",
    # LOD01..LOD49: the ocean's distant-island stand-ins.  d_a_lod_bg.cpp:160 streams
    # "/lod%02d/bdl/model.bdl" out of res/Stage/sea/LODALL.arc at run time, keyed on the
    # placement's param - not an Object archive, and the real island rooms are placed
    # anyway, so these would only double up on the geometry we already have.
    "lod",
)

# Invisible logic actors: triggers, switches, tags, Tingle Tuner (agb) hooks, cameras.
NO_MODEL_PREFIXES = (
    "tag", "atttag", "agb", "and_sw", "sw_", "ky_tag", "kytag", "ltag",
    "windtag", "alldie", "com_", "attag", "evt", "evsw", "gyctrl", "ky00you",
    "camera", "arrow", "ajav",
)

# Names placed on the disc that d_stage.cpp's OBJNAME table (l_objectName) does not
# list at all.  dStage_searchName() returns NULL and dStage_actorCreate() frees the
# request without spawning anything (d_stage.cpp:1266-1307), so the retail game simply
# ignores them: editor leftovers and test junk.  Krock00 is the old name for the
# falling rock that ships as "frock" (d_a_fallrock.cpp:56 loads Always/krock_00).
DEAD_NAMES = (
    "Krock00", "Stgate", "Sttoge", "Stdoorl", "Stdoorr", "TestPo", "speakun",
)

# Model-less actors matched by exact name rather than prefix.  Each was traced from
# d_stage.cpp's OBJNAME entry through c_dylink.cpp to its d_a_*.cpp: no J3DModel, and
# where an archive is loaded at all it holds only collision or a texture.
NO_MODEL_NAMES = frozenset(
    (
        "ITat00",                            # fpcNm_SW_ITEM_e - "item taken" switch
        "Ystm0", "Ystm1",                    # fpcNm_SteamTag_e - steam vent triggers
        "NBOX", "NBOX10",                    # fpcNm_Obj_Akabe_e - NBOX.arc is one .dzb
        "CmTrap", "TnTrap", "FgTrap",        # fpcNm_Obj_TnTrap_e - TnTrap.arc is one .dzb
        "Owater", "Astop",                   # fpcNm_Obj_Mtest_e 6/7 - .dzb-only archives
        "ReTag0",                            # fpcNm_Tag_Ret_e
        "PScnChg",                           # fpcNm_TAG_GSHIP_e - ghost-ship scene change
        "ObjTime",                           # fpcNm_Obj_Timer_e
        "Warpfo",                            # fpcNm_WARPFOUT_e - warp-out trigger
        "VolTag",                            # fpcNm_Tag_Volcano_e
        "WLvTag",                            # fpcNm_Tag_Waterlevel_e
        "SWat00",                            # fpcNm_SW_ATTACK_e
        "frock",                             # fpcNm_TagRock_e - spawns falling rocks
        "BLK_CR", "CrTrS3", "CrTrS4", "CrTrS5", "CrTrM1", "CrTrM2",  # fpcNm_Obj_Correct_e
        "Mmusic",                            # fpcNm_Mmusic_e - music region
        "spotbx1",                           # fpcNm_SPOTBOX_e
        "Tpota",                             # fpcNm_Tpota_e
    )
    + DEAD_NAMES
)

# Placed, but never drawn from an archive this ripper can reach.  The flags are cloth
# simulated in code over a single .bti (Cloth/Matif/Vsvfg/Xhcf/Gflag hold no model at
# all), and "sea" is the procedural ocean mesh d_a_sea.cpp builds from Always textures.
CODE_DRAWN_NAMES = frozenset(
    (
        "MjFlag", "HcFlag",                  # fpcNm_MAJUU_FLAG_e, d_a_majuu_flag.cpp:818-833
        "Gflag",                             # fpcNm_Goal_Flag_e, d_a_goal_flag.cpp:30-33
        "sea",                               # fpcNm_SEA_e, d_a_sea.cpp:195-215
    )
)

# Actors whose model ships in the stage's own Stage.arc under a different name than the
# placement uses.  "keyshut" is a fpcNm_DOOR10_e locked door (d_stage.cpp:456) and every
# dungeon Stage.arc carries it as stage/bdl/key10.bdl next to door10/door20/stop10.
STAGE_LOCAL_MODELS = {
    "keyshut": "key10",
}

# Treasure chests: model chosen from Object/Dalways.arc by (params >> 20) & 0xF.
CHEST_PREFIXES = ("takara", "tkr")
CHEST_MODELS = {
    0: ("Dalways", "bdli/boxa.bdl"),   # light wood
    1: ("Dalways", "bdli/boxb.bdl"),   # dark wood
    2: ("Dalways", "bdli/boxc.bdl"),   # metal
    3: ("Dalways", "bdlm/boxd.bdl"),   # big key
}

# Generic locked/plain doors ("KNOB..") share the Knob archive.
KNOB_PAIR = ("Knob", "bdl/door.bdl")
