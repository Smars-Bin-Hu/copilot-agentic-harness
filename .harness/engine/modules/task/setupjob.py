"""Get ready: the part of Finish that can take long (1.6.58). It runs on a thread of its own and the page reads its lines. Each step can be run again.

The knowledge base is written here because a person chose it on the page, as `company update --apply` and `target init-kb` are run by a person at a terminal.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import company, messages, paths, setup, targets

from . import kbsetup, ready

PLACEHOLDER = (".gitkeep", "README.md")  # what `knowledge-base/` ships with: an empty `.gitkeep` (1.7.38: it was a `README.md`, which an unzip over a copy replaced with the placeholder); a copy made before has the README
MAX_LISTED = 2000  # entries of one folder in the picker
LINE = 1200  # what a line on the page holds; doctor may have several errors


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def unused(path: Path) -> Path:
    """A name not in use: two runs can fall in one second."""
    found, count = path, 1
    while found.exists():
        found, count = path.with_name(f"{path.name}-{count}"), count + 1
    return found


def held_in(root: Path) -> List[str]:
    folder = root / targets.KB_DIR
    return [item.name for item in sorted(folder.iterdir()) if item.name not in PLACEHOLDER] if folder.is_dir() else []


def copy_folder(root: Path, source: Path, replace: bool = False) -> str:
    """The folder's content into `knowledge-base/`, its `.git` too. It is copied aside first: a copy that fails leaves nothing behind. What the copy already holds is refused: a person's work is not overwritten. With `replace` it moves to a backup first."""
    folder = root / targets.KB_DIR
    folder.mkdir(exist_ok=True)
    if source.resolve() == folder.resolve():
        return say("setup.kb.same")
    held = held_in(root)
    if held and not replace:
        raise ValueError(say("setup.kb.full", name=held[0]))
    moment = time.strftime("%Y%m%d-%H%M%S")
    work = unused(paths.runtime_dir(root) / f"kb-copy-{moment}")
    work.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, work, symlinks=True)
    except (OSError, shutil.Error) as error:
        shutil.rmtree(work, ignore_errors=True)
        reason = error.args[0][0][-1] if isinstance(error, shutil.Error) and error.args[0] else error
        raise ValueError(say("setup.kb.copyfail", error=reason)) from None
    backup = unused(paths.runtime_dir(root) / "kb-backup" / moment)
    items = sorted(work.iterdir())
    moved: List[str] = []
    placed: List[Path] = []
    try:
        for item in sorted(folder.iterdir()) if held else []:  # all of it: the README of a person's knowledge base is theirs too
            backup.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(backup / item.name))
            moved.append(item.name)
        for item in items:
            target = folder / item.name
            if target.is_file():  # the placeholder
                target.unlink()
            shutil.move(str(item), str(target))
            placed.append(target)
    except OSError as error:  # the old one goes back as it was
        for path in placed:
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        for name in moved:
            shutil.move(str(backup / name), str(folder / name))
        shutil.rmtree(work, ignore_errors=True)
        raise ValueError(say("setup.kb.copyfail", error=error)) from None
    work.rmdir()
    return say("setup.kb.moved", n=len(items), folder=str(backup.relative_to(root))) if held else say("setup.kb.copied", n=len(items))


def steps(root: Path, data: Dict[str, Any]) -> List[Tuple[str, Callable[[], str]]]:
    mode = str(data.get("kb_mode") or "none")
    path = setup.clean_path(data.get("kb_path"))

    def content() -> str:
        if mode == "package":
            found = company.update(root, path, apply=True, interactive=True)
            return say("setup.kb.package.done", version=found.get("version", ""))
        if mode == "folder":
            if held_in(root):  # a knowledge base is in place: a git pull when both are repositories, listed first and asked (Q5); the old copy-and-backup way only when git cannot be used
                found = company.folder_update(root, path)
                if found["state"] == "same":
                    return found["text"]
                if found["state"] == "behind":
                    if not data.get("kb_replace"):
                        raise ValueError(found["text"])  # the person has not said yes to the list
                    return company.folder_update(root, path, apply=True)["text"]
                if found["state"] != "plain":
                    raise ValueError(found["why"])
            return copy_folder(root, Path(path), bool(data.get("kb_replace")))
        return say("setup.kb.kept") if any(targets.knowledge_base_content(place) for _name, place in targets.knowledge_bases(root)) else say("setup.line.later")  # Keep it: the one in place stays (1.7.38)

    def repository() -> str:
        if mode == "none" and not targets.knowledge_base_content(root / targets.KB_DIR):
            return say("setup.line.later")
        found = kbsetup.init(root)
        if not found["registered"]:
            kept = setup.kept(root, "target")
            setup.write(root, "target", {"repos": dict(kept.get("repos") or {}, kb={"path": targets.KB_DIR, "knowledge_base": True})})
        return say("setup.kb.git", branch=found["branch"])

    def synced() -> str:
        found = company.sync_after(root, remove=True)  # Save asks for the same sync as Sync now: what left the knowledge base is taken back too (into the backup), not left for a second press
        if found is None:
            return say("setup.kb.nosync")
        if found.get("error"):
            raise ValueError(found["error"])
        left = [item["skill"] for item in found.get("refused") or []]
        lines = list((found.get("toolpacks") or {}).get("lines") or [])  # "ado 0.4.5 -> 0.5.0 updated" (1.7.30)
        back = list(found.get("taken_back") or [])
        first = say("setup.kb.synced.some", names=", ".join(left)) if left else say("setup.kb.synced")
        return " ".join([first + ("; " + say("setup.kb.synced.back", names=", ".join(back)) if back else ""), *lines])

    def doctor() -> str:
        found = ready.run_doctor(root)
        if found["failed"] or found["errors"]:
            raise ValueError(found["failed"] or "\n".join(found.get("lines") or [found["first"]]))
        return say("setup.doctor.warned", n=found["warned"], first=found["warning"]) if found.get("warned") else say("setup.doctor.clean")

    return [("kb", content), ("git", repository), ("sync", synced), ("doctor", doctor)]


class Job:
    """One Finish at a time. `lines` grow as the steps end."""

    def __init__(self) -> None:
        self.lines: List[Dict[str, Any]] = []
        self.running = False
        self.done = False
        self.total = 0
        self.lock = threading.Lock()

    def view(self) -> Dict[str, Any]:
        with self.lock:
            return self.view_locked()

    def start(self, root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        """Checks all the fields first: a ValueError here means nothing was written."""
        setup.check(root, data)
        ahead(root, data)
        with self.lock:
            if self.running:
                return self.view_locked()
            self.lines, self.running, self.done = [], True, False
            self.total = len(setup.steps(root, data)) + len(steps(root, data))
        threading.Thread(target=self.work, args=(root, data), daemon=True).start()
        return self.view()

    def view_locked(self) -> Dict[str, Any]:
        return {"lines": list(self.lines), "running": self.running, "done": self.done, "total": self.total}

    def work(self, root: Path, data: Dict[str, Any]) -> None:
        good = True
        for key, step in [*setup.steps(root, data), *steps(root, data)]:
            try:
                line = {"key": key, "ok": True, "detail": step()}
            except Exception as error:  # noqa: BLE001 - told on the page; the person fixes it and presses Finish again
                line = {"key": key, "ok": False, "detail": str(error)[:LINE]}
                good = False
            with self.lock:
                self.lines.append(line)
            if not line["ok"]:
                break
        try:
            if good:
                setup.write(root, "user", {"setup_done": True})
        finally:
            with self.lock:
                self.running, self.done = False, good


def ahead(root: Path, data: Dict[str, Any]) -> None:
    """What the knowledge base step would refuse, told before anything is written."""
    mode = str(data.get("kb_mode") or "none")
    if mode == "none":
        return
    found = probe_package(root, data.get("kb_path")) if mode == "package" else probe_folder(root, data.get("kb_path"))
    if not found["ok"] and not (found.get("full") and data.get("kb_replace")):
        raise ValueError(found["why"])


def probe_package(root: Path, raw: Any) -> Dict[str, Any]:
    """What a package holds, without writing."""
    value = setup.clean_path(raw)
    if not value or not Path(value).is_absolute():
        return {"ok": False, "why": say("setup.repos.absolute")}
    if not Path(value).is_file():
        return {"ok": False, "why": say("setup.kb.package.folder" if Path(value).is_dir() else "setup.kb.package.missing")}
    try:
        found = company.update(root, value)
    except Exception as error:  # noqa: BLE001 - told beside the field
        return {"ok": False, "why": str(error)[:300]}
    return {"ok": True, "why": "", "version": found.get("version", ""), "new": found.get("new", 0), "changed": found.get("changed", 0), "removed": found.get("removed", 0), "local": found.get("changed_here_count", 0), "prefix": found.get("skill_prefix", "")}


def drives() -> List[str]:
    """The drives of Windows from the system's own list: looking at each one would wait on a network drive that is gone. Elsewhere, none."""
    if sys.platform != "win32":
        return []
    bits = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    return [f"{letter}:\\" for index, letter in enumerate(string.ascii_uppercase) if bits & (1 << index)]


def browse(raw: Any, zips: bool = False) -> Dict[str, Any]:
    """One folder for the picker on the page: its folders and, with `zips`, its zip files. No new process starts: on a work computer that is what takes the time.
    An empty path is the person's home. A folder that cannot be read says so, and the page can still go up."""
    value = setup.clean_path(raw)
    path = Path(value) if value else Path.home()
    while path.is_absolute() and path.parent != path and not path.exists():  # a typed path that is not there: its nearest folder, as a person would go up
        path = path.parent
    found: Dict[str, Any] = {"path": str(path), "parent": str(path.parent) if path.parent != path else "", "drives": drives(), "folders": [], "zips": [], "cut": False, "error": ""}
    if not path.is_absolute():
        return {**found, "parent": "", "error": say("setup.repos.absolute")}
    try:
        with os.scandir(path) as items:
            for count, item in enumerate(items):
                if count >= MAX_LISTED:
                    found["cut"] = True
                    break
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    found["folders"].append(item.name)
                elif zips and item.name.lower().endswith(".zip"):
                    found["zips"].append(item.name)
    except OSError as error:
        return {**found, "folders": [], "zips": [], "error": type(error).__name__}
    found["folders"].sort(key=str.casefold)
    found["zips"].sort(key=str.casefold)
    return found


def probe_folder(root: Path, raw: Any) -> Dict[str, Any]:
    value = setup.clean_path(raw) or "."
    path = Path(value)
    if not path.is_absolute():
        return {"ok": False, "why": say("setup.repos.absolute")}
    if not path.is_dir():
        return {"ok": False, "why": say("setup.repos.file" if path.is_file() else "setup.repos.missing")}
    if (path / ".harness" / "engine").is_dir():
        return {"ok": False, "why": say("setup.kb.harness")}
    here, kb = path.resolve(), (root / targets.KB_DIR).resolve()
    if here == kb:
        return {"ok": True, "why": say("setup.kb.same"), "parts": company.layout(path)}
    if here in root.resolve().parents:
        return {"ok": False, "why": say("setup.kb.holds")}
    if kb in here.parents:
        return {"ok": False, "why": say("setup.kb.inside")}
    if not targets.knowledge_base_content(path):
        return {"ok": False, "why": say("setup.kb.nothing")}
    if held_in(root):
        update = company.folder_update(root, str(path))
        if update["state"] == "plain":  # no git on one side: the old way, a replace the person ticks (the old one moves to a backup); the words say which side has no history
            return {"ok": False, "full": True, "why": say("setup.kb.full.here" if not (path / ".git").exists() else "setup.kb.full.here.copy"), "parts": company.layout(path)}
        view = {key: update[key] for key in ("state", "behind", "ahead", "changes", "total", "counts", "subjects", "uncommitted_there", "branch", "pull")}
        if update["state"] == "same":
            return {"ok": True, "why": update["text"], "update": view, "parts": company.layout(path)}
        if update["state"] == "behind":  # listed, and the person ticks to say yes: `full` asks for the tick
            return {"ok": False, "full": True, "why": update["text"], "update": view, "parts": company.layout(path)}
        return {"ok": False, "why": update["why"], "update": view, "parts": company.layout(path)}  # ahead, unrelated, dirty, error: told, nothing to tick
    found: Dict[str, Any] = {}
    try:
        found = company.read_json(path / targets.COMPANY_DIR / company.CONFIG_FILE)
    except Exception:  # noqa: BLE001 - no prefix to offer; the copy and the sync say what is wrong
        pass
    return {"ok": True, "why": "" if (path / "README.md").is_file() else say("setup.kb.noreadme"), "company": (path / "company").is_dir(), "prefix": str(found.get("skill_prefix") or "").strip().lower(), "parts": company.layout(path)}
