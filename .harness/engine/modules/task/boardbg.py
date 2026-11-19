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

from core import boardperson, messages
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


def background(root: Path, port: Optional[int] = None, out: Any = None, interactive: Optional[bool] = None, *, start: Optional[Callable[..., Any]] = None, sleep: Callable[[float], Any] = time.sleep,
               clock: Callable[[], float] = time.monotonic, limit: float = WAIT_LIMIT, every: float = boardserve.WHEEL_EVERY) -> Dict[str, Any]:
    """`task board --background`: reopen the board that runs, or start one in the background; a wheel with the seconds until the browser has the page. `start`, `sleep`, `clock` exist for the tests.
    Exit 0 when the board runs (a page seen or not), 1 when it did not start."""
    task_ops.person("task board --background", interactive, typed=False)
    out = out or sys.stdout
    tty = boardserve.terminal(out)
    child = None
    running = boardserve.running_board(root)
    if running:  # nothing in the running board changes: it opens the browser with a new code
        address = f"http://127.0.0.1:{running}/"
        if not boardserve.open_again(running):
            print(say("serve.bg.not_opened", address=address), file=out, flush=True)
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
    shown = 0
    turn = 0
    looked = -POLL_EVERY
    answered = running
    while True:
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
                    return finish(out, shown, say("serve.bg.already" if running else "serve.bg.running", address=f"http://127.0.0.1:{answered}/"))
            if not answered and child is not None and child.poll() is not None:
                return failed(root, out, shown, say("serve.bg.why.died", code=child.returncode))
        if seconds >= limit:
            if answered:
                return finish(out, shown, say("serve.bg.not_seen", address=f"http://127.0.0.1:{answered}/", stage=stage_text(stage)))
            return failed(root, out, shown, say("serve.bg.why.late", seconds=int(limit)))
        line = f"{boardserve.WHEEL[turn % len(boardserve.WHEEL)]} " + say("serve.bg.wait", stage=stage_text(stage), seconds=int(seconds))
        turn += 1
        if tty:
            try:
                out.write("\r" + line + " " * max(0, shown - len(line)))
                out.flush()
            except (OSError, ValueError):  # a closed terminal: the wheel is a helper
                tty = False
            shown = len(line)
        sleep(every)


def clear(out: Any, shown: int) -> None:
    if shown:
        try:
            out.write("\r" + " " * shown + "\r")
        except (OSError, ValueError):
            pass


def finish(out: Any, shown: int, text: str) -> Dict[str, Any]:
    clear(out, shown)
    print(text, file=out, flush=True)
    return ok()


def failed(root: Path, out: Any, shown: int, why: str) -> Dict[str, Any]:
    clear(out, shown)
    path = log_path(root)
    print(say("serve.bg.failed", why=why, log=path), file=out, flush=True)
    lines = last_lines(path)
    if lines:
        print(lines, file=out, flush=True)
    return {"_text": "", "exit_code": 1}


def stop(root: Path, out: Any = None, interactive: Optional[bool] = None, *, sleep: Callable[[float], Any] = time.sleep, clock: Callable[[], float] = time.monotonic, wait: float = STOP_WAIT) -> Dict[str, Any]:
    """`task board --stop`: ask the board of this copy to stop (the file of the guardrail folder), wait for it to go. A person only. No board running: it says so."""
    task_ops.person("task board --stop", interactive, typed=False)
    out = out or sys.stdout
    if not boardserve.running_board(root):
        print(say("serve.stop.none"), file=out, flush=True)
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
