"""Get ready (1.6.57): what the page `/setup` shows and writes. No agent, no premium request.

Everything goes into the person's own `*.override.json`, next to what is already there. A broken file stops the write; nothing is overwritten. One wrong field: nothing is written.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, messages, shortcmd, state as files

MAX_NAME = 100
MAX_PATH = 1024
GIT_WAIT = 5.0


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def kept(root: Path, name: str) -> Dict[str, Any]:
    path = config.override_path(root, name)
    if not path.exists():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(say("setup.file.broken", file=str(path), error=error)) from None
    if not isinstance(found, dict):
        raise ValueError(say("setup.file.broken", file=str(path), error="not an object"))
    return found


def write(root: Path, name: str, values: Dict[str, Any]) -> None:
    found = kept(root, name)
    found.update(values)
    files.atomic_write(config.override_path(root, name), found)


def git_name() -> str:
    try:
        done = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True, timeout=GIT_WAIT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()[:MAX_NAME]


def clean_path(text: Any) -> str:
    value = str(text if text is not None else "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return os.path.expanduser(value)


def repositories(text: Any) -> Dict[str, Any]:
    """What is in the folder of code repositories: `{ok, n, names, why}`. Read only. Empty: a person may set it later."""
    value = clean_path(text)
    if not value:
        return {"ok": True, "n": 0, "names": [], "why": ""}
    path = Path(value)
    if len(value) > MAX_PATH or "\x00" in value or not path.is_absolute():
        return {"ok": False, "n": 0, "names": [], "why": say("setup.repos.absolute")}
    if not path.is_dir():
        return {"ok": False, "n": 0, "names": [], "why": say("setup.repos.missing")}
    try:
        names = sorted(item.name for item in path.iterdir() if (item / ".git").exists())
    except OSError as error:
        return {"ok": False, "n": 0, "names": [], "why": str(error)[:200]}
    return {"ok": True, "n": len(names), "names": names[:3], "why": "" if names else say("setup.repos.none")}


def status(root: Path, short_found: Optional[str] = None) -> Dict[str, Any]:
    """What the page needs. Reading a broken override file is told, not raised: the page must open to say so."""
    problem = ""
    user: Dict[str, Any] = {}
    target: Dict[str, Any] = {}
    try:
        user, target = kept(root, "user"), kept(root, "target")
    except ValueError as error:
        problem = str(error)
    path = shortcmd.fresh_path()
    found = shortcmd.found(path) if short_found is None else short_found
    return {"problem": problem, "name": str(user.get("name") or "") or git_name(), "language": str(user.get("language") or messages.language()), "repos_root": str(target.get("repos_root") or ""),
            "short": {"found": found, "command": "" if found else shortcmd.command_for(root, path), "windows": os.name == "nt"}}


def finish(root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Check all, then write all. `{lines: [{key, ok, detail}]}`. ValueError: what is wrong; nothing was written."""
    name = " ".join(str(data.get("name") or "").split())
    language = str(data.get("language") or "").strip().lower()
    repos = repositories(data.get("repos_root"))
    wrong: List[str] = []
    if not name or len(name) > MAX_NAME:
        wrong.append(say("setup.name.need", limit=MAX_NAME))
    if language not in messages.LANGUAGES:
        wrong.append(say("setup.language.need"))
    if not repos["ok"]:
        wrong.append(repos["why"])
    forced = os.environ.get(messages.ENVIRONMENT, "").strip().lower()
    if forced and forced != language:
        wrong.append(say("serve.language.env", name=messages.ENVIRONMENT))
    if wrong:
        raise ValueError(" ".join(wrong))
    lines: List[Dict[str, Any]] = []
    steps: List[Callable[[], str]] = []

    def user() -> str:
        write(root, "user", {"name": name, "language": language})
        return name

    def target() -> str:
        value = clean_path(data.get("repos_root"))
        if not value:
            return say("setup.line.later")
        write(root, "target", {"repos_root": value})
        return say("setup.line.repos", n=repos["n"])

    steps = [user, target]
    for key, step in zip(("user", "target"), steps):
        try:
            lines.append({"key": key, "ok": True, "detail": step()})
        except (OSError, ValueError) as error:
            lines.append({"key": key, "ok": False, "detail": str(error)[:300]})
    if all(line["ok"] for line in lines):
        write(root, "user", {"setup_done": True})
    return {"lines": lines, "done": all(line["ok"] for line in lines)}
