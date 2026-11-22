"""Signing the board's agent host in to Copilot with the GitHub CLI (1.8.x). Python standard library only.

Only a token of GitHub's own apps gets Copilot models in VS Code's agent host: gh's does; an OAuth app of one's own, a personal access token and VS Code's command-line
sign-in do not (checked 2026-11-22). So the board signs in through gh:
- gh keeps the token (macOS keychain, Windows Credential Manager). The harness stores none: `token()` is read when the host starts, handed over the connection, and dropped.
- The token is never printed, logged, put in an error or on a command line.
- Signing in is gh's own web flow, run with no terminal: gh prints a one-time code and the address, the page shows both, the person approves in the browser, gh ends.
  With no terminal gh asks nothing, so it never sets itself up as Git's credential helper: the person's Git settings stay as they are.
- The harness never downloads gh. When it is missing the page links to GitHub's page for it, and the person may name the folder it is in.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import procrun

HOST = "github.com"
GH_ENV = "HARNESS_GH"  # a person may point at gh (the program or its folder) by hand; `off`: no gh at all (the tests)
DOWNLOAD_PAGE = "https://cli.github.com/"
RUN_TIMEOUT = 30
CODE_LIFE = 900  # seconds a one-time code of GitHub's device flow is good for
CODE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
DEVICE_URL = re.compile(r"(https://[^\s]+/login/device)\b")
LOGGED_IN_TEXT = re.compile(r"Logged in to (\S+) (?:account|as) (\S+)")
TOKEN_SHAPE = re.compile(r"\b(gh[opusr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


class GhError(Exception):
    """`why`: `no-gh`, `cannot-run`, `slow`, `not-signed-in`."""

    def __init__(self, why: str, text: str = "") -> None:
        super().__init__(scrub(text or why))
        self.why = why


def scrub(text: Any) -> str:
    """Text that may be shown: anything shaped like a GitHub token is taken out."""
    return TOKEN_SHAPE.sub("***", str(text))


def program_name(platform: Optional[str] = None) -> str:
    return "gh.exe" if (platform or sys.platform).startswith("win") else "gh"


def standard_places(environ: Optional[Dict[str, str]] = None, platform: Optional[str] = None) -> List[str]:
    """Where gh is when it was installed the usual way."""
    env = os.environ if environ is None else environ
    kind = platform or sys.platform
    if kind.startswith("win"):
        places = []
        for key, sub in (("ProgramFiles", "GitHub CLI"), ("LOCALAPPDATA", "Programs\\GitHub CLI"), ("ProgramFiles(x86)", "GitHub CLI")):
            if env.get(key):
                places.append(env[key].rstrip("\\/") + "\\" + sub + "\\gh.exe")
        return places
    if kind == "darwin":
        return ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"]
    return ["/usr/bin/gh", "/usr/local/bin/gh", "/snap/bin/gh", "/home/linuxbrew/.linuxbrew/bin/gh"]


def switched_off(environ: Optional[Dict[str, str]] = None) -> bool:
    return (os.environ if environ is None else environ).get(GH_ENV, "").strip().lower() == "off"


def find_gh(folders: Optional[List[str]] = None, environ: Optional[Dict[str, str]] = None, platform: Optional[str] = None,
            exists: Callable[[str], bool] = os.path.isfile, which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """The gh program: the one a person set (`HARNESS_GH`, the program or its folder), the tool folders of Local (`folders`), PATH, then the standard install places. None: no gh."""
    env = os.environ if environ is None else environ
    if switched_off(env):
        return None
    name = program_name(platform)
    chosen = env.get(GH_ENV, "").strip()
    if chosen:
        for place in (chosen, os.path.join(chosen, name)):
            if exists(place):
                return place
    for item in folders or []:
        place = os.path.join(item, name)
        if exists(place):
            return place
    found = which("gh")
    if found:
        return found
    return next((place for place in standard_places(env, platform) if exists(place)), None)


def _env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ)
    for key in ("GH_PROMPT_DISABLED",):
        env.pop(key, None)
    env.update(extra or {})
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    env["NO_COLOR"] = "1"
    return env


def run_gh(gh: str, arguments: List[str], timeout: float = RUN_TIMEOUT, extra: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        return procrun.run([gh] + arguments, timeout=timeout, env=_env(extra), creationflags=flags, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise GhError("slow", f"gh gave no answer in {timeout:g} s") from None
    except (OSError, subprocess.SubprocessError) as error:
        raise GhError("cannot-run", f"gh cannot run: {type(error).__name__}") from None


def version(gh: str, extra: Optional[Dict[str, str]] = None) -> str:
    """`2.105.0`, or `GhError` when gh does not run (blocked, broken)."""
    done = run_gh(gh, ["--version"], extra=extra)
    found = re.search(r"gh version (\d+\.\d+\.\d+)", done.stdout.decode("utf-8", "replace"))
    if done.returncode != 0 or not found:
        raise GhError("cannot-run", f"gh --version: exit {done.returncode}")
    return found.group(1)


def read_status(text: str) -> Dict[str, Any]:
    """`{signed_in, login, why}` from `gh auth status --json hosts`: the active account of github.com. Text that is not that JSON: not signed in."""
    try:
        hosts = (json.loads(text) or {}).get("hosts") or {}
    except (ValueError, AttributeError):
        return {"signed_in": False, "login": "", "why": "unreadable"}
    accounts = [item for item in hosts.get(HOST) or [] if isinstance(item, dict)] if isinstance(hosts, dict) else []
    active = next((item for item in accounts if item.get("active")), accounts[0] if accounts else None)
    if not active:
        return {"signed_in": False, "login": "", "why": "not-signed-in"}
    ok = active.get("state") == "success"
    return {"signed_in": ok, "login": str(active.get("login") or ""), "why": "" if ok else str(active.get("state") or "error")}


def status(gh: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Is gh signed in to github.com, and as whom. An older gh without `--json` is read from its text."""
    done = run_gh(gh, ["auth", "status", "--hostname", HOST, "--active", "--json", "hosts"], extra=extra)
    out = done.stdout.decode("utf-8", "replace")
    if out.strip().startswith("{"):
        return read_status(out)
    done = run_gh(gh, ["auth", "status", "--hostname", HOST], extra=extra)
    text = (done.stdout + done.stderr).decode("utf-8", "replace")
    found = LOGGED_IN_TEXT.search(text)
    if done.returncode == 0 and found:
        return {"signed_in": True, "login": found.group(2), "why": ""}
    return {"signed_in": False, "login": "", "why": "not-signed-in"}


def token(gh: str, extra: Optional[Dict[str, str]] = None) -> str:
    """gh's token for github.com, for the agent host only. Never print it, log it or keep it."""
    done = run_gh(gh, ["auth", "token", "--hostname", HOST], extra=extra)
    value = done.stdout.decode("utf-8", "replace").strip()
    if done.returncode != 0 or not value or len(value.split()) != 1:
        raise GhError("not-signed-in", "gh is not signed in to github.com")
    return value


class Login:
    """`gh auth login --web`, run with no terminal, for the page: the one-time code and the address to open, then done when the person approved.

    States: `starting`, `waiting` (the code is there), `done`, `failed`, `cancelled`, `expired`. One at a time per board."""

    def __init__(self, gh: str, extra: Optional[Dict[str, str]] = None, popen: Callable[..., Any] = subprocess.Popen, clock: Callable[[], float] = time.monotonic,
                 life: float = CODE_LIFE) -> None:
        self.gh, self.extra, self.popen, self.clock, self.life = gh, extra, popen, clock, life
        self.lock = threading.Lock()
        self.state = "starting"
        self.code = ""
        self.url = ""
        self.why = ""
        self.started = clock()
        self.ended = 0.0
        self.process: Any = None
        self.lines: List[str] = []

    def start(self) -> "Login":
        arguments = [self.gh, "auth", "login", "--hostname", HOST, "--git-protocol", "https", "--web"]
        popen: Dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": _env(self.extra)}
        if os.name == "nt":
            popen["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            popen["start_new_session"] = True
        try:
            self.process = self.popen(arguments, **popen)
        except (OSError, subprocess.SubprocessError) as error:
            self._end("failed", f"gh cannot run: {type(error).__name__}")
            return self
        threading.Thread(target=self._read, name="gh-login", daemon=True).start()
        threading.Thread(target=self._expire, name="gh-login-limit", daemon=True).start()
        return self

    def _end(self, state: str, why: str = "") -> None:
        with self.lock:
            if self.state in ("done", "failed", "cancelled", "expired"):
                return
            self.state, self.why, self.ended = state, scrub(why), self.clock()

    def _read(self) -> None:
        try:
            self._lines(self.process)
        finally:
            try:
                self.process.stdout.close()
            except (OSError, AttributeError):
                pass

    def _lines(self, process: Any) -> None:
        for raw in iter(process.stdout.readline, b""):
            line = scrub((raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).rstrip())
            with self.lock:
                if len(self.lines) < 50:
                    self.lines.append(line)
                code, url = CODE.search(line), DEVICE_URL.search(line)
                if code and not self.code:
                    self.code = code.group(1)
                if url and not self.url:
                    self.url = url.group(1)
                if self.code and self.state == "starting":
                    self.state = "waiting"
        exit_code = process.wait()
        if exit_code == 0:
            self._end("done")
        else:
            with self.lock:
                last = next((line for line in reversed(self.lines) if line.strip()), "")
            self._end("failed", f"gh ended (exit {exit_code}){': ' + last[:200] if last else ''}")

    def _expire(self) -> None:
        while True:
            with self.lock:
                if self.state not in ("starting", "waiting"):
                    return
                left = self.life - (self.clock() - self.started)
            if left <= 0:
                self._end("expired", "the code ran out before it was approved")
                self._kill()
                return
            time.sleep(min(1.0, left))

    def _kill(self) -> None:
        if self.process is not None and self.process.poll() is None:
            procrun.end_tree(self.process)

    def cancel(self) -> None:
        self._end("cancelled")
        self._kill()

    def status(self) -> Dict[str, Any]:
        with self.lock:
            now = self.ended or self.clock()
            out: Dict[str, Any] = {"state": self.state, "code": self.code, "url": self.url or ("https://github.com/login/device" if self.code else ""), "why": self.why,
                                   "waited": int(now - self.started)}
            if self.state in ("starting", "waiting"):
                out["left"] = max(0, int(self.life - (now - self.started)))
        return out


def folders_of(root: Optional[Path]) -> List[str]:
    """The tool folders the person added in Local, where gh may be."""
    if root is None:
        return []
    try:
        from . import launchenv

        return launchenv.tool_folders(Path(root))
    except Exception:  # noqa: BLE001 - a broken setting must not hide gh found elsewhere
        return []


def check(root: Optional[Path] = None, extra: Optional[Dict[str, str]] = None, find: Callable[..., Optional[str]] = find_gh) -> Dict[str, Any]:
    """The gh half of the Enter item "Copilot signed in (gh)": `{gh, version, signed_in, login, why}`. `why`: `no-gh`, `cannot-run`, `slow`, `not-signed-in`, or empty. Never the token."""
    gh = find(folders_of(root))
    if not gh:
        return {"gh": "", "version": "", "signed_in": False, "login": "", "why": "no-gh", "download": DOWNLOAD_PAGE}
    try:
        found = version(gh, extra)
        state = status(gh, extra)
    except GhError as error:
        return {"gh": gh, "version": "", "signed_in": False, "login": "", "why": error.why}
    return {"gh": gh, "version": found, "signed_in": state["signed_in"], "login": state["login"], "why": "" if state["signed_in"] else "not-signed-in"}
