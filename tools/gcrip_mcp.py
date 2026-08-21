"""MCP server for the gcrip Godot remake's debug control channel.

Start the game with the channel open:

    Godot_v4.7.2-stable_win64_console.exe --path out/rip/GZLE01/godot -- --control

(add ``--headless`` for an unattended run, ``--stage=<key>`` to boot somewhere specific).
The game binds 127.0.0.1 only and the channel exists solely for testing - never ship a build
that starts it.

Every tool here is one JSON line to the game and one JSON line back, so the game stays in
charge of its own frame loop and nothing here can wedge it.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

from mcp.server.fastmcp import FastMCP

HOST = "127.0.0.1"
PORT = int(os.environ.get("GCRIP_CONTROL_PORT", "8787"))
TIMEOUT = float(os.environ.get("GCRIP_CONTROL_TIMEOUT", "20"))

mcp = FastMCP("gcrip")

_sock: socket.socket | None = None
_io: Any = None


def _connect() -> Any:
    global _sock, _io
    if _io is not None:
        return _io
    _sock = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
    _io = _sock.makefile("rwb")
    return _io


def _drop() -> None:
    global _sock, _io
    for c in (_io, _sock):
        try:
            if c is not None:
                c.close()
        except OSError:
            pass
    _sock = None
    _io = None


def call(**kw: Any) -> dict:
    """One command to the running game; reconnects once if the game was restarted."""
    for attempt in (1, 2):
        try:
            io = _connect()
            io.write((json.dumps(kw) + "\n").encode())
            io.flush()
            line = io.readline()
            if not line:
                raise ConnectionError("the game closed the connection")
            return json.loads(line.decode())
        except (OSError, ConnectionError, json.JSONDecodeError) as exc:
            _drop()
            if attempt == 2:
                return {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": f"is the game running with --control on {HOST}:{PORT}?",
                }
    return {"ok": False, "error": "unreachable"}


@mcp.tool()
def game_state() -> dict:
    """Where Link is and what the game is doing: scene, position, facing, player state,
    what is under his feet, hearts, items, and which story steps are done."""
    return call(cmd="state")


@mcp.tool()
def game_stages() -> dict:
    """Every stage that can actually be entered (the ones with a PLYR spawn), with the
    in-game place names."""
    return call(cmd="stages")


@mcp.tool()
def game_warp(stage: str, room: int = 0, spawn: int = 0) -> dict:
    """Load a stage and put Link on one of its spawn points."""
    return call(cmd="warp", stage=stage, room=room, spawn=spawn)


@mcp.tool()
def game_place(
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    facing_deg: float | None = None,
) -> dict:
    """Move Link straight to a position in the current scene (any omitted axis is kept)."""
    args: dict[str, Any] = {"cmd": "place"}
    for k, v in (("x", x), ("y", y), ("z", z), ("facing_deg", facing_deg)):
        if v is not None:
            args[k] = v
    return call(**args)


@mcp.tool()
def game_actors() -> dict:
    """Every NPC and enemy placed in the current scene, with positions."""
    return call(cmd="actors")


@mcp.tool()
def game_talk(actor: str) -> dict:
    """Stand Link in front of that actor and talk to it - the story step, if any, runs."""
    return call(cmd="talk", actor=actor)


@mcp.tool()
def game_input(action: str, frames: int = 2, strength: float = 1.0) -> dict:
    """Hold an input action for a number of frames, the way a player taps or holds a button.
    Call with a wrong name to get the list of actions the game defines."""
    return call(cmd="input", action=action, frames=frames, strength=strength)


@mcp.tool()
def game_stick(x: float, y: float, frames: int = 30) -> dict:
    """Push the analog stick (x right, y forward, each -1..1) for a number of frames."""
    return call(cmd="stick", x=x, y=y, frames=frames)


@mcp.tool()
def game_event(name: str) -> dict:
    """Run one of this stage's event_list.dat events by name. Call with a wrong name to get
    the list of events this stage has."""
    return call(cmd="event", name=name)


@mcp.tool()
def game_dialog_advance() -> dict:
    """Turn the page of an open text box (the scripted equivalent of pressing A)."""
    return call(cmd="dialog")


@mcp.tool()
def game_bit(id: int, set: bool | None = None) -> dict:  # noqa: A002
    """Read - or with set=true raise - one dSv_event_flag_c story bit, e.g. 0x0E20."""
    args: dict[str, Any] = {"cmd": "bit", "id": id}
    if set is not None:
        args["set"] = set
    return call(**args)


@mcp.tool()
def game_item(name: str, give: bool = False) -> dict:
    """Check, or hand over, one of the opening's quest items: clothes, telescope, sword,
    shield."""
    return call(cmd="item", name=name, give=give)


@mcp.tool()
def game_ground(x: float | None = None, z: float | None = None, y: float = 0.0) -> dict:
    """What collision is under a point (Link's own position when no point is given). An empty
    answer means nothing is there - a void."""
    args: dict[str, Any] = {"cmd": "ground"}
    if x is not None and z is not None:
        args.update(x=x, y=y, z=z)
    return call(**args)


@mcp.tool()
def game_screenshot(path: str = "user://control_shot.png") -> dict:
    """Save a screenshot of what the game is showing and return the file path. Needs a
    windowed (not --headless) run."""
    return call(cmd="screenshot", path=path)


@mcp.tool()
def game_quit() -> dict:
    """Close the running game."""
    return call(cmd="quit")


if __name__ == "__main__":
    mcp.run()
