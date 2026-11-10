"""A small client for the Agent Host Protocol of VS Code (1.6, B71). Python standard library only.

VS Code runs an agent host for its chats. `code agent endpoints` prints where it listens and the token to connect: a unix socket on
macOS and Linux, a named pipe on Windows. The wire is a WebSocket (one HTTP upgrade, then masked text frames) that carries JSON-RPC 2.0.
Everything here comes from what was checked on a real VS Code (macOS, 1.144) and from reading its code.

Rules this module keeps:
- The token lives in the `Endpoint` object in memory only. It is never printed, logged, stored, or put in an error: `scrub` takes it out of any text.
- `initialize` carries no `clientInfo`: the host then records the client as `vscode`, and the Agents window shows what we make.
- `disposeSession` is never called. It deletes the chat's `events.jsonl`. There is no function for it here.
- Starting `code` takes a second or more on a work PC (virus scan): `endpoints` is read by the one background thread of the board, seldom.
- A connection is used by one thread. It is not thread safe.
"""

from __future__ import annotations

import base64
import collections
import datetime
import json
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote, unquote, urlparse

PROTOCOL = "1.1.0"
CLI_TIMEOUT = 25  # seconds for `code agent endpoints` and `code <folder>`
CALL_TIMEOUT = 20
CLI_ENV = "HARNESS_VSCODE_CLI"  # a person may point at the `code` command by hand

# `status` of a session or chat is a set of bits (checked on real sessions)
IDLE, ERROR, IN_PROGRESS, INPUT_NEEDED, IS_READ, ARCHIVED = 1, 2, 8, 24, 32, 64
LOCAL_PROVIDER = "copilotcli"  # the chats of GitHub Copilot; other providers (claude, codex) are not ours
FUSION_ID = "auto"  # Copilot Fusion: Copilot picks the model for each request
FUSION_STANDARD = "balance"  # its lowest tier


class AhpError(Exception):
    """The host answered with an error, or the exchange broke."""


class NotReady(AhpError):
    """No connection yet. `why`: `no-cli` (no `code` command found), `cli-failed`, `none` (no endpoint: VS Code is not open, or still starting), `many` (several windows, none is ours)."""

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


def run_code(code: str, arguments: List[str], timeout: float = CLI_TIMEOUT, extra: Optional[Dict[str, str]] = None) -> str:
    """Run the `code` command and return what it printed. Called from the background thread of the board only, never from a page request.
    `extra`: variables for a VS Code this starts (tool folders, CA bundle: core.launchenv); one that is open already keeps its own."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("VSCODE_IPC") and key != "ELECTRON_RUN_AS_NODE"}  # the shim of a VS Code terminal does not know `agent`
    env.update(extra or {})
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        done = subprocess.run([code] + arguments, capture_output=True, timeout=timeout, env=env, creationflags=flags, stdin=subprocess.DEVNULL)
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


def parse_endpoints(text: str) -> List[Endpoint]:
    """The editor endpoints of the output of `code agent endpoints`. An output that cannot be read is no endpoint at all."""
    try:
        found = json.loads(text).get("endpoints") or []
    except (ValueError, AttributeError):
        raise NotReady("cli-failed", "unreadable output") from None
    out = []
    for item in found if isinstance(found, list) else []:
        try:
            where = item["endpoint"]
            if item.get("type") != "editor" or not where.get("path") or not item.get("connectionToken"):
                continue
            out.append(Endpoint(str(where.get("type") or ""), str(where["path"]), item.get("pid"), str(item.get("instanceId") or ""), str(item["connectionToken"])))
        except (KeyError, TypeError, AttributeError):
            continue
    return out


def read_endpoints(code: str) -> List[Endpoint]:
    return parse_endpoints(run_code(code, ["agent", "endpoints"]))


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


# --- transports: one socket or pipe, read with a wait ------------------------------------------------------------

class Unix:
    def __init__(self, path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(CALL_TIMEOUT)
        self.sock.connect(path)

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


class Pipe:
    """A Windows named pipe, opened as a file. A read that waits would also hold up a write on the same handle, so a read is made only when `PeekNamedPipe` says bytes are there."""

    def __init__(self, path: str) -> None:
        self.file = open(path, "r+b", buffering=0)
        self.handle = 0
        if os.name == "nt":
            import msvcrt

            self.handle = msvcrt.get_osfhandle(self.file.fileno())

    def available(self) -> int:
        import ctypes
        from ctypes import wintypes

        count = wintypes.DWORD(0)
        if not ctypes.windll.kernel32.PeekNamedPipe(wintypes.HANDLE(self.handle), None, 0, None, ctypes.byref(count), None):
            raise ConnectionClosed("the pipe is closed")
        return count.value

    def wait(self, timeout: float) -> bool:
        end = time.monotonic() + max(0.0, timeout)
        while True:
            if self.available():
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.03)

    def read(self) -> bytes:
        return self.file.read(max(1, min(self.available(), 65536)))

    def write(self, data: bytes) -> None:
        self.file.write(data)

    def close(self) -> None:
        try:
            self.file.close()
        except OSError:
            pass


def open_transport(endpoint: Endpoint) -> Any:
    return (Pipe if endpoint.path.startswith("\\\\") or endpoint.kind == "pipe" else Unix)(endpoint.path)


# --- the connection --------------------------------------------------------------------------------------------

class Connection:
    """JSON-RPC over the frames. `notices` are the notifications that came while a call waited; `next_notice` hands them out, oldest first."""

    def __init__(self, transport: Any, token: str = "") -> None:
        self.transport = transport
        self._token = token
        self.decoder = Decoder()
        self.notices: Deque[Dict[str, Any]] = collections.deque()
        self.counter = 0
        self.closed = False
        self.pid: Any = None  # the editor process this host runs in, as `code agent endpoints` names it (1.7.38: the board reads its environment before any chat)
        self.instance = ""

    def upgrade(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        self.transport.write(("GET /?tkn=%s HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                              "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (quote(self._token, safe=""), key)).encode())
        raw = b""
        end = time.monotonic() + CALL_TIMEOUT
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
        self.transport.write(encode_frame(json.dumps(message).encode("utf-8")))

    def absorb(self, frames: List[Tuple[int, bytes]]) -> List[Dict[str, Any]]:
        """Frames to messages. A ping is answered, a close ends the connection."""
        out: List[Dict[str, Any]] = []
        for opcode, body in frames:
            if opcode == 9:
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

    def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = CALL_TIMEOUT) -> Any:
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

    def hello(self) -> Dict[str, Any]:
        """`initialize`, without `clientInfo` (the host then records the client as `vscode`)."""
        return self.call("initialize", {"protocolVersions": [PROTOCOL], "clientId": str(uuid.uuid4())}) or {}

    def subscribe(self, channel: str) -> Dict[str, Any]:
        """The state of a channel as it is now, and a stream of its actions after it. Returns the snapshot's `state`."""
        return ((self.call("subscribe", {"channel": channel}) or {}).get("snapshot") or {}).get("state") or {}

    def unsubscribe(self, channel: str) -> None:
        self.call("unsubscribe", {"channel": channel})

    def dispatch(self, channel: str, action: Dict[str, Any]) -> None:
        """A client action on a chat or session channel: a notification, no answer (the host pushes the state it made of it). Used for a message, a steer and a stop."""
        self.counter += 1
        self.send({"jsonrpc": "2.0", "method": "dispatchAction", "params": {"channel": channel, "clientSeq": self.counter, "action": action}})

    def sessions(self) -> List[Dict[str, Any]]:
        return list((self.call("listSessions", {}) or {}).get("items") or [])

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


CHAT_SETTINGS = ("mode", "autoApprove")  # both may change while a chat lives (`chatMutable`); a value set on the chat goes over the session's


def slim(turn: Any) -> Any:
    """A turn cut to what the board reads: the last `PARTS_KEEP` parts, and no result text of a tool call (its `content` can be big)."""
    if not isinstance(turn, dict):
        return turn
    parts = turn.get("responseParts")
    if not isinstance(parts, list):
        return turn
    kept = []
    for part in parts[-PARTS_KEEP:]:
        call = part.get("toolCall") if isinstance(part, dict) else None
        if isinstance(call, dict) and "content" in call:
            part = dict(part, toolCall={key: value for key, value in call.items() if key != "content"})
        kept.append(part)
    return dict(turn, responseParts=kept, dropped=int(turn.get("dropped") or 0) + max(0, len(parts) - PARTS_KEEP))


QUEUED_CHARS = 2000  # characters of a queued message the board keeps to show


def pending(item: Any) -> Optional[Dict[str, Any]]:
    """One message waiting in a chat (`queuedMessages[]`: `queued` goes after the turn, `steering` into it), cut to its id, kind and the start of its text."""
    if not isinstance(item, dict) or not item.get("id"):
        return None
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    return {"id": str(item["id"]), "kind": str(item.get("kind") or "queued"), "text": str(message.get("text") or item.get("text") or "")[:QUEUED_CHARS]}


def trimmed(state: Dict[str, Any], keep: int = 2) -> Dict[str, Any]:
    """A chat snapshot cut to what the board shows: the last turns and the one running, and the messages that wait. A long chat is big."""
    return {"status": state.get("status"), "title": state.get("title"), "modifiedAt": state.get("modifiedAt"), "config": state.get("config"),
            "turns": [slim(turn) for turn in list(state.get("turns") or [])[-keep:]], "activeTurn": slim(state.get("activeTurn")),
            "queuedMessages": [found for found in (pending(item) for item in state.get("queuedMessages") or []) if found]}


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


def reduce_chat(state: Dict[str, Any], action: Dict[str, Any], keep: int = 2) -> None:
    """Apply one action of a subscribed chat to a trimmed state, as the host's own reducer does (read from its code): enough to know the tool that runs and the reply that grows."""
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
    elif kind == "chat/toolCallStart":
        call = {"toolCallId": action.get("toolCallId"), "toolName": action.get("toolName"), "displayName": action.get("displayName"), "intention": action.get("intention"), "status": "streaming"}
        if action.get("invocationMessage") is not None:
            call["invocationMessage"] = action["invocationMessage"]
        parts.append({"kind": "toolCall", "toolCall": call})
    elif kind in ("chat/toolCallReady", "chat/toolCallComplete"):
        for part in parts:
            call = part.get("toolCall") if part.get("kind") == "toolCall" else None
            if call and call.get("toolCallId") == action.get("toolCallId"):
                if kind == "chat/toolCallComplete":
                    result = action.get("result") if isinstance(action.get("result"), dict) else {}
                    call["status"] = "completed" if result.get("success", True) else "failed"
                    call["success"] = bool(result.get("success", True))
                    for field in ("pastTenseMessage",):
                        found = result.get(field) if result.get(field) is not None else action.get(field)
                        if found is not None:
                            call[field] = found
                else:
                    call["status"] = "running" if action.get("confirmed") else "pending-confirmation"
                    for field in ("toolInput", "intention", "invocationMessage"):
                        if action.get(field) is not None:
                            call[field] = action[field]
    elif kind == "chat/usage" and isinstance(action.get("usage"), dict):
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
        del parts[:len(parts) - PARTS_KEEP]


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


def trimmed_session(state: Dict[str, Any]) -> Dict[str, Any]:
    """A session snapshot cut to what the board reads of it: `inputNeeded[]` (the questions and tool confirmations that wait for a person), of its settings the two a person may
    change from the board (`mode`, `autoApprove`): the value and the choices the host offers, and the chats of its subagents (`subchats`, 1.6.105)."""
    items = state.get("inputNeeded")
    config = state.get("config") if isinstance(state.get("config"), dict) else {}
    schema = (config.get("schema") or {}).get("properties") or {}
    values = config_values(state)
    chats = state.get("chats") if isinstance(state.get("chats"), list) else []
    return {"inputNeeded": [item for item in items if isinstance(item, dict)] if isinstance(items, list) else [],
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
        new = action["request"]
        for at, item in enumerate(items):
            if item.get("id") == new["id"]:
                items[at] = new
                return
        items.append(new)
    elif kind == "session/inputNeededRemoved":
        state["inputNeeded"] = [item for item in items if item.get("id") != action.get("id")]
