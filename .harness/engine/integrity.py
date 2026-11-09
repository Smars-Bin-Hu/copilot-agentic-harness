"""The integrity list of the guardrail files (1.7.38, C13 FR 17a). Standard library only: the hook reads it before it imports any of the engine.

The files that hold the guardrails' code and policy (`.harness/engine/**`, `.harness/bin/**`, `.github/hooks/**`, `.harness/toolpacks/**`, `.harness/registry.json`, the shipped files of `.harness/policies/`) are
listed with their size, time and SHA-256 when the person accepts them: at the first start of the board, at the start of the board after an upgrade (another version in `registry.json`), with `harness doctor --accept`, and
when admin mode ends. The list is kept in the person's home, outside the workspace (`~/.copilot-harness/integrity/`), one file for each copy of the harness. The hook asks `problem()` before every call: size and time first,
the hash only of a file whose size or time changed. A file that is not what was accepted, a new file and a missing one are a problem; the hook then refuses commands and writes (hook.py) and says which files.

This stops a slip and plain tampering: a script of the agent that rewrites an engine file. It does not stop a process that runs as the same user and wants to break out: it can change the list as well. `docs/12` says so.
Never raises.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DIRS = (".harness/engine", ".harness/bin", ".github/hooks", ".harness/toolpacks")  # walked: every file, but the cache of Python
FILES = (".harness/registry.json",)
POLICIES = ".harness/policies"  # the files of the folder itself, but not the settings the person's tools write (`*.override.json`) and the company's (`*.company.json`)
SKIP_DIRS = frozenset(["__pycache__", ".pytest_cache", ".git"])
SKIP_SUFFIXES = (".pyc", ".pyo", ".lock", ".tmp")
SKIP_POLICY = re.compile(r"\.(?:override|company)\.json$")
SHOWN = 5  # files named in a message
VERSION = 1


def home_dir() -> Optional[Path]:
    """Where the lists are kept: `HARNESS_INTEGRITY_DIR`, else `~/.copilot-harness/integrity`. None when there is no home to keep them in."""
    custom = os.environ.get("HARNESS_INTEGRITY_DIR")
    if custom:
        return Path(custom)
    try:
        return Path.home() / ".copilot-harness" / "integrity"
    except (RuntimeError, KeyError):
        return None


def list_path(root: Path) -> Optional[Path]:
    base = home_dir()
    if base is None:
        return None
    return base / (hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16] + ".json")


def _skip_policy(name: str) -> bool:
    return bool(SKIP_POLICY.search(name)) or not name.endswith(".json")


def walk(root: Path) -> Dict[str, Tuple[int, int]]:
    """`{relative path: (size, mtime in ns)}` of every watched file now. A file that cannot be looked at is left out."""
    root = Path(root)
    found: Dict[str, Tuple[int, int]] = {}

    def add(path: Path) -> None:
        try:
            info = path.stat()
            found[path.relative_to(root).as_posix()] = (info.st_size, info.st_mtime_ns)
        except (OSError, ValueError):
            pass

    for relative in DIRS:
        for folder, names, files in os.walk(root / relative):
            names[:] = [name for name in names if name not in SKIP_DIRS]
            for name in files:
                if not name.endswith(SKIP_SUFFIXES):
                    add(Path(folder) / name)
    for relative in FILES:
        if (root / relative).is_file():
            add(root / relative)
    try:
        for entry in os.scandir(root / POLICIES):
            if entry.is_file() and not _skip_policy(entry.name):
                add(Path(entry.path))
    except OSError:
        pass
    return found


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _registry_version(root: Path) -> str:
    try:
        return str(json.loads((Path(root) / ".harness" / "registry.json").read_text(encoding="utf-8-sig")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def read(root: Path) -> Optional[Dict[str, Any]]:
    """The accepted list of this copy, or None when there is none or it cannot be read."""
    path = list_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def accept(root: Path) -> Dict[str, Any]:
    """The person accepts the watched files as they are now: write the list. `{files, path}`; raises `OSError` when it cannot be written (the caller says so)."""
    path = list_path(root)
    if path is None:
        raise OSError("no home folder to keep the list in")
    seen = walk(root)
    files = {}
    for relative, (size, stamp) in seen.items():
        try:
            files[relative] = [size, stamp, _digest(Path(root) / relative)]
        except OSError:
            continue
    data = {"version": VERSION, "root": str(Path(root).resolve()), "harness": _registry_version(root), "at": datetime.now(timezone.utc).isoformat(), "files": files}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False)
    with handle:
        json.dump(data, handle, indent=0, sort_keys=True)
    os.replace(handle.name, str(path))
    return {"files": len(files), "path": str(path)}


def changes(root: Path, listed: Optional[Dict[str, Any]] = None) -> List[str]:
    """The files that are not as accepted: `<path> (changed | new | gone)`, in path order. Empty when all are, or when there is no list. Size and time first: only a file whose size or time differs is hashed."""
    listed = read(root) if listed is None else listed
    if not listed:
        return []
    files = listed.get("files") or {}
    now = walk(root)
    out: List[str] = []
    for relative in sorted(set(files) | set(now)):
        if relative not in now:
            out.append(f"{relative} (gone)")
        elif relative not in files:
            out.append(f"{relative} (new)")
        else:
            try:
                size, stamp, digest = files[relative]
            except (TypeError, ValueError):
                out.append(f"{relative} (changed)")
                continue
            if now[relative] == (size, stamp):
                continue
            try:
                if _digest(Path(root) / relative) != digest:
                    out.append(f"{relative} (changed)")
            except OSError:
                out.append(f"{relative} (changed)")
    return out


def problem(root: Path) -> str:
    """"" when the watched files are as accepted (or nothing was accepted yet); else the files that are not, `a (changed), b (new)`, at most `SHOWN` and how many more."""
    try:
        found = changes(root)
    except Exception:  # noqa: BLE001 - a check that fails itself says nothing: the hook has its own net for the engine
        return ""
    if not found:
        return ""
    return ", ".join(found[:SHOWN]) + (f" (+{len(found) - SHOWN} more)" if len(found) > SHOWN else "")


def status(root: Path) -> Tuple[str, str]:
    """`(the files that are not as accepted, as problem() words, and why)`: why is `upgrade` when the list was made for another version of the harness than the one in the folder now (a new version was unzipped, and the
    board has not been started since: starting it accepts the new version), `changed` when it is the same version (a file was changed by hand or a repackaged copy was put over it: the person accepts or puts it back). `("", "")` when
    all is as accepted (or nothing was accepted yet)."""
    try:
        listed = read(root)
        found = changes(root, listed)
    except Exception:  # noqa: BLE001 - a check that fails itself says nothing
        return "", ""
    if not found:
        return "", ""
    words = ", ".join(found[:SHOWN]) + (f" (+{len(found) - SHOWN} more)" if len(found) > SHOWN else "")
    return words, ("upgrade" if listed and str(listed.get("harness") or "") != _registry_version(root) else "changed")


def write_problem() -> str:
    """"" when the folder of the lists can be written; else the fault in a few words (a home folder that is read only, a path that is no folder). For doctor: a list that cannot be kept is no check at all."""
    base = home_dir()
    if base is None:
        return "there is no home folder"
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = tempfile.NamedTemporaryFile("w", dir=str(base), delete=True)
        probe.close()
        return ""
    except (OSError, ValueError) as error:
        return " ".join(f"{type(error).__name__}: {error}".split())[:200]


def accept_on_start(root: Path) -> str:
    """For the start of the board (the person's own action): make the list when there is none, or when the harness is another version than the list was made for (an upgrade by the documented steps).
    A list for this version that the files do not match is NOT replaced: that is a change nobody accepted, and `harness doctor` says which files. Returns `made`, `kept` (matches), `changed` (does not), `none` (could not write)."""
    try:
        listed = read(root)
        if listed is None or str(listed.get("harness") or "") != _registry_version(root):
            accept(root)
            return "made"
        return "changed" if changes(root, listed) else "kept"
    except Exception:  # noqa: BLE001 - the board must start
        return "none"


# --- admin mode: the person switched it on in this session, so its changes are theirs ------------------------------------------------------------------------

def safe_session_id(session_id: str) -> str:
    """The same name `core/state.py` gives a session's state file."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    if safe in {"", ".", ".."}:
        safe = "session-" + hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return safe[:180]


def admin_session(root: Path, surface: str, session_id: str) -> bool:
    """Is admin mode on for this session (and it is no subagent's)? Read from the session state as plain JSON; any doubt says no."""
    try:
        data = json.loads((Path(root) / ".harness" / "runtime" / "state" / surface / f"{safe_session_id(session_id)}.json").read_text(encoding="utf-8"))
        return bool((data.get("admin") or {}).get("on")) and not data.get("parent_session_id")
    except (OSError, ValueError, AttributeError, TypeError):
        return False
