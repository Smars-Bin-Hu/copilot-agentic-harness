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
import re
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, launchenv, messages, readyitems, shortcmd, targets, tasks
from core import connections as conn_core
from core import reach, systems as outside

from . import reachcheck

LINES = 6  # errors of doctor shown at the end of the setup
DOCTOR_TIMEOUT = 300.0  # seconds the child `doctor` may take; `board.doctor_seconds` in the policy `task` (1.6.104: 90 was too short for a work computer that took 80 s)
DOCTOR_LIMITS = (30.0, 1800.0)
RETRY_FAILED = 20.0  # a doctor that failed or found errors is run again no sooner than this
REFRESH_CLEAN = 600.0  # a clean doctor is looked at again after this long
FOLDERS_FOR = 10.0  # seconds the optional items are kept
RUNNING_KEEP = 8.0  # seconds the answer "a VS Code runs on this computer" is kept
QUIT_QUIET = 180.0  # seconds after a restart began during which a failed one still holds the connection checks back (the quit is waiting for the person)
ENV_KEEP = 10.0  # seconds the answer "was this VS Code started with the settings of this copy" is kept (reading an environment starts a process on macOS)
BUTTON_HOLD = 12.0  # seconds a changed answer of "a VS Code runs" must stand before the button changes its words (1.7.38: helper processes that come and go made it jump between Open and Restart)
REASON_MAX = 300
# What the link says (`vslink.status()["why"]`) -> the state of the VS Code line. A host that is still starting, or a connection that dropped, is told as waiting: it comes back by itself.
WAITING = ("starting", "lost", "error")
STUCK = ("off", "no-cli", "cli-failed", "many")  # nothing the person can do by opening VS Code


def short(text: Any) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= REASON_MAX else one[: REASON_MAX - 1] + "…"


def clip(text: str, size: int) -> str:
    """At most `size` characters, cut at the end of a sentence or between words, never inside a word."""
    if len(text) <= size:
        return text
    head = text[:size]
    end = head.rfind(". ")
    if end >= size // 2:
        return head[:end + 1]
    return head[:head.rfind(" ")].rstrip(" ,;:(") + "…" if " " in head else head[:size - 1] + "…"


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


def crash_words(stderr: str, root: Path) -> str:
    """What a crashed `doctor` says, with where: `modules/gate/pin.py:1: SyntaxError: invalid syntax` (the last file and line of its traceback, from the root, and the last line of it); the last line alone when there is no file."""
    lines = stderr.strip().splitlines()
    if not lines:
        return ""
    found = [re.match(r'\s*File "(.+?)", line (\d+)', line) for line in lines]
    frame = next((item for item in reversed(found) if item), None)
    if frame is None:
        return lines[-1]
    name = frame.group(1)
    try:
        name = Path(name).resolve().relative_to(Path(root).resolve() / ".harness" / "engine").as_posix()
    except (ValueError, OSError):
        pass
    return f"{name}:{frame.group(2)}: {lines[-1]}"


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
    copies = [line[len("[WARN:copies]"):].strip() for line in text.splitlines() if line.startswith("[WARN:copies]")]  # the copies differ: the board counts them itself, with a Sync button (readyitems.sync_item)
    if not errors and done.returncode != 0 and '"errors"' not in text:  # it did not get as far as its summary line
        return {"errors": 0, "first": "", "failed": short(crash_words(done.stderr.decode("utf-8", errors="replace"), root) or f"exit code {done.returncode}")}
    return {"errors": len(errors) if errors else (1 if done.returncode else 0), "first": short(errors[0]) if errors else "", "failed": "", "lines": [short(line) for line in errors[:LINES]], "warned": len(warnings) + len(company) + len(copies), "warning": clip(" ".join((warnings + company + copies)[0].split()), REASON_MAX) if warnings or company or copies else "", "company": [short(line) for line in company[:LINES]], "company_n": len(company)}


def missing_words(missing: List[Any]) -> str:
    """What a VS Code lacks, short: `tool folders runbook/bin, ado/bin; CA bundle` for the words of `launchenv.lacking` (`PATH <folder>`, the name of a trust variable)."""
    folders = [" ".join(str(item).split(" ", 1)[1:]) for item in missing if str(item).startswith("PATH ")]
    short_folders = ["/".join(Path(folder.replace("\\", "/")).parts[-2:]) for folder in folders]
    parts = []
    if short_folders:
        parts.append(f"{messages.text('ready.vs.lacks.folders')} {', '.join(short_folders[:3])}" + (" ..." if len(short_folders) > 3 else ""))
    if any(not str(item).startswith("PATH ") for item in missing):
        parts.append(messages.text("ready.vs.lacks.bundle"))
    return "; ".join(parts)


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
        self.env_kept: Optional[Any] = None  # (mark, at, verdict) of `env_verdict`
        self.reopen = False  # the short command is new: VS Code must be closed and opened again before its terminals have it
        self.root = root
        self.link = link
        self.drops_then = 0  # the losses of the link when the wait began
        self.doctor = doctor or run_doctor
        self.clock = clock
        self.lock = threading.Lock()
        self.found: Optional[Dict[str, Any]] = None  # the kept result of doctor
        self.mark_seen: Optional[str] = None  # the mark of the configuration files when doctor last started (`config_mark`)
        self.at = 0.0
        self.running = False
        self.optional_kept: Any = None  # (what the items read, when, the answer)
        self.checker = checker or reachcheck.Checker(root)  # the board's own look at the connections (1.7.19)
        self.vs_running = running or Running(clock=clock)  # is any VS Code running on this computer
        self.process_held: Optional[Dict[str, Any]] = None  # what the button goes by: the answer of `vs_running`, once it has stood for BUTTON_HOLD
        self.restart: Any = None  # the board sets it: what a restart of VS Code is doing (`vsrestart.Restart`)

    # --- doctor: once, off the request thread ----------------------------------------------------------------------

    CONFIG_FILES = (".harness/policies/*.json", ".harness/registry.json", ".harness/toolpacks/*/toolpack.json", ".harness/toolpacks/*/types/*.json", ".harness/toolpacks/*/rules.json", "knowledge-base/company/tools/*.json",
                    "knowledge-base/company/tools/packs/*/toolpack.json", "knowledge-base/company/tools/packs/*/types/*.json", "knowledge-base/company/tools/packs/*/rules.json")  # the files whose change `doctor` may report (1.7.38, C13 FR 13)

    def config_mark(self) -> str:
        """A short mark of the configuration files (their names, sizes and times): when it changes, what doctor said is old, and the next question runs it again. Two stats for each file; never raises."""
        try:
            parts: List[str] = []
            for pattern in self.CONFIG_FILES:
                for path in sorted(self.root.glob(pattern)):
                    info = path.stat()
                    parts.append(f"{path.relative_to(self.root).as_posix()}:{info.st_size}:{info.st_mtime_ns}")
            return "|".join(parts)
        except Exception:  # noqa: BLE001 - a mark that cannot be made is no mark: the timer decides as before
            return ""

    def start_doctor(self) -> None:
        mark = self.config_mark()
        with self.lock:
            if self.running:
                return
            now = self.clock()
            again = self.found is None or now - self.at >= (REFRESH_CLEAN if not self.found["errors"] and not self.found["failed"] else RETRY_FAILED) or (bool(mark) and mark != self.mark_seen)  # a configuration file changed: ask again now, not in ten minutes
            if not again:
                return
            self.running = True
            self.mark_seen = mark
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

    def env_verdict(self) -> Optional[Dict[str, Any]]:
        """Was the VS Code that is connected started with the settings of this copy (tool folders, CA bundle)? `launchenv.carried`, answered before any chat (1.7.38, Q2): from the environment of the editor's agent host
        where it can be read (macOS, Linux), else from when the board started VS Code and when that process was created (Windows). None when no VS Code is connected. Kept for ENV_KEEP seconds, and read
        again at once when the host, the settings or the records change."""
        pid = getattr(self.link, "host", lambda: None)()
        if not pid:
            return None
        want = launchenv.needs(self.root)
        mark = (str(pid), json.dumps(want, sort_keys=True), json.dumps(launchenv.seen(self.root), sort_keys=True))
        now = self.clock()
        with self.lock:
            kept = self.env_kept
        if kept and kept[0] == mark and now - kept[1] < ENV_KEEP:
            return kept[2]
        verdict = launchenv.carried(self.root, pid)
        with self.lock:
            self.env_kept = (mark, now, verdict)
        return verdict

    def without_settings(self, vscode: Dict[str, Any]) -> None:
        """A connected VS Code that was not started with the settings of this copy is a line that needs the person (1.7.38, Q2): red, it blocks Enter, and the VS Code button is the way out."""
        if vscode["state"] != "ok":
            return
        verdict = self.env_verdict()
        if verdict is None or verdict["state"] == launchenv.FREE:
            return  # nothing connected, or this copy has no settings to carry: any VS Code will do
        vscode.update(env=verdict["state"], by=verdict.get("by", ""))
        if verdict["state"] == launchenv.CARRIED:
            return
        vscode.update(state="fail", why="env" if verdict["state"] == launchenv.MISSING else "unseen", detail=short(missing_words(verdict.get("missing") or [])), open=True, connected=True)  # connected: it runs, so the button restarts it

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
        try:
            from core import toolpacks

            clash = toolpacks.clash_lines(self.root)  # 1.7.38 (C11 T2-09): a company pack with the name of a factory pack is an error of `doctor`; the kept clean answer is older than the file, so it is looked at here (two folder listings)
        except Exception:  # noqa: BLE001 - a look at two folders must not break the line
            clash = []
        if clash:
            return {"state": "fail", "why": "errors", "n": len(clash), "detail": short(clash[0])}
        try:  # 1.7.38 (C13 FR 17a): a guardrail file that is not what the person accepted is an error of doctor too, and the hook refuses commands and writes meanwhile: the screen says so at once, not when doctor runs again
            import integrity

            changed = integrity.changes(self.root)
            listed = integrity.read(self.root) if changed else None
        except Exception:  # noqa: BLE001
            changed, listed = [], None
        if changed:
            was, now = str((listed or {}).get("harness") or ""), integrity._registry_version(self.root)  # noqa: SLF001
            files = ", ".join(changed[: integrity.SHOWN])
            words = messages.text("doctor.integrity.upgrade.board", n=len(changed), files=files, was=was, now=now) if was != now else messages.text("doctor.integrity.changed.board", n=len(changed), files=files)  # no command text on a page (FR2 8)
            return {"state": "fail", "why": "errors", "n": len(changed), "detail": short(words)}
        return {"state": "ok", "why": "ok", "n": 0}

    def drop_doctor(self) -> None:
        """What doctor said is old (a sync was done): the next question runs it again."""
        with self.lock:
            self.at = -1e9

    def drop_optional(self) -> None:
        """What the optional items said is old (a sync was done, F3 FB1-b): the next question reads them again at once, so a yellow note that a sync mended is gone on the poll that follows it, not when the kept answer runs out."""
        with self.lock:
            self.optional_kept = None

    def doctor_notes(self) -> Dict[str, Any]:
        """What `harness doctor` warned of about the company's content, from the kept result: `{n, first}`."""
        with self.lock:
            found = self.found or {}
        return {"n": int(found.get("company_n") or 0), "first": (found.get("company") or [""])[0]}

    # --- the optional items ----------------------------------------------------------------------------------------

    def identity_lacks(self) -> List[str]:
        """(1.7.38, C13 D3-3) The connections whose identity a VS Code that is connected now was not started with (`core.connections.identity_lacks`); none while no VS Code is connected. Never raises."""
        try:
            return conn_core.identity_lacks(self.root) if self.vscode().get("state") == "ok" else []
        except Exception:  # noqa: BLE001 - a note must not break the screen
            return []

    def table(self, systems: Dict[str, Any], raw: List[Dict[str, Any]]) -> Dict[str, Any]:
        """For the hover of the connections row (1.7.19): `names`, a state for each system (ok, down, unknown, partly), and `rows` for the table, one per system and environment.
        The environment of a system that has none (`none`, `any`) is empty."""
        kind = lambda state: "ok" if state == reach.OK else "unknown" if state == reach.UNKNOWN else "down"  # noqa: E731
        names, rows = [], []
        order = {"dev": 0, "ist": 1, "qat": 2, "prod": 3}
        pack_of = lambda system: str((systems.get(system) or {}).get("toolpack") or "")  # noqa: E731
        first_env = lambda system: min(order.get(item["env"], -1) for item in raw if item["system"] == system)  # noqa: E731
        try:
            listed, kinds = conn_core.listed(self.root), conn_core.types(self.root)
        except Exception:  # noqa: BLE001 - a broken list is doctor's to report; the table then keeps the order of the packs
            listed, kinds = {}, {}
        try:
            loose = set(conn_core.unsigned(self.root)) | {one["name"] for one in readyitems.connection_states(self.root) if one["state"] == "none"}  # a connection with no sign-in kept here: its row says so, as the name with its dot did (C12 N7), and the yellow line counts the same ones (RC-1)
        except Exception:  # noqa: BLE001 - see above
            loose = set()
        try:
            held = readyitems.held_by_fault(self.root)  # 1.7.38 (F3): the pack that brings their type has a faulty file, so the gate holds their calls: a yellow row with the file, whatever the sign-in or the last test says
        except Exception:  # noqa: BLE001 - see above
            held = {}
        lacks = set(self.identity_lacks())  # 1.7.38 (C13 D3-3): VS Code was not started with the identity of these: a yellow note on the row of the connection
        label_of = lambda system: str((kinds.get(str((listed.get(system) or {}).get("type") or "")) or {}).get("label") or "").casefold()  # noqa: E731
        # The order of the Connections window: by the label of the kind, then environment, then name (`servers.js`); the table was ordered by the name of the pack, so the two lists differed (C12 N6)
        raw = sorted(raw, key=lambda item: (not label_of(item["system"]), label_of(item["system"]), not pack_of(item["system"]), pack_of(item["system"]), first_env(item["system"]), item["system"], order.get(item["env"], -1)))
        for system in dict.fromkeys(item["system"] for item in raw):
            mine = [item for item in raw if item["system"] == system]
            for item in mine:
                why = ""
                if system in held:
                    rows.append({"system": system, "env": "" if item["env"] in ("none", "any") else item["env"], "state": "held", "reason": short(messages.text("board.enter.sys.held.reason", fault=held[system])), "at": "", "pack": pack_of(system)})
                    continue
                if item.get("why") == "vscode-env":  # VS Code was started without the settings of this copy: its answer says nothing of this connection. The row keeps its own state, and the table says why once, at its foot (RC-1)
                    item = dict(item, state=reach.UNKNOWN if system in loose else reach.FAILED)
                    why = messages.text("board.enter.cs.none") if system in loose else ""
                elif item["state"] == reach.DENIED:
                    why = item.get("launch") or messages.text("desk.reach.why.identity")
                elif item["state"] == reach.FAILED:
                    why = reach.failed_words(item)
                elif item["state"] == reach.OK:
                    why = item.get("who", "")
                elif system in loose:
                    why = messages.text("board.enter.cs.none")
                rows.append({"system": system, "env": "" if item["env"] in ("none", "any") else item["env"], "state": kind(item["state"]), "reason": short(why), "at": item.get("at", ""),
                             "pack": str((systems.get(system) or {}).get("toolpack") or ""), **({"note": messages.text("board.enter.sys.identity" if conn_core.window_known(self.root) else "board.enter.sys.identity.unknown")} if system in lacks else {})})
            states = {row["state"] for row in rows if row["system"] == system}
            names.append({"name": system, "state": "partly" if len(states) > 1 else next(iter(states))})
        for system in held:  # a held connection that has no line of its own in the checks (its pack's rules are not read) still has its row
            if not any(row["system"] == system for row in rows):
                rows.append({"system": system, "env": "" if str((listed.get(system) or {}).get("env") or "") in ("none", "any") else str((listed.get(system) or {}).get("env") or ""), "state": "held",
                             "reason": short(messages.text("board.enter.sys.held.reason", fault=held[system])), "at": "", "pack": ""})
                names.append({"name": system, "state": "held"})
        return {"names": names, "rows": rows, "checking": self.checker.busy()}

    def connection_facts(self) -> Dict[str, Any]:
        """For the connections row: the table of the hover, whether the company's launch script can start VS Code with an identity (Windows), whether VS Code was started without this computer's settings."""
        systems = config.policy_or_empty(self.root, "tools").get("systems") or {}
        raw = reach.view(self.root, systems) if systems and not outside.validate(systems) else []
        off = set(readyitems.connections_off(self.root))  # their tool pack is off: not in the table, the row says how many more there are (1.7.38)
        raw = [line for line in raw if line["system"] not in off]
        out: Dict[str, Any] = {"rows": self.table(systems, raw)["rows"] if raw else [], "checking": self.checker.busy(), "launch": False, "env_wrong": any(line.get("why") == "vscode-env" for line in raw)}
        out["launch"] = any(line["state"] == reach.DENIED and line.get("why") != "vscode-env" for line in raw) and reach.launch_script(self.root) is not None
        return out

    def optional_mark(self) -> List[Any]:
        """What the items read: the policies, the sign-ins, the answers of the connections, the packs, the skills, the knowledge base. A change shows at once, not after the cache."""
        mark: List[Any] = []
        for path in [*sorted((self.root / ".harness" / "policies").glob("*.json")), self.root / ".harness" / ".env", reach.path(self.root), self.root / ".harness" / "runtime" / "toolpacks.json", self.root / ".harness" / "toolpacks",
                     self.root / ".github" / "skills", self.root / ".github" / "instructions", *sorted((self.root / ".github" / "instructions").glob("*.md")), self.root / targets.KB_DIR, self.root / ".harness" / "certs"]:
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
                    problem = {"key": "doctor", "text": messages.text("ready.p.doctor.one" if notes["n"] == 1 else "ready.p.doctor", n=notes["n"]), "why": clip(plain(notes["first"]), 180), "short": messages.text("ready.p.doctor.short.one" if notes["n"] == 1 else "ready.p.doctor.short", n=notes["n"]),
                               "fix": {"to": "term", "run": "harness doctor", "label": messages.text("ready.fix.doctor")}}
                    entry["problems"] = [*entry["problems"], problem]
                    entry["state"] = "yellow"
        lacks = self.identity_lacks()
        if lacks:  # not in Required: a yellow note on the connections row (1.7.38, C13 D3-3)
            for entry in listed:
                if entry["key"] == "connections":
                    entry["problems"] = [*entry["problems"], readyitems.identity_problem(lacks, conn_core.window_known(self.root))]
                    entry["state"] = "yellow" if entry.get("state") != "red" else "red"
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

    def process_up(self) -> bool:
        """Does a VS Code run on this computer, as the button should believe it: a new answer counts after it has stood for BUTTON_HOLD seconds, so a process that comes and goes
        does not change the words of the button back and forth. Not known yet (no probe has answered): the last belief, else no."""
        raw = self.vs_running.get()
        now = self.clock()
        with self.lock:
            held = self.process_held
            if raw is None:
                return bool(held and held["shown"])
            if held is None:
                self.process_held = {"shown": raw, "raw": raw, "since": now}
                return raw
            if raw != held["raw"]:
                held["raw"], held["since"] = raw, now
            if raw != held["shown"] and now - held["since"] >= BUTTON_HOLD:
                held["shown"] = raw
            return bool(held["shown"])

    def quitting(self) -> bool:
        """A restart of VS Code is going on, or ended a moment ago with VS Code still not quit: a check of the connections now would find a VS Code half gone and tell a false problem ("1 does not answer"). It waits."""
        if self.restart is None:
            return False
        view = self.restart.view()
        return view["state"] in ("quitting", "opening") or (view["state"] == "failed" and 0 < view["since"] < QUIT_QUIET)

    def vscode_button(self, vscode: Dict[str, Any], identities: int) -> Dict[str, Any]:
        """The VS Code button of the screen. `open`: no VS Code runs for this copy or at all; `restart`: one runs; `identities`: one runs and some connection has a sign-in saved and a test that passed. `up`: one runs."""
        up = vscode["state"] in ("ok", "wait") or bool(vscode.get("connected")) or self.process_up()
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
                elif why in ("env", "unseen"):  # connected, but not started with this copy's settings (Q2): the VS Code button restarts it
                    text, reason, fix = say("ready.r.vscode.env" if why == "env" else "ready.r.vscode.unseen"), say("ready.r.vscode.env.why"), open_fix
                elif why == "none":
                    text, reason, fix = say("ready.r.vscode.none"), say("ready.r.vscode.none.why"), open_fix
                else:
                    text, reason = say("ready.r.vscode.stuck"), say(f"board.enter.m.vscode.{why}")
            elif key == "copilot":
                if why == "vscode":
                    continue
                text, reason = say("ready.r.copilot"), say(f"board.enter.m.copilot.{why}")
            out.append({"key": key, "level": "red" if state == "fail" else "yellow", "code": why, "text": plain(text), "why": plain(short(reason)), "fix": fix})
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
        add("copilot", lambda: self.copilot(vscode))  # Copilot is judged by the connection, before the settings are
        try:
            self.without_settings(vscode)
        except Exception:  # noqa: BLE001 - a check of the settings that breaks leaves the line as the connection says
            pass
        try:
            if not self.quitting():
                self.checker.maybe()  # the board asks the connections itself: the screen need not wait for a chat
        except Exception:  # noqa: BLE001 - a check of the connections that cannot start is not a reason to fail a poll
            pass
        optional = self.optional()
        if vscode["state"] == "ok" and vscode.get("env") != launchenv.CARRIED and any(entry.get("env_wrong") for entry in optional["items"]):  # a hook's old word does not count against a VS Code the board saw carry the settings
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
