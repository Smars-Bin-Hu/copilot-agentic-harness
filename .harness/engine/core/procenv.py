"""The process environment, home folder and working folder that the hook path reads, through one layer that a thread can override.

A hook is a fresh process: its environment variables, its home folder and its working folder are the answer's input. When the same judging code runs inside the board (one long process, many threads) for a hook
that was started elsewhere, the board's own environment is the wrong one. So every read on the hook path goes through this module, and `using(env, cwd)` puts the hook's values in place for the calling thread
only (a `ContextVar`: each thread has its own context, so two judgments at once never see each other's values).

Without an override every function gives exactly what the standard library gives (the standard function is called). With one, the same algorithms run on the given mapping: `expandvars` and `expanduser` are the
standard ones of the running system (`posixpath` or `ntpath`), written to read the mapping instead of `os.environ`. A test keeps them equal to the standard library.
"""

from __future__ import annotations

import contextvars
import hashlib
import ntpath
import os
import re
import string
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

Override = Tuple[Mapping[str, str], Optional[str]]

_OVERRIDE: "contextvars.ContextVar[Optional[Override]]" = contextvars.ContextVar("harness_procenv", default=None)


class _UpperEnv(dict):
    """The environment of Windows: names are not case sensitive (`os.environ` keeps them upper case there). A plain mapping of a hook's variables is read the same way."""

    def __getitem__(self, key: str) -> str:
        return super().__getitem__(key.upper())

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(key.upper(), default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and super().__contains__(key.upper())


def _prepared(env: Mapping[str, str], windows: Optional[bool] = None) -> Mapping[str, str]:
    """The mapping as this system reads it: upper-cased names on Windows, as given elsewhere."""
    return _UpperEnv((str(key).upper(), value) for key, value in env.items()) if (os.name == "nt" if windows is None else windows) else dict(env)


@contextmanager
def using(env: Mapping[str, str], cwd: Optional[str] = None) -> Iterator[None]:
    """For the calling thread only (a thread it starts has no override of its own), read `env` as the environment and `cwd` as the working folder, and put the previous values back on exit. `cwd` None keeps the process's own."""
    token = _OVERRIDE.set((_prepared(env), cwd))
    try:
        yield
    finally:
        _OVERRIDE.reset(token)


def active() -> bool:
    """Is an override in place for this thread?"""
    return _OVERRIDE.get() is not None


def environ() -> Mapping[str, str]:
    """The environment: the override, else `os.environ`."""
    found = _OVERRIDE.get()
    return os.environ if found is None else found[0]


def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    return environ().get(name, default)


def cwd() -> str:
    """The working folder: the override's, else the process's."""
    found = _OVERRIDE.get()
    return os.getcwd() if found is None or found[1] is None else found[1]


def anchored(path: Any) -> str:
    """The path as a file call should be given it: a relative path is read from the working folder of the override, so that `open`, `os.path.isfile` and `os.listdir` look where the hook's process would. An absolute
    path, and any path without an override, comes back as it is (as text), so what is shown to a person never changes."""
    text = os.fspath(path)
    found = _OVERRIDE.get()
    if found is None or found[1] is None or os.path.isabs(text):
        return text
    return os.path.join(found[1], text)


def abspath(path: Any) -> str:
    """`os.path.abspath`, with a relative path read from `cwd()`."""
    return os.path.abspath(anchored(path))


def realpath(path: Any) -> str:
    """`os.path.realpath`, with a relative path read from `cwd()`."""
    return os.path.realpath(anchored(path))


def resolve(path: Any) -> Path:
    """`Path(path).resolve()`, with a relative path read from `cwd()`."""
    return Path(anchored(path)).resolve()


# --- the standard algorithms, reading a mapping ---------------------------------------------------------------------------------------------------------------

_POSIX_VAR = re.compile(r"\$(\w+|\{[^}]*\})", re.ASCII)
_NT_VARCHARS = string.ascii_letters + string.digits + "_-"
_NT_CHECKS_USER = "USERNAME" in getattr(getattr(ntpath.expanduser, "__code__", None), "co_consts", ("USERNAME",))  # newer Pythons leave `~name` alone when it is not this account's folder name; 3.9 does not look


def _posix_expandvars(path: str, env: Mapping[str, str]) -> str:
    """`posixpath.expandvars` for text, reading `env`."""
    if "$" not in path:
        return path
    index = 0
    while True:
        found = _POSIX_VAR.search(path, index)
        if not found:
            break
        index, end = found.span(0)
        name = found.group(1)
        if name.startswith("{") and name.endswith("}"):
            name = name[1:-1]
        try:
            value = env[name]
        except KeyError:
            index = end
        else:
            tail = path[end:]
            path = path[:index] + value
            index = len(path)
            path += tail
    return path


def _nt_expandvars(path: str, env: Mapping[str, str]) -> str:
    """`ntpath.expandvars` for text, reading `env`: `$var`, `${var}`, `%var%`, `$$`, `%%`, and no expansion inside single quotes."""
    if "$" not in path and "%" not in path:
        return path
    quote, percent, brace, rbrace, dollar = "'", "%", "{", "}", "$"
    res = path[:0]
    index = 0
    length = len(path)
    while index < length:
        char = path[index:index + 1]
        if char == quote:
            path = path[index + 1:]
            length = len(path)
            try:
                index = path.index(char)
                res += char + path[:index + 1]
            except ValueError:
                res += char + path
                index = length - 1
        elif char == percent:
            if path[index + 1:index + 2] == percent:
                res += char
                index += 1
            else:
                path = path[index + 1:]
                length = len(path)
                try:
                    index = path.index(percent)
                except ValueError:
                    res += percent + path
                    index = length - 1
                else:
                    var = path[:index]
                    try:
                        value = env[var]
                    except KeyError:
                        value = percent + var + percent
                    res += value
        elif char == dollar:
            if path[index + 1:index + 2] == dollar:
                res += char
                index += 1
            elif path[index + 1:index + 2] == brace:
                path = path[index + 2:]
                length = len(path)
                try:
                    index = path.index(rbrace)
                except ValueError:
                    res += dollar + brace + path
                    index = length - 1
                else:
                    var = path[:index]
                    try:
                        value = env[var]
                    except KeyError:
                        value = dollar + brace + var + rbrace
                    res += value
            else:
                var = path[:0]
                index += 1
                char = path[index:index + 1]
                while char and char in _NT_VARCHARS:
                    var += char
                    index += 1
                    char = path[index:index + 1]
                try:
                    value = env[var]
                except KeyError:
                    value = dollar + var
                res += value
                if char:
                    index -= 1
        else:
            res += char
        index += 1
    return res


def _posix_expanduser(path: str, env: Mapping[str, str]) -> str:
    """`posixpath.expanduser` for text, reading `env` for `~` (`HOME`, else the account's home folder); `~name` is the account database's, as in the standard function."""
    if not path.startswith("~"):
        return path
    end = path.find("/", 1)
    if end < 0:
        end = len(path)
    if end == 1:
        if "HOME" not in env:
            try:
                import pwd
            except ImportError:
                return path
            try:
                userhome = pwd.getpwuid(os.getuid()).pw_dir
            except KeyError:
                return path
        else:
            userhome = env["HOME"]
    else:
        try:
            import pwd
        except ImportError:
            return path
        try:
            userhome = pwd.getpwnam(path[1:end]).pw_dir
        except KeyError:
            return path
    userhome = userhome.rstrip("/")
    return (userhome + path[end:]) or "/"


def _nt_expanduser(path: str, env: Mapping[str, str]) -> str:
    """`ntpath.expanduser` for text, reading `env` (`USERPROFILE`, else `HOMEDRIVE` and `HOMEPATH`; `USERNAME` for `~name`)."""
    if not path.startswith("~"):
        return path
    index, length = 1, len(path)
    while index < length and path[index] not in "\\/":
        index += 1
    if "USERPROFILE" in env:
        userhome = env["USERPROFILE"]
    elif "HOMEPATH" not in env:
        return path
    else:
        try:
            drive = env["HOMEDRIVE"]
        except KeyError:
            drive = ""
        userhome = ntpath.join(drive, env["HOMEPATH"])
    if index != 1:
        target = path[1:index]
        if not _NT_CHECKS_USER:
            userhome = ntpath.join(ntpath.dirname(userhome), target)  # the older standard function: another account's folder is next to this one's
        else:
            current = env.get("USERNAME")
            if target != current:
                if current != ntpath.basename(userhome):
                    return path
                userhome = ntpath.join(ntpath.dirname(userhome), target)
    return userhome + path[index:]


def expandvars(path: Any) -> Any:
    """`os.path.expandvars`, reading `environ()`."""
    found = _OVERRIDE.get()
    if found is None or not isinstance(path, str):
        return os.path.expandvars(path)
    return (_nt_expandvars if os.name == "nt" else _posix_expandvars)(path, found[0])


def expanduser(path: Any) -> Any:
    """`os.path.expanduser`, reading `environ()`."""
    found = _OVERRIDE.get()
    if found is None or not isinstance(path, str):
        return os.path.expanduser(path)
    return (_nt_expanduser if os.name == "nt" else _posix_expanduser)(path, found[0])


def home() -> Path:
    """`Path.home()`, reading `environ()`: `HOME` (else the account's home folder), or on Windows `USERPROFILE` (else `HOMEDRIVE` and `HOMEPATH`)."""
    if _OVERRIDE.get() is None:
        return Path.home()
    found = expanduser("~")
    if found[:1] == "~":
        raise RuntimeError("Could not determine home directory.")
    return Path(found)


def expanded(path: Any) -> Path:
    """`Path(path).expanduser()`, reading `environ()`. Without an override it is the standard call."""
    if _OVERRIDE.get() is None:
        return Path(path).expanduser()
    return Path(expanduser(str(path)))


def fingerprint() -> str:
    """A text that is the same for the same environment and working folder, to key a cache by: empty without an override, so that the process's own answers stay one entry."""
    found = _OVERRIDE.get()
    if found is None:
        return ""
    return hashlib.sha1(repr((sorted(found[0].items()), found[1])).encode("utf-8", "replace")).hexdigest()


def snapshot() -> Dict[str, str]:
    """A copy of `environ()` that a child process can be given (`subprocess.run(..., env=...)`)."""
    return dict(environ())
