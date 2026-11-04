"""Repository paths. HARNESS_ROOT overrides the root (used by tests)."""

from __future__ import annotations

import ntpath
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def is_windows(windows: Optional[bool] = None) -> bool:
    return os.name == "nt" if windows is None else windows


LONG_PREFIX = "\\\\?\\"
LONG_UNC = LONG_PREFIX + "UNC\\"


def long_path(path: Any, windows: Optional[bool] = None) -> str:
    """An absolute path as Windows opens it past 260 characters: with the `\\\\?\\` prefix (`\\\\?\\UNC\\` for a share). Without it, a deeper file
    than that is "No such file or directory", though it is there, unless long paths are turned on for the whole machine (1.6.109: the
    SNAPSHOT files of a task in an old copy whose folder was renamed longer). The prefix turns off Windows' own clean-up, so the path
    is cleaned here first. Elsewhere the path is given back as it is."""
    text = str(path)
    if not is_windows(windows) or text.startswith(LONG_PREFIX):
        return text
    text = ntpath.normpath(text)
    return LONG_UNC + text[2:] if text.startswith("\\\\") else LONG_PREFIX + text


def short_path(text: str) -> str:
    """`long_path` taken off again, for a path a person reads or that is compared with others."""
    if text.startswith(LONG_UNC):
        return "\\\\" + text[len(LONG_UNC):]
    return text[len(LONG_PREFIX):] if text.startswith(LONG_PREFIX) else text


def python_command(windows: Optional[bool] = None) -> str:
    """The interpreter name to type. Windows has `python` and often no `python3`; macOS and Linux have `python3`."""
    return "python" if is_windows(windows) else "python3"


SHORT_COMMAND = "harness"


def cli_command(windows: Optional[bool] = None) -> str:
    """The prefix of every harness command shown to an agent or a person: the short command (`.harness/bin/`, in PATH).

    Putting it into PATH is a required setup step; `doctor` checks it. `windows` is kept for callers that pass it.
    """
    return SHORT_COMMAND


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_stamp(moment: Optional[datetime] = None) -> str:
    """Local time with its UTC offset, for the files people read: `2026-10-29 12:13 (UTC-04:00)`."""
    local = (moment or datetime.now(timezone.utc)).astimezone()
    offset = local.strftime("%z") or "+0000"
    return f"{local:%Y-%m-%d %H:%M} (UTC{offset[:3]}:{offset[3:5]})"


def repo_root() -> Path:
    override = os.environ.get("HARNESS_ROOT")
    if override:
        return Path(override).resolve()
    # .harness/engine/core/paths.py -> repository root
    return Path(__file__).resolve().parents[3]


def policies_dir(root: Path) -> Path:
    return root / ".harness" / "policies"


def registry_path(root: Path) -> Path:
    return root / ".harness" / "registry.json"


def runtime_dir(root: Path) -> Path:
    return root / ".harness" / "runtime"


def state_dir(root: Path, surface: str) -> Path:
    return runtime_dir(root) / "state" / surface


def logs_dir(root: Path) -> Path:
    return runtime_dir(root) / "logs"


def board_serve_file(root: Path) -> Path:
    """Written by `task board --serve` while it runs (its port); read by the gate."""
    return runtime_dir(root) / "board-serve.json"


def board_serve_port(root: Path) -> int:
    """The port of the board server of this copy, or 0 when none runs. Never fails."""
    try:
        import json

        return int(json.loads(board_serve_file(root).read_text(encoding="utf-8"))["port"])
    except Exception:  # noqa: BLE001 - no file or a broken one: nothing to guard
        return 0
