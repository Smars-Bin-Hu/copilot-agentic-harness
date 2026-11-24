"""Which line of the hook log is which call of Copilot's record or of the board's stream (1.8.43).

The three records name and time one call differently:
- names: the hook gets the harness's names (`Bash`, `Read`, `Write`, `AskUserQuestion`), Copilot's `events.jsonl` and the board's stream the engine's own (`powershell`, `view`, `create`,
  `ask_user`). So calls are compared by family (`family`), never by name.
- times: a hook line is written when the hook is done. On the Mac that is 0.1 s after Copilot's `tool.execution_start`; on a work PC with security software it was 3–13 s (2026-11-24).
  So a hook line may come up to HOOK_LAG_S after its call, and never much before it.

`pair` gives each hook line the call of its family that started last before it. Pure.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

HOOK_LAG_S = 90.0  # a hook line may be written this long after the start of its call (a slow PC: measured up to 13 s; a busy one more)
HOOK_EARLY_S = 2.0  # and this much before it (two clocks, rounding)
PARALLEL_S = 1.0  # calls that start this close together run side by side

# Names in Copilot's own record and in the board's stream that the hook never gets (it gets the harness's names: adapters/tool_kinds.json). Seen on a work PC, 2026-11-24.
RECORD_NAMES = {"view": "read", "create": "create", "edit": "edit", "grep": "search", "glob": "search", "ask_user": "ask"}
# Kinds that are one family: a hook's `Write` is `create`, and an engine may call the same write an edit.
SAME_FAMILY = {"create": "write", "edit": "write"}

_known: Optional[Dict[str, str]] = None


def _kinds() -> Dict[str, str]:
    """adapters/tool_kinds.json, by lower-case name; the record's names on top. A file that cannot be read leaves the record's names only."""
    global _known
    if _known is None:
        found: Dict[str, str] = {}
        try:  # read as a file: a module does not import the adapters
            with open(Path(__file__).resolve().parents[2] / "adapters" / "tool_kinds.json", encoding="utf-8-sig") as handle:
                kinds = json.load(handle)
            for surface in kinds["surfaces"].values():
                for name, kind in (surface.get("tools") or {}).items():
                    found.setdefault(str(name).lower(), str(kind))
        except Exception:  # noqa: BLE001 - a family by name alone is still a family
            pass
        found.update(RECORD_NAMES)
        _known = found
    return _known


def family(name: Any) -> str:
    """The family of a tool by any of its names: terminal, read, search, write, ask, ... A name not known is its own family (lower case)."""
    text = str(name or "").strip().lower()
    kind = _kinds().get(text, text)
    return SAME_FAMILY.get(kind, kind)


def pair(hooks: Sequence[Tuple[Optional[float], Any]], calls: Sequence[Tuple[Optional[float], Any]]) -> Dict[int, int]:
    """`{hook index: call index}`. `hooks`, `calls`: `(seconds or None, tool name)`, each list oldest first; only calls of the same family pair.

    A hook line with a time goes with the call of its family that started last before it (up to HOOK_EARLY_S after it, at most HOOK_LAG_S before it): PreToolUse holds the call, so the
    next call of the session starts only after the line is written. Calls that start together (within PARALLEL_S) are taken oldest first. A line or a call with no time (a turn
    the board wrote later) goes by order alone. A line whose call the record lacks pairs with nothing; a missing line moves no other pair."""
    used: set = set()
    out: Dict[int, int] = {}
    families = [family(name) for _at, name in calls]
    for index, (at, name) in enumerate(hooks):
        mine = [number for number in range(len(calls)) if number not in used and families[number] == family(name)]
        timed = [number for number in mine if calls[number][0] is not None]
        if at is not None and timed:
            near = [number for number in timed if at - HOOK_LAG_S <= calls[number][0] <= at + HOOK_EARLY_S]
            if near:
                last = max(calls[number][0] for number in near)
                chosen = min((number for number in near if calls[number][0] >= last - PARALLEL_S), key=lambda number: (calls[number][0], number))
                used.add(chosen)
                out[index] = chosen
            continue
        untimed = [number for number in mine if calls[number][0] is None] if at is not None else mine
        if untimed:
            used.add(untimed[0])
            out[index] = untimed[0]
    return out
