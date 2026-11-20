"""How slow this computer is (1.8.15): one factor, from 1 to MAX, that the time limits of the board and its helpers are multiplied by.

On a work computer every new process takes about 1.5 s (endpoint security), and fixed limits made a slow answer look like a failure: lines went red, buttons
were turned off, a second board was started. The factor is measured once by the board (`measure_and_save`: the time to start `python -c pass`, divided by BASE)
and kept in `.harness/runtime/pace.json`; `board.slow_factor` in the policy `task` sets it by hand and wins. A process that never measured reads the kept value.

Guardrails do not use it: the hook timeout, the state lock, the retry of a file Windows holds, the approval waits stay as they are (a guard that cannot decide refuses).
Stdlib only. Never raises: a factor that cannot be told is 1.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core import config
from core.paths import repo_root, runtime_dir, utc_now

BASE = 0.3  # seconds a new Python process takes on a computer that needs no more time than the limits were written for
MAX = 5.0  # the factor is never larger: a limit grows five times at most
SET_MAX = 10.0  # a factor set by hand may go this far
KEEP = 30.0  # seconds a process keeps the factor it read before it reads the file again
MEASURE_LIMIT = 60.0  # seconds the measure may take; a measure that runs out gives MAX
FILE = "pace.json"

_lock = threading.Lock()
_kept: Dict[str, Any] = {}  # str(root) -> (when read, info)


def file_of(root: Path) -> Path:
    return runtime_dir(root) / FILE


def from_seconds(seconds: float) -> float:
    """The factor of a measured start time: seconds / BASE, kept between 1 and MAX, to one decimal."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds != seconds or seconds <= 0:
        return 1.0
    return round(min(max(seconds / BASE, 1.0), MAX), 1)


def set_by_hand(root: Path) -> Optional[float]:
    """`board.slow_factor` of the policy `task`, kept between 1 and SET_MAX; None when it is not set or not a number."""
    value = (config.policy_or_empty(root, "task").get("board") or {}).get("slow_factor")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return round(min(max(float(value), 1.0), SET_MAX), 1)


def read_kept(root: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(file_of(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    factor = data.get("factor")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or factor != factor:
        return None
    return {"factor": round(min(max(float(factor), 1.0), MAX), 1), "seconds": data.get("seconds"), "at": data.get("at", "")}


def info(root: Optional[Path] = None) -> Dict[str, Any]:
    """`{factor, source, seconds, at}`. `source`: `set` (board.slow_factor), `measured` (the kept measure), `default` (neither: 1)."""
    root = root or repo_root()
    key = str(root)
    with _lock:
        found = _kept.get(key)
        if found and time.monotonic() - found[0] < KEEP:
            return dict(found[1])
    try:
        hand = set_by_hand(root)
        if hand is not None:
            out: Dict[str, Any] = {"factor": hand, "source": "set", "seconds": None, "at": ""}
        else:
            kept = read_kept(root)
            out = {"factor": kept["factor"], "source": "measured", "seconds": kept.get("seconds"), "at": kept.get("at", "")} if kept else {"factor": 1.0, "source": "default", "seconds": None, "at": ""}
    except Exception:  # noqa: BLE001 - a factor that cannot be told is 1
        out = {"factor": 1.0, "source": "default", "seconds": None, "at": ""}
    with _lock:
        _kept[key] = (time.monotonic(), out)
    return dict(out)


def factor(root: Optional[Path] = None) -> float:
    return float(info(root)["factor"])


def scaled(seconds: float, root: Optional[Path] = None) -> float:
    """A time limit written for a quick computer, grown for this one."""
    return float(seconds) * factor(root)


def measure(run: Any = subprocess.run) -> float:
    """Seconds to start `python -c pass` and see it end. MEASURE_LIMIT when it ran out; 0 when it could not start (the factor is then 1)."""
    began = time.monotonic()
    try:
        run([sys.executable, "-c", "pass"], capture_output=True, timeout=MEASURE_LIMIT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return MEASURE_LIMIT
    except (OSError, subprocess.SubprocessError):
        return 0.0
    return time.monotonic() - began


def measure_and_save(root: Path, run: Any = subprocess.run) -> Dict[str, Any]:
    """Measure twice and keep the quicker (the first start of a while can be slow for other reasons), write `pace.json`, forget what was kept. Never raises."""
    first = measure(run)
    second = measure(run) if first < MEASURE_LIMIT else first
    seconds = min(value for value in (first, second) if value > 0) if any(value > 0 for value in (first, second)) else 0.0
    data = {"factor": from_seconds(seconds), "seconds": round(seconds, 3), "at": utc_now()}
    try:
        path = file_of(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        part.write_text(json.dumps(data), encoding="utf-8")
        part.replace(path)
    except OSError:
        pass
    forget(root)
    return data


def forget(root: Optional[Path] = None) -> None:
    with _lock:
        if root is None:
            _kept.clear()
        else:
            _kept.pop(str(root), None)
