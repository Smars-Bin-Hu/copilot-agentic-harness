"""The statements of a held call, one by one, for its card (1.7.38, C13 F3 AP): a statement, which system it is on, and how the type's lists judge it.

A card of a call that carries many statements (a script file, a `-Q` text with several, two scripts) used to show them as one block of text. Here each statement is cut as the gate cuts it (`gate.statements.split`),
judged by the lists of its type (`statements.judge`, one statement at a time), and told as `read` (the pass list: it passes with no approval), `write` (the write list: it passes once the connection is open for the
task) or `ask` (on no list: it waits for the person, whatever is open) with the reason the type gives (`why` of a `say` rule), or the general one. A statement on the refuse list makes the whole call refused and never has a card.

It is a display: the gate judged the call when it held it and judges it again when it runs. A line that cannot be read here has no list (the card is drawn as before). The files are those the card pins (`core.pinfiles`).
The statements are cut at STATEMENT_CHARS each and at MAX_STATEMENTS in all; the totals are of every statement. Stdlib only.
"""

from __future__ import annotations

import re
import shlex
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import inputfiles, statements  # the cut and the lists of the gate: the card tells what the gate will say
from core import systems as outside

from . import cmdview

MAX_STATEMENTS = 800  # the statements one card sends; a script of more has the rest counted, not listed
STATEMENT_CHARS = 280  # one statement is cut here; the whole text is in the file the card names
ZONES = ("read", "write", "ask", "refuse")
_KEPT: "OrderedDict[Any, Dict[str, Any]]" = OrderedDict()
_KEPT_MAX = 48  # the board asks for every card every few seconds: a call whose files did not change is not cut and judged again


def _tokens(text: str) -> List[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def _cut(text: str) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= STATEMENT_CHARS else one[: STATEMENT_CHARS - 1].rstrip() + "…"


def _program_at(tokens: List[str], programs: List[str]) -> Optional[int]:
    for index, token in enumerate(tokens):
        name = re.sub(r"\.(?:cmd|bat|exe)$", "", re.split(r"[\\/]", token)[-1], flags=re.IGNORECASE).lower()
        if name in programs:
            return index
    return None


def of_call(root: Path, task: str, command: str, listed: Dict[str, Any], pins: Optional[Dict[str, str]] = None, cwd: str = "") -> Optional[Dict[str, Any]]:
    """`{items: [{n, text, zone, system, env, why, file}], total, more, counts: {read, write, ask}, systems}` for the statements of a held call, or None when the call has none to list (its type has no lists, or
    it reads nothing the gate sees). `listed`: the systems of the tools policy. `pins`: what the card pins, for the cache. Never raises."""
    key = (command, cwd, task, tuple(sorted((pins or {}).items())))
    if key in _KEPT:
        _KEPT.move_to_end(key)
        return _KEPT[key]
    try:
        found = _of_call(root, task, command, listed, cwd)
    except Exception:  # noqa: BLE001 - a display: the card is drawn without it
        found = None
    _KEPT[key] = found  # type: ignore[assignment]
    while len(_KEPT) > _KEPT_MAX:
        _KEPT.popitem(last=False)
    return found


def _of_call(root: Path, task: str, command: str, listed: Dict[str, Any], cwd: str) -> Optional[Dict[str, Any]]:
    folder = root / task if task else None
    items: List[Dict[str, Any]] = []
    counts = {"read": 0, "write": 0, "ask": 0}
    names: List[Dict[str, str]] = []
    total = 0
    for part in cmdview.commands(command):
        tokens = _tokens(part)
        owner = None
        for name, system in (listed or {}).items():
            programs = outside.clis(system) if isinstance(system, dict) else []
            if programs and _program_at(tokens, programs) is not None and system.get("reads"):
                owner = (name, system, _program_at(tokens, programs))
                break
        if owner is None:
            continue
        name, system, start = owner
        read = inputfiles.read(system, tokens[start + 1:], root, folder, cwd, command)
        if read is None or not read.items:
            continue
        env = str(system.get("env") or "")
        if {"system": name, "env": env} not in names:
            names.append({"system": name, "env": env})
        rules = system.get("say")
        for item in read.items:
            verdict = statements.judge(system, [item])
            zone = verdict.zone if verdict.zone in ZONES else "ask"
            if zone in counts:
                counts[zone] += 1
            total += 1
            if len(items) >= MAX_STATEMENTS:
                continue
            raw = item.raw or item.text
            why = cmdview.why_of(raw, rules) if zone == "ask" else ""
            items.append({"n": total, "text": _cut(raw), "zone": zone, "system": name, "env": env, "why": why, "file": read.files.get(item.text, "") if read.files else "",
                          "cut": len(" ".join(raw.split())) > STATEMENT_CHARS, "odd": bool(item.odd), "directive": bool(item.directive)})
    if not total:
        return None
    return {"items": items, "total": total, "more": max(0, total - len(items)), "counts": counts, "systems": names}
