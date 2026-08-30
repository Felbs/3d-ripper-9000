"""res `rdms` meshes - Samurai Jack, Lemony Snicket, Digimon Rumble Arena 2."""

import struct

import numpy as np

from gcrip.formats import res_rdms
from gcrip.plugins import res as plugin


def build(npos=6, nuv=6, nnrm=4, corners=8, fmt=1, scale=2.0, preamble=13):
    """A section with the real shape: self-relative array offsets, a 32-byte aligned array
    block, and one triangle strip of `corners` corners."""

    def pad(n):
        return -(-n // res_rdms.ALIGN) * res_rdms.ALIGN

    strip = struct.pack(">BH", 0x98, corners)
    for i in range(corners):
        strip += struct.pack(">5H", i % npos, i % nnrm, 0, i % nuv, 0)
    block = max(res_rdms.FORMAT_AT + 1, res_rdms.FORMAT_AT + preamble) + len(strip)
    first = pad(block)

    # not collinear: a strip of collinear points is all stitches and comes back empty
    pts = [(i, (i * i) % 7, (i * 3) % 5) for i in range(npos)]
    if fmt == 0:
        positions = b"".join(struct.pack(">3f", *map(float, v)) for v in pts)
    else:
        positions = b"".join(struct.pack(">3h", *v) for v in pts)
    normals = b"".join(struct.pack(">3b", 64, 0, 0) for _ in range(nnrm))
    colors = struct.pack(">4B", 255, 255, 255, 255)
    uvs = b"".join(struct.pack(">2h", i * 100, 4096 - i * 100) for i in range(nuv))

    sizes = [pad(len(x)) for x in (positions, normals, colors, uvs)]
    offsets = [first]
    for s in sizes:
        offsets.append(offsets[-1] + s)

    head = bytearray(max(res_rdms.FORMAT_AT + 1, res_rdms.FORMAT_AT + preamble))
    struct.pack_into(">2I", head, 0, 1, 0xFFFFFF1C)
    struct.pack_into(">2I", head, 8, block - res_rdms.FORMAT_AT, res_rdms.FORMAT_AT)
    struct.pack_into(">f", head, res_rdms.SCALE_AT, scale)
    for i, off in enumerate(offsets):
        struct.pack_into(">I", head, res_rdms.ARRAYS_AT + 4 * i, off - res_rdms.ARRAYS_AT - 4 * i)
    head[res_rdms.FORMAT_AT] = fmt

    body = bytes(head) + strip
    body += bytes(first - len(body))
    for blob, size in zip((positions, normals, colors, uvs), sizes, strict=True):
        body += blob + bytes(size - len(blob))
    return body + bytes(4)


def test_array_offsets_are_self_relative():
    """A single base makes the first array right and every later one wrong by 4 per slot -
    which is exactly how this format used to read one element short."""
    data = build()
    arrays = res_rdms._arrays(data)
    assert arrays is not None and arrays == sorted(arrays)
    assert all(a % res_rdms.ALIGN == 0 for a in arrays)
    words = struct.unpack_from(">5I", data, res_rdms.ARRAYS_AT)
    flat = [w + res_rdms.ARRAYS_AT for w in words]
    assert flat != arrays  # a single base does not reproduce them


def test_the_last_offset_is_the_end_of_the_section():
    data = build()
    arrays = res_rdms._arrays(data)
    assert len(data) - arrays[-1] < res_rdms.ALIGN


def test_the_stride_comes_from_the_gap_not_a_guess():
    """Each array is padded to 32 bytes, so only one stride rounds up to the gap."""
    assert res_rdms._stride(288, 45, (6,)) == 6
    assert res_rdms._stride(288, 45, (12,)) is None  # 45 * 12 overruns
    assert res_rdms._stride(32, 4, (6, 8)) is None  # ambiguous, so refused


def test_s16_positions_are_scaled_by_the_header_float():
    m = res_rdms.mesh(build(fmt=1, scale=2.0))
    assert m is not None
    assert m.positions.max() == 5 * 2.0  # the largest packed component, times the scale


def test_f32_positions_are_taken_as_they_are():
    m = res_rdms.mesh(build(fmt=0))
    assert m is not None
    assert m.positions.max() == 5.0  # the largest packed component, unscaled


def test_uvs_and_normals_come_back_scaled():
    m = res_rdms.mesh(build())
    assert m.uvs is not None and m.uvs.max() <= 1.0
    assert m.normals is not None
    assert np.isclose(np.abs(m.normals).max(), 1.0)


def test_the_preamble_before_the_first_opcode_is_scanned_for():
    for preamble in (0, 5, 13, 40):
        assert res_rdms.mesh(build(preamble=preamble)) is not None


def test_degenerate_strip_stitches_are_dropped():
    """A strip that only stitches has no area at all, so nothing comes back."""
    assert res_rdms.mesh(build(npos=1)) is None


def test_plugin_claims_rdms_members_and_returns_a_mesh():
    data = build()
    assert plugin.detect("level/level.res_rdms_1628.bin", data[:64], len(data))
    (scene,) = plugin.extract(data, "level/level_rdms_1628.bin", None)
    assert scene.triangles > 0
    assert scene.extras["format"] == "res_rdms"
