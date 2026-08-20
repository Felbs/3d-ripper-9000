"""Regenerate gcrip/data/ww_actors.py's WW_ACTORS dict from noclip.website.

Downloads src/ZeldaWindWaker/LegacyActor.ts (MIT licensed; it credits LordNed,
Sage-of-Mirrors & LagoLunatic's Winditor ActorDatabase for the mapping) and mines the
actorName -> fetchArchive/buildModel pairs out of its if/else chain.

    python tools/ww_actor_table.py            # prints the dict body to stdout

Paste the output over the generated section of gcrip/data/ww_actors.py, keeping the
hand-added aliases and the category rules at the bottom of that file.
"""

from __future__ import annotations

import re
import urllib.request

URL = (
    "https://raw.githubusercontent.com/magcius/noclip.website/master/"
    "src/ZeldaWindWaker/LegacyActor.ts"
)


def mine(src: str) -> dict[str, list[tuple[str, str | None]]]:
    branch_re = re.compile(r"(?:else )?if \((?P<cond>[^)]*(?:actorName|pcName)[^)]*)\)")
    matches = list(branch_re.finditer(src))
    table: dict[str, list[tuple[str, str | None]]] = {}
    for i, m in enumerate(matches):
        names = re.findall(r"actorName === '([^']+)'", m.group("cond"))
        if not names:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        body = src[m.end() : end]
        pairs: list[tuple[str, str | None]] = []
        cur_arc = None
        pat = (
            r"fetchArchive\([`'\"](\w+)[`'\"]\)"
            r"|buildModel(?:BMT)?\(\s*rarc,\s*[`'\"]([^`'\"]+\.(?:bdl|bmd))[`'\"]"
        )
        for mm in re.finditer(pat, body):
            if mm.group(1):
                cur_arc = mm.group(1)
            elif cur_arc:
                pairs.append((cur_arc, mm.group(2)))
        for mm in re.finditer(r"getObjectRes\(ResType\.Model,\s*[`'\"](\w+)[`'\"]", body):
            pairs.append((mm.group(1), None))
        if pairs:
            for n in names:
                table.setdefault(n, pairs)
    return table


def main() -> None:
    with urllib.request.urlopen(URL) as r:  # noqa: S310
        src = r.read().decode("utf-8")
    table = mine(src)
    for name in sorted(table):
        seen: set = set()
        out = [p for p in table[name] if not (p in seen or seen.add(p))][:6]
        body = ", ".join(f"({arc!r}, {model!r})" for arc, model in out)
        print(f"    {name!r}: [{body}],")
    print(f"# {len(table)} actor names")


if __name__ == "__main__":
    main()
