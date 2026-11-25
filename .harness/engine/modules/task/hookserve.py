"""The board's judging service for hook calls (hook speed, 1.8.58).

Starting Python and loading the engine takes a hook process 4 to 8 seconds on a work computer, and the board, which is always open, has the engine loaded. So the board listens on a port of its own (127.0.0.1 only,
not the board's page: no pairing, no cookie) and a hook process asks it to judge the call (`hookclient.py`, started by `launch.py`). The judgment is `hook.answer`, the same function the hook process runs, so there is one
judgment and it is not copied. The protocol is in `hookclient.py`.

The service only ever makes the answer quicker. It refuses (`{"ok": false, "why": ...}`, and the hook process judges the call itself) whenever it is not sure its answer would be the one a hook process would give:
the request is not signed with the key of this board, it came too late (or the hook process has already gone: a call is never judged twice), the engine files are not the ones this process loaded (an upgrade without a
restart, a file edited), the temp folder or the Python of the hook process is not ours (the session locks and the text rules would not be the same), or `core.procenv` (the environment and folder of the asking
process for the judgment) is not there. One call is judged at a time.

A program that connects first has to prove nothing and is given nothing: the hello (a small line, read for 2 seconds at most) is answered with a signature of the client's nonce, so the hook process knows it is talking to
the board before it sends its environment; only then is the request read. At most `SLOTS` connections are served at once; the others are closed at once (the hook process judges for itself).

The file `.harness/runtime/hookserve.json` holds the port, the pid of this board, when that process was created (`born`: a pid used again by another process is not the board), and the key; it is written when the
service starts (mode 0600) and removed when it stops. Nothing here may stop the board: every failure of a request is an answer of `ok: false`, or a closed connection (the hook process then judges the call itself)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import select
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core import pace, state
from core.paths import runtime_dir, utc_now

FILE = "hookserve.json"
LIMIT = 8 * 1024 * 1024  # bytes of a request: a payload with a long file in it
READ_SECONDS = 10.0  # a client that sent no whole request line in this time is dropped (a thread must not wait for ever)
HELLO_LIMIT = 1024  # bytes of the hello line
HELLO_SECONDS = 2.0  # the hello is a few bytes: a client that takes longer is not a hook process
SLOTS = 16  # connections served at once; a hook process is never more than a few
MARGIN = 0.3  # seconds that must be left before the deadline of the request when the start line is sent: a call that the hook process is about to give up on is not begun
NONCE = re.compile(r"[0-9a-f]{32}\Z")
WAIT = 3.0  # seconds a hook process waits for the start line, before the pace factor
SKIP_DIRS = frozenset(["__pycache__", ".pytest_cache", ".git"])
SKIP_SUFFIXES = (".pyc", ".pyo", ".lock", ".tmp")
Stamp = Dict[str, Tuple[int, int]]


def file_of(root: Path) -> Path:
    return runtime_dir(root) / FILE


def same(one: str, other: str) -> bool:
    try:
        return hmac.compare_digest(one.encode("utf-8"), other.encode("utf-8"))
    except UnicodeError:
        return False


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
    state.replace_retrying(str(part), str(path))  # Windows refuses it for a moment while a hook process has the file open


class Listener(socketserver.ThreadingTCPServer):
    allow_reuse_address = False  # never: a second program must not be able to take the port over (on Windows `SO_REUSEADDR` allows exactly that)
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.slots = threading.BoundedSemaphore(SLOTS)
        super().__init__(*args, **kwargs)

    def verify_request(self, request: Any, client_address: Any) -> bool:
        """A connection over the number served at once is closed at once (a flood must not hold a thread for each connection)."""
        return self.slots.acquire(blocking=False)

    def process_request(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()  # the thread that would have given the place back did not start
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

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
        self.root = Path(root).resolve()  # as `hook.py` reads it from the environment (`_root()`): the records name the same folders either way
        self.engine = engine
        self.key = ""
        self.born = ""
        self.port = 0
        self.loaded: Stamp = {}
        self.server: Optional[Listener] = None
        self.thread: Optional[threading.Thread] = None
        self.judging = threading.Lock()  # one call is judged at a time: the engine's own memory (`targets`, `messages`) is not locked
        self.filing = threading.Lock()  # `start()` and the pace measure write the one file (and its one `.part`): not both at once
        self.counting = threading.Lock()
        self.busy = 0  # connections being served: a test waits for it to be 0 before it counts the records
        self.hook: Any = None

    # --- life ---------------------------------------------------------------------------------

    def start(self) -> bool:
        """True when it listens. Never raises: a board that cannot run the service is still a board (the hook processes judge themselves)."""
        try:
            import hook  # the engine's own judgment (hook.py is in the folder of the engine, which is on the path of the board)
            import hookclient  # (here and not above: a file that cannot be loaded keeps the service from starting, not the board from starting)

            if getattr(hook, "ENGINE_FAULT", None) is not None:
                return False
            self.born = hookclient.born(os.getpid()) or ""
            if not self.born:
                raise RuntimeError("the system does not say when this process was created: a hook process could not tell this board from another one")
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
        with self.filing:
            write_file(file_of(self.root), {"v": 2, "port": self.port, "pid": os.getpid(), "born": self.born, "key": self.key, "started": utc_now(), "wait": round(WAIT * pace.factor(self.root), 1)})

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
        with self.counting:
            self.busy += 1
        try:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # a small line must not wait for the next one (Windows holds it for up to 200 ms)
            except OSError:
                pass
            self.serve(sock)
        except BaseException:  # noqa: BLE001 - nothing of a request may reach the board; the hook process judges the call itself
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            with self.counting:
                self.busy -= 1

    def say(self, sock: socket.socket, data: Dict[str, Any]) -> None:
        sock.sendall(json.dumps(data).encode("utf-8") + b"\n")

    def refuse(self, sock: socket.socket, why: str) -> None:
        try:
            self.say(sock, {"ok": False, "why": why})
        except OSError:
            pass

    def read(self, sock: socket.socket, buffer: list, limit: int, seconds: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        """`(the next line as an object, True)`; `({}, True)` for a whole line that is not an object; `(None, False)` when no whole line of at most `limit` bytes came within `seconds` (the other side is not
        answered at all). `buffer` keeps what came after the line."""
        until = time.monotonic() + seconds
        while b"\n" not in buffer[0]:
            left = until - time.monotonic()
            if len(buffer[0]) > limit or left <= 0:
                return None, False
            sock.settimeout(left)
            try:
                chunk = sock.recv(min(65536, limit + 1))
            except OSError:  # a timeout too
                return None, False
            if not chunk:
                return None, False
            buffer[0] += chunk
        text, _, buffer[0] = buffer[0].partition(b"\n")
        if len(text) > limit:
            return None, False
        try:
            data = json.loads(text.decode("utf-8"))
        except ValueError:
            return {}, True
        return (data if isinstance(data, dict) else {}), True

    def serve(self, sock: socket.socket) -> None:
        buffer = [b""]
        hello, whole = self.read(sock, buffer, HELLO_LIMIT, HELLO_SECONDS)  # nothing private is read before the other side has heard that this is the board
        if hello is None:
            return
        nonce = hello.get("nonce")
        if hello.get("v") != 2 or not isinstance(nonce, str) or not NONCE.match(nonce) or len(hello) != 2:
            return self.refuse(sock, "request")
        self.say(sock, {"hello": sign(self.key, nonce, "hello")})
        request, whole = self.read(sock, buffer, LIMIT, READ_SECONDS)
        if not request:
            return self.refuse(sock, "request") if whole else None
        sent = request.pop("mac", None)
        if not isinstance(sent, str) or request.get("nonce") != nonce or not same(sent, sign(self.key, nonce, hashlib.sha256(canonical(request).encode("utf-8")).hexdigest())):
            return self.refuse(sock, "key")
        deadline = request.get("deadline")
        raw, env, cwd = request.get("raw"), request.get("env"), request.get("cwd")
        if request.get("v") != 2 or not isinstance(deadline, (int, float)) or not isinstance(raw, str) or not isinstance(cwd, str) or not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            return self.refuse(sock, "request")
        sock.settimeout(READ_SECONDS)  # what is written from here (a short line each) must not wait for ever either
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
            problem = self.not_worth_starting(sock, deadline)  # the work above took time: the hook process may have given up, and it then judges the call itself; a call is not judged twice
            if problem:
                return self.refuse(sock, problem)
            self.say(sock, {"start": True, "mac": sign(self.key, nonce, "start")})  # from here the call may leave state and a record: a failure ends the connection, and the hook process judges (`lost-after-start`)
            started = True
            pid = request.get("pid")
            messages.reset()  # the language of this call is read again (it may be the environment of the asking process)
            with procenv.using(env, cwd):
                output = self.hook.answer(raw, self.root, origin="service", pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None, nonce=nonce)
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

    def not_worth_starting(self, sock: socket.socket, deadline: float) -> str:
        """"" when the call may begin; else why not. It does not when the time left is under MARGIN, when the hook process has closed the connection (it gave up waiting), and on any doubt about either."""
        if time.time() + MARGIN > deadline:
            return "late"
        try:
            ready, _, _ = select.select([sock], [], [], 0)
            if ready:  # the hook process has sent nothing since its request: what can be read is the end of the connection (or something that is not the protocol)
                return "closed"
        except (OSError, ValueError):
            return "closed"
        return ""

    def differs(self, request: Dict[str, Any]) -> str:
        """"" when this process would judge as a hook process of the asker would; else why not."""
        if snapshot(self.root, self.engine) != self.loaded:
            return "stale"
        env = request.get("env") or {}
        for name in ("TMPDIR", "TEMP", "TMP"):  # where the session locks are made: the board and the hook process must find the same ones
            theirs, ours = env.get(name), os.environ.get(name)
            if (theirs is None) != (ours is None) or (theirs is not None and os.path.normcase(theirs) != os.path.normcase(ours)):
                return "tmp"
        if request.get("py") != [sys.version_info[0], sys.version_info[1]]:
            return "python"
        return ""
