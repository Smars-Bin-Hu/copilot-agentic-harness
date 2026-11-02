"""Get ready: the part of Finish that can take long (1.6.58). It runs on a thread of its own and the page reads its lines. Each step can be run again.

The knowledge base is written here because a person chose it on the page, as `company update --apply` and `target init-kb` are run by a person at a terminal.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import company, messages, setup, targets

from . import kbsetup, ready

PLACEHOLDER = ("README.md",)  # what `knowledge-base/` ships with


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def copy_folder(root: Path, source: Path) -> str:
    """The folder's content into `knowledge-base/`, its `.git` too. What the copy already holds is refused: a person's work is not overwritten."""
    folder = root / targets.KB_DIR
    folder.mkdir(exist_ok=True)
    if source.resolve() == folder.resolve():
        return say("setup.kb.same")
    held = [item.name for item in folder.iterdir() if item.name not in PLACEHOLDER]
    if held:
        raise ValueError(say("setup.kb.full", name=held[0]))
    count = 0
    for item in source.iterdir():
        target = folder / item.name
        if item.is_dir():
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)
        count += 1
    return say("setup.kb.copied", n=count)


def steps(root: Path, data: Dict[str, Any]) -> List[Tuple[str, Callable[[], str]]]:
    mode = str(data.get("kb_mode") or "none")
    path = setup.clean_path(data.get("kb_path"))

    def content() -> str:
        if mode == "package":
            found = company.update(root, path, apply=True, interactive=True)
            return say("setup.kb.package.done", version=found.get("version", ""))
        return copy_folder(root, Path(path)) if mode == "folder" else say("setup.line.later")

    def repository() -> str:
        if mode == "none" and not targets.knowledge_base_content(root / targets.KB_DIR):
            return say("setup.line.later")
        found = kbsetup.init(root)
        if not found["registered"]:
            kept = setup.kept(root, "target")
            setup.write(root, "target", {"repos": dict(kept.get("repos") or {}, kb={"path": targets.KB_DIR, "knowledge_base": True})})
        return say("setup.kb.git", branch=found["branch"])

    def synced() -> str:
        found = company.sync_after(root)
        return say("setup.kb.synced") if found else say("setup.kb.nosync")

    def doctor() -> str:
        found = ready.run_doctor(root)
        if found["failed"] or found["errors"]:
            raise ValueError(found["failed"] or found["first"])
        return say("setup.doctor.clean")

    return [("kb", content), ("git", repository), ("sync", synced), ("doctor", doctor)]


class Job:
    """One Finish at a time. `lines` grow as the steps end."""

    def __init__(self) -> None:
        self.lines: List[Dict[str, Any]] = []
        self.running = False
        self.done = False
        self.lock = threading.Lock()

    def view(self) -> Dict[str, Any]:
        with self.lock:
            return {"lines": list(self.lines), "running": self.running, "done": self.done}

    def start(self, root: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        """Checks all the fields first: a ValueError here means nothing was written."""
        setup.check(root, data)
        with self.lock:
            if self.running:
                return self.view_locked()
            self.lines, self.running, self.done = [], True, False
        threading.Thread(target=self.work, args=(root, data), daemon=True).start()
        return self.view()

    def view_locked(self) -> Dict[str, Any]:
        return {"lines": list(self.lines), "running": self.running, "done": self.done}

    def work(self, root: Path, data: Dict[str, Any]) -> None:
        good = True
        for key, step in [*setup.steps(root, data), *steps(root, data)]:
            try:
                line = {"key": key, "ok": True, "detail": step()}
            except Exception as error:  # noqa: BLE001 - told on the page; the person fixes it and presses Finish again
                line = {"key": key, "ok": False, "detail": str(error)[:400]}
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


def probe_package(root: Path, raw: Any) -> Dict[str, Any]:
    """What a package holds, without writing."""
    try:
        found = company.update(root, setup.clean_path(raw))
    except Exception as error:  # noqa: BLE001 - told beside the field
        return {"ok": False, "why": str(error)[:300]}
    return {"ok": True, "why": "", "version": found.get("version", ""), "new": found.get("new", 0), "prefix": found.get("skill_prefix", "")}


def probe_folder(raw: Any) -> Dict[str, Any]:
    path = Path(setup.clean_path(raw) or ".")
    if not path.is_absolute() or not path.is_dir():
        return {"ok": False, "why": say("setup.repos.missing")}
    return {"ok": True, "why": "" if (path / "README.md").is_file() else say("setup.kb.noreadme"), "company": (path / "company").is_dir()}
