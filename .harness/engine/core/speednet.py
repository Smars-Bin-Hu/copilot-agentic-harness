"""`harness speed`, network and VS Code parts: is the network slow, or the model? And how long did VS Code take to connect?

Network (`collect`): the work PC reaches the Copilot server through an HTTPS proxy that inspects TLS. Four steps are timed, 3 tries each, median:
DNS, TCP to the proxy, `CONNECT host:443` through it, and the TLS handshake. Only the handshake goes out: after it the socket is closed and no HTTP request is
sent, so nothing about the user, the task or the prompts leaves this computer. A proxy that re-signs with a company CA Python does not know makes the handshake fail
on the certificate; the handshake is then timed again without checking the certificate (only to time it) and `cert` says so. A step that fails is None and its first
error is in `error`.

VS Code (`record_vscode_start`, `vscode_starts`): the board link records the seconds from a VS Code window seen to the host connected. The newest KEEP are kept in
`.harness/runtime/speed-vscode.json` (not in `runtime/speed/`: that folder holds one `*.json` per run and lists them all).

Stdlib only. Never raises: a part that cannot be read is empty.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import launchenv, pace
from core.paths import runtime_dir, utc_now

TRIES = 3
KEEP = 10  # VS Code starts kept
FILE = "speed-vscode.json"
STEPS = ("dns_ms", "proxy_ms", "connect_ms", "tls_ms")
DEADLINE = 30.0  # seconds (times the pace) after which no new try starts


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _median(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def _split(address: str) -> "tuple[str, int]":
    host, _, port = address.rpartition(":")
    return host.strip("[]"), int(port)


def _status_line(sock: socket.socket) -> str:
    """The first line of the proxy's answer, and the rest of its header read off (so the handshake that follows starts on a clean stream)."""
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 8192:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.split(b"\r\n", 1)[0].decode("latin-1", "replace").strip()


def _resolve(name: str, port: int, timeout: float) -> None:
    """`getaddrinfo` has no time limit of its own: it runs in a thread that is left behind after `timeout`."""
    done: Dict[str, Any] = {}

    def look() -> None:
        try:
            socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
            done["ok"] = True
        except Exception as error:  # noqa: BLE001 - handed to the caller
            done["error"] = error

    thread = threading.Thread(target=look, name="speed-dns", daemon=True)
    thread.start()
    thread.join(timeout)
    if "error" in done:
        raise done["error"]
    if not done.get("ok"):
        raise TimeoutError(f"no DNS answer for {name} in {timeout:.0f} s")


def _try(host: str, port: int, proxy: str, timeout: float, connect: Callable[..., socket.socket], found: Dict[str, Any], deadline: float = float("inf")) -> Dict[str, float]:
    """One try: the times of the steps that worked. The first error and the cert note go to `found`.
    The TLS context is made before the clock starts: loading the trusted certificates (slow on Windows) is not the handshake."""
    times: Dict[str, float] = {}
    sock = None

    def left() -> float:  # each step waits `timeout` at most, and never past the deadline of the whole part
        return max(0.5, min(timeout, deadline - time.monotonic()))

    try:
        target = _split(proxy) if proxy else (host, port)
        strict = ssl.create_default_context()
        started = time.perf_counter()
        _resolve(target[0], target[1], left())
        times["dns_ms"] = _ms(started)
        started = time.perf_counter()
        sock = connect(target, left())
        sock.settimeout(left())
        if proxy:
            times["proxy_ms"] = _ms(started)
            started = time.perf_counter()
            sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii", "replace"))
            line = _status_line(sock)
            if line.split(" ")[1:2] != ["200"]:
                found.setdefault("error", f"proxy answered: {line or 'nothing'}")
                return times
        times["connect_ms"] = _ms(started)
        started = time.perf_counter()
        try:
            wrapped = strict.wrap_socket(sock, server_hostname=host)
        except ssl.SSLCertVerificationError:
            found["cert"] = "not trusted by Python"
            sock.close()
            sock = connect(target, left())  # a handshake that failed leaves the socket unusable: a new tunnel, to time the handshake only
            sock.settimeout(left())
            if proxy:
                sock.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode("ascii", "replace"))
                _status_line(sock)
            loose = ssl.create_default_context()
            loose.check_hostname = False
            loose.verify_mode = ssl.CERT_NONE
            started = time.perf_counter()
            wrapped = loose.wrap_socket(sock, server_hostname=host)
        sock = wrapped
        times["tls_ms"] = _ms(started)
    except Exception as error:  # noqa: BLE001 - a failed step is the answer, not a crash
        found.setdefault("error", f"{type(error).__name__}: {error}"[:200])
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
    return times


def collect(root: Path, host: str, port: int = 443, connect: Optional[Callable[..., socket.socket]] = None) -> Dict[str, Any]:
    """The network part. `connect(address, timeout)` replaces `socket.create_connection` (tests)."""
    result: Dict[str, Any] = {"host": host, "proxy": "", "dns_ms": None, "proxy_ms": None, "connect_ms": None, "tls_ms": None, "tries": TRIES, "cert": "", "error": ""}
    try:
        proxy = launchenv.detect_proxy()
        result["proxy"] = proxy
        timeout = pace.scaled(10, root)
        use = connect or socket.create_connection
        found: Dict[str, Any] = {}
        seen: Dict[str, List[float]] = {step: [] for step in STEPS}
        deadline = time.monotonic() + pace.scaled(DEADLINE, root)
        for _ in range(TRIES):
            for step, value in _try(host, port, proxy, timeout, use, found, deadline).items():
                seen[step].append(value)
            if found.get("error") or time.monotonic() > deadline:
                break  # a step that failed fails again: three tries would only triple the wait
        for step in STEPS:
            result[step] = _median(seen[step])
        result["cert"] = found.get("cert", "")
        result["error"] = str(found.get("error", ""))[:200]
    except Exception as error:  # noqa: BLE001 - never raises
        result["error"] = f"{type(error).__name__}: {error}"[:200]
    return result


# --- VS Code start → connected --------------------------------------------------------------------------------------------------------------------------------

def _file(root: Path) -> Path:
    return runtime_dir(root) / FILE


def vscode_starts(root: Path) -> List[Dict[str, Any]]:
    """The recorded starts, newest first; [] when none or the file is broken."""
    try:
        data = json.loads(_file(root).read_text(encoding="utf-8"))
        items = [x for x in data if isinstance(x, dict) and isinstance(x.get("seconds"), (int, float)) and not isinstance(x.get("seconds"), bool)]
        return items[::-1][:KEEP]
    except Exception:  # noqa: BLE001
        return []


def record_vscode_start(root: Path, seconds: float) -> None:
    """Add one start (the oldest of more than KEEP drops out). Written by temp file and replace. Never raises."""
    try:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds != seconds or seconds < 0:
            return
        items = vscode_starts(root)[::-1]
        items.append({"at": utc_now(), "seconds": round(float(seconds), 1)})
        path = _file(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{FILE}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(items[-KEEP:], ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except Exception:  # noqa: BLE001 - a helper must not disturb the caller
        pass
