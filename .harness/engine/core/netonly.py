"""Start a process with network credentials only, as `runas /netonly` does, without a prompt (1.7.10). Windows only.

The process runs as the person on this computer; when it reaches another computer (a database with Windows authentication, a share), it uses the given
account. The Windows call is CreateProcessWithLogonW with LOGON_NETCREDENTIALS_ONLY: the account and password are not checked here, only when a server
asks for them, so a wrong password shows as "login failed" at the server. Python's own ctypes, no package. The password is never on a command line.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import pace

LOGON_NETCREDENTIALS_ONLY = 0x2
CREATE_UNICODE_ENVIRONMENT = 0x400
CREATE_NO_WINDOW = 0x08000000
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF


def available() -> bool:
    return os.name == "nt"


def split_account(account: str) -> Tuple[str, Optional[str]]:
    """`DOMAIN\\user` -> (user, DOMAIN); `user@domain` -> (user@domain, None): Windows reads the domain from it."""
    if "\\" in account:
        domain, user = account.split("\\", 1)
        return user, domain
    return account, None


def environment_block(extra: Dict[str, str], base: Optional[Dict[str, str]] = None) -> str:
    """The environment of the new process: this one's (or `base`), with `extra` on top, as Windows wants it (`K=V\\0...\\0\\0`)."""
    merged = dict(os.environ if base is None else base)
    merged.update(extra)
    return "".join(f"{key}={value}\0" for key, value in sorted(merged.items(), key=lambda item: item[0].upper())) + "\0"


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("lpReserved", ctypes.c_wchar_p), ("lpDesktop", ctypes.c_wchar_p), ("lpTitle", ctypes.c_wchar_p),
                ("dwX", ctypes.c_ulong), ("dwY", ctypes.c_ulong), ("dwXSize", ctypes.c_ulong), ("dwYSize", ctypes.c_ulong),
                ("dwXCountChars", ctypes.c_ulong), ("dwYCountChars", ctypes.c_ulong), ("dwFillAttribute", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("wShowWindow", ctypes.c_ushort), ("cbReserved2", ctypes.c_ushort), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", ctypes.c_void_p), ("hStdOutput", ctypes.c_void_p), ("hStdError", ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p), ("dwProcessId", ctypes.c_ulong), ("dwThreadId", ctypes.c_ulong)]


def _create(account: str, password: str, command_line: str, cwd: Path, extra_env: Dict[str, str], flags: int, base: Optional[Dict[str, str]] = None) -> _ProcessInfo:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    user, domain = split_account(account)
    startup = _StartupInfo()
    startup.cb = ctypes.sizeof(_StartupInfo)
    info = _ProcessInfo()
    block = ctypes.create_unicode_buffer(environment_block(extra_env, base))
    line = ctypes.create_unicode_buffer(command_line)  # the call may write into it
    ok = advapi.CreateProcessWithLogonW(user, domain, password, LOGON_NETCREDENTIALS_ONLY, None, line, flags | CREATE_UNICODE_ENVIRONMENT,
                                        block, str(cwd), ctypes.byref(startup), ctypes.byref(info))
    if not ok:
        raise OSError(ctypes.get_last_error(), "CreateProcessWithLogonW failed")  # type: ignore[attr-defined]
    return info


MARK = "harness-netonly-started"  # (1.7.39) the first line the started shell writes: without it, the shell never ran
WAIT_FAILED = 0xFFFFFFFF
STILL_ACTIVE = 259


def told(code: int, text: str, waited: int, error: int = 0) -> Tuple[Optional[int], str]:
    """(1.7.39, Windows) What a run with network credentials says, from the exit code, the file the shell wrote and the wait: a run that printed nothing is told apart from a shell
    that never started and from a wait that failed, so the test names the step that broke instead of "no message"."""
    if waited == WAIT_FAILED:
        return None, f"could not wait for the process started with these credentials (Windows error {error})"
    if waited == WAIT_TIMEOUT:
        return None, ""
    if MARK not in text:
        return (code or 1), f"the shell started with these credentials did not run (exit code {code}{', still running' if code == STILL_ACTIVE else ''}): nothing was written to its output file"
    return code, text.split(MARK, 1)[1].lstrip("\r\n ")


def run(account: str, password: str, command: str, cwd: Path, extra_env: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> Tuple[Optional[int], str]:
    """Run a shell command with these network credentials and wait: (exit code, what it printed). (None, why) when it could not start or took too long."""
    timeout = pace.scaled(60.0) if timeout is None else timeout  # 1.8.15
    if not available():
        return None, "network credentials (runas /netonly) exist on Windows only"
    handle, name = tempfile.mkstemp(prefix="harness-as-", suffix=".txt")
    os.close(handle)  # (1.7.39) the file is the shell's to write: this process keeps no handle on it
    out = Path(name)
    try:
        info = _create(account, password, f'cmd.exe /d /s /c "(echo {MARK}& {command}) > "{out}" 2>&1"', cwd, extra_env or {}, CREATE_NO_WINDOW)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong  # WAIT_FAILED is 0xFFFFFFFF, not -1
        waited = kernel.WaitForSingleObject(ctypes.c_void_p(info.hProcess), int(timeout * 1000))
        error = ctypes.get_last_error() if waited == WAIT_FAILED else 0  # type: ignore[attr-defined]
        code = ctypes.c_ulong(0)
        kernel.GetExitCodeProcess(ctypes.c_void_p(info.hProcess), ctypes.byref(code))
        kernel.CloseHandle(ctypes.c_void_p(info.hProcess))
        kernel.CloseHandle(ctypes.c_void_p(info.hThread))
        text = out.read_bytes().decode("utf-8", errors="replace") if out.exists() else ""
        if waited == WAIT_TIMEOUT:
            return None, f"no answer in {int(timeout)} s"
        return told(int(code.value), text, waited, error)
    except OSError as error:
        return None, f"could not start with these credentials: {error}"
    finally:
        try:
            out.unlink()
        except OSError:
            pass


def start(account: str, password: str, argv: list, cwd: Path, extra_env: Optional[Dict[str, str]] = None) -> bool:
    """Start a program (VS Code) with these network credentials and do not wait. Every process it starts has them too."""
    if not available():
        return False
    info = _create(account, password, subprocess.list2cmdline(argv), cwd, extra_env or {}, CREATE_NO_WINDOW)  # (1.7.39) DETACHED_PROCESS is not a flag CreateProcessWithLogonW takes: Windows answered 87, the parameter is wrong. CREATE_NO_WINDOW, as `run` uses: no console for `cmd.exe /c code.cmd`
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.CloseHandle(ctypes.c_void_p(info.hProcess))
    kernel.CloseHandle(ctypes.c_void_p(info.hThread))
    return True


class Output:
    """The output file of a process started with network credentials, read like a pipe (H5b): `readline` waits for the next line and gives b"" once the process has ended and
    everything it wrote was read. CreateProcessWithLogonW hands no pipe to the caller, so the shell writes to a file."""

    def __init__(self, path: Path, ended: "Callable[[], bool]", poll: float = 0.2) -> None:
        self.path, self.ended, self.poll = path, ended, poll
        self.handle: Any = None
        self.rest = b""

    def readline(self) -> bytes:
        while True:
            if self.handle is None:
                try:
                    self.handle = open(self.path, "rb")  # noqa: SIM115 - kept open while the process writes
                except OSError:
                    if self.ended():
                        return b""
                    time.sleep(self.poll)
                    continue
            done = self.ended()  # looked at before the read: what was written before the end is read in full
            self.rest += self.handle.read()
            if b"\n" in self.rest:
                line, self.rest = self.rest.split(b"\n", 1)
                return line + b"\n"
            if done:
                line, self.rest = self.rest, b""
                return line
            time.sleep(self.poll)

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        try:
            self.path.unlink()
        except OSError:
            pass


class Process:
    """A program (the board's agent host) started with these network credentials, kept like a `subprocess.Popen` (H5b): `pid`, `stdout`, `poll`, `wait`, `kill`.
    Every process it starts reaches other computers with the account, as VS Code opened with identities did. Windows only."""

    def __init__(self, account: str, password: str, argv: List[str], cwd: Path, env: Dict[str, str]) -> None:
        handle, name = tempfile.mkstemp(prefix="harness-host-", suffix=".txt")
        os.close(handle)
        out = Path(name)
        line = f'cmd.exe /d /s /c "{subprocess.list2cmdline(argv)} > "{out}" 2>&1"'
        info = _create(account, password, line, cwd, {}, CREATE_NO_WINDOW, env)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self.kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.kernel.WaitForSingleObject.restype = ctypes.c_ulong
        self.kernel.CloseHandle(ctypes.c_void_p(info.hThread))
        self.handle, self.pid, self.returncode = info.hProcess, int(info.dwProcessId), None
        self.stdout = Output(out, lambda: self.poll() is not None)

    def poll(self) -> Optional[int]:
        if self.returncode is None and self.handle:
            if self.kernel.WaitForSingleObject(ctypes.c_void_p(self.handle), 0) == 0:
                code = ctypes.c_ulong(0)
                self.kernel.GetExitCodeProcess(ctypes.c_void_p(self.handle), ctypes.byref(code))
                self.kernel.CloseHandle(ctypes.c_void_p(self.handle))
                self.handle, self.returncode = None, int(code.value)
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> int:
        if self.returncode is None and self.handle:
            waited = self.kernel.WaitForSingleObject(ctypes.c_void_p(self.handle), INFINITE if timeout is None else int(timeout * 1000))
            if waited == WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired("agent host", timeout or 0)
        code = self.poll()
        return 1 if code is None else code

    def kill(self) -> None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.pid)], capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)


def popen(account: str, password: str) -> "Callable[..., Any]":
    """A `popen` for `agenthost.Host` that starts the host with these network credentials (the options of subprocess.Popen it is given are not used: the environment and the folder are)."""
    def start(argv: List[str], **options: Any) -> Process:
        return Process(account, password, list(argv), Path(options.get("cwd") or os.getcwd()), dict(options.get("env") or os.environ))
    return start
