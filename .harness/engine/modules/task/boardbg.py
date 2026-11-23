"""The board in the background (1.8.11): what `harness task board --background` and `--stop` do, the launcher side.

`--background` starts the board as a detached process of its own (`task board --serve`, with `HARNESS_BOARD_BACKGROUND=1` and a voucher of the person, `core.boardperson`) whose output goes to
`.harness/runtime/board.log`, and turns a wheel in the terminal until the browser has opened the page. The board itself is `boardserve.serve`. The launchers (`Start Harness.cmd`, `.command`) run this.
Stdlib only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import boardperson, messages, pace
from core.paths import runtime_dir

from . import boardserve
from . import task as task_ops
from .common import CommandError

ENGINE = Path(__file__).resolve().parents[2]  # .harness/engine: the entry `cli.py` is there
LOG_MAX = 5 * 1024 * 1024  # bytes: a log over this is renamed `board.log.1` at the next start (one kept)
LOG_LINES = 20  # lines of the log shown when the start fails
WAIT_LIMIT = 180.0  # seconds the launcher waits in all
POLL_EVERY = 0.5  # seconds between two looks at the board; the wheel turns faster
STOP_WAIT = 30.0  # seconds `--stop` waits for the board to go
HIDE = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (Windows): a hidden console that the board's own children (git, code) share, so none flashes a window. Not DETACHED_PROCESS: with it the board has no console, and every console program it starts opens one (review 2)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def stage_text(stage: str) -> str:
    """The words of a stage of the wheel."""
    if stage == "pairing":
        return say("serve.bg.pairing")
    if stage == "restarting":
        return say("serve.bg.restarting")
    return say("serve.bg.opening") if stage == "opening" else say("serve.bg.starting")


def log_path(root: Path) -> Path:
    return runtime_dir(root) / "board.log"


def rotate(path: Path, limit: int = LOG_MAX) -> bool:
    """A log over `limit` bytes becomes `<name>.1` (the older `.1` goes). Whether it was rotated. Never fails: a log that cannot be rotated is appended to."""
    try:
        if path.is_file() and path.stat().st_size > limit:
            os.replace(path, path.with_name(path.name + ".1"))
            return True
    except OSError:
        pass
    return False


def last_lines(path: Path, count: int = LOG_LINES) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:])
    except OSError:
        return ""


def spawn(root: Path, port: Optional[int], voucher: str) -> Any:
    """The board process, detached: no window on Windows, a session of its own elsewhere. Its input is nothing; its output is the log."""
    words: List[str] = [sys.executable, str(ENGINE / "cli.py"), "task", "board", "--serve"]
    if port:
        words += ["--port", str(port)]
    env = {**os.environ, boardserve.BACKGROUND_ENV: "1", boardperson.ENV: voucher}
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate(path)
    options: Dict[str, Any] = {"creationflags": HIDE} if os.name == "nt" else {"start_new_session": True}
    with open(path, "ab") as log:
        return subprocess.Popen(words, cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True, **options)


def ok() -> Dict[str, Any]:
    return {"_text": "", "exit_code": 0}


class Wheel:
    """The wheel in the terminal: one line, written over, cleared at the end."""

    cancelled = False

    def __init__(self, out: Any) -> None:
        self.out = out
        self.tty = boardserve.terminal(out)
        self.shown = 0
        self.turn = 0

    def tick(self, stage: str, seconds: int) -> None:
        line = f"{boardserve.WHEEL[self.turn % len(boardserve.WHEEL)]} " + say("serve.bg.wait", stage=stage_text(stage), seconds=seconds)
        self.turn += 1
        if self.tty:
            try:
                self.out.write("\r" + line + " " * max(0, self.shown - len(line)))
                self.out.flush()
            except (OSError, ValueError):  # a closed terminal: the wheel is a helper
                self.tty = False
            self.shown = len(line)

    def note(self, text: str) -> None:
        """A line that stays above the wheel (1.8.23: an older board was stopped)."""
        if self.shown:
            try:
                self.out.write("\r" + " " * self.shown + "\r")
            except (OSError, ValueError):
                pass
            self.shown = 0
        print(text, file=self.out, flush=True)

    def end(self, text: str, lines: str = "", kind: str = "ready", log: str = "") -> None:
        if self.shown:
            try:
                self.out.write("\r" + " " * self.shown + "\r")
            except (OSError, ValueError):
                pass
            self.shown = 0
        print(text, file=self.out, flush=True)
        if lines:
            print(lines, file=self.out, flush=True)


class Both:
    """The start window, and the same words in the terminal at the end (what stays after the window has gone)."""

    def __init__(self, window: Any, out: Any) -> None:
        self.window = window
        self.wheel = Wheel(out)
        self.wheel.tty = False

    @property
    def cancelled(self) -> bool:
        return bool(self.window.cancelled)

    def tick(self, stage: str, seconds: int) -> None:
        self.window.tick(stage_text(stage), seconds)

    def note(self, text: str) -> None:
        self.wheel.note(text)  # the terminal keeps it; the window shows the stage

    def end(self, text: str, lines: str = "", kind: str = "ready", log: str = "") -> None:
        self.wheel.end(text, lines, kind)
        if kind == "failed":  # the window has room for the reason: the last line of the log says it best (a taken port, an error), then where the log is
            last = next((line.strip() for line in reversed(lines.splitlines()) if line.strip()), "")
            text = "\n".join(part for part in (last or text, say("serve.splash.log", log=log) if log else "") if part)
        self.window.end(text, kind)


def background(root: Path, port: Optional[int] = None, out: Any = None, interactive: Optional[bool] = None, *, start: Optional[Callable[..., Any]] = None, sleep: Callable[[float], Any] = time.sleep,
               clock: Callable[[], float] = time.monotonic, limit: Optional[float] = None, every: float = boardserve.WHEEL_EVERY, splash: bool = False) -> Dict[str, Any]:
    """`task board --background`: reopen the board that runs, or start one in the background; a wheel with the seconds until the browser has the page. `start`, `sleep`, `clock` exist for the tests.
    With `splash` (what the launchers ask for) the wheel is a small start window (`boardsplash`), when this Python can show one. Exit 0 when the board runs (a page seen or not), 1 when it did not start."""
    task_ops.person("task board --background", interactive, typed=False)
    limit = pace.scaled(WAIT_LIMIT) if limit is None else limit  # 1.8.15: grown at the moment of use
    out = out or sys.stdout
    window = None
    if splash:
        from . import boardsplash

        window = boardsplash.open_window()
    if window is None:
        return wait(root, port, Wheel(out), start=start, sleep=sleep, clock=clock, limit=limit, every=every)
    import threading

    done: Dict[str, Any] = {}

    def work() -> None:
        ui = Both(window, out)
        try:
            done["result"] = wait(root, port, ui, start=start, sleep=sleep, clock=clock, limit=limit, every=every)
        except CommandError as error:
            done["error"] = error
            ui.window.end(str(error), "failed")
        except BaseException as error:  # noqa: BLE001 - shown, then raised again on the main thread
            done["error"] = error
            ui.window.end(str(error) or type(error).__name__, "failed")

    thread = threading.Thread(target=work, name="board-start", daemon=True)
    thread.start()
    window.run()
    thread.join(limit + 10)
    if "error" in done:
        raise done["error"]
    return done.get("result", ok())


def retire_stale(root: Path, port: int, ui: Any, *, sleep: Callable[[float], Any] = time.sleep, clock: Callable[[], float] = time.monotonic) -> bool:
    """1.8.23: the board that runs started on an older release than the folder holds (an update while it ran in the background): ask it to stop, as `--stop` does, and
    wait for it to go, so the start that follows runs the new code and accepts the new guardrail files. True when it went; False when it is the same release, or when it
    did not go in time (it is then opened as it is)."""
    try:
        from core import registry

        now = str(registry.harness_version(root) or "")
    except Exception:  # noqa: BLE001
        return False
    started = boardserve.running_release(port)
    if not now or not started or started == now:
        return False
    path = boardserve.stop_file(root)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("update\n", encoding="utf-8")  # the board keeps its agent host: the new board takes it over
    except OSError:
        return False
    began = clock()
    limit = pace.scaled(STOP_WAIT)
    while clock() - began < limit:
        if not boardserve.running_board(root):
            ui.note(say("serve.bg.restarted", started=started, now=now))
            return True
        ui.tick("restarting", int(clock() - began))
        sleep(POLL_EVERY)
    return False


def wait(root: Path, port: Optional[int], ui: Any, *, start: Optional[Callable[..., Any]], sleep: Callable[[float], Any], clock: Callable[[], float], limit: float, every: float) -> Dict[str, Any]:
    """Start the board, or open the one that runs, then follow it until a paired page is open, shown on `ui` (the terminal wheel or the start window)."""
    limit = pace.scaled(WAIT_LIMIT) if limit is None else limit  # 1.8.15: grown at the moment of use
    child = None
    running = boardserve.running_board(root)
    if running and retire_stale(root, running, ui, sleep=sleep, clock=clock):  # 1.8.23: an older release runs: it stops, and the new one starts below
        running = 0
    if running:  # nothing in the running board changes: it opens the browser with a new code
        address = f"http://127.0.0.1:{running}/"
        if not boardserve.open_again(running):
            ui.end(say("serve.bg.not_opened", address=address), "", "warn")
            return ok()
        stage = "opening"
    else:
        voucher = boardperson.issue()
        if not voucher:
            raise CommandError(say("serve.bg.novoucher"))
        try:
            child = (start or spawn)(root, port, voucher)
        except OSError as error:
            boardperson.drop(voucher)
            raise CommandError(say("serve.bg.spawn", error=error)) from error
        stage = "starting"
    began = clock()
    looked = -POLL_EVERY
    answered = running
    while True:
        if ui.cancelled:  # the start window was closed: the board keeps running, the wait ends
            return ok()
        seconds = clock() - began
        if seconds - looked >= POLL_EVERY:
            looked = seconds
            answered = boardserve.running_board(root) or 0
            if answered and stage == "starting":
                stage = "opening"
            if answered:
                flags = boardserve.page_flags(answered)
                stage = "pairing" if flags["page_seen"] else "opening"
                if flags["page_paired"]:
                    ui.end(say("serve.bg.already" if running else "serve.bg.running", address=f"http://127.0.0.1:{answered}/"))
                    return ok()
            if not answered and child is not None and child.poll() is not None:
                return failed(root, ui, say("serve.bg.why.died", code=child.returncode))
        if seconds >= limit:
            if answered:
                ui.end(say("serve.bg.not_seen", address=f"http://127.0.0.1:{answered}/", stage=stage_text(stage)), "", "warn")
                return ok()
            return failed(root, ui, say("serve.bg.why.late", seconds=int(limit)))
        ui.tick(stage, int(seconds))
        sleep(every)


def failed(root: Path, ui: Any, why: str) -> Dict[str, Any]:
    path = log_path(root)
    try:
        short = str(path.relative_to(root))
    except ValueError:
        short = str(path)
    ui.end(say("serve.bg.failed", why=why, log=path), last_lines(path), "failed", log=short)
    return {"_text": "", "exit_code": 1}


def stop(root: Path, out: Any = None, interactive: Optional[bool] = None, *, sleep: Callable[[float], Any] = time.sleep, clock: Callable[[], float] = time.monotonic, wait: Optional[float] = None) -> Dict[str, Any]:
    """`task board --stop`: ask the board of this copy to stop (the file of the guardrail folder), wait for it to go. A person only. No board running: it says so."""
    task_ops.person("task board --stop", interactive, typed=False)
    wait = pace.scaled(STOP_WAIT) if wait is None else wait  # 1.8.15
    out = out or sys.stdout
    if not boardserve.running_board(root):
        from core import agenthost

        left = agenthost.Host(root).stop_left()  # a host whose board is gone (it ends itself when idle; a reinstall must not wait for that)
        print(say("serve.stop.host" if left else "serve.stop.none"), file=out, flush=True)
        return ok()
    path = boardserve.stop_file(root)
    if path is None:
        raise CommandError(say("serve.stop.nohome"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stop\n", encoding="utf-8")
    except OSError as error:
        raise CommandError(say("serve.stop.write", error=error)) from error
    print(say("serve.stop.asked"), file=out, flush=True)
    began = clock()
    while clock() - began < wait:
        if not boardserve.running_board(root):
            print(say("serve.stop.done"), file=out, flush=True)
            return ok()
        sleep(POLL_EVERY)
    print(say("serve.stop.late", seconds=int(wait)), file=out, flush=True)
    return {"_text": "", "exit_code": 1}
