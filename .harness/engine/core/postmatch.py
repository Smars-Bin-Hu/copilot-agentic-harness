"""Which tool calls the PostToolUse hook is started for (hook speed).

On a slow computer every hook process costs seconds, and most of what the post hook once did is nothing for some tools (a skill load, a web fetch, a chat rename). Copilot's hook `matcher` is a regular
expression over the name Copilot gives its tool, and the hook payload carries a different name for some of them (`view` is `Read`, `create` is `Write`, `task` is `Agent`), so the matcher lists both.

The one source of truth is `adapters/tool_kinds.json`: `post_kinds` (the kinds of tool something is done after) and, for the surface, `tools` (the payload names, with their kind) and `copilot_names`
(Copilot's own names, with their kind). `matcher()` builds the expression from them; `.github/hooks/harness.json` holds it on its `PostToolUse` entry, and a test and `harness doctor` check that the two are the same.
Add a tool name to `tool_kinds.json`, run `python3 .harness/engine/core/postmatch.py` and put what it prints in `harness.json`.

Standard library only (the hook starts it); the file is read as a file, since a module does not import the adapters.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

SURFACE = "vscode"
EVENT = "PostToolUse"  # the entry of harness.json that carries the matcher; no other entry has one (the gate must see every call, and the other events are rare)

_cache: Dict[str, Any] = {}


def tool_kinds_path() -> Path:
    return Path(__file__).resolve().parents[1] / "adapters" / "tool_kinds.json"


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    """tool_kinds.json (cached when the default file). A file that cannot be read raises: a caller that must not fail catches it."""
    if path is not None:
        with path.open(encoding="utf-8-sig") as handle:
            return json.load(handle)
    if "data" not in _cache:
        _cache["data"] = load(tool_kinds_path())
    return _cache["data"]


def kinds(data: Optional[Dict[str, Any]] = None, surface: str = SURFACE) -> List[str]:
    """The kinds of tool a PostToolUse call is acted on for."""
    body = (data or load())["surfaces"][surface]
    return [str(kind) for kind in body["post_kinds"]]


def names(data: Optional[Dict[str, Any]] = None, surface: str = SURFACE) -> List[str]:
    """Every name, payload name and Copilot's own, of a tool whose kind is one of `kinds()`, sorted."""
    body = (data or load())["surfaces"][surface]
    wanted = set(kinds(data, surface))
    found = {str(name) for table in (body["tools"], body.get("copilot_names") or {}) for name, kind in table.items() if kind in wanted}
    return sorted(found)


def _escape(name: str) -> str:
    return name if re.fullmatch(r"\w+", name) else re.escape(name)


def matcher(data: Optional[Dict[str, Any]] = None, surface: str = SURFACE) -> str:
    """The expression for the `matcher` of the PostToolUse entry: anchored, so `view` does not match `preview` (whether Copilot anchors by itself is not known)."""
    return "^(?:" + "|".join(_escape(name) for name in names(data, surface)) + ")$"


def _compiled() -> Tuple[Pattern[str], str]:
    if "pattern" not in _cache:
        text = matcher()
        _cache["pattern"] = (re.compile(text), text)
    return _cache["pattern"]


def matches(name: Any) -> bool:
    """Is a post hook started for a tool of this name (payload or Copilot name)? False for a name the matcher does not list. A file that cannot be read: True (no claim that a call has no post row)."""
    try:
        return bool(_compiled()[0].search(str(name or "")))
    except Exception:  # noqa: BLE001 - a log reader must not fail on this
        return True


def configured(entry: Any) -> Optional[str]:
    """The `matcher` of one hook entry as it is written (None when the entry has none)."""
    value = entry.get("matcher") if isinstance(entry, dict) else None
    return value if isinstance(value, str) else None


if __name__ == "__main__":
    sys.stdout.write(matcher() + "\n")
