"""The board checks the outside connections itself (1.7.19), in the background, so the Enter screen does not wait for the first chat of VS Code.

Before, only the hook of a chat's first step probed (`core.reach`): the screen said "not checked yet" from the moment VS Code opened until the person had sent a first
message. Now the board runs each connection's test, in the environment VS Code is started with (`core.launchenv`) and with the identity kept here
(`core.connections.probe_all`), and writes the answers where the hook writes them. It starts

- at once after the board opens VS Code (the Open VS Code button, or Open with identities): `start(force=True)`;
- when the Enter screen asks and some connection has no answer younger than FRESH_SECONDS: `maybe()`;
- when the person presses Check: `start(force=True)`.

Never on the thread of a request: a check is a thread of its own, one at a time. A connection whose identity is not kept here is left to the hook.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from core import connections as conn_core, reach

FRESH_SECONDS = 300.0  # an answer younger than this is not asked again by the Enter screen
RETRY_SECONDS = 30.0  # the Enter screen starts a check no sooner than this after the last one began (a connection left to the hook stays without an answer)


class Checker:
    def __init__(self, root: Path, probe: Optional[Callable[[Path], Any]] = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.root = root
        self.probe = probe or conn_core.probe_all
        self.clock = clock
        self.lock = threading.Lock()
        self.running = False
        self.began = -1e9
        self.last = None  # the thread, for a test to join

    def wanted(self) -> bool:
        """Some connection the board can check has no answer younger than FRESH_SECONDS."""
        try:
            keys = conn_core.probe_keys(self.root)
            return bool(keys) and not reach.recent(self.root, keys, FRESH_SECONDS)
        except Exception:  # noqa: BLE001 - a broken list is doctor's to report, not a reason to fail a poll
            return False

    def start(self, force: bool = False) -> bool:
        """Start a check in a thread. False when one runs already, or nothing is to be checked (`force`: whatever the age of the answers)."""
        with self.lock:
            if self.running:
                return False
            try:
                if not conn_core.probe_keys(self.root):
                    return False
            except Exception:  # noqa: BLE001
                return False
            self.running, self.began = True, self.clock()
        self.last = threading.Thread(target=self.work, name="reach-check", daemon=True)
        self.last.start()
        return True

    def maybe(self) -> bool:
        """For the Enter screen: a check when one is due and none ran lately."""
        with self.lock:
            if self.running or self.clock() - self.began < RETRY_SECONDS:
                return False
        return self.wanted() and self.start()

    def work(self) -> None:
        try:
            self.probe(self.root)
        except Exception:  # noqa: BLE001 - a check that breaks leaves the lines as they were
            pass
        finally:
            with self.lock:
                self.running = False

    def busy(self) -> bool:
        with self.lock:
            return self.running
