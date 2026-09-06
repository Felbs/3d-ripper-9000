"""EA shape (FSH/GSH) textures - the GameCube record layout and directory forms."""

from gcrip.formats import ea_shape


def test_gc_record_body_starts_at_0x20():
    """The GameCube shape record header is 0x20 bytes, not 0x30.  A 0x30 header is one
    CMPR tile too long, which shifted every NHL / NBA Live arena by a tile."""
    import struct

    w, h = 8, 8
    body = bytes(range(32))  # one CMPR tile
    rec = bytearray(0x20 + len(body))
    rec[0] = 0x1E
    struct.pack_into(">2I", rec, 0x18, w, h)
    rec[0x20:] = body
    data = b"ShpG" + struct.pack("<I", 0x40 + len(rec)) + struct.pack(">I", 1) + b"GIMX"
    data += struct.pack(">2I", 0x40, len(rec))  # the single-image header pair at 0x10
    data = data.ljust(0x40, b"\0") + bytes(rec)

    imgs = ea_shape.parse(data)
    assert len(imgs) == 1
    img = imgs[0]
    assert (img.width, img.height) == (w, h)
    assert img.rgba is not None and img.rgba.shape == (h, w, 4)


def test_gc_directory_walks_variable_length_entries():
    """EA Canada's multi-image SHPG directory is ``u32 offset | 3 bytes | NUL name``,
    not the SHPI ``char[4] name | u32 offset`` table."""
    import struct

    names = [b"`1", b"`11", b"`2"]
    # build the directory first so the offsets can point past it
    dirbytes = b""
    for n in names:
        dirbytes += b"\0\0\0\0" + b"\x00\x04\x00" + n + b"\0"
    start = 0x10 + len(dirbytes)
    recs, offs = b"", []
    for _ in names:
        offs.append(start + len(recs))
        r = bytearray(0x20 + 32)
        r[0] = 0x1E
        struct.pack_into(">2I", r, 0x18, 8, 8)
        recs += bytes(r)
    dirbytes = b""
    for n, o in zip(names, offs):
        dirbytes += struct.pack(">I", o) + b"\x00\x04\x00" + n + b"\0"
    data = b"ShpG" + struct.pack("<I", 0x10 + len(dirbytes) + len(recs))
    data += struct.pack(">I", len(names)) + b"\0\0\0\0" + dirbytes + recs

    assert ea_shape._gc_directory(data) == [
        (n.decode("latin-1"), o) for n, o in zip(names, offs)
    ]
    imgs = ea_shape.parse(data)
    assert [i.name for i in imgs] == [n.decode("latin-1") for n in names]
    assert all(i.rgba is not None for i in imgs)


def test_gc_directory_rejects_a_real_shpi_table():
    """A genuine name/offset table must not be walked as the variable-length form."""
    import struct

    data = b"SHPI" + struct.pack("<I", 0x100) + struct.pack("<I", 2) + b"GIMX"
    data += b"aaaa" + struct.pack("<I", 0x40) + b"bbbb" + struct.pack("<I", 0x80)
    data = data.ljust(0x100, b"\0")
    assert ea_shape._gc_directory(data) is None
