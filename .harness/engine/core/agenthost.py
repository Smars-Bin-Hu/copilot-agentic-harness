"""The board's own agent host (1.8.x): VS Code's standalone agent host, started by the board, with no editor window. Python standard library only.

`code agent host --new-instance --foreground` starts a host that belongs to this copy of the harness alone:
- `--new-instance`: never reuse, never stop the host of an open VS Code (`--replace` would stop it). A person may have VS Code open at the same time.
- Its own `--user-data-dir` (the registry of endpoints) and `--server-data-dir` (its logs and state) under `.harness/runtime/agent-host/`. The CLI data folder is VS Code's default:
  the server package (about 620 MB, one per VS Code version) is downloaded once there and shared with Remote and tunnels.
- The connection token is ours: a new random one at each start, in a file only this user reads (`--connection-token-file`). Nothing is read from `code agent endpoints`.
- The port is read from the host's own output (`ws://localhost:<port>`): the endpoint is the one of the process we started, never another one.
- `--idle-timeout`: a host whose board died without stopping it ends itself once no client and no running chat is left.
- The chat store is not ours: the host reads and writes `~/.copilot` like VS Code does, so a chat the board makes is seen in VS Code too.

The host signs in to nobody by itself. The board hands it a GitHub token after each start (core.ghauth); the token never comes here.

Stopping: the whole process tree we started (its own process group; `taskkill /T` on Windows). `code agent kill` is never used: it finds whatever host runs.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import hashlib
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from . import ahp, paths, procrun

SERVER_MB = 620  # the size of the server package once unpacked (VS Code 1.147, macOS 624 MB): what a first start downloads
IDLE_TIMEOUT = 900  # seconds with no client and no running chat before a host left behind ends itself
READY_WAIT = 600  # seconds a start may take: the first one downloads the server package (177 s on a slow work computer)
STOP_GRACE = 5.0  # seconds a host gets to end by itself before its tree is ended
LINES_KEPT = 200
SIZE_EVERY = 2.0  # seconds between two looks at the size of the download

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
READY = re.compile(r"ws://([A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\]):(\d+)")
DOWNLOADING = re.compile(r"Downloading server ([0-9a-f]{7,40})")
VERSION = re.compile(r"Agent Host\s+v(\d+\.\d+\.\d+)")
TOKEN_IN = re.compile(r"(tkn=)[^\s&\"']+")


def env_mark(extra: Dict[str, str]) -> str:
    """A short mark of the variables a host was started with (H5): a host whose mark differs from what `extra` gives now runs with old Local settings."""
    return hashlib.sha256(json.dumps(sorted((extra or {}).items())).encode("utf-8")).hexdigest()[:16]


def folder(root: Path) -> Path:
    return paths.runtime_dir(root) / "agent-host"


def record_file(root: Path) -> Path:
    """What the board knows of the host it started: `{pid, port, version, started}`. The token is in its own file, never here."""
    return folder(root) / "host.json"


def token_file(root: Path) -> Path:
    return folder(root) / "connection-token"


def cli_data_dir(environ: Optional[Dict[str, str]] = None, platform: Optional[str] = None) -> Path:
    """VS Code's default CLI data folder, where the server packages are (`servers/Stable-<commit>`). `VSCODE_CLI_DATA_DIR` moves it."""
    env = os.environ if environ is None else environ
    if env.get("VSCODE_CLI_DATA_DIR"):
        return Path(env["VSCODE_CLI_DATA_DIR"])
    home = env.get("USERPROFILE") if (platform or sys.platform).startswith("win") and env.get("USERPROFILE") else os.path.expanduser("~") if environ is None else env.get("HOME", "")
    return Path(home or ".") / ".vscode" / "cli"


def clean(line: str) -> str:
    """A line of the host's output as it may be kept and shown: no colours, no connection token."""
    return TOKEN_IN.sub(r"\1***", ANSI.sub("", line)).rstrip()


def folder_size(top: Path, budget: int = 20000) -> int:
    """Bytes under `top`, looking at `budget` files at most. Never raises."""
    total, seen = 0, 0
    for base, _dirs, files in os.walk(str(top)):
        for name in files:
            seen += 1
            if seen > budget:
                return total
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
    return total


def _alive(pid: Any) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return str(pid) in done.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _answers(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=timeout):
            return True
    except OSError:
        return False


def end_group(pid: int, grace: float = STOP_GRACE) -> None:
    """End a process tree started in its own group (POSIX) or under one parent (Windows): ask first, then end it. Never raises."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        return
    end = time.monotonic() + grace
    while time.monotonic() < end:
        try:
            os.killpg(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


class Host:
    """One agent host of this copy. `start` returns at once; `status` says where the start is; `endpoint` is there once it is ready.

    States: `stopped`, `no-code` (VS Code is not installed: no `code` command), `starting`, `preparing` (the server package is being downloaded), `ready`, `failed`.
    Used by the board's link thread and read by page requests: the state is under a lock."""

    def __init__(self, root: Path, code: Optional[str] = None, extra: Optional[Callable[[], Dict[str, str]]] = None, popen: Callable[..., Any] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic, ready_wait: float = READY_WAIT, identities: Optional[Callable[[], Dict[str, Any]]] = None,
                 netonly_popen: Optional[Callable[[str, str], Callable[..., Any]]] = None, path: Optional[Callable[[], str]] = None) -> None:
        self.root = Path(root)
        self.code = code
        self.extra = extra or (lambda: {})
        self.identities = identities or (lambda: {"env": {}, "netonly": None, "mark": ""})  # H5b: `connections.host_identities`: variables, a Windows account, and a mark with no secret
        self.netonly_popen = netonly_popen  # H5b: how a host is started with a Windows account (`netonly.popen`); the tests pass their own
        self.path = path  # H6: the PATH a new terminal would see (`shortcmd.fresh_path`): the board may have been started before the short command was put on PATH
        self.outdated = False  # H6: something the host only reads at start changed outside Local (the short command was put on PATH): it is stale until it starts again
        self.popen = popen
        self.clock = clock
        self.ready_wait = ready_wait
        self.lock = threading.Lock()
        self.cycle = threading.RLock()  # H5: one start, stop or restart at a time. A restart from a page and the link's own start after the drop must not each start a host (one would be left running)
        self.ready_event = threading.Event()
        self.process: Any = None
        self.pid = 0
        self.port = 0
        self._token = ""
        self.state = "stopped"
        self.why = ""
        self.version = ""
        self.commit = ""
        self.started_at = 0.0
        self.ready_at = 0.0
        self.starts = 0
        self.adopted = False
        self.given = ""  # env_mark of what the running host was started with ("" before a start, or a host adopted from an older record)
        self.lines: Deque[str] = deque(maxlen=LINES_KEPT)
        self._size = (0.0, 0)  # (when looked, bytes)

    # --- what a page reads ---------------------------------------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Where the host is, for the Enter page and the hover: never the token."""
        with self.lock:
            out: Dict[str, Any] = {"state": self.state, "why": self.why, "version": self.version, "pid": self.pid or None, "port": self.port or None,
                                   "starts": self.starts, "adopted": self.adopted}
            if self.started_at:
                out["seconds"] = round((self.ready_at or self.clock()) - self.started_at, 1)
            if self.state == "preparing":
                out.update(self._download())
        return out

    def _download(self) -> Dict[str, Any]:
        now = self.clock()
        if now - self._size[0] >= SIZE_EVERY and self.commit:
            self._size = (now, folder_size(cli_data_dir() / "servers" / f"Stable-{self.commit}"))
        done = int(self._size[1] / (1024 * 1024))
        return {"downloaded_mb": done, "total_mb": SERVER_MB, "percent": min(99, int(100 * done / SERVER_MB))}

    def endpoint(self) -> Optional[ahp.Endpoint]:
        with self.lock:
            if self.state != "ready" or not self.port:
                return None
            return ahp.Endpoint("tcp", f"localhost:{self.port}", self.pid, "", self._token)

    def tail(self, count: int = 20) -> List[str]:
        with self.lock:
            return list(self.lines)[-count:]

    # --- start, adopt, stop ---------------------------------------------------------------------------------------------------

    def _write_record(self) -> None:
        try:
            record_file(self.root).write_text(json.dumps({"pid": self.pid, "port": self.port, "version": self.version, "env": self.given, "started": paths.utc_now()}), encoding="utf-8")
        except OSError:
            pass

    def stop_left(self) -> bool:
        """`task board --stop` with no board running: stop the host this copy started before, when it still runs and answers (a reinstall must not find its files held). False when there is none."""
        with self.cycle:
            if not self.adopt():
                return False
            self._stop()
            return True

    def adopt(self) -> bool:
        """Take over a host this copy started before (the board was restarted) when it still runs and still answers: no new start, chats keep running. False otherwise."""
        try:
            record = json.loads(record_file(self.root).read_text(encoding="utf-8"))
            token = token_file(self.root).read_text(encoding="utf-8").strip()
            pid, port = int(record["pid"]), int(record["port"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not token or not _alive(pid) or not _answers(port):
            return False
        with self.lock:
            self.pid, self.port, self._token, self.version = pid, port, token, str(record.get("version") or "")
            self.given = str(record.get("env") or "")
            self.process, self.adopted, self.state, self.why = None, True, "ready", ""
            self.started_at = self.ready_at = self.clock()
            self.ready_event.set()
        return True

    def start(self) -> Dict[str, Any]:
        """Start the host unless one runs or starts. Returns `status()` at once; a thread reads the host's output."""
        with self.cycle:
            return self._start()

    def _start(self) -> Dict[str, Any]:
        with self.lock:
            if self.state in ("starting", "preparing", "ready"):
                return self._status_unlocked()
        if self.adopt():
            return self.status()
        code = self.code or ahp.find_code()
        if not code:
            with self.lock:
                self.state, self.why = "no-code", "VS Code is not installed (no `code` command)"
            return self.status()
        home = folder(self.root)
        try:
            for name in ("user", "server"):
                (home / name).mkdir(parents=True, exist_ok=True)
            token = secrets.token_hex(24)
            target = token_file(self.root)
            target.write_text(token, encoding="utf-8")
            try:
                os.chmod(str(target), 0o600)
            except OSError:
                pass
        except OSError as error:
            with self.lock:
                self.state, self.why = "failed", f"cannot write {home}: {type(error).__name__}"
            return self.status()
        env = {key: value for key, value in os.environ.items() if not key.startswith("VSCODE_IPC") and key != "ELECTRON_RUN_AS_NODE"}
        given = dict(self.extra() or {})
        env.update(given)
        self._fresh_path(env)
        held = self._held()
        env.update(held.get("env") or {})  # H5b: the variables of the identities the host holds; never in the record, never in the output kept
        popen_now = self.popen
        if held.get("netonly"):  # a Windows account: every program the host starts reaches other computers with it
            account, password = held["netonly"]
            if self.netonly_popen is None:
                from . import netonly  # noqa: PLC0415 - Windows only

                if not netonly.available():
                    with self.lock:
                        self.state, self.why = "failed", "a Windows account can be held on Windows only"
                    return self.status()
                popen_now = netonly.popen(account, password)
            else:
                popen_now = self.netonly_popen(account, password)
        arguments = [code, "agent", "host", "--new-instance", "--foreground", "--user-data-dir", str(home / "user"), "--server-data-dir", str(home / "server"),
                     "--connection-token-file", str(target), "--idle-timeout", str(IDLE_TIMEOUT)]
        popen: Dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
        if os.name == "nt":
            popen["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen["start_new_session"] = True
        try:
            process = popen_now(arguments, **popen)
        except (OSError, subprocess.SubprocessError) as error:
            with self.lock:
                self.state, self.why = "failed", f"cannot start `code`: {type(error).__name__}"
            return self.status()
        with self.lock:
            self.process, self.pid, self.port, self._token = process, process.pid, 0, token
            self.given, self.outdated = self._mark(given, held), False
            self.state, self.why, self.version, self.commit, self.adopted = "starting", "", "", "", False
            self.started_at, self.ready_at = self.clock(), 0.0
            self.starts += 1
            self.lines.clear()
            self.ready_event.clear()
        threading.Thread(target=self._read, args=(process,), name="agent-host-output", daemon=True).start()
        return self.status()

    def _status_unlocked(self) -> Dict[str, Any]:
        return {"state": self.state, "why": self.why, "version": self.version, "pid": self.pid or None, "port": self.port or None, "starts": self.starts, "adopted": self.adopted}

    def _read(self, process: Any) -> None:
        """The host's output, line by line, until it ends: the download, the version, the port."""
        try:
            self._lines(process)
        finally:
            try:
                process.stdout.close()
            except (OSError, AttributeError):
                pass

    def _lines(self, process: Any) -> None:
        for raw in iter(process.stdout.readline, b""):
            line = clean(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))
            if not line.strip():
                continue
            with self.lock:
                if process is not self.process:
                    return
                self.lines.append(line)
                found = DOWNLOADING.search(line)
                if found and self.state == "starting":
                    self.state, self.commit = "preparing", found.group(1)
                found = VERSION.search(line)
                if found:
                    self.version = found.group(1)
                found = READY.search(line)
                if found and self.state in ("starting", "preparing"):
                    self.port, self.state, self.ready_at = int(found.group(2)), "ready", self.clock()
                    self._write_record()  # before anyone hears it is ready: a board started next may adopt it at once
                    self.ready_event.set()
        code = process.wait()
        with self.lock:
            if process is self.process and self.state != "stopped":
                self.state = "failed"
                self.why = f"the agent host ended (exit {code})"
                self.port = 0
                self.ready_event.set()

    def wait_ready(self, timeout: Optional[float] = None) -> ahp.Endpoint:
        """The endpoint once the host is ready. `ahp.NotReady` when it failed, is not installed, or took longer than `timeout` (default: READY_WAIT)."""
        self.ready_event.wait(self.ready_wait if timeout is None else timeout)
        found = self.endpoint()
        if found:
            return found
        with self.lock:
            state, why = self.state, self.why
        if state == "no-code":
            raise ahp.NotReady("no-cli", why)
        if state in ("starting", "preparing"):
            raise ahp.NotReady("cli-slow", "the agent host is not ready yet")
        raise ahp.NotReady("none", why or "the agent host is not running")

    def alive(self) -> bool:
        with self.lock:
            process, pid, port, state = self.process, self.pid, self.port, self.state
        if state != "ready":
            return False
        if process is not None:
            return process.poll() is None
        return _alive(pid) and _answers(port)

    def stop(self) -> None:
        """End the host and everything it started. Never raises."""
        with self.cycle:
            self._stop()

    def _stop(self) -> None:
        with self.lock:
            process, pid = self.process, self.pid
            self.state, self.why, self.port, self.process = "stopped", "", 0, None
            self.ready_event.set()
        if pid:
            end_group(pid)
        if process is not None:
            try:
                process.wait(timeout=STOP_GRACE)
            except (subprocess.SubprocessError, OSError):
                procrun.end_tree(process)
        for target in (record_file(self.root),):
            try:
                target.unlink()
            except OSError:
                pass

    def _mark(self, given: Dict[str, str], held: Dict[str, Any]) -> str:
        return env_mark(given) + (":" + hashlib.sha256(str(held.get("mark") or "").encode("utf-8")).hexdigest()[:16] if held.get("mark") else "")

    def _fresh_path(self, env: Dict[str, str]) -> None:
        """Add to the PATH of `env` the folders a new terminal has and this process does not (H6). Never raises: a PATH that cannot be told adds nothing."""
        if self.path is None:
            return
        try:
            fresh = [item for item in str(self.path() or "").split(os.pathsep) if item]
        except Exception:  # noqa: BLE001 - the host still starts with the PATH it has
            return
        key = next((name for name in env if name.upper() == "PATH"), "PATH")
        have = [item for item in env.get(key, "").split(os.pathsep) if item]
        more = [item for item in fresh if item not in have]
        if more:
            env[key] = os.pathsep.join(have + more)

    def outdate(self) -> None:
        """H6: mark a running host stale for a reason `extra` does not show (the short command is on PATH now); the board restarts it once no chat works."""
        with self.lock:
            self.outdated = True

    def stale(self) -> bool:
        """H5: the host runs (or starts) with other variables than `extra` gives now: a tool folder, the CA bundle or the proxy changed in Local since, or (H5b) the identities it holds.
        Only a restart gives it the new ones."""
        with self.lock:
            if self.state not in ("starting", "preparing", "ready"):
                return False
            if self.outdated:
                return True
            given = self.given
        return given != self._mark(dict(self.extra() or {}), self._held())

    def _held(self) -> Dict[str, Any]:
        try:
            return dict(self.identities() or {})
        except Exception:  # noqa: BLE001 - identities that cannot be read are none: the host still starts
            return {}

    def restart(self) -> Dict[str, Any]:
        with self.cycle:  # the link's start after the drop waits here, then finds the new host starting
            self._stop()
            return self._start()
