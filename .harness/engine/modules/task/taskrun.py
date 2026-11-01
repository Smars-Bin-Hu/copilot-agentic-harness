"""Commands the person runs from the task page (1.6.50): the Run button of a code block.

This is the person's own action, as in a terminal, so the gate does not see it. What keeps it the person's:
- only a paired browser may ask (`/api/run`); an agent can reach this address but has no pairing cookie;
- the page shows the whole command and waits for a click; each run is written in the task's record.

A run is one shell command with no input: no terminal, so a command that asks something gets an end of file. It runs in the task folder, the output is
written to `INBOX/BOARD/<time>/` (`given.txt`, `ran.txt`), which the agent can read as anything else the person gave. One run at a time for a task; the runs end with the board.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, tasks
from core.paths import utc_now

from . import task as task_ops
from .common import CommandError, decode_text

FOLDER = "INBOX/BOARD"
MAX_COMMAND = 5000  # characters
MAX_FILE = 5 * 1024 * 1024  # bytes of `given.txt`; the command goes on, the rest is not kept
MAX_MEMORY = 1024 * 1024  # characters held for the page: the end of the output
MAX_READ = 64 * 1024  # characters of one answer to the page
MAX_DONE = 20  # finished runs held in memory
CHUNK = 4096
KILL_AFTER = 3.0  # seconds from the polite stop to the hard one
DRAIN_SECONDS = 1.0  # a command that left a child holding its output has still ended


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def kinds() -> List[str]:
    """The languages of highlight.js a code block may have to get a Run button on this computer."""
    return ["powershell", "batch"] if sys.platform == "win32" else ["bash"]


def shell_line(command: str) -> List[str]:
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    return [os.environ.get("SHELL") or "/bin/sh", "-lc", command]


class Run:
    def __init__(self, task: str, command: str, folder: Path, relative: str) -> None:
        self.id, self.task, self.command, self.folder, self.relative = uuid.uuid4().hex, task, command, folder, relative
        self.started, self.ended = utc_now(), ""
        self.process: Optional["subprocess.Popen[bytes]"] = None
        self.code: Optional[int] = None
        self.stopped = False
        self.failed = ""
        self.text, self.first, self.written, self.cut = "", 0, 0, False  # `first`: the place of text[0] in the whole output
        self.lock = threading.Lock()

    def add(self, text: str) -> None:
        with self.lock:
            self.text += text
            extra = len(self.text) - MAX_MEMORY
            if extra > 0:
                self.text, self.first = self.text[extra:], self.first + extra

    def view(self, since: int = 0) -> Dict[str, Any]:
        with self.lock:
            place = max(since, self.first)
            part = self.text[place - self.first:place - self.first + MAX_READ]
            state = "running" if self.ended == "" else "stopped" if self.stopped else "failed" if self.failed else "done"
            return {"id": self.id, "command": self.command, "state": state, "code": self.code, "text": part, "next": place + len(part), "skipped": place > since,
                    "more": place + len(part) < self.first + len(self.text), "folder": self.relative, "cut": self.cut, "error": self.failed}


class Runner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runs: Dict[str, Run] = {}
        self.lock = threading.Lock()

    def active(self, task: str) -> Optional[Run]:
        with self.lock:
            return next((run for run in self.runs.values() if run.task == task and not run.ended), None)

    def folder_for(self, task: str) -> Tuple[Path, str]:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        for number in range(1000):
            name = stamp if not number else f"{stamp}-{number}"
            folder = tasks.task_dir(self.root, task) / FOLDER / name
            try:
                folder.mkdir(parents=True)
                return folder, f"{FOLDER}/{name}"
            except FileExistsError:
                continue
        raise CommandError(say("run.refused.folder"))

    def start(self, task: str, command: str) -> Dict[str, Any]:
        command = str(command or "").strip()
        if not command:
            raise CommandError(say("run.refused.empty"))
        if len(command) > MAX_COMMAND or "\x00" in command:
            raise CommandError(say("run.refused.long", limit=MAX_COMMAND))
        if self.active(task):
            raise CommandError(say("run.refused.busy"))
        folder, relative = self.folder_for(task)
        (folder / "ran.txt").write_text(command + "\n", encoding="utf-8")
        run = Run(task, command, folder, relative)
        extra: Dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}  # a group: Stop reaches what the command started
        try:
            run.process = subprocess.Popen(shell_line(command), cwd=str(tasks.task_dir(self.root, task)), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           env={**os.environ, "PYTHONUNBUFFERED": "1"}, **extra)
        except OSError as error:
            raise CommandError(say("run.refused.start", error=error)) from None
        with self.lock:
            self.runs[run.id] = run
            finished = [item.id for item in self.runs.values() if item.ended]
            for ident in finished[:max(0, len(finished) - MAX_DONE)]:
                del self.runs[ident]
        self.note(task, "run", command)
        reader = threading.Thread(target=self.read_output, args=(run,), daemon=True)
        reader.start()
        threading.Thread(target=self.wait_end, args=(run, reader), daemon=True).start()
        return run.view()

    def read_output(self, run: Run) -> None:
        """The bytes as they come. Text is decoded at the end of a line, so a character is not cut in two; a very long line goes out in pieces."""
        held = b""
        try:
            with open(run.folder / "given.txt", "ab") as out:
                stream = run.process.stdout
                while True:
                    chunk = stream.read1(CHUNK)
                    if not chunk:
                        break
                    held += chunk
                    if len(chunk) and run.written < MAX_FILE:
                        keep = chunk[:MAX_FILE - run.written]
                        out.write(keep)
                        out.flush()
                        run.written += len(keep)
                        run.cut = run.cut or len(keep) < len(chunk)
                    elif chunk:
                        run.cut = True
                    end = max(held.rfind(b"\n"), held.rfind(b"\r"))
                    if end >= 0 or len(held) > CHUNK * 4:
                        cut = end + 1 if end >= 0 else len(held)
                        run.add(decode_text(held[:cut]))
                        held = held[cut:]
        except (OSError, ValueError) as error:
            run.failed = str(error)[:300]
        if held:
            run.add(decode_text(held))

    def wait_end(self, run: Run, reader: threading.Thread) -> None:
        code = run.process.wait()
        reader.join(DRAIN_SECONDS)
        with run.lock:
            run.code, run.ended = code, utc_now()
        try:
            with open(run.folder / "ran.txt", "a", encoding="utf-8") as out:
                out.write(f"exit code: {code}{' (stopped by the person)' if run.stopped else ''}\n")
        except OSError:
            pass
        self.note(run.task, "run.end", f"{run.relative}: {code}")

    def note(self, task: str, what: str, detail: str) -> None:
        try:
            with task_ops.locked(self.root, task) as data:
                task_ops.note(data, what, detail[:200])
        except Exception:  # noqa: BLE001 - the run is on its way; its files hold the same
            pass

    def read(self, ident: str, since: Any) -> Dict[str, Any]:
        with self.lock:
            run = self.runs.get(ident)
        if run is None:
            raise CommandError(say("run.refused.gone"))
        return run.view(since if isinstance(since, int) and not isinstance(since, bool) and since >= 0 else 0)

    def latest(self, task: str) -> Optional[Dict[str, Any]]:
        run = self.active(task)
        return run.view() if run else None

    def stop(self, ident: str) -> Dict[str, Any]:
        with self.lock:
            run = self.runs.get(ident)
        if run is None:
            raise CommandError(say("run.refused.gone"))
        if not run.ended:
            run.stopped = True
            self.kill(run, False)
            timer = threading.Timer(KILL_AFTER, self.kill, args=(run, True))
            timer.daemon = True
            timer.start()
        return run.view()

    @staticmethod
    def kill(run: Run, hard: bool) -> None:
        process = run.process
        if process is None or run.ended:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=10, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGKILL if hard else signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass

    def stop_all(self) -> None:
        """The board is going away: nothing it started stays behind with no page to stop it."""
        with self.lock:
            left = [run for run in self.runs.values() if not run.ended]
        for run in left:
            run.stopped = True
            self.kill(run, True)
