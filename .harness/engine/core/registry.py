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
        ●
        │
   ╭─────────╮
   │╭───────╮│
   ││ ●   ● ││
   │╰───────╯│
   ╰───┬─┬───╯
╭─╮╭───┴─┴───╮╭─╮
│ ││         ││ │
│ ││    ●    ││ │
╰─╯│         │╰─╯
   ╰─────────╯
"""
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
GAP = "   "
SHADES = (51, 45, 39, 33, 63, 99, 135, 171, 207)  # 256 colours, left to right: Terminal.app has no true colour
GREEN = 41


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


def beside(robot: str, lines: List[str], width: int, colour: bool) -> str:
    """The robot to the left of the text. A terminal too narrow for both has it above."""
    left = robot.strip("\n").split("\n")
    room = max(len(line) for line in left)
    if colour:
        columns = shutil.get_terminal_size((80, 24)).columns
        if columns < room + len(GAP) + width:
            return "\n".join([*(paint_robot(line) for line in left), *lines])
    size = max(len(left), len(lines))
    rows = zip(left + [""] * (size - len(left)), lines + [""] * (size - len(lines)))
    return "\n".join(((paint_robot(one.ljust(room)) if colour else one.ljust(room)) + GAP + two).rstrip() for one, two in rows)


def paint_robot(line: str) -> str:
    return line.replace("●", f"\033[1;38;5;{GREEN}m●\033[0m")


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
        lines += ["", "Copilot Agentic Harness"]
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
    return beside(ROBOT if fancy else ROBOT_ASCII, lines, width, colour)


def modules_for(registry: Dict[str, Any], event_name: str) -> List[str]:
    """Names of enabled, non-retired modules that subscribe to this event, in registry order."""
    return [
        name
        for name, entry in registry["modules"].items()
        if entry["enabled"] and entry["status"] != "retired" and event_name in entry["events"]
    ]
