"""Walk up to every villager in Outset and talk to them, over the control channel.

Vertical traversal (ladders, stairs) is not something the bot can drive yet, so when the actor
is on another floor it is placed at that floor first and walks the last stretch - which still
exercises the real interaction range, the real A press, the dialogue rules and the story graph.
"""

from __future__ import annotations

import json
import math
import socket
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
STAGES = ["sea_r44", "LinkRM", "Ojhous", "Ojhous2", "Omori", "Onobuta", "Opub", "Obombh"]
# actors that are in the "interact" group but are not villagers standing on the ground: the
# Helmaroc King circles 4000 units up, so there is nowhere to stand and talk to it
SKIP = {"Dk"}


class Game:
    def __init__(self, port: int) -> None:
        self.f = socket.create_connection(("127.0.0.1", port), timeout=30).makefile("rwb")

    def __call__(self, **kw):
        self.f.write((json.dumps(kw) + "\n").encode())
        self.f.flush()
        return json.loads(self.f.readline().decode())

    def state(self) -> dict:
        return self(cmd="state").get("state", {})

    def quiet(self, timeout: float = 60.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            st = self.state()
            if st.get("dialog_open"):
                self(cmd="dialog")
                time.sleep(0.1)
                continue
            if not st.get("event_running") and not st.get("cutscene"):
                return st
            time.sleep(0.3)
        return self.state()

    def approach(self, target: list[float], stop: float = 90.0, seconds: float = 8.0) -> dict:
        """Get within `stop` of the target, placing Link on its floor first if need be."""
        st = self.state()
        p = st.get("pos") or [0, 0, 0]
        if abs(p[1] - target[1]) > 250.0:
            # another floor (or the far side of the island): the bot cannot climb, so start it
            # on the actor's own level, on a side that has a floor rather than open water
            # small offsets first: a lookout platform is not 220 units wide
            for dx, dz in ((0, 90), (0, -90), (90, 0), (-90, 0),
                           (0, 220), (0, -220), (220, 0), (-220, 0)):
                u = str(self(cmd="ground", x=target[0] + dx, y=target[1] + 5,
                             z=target[2] + dz).get("under") or "")
                if u and "liquid_water" not in u:
                    self(cmd="place", x=target[0] + dx, y=target[1] + 5, z=target[2] + dz,
                         facing_deg=math.degrees(math.atan2(-dx, -dz)))
                    break
            time.sleep(0.4)
        end = time.time() + seconds
        while time.time() < end:
            st = self.state()
            p = st.get("pos") or [0, 0, 0]
            dx, dz = target[0] - p[0], target[2] - p[2]
            d = math.hypot(dx, dz)
            if d < stop:
                self(cmd="stick", x=0, y=0, frames=1)
                return st
            self(cmd="place", facing_deg=math.degrees(math.atan2(dx, dz)))
            self(cmd="stick", x=0.0, y=1.0, frames=10)
            time.sleep(0.2)
        self(cmd="stick", x=0, y=0, frames=1)
        st = self.grounded()
        p = st.get("pos") or [0, 0, 0]
        if math.hypot(p[0] - target[0], p[2] - target[2]) > stop * 1.6:
            # walking got lost (Outset is all ledges and open water): stand him at talking
            # distance instead, on whichever side of the actor actually has a floor - the
            # point of this sweep is the interaction, not the pathfinding
            for dx, dz in ((0, stop), (0, -stop), (stop, 0), (-stop, 0)):
                probe = self(cmd="ground", x=target[0] + dx, y=target[1] + 5,
                             z=target[2] + dz)
                under = str(probe.get("under") or "")
                if under and "liquid_water" not in under:   # the sea is not somewhere to stand
                    self(cmd="place", x=target[0] + dx, y=target[1] + 5, z=target[2] + dz,
                         facing_deg=math.degrees(math.atan2(-dx, -dz)))
                    break
            else:
                self(cmd="place", x=target[0], y=target[1] + 5, z=target[2] + stop,
                     facing_deg=180.0)
            st = self.grounded()
        return st

    def grounded(self, timeout: float = 3.0) -> dict:
        """Wait until Link is back in the GROUND state - the prompt scan does not run in the
        air, so pressing A while he is still settling does nothing."""
        end = time.time() + timeout
        st = self.state()
        while time.time() < end and st.get("state") != 0:
            time.sleep(0.15)
            st = self.state()
        return st


def main() -> int:
    g = Game(PORT)
    seen: dict[str, str] = {}
    problems: list[str] = []

    for stage in STAGES:
        r = g(cmd="warp", stage=stage)
        if not r.get("ok"):
            print(f"-- {stage}: {r.get('error')}")
            continue
        g.quiet()
        actors = g(cmd="actors").get("actors", [])
        names = sorted({a["actor"] for a in actors if a["group"] == "interact"})
        print(f"\n== {stage}: {names}")
        for name in names:
            if name in ("<null>", "") or name in SKIP or name in seen:
                continue
            a = next(x for x in actors if x["actor"] == name)
            st = g.approach(a["pos"])
            p = st.get("pos") or [0, 0, 0]
            d = math.hypot(p[0] - a["pos"][0], p[2] - a["pos"][2])
            before = set(st.get("story_done", []))
            # capture WHY a press does nothing: no prompt target means out of range, on
            # another floor, or not facing the actor
            pre = g.grounded()
            why = (f"prompt={pre.get('prompt_target')!r} dy={abs(pre['pos'][1] - a['pos'][1]):.0f} "
                   f"facing={pre.get('facing_deg')} state={pre.get('state')}")
            g(cmd="input", action="action_a", frames=6)
            time.sleep(0.7)
            st2 = g.state()
            pages = 0
            while st2.get("dialog_open") and pages < 30:
                g(cmd="dialog")
                pages += 1
                time.sleep(0.1)
                st2 = g.state()
            st3 = g.quiet()
            new_story = sorted(set(st3.get("story_done", [])) - before)
            outcome = []
            if pages:
                outcome.append(f"{pages} pages")
            if new_story:
                outcome.append("story: " + ", ".join(new_story))
            if not outcome:
                outcome.append("NOTHING HAPPENED  " + why)
                problems.append(f"{stage}/{name}: no response at {d:.0f} units - {why}")
            seen[name] = "; ".join(outcome)
            print(f"   {name:7} at {d:5.0f} units -> {seen[name]}")

    print("\n---- villagers that said nothing ----")
    for line in problems:
        print("  " + line)
    print(f"{len(seen)} villagers talked to, {len(problems)} silent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
