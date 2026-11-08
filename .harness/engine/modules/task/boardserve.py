"""`task board --serve`: the board as a page on this computer only, with buttons that act (M15-4, M15-5).

  task board --serve [--port N] [--all]   a person starts it in a terminal; Ctrl+C stops it

Who may do what:
- Only a person at a terminal starts it (`person`), and the gate refuses an agent that tries. An agent that started it
  would be handed the pairing link.
- It listens on 127.0.0.1 only, and answers only to the Host and Origin of that address (no other web site, no DNS
  rebinding). Every POST needs the header `X-Harness-Board`, which a page of another site cannot send without asking.
- Pause and resume need nothing more: they guard nothing.
- The approvals need the paired browser. At start a random code is made and kept in memory only; the server opens the
  browser at `/#pair=<code>` and the page trades the code for a session cookie (HttpOnly, SameSite=Strict). The code
  works once. The terminal prints a new one only when the person presses Enter. When the server stops, it is gone.
- An approval runs the same function as the terminal command, in two steps: `preview` shows what the terminal would
  show and the code to type; `act` runs it with the code the person typed. A plan that changed between the two has
  another code, and the approval is refused, as in the terminal.
- `.harness/runtime/board-serve.json` holds the port while it runs: the gate refuses an agent's request to it.
- Talking to the chat (1.6, B72): `/api/send`, `/api/steer`, `/api/stop` (paired POST only; B78: `/api/compact`, which sends `/compact` to an idle chat) act through the link's thread, after it looked at the binding and the chat again. The confirmation code typed at an
  approval is not kept: no message to the agent holds it.
  `/api/language` (B85, paired POST only) sets the `language` setting: it writes `user.override.json`, the person's own file, and the board reads it again at once.
  Wallpaper (B89): `/api/wall` (a read, like `/api/board`) lists the pictures of the one folder the person chose; `/wall/<name>` hands out one of them (GET; see `wallpaper.py` for what is let through);
  `/api/wallfolder` (paired POST only) sets that folder in `user.override.json`, the person's own file; `/api/wallpick` (paired POST only) does so from the system's folder window. The server never resizes a picture: the page does.
  `/api/draft` lists, adds, edits, deletes and switches the notes of `.task/drafts.json`; `/api/setting` sets the task's model and thinking level (`chat.model`); `review set` runs through `/api/act`.
- New task (1.6, B73): `/api/create` (paired POST only; `step` options, preview or act) makes a chat in VS Code for a task the agent opens (`chatnew` checks every field again, `vslink.create` does it). It fails
  with a clear reason when VS Code is not ready; nothing is made then.
- Run (1.6.50): `/api/run` (paired POST only) starts, reads and stops a command of the person (`taskrun.py`).
- Rounds (1.6.55): `/api/rounds` (paired POST only) lists the rounds of a task's chat and gives one whole (`chatrounds.py`).
- Confirm and answer (1.6, B75): `/api/confirm` (allow or deny one tool call) and `/api/answer` (answer one question) are paired POSTs only. The page names the item (`id`, the `toolCallId` or request id,
  and the `digest` of what it showed); the link's thread reads the host again and refuses when the item is gone or changed (`chatask`). Each decision goes to the history and `.task/sent.jsonl`, the command
  redacted and cut.
- Gate review (1.6, B76): the report page (`/tasks/<name>/report.html`) is drawn by the server, with buttons for the verdicts; `/api/verdict` and `/api/export` (paired POST only) keep a verdict in the
  task state and write the samples of the blocks judged wrong (`gatereview`). `/report-save/<name>` gives the report as one file with no buttons and no calls. The report file on disk shows the verdicts, read only.
- Files, settings and taking back (1.6.22): `/api/send` and `/api/steer` take `attachments`; `/api/chatconfig` sets the mode and the tool permission of a chat; `/api/undo` takes the last message out of
  the chat (1.6.99: a turn that runs is stopped first). 1.6.99: `/api/queue` (with `attachments`) puts a message after the running turn, `/api/unqueue` takes one back, `/api/resume` runs a turn
  that ended in an error again. All are paired POSTs only.
- VS Code (1.6): one background thread (`vslink`) keeps a connection to the chats of VS Code and a cache; a request only reads the cache. Without VS Code
  `vscode.ready` is false: a request gets no error and no wait, and the Enter screen (`ready.py`) does not let a person in. `/api/open` (paired browser) asks the thread to bring the window of this folder forward.
"""

from __future__ import annotations

import http.server
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import re
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from core import ahp, approvals, company, config, messages, outbox, reach, registry, state, targets, tasks, toolpacks, user
from core import launchenv
from core import connections as conn_core
from core.paths import board_serve_file, board_serve_port, utc_now

from core import company, reinstall, setup as core_setup, shortcmd, skillboard

from . import chatrounds, testrecord
from . import kbview
from . import setupjob
from . import taskfileedit
from . import skillsend
from . import taskrun
from . import rewind
from . import tasksize
from . import wallpaper
from . import accept, autorun, boardterm, chatask, chatnew, chatsend, common, gatereview, health, intake, mdtree, task as task_ops, taskarchive, taskboard, taskdesk, taskfiles, taskhtml, taskinbox, tasklife, tasksub, taskreview, vslink
from . import ready as readiness
from . import reachcheck, vsrestart
from .common import CommandError

HEADER = "X-Harness-Board"
SHORT_KEEP = 60.0  # seconds the answer "the short command is found" is good for
SHORT_RETRY = 5.0  # and "not found": the person is about to run the line
COOKIE = "harness_board"
MAX_BODY = 4096
MAX_SEND_BODY = 64 * 1024  # `/api/answer`: the person's own words
MAX_FILES_BODY = (chatsend.MAX_FILES_TOTAL * 4) // 3 + chatsend.MAX_FILES * 1024 + MAX_SEND_BODY  # `/api/send`, `/api/steer` and `/api/create`: the words and their files, as base64
MAX_INBOX_BODY = 40 * 1024 * 1024  # `/api/inbox` carries pictures (base64); the other calls stay small
MAX_EDIT_BODY = 3 * 1024 * 1024  # `/api/fileop`: one text file the person edits (1 MB of UTF-8 at most, escaped in JSON)
MAX_ARCHIVE = 200  # tasks in one request
EARLY_ENTER = 2.0  # seconds after the start in which a line from the terminal is not taken for the person pressing Enter
REOPEN_EVERY = 3.0  # seconds
FREE = ("pause", "resume", "offwork", "onwork")  # no pairing: they guard nothing
SETTINGS = ("review set", "task allow", "task link", "test runner")  # settings the agent reads at its next step: they change nothing under its hands, so they work while it is at work (1.7.9)
ALL_AT_ONCE = ("offwork", "onwork")  # every task at once (`task offwork`, `task onwork`); allowed where `pause` is
BUILTIN = ("send", "answer", "steer", "stop", "create", "confirm", "question")  # the buttons that talk to the chat (1.6) and the "new task" button (B73): always offered by a served board, not a setting; each is a POST of a paired browser
DESK_REFRESH = 3  # seconds between two reads of a task page (10 until 1.7.26: a state that came from a hook, such as "waits for your answer", showed up about 7 seconds late)
REFRESH = 3  # seconds between two boards in the browser when `board.refresh_seconds` of the task policy says nothing
# The pages may run their own inline script and talk to this server only: an agent's text drawn on a page cannot load
# or send anything elsewhere, even if it ever got past the drawing (which uses textContent only).
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def refresh_seconds(value: Any) -> int:
    """Seconds between two boards in the browser: 1 to 600, else REFRESH."""
    number = config.whole(value, REFRESH)
    return number if 1 <= number <= 600 else REFRESH


def settings(root: Path) -> Dict[str, Any]:
    found = config.policy_or_empty(root, "task").get("board") or {}
    actions = found.get("actions")
    return {"port": config.whole(found.get("port"), 8765), "refresh": refresh_seconds(found.get("refresh_seconds")), "actions": list(actions) if isinstance(actions, list) else ["pause", "resume", "confirm-req", "approve-plan", "approve-promote", "review extend", "review waive", "review dismiss", "review set", "test runner", "task allow", "task link", "approve-action", "dismiss action", "autorun on", "recover", "archive", "close", "accept"]}


class Fallback(CommandError):
    """A send that was not done: the reason, and the text the person may copy to VS Code by hand."""

    def __init__(self, reason: str, text: str) -> None:
        super().__init__(reason)
        self.text = text


def ahp_scrub(error: BaseException) -> str:
    return say("send.refused.host", error=type(error).__name__)


class Preview(Exception):
    """Raised by the reader in the first step of an approval: what the terminal would ask, without approving."""

    def __init__(self, asked: str) -> None:
        super().__init__(asked)
        self.asked = asked


def runner(root: Path, action: str, task: str) -> Callable[..., Dict[str, Any]]:
    """The function of the terminal command, ready to be called with reader/interactive/out."""
    table: Dict[str, Callable[..., Dict[str, Any]]] = {
        "approve-plan": lambda **kw: task_ops.approve_plan(root, task, **kw),
        "confirm-req": lambda **kw: task_ops.confirm_req(root, task, **kw),
        "approve-promote": lambda **kw: task_ops.approve_promote(root, task, **kw),
        "review extend": lambda **kw: taskreview.extend(root, task, 2, **kw),
        "review waive": lambda **kw: taskreview.waive(root, task, **kw),
        "review dismiss": lambda **kw: taskreview.dismiss(root, task, **kw),
        "autorun on": lambda **kw: autorun.turn_on(root, task, **kw),
        "recover": lambda **kw: task_ops.recover(root, task, **kw),
        "approve-action": lambda **kw: outbox.approve_action(root, **kw),  # a call to an outside system held in the outbox (1.7.7): the person reads the command and types its code
    }  # `review set` is not here: it asks no code (see `Board.act`)
    return table[action]


_STAMP: Tuple[float, str] = (0.0, "")


def code_stamp(root: Path) -> str:
    """When the newest file of the engine (code, pages, messages) was written, as `MM-DD HH:MM`. A release that is changed again without a new number (a block in
    progress) is still told apart from what a running board loaded. Looked at at most once in 3 seconds."""
    global _STAMP
    now = time.time()
    if now - _STAMP[0] < 3 and _STAMP[1]:
        return _STAMP[1]
    newest = 0.0
    try:
        for current, folders, files in os.walk(str(root / ".harness" / "engine")):
            folders[:] = [name for name in folders if name != "__pycache__"]
            for name in files:
                if name.endswith((".py", ".js", ".css", ".html", ".json")):
                    newest = max(newest, os.stat(os.path.join(current, name)).st_mtime)
    except OSError:
        pass
    _STAMP = (now, time.strftime("%m-%d %H:%M", time.localtime(newest)) if newest else "")
    return _STAMP[1]


def disk_version(root: Path) -> str:
    try:
        return f"{registry.harness_version(root)} ({code_stamp(root)})" if code_stamp(root) else registry.harness_version(root)
    except Exception:  # noqa: BLE001 - a broken registry must not stop the board (doctor reports it)
        return ""


RESTART_AFTER = 0.3  # seconds for the answer to reach the page
RESTART_CODE = "HARNESS_BOARD_RESTART"  # the pairing code of the next process: in its environment, never on disk


CHAT_STILL = ("idle", "error", "input")  # VS Code says the chat runs no turn: it waits for the person (`input`: a question or a command to allow, 1.7.20), or its last turn failed


def trust_chat(row: Dict[str, Any]) -> bool:
    """A row (or a task page) whose bound chat runs no turn, as VS Code says, is not at work, whatever the hook log suggests (1.6.105: a subagent whose end was never recorded kept a
    task "working" for 30 minutes, and nothing on the board could be pressed while the agent waited for the person). True when it was put right."""
    chat = row.get("chat") or {}
    if row.get("state") != "working" or not chat.get("bound") or chat.get("state") not in CHAT_STILL:
        return False
    row["active"] = False
    row["state"] = tasklife.state_of(row.get("status", ""), row.get("paused_since", ""), row.get("waiting_why", ""), bool(row.get("held")), False)
    return True


def model_pair(model: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`message.model` as a picker shows it: `{id, thinking, context}` (the thinking level, or the level of Copilot Fusion); empty: none."""
    if not model:
        return {}
    found = model.get("config") or {}
    return {"id": model["id"], "thinking": str(found.get("thinkingLevel") or found.get("tier") or ""), "context": found.get("contextSize", 0)}


def relaunch(code: str) -> None:
    """The same command again, so new code and new texts are read. No exec replaces a process on Windows: it runs it and leaves with its answer, as `pinpython` does."""
    words = [sys.executable, *sys.argv]
    env = {**os.environ, RESTART_CODE: code}
    if os.name == "nt":
        sys.exit(subprocess.call(words, env=env))
    os.execve(sys.executable, words, env)



def servers_view(root: Path, vscode_open: bool) -> Dict[str, Any]:
    """What the Servers window shows (1.7.10): each server with its kind, environment, fields and whether an identity is saved (the account, never the password),
    what VS Code reached last, the kinds a person may add a server of, and whether VS Code is open now."""
    known = conn_core.types(root)
    env = conn_core.read_env(root)
    seen = reach.read(root)
    rows = []
    for alias, server in conn_core.listed(root).items():
        kind = known.get(str(server.get("type"))) or {}
        auth = (kind.get("auth") or {}).get(server.get("auth") or next(iter(kind.get("auth") or {}), ""), {}) or {}
        saved = conn_core.identity_of(env, alias, kind, server)
        reached = (seen.get(f"{alias}:{server.get('env', '')}") or {}).get("state", "")
        tool = conn_core.tool_program(auth) if auth.get("identity") == "tool" else ""
        rows.append({"alias": alias, "label": server.get("label", ""), "about": str(server.get("about") or ""), "type": server.get("type", ""), "type_label": kind.get("label", server.get("type", "")), "toolpack": kind.get("toolpack", ""), "known": bool(kind), "via": kind.get("via", "cli"), "login": auth.get("login", ""),
                     "env": server.get("env", ""), "auth": server.get("auth", ""), "auth_label": auth.get("label", ""), "identity": auth.get("identity", ""), "own": bool(server.get("own")),
                     "fields": {field: server.get(field, spec.get("default", "")) for field, spec in (kind.get("fields") or {}).items()},
                     "tool": tool,  # 1.7.38: the program whose own sign-in this connection uses; one sign-in per computer, shared
                     "account": saved.get("account", ""), "saved": bool(saved), "reach": reached,
                     "signed": bool(saved) or (bool(tool) and reached == reach.OK),  # a program keeps its own sign-in: a check that got through says it is signed in, whether or not the account was kept here. The Enter screen counts the same (retest N4)
                     "who": str((seen.get(f"{alias}:{server.get('env', '')}") or {}).get("who") or ""),
                     "untested": bool(saved) and reached == reach.UNKNOWN and (seen.get(f"{alias}:{server.get('env', '')}") or {}).get("why") == conn_core.UNTESTED})  # 1.7.38: `who` is the name a passed test answered with (a token has no account of its own to show); `untested`: kept, and no test has reached the system since
    kinds_out = {name: {"label": kind.get("label", name), "fields": kind.get("fields") or {}, "auth": {mode: {"label": (spec or {}).get("label", mode), "identity": (spec or {}).get("identity", ""), "login": (spec or {}).get("login", "")} for mode, spec in (kind.get("auth") or {}).items()}}
                 for name, kind in known.items() if not conn_core.type_problems(kind)}
    return {"connections": rows, "signins": conn_core.signins(root), "types": kinds_out, "state": conn_core.state(root), "vscode_open": bool(vscode_open), "env_wrong": launchenv.seen(root).get("ok") is False, "windows": os.name == "nt"}


EMBEDDED = re.compile(r"\bElectron/\d")  # the user agent of VS Code's own browser (an Electron app); Chrome, Edge and Firefox never send it

class Board:
    """What one server holds: the settings, the pairing code and the sessions of paired browsers. Memory only."""

    def __init__(self, root: Path, everything: bool, port: int, actions: List[str], link: Optional[vslink.VsLink] = None, refresh: int = REFRESH) -> None:
        self.root = root
        self.runner = taskrun.Runner(root)
        self.terminal = boardterm.Terminal(root)
        self.short_missing = False
        self.setup_job = setupjob.Job()
        self.tested: Dict[str, Any] = {}  # alias -> (the values that passed a test, when): Servers saves only those (1.7.10)
        self.short_kept: Optional[Dict[str, Any]] = None
        self.short_at = 0.0
        self.kb_view = kbview.View(root)
        self.refresh = refresh
        self.link = link or vslink.VsLink(root, enabled=False)  # a board made without a link (the tests) has none
        self.everything = everything
        self.port = port
        self.actions = actions
        self.restarted = bool(os.environ.get(RESTART_CODE))
        self.code = os.environ.pop(RESTART_CODE, "") or secrets.token_urlsafe(12)  # after Restart board the page brings this code back; a new process holds no session
        self.next_code = ""
        self.server: Any = None
        self.opener: Callable[[str], Any] = webbrowser.open
        self.reopened = -REOPEN_EVERY
        self.sessions: set = set()
        self.lock = threading.Lock()
        self.wall_window = threading.Lock()  # one folder window at a time
        self.language_stamp: List[int] = []
        self.version = disk_version(root)  # the release this process loaded: code changed on disk is not used until the board starts again (B63)
        self.checker = reachcheck.Checker(root)  # the board looks at the outside connections itself, in the background (1.7.19)
        self.ready = readiness.Ready(root, self.link, checker=self.checker)  # the Enter screen (`/api/ready`)
        self.restarter = vsrestart.Restart(launchenv.vscode_running, self.open_vscode, gone=self.link.hurry, chats=lambda: self.other_chats([]))  # the VS Code button of the screen (1.7.38): quit, wait, open
        self.ready.restart = self.restarter
        self.space = tasksize.Watch(root)  # how much room the task folders take, measured once an hour (1.6.109)
        self.who: Tuple[Any, str] = (None, "")  # (the stamp of the user files, the name) for `user_name`

    def user_name(self) -> str:
        """The name for `Hi, <name>` on the Enter screen: what `harness user` reads (user.override.json, else `git config user.name`).
        Kept until the user files change (1.6.109): every page has it, and git takes seconds to start on a slow computer. Before, a page waited on git once a minute."""
        stamp = self.user_stamp()
        with self.lock:
            if self.who[0] == stamp:
                return self.who[1]
        try:
            name = user.who(self.root)["name"]
        except Exception:  # noqa: BLE001 - no name is only a plainer greeting
            name = ""
        with self.lock:
            self.who = (stamp, name)
        return name

    def user_stamp(self) -> List[int]:
        """The times of `user.json` and its override: what the person may change while the board runs."""
        stamp = []
        for path in (config.policies_dir(self.root) / "user.json", config.override_path(self.root, "user")):
            try:
                stamp.append(path.stat().st_mtime_ns)
            except OSError:
                stamp.append(0)
        return stamp

    def serve_info(self, found: Dict[str, Any], refresh: int) -> Dict[str, Any]:
        """What a served page gets besides the rows: the actions, the refresh, and what the Enter screen shows without asking (the name, the release)."""
        return {"actions": self.served, "refresh": refresh, "run_kinds": taskrun.kinds(), **found, "user": self.user_name(), "version": self.release()}

    def release(self) -> str:
        try:
            return registry.harness_version(self.root)
        except Exception:  # noqa: BLE001 - a broken registry is doctor's to report
            return ""

    def sync_language(self) -> str:
        """The language now set in `user.json`. The process reads it once (`messages.language`), so a board that ran on
        while the person changed it would speak the old one: when the file (or its override) changed, it is read again.
        A stat per request is cheap."""
        stamp = self.user_stamp()
        with self.lock:
            if stamp != self.language_stamp:
                self.language_stamp = stamp
                messages.reset()
        return messages.language()

    @property
    def served(self) -> List[str]:
        """What the page may run: the settings' actions and the ones that talk to the chat."""
        return self.actions + [item for item in BUILTIN if item not in self.actions]

    def open_page(self) -> bool:
        """The browser of this computer, with a new code. Not more than once in REOPEN_EVERY seconds: a request must not be able to flood the screen with tabs."""
        with self.lock:
            if time.monotonic() - self.reopened < REOPEN_EVERY:
                return False
            self.reopened = time.monotonic()
        try:
            return bool(self.opener(f"http://127.0.0.1:{self.port}/#pair={self.new_code()}"))
        except Exception:  # noqa: BLE001 - the second start opens the plain address then
            return False

    def new_code(self) -> str:
        with self.lock:
            self.code = secrets.token_urlsafe(12)
            return self.code

    @property
    def cookie(self) -> str:
        """The name of this board's cookie. Cookies do not tell ports apart: with one name, a second board in the same browser would take this one's pairing away."""
        return f"{COOKIE}_{self.port}"

    def pair(self, code: str) -> Optional[str]:
        """A session token for the right code; the code is used up."""
        with self.lock:
            if not self.code or not secrets.compare_digest(code.encode(), self.code.encode()):
                return None
            self.code = ""
            token = secrets.token_urlsafe(24)
            self.sessions.add(token)
            return token

    def paired(self, token: str) -> bool:
        with self.lock:
            return bool(token) and token in self.sessions

    def rows(self) -> Dict[str, Any]:
        """The rows of the board as the page draws them, and how many older closed tasks are left out."""
        self.close_promoted()
        result, _problems = taskboard.board_rows(self.root, self.everything, 0, self.served, rewrite=False)
        self.link.overlay(result["tasks"])
        for row in result["tasks"]:
            trust_chat(row)
            health.with_context(self.root, row, row.get("chat"))
        asked = [taskboard.with_ask(row, self.link.ask_of(row["task"]), tuple(self.served), self.root) for row in result["tasks"] if row.get("status") == "open"]
        if any(asked):  # the chat waits for a person to allow a command or answer a question: that wait comes first in the order
            tasklife.sort_rows(result["tasks"])
        for row in result["tasks"]:  # the agent is at work in the chat: say something to it, or stop it
            if row.get("status") == "open" and (row.get("chat") or {}).get("state") == "busy" and "steer" in self.served:
                row["actions"] = [item for item in row["actions"] if item["action"] not in ("steer", "stop")] + [{"action": "steer", "command": ""}, {"action": "stop", "command": ""}]
        return {"rows": result["tasks"], "hidden": result["closed_hidden"], "as_of": utc_now(), "kb_found": company.found_in_place(self.root), "archive_to": taskarchive.remembered(self.root), "vscode": self.link.status(),
                "space": self.space.view(result["tasks"])}

    SWEEP_EVERY = 5.0  # seconds between two looks for a promoted task that waits for nothing

    def close_promoted(self) -> List[str]:
        """The promote is the acceptance of a development task: when it is done, the agent has stopped and nothing else waits, the board closes the task (1.7.38, C12 Q14). At most once in a few seconds."""
        now = time.monotonic()
        with self.lock:
            if now - getattr(self, "swept", -self.SWEEP_EVERY) < self.SWEEP_EVERY:
                return []
            self.swept = now
        closed = accept.sweep(self.root)
        for name in closed:
            print(say("serve.did", action="close (promoted)", task=name), flush=True)
        return closed

    def open_vscode(self) -> None:
        """Bring the VS Code window of this folder forward, started with this computer's settings; the connections are checked at once. Raises the reason when it cannot be asked (`/api/open`, and the end of a restart)."""
        if not self.link.status().get("ready") and not launchenv.vscode_running():
            launchenv.mark_started(self.root)  # this start has the settings: what an earlier one lacked no longer holds
        asked = self.link.open_window()
        if asked != "queued":
            raise ValueError(say("serve.open.off") if asked == "off" else say("serve.open.no-cli"))
        self.checker.start()  # the connections are checked at once, in VS Code's environment, so the Enter screen has a word within seconds (1.7.19)

    def working_tasks(self) -> List[str]:
        """The names of the open tasks whose agent is at work now: the hook log says so and VS Code does not say its chat runs no turn (`idle`), or VS Code says the chat is busy. A restart of VS Code would stop them."""
        found: List[str] = []
        for task in tasks.folders(self.root):
            data = tasks.read(self.root, task)
            if not data or data.get("status") != "open":
                continue
            chat = self.link.chat_of(task)
            busy = chat.get("bound") and chat.get("state") == "busy"
            if busy or (tasklife.at_work(self.root, data) and not (chat.get("bound") and chat.get("state") in CHAT_STILL)):
                found.append(Path(task).name)
        return found

    def other_chats(self, working: List[str]) -> List[str]:
        """The names of the chats VS Code lists as running or waiting for the person that `working_tasks` did not name: VS Code asks about each of them before it quits (`veto.chat`), a chat of a task or not, in any folder.
        A chat of an open task is named by the task; any other by its title. Said before the restart, so the person is not first met by VS Code's own question."""
        found: List[str] = []
        for chat in self.link.running_chats():
            name = Path(chat["task"]).name if chat["task"] else chat["title"].strip() or say("restart.chat.untitled")
            if name not in working and name not in found:
                found.append(name)
        return found

    def page(self) -> str:
        found = self.rows()
        return taskhtml.board_page(found["rows"], found["as_of"], 0, serve=self.serve_info({"archive_to": found["archive_to"], "vscode": found["vscode"], "kb_found": found["kb_found"], "space": found["space"]}, self.refresh), hidden=found["hidden"])

    def desk(self, name: str, trace_tree: bool = False) -> Dict[str, Any]:
        found = taskdesk.desk(self.root, name, self.served, trace_tree)  # the tree reads whole logs: only for a Trace tab that is open
        chat = self.link.chat_of(found["task"], name)
        recent = chat.pop("recent", "")
        sub = chat.pop("sub", None) or tasksub.from_hooklog(self.root, tasks.read(self.root, found["task"]) or {})  # the chat's own line; else the hook log's
        if chat.get("bound"):
            chat.update(self.link.context_card(found["task"]))
        found["chat"], found["sub"], found["recent"], found["vscode"] = chat, sub, recent, self.link.status()
        trust_chat(found)
        health.with_context(self.root, found, chat)
        if found["status"] == "open":
            taskboard.with_ask(found, self.link.ask_of(found["task"]), tuple(self.served), self.root)
        if chat.get("state") == "busy" and found["status"] == "open" and "steer" in self.served:
            found["actions"] = [item for item in found["actions"] if item["action"] not in ("steer", "stop")] + [{"action": "steer", "command": ""}, {"action": "stop", "command": ""}]
        found["settings"] = self.settings_of(found["task"])
        found["reply_lang"] = chatsend.reply_of(self.root, found["task"])
        return found

    def settings_of(self, task: str) -> Dict[str, Any]:
        """The row `Task settings` of the task page: the checks (0 to the cap), and the model and thinking level of the messages the board sends, from the models the host lists."""
        data = tasks.read(self.root, task) or {}
        model = chatsend.model_of(data) or {}
        return {"n": taskreview.state_of(data)["n"], "max_n": taskreview.settings(self.root)["max_n"], "model": model.get("id", ""), "thinking": (model.get("config") or {}).get("thinkingLevel") or (model.get("config") or {}).get("tier", ""), "context": (model.get("config") or {}).get("contextSize", 0), "options": self.link.chat_options(task),
                "models": self.link.model_list(), "ready": bool(self.link.status()["ready"])}

    def keep_override(self, key: str, value: Any) -> None:
        """One key of `user.override.json`, the person's own file, next to what is already there (nothing else in it changes). `value` None removes the key."""
        path = config.override_path(self.root, "user")
        kept: Dict[str, Any] = {}
        if path.exists():
            try:
                kept = json.loads(path.read_text(encoding="utf-8-sig"))
            except ValueError as error:
                raise CommandError(say("serve.language.broken", file=str(path), error=error)) from None
            if not isinstance(kept, dict):
                raise CommandError(say("serve.language.broken", file=str(path), error="not an object"))
        if value is None:
            kept.pop(key, None)
        else:
            kept[key] = value
        state.atomic_write(path, kept)

    def set_language(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The `language` setting of the harness (`en` or `zh`), written to `user.override.json` next to what the person already keeps there, as `task archive --remember` does. A paired browser only.
        The board reads it again at once (`sync_language`), so the answer already carries the new language and an open page loads its texts again."""
        wanted = str(data.get("language", "")).strip().lower()
        if wanted not in messages.LANGUAGES:
            raise CommandError(say("serve.language.bad"))
        forced = os.environ.get(messages.ENVIRONMENT, "").strip().lower()
        if forced and forced != wanted:
            raise CommandError(say("serve.language.env", name=messages.ENVIRONMENT))  # the environment wins over the file: writing the file would change nothing
        self.keep_override("language", wanted)
        self.language_stamp = []  # the file is new: read it at once
        return {"language": self.sync_language()}

    def set_wall_folder(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The folder the wallpaper is read from (a paired browser only). Empty: no wallpaper folder. A path that is not a folder on this computer is refused and nothing is written.
        The answer is the listing of the folder, as `/api/wall` gives it."""
        text = wallpaper.clean(data.get("folder", ""))
        if not text:
            self.keep_override(wallpaper.KEY, None)
        else:
            found = wallpaper.directory(text)
            if found is None:
                raise CommandError(say("serve.wall.missing", folder=text[:200]))
            self.keep_override(wallpaper.KEY, str(found))
        return wallpaper.listing(self.root)

    def pick_wall_folder(self) -> Dict[str, Any]:
        """The folder chosen in the system's window, which waits for the person on this request's own thread (a paired browser only). Cancelled: nothing changes."""
        if not self.wall_window.acquire(blocking=False):
            raise CommandError(say("serve.wall.picking"))
        try:
            text = wallpaper.pick(say("serve.wall.prompt"))
        except OSError as error:
            raise CommandError(say("serve.wall.nopicker")) from error
        finally:
            self.wall_window.release()
        return {"wall": self.set_wall_folder({"folder": text}), "cancelled": False} if text else {"wall": wallpaper.listing(self.root), "cancelled": True}

    def desk_page(self, name: str) -> str:
        return taskhtml.desk_page(self.desk(name), self.serve_info({}, DESK_REFRESH))

    def report_info(self, name: str) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
        task = task_ops.resolve(self.root, name)
        info, now = taskboard.insight(self.root, task)
        return task, taskboard.with_gate(self.root, task, info), now

    def report_page(self, name: str) -> str:
        """The time-and-usage page as the server sends it: the Gate verdicts have buttons, and the page can be saved."""
        _task, info, now = self.report_info(name)
        return taskhtml.task_page(info, 0, now, serve={"actions": self.served})

    def saved_report(self, name: str) -> Tuple[str, str]:
        """The same page as one file to keep or send (file name, page): as of now, verdicts shown, no buttons, no calls."""
        _task, info, now = self.report_info(name)
        stem = re.sub(r"[^\w.-]+", "-", info["name"]).strip("-.") or "task"
        return f"{stem}-report-{time.strftime('%Y-%m-%d')}.html", taskhtml.saved_report(info, now)

    def named(self, data: Dict[str, Any]) -> str:
        """The task a page named: a name is needed (an empty one would pick the one open task, and a verdict must not go by luck)."""
        if not str(data.get("task", "")).strip():
            raise CommandError(say("gate.refused.task"))
        return task_ops.resolve(self.root, str(data["task"]))

    def verdict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The person's verdict on one Gate block (right, wrong, unsure; empty takes it back). Any task, closed ones too: the report of a closed task is read later."""
        task = self.named(data)
        found = gatereview.set_verdict(self.root, task, str(data.get("id", "")), str(data.get("verdict", "")))
        taskboard.refresh_report(self.root, task)
        return {"gate": found}

    def export(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Write a sample for each block judged wrong (`.harness/eval/fixtures/gate/<rule>/`)."""
        task = self.named(data)
        done = gatereview.export(self.root, task)
        taskboard.refresh_report(self.root, task)
        return {"files": done["files"], "gate": done["section"]}

    def snapshot(self, name: str) -> Tuple[str, str]:
        """The task page as one file to keep or send (file name, page): as of now, no buttons, nothing that talks to a server.
        The commands the buttons would copy and the link to the time-and-usage page mean nothing away from this board: they are left out."""
        found = self.desk(name)
        found["actions"], found["report"] = [], ""
        taskfiles.embed(self.root, found["task"], found["files"])
        for item in found["files"]:  # a picture of the Files tab comes in as its own bytes
            if item["kind"] == "image":
                node = {"t": "img", "src": item["path"]}
                taskdesk.embed_images(self.root, name, node)
                item["data"] = node.get("data", "")
        for past in found["rounds"]:
            taskfiles.embed(self.root, found["task"], past["files"])
        taskdesk.embed_images(self.root, name, [found["docs"], found["test"], [item.get("doc") for item in found["files"]]])
        stem = re.sub(r"[^\w.-]+", "-", found["name"]).strip("-.") or "task"
        return f"{stem}-{time.strftime('%Y-%m-%d')}.html", taskhtml.desk_page(found)

    def intake(self, action: str, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """What the Intake tab asks for. The names and the text come from a page: each call checks them."""
        import base64

        if action == "upload":
            try:
                raw = base64.b64decode(str(data.get("data", "")), validate=True)
            except ValueError:
                raise CommandError(say("inbox.image_bad", n=1)) from None
            return intake.add_file(self.root, task, str(data.get("name", "")), raw, bool(data.get("include_hidden")))
        if action == "paste":
            return intake.paste(self.root, task, str(data.get("name", "")), str(data.get("text", "")), str(data.get("kind", "csv")))
        if action == "init":
            chosen = data.get("domains")
            return intake.init(self.root, task, [str(item) for item in chosen] if isinstance(chosen, list) else None)
        if action == "read":
            return intake.read_for_edit(self.root, task, str(data.get("path", "")))
        if action == "save":
            return intake.save_text(self.root, task, str(data.get("path", "")), str(data.get("text", "")))
        if action == "reset":
            return intake.reset_file(self.root, task, str(data.get("path", "")))
        if action == "delete":
            return intake.delete_file(self.root, task, str(data.get("path", "")))
        if action == "rename":
            return intake.rename_file(self.root, task, str(data.get("path", "")), str(data.get("name", "")))
        if action == "delete_many":
            chosen = data.get("paths")
            return intake.delete_files(self.root, task, [str(item) for item in chosen] if isinstance(chosen, list) else [])
        raise CommandError(say("serve.refused.request"))

    def archive(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Move closed tasks out of the repository (`task archive`). `step`: `preview` says what would move; `act` moves them.
        The browser must be paired; no code is typed, for it changes no repository and an agent may do it with the person's yes."""
        if "archive" not in self.actions:
            raise CommandError(say("serve.action.off", action="archive"))
        names = data.get("tasks")
        if not isinstance(names, list) or not names or len(names) > MAX_ARCHIVE or not all(isinstance(name, str) and name for name in names):
            raise CommandError(say("serve.refused.request"))
        apply = str(data.get("step", "preview")) == "act"
        result = taskarchive.archive(self.root, names, False, str(data.get("to", "")).strip(), apply, bool(data.get("remember")) and apply)
        if apply:
            print(say("serve.did", action="archive", task=", ".join(result["archived"])), flush=True)
            self.space.again()  # the advice to archive goes as soon as the folders are measured again
        return result

    def idle(self, action: str, task: str) -> bool:
        """The page may be ten seconds old: before any action, look again whether the agent is in the middle of a turn (it may be answering a doubt). VS Code's own word that the bound chat
        runs no turn wins over the hook log (1.6.105). True when the agent is not at work by that word only: a check of its own further on is told so."""
        found = task_ops.resolve(self.root, task)
        data = tasks.read(self.root, found)
        if data is None or not tasklife.at_work(self.root, data):
            return False
        chat = self.link.chat_of(found)
        if chat.get("bound") and chat.get("state") in CHAT_STILL:
            return True
        raise CommandError(say("serve.busy"))

    def close(self, name: str, reason: str = "") -> Dict[str, Any]:
        """Close a task (`task close`): the report is written, the session lets go. The folder stays; `task open` opens it again.
        The browser must be paired; no code is typed, for it undoes nothing that cannot be undone. `reason`: what the person typed in the dialog (like `task close --reason`); else the page's own words."""
        if "close" not in self.actions:
            raise CommandError(say("serve.action.off", action="close"))
        self.idle("close", name)
        words = reason.strip()[:500]
        result = task_ops.close(self.root, name, words or say("serve.close.reason"), check_todo=False, todo_note=words or say("serve.close.reason"))
        print(say("serve.did", action="close", task=task_ops.name_of(result["task"])), flush=True)
        return result

    def act(self, action: str, task: str, step: str, code: str = "", with_req: bool = False, n: Any = None, env_name: str = "", who: str = "", reason: str = "", note: str = "") -> Dict[str, Any]:
        """Run one action. `step`: `preview` or `act` for an approval; pause and resume act at once. `env_name` and `who` (agent or person) are for `test runner` only; `reason` and `note` for `dismiss action`."""
        if action in ALL_AT_ONCE:
            if "pause" not in self.actions:
                raise CommandError(say("serve.action.off", action=action))
            result = (tasklife.offwork if action == "offwork" else tasklife.onwork)(self.root, interactive=True)
            for name in result.get("paused") or result.get("resumed") or []:
                noted(self.root, name, action)
            return result
        if action not in self.actions:
            raise CommandError(say("serve.action.off", action=action))
        still = False if action in SETTINGS else self.idle(action, task)
        if action == "accept":  # the person accepts the delivered work (1.7.38): the board closes the task; nothing is sent to the chat
            result = accept.accept(self.root, task)
            noted_after = result.get("task") or task
            print(say("serve.did", action="accept", task=task_ops.name_of(noted_after)), flush=True)
            return result
        if action == "dismiss action":  # the person says no to a held call (1.7.7): the code names it, nothing runs. A reason (1.7.38) goes to the agent: at once by its wait, else by a message when its turn ended
            try:
                result = outbox.dismiss_action(self.root, str(code or ""), interactive=True, reason=str(reason or ""), note=str(note or ""))
            except ValueError as error:
                raise CommandError(str(error)) from None
            noted(self.root, task, action)
            result["told"] = self.after_dismiss(result)
            return result
        if action == "task allow":  # the person closes a connection for this task with one click (1.7.6); the same function as `task allow`. Opening one needs the code of a held call that offers it (1.7.38)
            name = " ".join(str(env_name or "").split()).lower()
            on, offer = str(who or "") == "on", None
            if on and name != tasklife.LINKS:
                offer = outbox.offer_for(self.root, task_ops.resolve(self.root, task), str(code or ""), name)
                if not offer:
                    raise CommandError(say("serve.allow.code", name=name or "-"))
            result = tasklife.set_allow(self.root, task, name, on, interactive=True, env=str((offer or {}).get("env") or ""))
            if offer:  # the held calls that offered it have done their part: the agent that waits hears at once, one whose turn ended is woken, else the page asks the person to tell it (1.7.38)
                found = result.get("task") or task_ops.resolve(self.root, task)
                stood = {str(item["code"]): outbox.agent_place(item) for item in outbox.pending_for(self.root, found) if any(isinstance(one, dict) and one.get("system") == name for one in item.get("offers") or [])}
                outbox.mark_opened_everywhere(self.root, found, [name])
                self.after_decision(found, [(each, place) for each, place in stood.items() if (self.entry(each) or {}).get("state") == "opened"], messages.text("desk.outbox.opened.body", names=name))
            noted(self.root, result.get("task") or task, action)
            return result
        if action == "task link":  # one click, no code: the person names an item of an outside tool in the task, or takes it away (1.7.20); the same function as `task link add|remove`
            if str(who or "") == "on":
                tasklife.check_link_type(self.root, str(env_name or ""))  # a type no installed tool pack gives is refused here, with the types there are (1.7.22)
            result = tasklife.link(self.root, task, str(env_name or ""), str(who or "") == "on", by_person=True)
            noted(self.root, result.get("task") or task, action)
            return result
        if action == "test runner":  # one click, no code: the person lets the agent run an environment of the test guide, or takes it back (1.7.2)
            result = testrecord.set_runner(self.root, task, str(env_name or ""), str(who or "") == testrecord.AGENT, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        if action == "review set":  # one click, no code: the same function as `task review set`; the cap and the history are its own
            result = taskreview.set_by_person(self.root, task, n if isinstance(n, int) and not isinstance(n, bool) else -1, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        if action in FREE:
            result = tasklife.pause(self.root, task, interactive=True, force=still) if action == "pause" else tasklife.resume(self.root, task, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        call = runner(self.root, action, task)
        if action == "autorun on" and still:  # its own check reads the hook log only
            alone = call
            call = lambda **kw: alone(force=True, **kw)  # noqa: E731
        if action == "approve-plan" and with_req:
            plain = call
            call = lambda **kw: plain(with_req=True, **kw)  # noqa: E731 - the requirement and the plan, one code
        stood = self.entry(code) if action == "approve-action" and step == "act" else None  # where the agent stood before the person's yes (1.7.38)
        out = io.StringIO()
        if step == "preview":
            def stop(asked: str) -> str:
                raise Preview(asked)

            try:
                call(reader=stop, interactive=True, out=out)
            except Preview as asked:
                return {"screen": [line for line in out.getvalue().splitlines() if line.strip()], "ask": asked.asked}
            except ValueError as error:
                raise CommandError(str(error)) from None
            raise CommandError(say("serve.preview.none"))
        try:
            result = call(reader=lambda _asked: code, interactive=True, out=out)
        except ValueError as error:  # core.outbox says no with a plain error; the page shows it as a refusal
            raise CommandError(str(error)) from None
        noted(self.root, result.get("task") or task, action)
        if stood and stood.get("task"):
            self.after_decision(str(stood["task"]), [(str(stood["code"]), outbox.agent_place(stood))], messages.text("desk.outbox.tell.body", codes=str(stood["code"])))
        return result

    # --- the agent, after the person decided on a held call (1.7.38) -----------------------------------------------

    def entry(self, code: str) -> Optional[Dict[str, Any]]:
        """The entry of a held call by its code, in any state it is in (None when none)."""
        try:
            return approvals.find(self.root, str(code or ""), approvals.minutes(config.policy_or_empty(self.root, "gate")), file=approvals.ACTIONS)
        except Exception:  # noqa: BLE001
            return None

    def after_decision(self, task: str, decided: List[Tuple[str, str]], text: str) -> None:
        """The person approved calls or opened their connection. `decided`: each code and where the agent stood (`outbox.agent_place`). One that waits in `harness wait --approval` hears it by itself
        (the entry is marked). One whose wait ran out and whose turn ended is woken with `text`, as one message for all of them. Others are left: the card asks the person to tell the agent."""
        minutes = approvals.minutes(config.policy_or_empty(self.root, "gate"))
        for code, place in decided:
            if place == "wait":
                approvals.told(self.root, code, "wait", minutes, file=approvals.ACTIONS)
        ended = [code for code, place in decided if place == "ended"]
        if ended and self.wake(task, text):
            for code in ended:
                approvals.told(self.root, code, "message", minutes, file=approvals.ACTIONS)

    def after_dismiss(self, done: Dict[str, Any]) -> str:
        """The person did not approve a held call. The agent that waits has the reason from its wait. One whose turn ended on the call is woken with the reason, when there is one; without a reason, or when the
        agent went on, it is only written in the task. Returns what happened: `wait`, `message` or `logged`."""
        try:
            task = str(done.get("task") or "")
            entry = self.entry(str(done.get("code") or "")) or {}
            if done.get("agent") == "wait":
                return "wait"
            if done.get("reason") and done.get("agent") == "ended" and task and self.wake(task, outbox.wake_dismissed(entry)):
                return "message"
            if task:
                with task_ops.locked(self.root, task) as data:
                    task_ops.note(data, "outbox-dismiss", f"{done.get('code')}: {outbox.reason_text(str(done.get('reason') or ''), str(done.get('note') or ''))}")
        except Exception:  # noqa: BLE001 - the call is dismissed; a missing line must not undo it in the person's eyes
            pass
        return "logged"

    def wake(self, task: str, text: str) -> bool:
        """Send `text` to the chat of the task as an answer (the agent's turn ended; the person has decided), without the person's saved drafts. False when it cannot go (no chat, VS Code closed, the chat is busy):
        nothing is lost, the page then asks the person to tell the agent."""
        try:
            found = tasks.read(self.root, task) or {}
            made = chatsend.prepare(self.root, task, "answer", "", "", text, "", with_drafts=False)
            model = chatsend.model_of(found)
            done = self.link.dispatch("send", task, made["text"], model, [])
        except Exception:  # noqa: BLE001 - see above
            return False
        try:
            tasklife.set_waiting(self.root, task, None)  # it works again; the card of the wait is gone with the answer
        except Exception:  # noqa: BLE001
            pass
        self.sent(task, found, "answer", made["text"], done, {"why": "", "lang": made["lang"], "model": model or {}, "drafts": 0, "files": [], "by": "board"})
        return True

    # --- talking to the chat (B72) ---------------------------------------------------------------------------------

    def target(self, data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        task = task_ops.resolve(self.root, str(data.get("task", "")))
        found = tasks.read(self.root, task) or {}
        task_ops.require_open(found)
        return task, found

    def refusal(self, why: str) -> str:
        return say(f"send.refused.{why}")

    def message(self, task: str, found: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        """The whole message of a send as the page asked for it (`kind` go or answer, `lang`, `note`, `body`). Python makes the text: the page only shows it."""
        kind = str(data.get("kind", "go"))
        why = tasklife.waiting(self.root, task, found)["why"] if kind == "go" else ""  # `command`: the "Ask agent" button of a code block
        if kind == "go" and why not in chatsend.GO:
            raise CommandError(self.refusal("nogo"))
        try:
            made = chatsend.prepare(self.root, task, kind, why, str(data.get("lang", "")), str(data.get("body", "")), str(data.get("note", "")))
        except ValueError as error:
            raise CommandError(self.refusal("text." + str(error))) from None
        made["kind"], made["why"] = kind, why
        return made

    def sent(self, task: str, found: Dict[str, Any], kind: str, text: str, done: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """After the host was told: one line of history, the whole text in `.task/sent.jsonl`. A message that went must not come back as an error because a note could not be written."""
        out: Dict[str, Any] = {"sent": True, "chat": done.get("title", ""), "text": text, "recorded": True}
        try:
            entry = {"at": utc_now(), "task": task, "kind": kind, "chat": done.get("chat", ""), "title": done.get("title", ""), "turn": done.get("turn", ""), "text": text, **(extra or {})}
            chatsend.record(self.root, task, entry)
            with task_ops.locked(self.root, task) as again:
                task_ops.note(again, kind if kind != "go" else "send", (done.get("title") or "-")[:60] + ": " + chatsend.summary(text))
        except Exception:  # noqa: BLE001
            out["recorded"] = False
        return out

    def short_now(self) -> Dict[str, Any]:
        """Is the short command found? The answer comes from a login shell, which is slow on a work computer and the page asks every few seconds: it is kept a while, longer once found."""
        now = time.monotonic()
        held = self.short_kept
        if held is None or now - self.short_at > (SHORT_KEEP if held["found"] else SHORT_RETRY):
            self.short_kept, self.short_at = core_setup.short_state(self.root), now
        return self.short_kept

    def servers(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get ready, Servers (1.7.10). `step`: list, test, save (only what passed a test in the last 15 minutes, the same values), forget, share, plan, open
        (VS Code with the chosen identities; refused while a VS Code of this folder is open: it could not take them). Never a password back to the page."""
        import hashlib

        step = str(data.get("step", ""))
        alias = str(data.get("alias") or "")
        given = {key: str(data.get(key) or "") for key in ("account", "password", "keyfile", "token")}
        own = data.get("own") if isinstance(data.get("own"), dict) else None
        if own is not None:
            own = {key: str(value) for key, value in own.items() if key in conn_core.OWN_FIELDS or key in ((conn_core.types(self.root).get(str(own.get("type"))) or {}).get("fields") or {})}
            if not conn_core.ALIAS.match(alias) or alias in conn_core.company_connections(config.policy_or_empty(self.root, conn_core.POLICY)):
                raise ValueError(say("connections.alias.bad", alias=alias))
            if own.get("env") not in ("dev", "ist", "qat", "none"):
                raise ValueError(say("connections.own.env.none"))
        stamp = hashlib.sha256(json.dumps([alias, given, own], sort_keys=True).encode("utf-8")).hexdigest()
        if step == "list":
            return servers_view(self.root, self.link.status().get("ready", False))
        if step == "test":
            found = conn_core.test(self.root, alias, given, server=dict(own, own=True) if own else None, saved=bool(data.get("saved")))
            if found["state"] in ("ok", "mcp"):  # an MCP connection has nothing to test here: what is kept is the connection itself
                self.tested[alias] = (stamp, time.time(), found.get("who", ""))
            if data.get("saved") and not own and found["state"] != "mcp":  # a test of what is kept here says how that connection is now (1.7.38)
                self.note_reach(alias, found)
            if data.get("keep") and not own:  # the sign-in form of a listed connection: a test that never reached the system keeps what was typed (1.7.38)
                found["kept"] = conn_core.keep_untested(self.root, alias, found, given)
            return found
        if step == "save":
            passed = self.tested.get(alias)
            if not passed or passed[0] != stamp or time.time() - passed[1] > 900:
                raise ValueError(say("connections.save.untested"))
            conn_core.save(self.root, alias, given, own, who=passed[2] if len(passed) > 2 else "")
            self.tested.pop(alias, None)
            self.note_reach(alias, {"state": "ok", "why": "", "who": passed[2] if len(passed) > 2 else ""}, own)  # it passed the test just before: the old failure is gone
            return {"saved": alias}
        if step == "forget":
            conn_core.forget(self.root, alias)
            return {"forgot": alias}
        if step == "forget-tool":  # the sign-in of a program shared by the connections of a type (1.7.37)
            conn_core.forget_tool(self.root, str(data.get("program") or ""))
            return {"forgot": str(data.get("program") or "")}
        if step == "export":  # one's own connections in the form of connections.json (Tools, Connections, Export): no identity
            return conn_core.export(self.root)
        if step == "share":  # into the company pack: the server only, never the identity (knowledge base, Pack for colleagues)
            return conn_core.share(self.root, [str(item) for item in (data.get("aliases") or []) if isinstance(item, str)])
        chosen = [str(item) for item in (data.get("chosen") or []) if isinstance(item, str)]
        primary = str(data.get("primary") or "")
        if step == "plan":
            return conn_core.plan(self.root, chosen, primary)
        if step == "open":
            if self.link.status().get("ready"):
                raise ValueError(say("connections.open.running"))
            code = ahp.find_code()
            if not code:
                raise ValueError(say("serve.open.no-cli"))
            made = conn_core.launch(self.root, chosen, primary, [code, str(self.root)])
            if made.get("started"):
                launchenv.mark_started(self.root)  # VS Code is on its way: look for its host often, and check the connections now, not at the first chat
                self.link.hurry()
                self.checker.start()
            return made
        raise ValueError(say("serve.refused.request"))

    def note_reach(self, alias: str, found: Dict[str, Any], own: Optional[Dict[str, Any]] = None) -> None:
        """Keep what a test of a connection found out beside the probes' answers (`core.reach.record`). A connection with no environment of the list is not recorded."""
        try:
            server = own or conn_core.listed(self.root).get(alias) or {}
            env = str(server.get("env") or "")
            if env not in conn_core.ENVS:
                return
            state = {"ok": reach.OK, "denied": reach.DENIED}.get(str(found.get("state")), reach.FAILED)
            reach.record(self.root, f"{alias}:{env}", state, str(found.get("why") or ""), str(found.get("who") or ""))
        except Exception:  # noqa: BLE001 - a note on a state must never fail the test the person pressed
            pass

    def machine(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get ready, This computer (1.7.11): the tool folders and the CA bundle VS Code is started with (`core.launchenv`). `step`: state, paths, bundle, drop."""
        step = str(data.get("step", ""))
        if step == "paths":
            launchenv.save_paths(self.root, [str(item) for item in (data.get("paths") or []) if isinstance(item, str)])
        elif step == "bundle":
            made = launchenv.make(self.root, str(data.get("host") or ""), str(data.get("proxy") or ""))
            return dict(launchenv.state(self.root), made=made, vscode_open=bool(self.link.status().get("ready", False)))
        elif step == "drop":
            launchenv.drop_bundle(self.root)
        elif step == "mcp":  # the person says whether MCP may be used here (1.7.17); the tool packs' MCP servers follow
            done = launchenv.set_mcp(self.root, bool(data.get("allowed")))
            return dict(launchenv.state(self.root), mcp_done=done, vscode_open=bool(self.link.status().get("ready", False)))
        elif step == "folder-add":  # "I installed it here" (1.7.37): the folder goes to HARNESS_TOOL_PATH when it holds the program; the next check finds it
            launchenv.add_folder(self.root, str(data.get("program") or ""), str(data.get("path") or ""))
            step = "state"
        elif step == "toolpack-add":  # a folder or zip the person names (1.7.19): what `harness toolpack add <path>` does; an installed name is replaced only after a second, confirming call
            from core import toolpacks

            try:
                found = toolpacks.installed_against(self.root, str(data.get("path") or ""))
                if found["source"] == toolpacks.COMPANY:
                    raise ValueError(say("toolpack.company.managed", name=found["name"]))
                if found["installed"] and not data.get("replace"):
                    return {"confirm": found}
                done = toolpacks.add(self.root, str(data.get("path") or ""), replace=bool(data.get("replace")))
                row = next((item for item in toolpacks.check(self.root, done["installed"])["toolpacks"] if item["name"] == done["installed"]), {})
            except toolpacks.ToolpackError as error:
                raise ValueError(str(error)) from None
            return {"added": done, "missing": [name for name, ok in (row.get("programs") or {}).items() if not ok]}
        elif step == "toolpack-use":  # a factory pack on or off: its name in `use` of the knowledge base's packs.json, and the skills follow at once (1.7.34)
            from core import toolpacks

            try:
                toolpacks.set_use(self.root, str(data.get("name") or ""), bool(data.get("on")))
            except toolpacks.ToolpackError as error:
                raise ValueError(str(error)) from None
            step = "toolpacks"
        elif step in ("toolpack-update", "toolpack-remove"):  # the paired browser is the person's: what `harness toolpack add --replace` / `remove` do at a terminal
            from core import toolpacks

            name = str(data.get("name") or "")
            try:
                if step == "toolpack-remove":  # a folder added here; a factory or company pack answers with where to turn it off
                    toolpacks.remove(self.root, name)
                else:  # nothing is copied now: the pack is read where it lies, so an update is only its skills again
                    done = toolpacks.sync_skills(self.root)
                    if done.get("failed"):  # a company pack has the name of a factory pack (1.7.38)
                        raise toolpacks.ToolpackError(done["error"])
            except toolpacks.ToolpackError as error:
                raise ValueError(str(error)) from None
            step = "toolpacks"
        if step == "toolpacks":  # Get ready, Tool packs (1.7.13): what each has and lacks, with the servers of its kinds and whether each is signed in
            from core import toolpacks

            found = toolpacks.check(self.root)
            found.pop("exit_code", None)
            known, env = conn_core.types(self.root), conn_core.read_env(self.root)
            for row in found["toolpacks"]:
                row["connections"] = [{"alias": alias, "saved": bool(conn_core.identity_of(env, alias, known.get(str(server.get("type"))) or {}, server))}
                                  for alias, server in conn_core.listed(self.root).items() if (known.get(str(server.get("type"))) or {}).get("toolpack") == row["name"]]
            return found
        if step not in ("state", "paths", "drop"):
            raise ValueError(say("serve.refused.request"))
        return dict(launchenv.state(self.root), vscode_open=bool(self.link.status().get("ready", False)))

    def setup(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get ready (`core/setup.py`). `step`: state, probe or act. When the short command appears while VS Code is open, the agent's terminals do not have it yet:
        the Enter screen waits until VS Code was closed and came back."""
        step = str(data.get("step", ""))
        if step == "probe":
            kind = str(data.get("kind") or "repos")
            return setupjob.probe_package(self.root, data.get("path")) if kind == "package" else setupjob.probe_folder(self.root, data.get("path"))
        if step == "act":
            return self.setup_job.start(self.root, data)
        if step == "job":
            found = self.setup_job.view()
            if found["done"]:
                self.language_stamp = []
                self.sync_language()
            return dict(found, stamp=core_setup.stamp(self.root))
        if step == "folders":
            return setupjob.browse(data.get("path"), str(data.get("kind")) == "file")
        if step == "pick":
            return {"path": wallpaper.pick(say("setup.pick.prompt"), file=str(data.get("kind")) == "file").rstrip("/\\") or ""}
        if step == "refuse":
            return core_setup.refused(data.get("repos_root"), data.get("path"), core_setup.single_list(data))
        if step == "repo":
            return core_setup.add_repo(data.get("path"), data.get("repos_root"), core_setup.single_list(data), self.root)
        if step == "short":
            problem = shortcmd.install(self.root)
            self.short_kept = None
            if problem:
                raise CommandError(problem)
            return {"done": True}
        if step == "test":
            return core_setup.try_short(self.root)
        if step == "guide":
            return core_setup.guide(self.root)
        if step == "none":
            return {"none": core_setup.declare(self.root, data.get("key"), data.get("on"))}
        if step == "older":
            return reinstall.run(self.root, str(data.get("path", "")), bool(data.get("apply")), True if data.get("apply") else None)
        if step != "state":
            raise CommandError(say("serve.refused.request"))
        found = core_setup.status(self.root, self.short_now())
        linked = bool(self.link.status().get("ready"))
        if not found["short"]["found"]:
            self.short_missing = True
        elif self.short_missing:
            self.short_missing = False
            if linked:
                self.ready.wait_reopen()
        return dict(found, reopen=self.ready.still_reopen())

    def skill(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """A one-click skill (`skillsend.py`): `step` preview or act. The message is made here, each time, from the skill name and the words."""
        step = str(data.get("step", ""))
        if step == "list":
            return {"skills": skillboard.skills(self.root)}
        if step == "options":  # the model picker of a dialog that sends to an agent (1.6.101): the models, the task's own model, and the default of a short one-off chat
            task = task_ops.resolve(self.root, str(data["task"])) if data.get("task") else ""
            own = chatsend.model_of(tasks.read(self.root, task) or {}) if task else None
            return {"models": self.link.model_list(), "task": model_pair(own), "small": {} if task else model_pair(self.click_model({}))}
        text = skillsend.message(self.root, data)
        why = self.link.create_blocked()
        model = self.click_model(data)
        if step == "preview":
            return {"text": text, "blocked": say(f"create.refused.{why}") if why else "", "model": self.model_words(model)}
        if step != "act":
            raise CommandError(say("serve.refused.request"))
        if why:
            raise CommandError(say(f"create.refused.{why}"))
        name = ""
        if data.get("task"):  # the chat goes on with this task: bound to it at once, not when its agent has answered
            task, found = self.target(data)
            name = str(found.get("name") or task_ops.name_of(task))
        try:
            done = self.link.create(dict(skillsend.plan(str(data.get("lang") or "en"), name), model=model), text)
        except vslink.Refused as error:
            raise CommandError(say(f"create.refused.{error.why}")) from None
        except Exception as error:  # noqa: BLE001 - the name of the error only, never its text
            raise CommandError(say("create.refused.host", error=type(error).__name__)) from None
        skillsend.record(self.root, str(data.get("skill")), "chat", done)
        self.link.open_window()
        return {"sent": True}

    def restart(self) -> Dict[str, Any]:
        """Restart board: the code the page pairs with when the new process answers. What runs in the Terminal window stops, as it does whenever the board stops."""
        self.next_code = secrets.token_urlsafe(12)
        threading.Timer(RESTART_AFTER, self.server.shutdown).start()
        return {"code": self.next_code}

    def click_model(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The model of a chat a click starts. What the person picked in the dialog comes first (`model`, 1.6.101; empty: VS Code's own choice), then the model of its task. A chat that works on
        a task gets no other default: it may have much to read, and a cheap model picked for a short first message would read it all again after a switch (1.6.101). A short one-off chat runs on
        Copilot Fusion unless `board.one_click_fusion` in the policy `task` is false."""
        if "model" in data:
            return chatnew.model_of(data, self.link.model_list())
        chosen = chatsend.model_of(tasks.read(self.root, task_ops.resolve(self.root, str(data["task"]))) or {}) if data.get("task") else None
        if chosen or data.get("task"):
            return chosen
        wanted = (config.policy_or_empty(self.root, "task").get("board") or {}).get("one_click_fusion", True)
        return chatnew.one_click_model(self.link.model_list()) if wanted is not False else None

    def model_words(self, model: Optional[Dict[str, Any]]) -> str:
        """The model of `click_model` as the page shows it. Empty: VS Code chooses."""
        found = next((item for item in self.link.model_list() if model and item["id"] == model["id"]), None)
        if not found:
            return ""
        level = next(iter(((model.get("config") or {}).values())), "")
        return " \u00b7 ".join(part for part in (found["name"], str(((found.get("thinking") or {}).get("labels") or {}).get(level, level))) if part)

    def run(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The Run button (`taskrun.py`). `op`: start, read, stop or latest (the run of a task under way, for a page opened meanwhile). A paired browser only."""
        op = str(data.get("op", ""))
        if op == "read":
            return self.runner.read(str(data.get("id", "")), data.get("since"))
        if op == "stop":
            return self.runner.stop(str(data.get("id", "")))
        if op == "latest":
            found = taskdesk.row_of(self.root, str(data.get("task", "")))
            return {"run": self.runner.latest(found["task"]) if found else None}
        if op != "start":
            raise CommandError(say("serve.refused.request"))
        task, _ = self.target(data)
        return self.runner.start(task, str(data.get("command", "")))

    def preview(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """What a send would say, and whether it can go now (`blocked`: the reason, or empty). Needs the paired browser."""
        task, found = self.target(data)
        made = self.message(task, found, data)
        why = self.link.check(task, "send")
        return {"text": made["text"], "kind": made["kind"], "lang": made["lang"], "reply": made["reply"], "notes": len(made["notes"]), "drafts": len(made["draft_ids"]), "blocked": self.refusal(why) if why else "", "model": chatsend.model_of(found) or {}}

    def send(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task, found = self.target(data)
        made = self.message(task, found, data)
        model = chatsend.model_of(found)
        files = self.files_of(data)
        try:
            done = self.link.dispatch("send", task, made["text"], model, files)
        except vslink.Refused as error:
            raise Fallback(self.refusal(error.why), made["text"]) from None
        except Exception as error:  # noqa: BLE001 - the host said no: the person copies the text
            raise Fallback(ahp_scrub(error), made["text"]) from None
        chatsend.drop_drafts(self.root, task, made["draft_ids"])
        try:
            tasklife.set_waiting(self.root, task, None)  # the person answered: the card goes now, not when the hook of the new turn has run
        except Exception:  # noqa: BLE001 - the message went; that hook takes the mark away too
            pass
        return self.sent(task, found, made["kind"], made["text"], done, {"why": made["why"], "lang": made["lang"], "model": model or {}, "drafts": len(made["draft_ids"]), "files": chatsend.listed(files)})

    def files_of(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return chatsend.attachments(data.get("attachments"))
        except ValueError as error:
            raise CommandError(self.refusal(str(error))) from None

    def steer(self, data: Dict[str, Any], kind: str = "steer") -> Dict[str, Any]:
        """A message while the agent works: `steer` goes into the running turn, `queue` (1.6.99) after it, as the next turn Copilot starts itself."""
        task, found = self.target(data)
        text, problem = chatsend.steer_text(str(data.get("text", "")), str(data.get("lang", "")))
        if problem:
            raise CommandError(self.refusal("text." + problem))
        text = chatsend.with_english(self.root, task, str(data.get("lang", "")), text)
        model = chatsend.model_of(found)
        files = self.files_of(data)
        try:
            done = self.link.dispatch(kind, task, text, model, files)
        except vslink.Refused as error:
            raise Fallback(self.refusal(error.why), text) from None
        except Exception as error:  # noqa: BLE001
            raise Fallback(ahp_scrub(error), text) from None
        return self.sent(task, found, kind, text, done, {"model": model or {}, "files": chatsend.listed(files)})

    def queue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.steer(data, "queue")

    def unqueue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Take one queued message back before Copilot sends it; its words come back for the reply box."""
        task, _found = self.target(data)
        try:
            done = self.link.dispatch("unqueue", task, plan={"id": str(data.get("id", ""))[:100]})
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except Exception as error:  # noqa: BLE001
            raise CommandError(ahp_scrub(error)) from None
        with task_ops.locked(self.root, task) as again:
            task_ops.note(again, "chat-unqueue", chatsend.summary(done["text"]))
        chinese = done["text"].startswith(chatsend.ZH_MARK)
        return {"text": done["text"][len(chatsend.ZH_MARK):].lstrip() if chinese else done["text"], "lang": "zh" if chinese else "en", "files": []}

    def resume(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Try again: the last turn of the chat ended in an error the host can run again (a limit or a broken connection), and it runs again with the same message."""
        task, _found = self.target(data)
        try:
            self.link.dispatch("resume", task)
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except Exception as error:  # noqa: BLE001
            raise CommandError(ahp_scrub(error)) from None
        with task_ops.locked(self.root, task) as again:
            task_ops.note(again, "chat-resume", "-")
        return {"resumed": True}

    def stop(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task, found = self.target(data)
        try:
            done = self.link.dispatch("stop", task)
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except Exception as error:  # noqa: BLE001
            raise CommandError(ahp_scrub(error)) from None
        try:
            with task_ops.locked(self.root, task) as again:
                task_ops.note(again, "stop", (done.get("title") or "-")[:60])
        except Exception:  # noqa: BLE001
            pass
        return {"stopped": True, "chat": done.get("title", "")}

    @staticmethod
    def compact_refusal(why: str) -> str:
        """Compact has its own words: the send ones tell a person to copy and paste, and there is nothing to paste here."""
        known = ("off", "not-ready", "unbound", "unsure", "changed", "not-idle", "timeout")
        return say(f"compact.refused.{why}" if why in known else "compact.refused.other")

    def compact(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The compact button: `/compact` as a message, to an idle chat only, as a send is. The only control mark the board sends; nothing but this call sends it."""
        task, found = self.target(data)
        try:
            done = self.link.dispatch("send", task, chatsend.COMPACT_TEXT)  # no model: the chat keeps the one it has
        except vslink.Refused as error:
            raise CommandError(self.compact_refusal(error.why)) from None
        except Exception as error:  # noqa: BLE001
            raise CommandError(ahp_scrub(error)) from None
        return self.sent(task, found, "compact", chatsend.COMPACT_TEXT, done)

    # --- allow, deny, answer (B75) ----------------------------------------------------------------------------------

    def ask_plan(self, data: Dict[str, Any], key: str) -> Dict[str, Any]:
        """What the page says it showed: the item (`id`), the call or request in it (`key`) and the `digest` of the text. All three, or nothing is done: never "whatever is pending"."""
        plan = {"id": str(data.get("id", "")).strip(), "key": str(data.get(key, "")).strip(), "digest": str(data.get("digest", "")).strip()}
        if not all(plan.values()):
            raise CommandError(say("ask.refused.shown"))
        return plan

    def asked(self, task: str, kind: str, detail: str, entry: Dict[str, Any]) -> None:
        """After the host was told: one line of history and one line of `.task/sent.jsonl`. A decision that went must not come back as an error because a note could not be written."""
        try:
            chatsend.record(self.root, task, dict(entry, at=utc_now(), task=task, kind=kind))
            with task_ops.locked(self.root, task) as again:
                task_ops.note(again, kind, detail)
        except Exception:  # noqa: BLE001
            pass

    def respond(self, kind: str, task: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.link.respond(kind, task, plan)
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except chatask.AnswerError as error:
            raise CommandError(say(f"ask.refused.answer.{error.code}", question=error.title)) from None
        except Exception as error:  # noqa: BLE001 - the host said no: the name of the error only
            raise CommandError(ahp_scrub(error)) from None

    def confirm(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Allow or deny the one tool call the page showed (`decision`: allow or deny). Read again before it is done; refused when the call is gone or changed."""
        task, _found = self.target(data)
        decision = str(data.get("decision", ""))
        if decision not in ("allow", "deny"):
            raise CommandError(say("ask.refused.decision"))
        plan = dict(self.ask_plan(data, "tool_call_id"), approved=decision == "allow")
        done = self.respond("confirm", task, plan)
        view = done["view"]
        command = chatask.one_line(view["command"], chatask.MAX_LINE)
        self.asked(task, "confirm", f"{decision}: {view['tool'] or '-'} {command}".strip(), {"decision": decision, "tool": view["tool"], "tool_call_id": view["tool_call_id"], "command": view["command"], "chat": done["chat"]})
        return {"decided": decision, "chat": done["title"]}

    def answer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Answer the one question the page showed (`answers`: {question id: value}). Read again before it is done; refused when the question is gone or changed."""
        task, _found = self.target(data)
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise CommandError(say("ask.refused.answer.unknown", question=""))
        plan = dict(self.ask_plan(data, "request_id"), answers=answers)
        done = self.respond("answer", task, plan)
        view = done["view"]
        self.asked(task, "question", done["line"] if (view["message"] or "-") in done["line"] else (view["message"] or "-")[:60] + ": " + done["line"], {"request_id": view["request_id"], "question": view["message"], "answer": done["line"], "chat": done["chat"]})
        return {"answered": True, "chat": done["title"]}

    def create_options(self) -> Dict[str, Any]:
        """What the new-task dialog offers: the models the host lists now (policy filtered), the kinds, the tasks a fork may start from, and whether VS Code is ready."""
        status = self.link.status()
        sources = []
        for folder in tasks.folders(self.root):
            found = tasks.read(self.root, folder) or {}
            sources.append({"name": task_ops.name_of(folder), "kind": str(found.get("kind") or ""), "status": str(found.get("status") or "")})
        return {"ready": bool(status["ready"]), "why": status["why"], "models": self.link.model_list(), "kinds": list(tasks.KINDS), "sources": sources,
                "limit": chatnew.MAX_TEXT, "link_types": toolpacks.link_types(self.root),
                "domains": intake.kb_domains(self.root)}  # the knowledge base domains a task may be about (none is a choice); empty: no knowledge base has one

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """`step` options: what the dialog offers. `preview`: the first message, whole, and whether it can go now. `act`: make the chat in VS Code and send it. Every field is checked here again."""
        step = str(data.get("step", "act"))
        if step == "options":
            return dict(self.create_options(), sample=core_setup.sample(self.root))
        why = self.link.create_blocked()
        if step == "preview":  # the message grows while the person types: it is made without VS Code, by the same code as the real one; `blocked` is why it cannot go now, `problem` what is not right in the fields
            made = chatnew.preview(self.root, data, [] if why else self.link.model_list(), self.link.waiting_names())
            return {**made, "blocked": say(f"create.refused.{why}") if why else ""}
        if why:
            raise CommandError(say(f"create.refused.{why}"))
        plan = chatnew.validate(self.root, data, self.link.model_list(), self.link.waiting_names())
        text = chatnew.first_message(plan)
        files = self.files_of(data)
        try:
            done = self.link.create(plan, text, files)
        except vslink.Refused as error:
            raise CommandError(say(f"create.refused.{error.why}")) from None
        except Exception as error:  # noqa: BLE001 - the host said no: nothing more is known; the name of the error only, never its text
            raise CommandError(say("create.refused.host", error=type(error).__name__)) from None
        initiator = str(done.get("initiator") or "")
        warn = say("create.warn.initiator", initiator=initiator) if initiator and initiator != "vscode" else ""
        return {"created": True, "name": plan["name"], "initiator": initiator, "warn": warn, "unchecked": not initiator, "text": text, "model": plan["model"] or {}}

    def draft(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The Drafts box of the task page (B77): `op` list, add, edit, delete or use (switch a draft in or out of the next send). The answer holds the drafts: they are the person's notes, so only the paired browser reads them."""
        task, _found = self.target(data)
        op = str(data.get("op", "add"))
        out: Dict[str, Any] = {"saved": True}
        try:
            if op == "add":
                out["at"] = chatsend.add_draft(self.root, task, str(data.get("text", "")))["at"]
            elif op == "edit":
                chatsend.change_draft(self.root, task, str(data.get("id", "")), text=str(data.get("text", "")))
            elif op == "delete":
                chatsend.change_draft(self.root, task, str(data.get("id", "")), delete=True)
            elif op == "use":
                chatsend.change_draft(self.root, task, str(data.get("id", "")), use=bool(data.get("use")))
            elif op != "list":
                raise ValueError("gone")
        except ValueError as error:
            raise CommandError(self.refusal("draft." + str(error))) from None
        items = chatsend.drafts(self.root, task)
        out.update({"items": items, "count": len(items), "max": chatsend.MAX_DRAFTS})
        return out

    def setting(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The model and thinking level of the messages the board sends (`chat.model`). Only a model the host lists, only a level that model has. `id` empty: the chat keeps its own."""
        task, _found = self.target(data)
        wanted, level, size = str(data.get("id", "")).strip(), str(data.get("thinking", "")).strip(), data.get("context") or 0
        model: Optional[Dict[str, Any]] = None
        if wanted:
            listed = {item["id"]: item for item in self.link.model_list()}
            if wanted not in listed:
                raise CommandError(self.refusal("model"))
            levels = (listed[wanted]["thinking"] or {}).get("levels") or []
            if level and level not in levels:
                raise CommandError(self.refusal("thinking"))
            size = ahp.context_size(listed[wanted], size)
            if size is None:
                raise CommandError(self.refusal("context"))
            model = ahp.model_choice(listed[wanted], level, size)
        with task_ops.locked(self.root, task) as again:
            kept = dict(again.get("chat") or {})
            if model:
                kept["model"] = model
            else:
                kept.pop("model", None)
            if kept:
                again["chat"] = kept
            else:
                again.pop("chat", None)
            task_ops.note(again, "chat-model", " ".join(str(part) for part in (wanted, level, size) if part) or "-")
        return {"model": model or {}}

    def undo(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Take the last message of the person out of the chat, with what answered it, and give back its words for the reply box. A turn that runs is stopped first (1.6.99)."""
        task, _found = self.target(data)
        try:
            done = self.link.dispatch("undo", task)
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except Exception as error:  # noqa: BLE001 - the host said no
            raise CommandError(ahp_scrub(error)) from None
        with task_ops.locked(self.root, task) as again:
            task_ops.note(again, "chat-undo", chatsend.summary(done["text"]))
        chinese = done["text"].startswith(chatsend.ZH_MARK)
        return {"text": done["text"][len(chatsend.ZH_MARK):].lstrip() if chinese else done["text"], "lang": "zh" if chinese else "en", "files": done["files"]}

    def rewind(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Go back to before a message of the person (1.6.109): `step` preview says what changes; act puts the task's files back as they were at its restore point and cuts the chat
        before it, and gives back its words for the reply box. Only the chat linked to the task, idle, in this round, with no write-back since."""
        task, _found = self.target(data)
        found = task_ops.read(self.root, task)
        try:
            seq = int(data.get("seq"))
        except (TypeError, ValueError):
            raise CommandError(say("serve.refused.request")) from None
        point = next((item for item in rewind.index(self.root, task) if item["seq"] == seq and item.get("kind") == "prompt"), None)
        session = str(found.get("session_id") or "")
        why = rewind.why_not(found, point, session)
        if why:
            raise CommandError(say(f"desk.rewind.why.{why}"))
        at = rewind.seconds(point["at"])
        step = str(data.get("step", "preview"))
        try:
            if step == "preview":
                changes = rewind.preview(self.root, task, seq)
                chat = self.link.dispatch("rewind", task, plan={"at": at, "dry": True})
                return {"seq": seq, "at": point["at"], "turns": chat["turns"], "counts": {key: len(changes[key]) for key in ("back", "removed", "lost")},
                        **{key: changes[key][:rewind.LISTED] for key in ("back", "removed", "lost")}, "plan": changes["plan"], "req": changes["req"]}
            if step != "act":
                raise CommandError(say("serve.refused.request"))
            done = self.link.dispatch("rewind", task, plan={"at": at, "restore": lambda: rewind.restore(self.root, task, seq, session)})
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        except CommandError:
            raise
        except Exception as error:  # noqa: BLE001 - the host or the disk said no
            raise CommandError(ahp_scrub(error)) from None
        changed = done.get("changed") or {}
        with task_ops.locked(self.root, task) as again:
            task_ops.note(again, "rewind", f"{chatsend.summary(done['text'])} · {done['turns']} turn(s) · {changed.get('back', 0)} back · {changed.get('removed', 0)} aside")  # the message's words, as Withdraw notes them; not a UTC time beside the record's local ones
        chinese = done["text"].startswith(chatsend.ZH_MARK)
        return {"text": done["text"][len(chatsend.ZH_MARK):].lstrip() if chinese else done["text"], "lang": "zh" if chinese else "en", "files": done["files"],
                "back": changed.get("back", 0), "removed": changed.get("removed", 0), "aside": changed.get("aside", ""), "lost": len(changed.get("lost") or [])}

    def chatconfig(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """The mode and the tool permission of the chat of the task: told to the host at once, they hold from the next turn. Only a value the host offers;
        the mode only goes back to Interactive, since a task has its own plan and autorun (Plan or Autopilot can only have been set in VS Code)."""
        task, _found = self.target(data)
        offered = self.link.chat_options(task)
        values = {key: data[key] for key in ("mode", "autoApprove") if key in data}
        if not values or data.get("mode", "interactive") != "interactive" or any(value not in [item["id"] for item in (offered.get(key) or {}).get("choices") or []] for key, value in values.items()):
            raise CommandError(self.refusal("setting"))
        try:
            self.link.dispatch("config", task, plan=values)
        except vslink.Refused as error:
            raise CommandError(self.refusal(error.why)) from None
        with task_ops.locked(self.root, task) as again:
            task_ops.note(again, "chat-config", " ".join(f"{key}={value}" for key, value in values.items()))
        return values


def noted(root: Path, task: str, action: str) -> None:
    """The audit trail says the action came from the board page, next to the line the action itself wrote."""
    try:
        with task_ops.locked(root, task_ops.resolve(root, task)) as data:
            task_ops.note(data, "board", action)
    except Exception:  # noqa: BLE001 - the action is done; a missing line must not undo it in the person's eyes
        pass


def handler_for(board: Board) -> type:
    allowed_hosts = {f"127.0.0.1:{board.port}", f"localhost:{board.port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}
    reports = (board.root / common.REPORTS_DIR).resolve()

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "harness-board"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the name is the base class's
            return  # the terminal shows only what the person needs

        def send(self, status: int, body: bytes, kind: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            if "Cache-Control" not in (extra or {}):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if kind.startswith("text/html"):
                self.send_header("Content-Security-Policy", CSP)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def answer(self, status: int, data: Dict[str, Any], extra: Optional[Dict[str, str]] = None) -> None:
            if status == 200:
                data = {**data, "language": messages.language()}  # an open page reloads its texts when this differs from the one it shows
            self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

        def host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def embedded(self) -> bool:
            """A browser inside an editor (VS Code's own, which the agent can drive with its browser tools, 1.7.14): it is never paired, so the agent
            cannot press a person's button there. Told by the user agent an Electron app sends."""
            return bool(EMBEDDED.search(self.headers.get("User-Agent", "")))

        def token(self) -> str:
            if self.embedded():
                return ""
            for part in self.headers.get("Cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == board.cookie:
                    return value
            return ""

        def do_GET(self) -> None:  # noqa: N802 - the name is the base class's
            board.sync_language()
            if not self.host_ok():
                return self.send(403, b"", "text/plain")
            path = unquote(urlparse(self.path).path)
            if path.startswith("/snapshot/"):
                try:
                    filename, page = board.snapshot(path[len("/snapshot/"):].strip("/"))
                    disposition = f"attachment; filename=\"task.html\"; filename*=UTF-8''{quote(filename)}"  # the plain name is for a browser that reads only ASCII
                    return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8", {"Content-Disposition": disposition})
                except CommandError as error:
                    return self.send(404, str(error).encode("utf-8"), "text/plain; charset=utf-8")
                except Exception as error:  # noqa: BLE001 - show it instead of a dead download
                    return self.send(500, f"{type(error).__name__}: {error}".encode("utf-8"), "text/plain; charset=utf-8")
            if path.startswith("/report-save/"):
                try:
                    filename, page = board.saved_report(path[len("/report-save/"):].strip("/"))
                    disposition = f"attachment; filename=\"report.html\"; filename*=UTF-8''{quote(filename)}"
                    return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8", {"Content-Disposition": disposition})
                except CommandError as error:
                    return self.send(404, str(error).encode("utf-8"), "text/plain; charset=utf-8")
                except Exception as error:  # noqa: BLE001 - show it instead of a dead download
                    return self.send(500, f"{type(error).__name__}: {error}".encode("utf-8"), "text/plain; charset=utf-8")
            shown = re.fullmatch(r"/tasks/([^/]+)/report\.html", path)
            if shown:  # the report is drawn when asked: the verdicts are the latest and the buttons are there
                try:
                    return self.send(200, board.report_page(shown.group(1)).encode("utf-8"), "text/html; charset=utf-8")
                except CommandError as error:
                    return self.send(404, str(error).encode("utf-8"), "text/plain; charset=utf-8")
                except Exception as error:  # noqa: BLE001 - show it instead of a dead page
                    return self.send(500, f"{type(error).__name__}: {error}".encode("utf-8"), "text/plain; charset=utf-8")
            if path == "/setup":
                return self.send(200, taskhtml.setup_page(board.serve_info({}, 0)).encode("utf-8"), "text/html; charset=utf-8")
            if path in ("/", "/board.html") or path.startswith("/task/"):
                try:
                    page = board.page() if not path.startswith("/task/") else board.desk_page(path[len("/task/"):].strip("/"))
                    return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
                except CommandError as error:  # a task the board does not list
                    return self.send(404, str(error).encode("utf-8"), "text/plain; charset=utf-8")
                except Exception as error:  # noqa: BLE001 - show it instead of a dead page
                    return self.send(500, f"{type(error).__name__}: {error}".encode("utf-8"), "text/plain; charset=utf-8")
            if path.startswith("/wall/"):  # one picture of the wallpaper folder: read only, by its bare name. Another site's page may not use it (Origin, Sec-Fetch-Site)
                origin = self.headers.get("Origin", "")
                if (origin and origin not in allowed_origins) or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                    return self.send(403, b"", "text/plain")
                found = wallpaper.file_for(board.root, path[len("/wall/"):])
                if found is None:
                    return self.send(404, b"", "text/plain")
                target, kind, info = found
                tag = f'"{info.st_mtime_ns:x}-{info.st_size:x}"'
                headers = {"ETag": tag, "Cache-Control": "private, max-age=86400"}
                if self.headers.get("If-None-Match", "") == tag:
                    return self.send(304, b"", kind, headers)
                try:
                    return self.send(200, target.read_bytes(), kind, headers)
                except OSError:
                    return self.send(404, b"", "text/plain")
            if path.startswith("/file/"):  # a picture of a task page (evidence a person gave): read only, by the task's name and a path inside its folder
                name, _, relative = path[len("/file/"):].partition("/")
                found = taskdesk.image_file(board.root, name, relative)
                if found is None:
                    return self.send(404, b"", "text/plain")
                return self.send(200, found.read_bytes(), mdtree.IMAGE_TYPES[found.suffix.lower()])
            if path.startswith("/download/"):  # an original of the Files tab, to save: the same files the tab lists
                name, _, relative = path[len("/download/"):].partition("/")
                found = taskdesk.download_file(board.root, name, relative)
                if found is None:
                    return self.send(404, b"", "text/plain")
                disposition = f"attachment; filename=\"download\"; filename*=UTF-8''{quote(found.name)}"
                return self.send(200, found.read_bytes(), "application/octet-stream", {"Content-Disposition": disposition})
            target = (reports / path.lstrip("/")).resolve()
            if not str(target).startswith(str(reports) + os.sep) or target.suffix != ".html" or not target.is_file():
                return self.send(404, b"", "text/plain")
            return self.send(200, target.read_bytes(), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            board.sync_language()
            origin = self.headers.get("Origin", "")
            if not self.host_ok() or (origin and origin not in allowed_origins) or self.headers.get(HEADER) != "1":
                return self.answer(403, {"error": say("serve.refused.request")})
            limit = MAX_INBOX_BODY if urlparse(self.path).path in ("/api/inbox", "/api/intake") else MAX_FILES_BODY if urlparse(self.path).path in ("/api/send", "/api/steer", "/api/queue", "/api/create") else MAX_EDIT_BODY if urlparse(self.path).path == "/api/fileop" else MAX_SEND_BODY if urlparse(self.path).path == "/api/answer" else MAX_BODY
            try:
                size = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(size, limit)).decode("utf-8") or "{}") if 0 <= size <= limit else None
            except (ValueError, UnicodeDecodeError):
                data = None
            if not isinstance(data, dict):
                return self.answer(400, {"error": say("serve.refused.body")})
            path = urlparse(self.path).path
            if path == "/api/pair":
                if self.embedded():  # checked first: the code is not used up
                    return self.answer(403, {"error": say("serve.pair.embedded")})
                token = board.pair(str(data.get("code", "")))
                if token is None:
                    return self.answer(403, {"error": say("serve.pair.wrong")})
                cookie = f"{board.cookie}={token}; HttpOnly; SameSite=Strict; Path=/"
                return self.answer(200, {"paired": True}, {"Set-Cookie": cookie})
            if path == "/api/reopen":  # a second `harness task board`: this server opens the browser with a new code. The answer never holds the code, so no pairing is needed
                return self.answer(200, {"opened": board.open_page()})
            if path == "/api/status":
                return self.answer(200, {"paired": board.paired(self.token()), "started": board.version, "now": disk_version(board.root), "vscode": board.link.status(), "root": str(board.root)})
            if path == "/api/ready":  # the Enter screen: what is in place, one line each. A read, as /api/board is: the cache of the link and of the one doctor run; it waits for nothing
                try:
                    return self.answer(200, board.ready.answer(board.paired(self.token())))
                except Exception as error:  # noqa: BLE001 - the page shows that the check itself failed
                    return self.answer(500, {"error": f"{type(error).__name__}: {error}"[:300]})
            if path == "/api/live":  # the Live tab of an open task: the latest items of its chat, from the memory of the link (no file, no call to the host); `rev` makes an unchanged poll tiny
                return self.answer(200, {"live": board.link.live(str(data.get("task", ""))[:200], str(data.get("rev", ""))[:300])})
            if path == "/api/open":  # bring the VS Code window of this folder forward: the thread of the link runs `code <folder>`; this answers at once
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                if not data.get("anyway") and launchenv.extra(board.root) and launchenv.vscode_running() and launchenv.seen(board.root).get("ok") is not True:  # it is running and no chat found it started with the settings: starting it again gives it nothing (1.7.21); the person may still open it (`anyway`, 1.7.29)
                    return self.answer(409, {"error": say("serve.open.running_env"), "running": True})
                try:
                    board.open_vscode()
                except ValueError as error:
                    return self.answer(409, {"error": str(error)})
                return self.answer(200, {"result": {"queued": True}})
            if path == "/api/restart":  # the VS Code button of the Enter screen (1.7.38): quit the normal way, wait, open again. The paired browser only; never a kill
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                if str(data.get("step", "")) == "state":
                    return self.answer(200, {"result": board.restarter.view()})
                if os.environ.get("TERM_PROGRAM") == "vscode" or os.environ.get("VSCODE_IPC_HOOK_CLI"):  # this board runs in a terminal of VS Code: quitting VS Code would stop it
                    return self.answer(409, {"error": say("restart.inside"), "inside": True})
                names = [] if data.get("anyway") else board.working_tasks()
                chats = [] if data.get("anyway") else board.other_chats(names)
                if names or chats:
                    return self.answer(409, {"error": say("restart.busy", names=", ".join(names + chats)), "busy": names, "chats": chats})
                return self.answer(200, {"result": {"started": board.restarter.start(bool(data.get("open", True)))}})
            if path == "/api/reach":  # the Check button of the outside systems line: the board checks the connections now (the paired browser only)
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                return self.answer(200, {"result": {"started": board.checker.start()}})
            if path == "/api/launch":  # Windows: start the company's launch script (it asks for the identity itself, then starts VS Code); the paired browser only (1.7.9)
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                if not reach.run_launch(board.root):
                    return self.answer(409, {"error": say("serve.launch.none")})
                return self.answer(200, {"result": {"started": True}})
            if path == "/api/create":  # a chat in VS Code and a task the agent opens: the paired browser, nothing else
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.create(data)
                    if str(data.get("step", "act")) == "act":
                        print(say("serve.did", action="create", task=str(result.get("name", ""))), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown in the dialog
                    return self.answer(409, {"error": str(error)})
            if path in ("/api/send", "/api/steer", "/api/queue", "/api/unqueue", "/api/stop", "/api/resume", "/api/compact", "/api/draft", "/api/setting", "/api/chatconfig", "/api/undo", "/api/rewind", "/api/verdict", "/api/export", "/api/confirm", "/api/answer"):  # talk to the chat, its settings, the Gate verdicts: the paired browser, nothing else
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    if path == "/api/send":
                        result = board.send(data) if str(data.get("step", "act")) == "act" else board.preview(data)
                    else:
                        result = getattr(board, path[len("/api/"):])(data)
                    if path not in ("/api/send", "/api/rewind") or str(data.get("step", "act")) == "act":
                        print(say("serve.did", action=path[len("/api/"):], task=task_ops.name_of(task_ops.resolve(board.root, str(data.get("task", ""))))), flush=True)
                    return self.answer(200, {"result": result})
                except Fallback as error:  # not sent: the reason, and the text to copy
                    return self.answer(409, {"error": str(error), "fallback": error.text})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/run":  # the Run button of a code block: the person's own run, the gate does not see it. The paired browser only: an agent can reach this address, but it has no cookie
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.run(data)
                    if str(data.get("op", "")) in ("start", "stop"):
                        print(say("serve.did", action="run " + str(data.get("op")), task=str(data.get("task", "-"))), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/rounds":  # the earlier rounds of the chat: what the person typed and what the agent wrote, so the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    row = taskdesk.row_of(board.root, task_ops.name_of(str(data.get("task", ""))))  # Live knows a task by its folder
                    if row is None:
                        raise CommandError(say("desk.unknown", name=str(data.get("task", ""))))
                    if str(data.get("op", "")) == "list":
                        listed = chatrounds.listing(board.root, row["task"])
                        state_now = task_ops.read(board.root, row["task"])  # each round: may the task go back to before it (1.6.109)
                        found = rewind.marks(board.root, row["task"], state_now, {str(item["n"]): rewind.seconds(item["at"]) for item in listed if not item.get("compact")}, str(state_now.get("session_id") or ""))
                        found.update({str(item["n"]): {"seq": None, "why": "compact"} for item in listed if item.get("compact")})  # no restore point is taken for /compact: no hook runs (1.6.113)
                        return self.answer(200, {"result": {"rounds": [dict(item, rewind=found.get(str(item["n"]))) for item in listed]}})
                    found = chatrounds.one(board.root, row["task"], data.get("n"))
                    return self.answer(200, {"result": found}) if found else self.answer(404, {"error": say("serve.refused.request")})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/connections":  # Get ready, Servers (1.7.10): the paired browser only; it writes the person's identities to .harness/.env
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.servers(data)
                    if str(data.get("step", "")) in ("save", "forget", "forget-tool", "open"):
                        print(say("serve.did", action="servers " + str(data.get("step")), task=str(data.get("alias") or "-")), flush=True)  # never a value
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/machine":  # Get ready, This computer (1.7.11): the paired browser only; it writes .harness/.env and .harness/certs/
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.machine(data)
                    if str(data.get("step", "")) not in ("state", "toolpacks"):  # a read leaves no line; an update or a removal does
                        print(say("serve.did", action="machine " + str(data.get("step")), task="-"), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/setup":  # Get ready: the paired browser only; it writes the person's own override files
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.setup(data)
                    if str(data.get("step", "")) == "act":
                        print(say("serve.did", action="setup", task="-"), flush=True)
                    return self.answer(200, {"result": result})
                except ValueError as error:  # a field not right: told on the page, nothing written
                    return self.answer(409, {"error": str(error)})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/skill":  # one click starts a chat with a skill: the paired browser only, and the page has shown the whole message
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.skill(data)
                    if str(data.get("step", "")) == "act":
                        print(say("serve.did", action="skill " + str(data.get("skill")), task="-"), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown in the dialog
                    return self.answer(409, {"error": str(error)})
            if path == "/api/kb":  # the knowledge base window: reads only, but what a team knows is not for any page on this computer, so the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    op = str(data.get("op", ""))
                    if op == "forget":  # every kept view is old: a rebuilt map, or Refresh (1.7.38)
                        board.kb_view.forget()
                        return self.answer(200, {"result": {"ok": True}})
                    return self.answer(200, {"result": board.kb_view.near(data.get("query")) if op == "near" else board.kb_view.get(op, bool(data.get("fresh")))})
                except (KeyError, ValueError) as error:
                    return self.answer(409, {"error": str(error)})
            if path == "/api/term":  # the Terminal window: a person's own `harness` commands, the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    return self.answer(200, {"result": board.terminal.act(data)})
                except CommandError as error:
                    return self.answer(409, {"error": str(error)})
            if path == "/api/restart":  # Restart board: the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                return self.answer(200, {"result": board.restart()})
            if path == "/api/company":  # the company content against its copies (every 2 minutes), and the Sync button: the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    if data.get("op") == "packcheck":  # before the folder is asked for (1.7.38)
                        return self.answer(200, {"result": company.pack_check(board.root)})
                    if data.get("op") == "commit":  # what is changed in the knowledge base, committed by the person's click
                        return self.answer(200, {"result": company.commit_changes(board.root)})
                    if data.get("op") == "pack":
                        return self.answer(200, {"result": company.pack(board.root, str(data.get("out", "")))})
                    if data.get("op") == "prefix":  # the word of the company content goes in the person's file, then the sync it was stopping
                        folder = targets.company_folder(board.root)
                        board.keep_override("skill_prefix", company.wanted_prefix(folder) if folder else "")
                    if data.get("op") in ("sync", "prefix"):
                        done = company.sync(board.root, remove=True)
                        if done.get("failed"):  # a company pack has the name of a factory pack: nothing was changed (1.7.38)
                            return self.answer(409, {"error": done["error"], "clashes": done.get("clashes") or []})
                        board.ready.drop_doctor()  # the notes of doctor were about the copies as they were
                    return self.answer(200, {"result": company.diff(board.root)})
                except company.DirtyError as error:
                    return self.answer(409, {"error": str(error), "dirty": error.path, "files": error.lines[:12], "more": max(0, len(error.lines) - 12)})
                except company.BadSkills as error:
                    return self.answer(409, {"error": str(error), "skills": error.skills})
                except (company.CompanyError, OSError) as error:
                    return self.answer(409, {"error": str(error)})
            if path == "/api/language":  # the language of the harness (settings panel): the paired browser only; it writes the person's own `user.override.json`
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.set_language(data)
                    print(say("serve.did", action="language " + result["language"], task="-"), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown in the settings panel
                    return self.answer(409, {"error": str(error)})
            if path == "/api/wall":  # the pictures of the wallpaper folder: a read, as /api/board is
                try:
                    return self.answer(200, {"wall": wallpaper.listing(board.root)})
                except Exception as error:  # noqa: BLE001 - the page then has no wallpaper and says why
                    return self.answer(500, {"error": f"{type(error).__name__}: {error}"[:300]})
            if path == "/api/wallfolder":  # the folder the wallpaper is read from: the paired browser only; it writes the person's own `user.override.json`
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    result = board.set_wall_folder(data)
                    print(say("serve.did", action="wallpaper folder", task="-"), flush=True)
                    return self.answer(200, {"wall": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown in the settings panel
                    return self.answer(409, {"error": str(error)})
            if path == "/api/wallpick":  # the same folder, chosen in the system's window: the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    return self.answer(200, board.pick_wall_folder())
                except Exception as error:  # noqa: BLE001 - a refusal is shown in the settings panel
                    return self.answer(409, {"error": str(error)})
            if path == "/api/board":
                try:
                    return self.answer(200, board.rows())
                except Exception as error:  # noqa: BLE001 - the page keeps what it shows
                    return self.answer(500, {"error": str(error)})
            if path == "/api/close":
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    if data.get("step") == "steps":  # the steps of TODO.md the close dialog lists
                        return self.answer(200, {"result": {"left": [text[:200] for text in task_ops.todo_left(board.root, task_ops.resolve(board.root, str(data.get("task", ""))))[:30]]}})
                    return self.answer(200, {"result": board.close(str(data.get("task", "")), str(data.get("reason", "")))})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                    return self.answer(409, {"error": str(error)})
            if path == "/api/archive":
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    return self.answer(200, {"result": board.archive(data)})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                    return self.answer(409, {"error": str(error)})
            if path == "/api/desk":
                try:
                    return self.answer(200, {"desk": board.desk(str(data.get("task", "")), data.get("trace") is True)})
                except CommandError as error:  # no such task any more: archived or removed while the page was open
                    return self.answer(404, {"error": str(error), "gone": True})
                except Exception as error:  # noqa: BLE001 - the page keeps what it shows
                    return self.answer(404, {"error": str(error)})
            if path == "/api/inbox":  # the person gives the task the results of a run: written to INBOX/, so the browser must be paired
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    row = taskdesk.row_of(board.root, str(data.get("task", "")))
                    if row is None:
                        raise CommandError(say("desk.unknown", name=str(data.get("task", ""))))
                    images = data.get("images")
                    result = taskinbox.save(board.root, row["task"], str(data.get("env", "")), str(data.get("text", "")), str(data.get("ran", "")), images if isinstance(images, list) else [])
                    print(say("serve.did", action="inbox", task=row["name"]), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/intake":  # the person puts the documents of a requirement in REQ/ on the page, trims them and undoes: it writes files, so the browser must be paired
                action = str(data.get("action", ""))
                if action != "read" and not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    row = taskdesk.row_of(board.root, str(data.get("task", "")))
                    if row is None:
                        raise CommandError(say("desk.unknown", name=str(data.get("task", ""))))
                    result = board.intake(action, row["task"], data)
                    if action != "read":
                        print(say("serve.did", action="intake " + action, task=row["name"]), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/fileop":  # the Files tab changes a file of the task (1.6.100): edit, add, rename, delete; the paired browser only
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    row = taskdesk.row_of(board.root, str(data.get("task", "")))
                    if row is None:
                        raise CommandError(say("desk.unknown", name=str(data.get("task", ""))))
                    result = taskfileedit.act(board.root, row["task"], data)
                    if str(data.get("op", "")) != "raw":
                        print(say("serve.did", action="file " + str(data.get("op", "")), task=row["name"]), flush=True)
                    return self.answer(200, {"result": result})
                except Exception as error:  # noqa: BLE001 - a refusal is shown on the page
                    return self.answer(409, {"error": str(error)})
            if path == "/api/file":  # one file of the Files tab, when the person opens it
                found = None
                try:
                    row = taskdesk.row_of(board.root, str(data.get("task", "")))
                    found = taskfiles.view(board.root, row["task"], str(data.get("path", ""))) if row else None
                except Exception:  # noqa: BLE001 - the page keeps what it shows
                    found = None
                return self.answer(200, {"file": found}) if found else self.answer(404, {"error": say("serve.refused.request")})
            if path != "/api/act":
                return self.answer(404, {"error": say("serve.refused.request")})
            action, task, step = str(data.get("action", "")), str(data.get("task", "")), str(data.get("step", "act"))
            if action not in FREE and not board.paired(self.token()):
                return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
            try:
                result = board.act(action, task, step, str(data.get("code", "")), bool(data.get("with_req")), data.get("n"), str(data.get("env", "")), str(data.get("runner", "")), str(data.get("reason", "")), str(data.get("note", "")))
            except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                return self.answer(409, {"error": str(error)})
            print(say("serve.did", action=action, task=task_ops.name_of(task) if task else "-"), flush=True)
            return self.answer(200, {"result": result})

    return Handler


def open_again(port: int) -> bool:
    """A second start: the running board opens the browser with a new code. The code stays in that process: this call only hears that it was done."""
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}/api/reopen", data=b"{}", headers={HEADER: "1", "Content-Type": "application/json"}), timeout=3) as answer:
            return answer.status == 200 and json.load(answer).get("opened") is True
    except (OSError, ValueError):
        return False


def running_board(root: Path) -> int:
    """The port of the board of this same copy that runs and answers, or 0 (1.7.38: one board for a copy, whatever its port). The file `board-serve.json` names the port; the answer names the folder it serves,
    so another copy that took the port after a crash is not taken for this one. A board of an older release says no folder: the file is trusted then."""
    port = board_serve_port(root)
    if not port:
        return 0
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}/api/status", data=b"{}", headers={HEADER: "1", "Content-Type": "application/json"}), timeout=3) as answer:
            found = json.load(answer) if answer.status == 200 else None
    except (OSError, ValueError):
        return 0
    if not isinstance(found, dict):
        return 0
    theirs = str(found.get("root") or "")
    try:
        return port if not theirs or Path(theirs).resolve() == root.resolve() else 0
    except OSError:
        return 0


def already_running(root: Path, port: int, out: Any, opener: Callable[[str], Any]) -> Dict[str, Any]:
    """A second start of the board of a copy that has one (any port): say where it is, open it, leave it running."""
    address = f"http://127.0.0.1:{port}/"
    print(say("serve.already", port=port, url=address), file=out, flush=True)
    if not open_again(port):
        opener(address)
    return {"served": address, "stopped": False, "already": True, "port": port}


def serve(root: Path, everything: bool = True, port: Optional[int] = None, out: Any = None, interactive: Optional[bool] = None, opener: Callable[[str], Any] = webbrowser.open, ready: Optional[Callable[[Any], None]] = None,
          link: Optional[vslink.VsLink] = None) -> Dict[str, Any]:
    """Run until Ctrl+C. `opener`, `ready` and `link` exist for the tests: `ready` gets the server once it listens; `link`, a link made by hand (a fake host, or none)."""
    task_ops.person("task board --serve", interactive, typed=False)
    out = out or sys.stdout
    running = running_board(root)
    if running:  # one board for a copy: a second start, on any port, tells the port of the one that runs and opens it
        return already_running(root, running, out, opener)
    found = settings(root)
    link = link if link is not None else vslink.VsLink(root, enabled=vslink.enabled_by_policy(root))
    board = Board(root, everything, port or found["port"], found["actions"], link, found["refresh"])
    board.opener = opener
    try:
        server = board.server = http.server.ThreadingHTTPServer(("127.0.0.1", board.port), handler_for(board))
    except OSError as error:
        running = running_board(root)  # two starts at one moment: the first was not in the file yet when this one looked
        if running:
            return already_running(root, running, out, opener)
        raise CommandError(say("serve.port.busy", port=board.port, error=error))
    taskarchive.prune_transcripts(root, taskarchive.remembered(root))
    try:
        toolpacks.sync_skills(root)  # the skills of the packs the knowledge base turns on are in place when the board opens (1.7.30)
    except Exception:  # noqa: BLE001 - a broken pack must not keep the board from starting; doctor says why
        pass
    link.start()  # the thread only; the board does not wait for VS Code
    board.space.start()
    path = board_serve_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": board.port, "pid": os.getpid(), "started": utc_now()}), encoding="utf-8")
    address = f"http://127.0.0.1:{board.port}/"
    opened = False
    try:
        opened = board.restarted or bool(opener(f"{address}#pair={board.code}"))  # after a restart the page is there, and asks for itself
    except Exception:  # noqa: BLE001 - the person can pair by hand
        opened = False
    def button(action: str) -> str:  # the first line names the buttons as the board shows them (1.7.22), not as the command words
        key = "board.action." + action.replace(" ", "-")
        word = say(key)
        return action if word == key else word

    print(say("serve.started", address=address, actions=", ".join(button(action) for action in board.actions)), file=out, flush=True)
    print(say("serve.opened" if opened else "serve.not_opened"), file=out, flush=True)
    if ready is not None:
        ready(server)
    else:
        board.ready.vs_running.get()  # is any VS Code running: the button of the Enter screen says Open or Restart from the first answer
        board.ready.start_doctor()  # the Enter screen waits for it: it runs while the browser opens and pairs (1.6.104), not from the page's first question
        threading.Thread(target=wait_for_enter, args=(board, address, out), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        board.runner.stop_all()
        board.terminal.stop_all()
        link.stop()
        server.server_close()
        try:
            path.unlink()
        except OSError:
            pass
    if board.next_code:
        relaunch(board.next_code)
    return {"served": address, "stopped": True}


def wait_for_enter(board: Board, address: str, out: Any, early: float = EARLY_ENTER) -> None:
    """Enter in the server's terminal: a new pairing code for a browser that was not paired. The old one stops working.
    An Enter that arrives at once is not the person's: a launcher on Windows can leave a line in the input, and it would
    take the code away from the browser that was just opened with it. It is ignored."""
    begun = time.monotonic()
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:  # noqa: BLE001
            return
        if not line:
            return
        if time.monotonic() - begun < early:
            continue
        print(say("serve.code", address=address, code=board.new_code()), file=out, flush=True)