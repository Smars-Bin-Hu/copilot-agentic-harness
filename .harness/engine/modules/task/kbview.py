"""The knowledge base window of the board (1.6.63). Reading the whole map can take a while, so each view is worked out on a thread, kept with its time, and the page shows when it was made.

Only reads. Nothing here runs when the window is closed.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict

from core import kbatlas, kbdetail, kbgraph, kbmap, kbstatus, messages, readyitems

from . import companyview

KEEP = 600.0  # seconds a view is good for
MAX_LIST = 200


class View:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.kept: Dict[str, Dict[str, Any]] = {}

    def work(self, name: str) -> Callable[[], Dict[str, Any]]:
        return {"status": lambda: kbstatus.status(self.root, True), "detail": lambda: kbdetail.detail(self.root), "health": lambda: kbdetail.health(self.root), "atlas": lambda: kbatlas.atlas(self.root), "company": lambda: companyview.company(self.root)}[name]

    def forget(self) -> None:
        """Every kept view is old now (1.7.38): the map was rebuilt, or the person pressed Refresh. The old result stays on the page until the new one is made."""
        with self.lock:
            for held in self.kept.values():
                held["at"] = 0.0

    def has_kb(self) -> bool:
        """A knowledge base with content is in place (a few file looks). Without it every tab says so and leads to the setup, instead of asking for steps nobody can do yet."""
        try:
            return readyitems.knowledge_base(self.root)[0] is not None
        except Exception:  # noqa: BLE001 - the window then shows the view as it was
            return True

    def get(self, name: str, fresh: bool = False) -> Dict[str, Any]:
        """{running, result, at (seconds ago), error, has_kb}. A view that is missing or old starts on a thread; the page asks again."""
        with self.lock:
            held = self.kept.setdefault(name, {"result": None, "at": 0.0, "good": 0.0, "running": False, "error": ""})
            old = fresh or not held["at"] or time.time() - held["at"] > KEEP
            if old and not held["running"]:
                held["running"] = True
                threading.Thread(target=self.fill, args=(name, held), daemon=True).start()
            return {"running": held["running"], "result": held["result"], "age": round(time.time() - held["good"]) if held["good"] else None, "error": messages.text("dock.kb.nomap") if held["error"] == messages.text("kbmap.none") else held["error"], "nomap": held["error"] == messages.text("kbmap.none"), "canmap": bool(kbmap.toolkits(self.root)) if name == "atlas" else False,
                    "has_kb": self.has_kb()}  # the age of the result shown, not of the last try

    def fill(self, name: str, held: Dict[str, Any]) -> None:
        result, error = None, ""
        try:
            result = self.work(name)()
        except Exception as problem:  # noqa: BLE001 - told in the window
            error = str(problem)[:300]
        with self.lock:
            now = time.time()
            held.update(result=result if result is not None else held["result"], at=now, good=now if result is not None else held["good"], running=False, error=error)

    def near(self, query: Any) -> Dict[str, Any]:
        """What one object uses and what uses it. No map yet: the words of the error say so."""
        text = " ".join(str(query or "").split())[:200]
        if not text:
            raise ValueError(messages.text("kbview.empty"))
        try:
            return kbgraph.near(self.root, text)
        except kbmap.MapError as error:
            raise ValueError(messages.text("dock.kb.nomap") if str(error) == messages.text("kbmap.none") else messages.text("dock.kb.near.none", query=text) if str(error) == messages.text("kbmap.near.none", query=text) else str(error)) from None
