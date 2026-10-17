"""Repository paths. HARNESS_ROOT overrides the root (used by tests)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def is_windows(windows: Optional[bool] = None) -> bool:
    return os.name == "nt" if windows is None else windows


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
