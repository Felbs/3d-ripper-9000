"""Mass Media ``BOLT`` archives (``.BLT``) as a container: every member decompressed
(gcrip.formats.bolt) and handed on as ``g<group>_<slot>_t<type>.bmdl`` (a model node tree),
``.bmat`` (the material list the models of the archive index) or ``.bin``."""

from __future__ import annotations

from gcrip.formats import bolt, bolt_model

NAME = "bolt"


def is_container(name: str, head: bytes) -> bool:
    return bolt.is_bolt(head)


def expand(data: bytes) -> list[tuple[str, bytes]]:
    out = []
    for m in bolt.members(data):
        try:
            blob = bolt.unpack(data, m)
        except bolt.BoltError:
            continue
        if blob:
            ext = (
                "bmdl"
                if bolt_model.is_model(blob[:bolt_model.HEAD])
                else "bmat"
                if bolt_model.is_material_list(blob[:bolt_model.HEAD])
                else "bin"
            )
            out.append((f"g{m.group:02d}_{m.slot:04d}_t{m.kind:02x}.{ext}", blob))
    return out


# a container is only registered when it also carries a detect/extract pair
def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []
