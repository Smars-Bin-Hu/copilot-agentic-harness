"""One-click skills of the board (1.6.61): a new chat in VS Code whose first message calls a skill. A click counts as typed, and the person sees the whole message first.

The page sends a skill name and short words; the server makes the message. Only a skill of this copy, one line, no control characters: the words cannot pretend to be another instruction.
`[ZH]` goes at the end, so the slash stays first.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from core import paths
from core.paths import utc_now

from . import chatnew
from .common import CommandError, say

MAX_WORDS = 2000
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
BREAKS = re.compile(r"[\t\r\n]+")  # what a paste brings: a space to a person


def known(root: Path, name: str) -> bool:
    return bool(NAME.fullmatch(name)) and (root / ".github" / "skills" / name / "SKILL.md").is_file()


def message(root: Path, data: Dict[str, Any]) -> str:
    name, words, lang = str(data.get("skill") or ""), BREAKS.sub(" ", str(data.get("words") or "")).strip(), str(data.get("lang") or "en")
    if not known(root, name):
        raise CommandError(say("skill.refused.name"))
    if len(words) > MAX_WORDS or CONTROL.search(words):
        raise CommandError(say("skill.refused.words", limit=MAX_WORDS))
    if lang not in ("en", "zh"):
        raise CommandError(say("skill.refused.lang"))
    return " ".join(part for part in (f"/{name}", words, "[ZH]" if lang == "zh" else "") if part)


def plan(lang: str, name: str = "") -> Dict[str, Any]:
    """A chat with no task: `vslink` keeps no name for it, so nothing waits for a task to bind. With the `name` of a task that exists ("go on in a new chat"), the board binds the chat to it
    at its next look, as it does a chat it made for a new task. The model of a click is not kept on the task: the person did not choose it."""
    return {"name": name, "kind": "", "source": "", "text": "", "lang": lang, "permission": "allow-all", "approve": chatnew.PERMISSIONS["allow-all"], "model": None, "domains": [], "keep_model": False}


def record(root: Path, name: str, opens: str, done: Dict[str, Any]) -> None:
    """One line for each chat the board started: what, when and which session. Never the words."""
    path = paths.runtime_dir(root) / "board-chats.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": utc_now(), "skill": name, "opens": opens, "session": str(done.get("session") or "")}) + "\n")
