"""High Voltage ``.AGM`` material databases - text beside the ``GGG`` models in an ``FSTA``
archive.  The parts that bind a material to a texture::

    StagedShaderTexture[76]
    {
        "TstBrck"
        "HSout2LT"
        Default
        ...
    }
    Material[81]
    {
        Material "HSout1L4"
        {
            ...
            SimpleTextureShader 0      <- index into the StagedShaderTexture list
            ...
        }
    }

The texture name is the stem of a ``.TPL`` member of the same archive, upper-cased.
"""

from __future__ import annotations

import re

_LIST = re.compile(r"StagedShaderTexture\[\d+\]\s*\{(.*?)\}", re.S)
_ENTRY = re.compile(r'"([^"]*)"|\b(Default)\b')
_MATERIAL = re.compile(r'Material\s+"([^"]+)"\s*\{(.*?)\}', re.S)
_SHADER = re.compile(r"SimpleTextureShader\s+(\d+)")


def textures(text: str) -> dict[str, str]:
    """material name -> texture name for every material with a simple texture shader."""
    m = _LIST.search(text)
    names: list[str | None] = []
    if m:
        for q, default in _ENTRY.findall(m.group(1)):
            names.append(None if default else q)
    out: dict[str, str] = {}
    for name, body in _MATERIAL.findall(text):
        s = _SHADER.search(body)
        if not s:
            continue
        k = int(s.group(1))
        if 0 <= k < len(names) and names[k]:
            out[name] = names[k]
    return out
