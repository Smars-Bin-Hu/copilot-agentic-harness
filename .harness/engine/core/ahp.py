"""A small client for the Agent Host Protocol of VS Code (1.6, B71). Python standard library only.

The board starts its own agent host (`code agent host`, 1.8.x: `core.agenthost`), which listens on a local TCP port with a token it was given.
The wire is a WebSocket (one HTTP upgrade, then masked text frames) that carries JSON-RPC 2.0.
Everything here comes from what was checked on a real VS Code (macOS, 1.144) and from reading its code.

Rules this module keeps:
- The token lives in the `Endpoint` object in memory only. It is never printed, logged, stored, or put in an error: `scrub` takes it out of any text.
- `initialize` carries no `clientInfo`: the host then records the client as `vscode`, and the Agents window shows what we make.
- `disposeSession` is never called. It deletes the chat's `events.jsonl`. There is no function for it here.
- Starting `code` takes a second or more on a work PC (virus scan): it is run by the one background thread of the board, seldom.
- A connection is used by one thread. It is not thread safe.
"""

from __future__ import annotations

import base64
import collections
import datetime
import json
import os
import re
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, unquote, urlparse
from . import pace, procrun

PROTOCOL = "1.1.0"
CLI_TIMEOUT = 25  # seconds for a `code` command (`--version`, `<file>`)
CALL_TIMEOUT = 20
CREATE_TIMEOUT = 40  # 1.8.6: `createSession` on a busy work computer took more than CALL_TIMEOUT (1.8.7: the board waits with no limit; a caller without a reader still uses it)
READ_SLICE = 0.5  # seconds the reader waits for bytes before it looks whether the connection was closed
LATE_KEPT = 50  # answers that came after their caller stopped waiting, kept for the record
CLI_ENV = "HARNESS_VSCODE_CLI"  # a person may point at the `code` command by hand

# `status` of a session or chat is a set of bits (checked on real sessions)
IDLE, ERROR, IN_PROGRESS, INPUT_NEEDED, IS_READ, ARCHIVED = 1, 2, 8, 24, 32, 64
LOCAL_PROVIDER = "copilotcli"  # the chats of GitHub Copilot; other providers (claude, codex) are not ours
FUSION_ID = "auto"  # Copilot Fusion: Copilot picks the model for each request
FUSION_STANDARD = "balance"  # its lowest tier
GITHUB_RESOURCE = "https://api.github.com"  # what `authenticate` signs in to: Copilot's `protectedResources` names it


class AhpError(Exception):
    """The host answered with an error, or the exchange broke."""


SLOW = re.compile(r": no answer in (\d+(?:\.\d+)?) s$")
WORDS_MAX = 200  # characters of the host's own words a page shows


def problem_of(error: BaseException) -> Tuple[str, str]:
    """What went wrong with the host, for a person (1.8.6): (`slow`, seconds) when it did not answer in time; (`copilot`, "") when Copilot itself is not ready in VS Code
    (signed out, or still starting: `Provider copilotcli is not ready`, `Client is not connected`); (`said`, its words on one line, at most WORDS_MAX characters) for any other
    error of the exchange; (`other`, "") for an error that is not the host's, whose words may hold a path of this computer."""
    if not isinstance(error, AhpError):
        return ("other", "")
    text = " ".join(str(error).split())
    found = SLOW.search(text)
    if found:
        return ("slow", found.group(1))
    lower = text.lower()
    if ("provider" in lower and "not ready" in lower) or "not connected" in lower:
        return ("copilot", "")
    return ("said", text if len(text) <= WORDS_MAX else text[:WORDS_MAX - 1].rstrip() + "\u2026")


class NotReady(AhpError):
    """No connection yet. `why`: `no-cli` (no `code` command found), `cli-failed`, `cli-slow` (it did not answer in time: tried again), `none` (no endpoint: VS Code is not open, or still starting), `many` (several windows, none is ours)."""

    def __init__(self, why: str, text: str = "") -> None:
        super().__init__(text or why)
        self.why = why


class ConnectionClosed(AhpError):
    pass


# --- the `code` command ------------------------------------------------------------------------------------------

def standard_places(environ: Optional[Dict[str, str]] = None, platform: Optional[str] = None) -> List[str]:
    """Where the `code` command is when VS Code was installed the usual way, most likely first. The shim of a VS Code terminal (`remote-cli`) is never one of them."""
    env = os.environ if environ is None else environ
    kind = platform or sys.platform
    home = os.path.expanduser("~") if environ is None else env.get("HOME", "")
    if kind == "darwin":
        app = "Visual Studio Code.app/Contents/Resources/app/bin/code"
        return [f"/Applications/{app}", os.path.join(home, "Applications", app), "/usr/local/bin/code", "/opt/homebrew/bin/code"]
    if kind.startswith("win"):
        places = []
        for key, folder in (("LOCALAPPDATA", "Programs\\Microsoft VS Code"), ("ProgramFiles", "Microsoft VS Code"), ("ProgramFiles(x86)", "Microsoft VS Code")):
            if env.get(key):
                places.append(env[key].rstrip("\\/") + "\\" + folder + "\\bin\\code.cmd")
        return places
    return ["/usr/bin/code", "/usr/share/code/bin/code", "/snap/bin/code", "/opt/visual-studio-code/bin/code"]


def switched_off(environ: Optional[Dict[str, str]] = None) -> bool:
    """`HARNESS_VSCODE_CLI=off`: no link to VS Code at all (the tests set it, so no test ever touches the real VS Code of the machine)."""
    return (os.environ if environ is None else environ).get(CLI_ENV, "").strip().lower() == "off"


def find_code(environ: Optional[Dict[str, str]] = None, platform: Optional[str] = None, exists: Callable[[str], bool] = os.path.isfile) -> Optional[str]:
    """The `code` command: the one a person set (`HARNESS_VSCODE_CLI`), the standard install places, then PATH. None when there is none: VS Code is not installed here."""
    env = os.environ if environ is None else environ
    if switched_off(env):
        return None
    chosen = env.get(CLI_ENV, "").strip()
    if chosen and exists(chosen):
        return chosen
    for place in standard_places(env, platform):
        if exists(place):
            return place
    if environ is None:
        found = shutil.which("code")
        if found and "remote-cli" not in found.replace("\\", "/"):
            return found
    return None


def code_version(code: str) -> str:
    """The version of the VS Code a `code` command belongs to, from its `package.json` (1.8.x): read from a file, no program started. Empty when it cannot be read."""
    real = os.path.realpath(code)
    top = os.path.dirname(os.path.dirname(real))  # .../app/bin/code (macOS), <install>/bin/code.cmd (Windows), /usr/share/code/bin/code (Linux)
    for place in (os.path.join(top, "package.json"), os.path.join(top, "resources", "app", "package.json")):
        try:
            with open(place, encoding="utf-8") as handle:
                found = json.load(handle).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(found, str) and re.match(r"^\d+\.\d+", found):
            return found
    return ""


_CODE_LOCK = threading.Lock()  # 1.8.15: one `code agent ...` at a time from this process (the link thread, the launch settings): two slow ones at once only made each other slower


def call_timeout() -> float:
    return pace.scaled(CALL_TIMEOUT)


def create_timeout() -> float:
    return pace.scaled(CREATE_TIMEOUT)


def run_code(code: str, arguments: List[str], timeout: Optional[float] = None, extra: Optional[Dict[str, str]] = None) -> str:
    """Run the `code` command and return what it printed. Called from the background thread of the board only, never from a page request.
    `extra`: variables for a VS Code this starts (tool folders, CA bundle: core.launchenv); one that is open already keeps its own."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("VSCODE_IPC") and key != "ELECTRON_RUN_AS_NODE"}  # the shim of a VS Code terminal does not know `agent`
    env.update(extra or {})
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    timeout = pace.scaled(CLI_TIMEOUT) if timeout is None else timeout  # a caller's own limit is used as it is
    try:
        if arguments[:1] == ["agent"]:  # only the asks of the agent host wait for each other; opening a folder for the person never waits behind one
            with _CODE_LOCK:
                done = procrun.run([code] + arguments, capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
        else:
            done = procrun.run([code] + arguments, capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise NotReady("cli-slow", f"no answer in {timeout:g} s") from None  # a busy computer, or a VS Code that is still starting: the link tries again, the person waits (1.7.41)
    except (OSError, subprocess.SubprocessError) as error:
        raise NotReady("cli-failed", type(error).__name__) from None
    if done.returncode != 0:
        raise NotReady("cli-failed", f"exit {done.returncode}")
    return done.stdout.decode("utf-8", "replace")


class Endpoint:
    """One live agent host. The token is kept in a private slot and left out of `repr`."""

    __slots__ = ("kind", "path", "pid", "instance", "_token")

    def __init__(self, kind: str, path: str, pid: Any, instance: str, token: str) -> None:
        self.kind, self.path, self.pid, self.instance, self._token = kind, path, pid, instance, token

    def __repr__(self) -> str:
        return f"Endpoint({self.kind} pid={self.pid})"

    def token(self) -> str:
        return self._token


def scrub(text: Any, secret: str = "") -> str:
    """Text that may be shown: the token is taken out of it."""
    out = str(text)
    if secret:
        out = out.replace(secret, "***").replace(quote(secret), "***")
    return out


class Backoff:
    """Waits that grow: 3 s, 6 s, ... up to `top`. `reset` after a success."""

    def __init__(self, first: float = 3.0, top: float = 60.0) -> None:
        self.first, self.top, self.now = first, top, 0.0

    def next(self) -> float:
        self.now = self.first if not self.now else min(self.top, self.now * 2)
        return self.now

    def reset(self) -> None:
        self.now = 0.0


# --- the wire: WebSocket frames -----------------------------------------------------------------------------------

def encode_frame(data: bytes, opcode: int = 1, mask: Optional[bytes] = None) -> bytes:
    """One masked client frame (the protocol says a client masks)."""
    mask = os.urandom(4) if mask is None else mask
    size = len(data)
    if size < 126:
        head = bytes([0x80 | opcode, 0x80 | size])
    elif size < 65536:
        head = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", size)
    else:
        head = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", size)
    return head + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))


class Decoder:
    """Frames from the host, fed as bytes arrive. `feed` returns the whole messages that are complete: (opcode, payload) with opcode 1 (text), 8 (close), 9 (ping), 10 (pong).
    A message sent in pieces (opcode 0 continues) is joined."""

    def __init__(self) -> None:
        self.buffer = b""
        self.parts = b""
        self.first = 0

    def feed(self, data: bytes) -> List[Tuple[int, bytes]]:
        self.buffer += data
        out: List[Tuple[int, bytes]] = []
        while True:
            buffer = self.buffer
            if len(buffer) < 2:
                return out
            first, second = buffer[0], buffer[1]
            size, at = second & 127, 2
            if size == 126:
                if len(buffer) < 4:
                    return out
                size, at = struct.unpack(">H", buffer[2:4])[0], 4
            elif size == 127:
                if len(buffer) < 10:
                    return out
                size, at = struct.unpack(">Q", buffer[2:10])[0], 10
            masked = bool(second & 128)
            if masked:
                at += 4
            if len(buffer) < at + size:
                return out
            body = buffer[at:at + size]
            if masked:
                key = buffer[at - 4:at]
                body = bytes(byte ^ key[index % 4] for index, byte in enumerate(body))
            self.buffer = buffer[at + size:]
            opcode = first & 15
            if opcode >= 8:  # a control frame may come between the pieces of a message
                out.append((opcode, body))
                continue
            if opcode:
                self.first = opcode
                self.parts = b""
            self.parts += body
            if first & 128:
                out.append((self.first or 1, self.parts))
                self.parts, self.first = b"", 0


# --- transport: one socket, read with a wait ------------------------------------------------------------

class Tcp:
    """The board's own standalone agent host (1.8.x, core.agenthost) listens on a local TCP port: `path` is `host:port`."""

    def __init__(self, path: str) -> None:
        host, _, port = path.rpartition(":")
        self.sock = socket.create_connection((host.strip("[]") or "localhost", int(port)), timeout=call_timeout())
        self.sock.settimeout(call_timeout())

    def wait(self, timeout: float) -> bool:
        return bool(select.select([self.sock], [], [], max(0.0, timeout))[0])

    def read(self) -> bytes:
        return self.sock.recv(65536)

    def write(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def open_transport(endpoint: Endpoint) -> Any:
    if endpoint.kind != "tcp":
        raise NotReady("cli-failed", "only a TCP endpoint of the board's own agent host is known")
    return Tcp(endpoint.path)


# --- the connection --------------------------------------------------------------------------------------------

class Connection:
    """JSON-RPC over the frames. `notices` are the notifications that came while a call waited; `next_notice` hands them out, oldest first.

    Two ways to use it. Without a reader, whoever waits reads: one caller at a time (the tests, a command line). With `start_reader()` (1.8.7, the board's link), one thread reads
    the connection and hands each answer to the call that waits for it by its id, and each notification to `next_notice`: several threads may call at once, an answer may come
    in any order or very late, and a call may wait with no limit (`timeout=None`). A closed connection ends every call that waits."""

    def __init__(self, transport: Any, token: str = "") -> None:
        self.transport = transport
        self._token = token
        self.decoder = Decoder()
        self.notices: Deque[Dict[str, Any]] = collections.deque()
        self.counter = 0
        self.closed = False
        self._reader: Optional[threading.Thread] = None
        self._write = threading.Lock()  # one frame at a time on the wire
        self._state = threading.Condition()  # with a reader: `notices`, `_waiting`, `counter`
        self._waiting: Dict[int, Dict[str, Any]] = {}  # id -> {event, message, error, method}
        self._given_up: Dict[int, Tuple[str, float]] = {}  # id -> (method, when its caller stopped waiting)
        self.late: Deque[Dict[str, Any]] = collections.deque(maxlen=LATE_KEPT)  # {method, id, late_s}: answers nobody waited for any more
        self.default_timeout: Optional[float] = call_timeout()  # what a call waits when it names no time (the board's link sets more)
        self.pid: Any = None  # the process of the agent host, from the endpoint the board made
        self.instance = ""

    def upgrade(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        self.transport.write(("GET /?tkn=%s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (quote(self._token, safe=""), key)).encode())
        raw = b""
        end = time.monotonic() + call_timeout()
        while b"\r\n\r\n" not in raw:
            if time.monotonic() > end or not self.transport.wait(max(0.0, end - time.monotonic())):
                raise AhpError("no answer to the upgrade")
            data = self.transport.read()
            if not data:
                raise ConnectionClosed("the host closed the connection")
            raw += data
        head, rest = raw.split(b"\r\n\r\n", 1)
        line = head.split(b"\r\n")[0].decode("latin-1")
        if " 101 " not in line + " ":
            raise AhpError("the host refused the upgrade: " + line[:60])
        if rest:
            self.absorb(self.decoder.feed(rest))

    def send(self, message: Dict[str, Any]) -> None:
        with self._write:
            self.transport.write(encode_frame(json.dumps(message).encode("utf-8")))

    def next_id(self) -> int:
        with self._state:
            self.counter += 1
            return self.counter

    def start_reader(self) -> None:
        """From now on one thread reads the connection (see the class). Once only; after `upgrade` and `hello`."""
        if self._reader is not None:
            return
        self._reader = threading.Thread(target=self._read_loop, name="ahp-reader", daemon=True)
        self._reader.start()

    def reading(self) -> bool:
        return self._reader is not None

    def _read_loop(self) -> None:
        try:
            while not self.closed:
                for message in self.pump(READ_SLICE):
                    self._route(message)
        except (AhpError, OSError, ValueError):
            pass
        finally:
            with self._state:
                self.closed = True
                for entry in self._waiting.values():
                    entry["error"] = ConnectionClosed("the connection closed while the call waited")
                    entry["event"].set()
                self._waiting.clear()
                self._state.notify_all()

    def _route(self, message: Dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            with self._state:
                entry = self._waiting.pop(message["id"], None)
                if entry is None:
                    gone = self._given_up.pop(message["id"], None)
                    self.late.append({"method": gone[0] if gone else "", "id": message["id"], "late_s": round(time.monotonic() - gone[1], 1) if gone else None})
                    return
                entry["message"] = message  # under the lock: a caller whose wait runs out at this moment finds the answer, not an empty one
                entry["event"].set()
        elif "method" in message and "id" in message:  # the host asks something: we know no method
            self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "method not found"}})
        elif "method" in message:
            with self._state:
                self.notices.append(message)
                self._state.notify_all()

    def absorb(self, frames: List[Tuple[int, bytes]]) -> List[Dict[str, Any]]:
        """Frames to messages. A ping is answered, a close ends the connection."""
        out: List[Dict[str, Any]] = []
        for opcode, body in frames:
            if opcode == 9:
                with self._write:
                    self.transport.write(encode_frame(body, 10))
            elif opcode == 8:
                self.closed = True
                raise ConnectionClosed("the host closed the connection")
            elif opcode == 1:
                try:
                    message = json.loads(body.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(message, dict):
                    out.append(message)
        return out

    def pump(self, timeout: float) -> List[Dict[str, Any]]:
        """Wait up to `timeout` seconds for the host to say something; the messages that came (maybe none)."""
        if self.closed:
            raise ConnectionClosed("closed")
        if not self.transport.wait(timeout):
            return []
        try:
            data = self.transport.read()
        except OSError as error:
            raise ConnectionClosed(type(error).__name__) from None
        if not data:
            self.closed = True
            raise ConnectionClosed("the host closed the connection")
        return self.absorb(self.decoder.feed(data))

    def next_notice(self, timeout: float = 0.0) -> Optional[Dict[str, Any]]:
        """The next notification, waiting up to `timeout` seconds. A request of the host to us gets `method not found`."""
        end = time.monotonic() + max(0.0, timeout)
        if self._reader is not None:
            with self._state:
                while not self.notices:
                    if self.closed:
                        raise ConnectionClosed("closed")
                    left = end - time.monotonic()
                    if left <= 0:
                        return None
                    self._state.wait(left)
                return self.notices.popleft()
        while True:
            if self.notices:
                return self.notices.popleft()
            for message in self.pump(max(0.0, end - time.monotonic())):
                self.sort(message)
            if self.notices:
                return self.notices.popleft()
            if time.monotonic() >= end:
                return None

    def sort(self, message: Dict[str, Any]) -> None:
        if "method" in message and "id" in message:  # the host asks something: we know no method
            self.send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "method not found"}})
        elif "method" in message:
            self.notices.append(message)

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = -1.0) -> Any:
        """Ask the host and wait for its answer, at most `timeout` seconds (None: until it answers or the connection closes; left out: `default_timeout`)."""
        if timeout is not None and timeout < 0:
            timeout = self.default_timeout
        if self._reader is not None:
            return self._call_read(method, params, timeout)
        timeout = call_timeout() if timeout is None else timeout  # without a reader, nobody would read the answer of a wait with no end
        self.counter += 1
        mine = self.counter
        self.send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                raise AhpError(f"{method}: no answer in {timeout:g} s")
            batch = self.pump(left)
            for at, message in enumerate(batch):
                if message.get("id") == mine and "method" not in message:
                    for later in batch[at + 1:]:  # what came in the same read after the answer is kept, not dropped
                        self.sort(later)
                    if "error" in message:
                        error = message["error"] if isinstance(message["error"], dict) else {}
                        raise AhpError(scrub(f"{method} failed: {error.get('message') or message['error']}", self._token))
                    return message.get("result")
                self.sort(message)

    def _call_read(self, method: str, params: Optional[Dict[str, Any]], timeout: Optional[float]) -> Any:
        entry: Dict[str, Any] = {"event": threading.Event(), "message": None, "error": None, "method": method}
        with self._state:
            if self.closed:
                raise ConnectionClosed("closed")
            self.counter += 1
            mine = self.counter
            self._waiting[mine] = entry
        try:
            self.send({"jsonrpc": "2.0", "id": mine, "method": method, "params": params or {}})
        except (OSError, ValueError):  # a broken or closed transport: the connection is going, not the host saying no
            with self._state:
                self._waiting.pop(mine, None)
            raise ConnectionClosed("the connection broke while the request was written") from None
        if not entry["event"].wait(timeout):
            with self._state:
                if self._waiting.pop(mine, None) is not None:
                    self._given_up[mine] = (method, time.monotonic())
                    while len(self._given_up) > LATE_KEPT:
                        self._given_up.pop(next(iter(self._given_up)))
                    raise AhpError(f"{method}: no answer in {timeout:g} s")
        if entry["error"] is not None:
            raise entry["error"]
        message = entry["message"] or {}
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            raise AhpError(scrub(f"{method} failed: {error.get('message') or message['error']}", self._token))
        return message.get("result")

    def hello(self) -> Dict[str, Any]:
        """`initialize`, without `clientInfo` (the host then records the client as `vscode`)."""
        return self.call("initialize", {"protocolVersions": [PROTOCOL], "clientId": str(uuid.uuid4())}) or {}

    def subscribe(self, channel: str, timeout: Optional[float] = -1.0) -> Dict[str, Any]:
        """The state of a channel as it is now, and a stream of its actions after it. Returns the snapshot's `state`."""
        return ((self.call("subscribe", {"channel": channel}, timeout) or {}).get("snapshot") or {}).get("state") or {}

    def unsubscribe(self, channel: str, timeout: Optional[float] = -1.0) -> None:
        self.call("unsubscribe", {"channel": channel}, timeout)

    def dispatch(self, channel: str, action: Dict[str, Any]) -> None:
        """A client action on a chat or session channel: a notification, no answer (the host pushes the state it made of it). Used for a message, a steer and a stop."""
        self.send({"jsonrpc": "2.0", "method": "dispatchAction", "params": {"channel": channel, "clientSeq": self.next_id(), "action": action}})

    def authenticate(self, github_token: str, timeout: Optional[float] = -1.0) -> None:
        """Sign the whole host in to Copilot with a GitHub token (1.8.x, the board's own host). The sign-in is the host's, not the connection's, and lives in its memory
        only: after a host restart it is handed again. The token is taken out of any error."""
        try:
            self.call("authenticate", {"resource": GITHUB_RESOURCE, "token": github_token}, timeout)
        except AhpError as error:
            raise type(error)(scrub(str(error), github_token)) from None

    def sessions(self, timeout: Optional[float] = -1.0) -> List[Dict[str, Any]]:
        return list((self.call("listSessions", {}, timeout) or {}).get("items") or [])

    def close(self) -> None:
        self.closed = True
        self.transport.close()


def connect(endpoint: Endpoint) -> Connection:
    """Open the endpoint, upgrade, `initialize`. The caller keeps the Connection in one thread."""
    transport = open_transport(endpoint)
    link = Connection(transport, endpoint.token())
    link.pid, link.instance = endpoint.pid, endpoint.instance
    try:
        link.upgrade()
        link.hello()
    except BaseException:
        link.close()
        raise
    return link


# --- reading what the host says ---------------------------------------------------------------------------------

def uri_path(uri: str) -> str:
    """The folder of a `file:///` address as the OS writes it: `file:///c%3A/x` is `c:/x`; a trailing slash and the case of a drive letter do not matter."""
    parsed = urlparse(uri or "")
    if parsed.scheme != "file":
        return ""
    path = unquote(parsed.path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":  # /c:/x
        path = path[1:]
    return path.replace("\\", "/").rstrip("/")


def same_folder(left: str, right: str) -> bool:
    a, b = left.replace("\\", "/").rstrip("/"), right.replace("\\", "/").rstrip("/")
    if not a or not b:
        return False
    if len(a) > 1 and a[1] == ":" or len(b) > 1 and b[1] == ":" or os.name == "nt":
        return a.lower() == b.lower()  # Windows: not case sensitive
    return a == b


def session_in(summary: Dict[str, Any], folder: str) -> bool:
    """Is the session of this folder: one of its working directories, or its project, is the folder."""
    places = [uri_path(item) for item in summary.get("workingDirectories") or []] + [uri_path((summary.get("project") or {}).get("uri", ""))]
    return any(same_folder(place, folder) for place in places)


def folder_uri(folder: Any) -> str:
    """The `file:///` address of a folder as the host wants it for `workingDirectories`. The path is not resolved: the host lists the chat under the address given, and `session_in` must find the folder again."""
    path = str(folder).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path  # c:/x -> /c:/x
    return "file://" + quote(path, safe="/:")


INITIATOR_KEY = "vscode.session.initiator"  # `_meta` of a session summary: who made the chat; `vscode` is what the Agents window of VS Code shows
def initiator_of(meta: Any) -> str:
    """The name in `_meta["vscode.session.initiator"]`: the host gives `{"name": "vscode"}` (checked live); a plain string is taken as it is."""
    value = (meta or {}).get(INITIATOR_KEY) if isinstance(meta, dict) else None
    if isinstance(value, dict):
        value = value.get("name")
    return str(value) if isinstance(value, str) else ""


PERMISSIONS = ("default", "assisted", "autoApprove")  # `config.autoApprove` of a chat (from `resolveSessionConfig`); autoApprove asks for nothing, the hooks and the gate still run


def status_name(bits: Any) -> str:
    """`input` (waits for the person), `busy`, `error` or `idle` from the status bits of a session."""
    if not isinstance(bits, int):
        return "unknown"
    if bits & 16:
        return "input"
    if bits & IN_PROGRESS:
        return "busy"
    if bits & ERROR:
        return "error"
    return "idle" if bits & IDLE else "unknown"


def is_ours(summary: Dict[str, Any]) -> bool:
    return summary.get("provider") == LOCAL_PROVIDER


def sdk_ids(state: Dict[str, Any]) -> Set[str]:
    """The ids Copilot gave the session behind this chat (`turn.usage._meta["vscode.modelCall"].sdkSessionId`; the hook calls it `session_id`).
    A chat has none until the model has been called once."""
    found: Set[str] = set()
    turns = list(state.get("turns") or [])
    if isinstance(state.get("activeTurn"), dict):
        turns.append(state["activeTurn"])
    for turn in turns:
        try:
            value = turn["usage"]["_meta"]["vscode.modelCall"]["sdkSessionId"]
        except (KeyError, TypeError):
            continue
        if isinstance(value, str) and value:
            found.add(value)
    return found


def utc_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def models_of(root_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The models a person may pick, from the root state of the host (`agents[].models` of Copilot, checked on a real VS Code): only those the policy enables (`policyState == "enabled"`;
    a model with no policyState is not offered: nothing says it is allowed). Copilot Fusion is the one exception: the host lists it with no policyState, and any other state keeps it out.
    `thinking`: the levels of `configSchema.properties.thinkingLevel`, or for Fusion its `tier`, with `key` (the name in `config`) and `labels`; None when the model has none."""
    out: List[Dict[str, Any]] = []
    for agent in root_state.get("agents") or []:
        if not isinstance(agent, dict) or agent.get("provider") != LOCAL_PROVIDER:
            continue
        for model in agent.get("models") or []:
            if not isinstance(model, dict) or not model.get("id"):
                continue
            fusion = model["id"] == FUSION_ID and "policyState" not in model
            if model.get("policyState") != "enabled" and not fusion:
                continue
            properties = (model.get("configSchema") or {}).get("properties") or {}
            key = "tier" if model["id"] == FUSION_ID else "thinkingLevel"
            level = properties.get(key) or {}
            choices = named(level)
            levels = [str(item["id"]) for item in choices]
            size = properties.get("contextSize") or {}
            sizes = named(size)
            out.append({"id": str(model["id"]), "name": str(model.get("name") or model["id"]), "price": str((model.get("_meta") or {}).get("priceCategory") or ""),
                        "thinking": {"levels": levels, "default": level.get("default"), "key": key, "labels": {str(item["id"]): item["label"] for item in choices}} if levels else None, "context": {"sizes": sizes, "default": size.get("default")} if sizes else None})
    return out


def model_choice(model: Dict[str, Any], level: str = "", size: Any = 0) -> Dict[str, Any]:
    """A model of `models_of` with a level and a context size (`contextSize`), in the shape of `message.model`."""
    key = (model.get("thinking") or {}).get("key") or "thinkingLevel"
    config = {**({key: level} if level else {}), **({"contextSize": size} if size else {})}
    return {"id": model["id"], **({"config": config} if config else {})}


def context_size(model: Dict[str, Any], wanted: Any) -> Any:
    """The context size of `model` that `wanted` names, as the host spells it (a page sends it as text); None when the model has no such size. 0 or empty: none asked."""
    if wanted in (None, "", 0, "0"):
        return 0
    return next((item["id"] for item in ((model.get("context") or {}).get("sizes") or []) if str(item["id"]) == str(wanted).strip()), None)


def named(schema: Any) -> List[Dict[str, Any]]:
    """The choices of a setting in a schema of the host: `[{id, label}]`, from its `enum` and `enumLabels`."""
    schema = schema if isinstance(schema, dict) else {}
    labels = schema.get("enumLabels") if isinstance(schema.get("enumLabels"), list) else []
    return [{"id": item, "label": str(labels[at]) if at < len(labels) else str(item)} for at, item in enumerate(schema.get("enum") or []) if isinstance(item, (str, int)) and not isinstance(item, bool)]


def limits_of(root_state: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """What decides the context window of every model Copilot lists, by model id, whatever its policy: `{window, output, size}` (`maxContextWindow`, `maxOutputTokens`, the default of
    `contextSize`; the last two only when the model has them). A model with no window is not in it."""
    out: Dict[str, Dict[str, int]] = {}
    positive = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0  # noqa: E731
    for agent in root_state.get("agents") or []:
        if not isinstance(agent, dict) or agent.get("provider") != LOCAL_PROVIDER:
            continue
        for model in agent.get("models") or []:
            if not isinstance(model, dict) or not model.get("id") or not positive(model.get("maxContextWindow")):
                continue
            size = (((model.get("configSchema") or {}).get("properties") or {}).get("contextSize") or {}).get("default")
            found = {"window": int(model["maxContextWindow"])}
            if positive(model.get("maxOutputTokens")):
                found["output"] = int(model["maxOutputTokens"])
            if positive(size):
                found["size"] = int(size)
            out[str(model["id"])] = found
    return out


PARTS_KEEP = 60  # parts of one turn kept in memory: the board shows the latest few; a turn of 500 tool calls must not grow without end
TEXT_KEEP = 24000  # characters of one text result the board keeps (a whole file or megabytes of command output must not sit in memory)
TEXT_HEAD = 8000  # of those, the characters from the start (the start of a file matters); the rest is the end (the end of an output matters)
CONTENT_ITEMS = 40  # items of one result kept; the rest is counted in a last `more` item
PARTIAL_KEEP = 4000  # characters of a tool call's input kept while the host still streams it
URI_KEEP = 2000  # characters of one uri or path of a result item
NOTE_KEEP = 500  # characters of one name or description of a subagent item
ERROR_KEEP = 2000  # characters of the error message of a failed call
AUTH_KEEP = 4000  # characters (as JSON) of the sign-in request of a call that waits for one
ENDED = ("completed", "failed", "cancelled", "pending-result-confirmation")  # a tool call in one of these takes no second result


CHAT_SETTINGS = ("mode", "autoApprove")  # both may change while a chat lives (`chatMutable`); a value set on the chat goes over the session's


def _text_bound(text: str, carried: int = 0) -> Tuple[str, int]:
    """`text` cut to its head and its tail, and how many characters are left out (`carried`: what an earlier cut already left out, so a second pass changes nothing)."""
    if len(text) <= TEXT_KEEP:
        return text, carried
    return text[:TEXT_HEAD] + text[len(text) - (TEXT_KEEP - TEXT_HEAD):], carried + len(text) - TEXT_KEEP


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _short(value: Any, limit: int) -> Optional[str]:
    """`value` when it is a string of at most `limit` characters, else None."""
    return value if isinstance(value, str) and len(value) <= limit else None


def _bounded_item(item: Any) -> Dict[str, Any]:
    kind = item.get("type") if isinstance(item, dict) else None
    kind = kind[:40] if isinstance(kind, str) and kind else "unknown"
    try:
        if not isinstance(item, dict):
            return {"type": kind, "cut": True}
        if kind == "text" and isinstance(item.get("text"), str):
            text, cut = _text_bound(item["text"], _count(item.get("cut")))
            return dict({"type": "text", "text": text}, **({"cut": cut} if cut else {}))
        if kind == "terminal":
            out: Dict[str, Any] = {"type": "terminal"}
            for key in ("title", "resource", "outputFilePath"):
                if isinstance(item.get(key), str):
                    out[key] = item[key][:URI_KEEP]
            if isinstance(item.get("isPty"), bool):
                out["isPty"] = item["isPty"]
            result = item.get("result")
            if isinstance(result, dict):
                preview, cut = _text_bound(result["preview"] if isinstance(result.get("preview"), str) else "", _count(result.get("cut")))
                code = result.get("exitCode")
                out["result"] = {"exitCode": code if isinstance(code, int) and not isinstance(code, bool) else None, "truncated": result.get("truncated") is True, "preview": preview}
                if cut:
                    out["result"]["cut"] = cut
            return out
        if kind == "fileEdit":
            out = {"type": "fileEdit"}
            for side in ("before", "after"):
                found = item.get(side)
                if isinstance(found, dict):
                    uri = _short(found.get("uri"), URI_KEEP)
                    inner = found.get("content")
                    inner_uri = _short(inner.get("uri"), URI_KEEP) if isinstance(inner, dict) else None
                    kept: Dict[str, Any] = {}
                    if uri is not None:
                        kept["uri"] = uri
                    if inner_uri is not None:
                        kept["content"] = {"uri": inner_uri}
                    out[side] = kept
            diff = item.get("diff")
            if isinstance(diff, dict):
                out["diff"] = {"added": _count(diff.get("added")), "removed": _count(diff.get("removed"))}
            return out
        if kind == "subagent":
            out = {"type": "subagent"}
            for key in ("resource", "title", "agentName", "description"):
                if isinstance(item.get(key), str):
                    out[key] = item[key][:NOTE_KEEP]
            return out
        if kind == "resource":
            out = {"type": "resource"}
            for key in ("uri", "contentType"):
                if isinstance(item.get(key), str):
                    out[key] = item[key][:URI_KEEP]
            if isinstance(item.get("sizeHint"), (int, float, str)) and not isinstance(item.get("sizeHint"), bool):
                out["sizeHint"] = item["sizeHint"] if not isinstance(item["sizeHint"], str) else item["sizeHint"][:NOTE_KEEP]
            return out
        if kind in ("embeddedResource", "image"):
            out = {"type": kind}
            if isinstance(item.get("contentType"), str):
                out["contentType"] = item["contentType"][:URI_KEEP]
            if isinstance(item.get("data"), str):
                out["size"] = len(item["data"])
            elif _count(item.get("size")):
                out["size"] = item["size"]  # a second pass: the data is gone, its size stays
            return out
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return {"type": kind, "cut": True}


def bounded_content(content: Any) -> List[Any]:
    """The result of a tool call (`content`: a list of items) cut to what the board keeps. It comes from outside and can be huge (a file, megabytes of output, base64 images), so: one linear pass, hard caps, never an exception. A text is cut to its head and tail (`cut`: the characters left out), a file edit keeps only the uris of its two sides
    (the text is fetched later), an image never keeps its data, an item in a shape not expected is `{type, cut: true}`, and items past `CONTENT_ITEMS` are counted in a last `more` item. Idempotent: a result already cut comes out the same."""
    if not isinstance(content, list):
        return []
    more = 0
    if content and isinstance(content[-1], dict) and content[-1].get("type") == "more" and len(content) > 1:  # the mark of an earlier cut
        more = _count(content[-1].get("count"))
        content = content[:-1]
    out = [_bounded_item(item) for item in content[:CONTENT_ITEMS]]
    more += max(0, len(content) - CONTENT_ITEMS)
    if more:
        out.append({"type": "more", "count": more})
    return out


def slim(turn: Any) -> Any:
    """A turn cut to what the board reads: the last `PARTS_KEEP` parts, and the result of each tool call (`content`, which can be big) cut by `bounded_content`."""
    if not isinstance(turn, dict):
        return turn
    parts = turn.get("responseParts")
    if not isinstance(parts, list):
        return turn
    kept = [slim_part(part) for part in parts[-PARTS_KEEP:]]
    gone = parts[:max(0, len(parts) - PARTS_KEEP)]
    return dict(turn, responseParts=kept, dropped=int(turn.get("dropped") or 0) + len(gone), droppedCalls=int(turn.get("droppedCalls") or 0) + _calls_in(gone))


def _calls_in(parts: List[Any]) -> int:
    """How many tool calls are among `parts` (B9: a round counts the calls that fell out of memory too)."""
    return sum(1 for part in parts if isinstance(part, dict) and part.get("kind") == "toolCall")


UNBOUNDED = ("structuredContent", "resultMetadata")  # of a tool call in a snapshot: no limit on their size, and no page reads them


def slim_part(part: Any) -> Any:
    """One part of a turn as the board keeps it: the result of a tool call cut by `bounded_content`, and without the fields of `UNBOUNDED` (`reduce_chat` never takes those either)."""
    if isinstance(part, dict) and part.get("kind") == "inputRequest" and isinstance(part.get("request"), dict) and isinstance(part["request"].get("id"), str):  # B8: a question, bounded
        kept_part = {"kind": "inputRequest", "request": input_kept(part["request"])}
        if isinstance(part.get("response"), str):
            kept_part["response"] = part["response"][:20]
        return kept_part
    call = part.get("toolCall") if isinstance(part, dict) else None
    if not isinstance(call, dict) or not ("content" in call or any(key in call for key in UNBOUNDED)):
        return part
    kept = {key: value for key, value in call.items() if key not in UNBOUNDED}
    if "content" in kept:
        kept["content"] = bounded_content(kept["content"])
    return dict(part, toolCall=kept)


def _contributor(value: Any) -> Optional[Dict[str, str]]:
    """Who made a tool call (`{kind: mcp, ...}`), kept when it is a small dict of strings; the guard of a sign-in request reads its kind."""
    if isinstance(value, dict) and len(value) <= 5 and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        return dict(value)
    return None


QUEUED_CHARS = 2000  # characters of a queued message the board keeps to show


def pending(item: Any) -> Optional[Dict[str, Any]]:
    """One message waiting in a chat (`queuedMessages[]`: `queued` goes after the turn, `steering` into it), cut to its id, kind and the start of its text."""
    if not isinstance(item, dict) or not item.get("id"):
        return None
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    return {"id": str(item["id"]), "kind": str(item.get("kind") or "queued"), "text": str(message.get("text") or item.get("text") or "")[:QUEUED_CHARS]}


def trimmed(state: Dict[str, Any], keep: int = 2) -> Dict[str, Any]:
    """A chat snapshot cut to what the board shows: the last turns and the one running, and the messages that wait. A long chat is big."""
    out = {"status": state.get("status"), "title": state.get("title"), "modifiedAt": state.get("modifiedAt"), "config": state.get("config"),
           "turns": [slim(turn) for turn in list(state.get("turns") or [])[-keep:]], "activeTurn": slim(state.get("activeTurn")),
           "queuedMessages": [found for found in (pending(item) for item in state.get("queuedMessages") or []) if found]}
    if state.get("turnsNextCursor") is not None:
        out["turnsNextCursor"] = state["turnsNextCursor"]  # where the host goes on when older turns are asked for
    if isinstance(state.get("activity"), str) and state["activity"].strip():
        out["activity"] = state["activity"][:ACTIVITY_KEEP]
    work = [background_kept(item) for item in state.get("backgroundWork") or [] if isinstance(item, dict) and isinstance(item.get("id"), str)]
    if work:
        out["backgroundWork"] = work[-BACKGROUND_KEEP:]
    return out


def queued(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """The messages that go after the running turn, oldest first: `{id, text}`."""
    return [{"id": item["id"], "text": item["text"]} for item in state.get("queuedMessages") or [] if isinstance(item, dict) and item.get("kind") == "queued"]


def resumable_turn(state: Dict[str, Any]) -> str:
    """The id of the last turn when it ended in an error the host says can be tried again (its last part: `{kind: error, resumable: true}`), and nothing runs. Empty: none."""
    turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
    if state.get("activeTurn") or not turns or turns[-1].get("state") != "error":
        return ""
    parts = turns[-1].get("responseParts") or []
    last = parts[-1] if parts and isinstance(parts[-1], dict) else {}
    return str(turns[-1].get("id") or "") if last.get("kind") == "error" and last.get("resumable") is True else ""


def last_error(state: Dict[str, Any]) -> Dict[str, Any]:
    """`{message, resumable}` of the error part that ended the last turn (1.8.4), when that turn ended in an error and nothing runs; empty otherwise. The message is on one line, at most 300 characters. A state in another shape gives an empty answer."""
    try:
        turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
        if state.get("activeTurn") or not turns or turns[-1].get("state") != "error":
            return {}
        parts = turns[-1].get("responseParts") or []
        last = parts[-1] if parts and isinstance(parts[-1], dict) else {}
        if last.get("kind") != "error":
            return {}
        words = " ".join(str(last.get("message") or "").split())
        return {"message": words if len(words) <= 300 else words[:299].rstrip() + "\u2026", "resumable": last.get("resumable") is True}
    except (AttributeError, TypeError):
        return {}


def _tool_call_action(call: Dict[str, Any], kind: str, action: Dict[str, Any]) -> None:
    """One action on one tool call of the running turn, with the guards of the host's reducer: an action that does not fit the call's status changes nothing (not even `_meta`)."""
    if _tool_call_step(call, kind, action) and isinstance(action.get("_meta"), dict):
        call["_meta"] = action["_meta"]


def _tool_call_step(call: Dict[str, Any], kind: str, action: Dict[str, Any]) -> bool:
    """True when the action fitted the status of the call and was applied."""
    status = call.get("status")
    if kind == "chat/toolCallDelta":
        if status != "streaming":
            return False
        if action.get("content") is not None:
            call["partialInput"] = (str(call.get("partialInput") or "") + str(action["content"]))[-PARTIAL_KEEP:]
        if action.get("invocationMessage") is not None:
            call["invocationMessage"] = action["invocationMessage"]
    elif kind == "chat/toolCallReady":
        call["status"] = "running" if action.get("confirmed") else "pending-confirmation"
        call.pop("partialInput", None)  # the whole input is here now
        for field in ("toolInput", "intention", "invocationMessage", "confirmationTitle", "options", "_meta", "confirmed"):
            if action.get(field) is not None:
                call[field] = action[field]
        if _contributor(action.get("contributor")) is not None:
            call["contributor"] = _contributor(action["contributor"])
    elif kind == "chat/toolCallConfirmed":
        if status != "pending-confirmation":
            return False
        if action.get("approved"):
            call["status"] = "running"
            call["confirmed"] = action.get("confirmed") or "user-action"  # B8: a call that waited and was let go was let go by a person (the board's own yes names no reason)
            if action.get("editedToolInput") is not None and isinstance(call.get("toolInput"), str):
                call["toolInput"] = action["editedToolInput"]
        else:
            call["status"] = "cancelled"
            for field in ("reason", "reasonMessage", "userSuggestion"):
                if action.get(field) is not None:
                    call[field] = action[field]
    elif kind == "chat/toolCallComplete":
        result = action.get("result") if isinstance(action.get("result"), dict) else {}
        if status in ENDED or (status == "auth-required" and result.get("success")):  # the host also wants a Ready first; an older host may not send one, and a call that ended must not stay "running" on the page
            return False
        call.pop("auth", None)
        call["success"] = bool(result.get("success", True))
        found = result.get("pastTenseMessage") if result.get("pastTenseMessage") is not None else action.get("pastTenseMessage")
        if found is not None:
            call["pastTenseMessage"] = found
        if "content" in result:
            call["content"] = bounded_content(result["content"])
        if isinstance(result.get("error"), dict):
            call["error"] = {"message": str(result["error"].get("message") or "")[:ERROR_KEEP]}
        if action.get("requiresResultConfirmation") and status != "auth-required":
            call["status"] = "pending-result-confirmation"
        else:
            call["status"] = "completed" if call["success"] else "failed"  # the host says `completed` with `success: false`; the page reads `failed`
    elif kind == "chat/toolCallResultConfirmed":
        if status != "pending-result-confirmation":
            return False
        if action.get("approved"):
            call["status"] = "completed" if call.get("success", True) else "failed"
        else:
            call["status"] = "cancelled"
            call["reason"] = "result-denied"
            call.pop("content", None)
    elif kind == "chat/toolCallContentChanged":
        if status != "running":
            return False
        call["content"] = bounded_content(action.get("content"))
    elif kind == "chat/toolCallAuthRequired":
        contributor = call.get("contributor")
        if status != "running" or not isinstance(contributor, dict) or contributor.get("kind") != "mcp":
            return False
        call["status"] = "auth-required"
        try:
            call["auth"] = auth_kept(action.get("auth"))
        except (TypeError, ValueError):
            call["auth"] = {"cut": True}
    elif kind == "chat/toolCallAuthResolved":
        if status != "auth-required":
            return False
        call["status"] = "running"
        call.pop("auth", None)
    return True


def reduce_chat(state: Dict[str, Any], action: Dict[str, Any], keep: int = 2) -> None:
    """Apply one action of a subscribed chat to a trimmed state, as the host's own reducer does (read from its code, with its status guards: an action that does not fit the status of a tool call changes nothing). Kept: the reply and the thinking (with its start and duration), each tool call with
    its status, input, a bounded result (`bounded_content`), the error message, the sign-in request and who made it, and the cursor for older turns (`turnsLoaded` adds no turns: the board keeps only the last `keep`)."""
    kind = str(action.get("type") or "")
    if kind == "chat/configChanged":
        state["config"] = {"values": {**config_values(state), **(action.get("config") or {})}}
        return
    if kind == "chat/pendingMessageSet":
        found = pending(action)
        if found:
            state["queuedMessages"] = [item for item in state.get("queuedMessages") or [] if item.get("id") != found["id"]] + [found]
        return
    if kind == "chat/pendingMessageRemoved":
        state["queuedMessages"] = [item for item in state.get("queuedMessages") or [] if not (item.get("id") == action.get("id") and item.get("kind", "queued") == (action.get("kind") or "queued"))]
        return
    if kind == "chat/queuedMessagesReordered" and isinstance(action.get("order"), list):
        waiting = {item.get("id"): item for item in state.get("queuedMessages") or []}
        first = [waiting.pop(ident) for ident in action["order"] if ident in waiting]
        state["queuedMessages"] = first + list(waiting.values())
        return
    if kind == "chat/turnResume":  # Try again: the last turn, ended in an error, runs again
        turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
        if not state.get("activeTurn") and turns and turns[-1].get("id") == action.get("turnId"):
            state["activeTurn"] = {key: value for key, value in turns[-1].items() if key not in ("state", "duration")}
            state["turns"] = turns[:-1]
        return
    if kind == "chat/truncated":  # kept: up to and with `turnId`; no `turnId`: nothing. A turn this cut state no longer holds changes nothing here
        turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
        ends = [at for at, turn in enumerate(turns) if turn.get("id") == action.get("turnId")]
        state["turns"] = turns[:ends[0] + 1] if ends else [] if action.get("turnId") is None else turns
        state["activeTurn"] = None
        return
    if kind == "chat/turnsLoaded":  # older turns were paged in: the board keeps only its last turns, so only the cursor is noted
        state["turnsNextCursor"] = action.get("turnsNextCursor")
        return
    if kind == "chat/activityChanged":  # B15: what the host says it is doing (loading plugins, settings), or nothing
        state["activity"] = action["activity"][:ACTIVITY_KEEP] if isinstance(action.get("activity"), str) and action["activity"].strip() else None
        return
    if kind == "chat/backgroundWorkSet" and isinstance(action.get("work"), dict) and isinstance(action["work"].get("id"), str):  # B16: a shell or subagent that runs on after its call
        work = background_kept(action["work"])
        listed = [item for item in state.get("backgroundWork") or [] if isinstance(item, dict) and item.get("id") != work["id"]]
        state["backgroundWork"] = (listed + [work])[-BACKGROUND_KEEP:]
        return
    if kind == "chat/backgroundWorkRemoved":
        state["backgroundWork"] = [item for item in state.get("backgroundWork") or [] if isinstance(item, dict) and item.get("id") != action.get("id")]
        return
    if kind == "chat/turnStarted":
        state["activeTurn"] = {"id": action.get("turnId"), "startedAt": action.get("startedAt"), "message": action.get("message"), "responseParts": [], "usage": None}
        state["modifiedAt"] = action.get("startedAt") or state.get("modifiedAt")
        return
    active = state.get("activeTurn")
    if not isinstance(active, dict) or action.get("turnId") != active.get("id"):
        return
    parts = active.setdefault("responseParts", [])
    if kind == "chat/responsePart" and isinstance(action.get("part"), dict):
        parts.append(action["part"])
    elif kind == "chat/delta":
        for part in parts:
            if part.get("kind") == "markdown" and part.get("id") == action.get("partId"):
                part["content"] = str(part.get("content") or "") + str(action.get("content") or "")
    elif kind == "chat/reasoning":  # the thinking text grows the same way; it is often empty (the host does not always send it)
        for part in parts:
            if part.get("kind") == "reasoning" and part.get("id") == action.get("partId"):
                part["content"] = str(part.get("content") or "") + str(action.get("content") or "")
                for field in ("startedAt", "duration"):
                    if action.get(field) is not None:
                        part[field] = action[field]
    elif kind == "chat/toolCallStart":
        call = {"toolCallId": action.get("toolCallId"), "toolName": action.get("toolName"), "displayName": action.get("displayName"), "intention": action.get("intention"), "status": "streaming"}
        if action.get("invocationMessage") is not None:
            call["invocationMessage"] = action["invocationMessage"]
        if isinstance(action.get("_meta"), dict):
            call["_meta"] = action["_meta"]  # a running `task` call names its subagent's chat here (1.8)
        if _contributor(action.get("contributor")) is not None:
            call["contributor"] = _contributor(action["contributor"])
        parts.append({"kind": "toolCall", "toolCall": call})
    elif kind == "chat/inputRequested" and isinstance(action.get("request"), dict) and isinstance(action["request"].get("id"), str):  # B8: a question of the agent is a part of the turn
        request = input_kept(action["request"])
        at = _open_input(parts, request["id"])
        if at is None:
            parts.append({"kind": "inputRequest", "request": request})
        else:
            parts[at] = {"kind": "inputRequest", "request": dict(request, answers=request.get("answers") or parts[at]["request"].get("answers"))}
    elif kind == "chat/inputAnswerChanged":
        at = _open_input(parts, action.get("requestId"))
        if at is not None and isinstance(action.get("questionId"), str):
            answers = dict(parts[at]["request"].get("answers") or {})
            if action.get("answer") is None:
                answers.pop(action["questionId"], None)
            else:
                answers[action["questionId"]] = _answer_kept(action["answer"])
            parts[at]["request"]["answers"] = answers or None
    elif kind == "chat/inputCompleted":
        at = _open_input(parts, action.get("requestId"))
        if at is not None:
            given = action.get("answers") if isinstance(action.get("answers"), dict) else {}
            answers = dict(parts[at]["request"].get("answers") or {}, **{str(key): _answer_kept(value) for key, value in list(given.items())[:INPUT_QUESTIONS]})
            parts[at]["request"]["answers"] = answers or None
            parts[at]["response"] = str(action.get("response") or "accept")[:20]
    elif kind.startswith("chat/toolCall"):
        for part in parts:
            call = part.get("toolCall") if isinstance(part, dict) and part.get("kind") == "toolCall" else None
            if isinstance(call, dict) and call.get("toolCallId") == action.get("toolCallId"):
                _tool_call_action(call, kind, action)
    elif kind == "chat/usage" and isinstance(action.get("usage"), dict):
        before, after = _compactions(active.get("usage")), _compactions(action["usage"])
        if before is not None and after is not None and after > before:  # B14: the context was compacted (the host counts it in the usage; it sends nothing else): a part of the turn says so
            parts.append({"kind": "compaction", "id": f"compact-{after}-{len(parts)}", "count": after, "before": _context_total(active.get("usage")), "after": _context_total(action["usage"])})
        active["usage"] = action["usage"]
    elif kind in ("chat/turnComplete", "chat/turnCancelled", "chat/error"):
        if kind == "chat/error" and isinstance(action.get("part"), dict):
            parts.append(action["part"])  # `{kind: error, resumable}`: whether Try again can be offered
        done = dict(active, state={"chat/turnComplete": "complete", "chat/turnCancelled": "cancelled"}.get(kind, "error"), duration=action.get("duration"))
        state["turns"] = (list(state.get("turns") or []) + [done])[-keep:]
        state["activeTurn"] = None
        return
    if len(parts) > PARTS_KEEP + 20:  # cut in steps, not on every action
        active["dropped"] = int(active.get("dropped") or 0) + len(parts) - PARTS_KEEP
        active["droppedCalls"] = int(active.get("droppedCalls") or 0) + _calls_in(parts[:len(parts) - PARTS_KEEP])
        del parts[:len(parts) - PARTS_KEEP]


# --- what the chat does besides its turn (B13-B16) ---------------------------------------------------------------------------
ACTIVITY_KEEP = 200
BACKGROUND_KEEP = 20


def background_kept(work: Dict[str, Any]) -> Dict[str, Any]:
    """A shell or subagent that runs in the background, as a page reads it: kind, id, label, command (cut), startedAt."""
    kept: Dict[str, Any] = {"id": work["id"][:200], "kind": str(work.get("kind") or "")[:20]}
    for key, cap in (("label", 200), ("command", 400), ("startedAt", 40)):
        if isinstance(work.get(key), str):
            kept[key] = work[key][:cap]
    return kept


def _attribution(usage: Any) -> Dict[str, Any]:
    meta = usage.get("_meta") if isinstance(usage, dict) and isinstance(usage.get("_meta"), dict) else {}
    return meta["contextAttribution"] if isinstance(meta.get("contextAttribution"), dict) else {}


def _compactions(usage: Any) -> Optional[int]:
    """How many times the session's context was compacted, as the host counts it in a usage; None: it does not say."""
    found = _attribution(usage).get("compactions")
    if isinstance(found, list):
        return len(found)
    return found if isinstance(found, int) and not isinstance(found, bool) else None


def _context_total(usage: Any) -> Optional[int]:
    found = _attribution(usage).get("totalTokens")
    if isinstance(found, (int, float)) and not isinstance(found, bool):
        return int(found)
    if isinstance(usage, dict) and isinstance(usage.get("inputTokens"), (int, float)) and not isinstance(usage.get("inputTokens"), bool):
        return int(usage["inputTokens"])
    return None


# --- the questions of the agent (B8): a part of the turn, bounded ---------------------------------------------------------
INPUT_TEXT = 4000  # characters of the message of a question, and of a free answer
INPUT_QUESTIONS = 20
INPUT_OPTIONS = 50


def _short_text(value: Any, cap: int) -> Optional[str]:
    return value[:cap] if isinstance(value, str) else None


def _answer_kept(value: Any) -> Any:
    """An answer as the host holds it (`{state, value: {kind, value}}` or plainer), with its texts cut and no deeper than it needs."""
    if isinstance(value, str):
        return value[:INPUT_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_answer_kept(item) for item in value[:INPUT_OPTIONS]]
    if isinstance(value, dict):
        return {str(key)[:60]: _answer_kept(item) for key, item in list(value.items())[:12]}
    return None


def input_kept(request: Dict[str, Any]) -> Dict[str, Any]:
    """A question request kept to what a page reads: its id, message, the questions (id, title, message, kind, options' ids and labels) and the answers so far; every text cut."""
    out: Dict[str, Any] = {"id": str(request.get("id"))[:200]}
    for key in ("message", "title"):
        if isinstance(request.get(key), str):
            out[key] = request[key][:INPUT_TEXT]
    questions = []
    for question in (request.get("questions") or [])[:INPUT_QUESTIONS] if isinstance(request.get("questions"), list) else []:
        if not isinstance(question, dict):
            continue
        kept = {key: _short_text(question.get(key), INPUT_TEXT if key == "message" else 400) for key in ("id", "title", "message", "kind") if isinstance(question.get(key), str)}
        options = question.get("options") if isinstance(question.get("options"), list) else []
        if options:
            kept["options"] = [{"id": str(item.get("id"))[:100], "label": str(item.get("label") or "")[:200]} for item in options[:INPUT_OPTIONS] if isinstance(item, dict)]
        questions.append(kept)
    if questions:
        out["questions"] = questions
    if isinstance(request.get("answers"), dict) and request["answers"]:
        out["answers"] = {str(key)[:200]: _answer_kept(value) for key, value in list(request["answers"].items())[:INPUT_QUESTIONS]}
    return out


def _open_input(parts: List[Any], ident: Any) -> Optional[int]:
    """The index of the question part `ident` that has no response yet, as the host finds it."""
    for at, part in enumerate(parts):
        if isinstance(part, dict) and part.get("kind") == "inputRequest" and "response" not in part and isinstance(part.get("request"), dict) and part["request"].get("id") == ident:
            return at
    return None


# --- what waits for a person (1.6, B75) --------------------------------------------------------------------------

def config_values(state: Dict[str, Any]) -> Dict[str, Any]:
    config = state.get("config") if isinstance(state.get("config"), dict) else {}
    return config.get("values") if isinstance(config.get("values"), dict) else {}


SUB_CHATS_KEPT = 20  # the newest chats of subagents a session state keeps


def sub_chat(summary: Any) -> Optional[Dict[str, Any]]:
    """A chat a tool call made in the session, the work of a subagent (`origin: {kind: tool, chat, toolCallId}`, read only; read from the host's code, 1.6.105): `{chat, parent, call, title,
    status}`. None for any other chat."""
    if not isinstance(summary, dict) or not summary.get("resource"):
        return None
    origin = summary.get("origin") if isinstance(summary.get("origin"), dict) else {}
    if origin.get("kind") != "tool" or not origin.get("chat") or not origin.get("toolCallId"):
        return None
    return {"chat": str(summary["resource"]), "parent": str(origin["chat"]), "call": str(origin["toolCallId"]), "title": str(summary.get("title") or "")[:120], "status": summary.get("status")}


def auth_kept(auth: Any) -> Any:
    """The sign-in request of a tool call as the board keeps it: without `oauthClient` (an OAuth client id and maybe its secret: never in memory, a file or a page), and `{cut: true}` when it is too big. Raises TypeError or ValueError on what is not JSON."""
    if isinstance(auth, dict):
        auth = {key: value for key, value in auth.items() if key != "oauthClient"}
    return auth if len(json.dumps(auth)) <= AUTH_KEEP else {"cut": True}


def need_slim(item: Dict[str, Any]) -> Dict[str, Any]:
    """An `inputNeeded` item with the result of its tool call cut as `slim_part` cuts it (a call that waits for its result to be confirmed carries the whole result), and its sign-in request as `auth_kept` keeps it (B5, 1.8.x)."""
    call = item.get("toolCall")
    if not isinstance(call, dict):
        return item
    call = slim_part({"toolCall": call})["toolCall"]
    if "auth" in call:
        try:
            call = dict(call, auth=auth_kept(call["auth"]))
        except (TypeError, ValueError):
            call = dict(call, auth={"cut": True})
    return dict(item, toolCall=call)


def trimmed_session(state: Dict[str, Any]) -> Dict[str, Any]:
    """A session snapshot cut to what the board reads of it: `inputNeeded[]` (the questions and tool confirmations that wait for a person), of its settings the two a person may
    change from the board (`mode`, `autoApprove`): the value and the choices the host offers, and the chats of its subagents (`subchats`, 1.6.105)."""
    items = state.get("inputNeeded")
    config = state.get("config") if isinstance(state.get("config"), dict) else {}
    schema = (config.get("schema") or {}).get("properties") or {}
    values = config_values(state)
    chats = state.get("chats") if isinstance(state.get("chats"), list) else []
    return {"inputNeeded": [need_slim(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else [],
            "config": {"values": {key: values.get(key) for key in CHAT_SETTINGS}, "choices": {key: named(schema.get(key)) for key in CHAT_SETTINGS}},
            "subchats": [found for found in (sub_chat(item) for item in chats) if found][-SUB_CHATS_KEPT:]}


def reduce_session(state: Dict[str, Any], action: Dict[str, Any]) -> None:
    """Apply `session/inputNeededSet` (an item came, or changed: same `id`) and `session/inputNeededRemoved` to a trimmed session state, and the chats of subagents that come, change and go."""
    kind = str(action.get("type") or "")
    items = state.setdefault("inputNeeded", [])
    if kind == "session/chatAdded":
        found = sub_chat(action.get("summary"))
        if found:
            state["subchats"] = ([item for item in state.get("subchats") or [] if item["chat"] != found["chat"]] + [found])[-SUB_CHATS_KEPT:]
        return
    if kind == "session/chatRemoved":
        state["subchats"] = [item for item in state.get("subchats") or [] if item["chat"] != str(action.get("chat") or "")]
        return
    if kind == "session/chatUpdated" and isinstance(action.get("changes"), dict):
        for item in state.get("subchats") or []:
            if item["chat"] == str(action.get("chat") or ""):
                if "title" in action["changes"]:
                    item["title"] = str(action["changes"]["title"] or "")[:120]
                if "status" in action["changes"]:
                    item["status"] = action["changes"]["status"]
        return
    if kind == "session/configChanged" and isinstance(state.get("config"), dict) and isinstance(action.get("config"), dict):
        state["config"]["values"].update({key: value for key, value in action["config"].items() if key in CHAT_SETTINGS})
    elif kind == "session/inputNeededSet" and isinstance(action.get("request"), dict) and action["request"].get("id"):
        new = need_slim(action["request"])
        for at, item in enumerate(items):
            if item.get("id") == new["id"]:
                items[at] = new
                return
        items.append(new)
    elif kind == "session/inputNeededRemoved":
        state["inputNeeded"] = [item for item in items if item.get("id") != action.get("id")]
