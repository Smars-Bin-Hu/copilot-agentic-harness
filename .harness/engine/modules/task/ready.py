"""What the Enter screen of the board asks (`/api/ready`, 1.6 B86): is everything the board needs in place? One line for each check, as data; the page says it in words.

Blocking, in this order: this copy is set up (Get ready); VS Code is open and connected; Copilot can answer; `harness doctor` has no error; this browser is paired. Warn only: the knowledge base and the target repositories.

Nothing here waits on the outside world, so the server never hangs on it:
- VS Code and Copilot are read from the cache of the link thread (`vslink`), which owns every `code` command and its timeout.
- `harness doctor` takes about a second (a minute and more on a slow work computer): it runs once in a thread of its own, in a child process with a deadline (`board.doctor_seconds`), and its result is kept. A board started from a terminal starts it at once, before a page asks (1.6.104). It is run again only
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

from core import config, messages, shortcmd, targets, tasks
from core import reach, systems as outside

LINES = 6  # errors of doctor shown at the end of the setup
DOCTOR_TIMEOUT = 300.0  # seconds the child `doctor` may take; `board.doctor_seconds` in the policy `task` (1.6.104: 90 was too short for a work computer that took 80 s)
DOCTOR_LIMITS = (30.0, 1800.0)
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


def doctor_seconds(root: Path) -> float:
    """The deadline of the child `doctor`: `board.doctor_seconds` of the policy `task`, kept between DOCTOR_LIMITS; DOCTOR_TIMEOUT when it is not set or not a number."""
    value = (config.policy_or_empty(root, "task").get("board") or {}).get("doctor_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DOCTOR_TIMEOUT
    return min(max(float(value), DOCTOR_LIMITS[0]), DOCTOR_LIMITS[1])


def run_doctor(root: Path, timeout: Optional[float] = None) -> Dict[str, Any]:
    """`doctor` in a child process: `{errors, first, failed}`. `failed`: why it could not be run or read (empty when it ran). Never raises."""
    timeout = doctor_seconds(root) if timeout is None else timeout
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
        self.drops_then = 0  # the losses of the link when the wait began
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
        try:
            systems = config.policy_or_empty(self.root, "tools").get("systems") or {}
            raw = reach.view(self.root, systems) if systems and not outside.validate(systems) else []  # what VS Code reached (1.7.9), per server and environment
            marks = {reach.OK: "\u2713", reach.DENIED: "\u2717", reach.FAILED: "\u2717", reach.UNKNOWN: "?"}
            servers = list(dict.fromkeys(line["system"] for line in raw))
            worst = lambda states: reach.DENIED if reach.DENIED in states else reach.FAILED if reach.FAILED in states else reach.UNKNOWN if reach.UNKNOWN in states else reach.OK  # noqa: E731
            reason = lambda line: (line["launch"] or messages.text("desk.reach.why.identity")) if line["state"] == reach.DENIED else messages.text("desk.reach.why.no-answer") if line["why"] == "no-answer" else messages.text("desk.reach.why.exit", why=line["why"])  # noqa: E731
            env_marks = lambda lines: " ".join(f"{line['env'].upper() if line['env'] != 'any' else ''}{marks[line['state']]}".strip() for line in lines)  # noqa: E731
            if len(servers) > 1:  # several servers: one mark per server (the worst of its environments); the hover lists each server's environments
                units = [(name, worst([line["state"] for line in raw if line["system"] == name]), [line for line in raw if line["system"] == name]) for name in servers]
            else:  # one server: one mark per environment
                units = [(line["env"].upper() if line["env"] != "any" else line["system"], line["state"], [line]) for line in raw]
            detail = " \u00b7 ".join(f"{label} {marks[state]}" for label, state, _lines in units)
            if len(servers) > 2:  # three servers or more: a count per mark keeps the line on one line; the hover names each server
                counts = [(sum(1 for _l, state, _x in units if marks[state] == mark), mark) for mark in ("\u2713", "\u2717", "?")]
                detail = messages.text("board.enter.d.systems.count", n=len(servers), marks=" ".join(f"{count} {mark}" for count, mark in counts if count))
            bad = [line for line in raw if line["state"] in (reach.DENIED, reach.FAILED)]
            name = lambda line: f"{line['system']} {line['env'].upper()}" if len(servers) > 1 else line["env"].upper()  # noqa: E731
            if not systems:
                lines["systems"] = {"state": "note", "why": "none", "tip": "none"}  # not set up yet: the hover says how
            elif not raw:
                lines["systems"] = {"state": "ok", "why": "listed", "n": len(systems)}  # listed, with no probe: nothing to look at
            elif bad:
                grouped: Dict[str, List[str]] = {}  # one reason, the places it holds for: "finance IST, hr DEV: <sentence>"
                for line in bad:
                    grouped.setdefault(reason(line), []).append(name(line))
                overview = "\n".join(f"{label}: {env_marks(lines_)}" for label, _state, lines_ in units) if len(servers) > 1 else ""
                lines["systems"] = {"state": "note", "why": "unreached", "detail": detail, "tip": "\n".join(([overview] if overview else []) + [short(f"{', '.join(names)}: {text}") for text, names in grouped.items()]),
                                    "launch": any(line["state"] == reach.DENIED for line in bad) and reach.launch_script(self.root) is not None}  # only a refused identity is helped by starting VS Code again
            elif any(line["state"] == reach.UNKNOWN for line in raw):
                lines["systems"] = {"state": "note", "why": "unknown", "detail": detail, "launch": reach.launch_script(self.root) is not None}
            else:
                last = max((line.get("at", "") for line in raw), default="")
                accounts = " \u00b7 ".join(f"{name(line)} {line['who']}" for line in raw if line["who"])
                lines["systems"] = {"state": "ok", "why": "ok", "detail": detail, "tip": short(messages.text("desk.reach.ok.tip", accounts=accounts or "-", at=last[11:16]))}
        except Exception as error:  # noqa: BLE001
            lines["systems"] = {"state": "note", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
        with self.lock:
            self.folders = {"at": now, "lines": lines}
        return lines

    def wait_reopen(self) -> None:
        self.drops_then = self.link.drops()
        self.reopen = True

    def still_reopen(self) -> bool:
        """The wait ends when the link was lost once, whichever page is open and however fast VS Code came back."""
        if self.reopen and self.link.drops() != self.drops_then:
            self.reopen = False
        return self.reopen

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

        add("setup", True, lambda: {"state": "fail", "why": "new"} if not setup_done(self.root) else {"state": "wait", "why": "reopen"} if self.still_reopen() else {"state": "ok", "why": "ok"})
        vscode = add("vscode", True, self.vscode)
        add("copilot", True, lambda: self.copilot(vscode))
        add("doctor", True, self.doctor_line)
        add("paired", True, lambda: {"state": "ok", "why": "ok"} if paired else {"state": "fail", "why": "unpaired"})
        try:
            more = self.folder_lines()
        except Exception as error:  # noqa: BLE001
            more = {name: {"state": "note", "why": "error", "detail": short(error)} for name in ("kb", "repos", "systems")}
        for name in ("kb", "repos", "systems"):
            checks.append(dict(more[name], id=name, blocking=False))
        return {"ready": all(line["state"] == "ok" for line in checks if line["blocking"]), "checks": checks}
