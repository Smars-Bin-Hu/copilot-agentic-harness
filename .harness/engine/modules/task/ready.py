"""What the Enter screen of the board asks (`/api/ready`, 1.6 B86): is everything the board needs in place? One line for each check, as data; the page says it in words.

Blocking, in this order: this copy is set up (Get ready); VS Code is open and connected; Copilot can answer; `harness doctor` has no error; this browser is paired. Warn only: the knowledge base and the target repositories.

Nothing here waits on the outside world, so the server never hangs on it:
- VS Code and Copilot are read from the cache of the link thread (`vslink`), which owns every `code` command and its timeout.
- `harness doctor` takes about a second (more with a slow `code`): it runs once in a thread of its own, in a child process with a deadline, and its result is kept. It is run again only
  when it failed or found an error (and not sooner than RETRY_FAILED), or very late when it was clean. A poll only reads the kept result.
- The knowledge base and the repositories are two folder listings, kept for a few seconds.
A check that goes wrong itself is a line that failed with its reason, never an error of the request.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, shortcmd, targets, tasks

LINES = 6  # errors of doctor shown at the end of the setup
DOCTOR_TIMEOUT = 90.0  # seconds the child `doctor` may take (a stalled `code` command inside it has its own 25 s)
RETRY_FAILED = 20.0  # a doctor that failed or found errors is run again no sooner than this
REFRESH_CLEAN = 600.0  # a clean doctor is looked at again after this long
FOLDERS_FOR = 10.0  # seconds the two folder checks are kept
REASON_MAX = 300
# What the link says (`vslink.status()["why"]`) -> the state of the VS Code line. A host that is still starting, or a connection that dropped, is told as waiting: it comes back by itself.
WAITING = ("starting", "lost", "error")
STUCK = ("off", "no-cli", "cli-failed", "many")  # nothing the person can do by opening VS Code


def short(text: Any) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= REASON_MAX else one[: REASON_MAX - 1] + "…"


def setup_done(root: Path) -> bool:
    """Get ready was finished, or this is an older copy: it has a repository setting or tasks, and its owner is not asked again."""
    try:
        kept = json.loads(config.override_path(root, "user").read_text(encoding="utf-8-sig"))
        if isinstance(kept, dict) and kept.get("setup_done"):
            return True
    except (OSError, ValueError):
        pass
    return config.override_path(root, "target").exists() or bool(tasks.folders(root))


def run_doctor(root: Path, timeout: float = DOCTOR_TIMEOUT) -> Dict[str, Any]:
    """`doctor` in a child process: `{errors, first, failed}`. `failed`: why it could not be run or read (empty when it ran). Never raises."""
    command = [sys.executable, str(root / ".harness" / "engine" / "cli.py"), "doctor"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PATH=shortcmd.fresh_path())  # what a new terminal sees: the person may have added the short command after the board started
    try:
        done = subprocess.run(command, cwd=str(root), capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"errors": 0, "first": "", "failed": f"no answer in {timeout:g} s"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"errors": 0, "first": "", "failed": short(f"{type(error).__name__}: {error}")}
    text = done.stdout.decode("utf-8", errors="replace")
    errors = [line[len("[ERROR]"):].strip() for line in text.splitlines() if line.startswith("[ERROR]")]
    warnings = [line[len("[WARN]"):].strip() for line in text.splitlines() if line.startswith("[WARN]")]
    if not errors and done.returncode != 0 and '"errors"' not in text:  # it did not get as far as its summary line
        tail = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return {"errors": 0, "first": "", "failed": short(tail[-1] if tail else f"exit code {done.returncode}")}
    return {"errors": len(errors) if errors else (1 if done.returncode else 0), "first": short(errors[0]) if errors else "", "failed": "", "lines": [short(line) for line in errors[:LINES]], "warned": len(warnings), "warning": short(warnings[0]) if warnings else ""}


class Ready:
    def __init__(self, root: Path, link: Any, doctor: Optional[Callable[[Path], Dict[str, Any]]] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.reopen = False  # the short command is new: VS Code must be closed and opened again before its terminals have it
        self.root = root
        self.link = link
        self.doctor = doctor or run_doctor
        self.clock = clock
        self.lock = threading.Lock()
        self.found: Optional[Dict[str, Any]] = None  # the kept result of doctor
        self.at = 0.0
        self.running = False
        self.folders: Dict[str, Any] = {"at": -1e9}

    # --- doctor: once, off the request thread ----------------------------------------------------------------------

    def start_doctor(self) -> None:
        with self.lock:
            if self.running:
                return
            now = self.clock()
            again = self.found is None or now - self.at >= (REFRESH_CLEAN if not self.found["errors"] and not self.found["failed"] else RETRY_FAILED)
            if not again:
                return
            self.running = True
        threading.Thread(target=self.run_doctor, name="ready-doctor", daemon=True).start()

    def run_doctor(self) -> None:
        try:
            found = self.doctor(self.root)
        except Exception as error:  # noqa: BLE001 - a doctor that breaks is a line that failed, not a dead thread
            found = {"errors": 0, "first": "", "failed": short(f"{type(error).__name__}: {error}")}
        with self.lock:
            self.found, self.at, self.running = found, self.clock(), False

    # --- the checks ------------------------------------------------------------------------------------------------

    def vscode(self) -> Dict[str, Any]:
        status = self.link.status()
        if status.get("ready"):
            return {"state": "ok", "why": "ok", "n": int(status.get("bound", 0)) + int(status.get("unbound", 0))}
        why = str(status.get("why") or "starting")
        if why in WAITING:
            return {"state": "wait", "why": why, "open": True}
        return {"state": "fail", "why": why, "open": why not in STUCK}  # `none`: VS Code is not running for this folder: the person may open it

    def copilot(self, vscode: Dict[str, Any]) -> Dict[str, Any]:
        if vscode["state"] != "ok":
            return {"state": "wait", "why": "vscode"}
        found = self.link.copilot()
        if found["problem"]:
            return {"state": "fail", "why": found["problem"]}  # `Provider copilotcli is not ready` / `Client is not connected`: Copilot is not signed in
        if not found["models"]:
            return {"state": "fail", "why": "nomodel"}
        return {"state": "ok", "why": "ok", "n": found["models"]}

    def doctor_line(self) -> Dict[str, Any]:
        self.start_doctor()
        with self.lock:
            found = self.found
        if found is None:
            return {"state": "check", "why": "running"}
        if found["failed"]:
            return {"state": "fail", "why": "failed", "detail": found["failed"]}
        if found["errors"]:
            return {"state": "fail", "why": "errors", "n": found["errors"], "detail": found["first"]}
        return {"state": "ok", "why": "ok", "n": 0}

    def folder_lines(self) -> Dict[str, Dict[str, Any]]:
        now = self.clock()
        with self.lock:
            if now - self.folders["at"] < FOLDERS_FOR:
                return self.folders["lines"]
        lines: Dict[str, Dict[str, Any]] = {}
        try:
            count = sum(len(targets.knowledge_base_content(path)) for _name, path in targets.knowledge_bases(self.root))
            lines["kb"] = {"state": "ok", "why": "ok", "n": count} if count else {"state": "note", "why": "none"}
        except Exception as error:  # noqa: BLE001
            lines["kb"] = {"state": "note", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
        try:
            found = targets.load(self.root)
            if found.problems:
                lines["repos"] = {"state": "note", "why": "problem", "n": len(found.problems), "detail": short(found.problems[0])}
            elif found.repos:
                lines["repos"] = {"state": "ok", "why": "ok", "n": len(found.repos)}
            else:
                lines["repos"] = {"state": "note", "why": "none"}
        except Exception as error:  # noqa: BLE001 - a broken policy is doctor's to report; here it is a grey line
            lines["repos"] = {"state": "note", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
        with self.lock:
            self.folders = {"at": now, "lines": lines}
        return lines

    def answer(self, paired: bool) -> Dict[str, Any]:
        """`{ready, checks: [{id, blocking, state, why, ...}]}`. `state`: ok, wait (it comes by itself), fail (needs the person), check (not known yet), note (grey, never blocks)."""
        checks: List[Dict[str, Any]] = []

        def add(name: str, blocking: bool, make: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
            try:
                line = make()
            except Exception as error:  # noqa: BLE001 - a check that breaks is told as failed, with its reason
                line = {"state": "fail" if blocking else "note", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
            line = dict(line, id=name, blocking=blocking)
            checks.append(line)
            return line

        add("setup", True, lambda: {"state": "fail", "why": "new"} if not setup_done(self.root) else {"state": "wait", "why": "reopen"} if self.reopen else {"state": "ok", "why": "ok"})
        vscode = add("vscode", True, self.vscode)
        add("copilot", True, lambda: self.copilot(vscode))
        add("doctor", True, self.doctor_line)
        add("paired", True, lambda: {"state": "ok", "why": "ok"} if paired else {"state": "fail", "why": "unpaired"})
        try:
            more = self.folder_lines()
        except Exception as error:  # noqa: BLE001
            more = {name: {"state": "note", "why": "error", "detail": short(error)} for name in ("kb", "repos")}
        for name in ("kb", "repos"):
            checks.append(dict(more[name], id=name, blocking=False))
        return {"ready": all(line["state"] == "ok" for line in checks if line["blocking"]), "checks": checks}
