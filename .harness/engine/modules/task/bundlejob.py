"""The certificate bundle, made by the harness itself (1.8.34).

The knowledge base brings only the recipe (`company/tools/computer.json`, a `ca_bundle` with a host and a proxy); the bundle is made on this computer (`launchenv.make`).
It is made in the background, once: after a knowledge base comes in (`kick(fresh=True)`) and when the board starts (`kick()`), never in a loop. A failure is kept for this run
and shown (the wizard's Review, the gear's dot); a new import, or the button in Settings, may try again.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import launchenv

WHY = 200  # characters of the reason kept


class Auto:
    """`state`: idle (nothing was tried this run), making, made, failed. `view()` is read by `/api/setup` (state) and `/api/ready`."""

    def __init__(self, root: Path, after: Optional[Callable[[], Any]] = None) -> None:
        self.root = root
        self.after = after  # what a pressed "Make a bundle" does afterwards: the agent host gets the file when it starts (`apply_local`)
        self.state, self.why, self.at = "idle", "", 0.0
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

    def wanted(self) -> bool:
        """The copy has a recipe that asks for a bundle, and there is none."""
        try:
            recipe = launchenv.recipe(self.root)
        except Exception:  # noqa: BLE001 - a broken file is doctor's to report
            return False
        return bool(recipe.get("host") or recipe.get("proxy")) and launchenv.bundle_path(self.root) is None

    def view(self) -> Dict[str, Any]:
        with self.lock:
            state, why, at = self.state, self.why, self.at
        if state == "idle" and launchenv.bundle_path(self.root):
            state = "made"
        return {"state": state, "why": why, "made": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(at)) if at else "", "age": round(time.time() - at, 1) if at else None}

    def kick(self, fresh: bool = False) -> bool:
        """Start making the bundle in the background when it is wanted. Not while one is being made; not again after a failure of this run unless `fresh` (a new knowledge base came in). True when it started."""
        if not self.wanted():
            return False
        with self.lock:
            if self.state == "making" or (self.state == "failed" and not fresh):
                return False
            self.state, self.why = "making", ""
            self.thread = threading.Thread(target=self.work, name="ca-bundle", daemon=True)
        self.thread.start()
        return True

    def work(self) -> None:
        state, why = "made", ""
        try:
            recipe = launchenv.recipe(self.root)
            found = launchenv.make(self.root, recipe.get("host") or "", recipe.get("proxy") or None)
            if not found.get("ok"):
                state, why = "failed", str(found.get("why") or "")[:WHY]
        except Exception as error:  # noqa: BLE001 - told on the page, never raised
            state, why = "failed", str(error)[:WHY]
        if state == "made" and self.after:
            try:
                self.after()
            except Exception:  # noqa: BLE001 - the bundle is made; the host takes it at its next start
                pass
        with self.lock:
            self.state, self.why, self.at = state, why, time.time()
