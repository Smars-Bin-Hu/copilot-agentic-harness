"""What the Enter screen of the board asks (`/api/ready`, 1.6 B86): is everything the board needs in place? One line for each check, as data; the page says it in words.

Two blocks (1.7.38, block B).
- REQUIRED, Harness & Local: this copy is set up, this browser is paired, `harness doctor` has no error, VS Code is open for this copy, Copilot is connected. Every line must be ok before Enter is on:
  without one the harness cannot work here. They are `checks`, each with `group: "required"` and `blocking: true`, and a `level` for its dot: ok, grey, yellow, red.
- OPTIONAL, from the company: knowledge base, instructions, company skills, code standards, tool packs, connections, code repositories (`core/readyitems.py`). They never block. `optional` holds the items and the
  `problems` to look at; each problem has the place that mends it.
`problems.required` is what is not ok in the first block (the red block of the board after Enter), and `action` is the button beside Enter: the fix of the VS Code or Copilot line (H6: the board runs its own
agent host, so VS Code only has to be installed).

Nothing here waits on the outside world, so the server never hangs on it:
- VS Code and Copilot are read from the cache of the link thread (`vslink`) and of the board's own agent host (`core.agenthost`), which own every `code` and `gh` command and its timeout.
- `harness doctor` takes about a second (a minute and more on a slow work computer): it runs once in a thread of its own, in a child process with a deadline (`board.doctor_seconds`), and its result is kept. A board started from a terminal starts it at once, before a page asks (1.6.104). It is run again only
  when it failed or found an error (and not sooner than RETRY_FAILED), or very late when it was clean. A poll only reads the kept result.
- The optional items are file listings, kept for a few seconds, and again at once when a policy, the sign-ins or the packs change.
A check that goes wrong itself is a line that failed with its reason, never an error of the request.
"""

from __future__ import annotations

import json
import re
import shutil
import os
import subprocess
import sys
import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import config, ghauth, launchenv, messages, pace, readyitems, shortcmd, targets, tasks
from core import connections as conn_core
from core import reach, systems as outside

from . import reachcheck
from core import procrun

LINES = 6  # errors of doctor shown at the end of the setup
DOCTOR_TIMEOUT = 300.0  # seconds the child `doctor` may take; `board.doctor_seconds` in the policy `task` (1.6.104: 90 was too short for a work computer that took 80 s)
DOCTOR_LIMITS = (30.0, 1800.0)
RETRY_FAILED = (60.0, 120.0, 300.0, 600.0)  # 1.7.45: a doctor that failed or found errors is run again after 1, 2, 5, then every 10 minutes (it was every 20 s: on a busy work computer doctor ran without a stop); Check again, or a changed configuration file, runs it at once
RETRY_TIMEOUT = 600.0  # a doctor that gave no answer in time is run again after 10 minutes, not sooner: the computer was busy
REFRESH_CLEAN = 600.0  # a clean doctor is looked at again after this long
FOLDERS_FOR = 10.0  # seconds the optional items are kept
REASON_MAX = 300
FRESH_FOR = 20.0  # 1.8.13: seconds after the page's last question that the answer is still worked out
KEEP_EVERY = 2.0  # 1.8.13: the pause between two answers worked out
FIRST_WAIT = 5.0  # 1.8.13: how long the first question waits for the first answer
GH_KEEP = 20.0  # 1.8.x: seconds what gh said (found, signed in, as whom) is kept; a sign-in that ends, or a folder given, asks again at once
MODELS_GRACE = 30.0  # 1.8.x: seconds after gh's token was handed in which "no model yet" is still waiting; after that the host refused it
VSCODE_PAGE = "https://code.visualstudio.com/"
SLOW_ANSWER = 3.0  # 1.8.13: an answer that took longer is written to the board's log, with the time of each part


EFFECTS = {"kb": "ready.effect.kb", "instructions": "ready.effect.instructions", "skills": "ready.effect.skills", "standards": "ready.effect.standards", "packs": "ready.effect.packs", "connections": "ready.effect.connections", "repos": "ready.effect.repos"}  # what is lost while an item is not set up (O1)
NOTES = {"kb": "ready.note.kb", "instructions": "ready.note.instructions", "skills": "ready.note.skills", "standards": "ready.note.standards", "packs": "ready.note.packs", "connections": "ready.note.connections", "repos": "ready.note.repos"}  # the words of its dot on the gear
BUTTONS = {"pair": "ready.btn.pair", "setup": "ready.btn.setup", "program": "ready.btn.program", "doctor": "ready.btn.doctor", "signin": "ready.btn.signin", "signing": "ready.btn.signing", "preparing": "ready.btn.preparing", "restart-host": "ready.btn.restart-host",
           "wait": "ready.btn.wait", "check": "ready.btn.check", "enter": "ready.btn.enter"}  # the label of each kind of the middle button
PROGRAM_PAGES = {"vscode": "https://code.visualstudio.com/download", "gh": ghauth.DOWNLOAD_PAGE}


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
    """Is this copy set up? `setup_done` in the person's file: yes. `setup_wizard` set and no `setup_done`: the wizard is under way, not yet. Neither, but a repository setting or tasks: an older copy, its owner is not asked
    again. Nothing at all: a new copy, which goes to the wizard (O1)."""
    try:
        kept = json.loads(config.override_path(root, "user").read_text(encoding="utf-8-sig"))
        if isinstance(kept, dict):
            if kept.get("setup_done"):
                return True
            if kept.get("setup_wizard"):
                return False
    except (OSError, ValueError):
        pass
    return config.override_path(root, "target").exists() or bool(tasks.folders(root))


def doctor_seconds(root: Path) -> float:
    """The deadline of the child `doctor`: `board.doctor_seconds` of the policy `task` (DOCTOR_TIMEOUT when it is not set or not a number), times the pace factor,
    kept between DOCTOR_LIMITS. 1.8.15: the value is scaled too, as `git_timeout_seconds` is: the shipped policy sets 300, written for a quick computer."""
    value = (config.policy_or_empty(root, "task").get("board") or {}).get("doctor_seconds")
    base = DOCTOR_TIMEOUT if isinstance(value, bool) or not isinstance(value, (int, float)) else float(value)
    return min(max(pace.scaled(base), DOCTOR_LIMITS[0]), DOCTOR_LIMITS[1])


def crash_words(stderr: str, root: Path) -> str:
    """What a crashed `doctor` says, with where: `modules/gate/pin.py:1: SyntaxError: invalid syntax` (the last file and line of its traceback, from the root, and the last line of it); the last line alone when there is no file."""
    lines = stderr.strip().splitlines()
    if not lines:
        return ""
    for line in lines:  # `cli.py` already says it in one sentence when the engine cannot load (the file, the line and the fault)
        if line.startswith("harness: the engine cannot load: "):
            return line[len("harness: the engine cannot load: "):]
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


class _Done:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_with_steps(command: List[str], root: Path, env: Dict[str, str], flags: int, timeout: float, progress: Callable[[int, int, str], None]) -> _Done:
    """The child `doctor`, its stderr read line by line while it runs: a line `doctor.PROGRESS_MARK <done>/<total> <step>` goes to `progress`, the rest is kept as its stderr (1.7.43)."""
    child = subprocess.Popen(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, creationflags=flags, **({} if os.name == "nt" else {"start_new_session": True}))  # its own group: at the deadline doctor and what it started end together (1.7.45)
    out: List[bytes] = []
    err: List[bytes] = []

    def read_err() -> None:
        for raw in iter(child.stderr.readline, b""):  # type: ignore[union-attr]
            words = raw.decode("utf-8", errors="replace").split(None, 2)
            if len(words) >= 2 and words[0] == PROGRESS_MARK and "/" in words[1]:
                done, _, total = words[1].partition("/")
                try:
                    progress(int(done), int(total), words[2].strip() if len(words) > 2 else "")
                except (ValueError, Exception):  # noqa: BLE001 - a progress line is a helper: never a reason to fail doctor
                    pass
                continue
            err.append(raw)

    readers = [threading.Thread(target=read_err, daemon=True), threading.Thread(target=lambda: out.append(child.stdout.read()), daemon=True)]  # type: ignore[union-attr]
    for reader in readers:
        reader.start()
    try:
        code = child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        procrun.end_tree(child)  # 1.7.45: not doctor alone; a probe it started (sqlcmd, az, git) would stay and keep the computer busy
        child.wait()
        raise
    for reader in readers:
        reader.join(5)
    for pipe in (child.stdout, child.stderr):
        if pipe is not None:
            pipe.close()
    return _Done(code, b"".join(out), b"".join(err))


PROGRESS_MARK = "harness-doctor-step"  # the line `doctor` writes on stderr at each step when HARNESS_DOCTOR_PROGRESS is set (1.7.43): the same word as doctor.PROGRESS_MARK


def run_doctor(root: Path, timeout: Optional[float] = None, progress: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
    """`doctor` in a child process: `{errors, first, failed}`. `failed`: why it could not be run or read (empty when it ran). Never raises.
    `progress(done, total, step)` (1.7.43): called at each step while it runs, for the Enter screen's bar: on a work computer it takes a minute or more."""
    timeout = doctor_seconds(root) if timeout is None else timeout
    command = [sys.executable, str(root / ".harness" / "engine" / "cli.py"), "doctor"]
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)) if os.name == "nt" else 0  # 1.7.45: below normal, and what it starts too: VS Code and Copilot come first
    if os.name != "nt" and shutil.which("nice"):
        command = ["nice", "-n", "10", *command]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PATH=shortcmd.fresh_path(), HARNESS_DOCTOR_TOPICS="1")  # what a new terminal sees: the person may have added the short command after the board started
    try:
        if progress is not None:
            env["HARNESS_DOCTOR_PROGRESS"] = "1"
            done: Any = _run_with_steps(command, root, env, flags, timeout, progress)
        else:
            done = procrun.run(command, cwd=str(root), capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"errors": 0, "first": "", "failed": f"no answer in {timeout:g} s", "timeout": timeout}
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


class Ready:
    REQUIRED = ("setup", "paired", "doctor", "vscode", "copilot")  # Harness & Local: every one must be ok before Enter (1.7.38)

    def __init__(self, root: Path, link: Any, doctor: Optional[Callable[[Path], Dict[str, Any]]] = None, clock: Callable[[], float] = time.monotonic, checker: Any = None) -> None:
        self.root = root
        self.link = link
        self.doctor = doctor or run_doctor
        self.clock = clock
        self.lock = threading.Lock()
        self.found: Optional[Dict[str, Any]] = None  # the kept result of doctor
        self.steps: Dict[str, Any] = {}  # where the doctor that runs is: done, total, step, began (1.7.43)
        self.mark_seen: Optional[str] = None  # the mark of the configuration files when doctor last started (`config_mark`)
        self.misses = 0  # doctor runs in a row that failed or found errors: the wait before the next one grows (RETRY_FAILED)
        self.at = 0.0
        self.running = False
        self.started = ""  # 1.8.23: the release number this board process started with (the board sets it); "" in a test without a board
        self.kept: Optional[Dict[str, Any]] = None  # 1.8.13: the last answer of `keep_fresh`
        self.asked_at = -1e9
        self.worker: Optional[threading.Thread] = None
        self.first = threading.Event()
        self.took: Dict[str, float] = {}
        self.asked_again = False  # 1.8.13: the running doctor was asked for by Check again: its line shows the bar, not the old answer
        self.optional_kept: Any = None  # (what the items read, when, the answer)
        self.checker = checker or reachcheck.Checker(root)  # the board's own look at the connections (1.7.19)
        self.gh_kept: Optional[Any] = None  # 1.8.x: (what `ghauth.check` said, when, the sign-in state then)

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
            again = self.found is None or now - self.at >= self.next_wait() or (bool(mark) and mark != self.mark_seen)  # a configuration file changed: ask again now, not in ten minutes
            if not again:
                return
            self.running = True
            self.mark_seen = mark
        threading.Thread(target=self.run_doctor, name="ready-doctor", daemon=True).start()

    def next_wait(self) -> float:
        """Seconds after the last doctor before the next (1.7.45): 10 minutes when it was clean, or gave no answer in time; else 1, 2, 5, then 10 minutes as it keeps failing."""
        found = self.found or {}
        if not found.get("errors") and not found.get("failed"):
            return REFRESH_CLEAN
        if found.get("timeout"):
            return pace.scaled(RETRY_TIMEOUT)
        return RETRY_FAILED[min(max(self.misses, 1), len(RETRY_FAILED)) - 1]

    def note_step(self, done: int, total: int, step: str) -> None:
        with self.lock:
            self.steps = {"done": max(0, min(done, total)), "total": max(total, 0), "step": step[:60], "began": self.steps.get("began", self.clock())}

    def doctor_progress(self) -> Dict[str, Any]:
        """While the first doctor runs (1.7.43): `{progress: {done, total, step, seconds}}` for the Enter screen's bar; `total` 0 before its first step is told."""
        with self.lock:
            steps = dict(self.steps)
        if not steps:
            return {}
        return {"progress": {"done": steps.get("done", 0), "total": steps.get("total", 0), "step": steps.get("step", ""), "seconds": int(max(0.0, self.clock() - steps.get("began", self.clock())))}}

    def run_doctor(self) -> None:
        with self.lock:
            self.steps = {"done": 0, "total": 0, "step": "", "began": self.clock()}
        try:
            found = self.doctor(self.root, progress=self.note_step) if self.doctor is run_doctor else self.doctor(self.root)  # a doctor given by a test takes the root only
        except Exception as error:  # noqa: BLE001 - a doctor that breaks is a line that failed, not a dead thread
            found = {"errors": 0, "first": "", "failed": short(f"{type(error).__name__}: {error}")}
        with self.lock:
            if found.get("timeout"):  # 1.7.45: where it stopped, and when it is tried again
                step = str(self.steps.get("step") or "") or "-"
                found = dict(found, failed=messages.text("ready.doctor.timeout", seconds=f"{found['timeout']:g}", step=step))
            self.misses = self.misses + 1 if found.get("errors") or found.get("failed") else 0
            self.found, self.at, self.running, self.asked_again = found, self.clock(), False, False

    # --- the required checks ---------------------------------------------------------------------------------------

    def vscode(self) -> Dict[str, Any]:
        """1.8.x: VS Code is installed (the board starts its agent host from it); it never has to be open."""
        found = self.link.installed()
        if not found["found"]:
            return {"state": "fail", "why": "off" if found.get("off") else "no-code", "download": VSCODE_PAGE}
        return {"state": "ok", "why": "ok", "version": found.get("version", "")}

    def gh_state(self, login: Dict[str, Any]) -> Dict[str, Any]:
        """What gh says (`ghauth.check`), kept GH_KEEP seconds; asked again at once when the sign-in the page started changed its state. Runs gh twice: on the answer's thread, never a request's."""
        now = self.clock()
        with self.lock:
            kept = self.gh_kept
        if kept and now - kept[1] < GH_KEEP and kept[2] == login.get("state"):
            return kept[0]
        found = ghauth.check(self.root, launchenv.extra(self.root))
        with self.lock:
            self.gh_kept = (found, now, login.get("state"))
        return found

    def forget_gh(self) -> None:
        with self.lock:
            self.gh_kept = None

    def copilot(self, vscode: Dict[str, Any]) -> Dict[str, Any]:
        """1.8.x: "Copilot signed in (gh)". Three things: gh is found, gh is signed in, the host has models once it got gh's token. `host` rides along while the agent host
        is being prepared (the download of a first start), whatever the rest says, so the page can show its progress beside a sign-in."""
        if vscode["state"] != "ok":
            return {"state": "wait", "why": "vscode"}
        host = self.link.host_state()
        login = self.link.login_state()
        line = self.copilot_line(host, login)
        if host.get("state") in ("starting", "preparing"):
            line["host"] = {key: host.get(key) for key in ("state", "seconds", "downloaded_mb", "total_mb", "percent") if host.get(key) is not None}
        return line

    def copilot_line(self, host: Dict[str, Any], login: Dict[str, Any]) -> Dict[str, Any]:
        if login.get("state") in ("starting", "waiting"):
            return {"state": "wait", "why": "signing-in", "code": login.get("code", ""), "url": login.get("url", ""), "left": login.get("left"), "waited": login.get("waited")}
        gh = self.gh_state(login)
        if gh["why"] == "no-gh":
            return {"state": "fail", "why": "no-gh", "download": ghauth.DOWNLOAD_PAGE}
        if gh["why"] in ("cannot-run", "slow"):
            return {"state": "fail", "why": "gh-broken", "detail": gh["why"], "gh": gh["gh"]}
        if not gh["signed_in"]:
            out: Dict[str, Any] = {"state": "fail", "why": "signin", "gh": gh["gh"], "gh_version": gh["version"]}
            if login.get("state") in ("failed", "expired", "cancelled"):
                out.update(last=login["state"], detail=short(login.get("why", "")))  # how the sign-in the page started ended
            return out
        about = {"login": gh["login"], "gh": gh["gh"], "gh_version": gh["version"], "host_version": host.get("version", ""), "host_seconds": host.get("seconds"), "host_starts": host.get("starts")}
        state = host.get("state")
        if state in ("stopped", "starting"):
            return {"state": "wait", "why": "host-starting", **about}
        if state == "preparing":
            return {"state": "wait", "why": "host-preparing", **about}
        if state == "failed":
            return {"state": "fail", "why": "host-failed", "detail": short(host.get("why", "")), **about}
        if state in ("no-code", "off"):
            return {"state": "wait", "why": "vscode"}
        if not self.link.status().get("ready"):
            return {"state": "wait", "why": "connecting", **about}
        models = int(self.link.copilot().get("models") or 0)
        if models:
            return {"state": "ok", "why": "ok", "n": models, **about}
        handed = self.link.signin_state()
        if handed.get("state") == "refused" or (handed.get("state") == "handed" and (handed.get("ago") or 0) >= MODELS_GRACE):
            return {"state": "fail", "why": "refused", **about}
        if handed.get("state") in ("no-gh", "not-signed-in", "cannot-run", "slow"):  # gh is signed in now, but was not when the host was opened: hand it now
            self.link.sign_in_again()
        return {"state": "wait", "why": "models", **about}

    def stale(self) -> Optional[Dict[str, str]]:
        """1.8.23: the release this board process started with, when the folder now holds another one (`{started, now}`), else None. The board runs in the background
        since 1.8.11, so an update of the folder no longer meets a start of the board: the guardrail files of the new release stay unaccepted (the hook refuses the agent's
        commands meanwhile) and the old code serves new pages. A restart of the board accepts them (`integrity.accept_on_start`)."""
        if not self.started:
            return None
        try:
            from core import registry

            now = str(registry.harness_version(self.root) or "")
        except Exception:  # noqa: BLE001 - a registry that cannot be read is doctor's to report
            return None
        return {"started": self.started, "now": now} if now and now != self.started else None

    def doctor_line(self) -> Dict[str, Any]:
        old = self.stale()
        if old:  # before anything doctor says: its errors after an update are this
            return {"state": "fail", "why": "stale", **old}
        self.start_doctor()
        with self.lock:
            found, again = self.found, self.running and self.found is not None and self.asked_again
        if found is None or again:  # 1.8.13: Check again shows the bar too; before, the old answer stayed until the new one came, so the press seemed to do nothing
            return {"state": "check", "why": "running", **self.doctor_progress()}
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
            return {"state": "fail", "why": "errors", "n": len(changed), "detail": short(words), "integrity": len(changed)}  # the row has a button that accepts them (1.7.39)
        return {"state": "ok", "why": "ok", "n": 0}

    def drop_doctor(self) -> None:
        """What doctor said is old (a sync was done, or the person pressed Check again): the next question runs it again."""
        with self.lock:
            self.at = -1e9

    def doctor_again(self) -> bool:
        """Check again, pressed by the person (1.7.45): doctor runs now, not when its wait is over. False when one runs already."""
        with self.lock:
            busy = self.running
        if busy:
            return False
        self.drop_doctor()
        with self.lock:
            self.asked_again = True
        self.start_doctor()
        return True

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
        """(H6) The connections whose saved identity the agent host does not hold: it holds another Windows account (`core.connections.identity_lacks`). Never raises."""
        try:
            return conn_core.identity_lacks(self.root)
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
        lacks = set(self.identity_lacks())  # H6: the agent host holds another Windows account: a yellow note on the row of the connection
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
                if item["state"] == reach.DENIED:
                    why = item.get("launch") or messages.text("desk.reach.why.identity")
                elif item["state"] == reach.FAILED:
                    why = reach.failed_words(item)
                elif item["state"] == reach.OK:
                    why = item.get("who", "")
                elif system in loose:
                    why = messages.text("board.enter.cs.none")
                rows.append({"system": system, "env": "" if item["env"] in ("none", "any") else item["env"], "state": kind(item["state"]), "reason": short(why), "at": item.get("at", ""),
                             "pack": str((systems.get(system) or {}).get("toolpack") or ""), **({"note": messages.text("board.enter.sys.identity")} if system in lacks else {})})
            states = {row["state"] for row in rows if row["system"] == system}
            names.append({"name": system, "state": "partly" if len(states) > 1 else next(iter(states))})
        for system in held:  # a held connection that has no line of its own in the checks (its pack's rules are not read) still has its row
            if not any(row["system"] == system for row in rows):
                rows.append({"system": system, "env": "" if str((listed.get(system) or {}).get("env") or "") in ("none", "any") else str((listed.get(system) or {}).get("env") or ""), "state": "held",
                             "reason": short(messages.text("board.enter.sys.held.reason", fault=held[system])), "at": "", "pack": ""})
                names.append({"name": system, "state": "held"})
        return {"names": names, "rows": rows, "checking": self.checker.busy()}

    def connection_facts(self) -> Dict[str, Any]:
        """For the connections row: the table of the hover."""
        systems = config.policy_or_empty(self.root, "tools").get("systems") or {}
        raw = reach.view(self.root, systems) if systems and not outside.validate(systems) else []
        off = set(readyitems.connections_off(self.root))  # their tool pack is off: not in the table, the row says how many more there are (1.7.38)
        raw = [line for line in raw if line["system"] not in off]
        return {"rows": self.table(systems, raw)["rows"] if raw else [], "checking": self.checker.busy()}

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
                    entry.update({"rows": [], "checking": False})
        return {"items": listed}

    def optional(self) -> Dict[str, Any]:
        """The optional block: `{items, problems, count, kb}`. The items are kept for FOLDERS_FOR and read again at once when what they read changes. The notes of doctor go with the knowledge base."""
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
                base = {"items": [], "error": short(f"{type(error).__name__}: {error}")}
            with self.lock:
                self.optional_kept = (mark, now, base)
        notes = self.doctor_notes()
        listed = [dict(entry) for entry in base["items"]]
        gaps = [entry for entry in listed if entry["state"] in ("yellow", "red")]  # before the notes of doctor and the identities colour a row: those are not a thing left to set up
        for entry in listed:
            entry["kind"] = "setup"
            if entry["state"] != "ok":
                entry["effect"] = messages.text(EFFECTS[entry["key"]]) if entry["key"] in EFFECTS else ""
        if notes["n"]:
            for entry in listed:
                if entry["key"] == "kb":
                    problem = {"key": "doctor", "text": messages.text("ready.p.doctor.one" if notes["n"] == 1 else "ready.p.doctor", n=notes["n"]), "why": clip(plain(notes["first"]), 180), "short": messages.text("ready.p.doctor.short.one" if notes["n"] == 1 else "ready.p.doctor.short", n=notes["n"]),
                               "fix": {"to": "term", "run": "harness doctor", "label": messages.text("ready.fix.doctor")}}
                    entry["problems"] = [*entry["problems"], dict(problem, kind="note")]
                    entry["state"] = "yellow"
        lacks = self.identity_lacks()
        if lacks:  # not in Required: a yellow note on the connections row (1.7.38, C13 D3-3)
            for entry in listed:
                if entry["key"] == "connections":
                    entry["problems"] = [*entry["problems"], readyitems.identity_problem(lacks, len((conn_core.state(self.root).get("accounts") or [])) > 1)]
                    entry["state"] = "yellow" if entry.get("state") != "red" else "red"
        problems = readyitems.problems(listed)
        return {"items": listed, "problems": problems, "count": len(problems), "kb": any(entry["key"] == "kb" and entry.get("found") for entry in listed), "notes": self.notes(gaps, listed)}

    def notes(self, gaps: List[Dict[str, Any]], listed: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """The dot on the gear (O1): `{key, text, effect}` for each thing of the company that is not set up, and for each reminder of kind `note`."""
        out = [{"key": entry["key"], "text": messages.text(NOTES[entry["key"]]) if entry["key"] in NOTES else entry["key"], "effect": messages.text(EFFECTS[entry["key"]]) if entry["key"] in EFFECTS else ""} for entry in gaps]
        for entry in listed:
            for problem in entry["problems"]:
                if problem.get("kind") == "note":
                    out.append({"key": str(problem["key"]), "text": problem["text"], "effect": problem.get("why", "")})
        return out

    # --- VS Code: the button --------------------------------------------------------------------------------------

    def button(self, checks: List[Dict[str, Any]], is_ready: bool) -> Dict[str, Any]:
        """The one button in the middle of the Enter screen (O1): the first of BUTTONS that holds. `{kind, label, off, code, url, left, percent, program, download, detail, n}`; the page only draws it."""
        say = messages.text
        found = {entry["id"]: entry for entry in checks}
        setup, paired, doctor, vscode, copilot = (found.get(name) or {} for name in self.REQUIRED)
        out: Dict[str, Any] = {"kind": "", "label": "", "off": False, "code": "", "url": "", "left": None, "percent": None, "program": "", "download": "", "detail": "", "n": 0}
        why = str(copilot.get("why") or "")
        kind = "check"
        if paired.get("state") == "fail":
            kind = "pair"
        elif setup.get("state") == "fail":
            kind = "setup"
        elif vscode.get("why") in ("no-code", "off") and vscode.get("state") == "fail":
            kind, out["program"], out["download"] = "program", "VS Code", PROGRAM_PAGES["vscode"]
        elif copilot.get("state") == "fail" and why in ("no-gh", "gh-broken"):
            kind, out["program"], out["download"], out["detail"] = "program", "GitHub CLI", str(copilot.get("download") or PROGRAM_PAGES["gh"]), str(copilot.get("detail") or "")
        elif doctor.get("state") == "fail":
            kind, out["n"] = "doctor", int(doctor.get("n") or 1)
        elif copilot.get("state") == "fail" and why in ("signin", "refused"):
            kind = "signin"
        elif copilot.get("state") == "wait" and why == "signing-in":
            kind, out["code"], out["url"], out["left"] = "signing", str(copilot.get("code") or ""), str(copilot.get("url") or ""), copilot.get("left")
        elif copilot.get("state") == "wait" and why == "host-preparing":
            kind, out["percent"] = "preparing", (copilot.get("host") or {}).get("percent")
        elif copilot.get("state") == "fail" and why == "host-failed":
            kind, out["detail"] = "restart-host", str(copilot.get("detail") or "")
        elif vscode.get("state") == "wait" or (copilot.get("state") == "wait" and why in ("host-starting", "connecting", "models", "vscode")):
            kind = "wait"
        elif any(entry.get("state") == "check" for entry in checks):
            kind = "check"
        elif is_ready:
            kind = "enter"
        elif any(entry.get("state") == "wait" for entry in checks):
            kind = "wait"
        out["kind"], out["off"] = kind, kind in ("signing", "preparing", "wait", "check")
        words = {"doctor": "ready.btn.doctor.one" if out["n"] == 1 else "ready.btn.doctor", "preparing": "ready.btn.preparing" if isinstance(out["percent"], (int, float)) else "ready.btn.preparing.plain"}
        out["label"] = say(words.get(kind) or BUTTONS[kind], program=out["program"], n=out["n"], percent=out["percent"])
        return out

    ACTIONS = {"signin": "signin", "refused": "signin", "no-gh": "get-gh", "signing-in": "signing", "host-preparing": "preparing", "host-starting": "preparing", "no-code": "get-vscode"}

    def action(self, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """1.8.x: the button beside Enter: the fix of the VS Code or Copilot line that is not ok (sign in, get gh, get VS Code), or what goes on (preparing, signing in: off)."""
        for line in checks:
            if line["id"] in ("vscode", "copilot") and line["state"] != "ok":
                kind = self.ACTIONS.get(str(line.get("why") or ""), "")
                if kind:
                    return {"kind": kind, "label": messages.text(f"ready.act.{kind}"), "off": kind in ("signing", "preparing"), "url": str(line.get("download") or "")}
                return {"kind": "none"}
        return {"kind": "none"}

    # --- the answer -----------------------------------------------------------------------------------------------

    def level(self, line: Dict[str, Any]) -> str:
        """The dot of a required line: ok (green), grey (not known yet), yellow (it comes by itself), red (needs the person)."""
        if line.get("level"):
            return str(line["level"])
        return "ok" if line["state"] == "ok" else "grey" if line["state"] == "check" else "yellow" if line["state"] == "wait" else "red"

    def required_problems(self, checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """What is not ok in the first block, as words for the red block of the board: `{key, level, text, why, fix}`. Copilot waiting for VS Code is not a problem of its own."""
        out: List[Dict[str, Any]] = []
        say = messages.text
        for line in checks:
            state, why, key = line["state"], line.get("why", ""), line["id"]
            if state in ("ok", "check"):
                continue
            text, reason, fix = "", "", {}
            if key == "setup":
                text, reason, fix = say("ready.r.setup.new"), say("ready.r.setup.new.why"), {"to": "setup", "sec": "you", "label": say("board.enter.getready")}
            elif key == "paired":
                text, reason = say("ready.r.paired"), say("ready.r.paired.why")
            elif key == "doctor":
                text, reason = (say("ready.r.doctor.failed"), line.get("detail", "")) if why == "failed" else (say("ready.r.doctor.errors.one" if line.get("n") == 1 else "ready.r.doctor.errors", n=line.get("n", "")), line.get("detail", ""))
                fix = {} if line.get("integrity") else {"to": "doctor", "label": say("board.enter.doctor.again")}  # 1.7.45: run it now, not when its wait is over; guardrail files have their own button
            elif key == "vscode":
                text, reason = say(f"ready.r.vscode.{'off' if why == 'off' else 'no-code'}"), say("ready.r.vscode.no-code.why")
                fix = {"to": "copilot", "kind": "get-vscode", "url": line.get("download") or VSCODE_PAGE, "label": say("ready.act.get-vscode")} if why == "no-code" else {}
            elif key == "copilot":
                if why == "vscode":
                    continue
                text, reason = say(f"ready.r.copilot.{why}"), say(f"board.enter.m.copilot.{why}", n=line.get("n", ""), detail=line.get("detail", ""))
                kind = self.ACTIONS.get(why, "")
                if kind in ("signin", "get-gh"):
                    fix = {"to": "copilot", "kind": kind, "url": line.get("download", ""), "label": say(f"ready.act.{kind}")}
            out.append({"key": key, "level": "red" if state == "fail" else "yellow", "code": why, "text": plain(text), "why": plain(short(reason)), "fix": fix})
        return out

    def latest(self, paired: bool) -> Dict[str, Any]:
        """1.8.13: what `/api/ready` sends: the last answer a thread of its own worked out, at once. On a work computer one answer took more than the page's 8 s, the page
        counted that as "the board did not answer" and turned Enter off, with every line green. The thread works while the page asks (FRESH_FOR s after the last question).
        Until the first answer is there: every line is still being checked."""
        with self.lock:
            self.asked_at = self.clock()
            kept = self.kept
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self.keep_fresh, name="ready-answer", daemon=True)
                self.worker.start()
        if kept is None:
            self.first.wait(pace.scaled(FIRST_WAIT))
            with self.lock:
                kept = self.kept
        if kept is None:
            checking = [{"id": name, "blocking": True, "group": "required", "kind": "setup" if name == "setup" else "run", "state": "check", "why": "running", "level": "grey"} for name in self.REQUIRED]
            return {"ready": False, "checks": checking, "optional": {"items": [], "problems": [], "count": 0, "notes": []}, "problems": {"required": [], "optional": []}, "button": self.button(checking, False), "notes": []}
        out = copy.deepcopy(kept)
        if not paired:  # worked out for a paired browser: this one is not
            for line in out["checks"]:
                if line["id"] == "paired":
                    line.update(state="fail", why="unpaired")
                    line["level"] = self.level(line)
            out["ready"] = False
            out["problems"]["required"] = self.required_problems(out["checks"])
            out["button"] = self.button(out["checks"], False)
        return out

    def keep_fresh(self) -> None:
        """Work the answer out again and again while the page asks; stop FRESH_FOR s after its last question. A slow answer is written to the board's log with the time of each part."""
        while True:
            with self.lock:
                if self.clock() - self.asked_at > FRESH_FOR:
                    self.worker = None
                    return
            began = time.monotonic()
            try:
                found = self.answer(True)
            except Exception as error:  # noqa: BLE001 - the page shows that the check itself failed
                found = {"ready": False, "checks": [{"id": "doctor", "blocking": True, "group": "required", "kind": "run", "state": "fail", "why": "failed", "level": "red", "detail": short(f"{type(error).__name__}: {error}")}],
                         "optional": {"items": [], "problems": [], "count": 0, "notes": []}, "problems": {"required": [], "optional": []}, "button": {"kind": "check", "label": messages.text("ready.btn.check"), "off": True, "code": "", "url": "", "left": None, "percent": None, "program": "", "download": "", "detail": "", "n": 0}, "notes": []}
            spent = time.monotonic() - began
            if spent > SLOW_ANSWER:
                parts = ", ".join(f"{name} {value:.1f}" for name, value in sorted((getattr(self, "took", {}) or {}).items(), key=lambda item: -item[1]) if value >= 0.1)
                print(messages.text("ready.slow", seconds=f"{spent:.1f}", parts=parts or "-"), flush=True)
            with self.lock:
                self.kept = found
            self.first.set()
            time.sleep(KEEP_EVERY)

    def answer(self, paired: bool) -> Dict[str, Any]:
        """`{ready, checks, optional, problems, action}`. `checks`: the five required lines `{id, group, blocking, level, state, why, ...}`. `state`: ok, wait (it comes by itself), fail (needs the person), check
        (not known yet). `ready`: every required line is ok, and only then Enter is on (1.7.38)."""
        checks: List[Dict[str, Any]] = []
        took: Dict[str, float] = {}

        def add(name: str, make: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
            began = time.monotonic()
            try:
                line = make()
            except Exception as error:  # noqa: BLE001 - a check that breaks is told as failed, with its reason
                line = {"state": "fail", "why": "error", "detail": short(f"{type(error).__name__}: {error}")}
            finally:
                took[name] = time.monotonic() - began
            line = dict(line, id=name, blocking=True, group="required", kind="setup" if name == "setup" else "run")
            checks.append(line)
            return line

        add("setup", lambda: {"state": "fail", "why": "new"} if not setup_done(self.root) else {"state": "ok", "why": "ok"})
        add("paired", lambda: {"state": "ok", "why": "ok"} if paired else {"state": "fail", "why": "unpaired"})
        add("doctor", self.doctor_line)
        vscode = add("vscode", self.vscode)
        add("copilot", lambda: self.copilot(vscode))
        began = time.monotonic()
        try:
            self.checker.maybe()  # the board asks the connections itself: the screen need not wait for a chat
        except Exception:  # noqa: BLE001 - a check of the connections that cannot start is not a reason to fail a poll
            pass
        took["connections"] = time.monotonic() - began
        began = time.monotonic()
        optional = self.optional()
        took["optional"] = time.monotonic() - began
        self.took = took
        for line in checks:
            line["level"] = self.level(line)
        return {"ready": all(line["state"] == "ok" for line in checks), "checks": checks, "optional": optional, "problems": {"required": self.required_problems(checks), "optional": optional["problems"]},
                "action": self.action(checks), "button": self.button(checks, all(line["state"] == "ok" for line in checks)), "notes": optional["notes"]}
