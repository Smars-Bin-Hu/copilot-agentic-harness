"""The board's judging service for hook calls (hook speed, 1.8.50).

Starting Python and loading the engine takes a hook process 4 to 8 seconds on a work computer, and the board, which is always open, has the engine loaded. So the board listens on a port of its own (127.0.0.1 only,
not the board's page: no pairing, no cookie) and a hook process asks it to judge the call (`hookclient.py`, started by `launch.py`). The judgment is `hook.answer`, the same function the hook process runs, so there is one
judgment and it is not copied. The protocol is in `hookclient.py`.

The service only ever makes the answer quicker. It refuses (`{"ok": false, "why": ...}`, and the hook process judges the call itself) whenever it is not sure its answer would be the one a hook process would give:
the request is not signed with the key of this board, it came too late, the engine files are not the ones this process loaded (an upgrade without a restart, a file edited), the temp folder or the Python of the
hook process is not ours (the session locks and the text rules would not be the same), or `core.procenv` (the environment and folder of the asking process for the judgment) is not there. One call is judged at a time.

The file `.harness/runtime/hookserve.json` holds the port, the pid of this board and the key; it is written when the service starts (mode 0600) and removed when it stops. Nothing here may stop the board:
every failure of a request is an answer of `ok: false`, or a closed connection (the hook process then judges the call itself)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core import pace
from core.paths import runtime_dir, utc_now

FILE = "hookserve.json"
LIMIT = 8 * 1024 * 1024  # bytes of a request: a payload with a long file in it
READ_SECONDS = 10.0  # a client that sent no whole line in this time is dropped (a thread must not wait for ever)
WAIT = 3.0  # seconds a hook process waits for the start line, before the pace factor
SKIP_DIRS = frozenset(["__pycache__", ".pytest_cache", ".git"])
SKIP_SUFFIXES = (".pyc", ".pyo", ".lock", ".tmp")
Stamp = Dict[str, Tuple[int, int]]


def file_of(root: Path) -> Path:
    return runtime_dir(root) / FILE


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sign(key: str, *parts: str) -> str:
    return hmac.new(key.encode("utf-8"), "".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def snapshot(root: Path, engine: Optional[Path] = None) -> Stamp:
    """`{path: (size, mtime in ns)}` of every file whose change makes the code in this process not the code on disk: the engine (`engine`, the folder the loaded `hook.py` is in), the hook configuration, the
    registry and the tool packs. The settings (`policies/`) are not in it: they are read again for every call (a change shows in the next answer). A file that cannot be looked at is left out."""
    root = Path(root)
    found: Stamp = {}

    def add(path: Path) -> None:
        try:
            info = path.stat()
            found[str(path)] = (info.st_size, info.st_mtime_ns)
        except OSError:
            pass

    for folder in (engine if engine is not None else root / ".harness" / "engine", root / ".github" / "hooks", root / ".harness" / "toolpacks"):
        for here, names, files in os.walk(folder):
            names[:] = [name for name in names if name not in SKIP_DIRS]
            for name in files:
                if not name.endswith(SKIP_SUFFIXES):
                    add(Path(here) / name)
    add(root / ".harness" / "registry.json")
    return found


def write_file(path: Path, data: Dict[str, Any]) -> None:
    """Atomically, readable by this user only (the key is in it). On Windows the mode does not apply: the folder is the user's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    descriptor = os.open(str(part), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data))
    os.replace(str(part), str(path))


class Listener(socketserver.ThreadingTCPServer):
    allow_reuse_address = False  # never: a second program must not be able to take the port over (on Windows `SO_REUSEADDR` allows exactly that)
    daemon_threads = True
    request_queue_size = 32

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: nobody else may bind this port while we hold it
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that went away is not an error to print."""


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.service.serve_one(self.request)  # type: ignore[attr-defined]


class HookService:
    """`start()` makes the key and the file and begins to listen; `stop()` ends it. `engine` is the folder whose files are watched (default: the folder of the loaded `hook.py`; a test gives its own)."""

    def __init__(self, root: Path, engine: Optional[Path] = None) -> None:
        self.root = Path(root)
        self.engine = engine
        self.key = ""
        self.port = 0
        self.loaded: Stamp = {}
        self.server: Optional[Listener] = None
        self.thread: Optional[threading.Thread] = None
        self.judging = threading.Lock()  # one call is judged at a time: the engine's own memory (`targets`, `messages`) is not locked
        self.hook: Any = None

    # --- life ---------------------------------------------------------------------------------

    def start(self) -> bool:
        """True when it listens. Never raises: a board that cannot run the service is still a board (the hook processes judge themselves)."""
        try:
            import hook  # the engine's own judgment (hook.py is in the folder of the engine, which is on the path of the board)

            if getattr(hook, "ENGINE_FAULT", None) is not None:
                return False
            self.hook = hook
            self.engine = self.engine if self.engine is not None else Path(hook.__file__).resolve().parent
            self.key = secrets.token_hex(32)
            self.loaded = snapshot(self.root, self.engine)
            server = Listener(("127.0.0.1", 0), Handler, bind_and_activate=False)
            try:
                server.server_bind()
                server.server_activate()
            except BaseException:
                server.server_close()
                raise
            server.service = self  # type: ignore[attr-defined]
            self.server = server
            self.port = server.server_address[1]
            self.write()
            self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, name="hook-serve", daemon=True)
            self.thread.start()
            return True
        except BaseException as error:  # noqa: BLE001
            print(f"hook service not started: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
            self.stop()
            return False

    def write(self) -> None:
        """The file the hook processes read. Written again when the pace factor is measured (the time a hook process waits for the start line grows with it)."""
        write_file(file_of(self.root), {"v": 1, "port": self.port, "pid": os.getpid(), "key": self.key, "started": utc_now(), "wait": round(WAIT * pace.factor(self.root), 1)})

    def stop(self) -> None:
        """Close, and remove the file when it is ours (a board that started after a crash may have written its own)."""
        server, self.server = self.server, None
        if server is not None:
            try:
                if self.thread is not None:  # `shutdown` waits for `serve_forever` to end: it must have begun
                    server.shutdown()
            except BaseException:  # noqa: BLE001
                pass
            try:
                server.server_close()
            except BaseException:  # noqa: BLE001
                pass
        try:
            path = file_of(self.root)
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError, AttributeError):
            pass

    # --- one request --------------------------------------------------------------------------

    def serve_one(self, sock: socket.socket) -> None:
        try:
            self.serve(sock)
        except BaseException:  # noqa: BLE001 - nothing of a request may reach the board; the hook process judges the call itself
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def say(self, sock: socket.socket, data: Dict[str, Any]) -> None:
        sock.sendall(json.dumps(data).encode("utf-8") + b"\n")

    def refuse(self, sock: socket.socket, why: str) -> None:
        try:
            self.say(sock, {"ok": False, "why": why})
        except OSError:
            pass

    def read(self, sock: socket.socket) -> Optional[Dict[str, Any]]:
        sock.settimeout(READ_SECONDS)
        buffer = b""
        until = time.monotonic() + READ_SECONDS
        while b"\n" not in buffer:
            if len(buffer) > LIMIT or time.monotonic() > until:
                return None
            chunk = sock.recv(65536)
            if not chunk:
                return None
            buffer += chunk
        try:
            data = json.loads(buffer.partition(b"\n")[0].decode("utf-8"))
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def serve(self, sock: socket.socket) -> None:
        request = self.read(sock)
        if request is None:
            return self.refuse(sock, "request")
        sent = request.pop("mac", None)
        nonce = request.get("nonce")
        if not isinstance(sent, str) or not isinstance(nonce, str) or not hmac.compare_digest(sent, sign(self.key, nonce, hashlib.sha256(canonical(request).encode("utf-8")).hexdigest())):
            return self.refuse(sock, "key")
        deadline = request.get("deadline")
        raw, env, cwd = request.get("raw"), request.get("env"), request.get("cwd")
        if request.get("v") != 1 or not isinstance(deadline, (int, float)) or not isinstance(raw, str) or not isinstance(cwd, str) or not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            return self.refuse(sock, "request")
        if not self.judging.acquire(timeout=max(0.0, deadline - time.time())):
            return self.refuse(sock, "late")
        started = False
        try:
            if time.time() > deadline:
                return self.refuse(sock, "late")
            problem = self.differs(request)
            if problem:
                return self.refuse(sock, problem)
            try:
                from core import messages, procenv
            except ImportError:
                return self.refuse(sock, "procenv")  # the environment of the asking process cannot be given to the judgment: it judges itself
            self.say(sock, {"start": True, "mac": sign(self.key, nonce, "start")})  # from here the call may leave state and a record: a failure ends the connection, and the hook process judges (`lost-after-start`)
            started = True
            pid = request.get("pid")
            messages.reset()  # the language of this call is read again (it may be the environment of the asking process)
            with procenv.using(env, cwd):
                output = self.hook.answer(raw, self.root, origin="service", pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None)
            if not isinstance(output, dict):
                return
            self.say(sock, {"ok": True, "output": output, "mac": sign(self.key, nonce, canonical(output))})
        except OSError:
            return
        except BaseException as error:  # noqa: BLE001 - before the start line: the hook process judges; after it (`hook.answer` never raises) the connection just ends
            if not started:
                self.refuse(sock, "error:" + type(error).__name__)
        finally:
            self.judging.release()

    def differs(self, request: Dict[str, Any]) -> str:
        """"" when this process would judge as a hook process of the asker would; else why not."""
        if snapshot(self.root, self.engine) != self.loaded:
            return "stale"
        if request.get("tmp") != tempfile.gettempdir():
            return "tmp"
        if request.get("py") != [sys.version_info[0], sys.version_info[1]]:
            return "python"
        return ""
