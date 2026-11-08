"""Restart VS Code from the board (1.7.38, block B): ask it to quit the normal way, wait until it has gone, open it again the way the board opens it (with this computer's settings).

Never a kill. macOS: AppleScript `quit`, which VS Code answers like Cmd+Q (a file that is not saved is asked about by VS Code itself). Windows: `taskkill` without `/F`, which asks each window to close. Elsewhere: SIGTERM to `code`.
A VS Code that does not go in QUIT_WAIT seconds (a window is asking to save a file, say) is not opened again and not forced: the board says so and the person answers the window, then presses the button again.

One restart at a time, in a thread of its own. `view()` is what `/api/ready` carries: `{state, why, since}`, state one of idle, quitting, opening, done, failed. `Restart` takes the commands as functions, so a test never touches a real VS Code.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

QUIT_WAIT = 30.0  # seconds a VS Code is given to quit (a window may ask about a file)
POLL = 0.5
SETTLE = 1.0  # a pause between "it has gone" and "open it": the host's socket and the window state are let go
ASK_SECONDS = 15  # the quit command itself


def quit_command(platform: str = sys.platform) -> List[str]:
    """The command that asks VS Code to quit, never to be killed. Windows: no `/F`; macOS: the app's own quit; elsewhere SIGTERM to `code`."""
    if platform.startswith("win"):
        return ["taskkill", "/IM", "Code.exe"]
    if platform == "darwin":
        return ["osascript", "-e", 'if application "Visual Studio Code" is running then tell application "Visual Studio Code" to quit']
    return ["pkill", "-TERM", "-x", "code"]


def ask_to_quit(run: Callable[..., Any] = subprocess.run, platform: str = sys.platform) -> bool:
    """Run the quit command. True when it could be run; its exit code says nothing (taskkill answers 128 for a helper process that has no window)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.startswith("win") else 0
    try:
        run(quit_command(platform), capture_output=True, timeout=ASK_SECONDS, stdin=subprocess.DEVNULL, **({"creationflags": flags} if flags else {}))
        return True
    except (OSError, subprocess.SubprocessError):
        return False


class Restart:
    def __init__(self, running: Callable[[], bool], opener: Callable[[], Any], ask: Optional[Callable[[], bool]] = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Any] = time.sleep, wait: float = QUIT_WAIT, settle: float = SETTLE, gone: Optional[Callable[[], Any]] = None) -> None:
        self.running = running  # is any VS Code running on this computer
        self.opener = opener  # opens this folder the way the board does (`/api/open`)
        self.gone = gone or (lambda: None)  # VS Code has quit: the link looks for it again at once
        self.ask = ask or ask_to_quit
        self.clock, self.sleep, self.wait, self.settle = clock, sleep, wait, settle
        self.lock = threading.Lock()
        self.state, self.why, self.since = "idle", "", 0.0
        self.thread: Optional[threading.Thread] = None  # for a test to join

    def view(self) -> Dict[str, Any]:
        with self.lock:
            return {"state": self.state, "why": self.why, "since": round(self.clock() - self.since, 1) if self.since else 0}

    def busy(self) -> bool:
        with self.lock:
            return self.state in ("quitting", "opening")

    def set(self, state: str, why: str = "") -> None:
        with self.lock:
            self.state, self.why = state, why

    def start(self, then_open: bool = True) -> bool:
        """Begin a restart. False when one is going on already. `then_open` False: only quit (the caller opens VS Code itself, with identities)."""
        with self.lock:
            if self.state in ("quitting", "opening"):
                return False
            self.state, self.why, self.since = "quitting", "", self.clock()
        self.thread = threading.Thread(target=self.work, args=(then_open,), name="vs-restart", daemon=True)
        self.thread.start()
        return True

    def work(self, then_open: bool) -> None:
        try:
            if self.running():
                if not self.ask():
                    self.set("failed", "no-command")
                    return
                deadline = self.clock() + self.wait
                while self.running():
                    if self.clock() >= deadline:
                        self.set("failed", "still-open")  # not forced, not opened: a window is waiting for the person
                        return
                    self.sleep(POLL)
                self.sleep(self.settle)
                self.gone()
            if then_open:
                self.set("opening")
                self.opener()
            self.set("done")
        except Exception as error:  # noqa: BLE001 - a restart that breaks is told as failed, with its reason
            self.set("failed", f"{type(error).__name__}: {error}"[:200])
