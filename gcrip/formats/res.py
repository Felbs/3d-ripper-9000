"""``res\\n`` resource files (Digimon Rumble Arena 2, Lemony Snicket's A Series of Unfortunate
Events, Samurai Jack: The Shadow of Aku - the same middleware under three publishers).

Header (big-endian): ``char "res\\n" | u16 version (7) | u16 | u32 data offset | u32 data size
| u32 | u32 | u32 | u32 directory offset | u32 directory size | u32 tag count`` followed by
one 8-byte record per tag kind (``char tag[4] | u8 | u8 | u16``).  The directory lives at the
end of the file: ``u32 entry count`` then 20-byte entries ``u32 id | char tag[4] | u32 offset
| u32 size | u32 flags``, where the offset is relative to the data area.

Section tags seen: ``wave`` / ``musc`` / ``mdat`` (audio), ``strg`` / ``indx`` (text and its
index), and on level files ``sdta``, ``gshd``, ``node``, ``surf``, ``ndbg``, ``levl``,
``tern``, ``rdms`` - the geometry side, which is not decoded yet.

``indx`` is **a name directory for the other sections**, not an index of the text::

    u32 count
    u32 4
    then count entries of 12 bytes:
        u32  name offset    self-relative from this field, into ``strg``
        char tag[4]         the kind of section referred to
        u32  delta          self-relative from this field, to the section itself

**Both offsets are self-relative**, the same convention ``rdms`` uses for its array offsets, and
that is what makes them resolve: `field position + value`.  Measured against a base of the
``indx`` section start instead, none of the six names lands on a string.  All six of Lemony
Snicket's entries and Samurai Jack's one entry resolve to a real section whose tag matches the
entry's, and to a full asset path - ``menus/train_game/bobblehead_texture.tif``,
``menus/train_game/fx_hud_shelf``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"res\n"
ENTRY = 20


@dataclass
class IndexEntry:
    name: str
    tag: str
    offset: int  # absolute in the file, of the section this entry names


@dataclass
class Section:
    tag: str
    ident: int
    offset: int  # absolute in the file
    size: int
    flags: int


def is_res(head: bytes) -> bool:
    if len(head) < 0x28 or head[:4] != MAGIC:
        return False
    version = head[4]  # stored little-endian: 07 00
    data_off, data_size = struct.unpack_from(">2I", head, 8)
    return 0 < version <= 32 and data_off >= 0x28 and data_size > 0


def sections(data: bytes) -> list[Section]:
    if not is_res(data[:0x28]):
        return []
    data_off, data_size = struct.unpack_from(">2I", data, 8)
    dir_off, dir_size = struct.unpack_from(">2I", data, 0x1C)
    if dir_off + dir_size > len(data) or dir_size < 4:
        return []
    count = struct.unpack_from(">I", data, dir_off)[0]
    if not 0 < count < 100000 or 4 + count * ENTRY > dir_size + ENTRY:
        return []
    out = []
    for i in range(count):
        p = dir_off + 4 + i * ENTRY
        if p + ENTRY > len(data):
            break
        ident, tag, off, size, flags = struct.unpack_from(">I4sIII", data, p)
        start = data_off + off
        if size == 0 or start + size > len(data) or off + size > data_size + size:
            continue
        out.append(Section(tag.decode("latin-1", "replace").strip("\0"), ident, start, size, flags))
    return out


def _stem(path: str) -> str:
    """The asset's own name, safe to use as a file name."""
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in leaf)[:48]


SHADER_LINK = 4  # an rdms section's word at +4 reaches its gshd
SURF_LINK = 0x5C  # a gshd section's word at +0x5c reaches its surf


def shader_textures(data: bytes, found: list[Section] | None = None) -> dict[int, int]:
    """rdms section index -> surf section index, through the shader.

    Every ``rdms`` carries a **self-relative** word at +4 (the ``0xffffff1c``-looking one)
    that lands on a ``gshd`` section - its shader - and every ``gshd`` a self-relative word at
    +0x5c that lands on the ``surf`` it samples.  On Samurai Jack's level files 73 of 73
    ``rdms`` resolve this way (ladder, test_bridge, test_platforms).  Characters' ``bmsh``
    reach their ``gshd`` the same way from their batch records.
    """
    found = sections(data) if found is None else found
    by_offset = {s.offset: (i, s.tag) for i, s in enumerate(found)}
    out: dict[int, int] = {}
    for i, s in enumerate(found):
        if s.tag != "rdms" or s.offset + SHADER_LINK + 4 > len(data):
            continue
        gshd = s.offset + SHADER_LINK + struct.unpack_from(">i", data, s.offset + SHADER_LINK)[0]
        if by_offset.get(gshd, (None, None))[1] != "gshd" or gshd + SURF_LINK + 4 > len(data):
            continue
        surf = gshd + SURF_LINK + struct.unpack_from(">i", data, gshd + SURF_LINK)[0]
        hit = by_offset.get(surf)
        if hit and hit[1] == "surf":
            out[i] = hit[0]
    return out


def expand(data: bytes) -> list[tuple[str, bytes]]:
    """One member a section.

    Sections the ``indx`` directory names carry that name, so a texture comes out as
    ``000_surf_bobblehead_texture.bin`` rather than ``000_surf_84213.bin``.  The numbered
    prefix and the ``_tag_`` infix stay either way - the plugin screens members on ``_surf_``
    and ``_rdms_``, and the index only ever covers a handful of the sections.
    """
    named = {e.offset: e.name for e in index_entries(data)}
    owners = {}
    for link in node_links(data):
        for mesh in link.meshes:
            owners.setdefault(mesh, link.name or f"node{link.offset}")
    out = []
    found = sections(data)
    textures = shader_textures(data, found)
    for i, s in enumerate(found):
        label = _stem(named[s.offset]) if s.offset in named else str(s.ident)
        if s.tag == "rdms" and s.offset in owners:
            # a mesh takes its node's name, so the parts of one object land together
            label = f"{_stem(owners[s.offset])}_{s.ident}"
        if s.tag == "rdms" and i in textures:
            # ... and names the surf member its shader samples, so the plugin can bind it
            label = f"{label}_t{textures[i]:03d}"
        name = f"{i:03d}_{s.tag or 'sect'}_{label}.bin"
        out.append((name, data[s.offset : s.offset + s.size]))
    return out


INDEX_HEADER = 8
INDEX_ENTRY = 12


def _string(table: bytes, at: int) -> str | None:
    if not 0 <= at < len(table):
        return None
    end = table.find(b"\0", at)
    if end < 0:
        end = len(table)
    return table[at:end].decode("latin-1") or None


def index_entries(data: bytes) -> list[IndexEntry]:
    """The ``indx`` directory: what each named section is called.

    Returns [] when the file carries no ``indx``/``strg`` pair, and skips any entry whose
    offsets do not land on a real section and a real string - the two self-relative offsets are
    the check, so a misread entry drops out instead of naming the wrong thing.
    """
    found = sections(data)
    index = next((s for s in found if s.tag == "indx"), None)
    strings = next((s for s in found if s.tag == "strg"), None)
    if index is None or strings is None or index.size < INDEX_HEADER:
        return []
    table = data[strings.offset : strings.offset + strings.size]
    at_section = {s.offset: s.tag for s in found}
    (count,) = struct.unpack_from(">I", data, index.offset)
    if count * INDEX_ENTRY + INDEX_HEADER > index.size:
        return []
    out = []
    for i in range(count):
        at = index.offset + INDEX_HEADER + INDEX_ENTRY * i
        name_off, tag, delta = struct.unpack_from(">I4sI", data, at)
        if delta > 0x7FFFFFFF:
            delta -= 1 << 32
        target = at + 8 + delta
        label = tag.decode("latin-1", "replace").strip("\0")
        if at_section.get(target) != label:
            continue
        name = _string(table, at + name_off - strings.offset)
        if name is None:
            continue
        out.append(IndexEntry(name, label, target))
    return out


@dataclass
class NodeLink:
    offset: int  # of the node section
    name: str | None  # from the index, when the node is named
    meshes: list[int]  # offsets of the rdms sections this node draws


def node_links(data: bytes) -> list[NodeLink]:
    """Which meshes each ``node`` section draws.

    A node refers to its meshes by the format's usual **self-relative** offset - a word whose
    value plus its own position lands on an ``rdms`` section - and the reference sits inside a
    52-byte record laid out as::

        f32[6]   a min/max box, small and near the origin
        u32 0 | u32 1 | u32 1 | u32 4
        u32      the self-relative offset of the mesh
        u32      0x7f7fffff (FLT_MAX)
        u32 2

    On Lemony Snicket's 25-section file **all seven ``rdms`` sections are referenced, each
    exactly once**, by three nodes - so the nodes account for the whole geometry of the file.

    **This is not the placement data.**  The box in each record is about 0.3 units wide and off
    centre, while the mesh it points at spans +-39 and is symmetric about the origin, so it is
    neither the mesh's bounds nor a scale of them.  What the links give is *grouping* - which
    meshes belong to one object - and, through the index, that object's name.  Assembling a
    level still needs the transform, which is somewhere else in the node section.
    """
    found = sections(data)
    meshes = {s.offset for s in found if s.tag == "rdms"}
    named = {e.offset: e.name for e in index_entries(data)}
    out = []
    for section in found:
        if section.tag != "node":
            continue
        seen = []
        for at in range(section.offset, section.offset + max(0, section.size - 3), 4):
            (delta,) = struct.unpack_from(">i", data, at)
            target = at + delta
            if target in meshes and target not in seen:
                seen.append(target)
        if seen:
            out.append(NodeLink(section.offset, named.get(section.offset), seen))
    return out
