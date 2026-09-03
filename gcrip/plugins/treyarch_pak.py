"""Treyarch's ``amalga_gc.pak`` (gcrip.formats.ngl_gc) as a container: every resource pack
inside it becomes a folder, and the pack's textures, mesh files and material files go on as
``<PACK>/<hash>[_<name>].gct`` / ``.ifl`` / ``.gcmesh`` / ``.gcmat`` for the ``ngl_mesh``
plugin."""

from __future__ import annotations

from gcrip.formats import ngl_gc

NAME = "treyarch_pak"

EXT = {ngl_gc.TL_TEXTURE: "gct", ngl_gc.TL_MESHFILE: "gcmesh", ngl_gc.TL_MATFILE: "gcmat"}


def detect(path: str, head: bytes, size: int) -> bool:
    return False


def extract(data: bytes, path: str, src):
    return []


def is_container(name: str, head: bytes) -> bool:
    return name.lower().endswith(".pak") and ngl_gc.is_amalgapak(head, 1 << 40)


def _member(prefix: str, r: ngl_gc.Resource, seen: dict[str, int]) -> str:
    stem = f"{prefix}/{r.hash:08x}"
    if r.name:
        stem += "_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in r.name)
    n = seen.get(stem, 0)
    seen[stem] = n + 1
    return f"{stem}{'' if n == 0 else f'_{n}'}.{EXT[r.kind]}"


def expand(data: bytes) -> list[tuple[str, bytes]]:
    try:
        entries = ngl_gc.pak_entries(data)
    except ngl_gc.NglError:
        return []
    out = []
    packs: dict[str, int] = {}
    for e in entries:
        blob = data[e.offset : e.offset + e.size]
        if not ngl_gc.is_pack(blob[:64]):
            continue
        try:
            pack = ngl_gc.parse_pack(blob)
        except (ngl_gc.NglError, ValueError):
            continue
        prefix = e.name or "pack"
        n = packs.get(prefix, 0)
        packs[prefix] = n + 1
        if n:
            prefix = f"{prefix}_{n}"
        seen: dict[str, int] = {}
        for r in pack.textures + pack.mesh_files + pack.material_files:
            payload = ngl_gc.resource_bytes(blob, r)
            if r.kind == ngl_gc.TL_TEXTURE and not ngl_gc.is_gct(payload[:24]):
                if ngl_gc.is_ifl(payload[:64]):  # a frame list shares the texture type
                    out.append((_member(prefix, r, seen).rsplit(".", 1)[0] + ".ifl", payload))
                continue
            if r.kind != ngl_gc.TL_TEXTURE and not ngl_gc.is_gcnm(payload[:20], len(payload)):
                continue
            out.append((_member(prefix, r, seen), payload))
    return out
