"""The Terminal window of the board (1.6.92): a person types a command on the page and reads its output, in tabs. It is no real terminal.

This is the person's own action, as in a terminal, so the gate does not see it. What keeps it the person's:
- only a paired browser may ask (`/api/term`); an agent can reach this address but has no pairing cookie;
- there is no input and no terminal, so a command that needs a person at a real terminal (an approval, autorun on, admin on) is refused as it is anywhere else;
- `board.terminal_any_command` in the policy `task` set to false leaves `harness` commands only, with no shell: no pipe, no other program.

A line goes to the shell of the Run button, one shell for each line, so `export` does not last. `cd` is kept by the tab on the page. The harness folder's `bin` comes first on PATH, so `harness` works
in a board started before the short command. A run goes on when the page goes away, and a second click on the same line finds it. Nothing kills a run that is quiet: the page says so, and the person stops it. The runs end with the board. Each line is kept in `.harness/runtime/board-terminal.jsonl`.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from core import boardperson, config, launchenv, messages, paths
from core.paths import utc_now

from . import taskrun
from .common import CommandError, decode_text

MAX_LINE = 2000  # characters of a command
MAX_MEMORY = 1024 * 1024  # characters held for the page: the end of the output
MAX_READ = 64 * 1024  # characters of one answer to the page
MAX_RUNNING = 4
MAX_DONE = 20  # finished runs held in memory
REFUSED = (("task", "board"),)  # it would start a second board
PROGRESS = re.compile(r"^::progress (\d+)/(\d+)[ \t]*(.*)$")  # a line of a long command (`HARNESS_PROGRESS`): it fills the bar of the tab and is not output


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def checked(line: Any) -> str:
    """One line a shell may be given, or a CommandError. A second board is refused: it asks for a terminal this window does not have."""
    text = str(line or "").strip()
    if not text or len(text) > MAX_LINE or any(ord(char) < 32 and char != "\t" for char in text):
        raise CommandError(say("term.refused.line", limit=MAX_LINE))
    if any(re.search(r"(^|[\s;&|])harness\s+" + r"\s+".join(item) + r"(\s|$)", text) for item in REFUSED):
        raise CommandError(say("term.refused.board"))
    return text


def words_of(line: Any) -> List[str]:
    """With `board.terminal_any_command` off: the arguments after `harness`, or a CommandError. A backslash is kept: on Windows it is part of a path."""
    text = checked(line)
    try:
        words = shlex.split(text.replace("\\", "\\\\"))
    except ValueError:
        raise CommandError(say("term.refused.line", limit=MAX_LINE)) from None
    if not words or words[0] != "harness":
        raise CommandError(say("term.refused.other"))
    return words[1:]


def runs_harness(line: str) -> bool:
    """Does the line start a harness command (the gate's reading of a line: `harness ...`, `cli.py`, through a wrapper)? Only such a line gets a code from the board: any other command needs none."""
    try:
        from modules.gate import harnesscmd

        return bool(harnesscmd.calls(line)[0])
    except Exception:  # noqa: BLE001 - no code is the safe side: the command runs as before
        return False


class Job:
    def __init__(self, line: str, process: "subprocess.Popen[bytes]", cwd: str = "") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.line, self.process, self.cwd = line, process, cwd
        self.begun = self.last = time.monotonic()
        self.progress: Dict[str, Any] = {}
        self.text, self.dropped, self.code = "", 0, None  # type: ignore[assignment]
        self.ended = False
        self.person = ""  # the one-time code the board gave this command (1.7.39, `boardperson`)

    def add(self, text: str) -> None:
        self.last = time.monotonic()
        kept = []
        for line in text.splitlines(True):
            found = PROGRESS.match(line.rstrip("\r\n"))
            if found:
                self.progress = {"done": int(found[1]), "total": int(found[2]), "word": found[3][:60]}
            else:
                kept.append(line)
        self.text += "".join(kept)
        if len(self.text) > MAX_MEMORY:
            self.dropped += len(self.text) - MAX_MEMORY
            self.text = self.text[-MAX_MEMORY:]

    def view(self, since: int) -> Dict[str, Any]:
        start = max(since - self.dropped, 0)
        part = self.text[start:start + MAX_READ]
        return {"id": self.id, "text": part, "next": self.dropped + start + len(part), "done": self.ended and start + len(part) >= len(self.text), "code": self.code,
                "seconds": round(time.monotonic() - self.begun), "idle": 0 if self.ended else round(time.monotonic() - self.last), "progress": self.progress}


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

    def any_command(self) -> bool:
        return (config.policy_or_empty(self.root, "task").get("board") or {}).get("terminal_any_command", True) is not False

    def start(self, line: Any, here: Any = "") -> Dict[str, Any]:
        text = checked(line)
        engine = self.root / ".harness"
        command = taskrun.shell_line(text) if self.any_command() else [sys.executable, str(engine / "engine" / "cli.py"), *words_of(text)]
        cwd = self.folder("", here)
        with self.lock:
            same = next((job for job in self.jobs.values() if not job.ended and job.line == text and job.cwd == str(cwd)), None)
            if same:  # a second click: the run that is going on, not one more
                return {"id": same.id, "again": True}
            if sum(1 for job in self.jobs.values() if not job.ended) >= MAX_RUNNING:
                raise CommandError(say("term.refused.many", limit=MAX_RUNNING))
        extra: Dict[str, Any] = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {"start_new_session": True}
        base = {**os.environ, **launchenv.extra(self.root)}  # the tool folders and CA bundle VS Code gets (1.7.11): a tool found there is found here
        path_key = next((key for key in base if key.upper() == "PATH"), "PATH")
        person = boardperson.issue() if runs_harness(text) else ""  # (1.7.39) a harness command typed here is the person's: a one-time code it uses when it asks whether a person runs it
        try:
            process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       env={**base, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "HARNESS_PROGRESS": "1", path_key: str(engine / "bin") + os.pathsep + base.get(path_key, ""),
                                            **({boardperson.ENV: person} if person else {})}, **extra)
        except OSError as error:
            boardperson.drop(person)
            raise CommandError(say("term.refused.start", error=error)) from None
        job = Job(text, process, str(cwd))
        job.person = person
        with self.lock:
            self.jobs[job.id] = job
            done = [item.id for item in self.jobs.values() if item.ended]
            for ident in done[:max(0, len(done) - MAX_DONE)]:
                del self.jobs[ident]
        reader = threading.Thread(target=self.follow, args=(job,), daemon=True)
        reader.start()
        threading.Thread(target=self.wait_end, args=(job, reader), daemon=True).start()
        self.note(job.line)
        return {"id": job.id}

    def follow(self, job: Job) -> None:
        """Bytes as they come; decoded at the end of a line, so a character is not cut in two. `decode_text` also reads the code page of a Windows program."""
        held = b""
        while True:
            try:
                chunk = job.process.stdout.read1(taskrun.CHUNK)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            held += chunk
            end = max(held.rfind(b"\n"), held.rfind(b"\r"))
            if end >= 0 or len(held) > taskrun.CHUNK * 4:
                cut = end + 1 if end >= 0 else len(held)
                with self.lock:
                    job.add(decode_text(held[:cut]))
                held = held[cut:]
        if held:
            with self.lock:
                job.add(decode_text(held))

    def wait_end(self, job: Job, reader: threading.Thread) -> None:
        code = job.process.wait()
        reader.join(taskrun.DRAIN_SECONDS)  # a command that left a child holding its output has still ended
        with self.lock:
            job.code, job.ended = code, True
        boardperson.drop(job.person)  # used or not, the code goes with the command

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
            taskrun.Runner.kill(job, True)
        return {"stopped": True}

    def stop_all(self) -> None:
        """The board is going away: nothing it started stays behind with no page to stop it."""
        with self.lock:
            left = [job for job in self.jobs.values() if not job.ended]
        for job in left:
            taskrun.Runner.kill(job, True)

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
        if op == "running":
            with self.lock:
                return {"running": [{"id": job.id, "line": job.line} for job in self.jobs.values() if not job.ended]}
        raise CommandError(say("serve.refused.request"))
