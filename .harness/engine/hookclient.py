"""The hook process asks the board to judge a call (hook speed, 1.8.50). Standard library only, no import of the engine, small on purpose: `launch.py` loads it before anything else, and nobody should have a reason to change it.

Starting Python and importing the engine takes 4 to 8 seconds in a hook process on a work computer (endpoint security reads every file), and the board, which is always open, has the engine loaded already. So the board
runs a judging service (`modules/task/hookserve.py`) and this file is its client. It only ever makes the answer quicker: the service's answer is used only when it comes with the right signature; in every other case
(`ask` returns `(None, why)`) the caller judges the call itself, in its own process, exactly as it did before there was a service. A problem with the service, or a program that is not the service, never lets a call through.

The protocol (local TCP, one JSON object on a line each way, UTF-8):
  `.harness/runtime/hookserve.json` is written by the service when it starts and deleted when it stops: `{"v":2, "port", "pid", "born", "key", "started", "wait"}`. `born` is the time the board's process was created, as the
  system tells it: a file whose pid is a live process that is not the board that wrote it (the pid was used again) is not believed (`born` below).
  1. hello: the client sends `{"v":2,"nonce"}`; the service answers `{"hello": mac(nonce, "hello")}`. A program that cannot sign that has the key of nobody: the client sends it nothing private.
  2. request: `{"v":2, "nonce", "raw", "env", "cwd", "py", "pid", "deadline", "mac"}`; `mac` is HMAC-SHA256 with `key` over the nonce and the SHA-256 of the rest of the request as canonical JSON.
  3. the service answers `{"ok":false,"why":...}` when it will not judge (only ever read as "judge it yourself"), else `{"start":true,"mac"}` (the mac of the nonce and "start") once it has the call and the lock,
     then `{"ok":true,"output":{...},"mac"}` (the mac of the nonce and the output as canonical JSON). A line whose mac is not right, or that is not what it should be, is not an answer.
Each time the answer of the service is used, one line goes to `.harness/runtime/logs/hookclient.jsonl` (`at`, `nonce`, `session_id`, `event`); the service writes the same `nonce` in the record of the call, so a check can
find an answer that was used and was not judged by this board."""

import hashlib
import hmac
import json
import os
import socket
import sys
import time

LIMIT = 8 * 1024 * 1024  # bytes of one line, either way
CONNECT = 1.0  # seconds to connect (a closed port on Windows takes 1 to 2 s to say so)
MOST = 5.0  # most seconds to wait for the hello and for the start line, whatever the file says
TOTAL = 60.0  # seconds from the start of this process to the answer (the hook may run 120: Copilot lets the call go when a hook does not answer in time; the judgment here comes after)
FILE = (".harness", "runtime", "hookserve.json")
TRACE = (".harness", "runtime", "logs", "hookclient.jsonl")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sign(key, *parts):
    return hmac.new(key.encode("utf-8"), "".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def same(one, other):
    """Are two signatures the same text (a text with a letter that is not ASCII is not a signature, and is never the same)?"""
    try:
        return hmac.compare_digest(one.encode("utf-8"), other.encode("utf-8"))
    except (AttributeError, UnicodeError):
        return False


def born(pid):
    """When the process `pid` was created, as the system tells it (a text that is the same each time it is asked while the process lives), or None when there is no such process or the system does not say. Windows:
    GetProcessTimes; macOS: proc_pidinfo; Linux: /proc. Any doubt is None, and None is never the same as anything."""
    try:
        pid = int(pid)
        if pid < 1:
            return None
        if os.name == "nt":
            return _born_windows(pid)
        if sys.platform == "darwin":
            return _born_mac(pid)
        if sys.platform.startswith("linux"):
            return _born_linux(pid)
    except BaseException:  # noqa: BLE001
        pass
    return None


def _born_windows(pid):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        created, _exit, _kernel, _user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(_exit), ctypes.byref(_kernel), ctypes.byref(_user)):
            return None
        return "nt:%d" % ((created.dwHighDateTime << 32) | created.dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def _born_mac(pid):
    import ctypes

    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    size = 136  # sizeof(struct proc_bsdinfo)
    buffer = ctypes.create_string_buffer(size)
    if lib.proc_pidinfo(pid, 3, 0, buffer, size) != size:  # PROC_PIDTBSDINFO
        return None
    raw = buffer.raw
    if int.from_bytes(raw[4:8], sys.byteorder) == 5:  # SZOMB: it ended, nobody has collected it yet
        return None
    seconds, micro = int.from_bytes(raw[120:128], sys.byteorder), int.from_bytes(raw[128:136], sys.byteorder)  # pbi_start_tvsec, pbi_start_tvusec
    return "mac:%d.%06d" % (seconds, micro) if seconds else None


def _born_linux(pid):
    with open("/proc/%d/stat" % pid, "rb") as handle:
        text = handle.read().decode("latin-1")
    rest = text[text.rindex(")") + 2:].split()  # after the name of the program, which may hold spaces and brackets: state is field 3, start time field 22
    return None if rest[0] in ("Z", "X") else "linux:" + rest[19]


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


def trace(root, nonce, raw):
    """One line in `hookclient.jsonl`: this process used an answer of the service. A trace is never a reason to change the answer, so whatever goes wrong here is ignored."""
    try:
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}  # the service judged a payload that is no object too (it refuses it): that is a record, so it is a line
        data = data if isinstance(data, dict) else {}
        session, event = data.get("session_id") or data.get("sessionId") or "", data.get("hook_event_name") or ""
        now = time.time()
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + ".%06d+00:00" % int((now % 1) * 1000000), "nonce": nonce, "session_id": session if isinstance(session, str) else "", "event": event if isinstance(event, str) else ""}
        with open(os.path.join(str(root), *TRACE), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except BaseException:  # noqa: BLE001
        pass


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
    port, pid, key, saved, wait = info.get("port"), info.get("pid"), info.get("key"), info.get("born"), info.get("wait")
    if info.get("v") != 2 or not (isinstance(port, int) and isinstance(pid, int) and isinstance(key, str) and key and isinstance(saved, str) and saved and isinstance(wait, (int, float))) or isinstance(port, bool) or isinstance(pid, bool):
        return None, "file"
    if pid < 1 or port < 1:
        return None, "file"
    if born(pid) != saved:  # no such process, another process (the pid was used again after the board went), or the system does not say: not the board that wrote this file
        return None, "dead"
    window = min(max(float(wait), 1.0), MOST)
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=CONNECT)
    except OSError:
        return None, "connect"
    try:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
        buffer = [b""]
        try:
            sock.sendall(canonical({"v": 2, "nonce": nonce}).encode("utf-8") + b"\n")
        except OSError:
            return None, "closed"
        line, why = read_line(sock, buffer, time.monotonic() + window)  # the service proves it has the key before this process sends it anything
        if line is None:
            return None, why
        first = parse(line)
        if first is None:
            return None, "reply"
        if first.get("ok") is False:
            return None, clean(first.get("why"))
        if not isinstance(first.get("hello"), str):
            return None, "reply"
        if not same(first["hello"], sign(key, nonce, "hello")):
            return None, "mac"
        request = {"v": 2, "nonce": nonce, "raw": raw, "env": dict(os.environ), "cwd": os.getcwd(), "py": [sys.version_info[0], sys.version_info[1]], "pid": os.getpid(), "deadline": time.time() + window}
        request["mac"] = sign(key, nonce, hashlib.sha256(canonical(request).encode("utf-8")).hexdigest())  # signed over everything but itself
        try:
            sock.sendall(canonical(request).encode("utf-8") + b"\n")
        except OSError:
            return None, "closed"
        line, why = read_line(sock, buffer, time.monotonic() + window)  # the start line is due `window` seconds after the request left
        if line is None:
            return None, why
        first = parse(line)
        if first is None:
            return None, "reply"
        if first.get("ok") is False:
            return None, clean(first.get("why"))
        if first.get("start") is not True or not isinstance(first.get("mac"), str) or not same(first["mac"], sign(key, nonce, "start")):
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
        if not isinstance(second.get("mac"), str) or not same(second["mac"], sign(key, nonce, canonical(output))):
            return None, "mac"
        trace(root, nonce, raw)
        return output, ""
    finally:
        try:
            sock.close()
        except OSError:
            pass
