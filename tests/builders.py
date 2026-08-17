"""Synthetic GameCube data builders for tests (no game data required)."""

from __future__ import annotations

import struct


def yaz0_literal(data: bytes) -> bytes:
    """Yaz0 stream containing only literals."""
    out = bytearray(b"Yaz0" + struct.pack(">I", len(data)) + b"\x00" * 8)
    for i in range(0, len(data), 8):
        chunk = data[i : i + 8]
        out.append(0xFF)
        out += chunk
    return bytes(out)


def yay0_literal(data: bytes) -> bytes:
    """Yay0 stream containing only literals: header, mask words, (no links), chunk data."""
    n_masks = (len(data) + 31) // 32
    mask_bytes = b"\xff\xff\xff\xff" * n_masks
    link_off = 16 + len(mask_bytes)
    chunk_off = link_off  # no links
    return b"Yay0" + struct.pack(">III", len(data), link_off, chunk_off) + mask_bytes + data


def build_rarc(files: dict[str, bytes], root: str = "root") -> bytes:
    """Build a RARC with arbitrary nested paths (e.g. {'a/b.bin': data})."""
    # Collect directory tree
    tree: dict = {}
    for path, data in files.items():
        parts = path.split("/")
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = data

    strings = bytearray(b".\x00..\x00")
    str_offsets: dict[str, int] = {".": 0, "..": 2}

    def s(name: str) -> int:
        if name not in str_offsets:
            str_offsets[name] = len(strings)
            strings.extend(name.encode("shift_jis") + b"\x00")
        return str_offsets[name]

    def hsh(name: str) -> int:
        h = 0
        for c in name.encode("shift_jis"):
            h = (h * 3 + c) & 0xFFFF
        return h

    nodes: list[tuple[str, str, int, int]] = []  # (tag, name, nfiles, first)
    entries: list[tuple] = []  # (id, hash, flags, name, off_or_node, size)
    data_blob = bytearray()
    next_id = 0

    def add_node(name: str, node: dict, parent_index: int | None) -> int:
        nonlocal next_id
        idx = len(nodes)
        tag = "ROOT" if parent_index is None else name.upper()[:4].ljust(4)
        nodes.append((tag, name, 0, 0))
        first = len(entries)
        # reserve slots: files then subdirs, then . and ..
        subdirs = [(k, v) for k, v in node.items() if isinstance(v, dict)]
        my_entries: list = []
        for k, v in node.items():
            if isinstance(v, dict):
                continue
            off = len(data_blob)
            data_blob.extend(v)
            while len(data_blob) % 32:
                data_blob.append(0)
            my_entries.append((next_id, hsh(k), 0x11, k, off, len(v)))
            next_id += 1
        for k, _ in subdirs:
            my_entries.append((0xFFFF, hsh(k), 0x02, k, -1, 0x10))  # node idx patched later
        my_entries.append((0xFFFF, hsh("."), 0x02, ".", idx, 0x10))
        my_entries.append(
            (
                0xFFFF,
                hsh(".."),
                0x02,
                "..",
                parent_index if parent_index is not None else 0xFFFFFFFF,
                0x10,
            )
        )
        entries.extend(my_entries)
        nodes[idx] = (tag, name, len(my_entries), first)
        # recurse into subdirs and patch node index
        for k, v in subdirs:
            child = add_node(k, v, idx)
            for ei in range(first, first + len(my_entries)):
                e = entries[ei]
                if e[3] == k and e[2] == 0x02 and e[4] == -1:
                    entries[ei] = (e[0], e[1], e[2], e[3], child, e[5])
                    break
        return idx

    add_node(root, tree, None)
    for _tag, name, _, _ in nodes:
        s(name)
    for e in entries:
        s(e[3])

    node_tbl = bytearray()
    for tag, name, nfiles, first in nodes:
        node_tbl += tag.encode("ascii") + struct.pack(">IHHI", s(name), hsh(name), nfiles, first)
    ent_tbl = bytearray()
    for fid, h, flags, name, off, size in entries:
        ent_tbl += struct.pack(
            ">HHIIII", fid, h, (flags << 24) | s(name), off & 0xFFFFFFFF, size, 0
        )

    info_size = 0x20
    node_off = info_size
    file_off = node_off + len(node_tbl)
    str_off = file_off + len(ent_tbl)
    while str_off % 32:
        ent_tbl.append(0)
        str_off += 1
    strings_padded = bytes(strings)
    while (str_off + len(strings_padded)) % 32:
        strings_padded += b"\x00"
    data_off_rel = str_off + len(strings_padded)  # relative to header end (0x20)
    total = 0x20 + data_off_rel + len(data_blob)
    header = b"RARC" + struct.pack(
        ">IIIIIII", total, 0x20, data_off_rel, len(data_blob), len(data_blob), 0, 0
    )
    info = struct.pack(
        ">IIIIIIHBBI",
        len(nodes),
        node_off,
        len(entries),
        file_off,
        len(strings_padded),
        str_off,
        next_id,
        1,
        0,
        0,
    )
    return header + info + bytes(node_tbl) + bytes(ent_tbl) + strings_padded + bytes(data_blob)


def build_disc(
    files: dict[str, bytes],
    *,
    game_id: bytes = b"GTST01",
    title: bytes = b"Test Disc",
    dirs: list[str] | None = None,
) -> bytes:
    """Build a minimal GameCube disc image with the given files (paths like 'a/b.bin').

    Layout: header @0, bi2 @0x440, apploader @0x2440 (0x20 header + 0x100 body),
    main.dol @0x3000 (a header-only DOL of size 0x100), FST @0x4000, files after.
    """
    tree: dict = {}
    for d in dirs or []:
        node = tree
        for p in d.split("/"):
            node = node.setdefault(p, {})
    for path, data in files.items():
        parts = path.split("/")
        node = tree
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = data

    entries: list[list] = [[1, 0, 0, 0]]  # root: [flags, name_off, offset, size]
    strings = bytearray()
    blobs: list[tuple[int, bytes]] = []  # (entry index, data)

    def add(node: dict, parent_index: int) -> None:
        for name in sorted(node):  # deterministic; real discs are also sorted (case-insensitive)
            v = node[name]
            name_off = len(strings)
            strings.extend(name.encode("shift_jis") + b"\x00")
            idx = len(entries)
            if isinstance(v, dict):
                entries.append([1, name_off, parent_index, 0])
                add(v, idx)
                entries[idx][3] = len(entries)  # next index
            else:
                entries.append([0, name_off, 0, len(v)])
                blobs.append((idx, v))

    add(tree, 0)
    entries[0][3] = len(entries)

    fst_offset = 0x4000
    fst_entries_size = 12 * len(entries)
    fst_size = fst_entries_size + len(strings)
    data_pos = (fst_offset + fst_size + 0x7FFF) & ~0x7FFF
    for idx, data in blobs:
        entries[idx][2] = data_pos
        data_pos += (len(data) + 31) & ~31

    fst = bytearray()
    for flags, name_off, off, size in entries:
        fst += struct.pack(">III", (flags << 24) | name_off, off, size)
    fst += strings

    img = bytearray(data_pos)
    img[0:6] = game_id
    img[6] = 0  # disc number
    img[7] = 1  # revision
    img[0x1C:0x20] = struct.pack(">I", 0xC2339F3D)
    img[0x20 : 0x20 + len(title)] = title
    dol_offset = 0x3000
    img[0x420:0x438] = struct.pack(">6I", dol_offset, fst_offset, fst_size, fst_size, 0, 0)
    img[0x458:0x45C] = struct.pack(">I", 1)  # NTSC-U
    # apploader: date + sizes
    img[0x2440:0x2450] = b"2001/01/01\x00\x00\x00\x00\x00\x00"
    img[0x2440 + 0x14 : 0x2440 + 0x1C] = struct.pack(">II", 0x100, 0)
    # DOL header: one text section at 0x100, size 0x40 -> total 0x140
    img[dol_offset : dol_offset + 4] = struct.pack(">I", 0x100)
    img[dol_offset + 0x90 : dol_offset + 0x94] = struct.pack(">I", 0x40)
    img[fst_offset : fst_offset + fst_size] = fst
    for idx, data in blobs:
        off = entries[idx][2]
        img[off : off + len(data)] = data
    return bytes(img)
