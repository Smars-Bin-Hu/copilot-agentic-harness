"""What the Enter screen of the board asks (`/api/ready`, 1.6 B86): is everything the board needs in place? One line for each check, as data; the page says it in words.

Two blocks (1.7.38, block B).
- REQUIRED, Harness & Local: this copy is set up, this browser is paired, `harness doctor` has no error, VS Code is open for this copy, Copilot is connected. Every line must be ok before Enter is on:
  without one the harness cannot work here. They are `checks`, each with `group: "required"` and `blocking: true`, and a `level` for its dot: ok, grey, yellow, red.
- OPTIONAL, from the company: knowledge base, instructions, company skills, code standards, tool packs, connections, code repositories (`core/readyitems.py`). They never block. `optional` holds the items and the
  `problems` to look at; each problem has the place that mends it.
`problems.required` is what is not ok in the first block (the red block of the board after Enter), `vscode_button` says what the VS Code button of the screen is called (open, restart, identities), and `restart`
what a restart that was asked for is doing (`vsrestart.py`).

Nothing here waits on the outside world, so the server never hangs on it:
- VS Code and Copilot are read from the cache of the link thread (`vslink`), which owns every `code` command and its timeout. Whether any VS Code runs on this computer is one `pgrep` or `tasklist`, in a thread of its own.
- `harness doctor` takes about a second (a minute and more on a slow work computer): it runs once in a thread of its own, in a child process with a deadline (`board.doctor_seconds`), and its result is kept. A board started from a terminal starts it at once, before a page asks (1.6.104). It is run again only
  when it failed or found an error (and not sooner than RETRY_FAILED), or very late when it was clean. A poll only reads the kept result.
- The optional items are file listings, kept for a few seconds, and again at once when a policy, the sign-ins or the packs change.
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

from core import config, launchenv, messages, readyitems, shortcmd, targets, tasks
from core import reach, systems as outside

from . import reachcheck

LINES = 6  # errors of doctor shown at the end of the setup
DOCTOR_TIMEOUT = 300.0  # seconds the child `doctor` may take; `board.doctor_seconds` in the policy `task` (1.6.104: 90 was too short for a work computer that took 80 s)
DOCTOR_LIMITS = (30.0, 1800.0)
RETRY_FAILED = 20.0  # a doctor that failed or found errors is run again no sooner than this
REFRESH_CLEAN = 600.0  # a clean doctor is looked at again after this long
FOLDERS_FOR = 10.0  # seconds the optional items are kept
RUNNING_KEEP = 8.0  # seconds the answer "a VS Code runs on this computer" is kept
REASON_MAX = 300
# What the link says (`vslink.status()["why"]`) -> the state of the VS Code line. A host that is still starting, or a connection that dropped, is told as waiting: it comes back by itself.
WAITING = ("starting", "lost", "error")
STUCK = ("off", "no-cli", "cli-failed", "many")  # nothing the person can do by opening VS Code


def short(text: Any) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= REASON_MAX else one[: REASON_MAX - 1] + "…"


def plain(text: Any) -> str:
    """Words of the engine for a person at a page: the marks that are for a terminal are left out."""
    return str(text).replace("`", "")


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
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PATH=shortcmd.fresh_path(), HARNESS_DOCTOR_TOPICS="1")  # what a new terminal sees: the person may have added the short command after the board started
    try:
        done = subprocess.run(command, cwd=str(root), capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"errors": 0, "first": "", "failed": f"no answer in {timeout:g} s"}
    except (OSError, subprocess.SubprocessError) as error:
        return {"errors": 0, "first": "", "failed": short(f"{type(error).__name__}: {error}")}
    text = done.stdout.decode("utf-8", errors="replace")
    errors = [line[len("[ERROR]"):].strip() for line in text.splitlines() if line.startswith("[ERROR]")]
    warnings = [line[len("[WARN]"):].strip() for line in text.splitlines() if line.startswith("[WARN]")]
    company = [line[len("[WARN:company]"):].strip() for line in text.splitlines() if line.startswith("[WARN:company]")]  # about the company's content: they go with the Optional block
    if not errors and done.returncode != 0 and '"errors"' not in text:  # it did not get as far as its summary line
        tail = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return {"errors": 0, "first": "", "failed": short(tail[-1] if tail else f"exit code {done.returncode}")}
    return {"errors": len(errors) if errors else (1 if done.returncode else 0), "first": short(errors[0]) if errors else "", "failed": "", "lines": [short(line) for line in errors[:LINES]], "warned": len(warnings) + len(company), "warning": short((warnings + company)[0]) if warnings or company else "", "company": [short(line) for line in company[:LINES]], "company_n": len(company)}


class Running:
    """Is a VS Code running on this computer, any window or any folder? One `pgrep` or `tasklist` (about a second on a work computer), in a thread of its own and kept for a few seconds,
    so a poll never waits for it. `None` until it has run once."""

    def __init__(self, probe: Optional[Callable[[], bool]] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.probe = probe or launchenv.vscode_running
        self.clock = clock
        self.lock = threading.Lock()
        self.value: Optional[bool] = None
        self.at = -1e9
        self.busy = False

    def get(self) -> Optional[bool]:
        with self.lock:
            if self.busy or self.clock() - self.at < RUNNING_KEEP:
                return self.value
            self.busy = True
        threading.Thread(target=self.look, name="ready-running", daemon=True).start()
        with self.lock:
            return self.value

    def look(self) -> None:
        try:
            found: Optional[bool] = bool(self.probe())
        except Exception:  # noqa: BLE001 - a probe that breaks says nothing
            found = None
        with self.lock:
            self.value, self.at, self.busy = found, self.clock(), False

    def forget(self) -> None:
        """A restart just ended or began: the next `get` looks again."""
        with self.lock:
            self.at = -1e9


class Ready:
    REQUIRED = ("setup", "paired", "doctor", "vscode", "copilot")  # Harness & Local: every one must be ok before Enter (1.7.38)

    def __init__(self, root: Path, link: Any, doctor: Optional[Callable[[Path], Dict[str, Any]]] = None, clock: Callable[[], float] = time.monotonic, checker: Any = None, running: Optional[Running] = None) -> None:
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
        self.optional_kept: Any = None  # (what the items read, when, the answer)
        self.checker = checker or reachcheck.Checker(root)  # the board's own look at the connections (1.7.19)
        self.vs_running = running or Running(clock=clock)  # is any VS Code running on this computer
        self.restart: Any = None  # the board sets it: what a restart of VS Code is doing (`vsrestart.Restart`)

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

    # --- the required checks ---------------------------------------------------------------------------------------

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

    def doctor_notes(self) -> Dict[str, Any]:
        """What `harness doctor` warned of about the company's content, from the kept result: `{n, first}`."""
        with self.lock:
            found = self.found or {}
        return {"n": int(found.get("company_n") or 0), "first": (found.get("company") or [""])[0]}

    # --- the optional items ----------------------------------------------------------------------------------------

    def table(self, systems: Dict[str, Any], raw: List[Dict[str, Any]]) -> Dict[str, Any]:
        """For the hover of the connections row (1.7.19): `names`, a state for each system (ok, down, unknown, partly), and `rows` for the table, one per system and environment.
        The environment of a system that has none (`none`, `any`) is empty."""
        kind = lambda state: "ok" if state == reach.OK else "unknown" if state == reach.UNKNOWN else "down"  # noqa: E731
        names, rows = [], []
        for system in dict.fromkeys(item["system"] for item in raw):
            mine = [item for item in raw if item["system"] == system]
            states = {kind(item["state"]) for item in mine}
            names.append({"name": system, "state": "partly" if len(states) > 1 else next(iter(states))})
            for item in mine:
                why = ""
                if item["state"] == reach.DENIED:
                    why = item.get("launch") or messages.text("desk.reach.why.identity")
                elif item["state"] == reach.FAILED:
                    why = messages.text("desk.reach.why.no-answer") if item.get("why") == "no-answer" else messages.text("desk.reach.why.exit", why=item.get("why", ""))
                elif item["state"] == reach.OK:
                    why = item.get("who", "")
                rows.append({"system": system, "env": "" if item["env"] in ("none", "any") else item["env"], "state": kind(item["state"]), "reason": short(why), "at": item.get("at", ""),
                             "pack": str((systems.get(system) or {}).get("toolpack") or "")})
        return {"names": names, "rows": rows, "checking": self.checker.busy()}

    def connection_facts(self) -> Dict[str, Any]:
        """For the connections row: the table of the hover, whether the company's launch script can start VS Code with an identity (Windows), whether VS Code was started without this computer's settings."""
        systems = config.policy_or_empty(self.root, "tools").get("systems") or {}
        raw = reach.view(self.root, systems) if systems and not outside.validate(systems) else []
        out: Dict[str, Any] = {"rows": self.table(systems, raw)["rows"] if raw else [], "checking": self.checker.busy(), "launch": False, "env_wrong": any(line.get("why") == "vscode-env" for line in raw)}
        out["launch"] = any(line["state"] == reach.DENIED and line.get("why") != "vscode-env" for line in raw) and reach.launch_script(self.root) is not None
        return out

    def optional_mark(self) -> List[Any]:
        """What the items read: the policies, the sign-ins, the answers of the connections, the packs, the skills, the knowledge base. A change shows at once, not after the cache."""
        mark: List[Any] = []
        for path in [*sorted((self.root / ".harness" / "policies").glob("*.json")), self.root / ".harness" / ".env", reach.path(self.root), self.root / ".harness" / "runtime" / "toolpacks.json", self.root / ".harness" / "toolpacks",
                     self.root / ".github" / "skills", self.root / targets.KB_DIR, self.root / ".harness" / "certs"]:
            try:
                mark.append((path.name, path.stat().st_mtime_ns))
            except OSError:
                mark.append((path.name, 0))
        mark.append(("busy", self.checker.busy()))
        return mark

    def optional_made(self) -> Dict[str, Any]:
        listed = readyitems.items(self.root)
        for entry in listed:
            if entry["key"] == "connections":
                try:
                    entry.update(self.connection_facts())
                except Exception:  # noqa: BLE001 - the hover table is a detail
                    entry.update({"rows": [], "checking": False, "launch": False, "env_wrong": False})
        identities = len([one for entry in listed if entry["key"] == "connections" for one in entry["names"] if one.get("saved") and one["state"] == "ok"])
        return {"items": listed, "identities": identities}

    def optional(self) -> Dict[str, Any]:
        """The optional block: `{items, problems, count, kb, identities}`. The items are kept for FOLDERS_FOR and read again at once when what they read changes. The notes of doctor go with the knowledge base."""
        mark = self.optional_mark()
        now = self.clock()
        with self.lock:
            kept = self.optional_kept
            if kept and kept[0] == mark and now - kept[1] < FOLDERS_FOR:
                base = kept[2]
            else:
                base = None
        if base is None:
            try:
                base = self.optional_made()
            except Exception as error:  # noqa: BLE001 - never an error of the request
                base = {"items": [], "identities": 0, "error": short(f"{type(error).__name__}: {error}")}
            with self.lock:
                self.optional_kept = (mark, now, base)
        notes = self.doctor_notes()
        listed = [dict(entry) for entry in base["items"]]
        if notes["n"]:
            for entry in listed:
                if entry["key"] == "kb":
                    problem = {"key": "doctor", "text": messages.text("ready.p.doctor.one" if notes["n"] == 1 else "ready.p.doctor", n=notes["n"]), "why": plain(notes["first"])[:180], "short": messages.text("ready.p.doctor.short.one" if notes["n"] == 1 else "ready.p.doctor.short", n=notes["n"]),
                               "fix": {"to": "term", "run": "harness doctor", "label": messages.text("ready.fix.doctor")}}
                    entry["problems"] = [*entry["problems"], problem]
                    entry["state"] = "yellow"
        problems = readyitems.problems(listed)
        return {"items": listed, "problems": problems, "count": len(problems), "kb": any(entry["key"] == "kb" and entry.get("found") for entry in listed), "identities": base["identities"]}

    # --- VS Code: the button --------------------------------------------------------------------------------------

    def wait_reopen(self) -> None:
        self.drops_then = self.link.drops()
        self.reopen = True

    def still_reopen(self) -> bool:
        """The wait ends when the link was lost once, whichever page is open and however fast VS Code came back."""
        if self.reopen and self.link.drops() != self.drops_then:
            self.reopen = False
        return self.reopen

    def vscode_button(self, vscode: Dict[str, Any], identities: int) -> Dict[str, Any]:
        """The VS Code button of the screen. `open`: no VS Code runs for this copy or at all; `restart`: one runs; `identities`: one runs and some connection has a sign-in saved and a test that passed. `up`: one runs."""
        up = vscode["state"] in ("ok", "wait") or self.vs_running.get() is True
        kind = "identities" if up and identities else "restart" if up else "open"
        return {"kind": kind, "label": messages.text(f"ready.vs.{kind}"), "up": up, "identities": identities}

    # --- the answer -----------------------------------------------------------------------------------------------

    def level(self, line: Dict[str, Any]) -> str:
        """The dot of a required line: ok (green), grey (not known yet), yellow (it comes by itself), red (needs the person)."""
        if line.get("level"):
            return str(line["level"])
        return "ok" if line["state"] == "ok" else "grey" if line["state"] == "check" else "yellow" if line["state"] == "wait" else "red"

    def required_problems(self, checks: List[Dict[str, Any]], button: Dict[str, Any]) -> List[Dict[str, Any]]:
        """What is not ok in the first block, as words for the red block of the board: `{key, level, text, why, fix}`. Copilot waiting for VS Code is not a problem of its own."""
        out: List[Dict[str, Any]] = []
        say = messages.text
        open_fix = {"to": "vscode", "kind": button["kind"], "label": button["label"]}
        for line in checks:
            state, why, key = line["state"], line.get("why", ""), line["id"]
            if state in ("ok", "check"):
                continue
            text, reason, fix = "", "", {}
            if key == "setup":
                text, reason, fix = (say("ready.r.setup.reopen"), say("ready.r.setup.reopen.why"), open_fix) if why == "reopen" else (say("ready.r.setup.new"), say("ready.r.setup.new.why"), {"to": "setup", "sec": "you", "label": say("board.enter.getready")})
            elif key == "paired":
                text, reason = say("ready.r.paired"), say("ready.r.paired.why")
            elif key == "doctor":
                text, reason = (say("ready.r.doctor.failed"), line.get("detail", "")) if why == "failed" else (say("ready.r.doctor.errors.one" if line.get("n") == 1 else "ready.r.doctor.errors", n=line.get("n", "")), line.get("detail", ""))
            elif key == "vscode":
                if state == "wait":
                    text, reason = say("ready.r.vscode.wait"), say(f"board.enter.m.vscode.{why}")
                elif why == "none":
                    text, reason, fix = say("ready.r.vscode.none"), say("ready.r.vscode.none.why"), open_fix
                else:
                    text, reason = say("ready.r.vscode.stuck"), say(f"board.enter.m.vscode.{why}")
            elif key == "copilot":
                if why == "vscode":
                    continue
                text, reason = say("ready.r.copilot"), say(f"board.enter.m.copilot.{why}")
            out.append({"key": key, "level": "red" if state == "fail" else "yellow", "text": plain(text), "why": plain(short(reason)), "fix": fix})
        return out

    def answer(self, paired: bool) -> Dict[str, Any]:
        """`{ready, checks, optional, problems, vscode_button, restart}`. `checks`: the five required lines `{id, group, blocking, level, state, why, ...}`. `state`: ok, wait (it comes by itself), fail (needs the person), check
        (not known yet). `ready`: every required line is ok, and only then Enter is on (1.7.38)."""
        checks: List[Dict[str, Any]] = []

        def add(name: str, make: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
            try:
                line = make()
            except Exception as error:  # noqa: BLE001 - a check that breaks is told as failed, with its reason
                line = {"state": "fail", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
            line = dict(line, id=name, blocking=True, group="required")
            checks.append(line)
            return line

        add("setup", lambda: {"state": "fail", "why": "new"} if not setup_done(self.root) else {"state": "wait", "why": "reopen"} if self.still_reopen() else {"state": "ok", "why": "ok"})
        add("paired", lambda: {"state": "ok", "why": "ok"} if paired else {"state": "fail", "why": "unpaired"})
        add("doctor", self.doctor_line)
        vscode = add("vscode", self.vscode)
        add("copilot", lambda: self.copilot(vscode))
        try:
            self.checker.maybe()  # the board asks the connections itself: the screen need not wait for a chat
        except Exception:  # noqa: BLE001 - a check of the connections that cannot start is not a reason to fail a poll
            pass
        optional = self.optional()
        if vscode["state"] == "ok" and any(entry.get("env_wrong") for entry in optional["items"]):
            vscode["level"] = "yellow"  # opened, but without this computer's settings (1.7.24)
            vscode["env_wrong"] = True
        for line in checks:
            line["level"] = self.level(line)
        button = self.vscode_button(vscode, optional["identities"])
        required = self.required_problems(checks, button)
        out = {"ready": all(line["state"] == "ok" for line in checks), "checks": checks, "optional": optional, "problems": {"required": required, "optional": optional["problems"]}, "vscode_button": button}
        if self.restart is not None:
            out["restart"] = self.restart.view()
        return out
