"""How the CLI prints: the `cli` policy. Reading it never fails: a missing or broken policy means the default."""

from __future__ import annotations

import locale
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import config
from .paths import repo_root

POLICY_NAME = "cli"
AUTO = "auto"
UTF8 = "utf-8"
NATIVE = "native"
CHOICES = (AUTO, UTF8, NATIVE)
SAMPLE = "中文样例：成果已写入"
REPLACED: Dict[str, str] = {}  # stream name -> the encoding `auto` replaced with UTF-8 in this process; doctor reports it


def setting(root: Optional[Path] = None) -> str:
    """`auto`, `utf-8` or `native`, as the policy says. Anything else, or a policy that cannot be read, is `auto`."""
    try:
        value = config.load_policy(root or repo_root(), POLICY_NAME)["output"]["encoding"]
    except Exception:  # noqa: BLE001 - printing must work with a broken policy; doctor reports it
        return AUTO
    return value if value in CHOICES else AUTO


def encoding_for(stream: Any, root: Optional[Path] = None) -> str:
    """The encoding to force on `stream`, or an empty string to leave it as it is.

    `auto` leaves a terminal alone. A pipe that cannot write Chinese (cp1252 on Windows) gets UTF-8: the reader there is
    an agent's terminal tool, and it decodes UTF-8. `native` never changes the encoding, for a reader that does not.
    """
    value = setting(root)
    if value == NATIVE:
        return ""
    if value != AUTO:
        return value
    try:
        if stream.isatty():
            return ""
    except Exception:  # noqa: BLE001
        pass
    return "" if shows(SAMPLE, getattr(stream, "encoding", "") or "") else UTF8


def code_pages() -> Dict[str, int]:
    """Windows only: the console output code page and the ANSI code page. Empty elsewhere."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return {"console_output": int(kernel.GetConsoleOutputCP()), "ansi": int(kernel.GetACP())}
    except Exception:  # noqa: BLE001
        return {}


def facts(stream: Any = None) -> Dict[str, Any]:
    stream = stream if stream is not None else sys.stdout
    try:
        terminal = bool(stream.isatty())
    except Exception:  # noqa: BLE001
        terminal = False
    return {
        "stdout_encoding": getattr(stream, "encoding", "") or "",
        "terminal": terminal,
        "preferred": locale.getpreferredencoding(False),
        "code_pages": code_pages(),
    }


def shows(text: str, encoding: str) -> bool:
    """True when `encoding` can write `text` as it is (no \\uXXXX)."""
    try:
        text.encode(encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True
