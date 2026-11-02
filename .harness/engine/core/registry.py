"""Module registry: .harness/registry.json. Decides which modules get which events."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from . import config, schema
from .events import EVENT_NAMES
from .paths import registry_path

STATUSES = ["experimental", "active", "deprecated", "retired"]

REGISTRY_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "version", "engine", "modules"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "released": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "copyright": {"type": "string"},
        "contributors": {"type": "array", "items": {"type": "string"}},
        "engine": {
            "type": "object",
            "required": ["files"],
            "properties": {"files": {"type": "array", "items": {"type": "string"}}},
        },
        "modules": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["status", "enabled", "events", "files"],
                "properties": {
                    "status": {"type": "string", "enum": STATUSES},
                    "enabled": {"type": "boolean"},
                    "events": {"type": "array", "items": {"type": "string", "enum": list(EVENT_NAMES)}},
                    "enforcement": {"type": "array", "items": {"type": "string", "enum": ["S", "C", "H", "V"]}},
                    "surfaces_verified": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "retire_when": {"type": "string"},
                },
            },
        },
    },
}


def load_registry(root: Path) -> Dict[str, Any]:
    registry = config.read_json(registry_path(root))
    schema.check(registry, REGISTRY_SCHEMA, "registry.json")
    return registry


def harness_version(root: Path) -> str:
    """The harness release, `major.minor.patch`. `registry.json` is its only source."""
    return load_registry(root)["version"]


BANNER = r"""
    __  __
   / / / /___ __________  ___  __________
  / /_/ / __ `/ ___/ __ \/ _ \/ ___/ ___/
 / __  / /_/ / /  / / / /  __(__  |__  )
/_/ /_/\__,_/_/  /_/ /_/\___/____/____/   version {version}
"""


BLOCKS = """
██╗  ██╗ █████╗ ██████╗ ███╗   ██╗███████╗███████╗███████╗
██║  ██║██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝
███████║███████║██████╔╝██╔██╗ ██║█████╗  ███████╗███████╗
██╔══██║██╔══██║██╔══██╗██║╚██╗██║██╔══╝  ╚════██║╚════██║
██║  ██║██║  ██║██║  ██║██║ ╚████║███████╗███████║███████║
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝
"""
ROBOT = """
.........gg.........
.........gg.........
.........oo.........
.........oo.........
....oooooooooooo....
...owwwwwwwwwwwwo...
..owwkkkkkkkkkkwwo..
..owkkkkkkkkkkkkwo..
..owkkggkkkkggkkwo..
..owkkggkkkkggkkwo..
..owkkkkkkkkkkkkwo..
..owwkkkkkkkkkkwwo..
..owwwwwwwwwwwwwso..
...owwwwwwwwwwwso...
....oooooooooooo....
.....owwwwwwwwo.....
.oo..owwwwwwwwo..oo.
owwo.owwwwwwwwo.owwo
owwo.owwwwwwwwo.owwo
owwo.owwwwwwwwo.owwo
owwo.owwwggwwwo.owwo
owwo.owwwggwwwo.owwo
owwo.owwwwwwwso.owwo
owso.owwwwwwwso.owso
.oo..owwwwwwsso..oo.
.....owwwwwwsso.....
......oooooooo......
....................
"""  # pixels: two rows make one line of text. o outline, w white, s shade, k visor, g green
ROBOT_ASCII = r"""
      o
      |
  .-------.
  | [o o] |
  '-------'
 _ .-----. _
| ||  o  || |
|_||     ||_|
   '-----'
"""
GAP = "  "
SHADES = (51, 45, 39, 33, 63, 99, 135, 171, 207)  # 256 colours, left to right: Terminal.app has no true colour
PIXELS = {"o": 240, "w": 255, "s": 250, "k": 235, "g": 41}


def unicode_stream(stream: Any) -> bool:
    return str(getattr(stream, "encoding", "") or "").lower().replace("-", "").startswith("utf")


def colour_stream(stream: Any) -> bool:
    """A terminal that takes colour codes. A Windows console takes them only in Windows Terminal or VS Code; elsewhere they show as text."""
    try:
        terminal = stream.isatty()
    except (AttributeError, ValueError):
        return False
    if not terminal or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    return os.name != "nt" or bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"))


def painted(line: str) -> str:
    """One line of the blocks, in the colours of its columns."""
    size = len(line)
    parts = []
    for start in range(size):
        shade = SHADES[start * len(SHADES) // size]
        parts.append(f"\033[38;5;{shade}m{line[start]}")
    return "".join(parts) + "\033[0m"


def cell(top: str, bottom: str, colour: bool) -> str:
    """Two pixels, one above the other, as one character. Without colour the visor is a hole, the green shows as a shade, and the page paints that shade green."""
    if colour:
        high, low = PIXELS.get(top), PIXELS.get(bottom)
        if high is None and low is None:
            return " "
        if high == low:
            return f"\033[38;5;{high}m█\033[0m"
        if low is None:
            return f"\033[38;5;{high}m▀\033[0m"
        if high is None:
            return f"\033[38;5;{low}m▄\033[0m"
        return f"\033[38;5;{high};48;5;{low}m▀\033[0m"
    if "g" in (top, bottom):
        return "▓"
    high, low = top in "ows", bottom in "ows"
    return "█" if high and low else "▀" if high else "▄" if low else " "


def robot_lines(colour: bool) -> List[str]:
    rows = ROBOT.strip("\n").split("\n")
    return ["".join(cell(top, bottom, colour) for top, bottom in zip(rows[at], rows[at + 1])) for at in range(0, len(rows), 2)]


def beside(left: List[str], room: int, lines: List[str], width: int, colour: bool) -> str:
    """The robot to the left of the text. A terminal too narrow for both has it above."""
    if colour and shutil.get_terminal_size((80, 24)).columns < room + len(GAP) + width:
        return "\n".join([*left, *lines])
    size = max(len(left), len(lines))
    rows = zip(left + [" " * room] * (size - len(left)), lines + [""] * (size - len(lines)))
    return "\n".join((one + GAP + two).rstrip() for one, two in rows)


def version_banner(root: Path, stream: Any = None) -> str:
    """What `harness --version` prints: the robot beside the name. Blocks where `stream` is UTF-8, in colour on a terminal; else ASCII, which shows on every terminal."""
    registry = load_registry(root)
    fancy = unicode_stream(stream)
    colour = fancy and colour_stream(stream)
    if fancy:
        art = BLOCKS.strip("\n").split("\n")
        word = f"version {registry['version']}"
        width = max(len(line) for line in art)
        lines = [*(painted(line) for line in art), f"\033[1m{word}\033[0m"] if colour else [*art, word]
        lines = ["", *lines, "", "Copilot Agentic Harness"]  # the robot is two lines taller: the text sits in its middle
    else:
        lines = [*BANNER.strip("\n").format(version=registry["version"]).split("\n"), "", "Copilot Agentic Harness"]
        width = max(len(line) for line in lines)
    released = registry.get("released", "")
    if released:
        lines.append(f"Released {released}")
    owner = registry.get("copyright", "")
    if owner:
        lines.append(f"Copyright (c) {released[:4]} {owner}".replace("  ", " "))
    others = registry.get("contributors") or []
    if others:
        lines.append("Contributors: " + ", ".join(others))
    if fancy:
        return beside(robot_lines(colour), len(ROBOT.strip("\n").split("\n")[0]), lines, width, colour)
    plain = ROBOT_ASCII.strip("\n").split("\n")
    room = max(len(line) for line in plain)
    return beside([line.ljust(room) for line in plain], room, lines, width, False)


def modules_for(registry: Dict[str, Any], event_name: str) -> List[str]:
    """Names of enabled, non-retired modules that subscribe to this event, in registry order."""
    return [
        name
        for name, entry in registry["modules"].items()
        if entry["enabled"] and entry["status"] != "retired" and event_name in entry["events"]
    ]
