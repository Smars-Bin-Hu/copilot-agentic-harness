"""The Terminal window of the board (1.6.92): a person types a `harness` command on the page and reads its output, in tabs. It is no real terminal.

This is the person's own action, as in a terminal, so the gate does not see it. What keeps it safe:
- only a paired browser may ask (`/api/term`); an agent can reach this address but has no pairing cookie;
- only `harness ...` runs, with no shell: no pipe, no other program; `cd` moves a tab, and the engine stays the one of this copy;
- there is no input and no terminal, so a command that needs a person at a real terminal (an approval, autorun on, admin on) is refused as it is anywhere else.

The runs end with the board. Each one leaves a line in `.harness/runtime/board-terminal.jsonl`.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List

from core import messages, paths
from core.paths import utc_now

from .common import CommandError

MAX_LINE = 2000  # characters of a command
MAX_MEMORY = 1024 * 1024  # characters held for the page: the end of the output
MAX_READ = 64 * 1024  # characters of one answer to the page
MAX_RUNNING = 4
MAX_DONE = 20  # finished runs held in memory
REFUSED = (("task", "board"),)  # it would start a second board


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def words_of(line: Any) -> List[str]:
    """The arguments after `harness`, or a CommandError. A backslash is kept: on Windows it is part of a path."""
    text = str(line or "").strip()
    if not text or len(text) > MAX_LINE or any(ord(char) < 32 for char in text):
        raise CommandError(say("term.refused.line", limit=MAX_LINE))
    try:
        words = shlex.split(text.replace("\\", "\\\\"))
    except ValueError:
        raise CommandError(say("term.refused.line", limit=MAX_LINE)) from None
    if words[0] != "harness":
        raise CommandError(say("term.refused.other"))
    if any(tuple(words[1:1 + len(item)]) == item for item in REFUSED):
        raise CommandError(say("term.refused.board"))
    return words[1:]


class Job:
    def __init__(self, line: str, process: "subprocess.Popen[str]") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.line, self.process = line, process
        self.text, self.dropped, self.code = "", 0, None  # type: ignore[assignment]
        self.ended = False

    def add(self, text: str) -> None:
        self.text += text
        if len(self.text) > MAX_MEMORY:
            self.dropped += len(self.text) - MAX_MEMORY
            self.text = self.text[-MAX_MEMORY:]

    def view(self, since: int) -> Dict[str, Any]:
        start = max(since - self.dropped, 0)
        part = self.text[start:start + MAX_READ]
        return {"id": self.id, "text": part, "next": self.dropped + start + len(part), "done": self.ended and start + len(part) >= len(self.text), "code": self.code}


class Terminal:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.jobs: Dict[str, Job] = {}

    def folder(self, here: Any, to: Any = "") -> Path:
        """The folder of a tab: `to` from `here`, the harness folder when both are empty. `~` works; a folder that is not there is refused."""
        text = str(to or "").strip().strip("\"'")
        base = Path(str(here or "")) if here else self.root
        found = (base / Path(os.path.expanduser(text))).resolve() if text else self.root.resolve()
        if not found.is_dir():
            raise CommandError(say("term.refused.folder", path=text or str(here)))
        return found

    def start(self, line: Any, here: Any = "") -> Dict[str, Any]:
        words = words_of(line)
        cwd = self.folder("", here)
        with self.lock:
            if sum(1 for job in self.jobs.values() if not job.ended) >= MAX_RUNNING:
                raise CommandError(say("term.refused.many", limit=MAX_RUNNING))
        extra: Dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
        command = [sys.executable, str(self.root / ".harness" / "engine" / "cli.py"), *words]
        try:
            process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                       env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}, **extra)
        except OSError as error:
            raise CommandError(say("term.refused.start", error=error)) from None
        job = Job(str(line).strip(), process)
        with self.lock:
            self.jobs[job.id] = job
            done = [item.id for item in self.jobs.values() if item.ended]
            for ident in done[:max(0, len(done) - MAX_DONE)]:
                del self.jobs[ident]
        threading.Thread(target=self.follow, args=(job,), daemon=True).start()
        self.note(job.line)
        return {"id": job.id}

    def follow(self, job: Job) -> None:
        for chunk in job.process.stdout or []:
            with self.lock:
                job.add(chunk)
        code = job.process.wait()
        with self.lock:
            job.code, job.ended = code, True

    def note(self, line: str) -> None:
        try:
            path = paths.runtime_dir(self.root) / "board-terminal.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": utc_now(), "line": line}, ensure_ascii=False) + "\n")
        except OSError:
            pass  # the run counts more than its line

    def read(self, ident: Any, since: Any) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(str(ident))
            if job is None:
                return {"id": str(ident), "text": "", "next": 0, "done": True, "code": None, "gone": True}
            return job.view(max(0, int(since) if str(since).isdigit() else 0))

    def stop(self, ident: Any) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(str(ident))
        if job is not None and not job.ended:
            self.kill(job)
        return {"stopped": True}

    @staticmethod
    def kill(job: Job) -> None:
        try:
            if os.name == "nt":
                job.process.terminate()
            else:
                os.killpg(job.process.pid, signal.SIGKILL)
        except OSError:
            pass  # it has ended by itself

    def stop_all(self) -> None:
        """The board is going away: nothing it started stays behind with no page to stop it."""
        with self.lock:
            left = [job for job in self.jobs.values() if not job.ended]
        for job in left:
            self.kill(job)

    def act(self, data: Dict[str, Any]) -> Dict[str, Any]:
        op = str(data.get("op", ""))
        if op == "start":
            return self.start(data.get("line"), data.get("cwd"))
        if op == "cd":
            return {"cwd": str(self.folder(data.get("cwd"), data.get("to")))}
        if op == "read":
            return self.read(data.get("id"), data.get("since"))
        if op == "stop":
            return self.stop(data.get("id"))
        raise CommandError(say("serve.refused.request"))
