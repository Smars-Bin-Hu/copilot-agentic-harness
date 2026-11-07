"""Can the agent reach each environment from VS Code? (1.7.9)

The identity a system needs (Windows authentication, a password in the environment) is on the VS Code process, not on the board's. So the board cannot
probe for it; the hooks can, because VS Code starts them and they inherit its identity. Two ways in, both cheap:

  - at the start of a chat (SessionStart) the hook starts the pack's probes in a process of its own and returns at once: the chat does not wait. A probe
    that answered well in the last FRESH_MINUTES is not run again; a VS Code started again with another identity is probed by its first chat anyway
    when the last answer was not good;
  - after a call of a listed system (PostToolUse) the hook reads what the terminal printed: the pack's `needs.denied` pattern means the identity is wrong,
    an answer means the way in works. No process is started for it.

The state is `.harness/runtime/state/reach.json`: `{"<system>:<env>": {state, at, why, who, source}}`. `state`: ok, denied (the identity is not let in: the
launch sentence helps), failed (the server did not answer: down, or this computer is off its network; a new identity would not help), unknown.
`why` is a word the page turns into its own sentence: `identity`, `other-identity`, `no-answer`, `exit-<n>`. `who` is what the pack's `expect` pattern captured (its first group), or empty: the board shows only what the
company asked it to show. Never a password, never the probe's whole output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import systems as outside
from .paths import utc_now

FILE = Path(".harness") / "runtime" / "state" / "reach.json"
FRESH_MINUTES = 30
OK, DENIED, FAILED, UNKNOWN = "ok", "denied", "failed", "unknown"


def path(root: Path) -> Path:
    return root / FILE


def read(root: Path) -> Dict[str, Dict[str, Any]]:
    try:
        found = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _write(root: Path, found: Dict[str, Dict[str, Any]]) -> None:
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(found, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, target)


probes = outside.probes


def _judge(needs: Dict[str, Any], code: Optional[int], output: str) -> Tuple[str, str, str]:
    """(state, why, who) of one probe's answer."""
    if needs.get("denied") and re.search(needs["denied"], output or "", re.IGNORECASE):
        return DENIED, "identity", ""
    if code is None or (needs.get("down") and re.search(needs["down"], output or "", re.IGNORECASE)):
        return FAILED, "no-answer", ""
    if code != 0:
        return FAILED, f"exit-{code}", ""
    if needs.get("expect"):
        found = re.search(needs["expect"], output or "")
        if not found:
            return DENIED, "other-identity", ""
        return OK, "", (found.group(1).strip()[:80] if found.groups() and found.group(1) else "")
    return OK, "", ""


def probe_all(root: Path, listed: Dict[str, Any], run: Callable[[str], Tuple[Optional[int], str]]) -> Dict[str, Dict[str, Any]]:
    """Run every probe of every listed system and keep the answers. Run in VS Code's identity (the process the hook started)."""
    found = read(root)
    for name, system in (listed or {}).items():
        needs = system.get("needs") or {}
        for env, command in probes(system).items():
            state, why, who = _judge(needs, *run(command))
            found[f"{name}:{env}"] = {"state": state, "at": utc_now(), "why": why[:200], "who": who, "source": "probe"}
    _write(root, found)
    return found


def fresh(root: Path, listed: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Every environment of every system with a probe answered well in the last FRESH_MINUTES: no need to probe again."""
    found = read(root)
    now = time.time() if now is None else now
    keys = [f"{name}:{env}" for name, system in (listed or {}).items() for env in probes(system)]
    if not keys:
        return True
    for key in keys:
        line = found.get(key) or {}
        if line.get("state") != OK or line.get("source") != "probe":
            return False
        try:
            stamp = datetime.fromisoformat(str(line.get("at", ""))).timestamp()
        except ValueError:
            return False
        if now - stamp > FRESH_MINUTES * 60:
            return False
    return True


def recent(root: Path, keys: List[str], seconds: float = 300.0, now: Optional[float] = None) -> bool:
    """Every key has an answer, whatever it said, no older than `seconds`: the board need not check again (1.7.19)."""
    found = read(root)
    now = time.time() if now is None else now
    for key in keys:
        try:
            if now - datetime.fromisoformat(str((found.get(key) or {}).get("at", ""))).timestamp() > seconds:
                return False
        except ValueError:
            return False
    return True


def start(root: Path, listed: Dict[str, Any]) -> bool:
    """At the start of a chat: start the probes in a process of their own and return at once. False when nothing was started (no probe, or fresh)."""
    if not any(probes(system) for system in (listed or {}).values()) or fresh(root, listed):
        return False
    cli = root / ".harness" / "engine" / "cli.py"
    flags: Dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(root), "close_fds": True}
    if os.name == "nt":
        flags["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    else:
        flags["start_new_session"] = True
    subprocess.Popen([sys.executable, str(cli), "tools", "reach", "--probe"], **flags)  # noqa: S603 - our own command, no shell
    return True


def note_call(root: Path, system_name: str, system: Dict[str, Any], env: str, answer: str, failed: bool) -> None:
    """After a call of a listed system: what the terminal printed says whether the way in works. A denial counts; an answer counts as ok only when the
    environment was not known to be ok already (it keeps the `who` of the probe). A call that failed for another reason says nothing about the way in."""
    needs = system.get("needs") or {}
    key = f"{system_name}:{env}"
    found = read(root)
    line = found.get(key) or {}
    if needs.get("denied") and re.search(needs["denied"], answer or "", re.IGNORECASE):
        found[key] = {"state": DENIED, "at": utc_now(), "why": "identity", "who": "", "source": "call"}
    elif needs.get("down") and re.search(needs["down"], answer or "", re.IGNORECASE):
        found[key] = {"state": FAILED, "at": utc_now(), "why": "no-answer", "who": line.get("who", ""), "source": "call"}  # the server did not answer: no word on the identity
    elif not failed and answer.strip() and line.get("state") != OK:
        found[key] = {"state": OK, "at": utc_now(), "why": "", "who": line.get("who", ""), "source": "call"}
    else:
        return
    _write(root, found)


def view(root: Path, listed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """For the board: one line per system and environment that has a probe, `{system, env, state, at, why, who, source, launch}`; unknown when never seen."""
    found = read(root)
    out: List[Dict[str, Any]] = []
    for name, system in (listed or {}).items():
        launch = (system.get("needs") or {}).get("launch") or ""
        for env in probes(system):
            line = found.get(f"{name}:{env}") or {"state": UNKNOWN, "at": "", "why": "", "who": "", "source": ""}
            out.append({"system": name, "env": env, **line, "launch": launch})
    return out


ORDER = ("dev", "ist", "qat", "prod")


def by_env(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One line per environment, across the systems that reach it (the board shows one mark per environment): not reached when one system is not,
    not checked when one is not known yet, else reached. A system with no environment (`any`) is its own line, named by the system.
    `{env, label, state, who, launch, why, systems}`; in the order dev, ist, qat, prod, then the others."""
    merged: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        key = line["env"] if line["env"] != "any" else line["system"]
        item = merged.setdefault(key, {"env": key, "label": key.upper(), "states": [], "who": [], "launch": [], "why": [], "systems": [], "parts": []})
        item["states"].append(line["state"])
        item["systems"].append(line["system"])
        item["parts"].append({"system": line["system"], "state": line["state"], "who": line.get("who", ""), "launch": line.get("launch", "") if line["state"] == DENIED else "", "why": line.get("why", ""), "at": line.get("at", "")})  # each server of this environment, for the hover
        for name in ("who", "launch", "why"):
            if line.get(name) and line[name] not in item[name] and (name == "who" or (name == "launch" and line["state"] == DENIED) or (name == "why" and line["state"] in (DENIED, FAILED))):
                item[name].append(line[name])
    out = []
    for key in sorted(merged, key=lambda env: (ORDER.index(env) if env in ORDER else len(ORDER), env)):
        item = merged[key]
        states = item.pop("states")
        state = DENIED if DENIED in states else FAILED if FAILED in states else UNKNOWN if UNKNOWN in states else OK
        out.append({**item, "state": state, "who": ", ".join(item["who"]), "launch": "; ".join(item["launch"]), "why": "; ".join(item["why"])})
    return out


def launch_script(root: Path, platform: str = sys.platform) -> Optional[Path]:
    """A tool pack's script that starts VS Code with the identity (`launch/` of an installed tool pack): Windows only, the first `.cmd` or `.bat`."""
    if not platform.startswith("win"):
        return None
    found = sorted(item for item in (root / ".harness" / "toolpacks").glob("*/launch/*") if item.suffix.lower() in (".cmd", ".bat"))
    return found[0] if found else None


def run_launch(root: Path) -> bool:
    """Start the launch script in a window of its own (it asks the person for the account and the password itself). False when there is none."""
    script = launch_script(root)
    if script is None:
        return False
    subprocess.Popen(["cmd", "/c", "start", "", str(script)], cwd=str(root), close_fds=True)  # noqa: S603,S607 - the company's script, started as the person would
    return True
