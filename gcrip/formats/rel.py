"""Nintendo GameCube ``.rel`` relocatable modules: enough of the OSModule format to turn a
module into a flat image whose pointer fields hold ``base + file offset`` (the same fix-up
SA Tools' ``FixRELPointers`` applies), so structures inside can be read with absolute
addresses relative to a known load base.

Header (big-endian): ``u32 id | u32 next | u32 prev | u32 sections | u32 section table |
u32 name | u32 name size | u32 version | u32 bss size | u32 rel table | u32 imp table |
u32 imp size | u8 prolog/epilog/unresolved sections ...``.  Section table entries ``u32
offset (bit 0 = executable) | u32 size``; imp entries ``u32 module id | u32 rel offset``;
relocations ``u16 offset | u8 type | u8 section | u32 addend`` run per imported module,
where type 201 (R_DOLPHIN_NOP), 202 (R_DOLPHIN_SECTION: switch to a section) and 203
(R_DOLPHIN_END) drive the walk and offsets accumulate.
"""

from __future__ import annotations

import struct

R_END, R_SECTION, R_NOP = 203, 202, 201


def is_rel(head: bytes, size: int | None = None) -> bool:
    if len(head) < 0x40:
        return False
    mid, nxt, prv, nsec, sec_off, _n, _ns, ver = struct.unpack_from(">8I", head, 0)
    if nxt or prv or not (0 < nsec < 64) or ver > 3 or mid == 0 or mid > 0xFFFF:
        return False
    return size is None or sec_off + nsec * 8 <= size


def fix_pointers(data: bytes, base: int) -> bytearray:
    """Copy of the module with every 32-bit relocation resolved against ``base`` (the
    module's load address, e.g. 0xC900000 for Sonic Adventure DX / 2 Battle)."""
    d = bytearray(data)
    mid, _nxt, _prv, nsec, sec_off, _n, _ns, _ver, _bss, _rel, imp_off, imp_size = (
        struct.unpack_from(">12I", d, 0)
    )
    sections = [struct.unpack_from(">2I", d, sec_off + i * 8) for i in range(nsec)]
    imports = [struct.unpack_from(">2I", d, imp_off + i * 8) for i in range(imp_size // 8)]
    rel_off = next((off for i, off in imports if i == mid), None)
    if rel_off is None:
        return d
    p = rel_off
    addr = 0
    while p + 8 <= len(d):
        off, typ, sec, addend = struct.unpack_from(">HBBI", d, p)
        p += 8
        if typ == R_END:
            break
        addr += off
        if typ == R_SECTION:
            addr = sections[sec][0] & ~1 if sec < len(sections) else 0
            continue
        if typ in (0, R_NOP):
            continue
        target = (sections[sec][0] & ~1) + addend if sec < len(sections) else addend
        if addr + 4 > len(d):
            continue
        if typ == 1:  # R_PPC_ADDR32
            struct.pack_into(">I", d, addr, (target + base) & 0xFFFFFFFF)
        elif typ == 2:  # R_PPC_ADDR24
            v = struct.unpack_from(">I", d, addr)[0]
            struct.pack_into(
                ">I", d, addr, ((v & 0xFC000003) | ((target + base) & 0x3FFFFFC)) & 0xFFFFFFFF
            )
        elif typ in (3, 4):  # ADDR16 / ADDR16_LO
            struct.pack_into(">H", d, addr, (target + base) & 0xFFFF)
        elif typ == 5:  # ADDR16_HI
            struct.pack_into(">H", d, addr, ((target + base) >> 16) & 0xFFFF)
        elif typ == 6:  # ADDR16_HA
            v = target + base
            struct.pack_into(">H", d, addr, ((v >> 16) + (1 if v & 0x8000 else 0)) & 0xFFFF)
    return d
