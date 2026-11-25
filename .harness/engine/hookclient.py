"""The hook process asks the board to judge a call (hook speed, 1.8.50). Standard library only, no import of the engine, small on purpose: `launch.py` loads it before anything else, and nobody should have a reason to change it.

Starting Python and importing the engine takes 4 to 8 seconds in a hook process on a work computer (endpoint security reads every file), and the board, which is always open, has the engine loaded already. So the board
runs a judging service (`modules/task/hookserve.py`) and this file is its client. It only ever makes the answer quicker: the service's answer is used only when it comes with the right signature; in every other case
(`ask` returns `(None, why)`) the caller judges the call itself, in its own process, exactly as it did before there was a service. A problem with the service never lets a call through.

The protocol (one request and one answer on a local TCP connection, one JSON object on a line each, UTF-8):
  `.harness/runtime/hookserve.json` is written by the service when it starts and deleted when it stops: `{"v", "port", "pid", "key", "started", "wait"}`.
  request: `{"v":1, "nonce", "raw", "env", "cwd", "tmp", "py", "pid", "deadline", "mac"}`; `mac` is HMAC-SHA256 with `key` over the nonce and the SHA-256 of the rest of the request as canonical JSON.
  the service answers `{"ok":false,"why":...}` when it will not judge (only ever read as "judge it yourself"), else `{"start":true,"mac"}` (the mac of the nonce and "start") once it has the call and the lock,
  then `{"ok":true,"output":{...},"mac"}` (the mac of the nonce and the output as canonical JSON). A line whose mac is not right, or that is not what it should be, is not an answer."""

import hashlib
import hmac
import json
import os
import socket
import sys
import tempfile
import time

LIMIT = 8 * 1024 * 1024  # bytes of one line, either way
TOTAL = 100.0  # seconds to wait for the answer after the start line (the hook may run 120: Copilot lets the call go when a hook does not answer in time)
FILE = (".harness", "runtime", "hookserve.json")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sign(key, *parts):
    return hmac.new(key.encode("utf-8"), "".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def alive(pid):
    """Is there a process with this pid? Any doubt says no."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = wintypes.DWORD()
            ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
            kernel.CloseHandle(handle)
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        os.kill(int(pid), 0)
        return True
    except BaseException:  # noqa: BLE001
        return False


def read_line(sock, buffer, until):
    """One line from the socket (the bytes kept in `buffer` count), or `(None, "wait")` when `until` passes, `(None, "closed")` when the other side ends, `(None, "reply")` when the line is longer than LIMIT."""
    while b"\n" not in buffer[0]:
        left = until - time.monotonic()
        if left <= 0:
            return None, "wait"
        sock.settimeout(left)
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            return None, "wait"
        except OSError:
            return None, "closed"
        if not chunk:
            return None, "closed"
        buffer[0] += chunk
        if len(buffer[0]) > LIMIT:
            return None, "reply"
    line, _, rest = buffer[0].partition(b"\n")
    buffer[0] = rest
    return line, ""


def parse(line):
    try:
        data = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clean(why):
    """The words a service gave, as a short tag (it goes into a log line)."""
    text = "".join(char for char in str(why) if char.isalnum() or char in "-_:.")
    return text[:40] or "refused"


def ask(raw, root):
    """`(the output, "")` when the service judged the call and signed its answer; else `(None, why)`: the caller judges it itself. Never raises."""
    try:
        return _ask(raw, root)
    except BaseException as error:  # noqa: BLE001 - whatever goes wrong here, the call is judged by the caller
        return None, "client:" + type(error).__name__


def _ask(raw, root):
    began = time.monotonic()
    try:
        with open(os.path.join(str(root), *FILE), "r", encoding="utf-8") as handle:
            info = json.load(handle)
    except OSError:
        return None, "absent"
    except ValueError:
        return None, "file"
    if not isinstance(info, dict):
        return None, "file"
    port, pid, key = info.get("port"), info.get("pid"), info.get("key")
    wait = info.get("wait")
    if not (isinstance(port, int) and isinstance(pid, int) and isinstance(key, str) and key and isinstance(wait, (int, float))) or isinstance(port, bool) or isinstance(pid, bool):
        return None, "file"
    if not alive(pid):
        return None, "dead"
    if pid < 1 or port < 1:  # pid 0 would be "alive" (`os.kill(0, 0)` is the process group)
        return None, "file"
    wait = min(max(float(wait), 1.0), 60.0)
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=wait)
    except OSError:
        return None, "connect"
    try:
        nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
        request = {"v": 1, "nonce": nonce, "raw": raw, "env": dict(os.environ), "cwd": os.getcwd(), "tmp": tempfile.gettempdir(), "py": [sys.version_info[0], sys.version_info[1]], "pid": os.getpid(), "deadline": time.time() + wait}
        request["mac"] = sign(key, nonce, hashlib.sha256(canonical(request).encode("utf-8")).hexdigest())  # signed over everything but itself
        try:
            sock.sendall(canonical(request).encode("utf-8") + b"\n")
        except OSError:
            return None, "closed"
        buffer = [b""]
        line, why = read_line(sock, buffer, time.monotonic() + wait)  # the start line is due `wait` seconds after the request left
        if line is None:
            return None, why
        first = parse(line)
        if first is None:
            return None, "reply"
        if first.get("ok") is False:
            return None, clean(first.get("why"))
        if first.get("start") is not True or not isinstance(first.get("mac"), str) or not hmac.compare_digest(first["mac"], sign(key, nonce, "start")):
            return None, "mac" if first.get("start") is True else "reply"
        line, why = read_line(sock, buffer, time.monotonic() + max(TOTAL - (time.monotonic() - began), 1.0))
        if line is None:
            return None, "lost-after-start" if why in ("wait", "closed") else why
        second = parse(line)
        if second is None:
            return None, "reply"
        output = second.get("output")
        if second.get("ok") is False:
            return None, "lost-after-start"  # the service began and could not finish
        if second.get("ok") is not True or not isinstance(output, dict):
            return None, "reply"
        if not isinstance(second.get("mac"), str) or not hmac.compare_digest(second["mac"], sign(key, nonce, canonical(output))):
            return None, "mac"
        return output, ""
    finally:
        try:
            sock.close()
        except OSError:
            pass
