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
- Files, settings and taking back (1.6.22): `/api/send` and `/api/steer` take `attachments`; `/api/chatconfig` sets the mode and the tool permission of a chat; `/api/undo` takes the last message out of an idle
  chat. All are paired POSTs only.
- VS Code (1.6): one background thread (`vslink`) keeps a connection to the chats of VS Code and a cache; a request only reads the cache. Without VS Code
  `vscode.ready` is false: a request gets no error and no wait, and the Enter screen (`ready.py`) does not let a person in. `/api/open` (paired browser) asks the thread to bring the window of this folder forward.
"""

from __future__ import annotations

import http.server
import io
import json
import os
import secrets
import sys
import threading
import re
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from core import config, messages, registry, state, tasks, user
from core.paths import board_serve_file, board_serve_port, utc_now

from core import setup as core_setup

from . import chatrounds
from . import taskrun
from . import wallpaper
from . import autorun, chatask, chatnew, chatsend, common, gatereview, health, intake, mdtree, task as task_ops, taskarchive, taskboard, taskdesk, taskfiles, taskhtml, taskinbox, tasklife, tasksub, taskreview, vslink
from . import ready as readiness
from .common import CommandError

HEADER = "X-Harness-Board"
COOKIE = "harness_board"
MAX_BODY = 4096
MAX_SEND_BODY = 64 * 1024  # `/api/answer`: the person's own words
MAX_FILES_BODY = (chatsend.MAX_FILES_TOTAL * 4) // 3 + chatsend.MAX_FILES * 1024 + MAX_SEND_BODY  # `/api/send`, `/api/steer` and `/api/create`: the words and their files, as base64
MAX_INBOX_BODY = 40 * 1024 * 1024  # `/api/inbox` carries pictures (base64); the other calls stay small
MAX_ARCHIVE = 200  # tasks in one request
EARLY_ENTER = 2.0  # seconds after the start in which a line from the terminal is not taken for the person pressing Enter
FREE = ("pause", "resume", "offwork", "onwork")  # no pairing: they guard nothing
ALL_AT_ONCE = ("offwork", "onwork")  # every task at once (`task offwork`, `task onwork`); allowed where `pause` is
BUILTIN = ("send", "answer", "steer", "stop", "create", "confirm", "question")  # the buttons that talk to the chat (1.6) and the "new task" button (B73): always offered by a served board, not a setting; each is a POST of a paired browser
DESK_REFRESH = 10  # seconds between two reads of a task page
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
    return {"port": config.whole(found.get("port"), 8765), "refresh": refresh_seconds(found.get("refresh_seconds")), "actions": list(actions) if isinstance(actions, list) else ["pause", "resume", "confirm-req", "approve-plan", "approve-promote", "review extend", "review waive", "review dismiss", "review set", "autorun on", "recover", "archive", "close"]}


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


class Board:
    """What one server holds: the settings, the pairing code and the sessions of paired browsers. Memory only."""

    def __init__(self, root: Path, everything: bool, port: int, actions: List[str], link: Optional[vslink.VsLink] = None, refresh: int = REFRESH) -> None:
        self.root = root
        self.runner = taskrun.Runner(root)
        self.short_missing = False
        self.refresh = refresh
        self.link = link or vslink.VsLink(root, enabled=False)  # a board made without a link (the tests) has none
        self.everything = everything
        self.port = port
        self.actions = actions
        self.code = secrets.token_urlsafe(12)
        self.sessions: set = set()
        self.lock = threading.Lock()
        self.wall_window = threading.Lock()  # one folder window at a time
        self.language_stamp: List[int] = []
        self.version = disk_version(root)  # the release this process loaded: code changed on disk is not used until the board starts again (B63)
        self.ready = readiness.Ready(root, self.link)  # the Enter screen (`/api/ready`)
        self.who: Tuple[float, str] = (-1e9, "")

    def user_name(self) -> str:
        """The name for `Hi, <name>` on the Enter screen: what `harness user` reads (user.override.json, else `git config user.name`). Kept a minute: git may be slow, and a page must not wait on it each time."""
        now = time.monotonic()
        with self.lock:
            if now - self.who[0] < 60:
                return self.who[1]
        try:
            name = user.who(self.root)["name"]
        except Exception:  # noqa: BLE001 - no name is only a plainer greeting
            name = ""
        with self.lock:
            self.who = (now, name)
        return name

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
        stamp = []
        for path in (config.policies_dir(self.root) / "user.json", config.override_path(self.root, "user")):
            try:
                stamp.append(path.stat().st_mtime_ns)
            except OSError:
                stamp.append(0)
        with self.lock:
            if stamp != self.language_stamp:
                self.language_stamp = stamp
                messages.reset()
        return messages.language()

    @property
    def served(self) -> List[str]:
        """What the page may run: the settings' actions and the ones that talk to the chat."""
        return self.actions + [item for item in BUILTIN if item not in self.actions]

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
        result, _problems = taskboard.board_rows(self.root, self.everything, 0, self.served)
        self.link.overlay(result["tasks"])
        for row in result["tasks"]:
            health.with_context(self.root, row, row.get("chat"))
        asked = [taskboard.with_ask(row, self.link.ask_of(row["task"]), tuple(self.served), self.root) for row in result["tasks"] if row.get("status") == "open"]
        if any(asked):  # the chat waits for a person to allow a command or answer a question: that wait comes first in the order
            tasklife.sort_rows(result["tasks"])
        for row in result["tasks"]:  # the agent is at work in the chat: say something to it, or stop it
            if row.get("status") == "open" and (row.get("chat") or {}).get("state") == "busy" and "steer" in self.served:
                row["actions"] = [item for item in row["actions"] if item["action"] not in ("steer", "stop")] + [{"action": "steer", "command": ""}, {"action": "stop", "command": ""}]
        return {"rows": result["tasks"], "hidden": result["closed_hidden"], "as_of": utc_now(), "archive_to": taskarchive.remembered(self.root), "vscode": self.link.status()}

    def page(self) -> str:
        found = self.rows()
        return taskhtml.board_page(found["rows"], found["as_of"], 0, serve=self.serve_info({"archive_to": found["archive_to"], "vscode": found["vscode"]}, self.refresh), hidden=found["hidden"])

    def desk(self, name: str, trace_tree: bool = False) -> Dict[str, Any]:
        found = taskdesk.desk(self.root, name, self.served, trace_tree)  # the tree reads whole logs: only for a Trace tab that is open
        chat = self.link.chat_of(found["task"], name)
        recent = chat.pop("recent", "")
        sub = chat.pop("sub", None) or tasksub.from_hooklog(self.root, tasks.read(self.root, found["task"]) or {})  # the chat's own line; else the hook log's
        if chat.get("bound"):
            chat.update(self.link.context_card(found["task"]))
        found["chat"], found["sub"], found["recent"], found["vscode"] = chat, sub, recent, self.link.status()
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
        return {"n": taskreview.state_of(data)["n"], "max_n": taskreview.settings(self.root)["max_n"], "model": model.get("id", ""), "thinking": (model.get("config") or {}).get("thinkingLevel", ""), "context": (model.get("config") or {}).get("contextSize", 0), "options": self.link.chat_options(task),
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
        return result

    def idle(self, action: str, task: str) -> None:
        """The page may be ten seconds old: before any action, look again whether the agent is in the middle of a turn (it may be answering a doubt)."""
        data = tasks.read(self.root, task_ops.resolve(self.root, task))
        if data is not None and tasklife.at_work(self.root, data):
            raise CommandError(say("serve.busy"))

    def close(self, name: str, reason: str = "") -> Dict[str, Any]:
        """Close a task (`task close`): the report is written, the session lets go. The folder stays; `task open` opens it again.
        The browser must be paired; no code is typed, for it undoes nothing that cannot be undone. `reason`: what the person typed in the dialog (like `task close --reason`); else the page's own words."""
        if "close" not in self.actions:
            raise CommandError(say("serve.action.off", action="close"))
        self.idle("close", name)
        result = task_ops.close(self.root, name, reason.strip()[:500] or say("serve.close.reason"), check_todo=False)
        print(say("serve.did", action="close", task=task_ops.name_of(result["task"])), flush=True)
        return result

    def act(self, action: str, task: str, step: str, code: str = "", with_req: bool = False, n: Any = None) -> Dict[str, Any]:
        """Run one action. `step`: `preview` or `act` for an approval; pause and resume act at once."""
        if action in ALL_AT_ONCE:
            if "pause" not in self.actions:
                raise CommandError(say("serve.action.off", action=action))
            result = (tasklife.offwork if action == "offwork" else tasklife.onwork)(self.root, interactive=True)
            for name in result.get("paused") or result.get("resumed") or []:
                noted(self.root, name, action)
            return result
        if action not in self.actions:
            raise CommandError(say("serve.action.off", action=action))
        self.idle(action, task)
        if action == "review set":  # one click, no code: the same function as `task review set`; the cap and the history are its own
            result = taskreview.set_by_person(self.root, task, n if isinstance(n, int) and not isinstance(n, bool) else -1, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        if action in FREE:
            result = (tasklife.pause if action == "pause" else tasklife.resume)(self.root, task, interactive=True)
            noted(self.root, result.get("task") or task, action)
            return result
        call = runner(self.root, action, task)
        if action == "approve-plan" and with_req:
            plain = call
            call = lambda **kw: plain(with_req=True, **kw)  # noqa: E731 - the requirement and the plan, one code
        out = io.StringIO()
        if step == "preview":
            def stop(asked: str) -> str:
                raise Preview(asked)

            try:
                call(reader=stop, interactive=True, out=out)
            except Preview as asked:
                return {"screen": [line for line in out.getvalue().splitlines() if line.strip()], "ask": asked.asked}
            raise CommandError(say("serve.preview.none"))
        result = call(reader=lambda _asked: code, interactive=True, out=out)
        noted(self.root, result.get("task") or task, action)
        return result

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

    def setup(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Get ready (`core/setup.py`). `step`: state, probe or act. When the short command appears while VS Code is open, the agent's terminals do not have it yet:
        the Enter screen waits until VS Code was closed and came back."""
        step = str(data.get("step", ""))
        if step == "probe":
            return core_setup.repositories(data.get("repos_root"))
        if step == "act":
            result = core_setup.finish(self.root, data)
            self.language_stamp = []
            self.sync_language()
            return result
        if step != "state":
            raise CommandError(say("serve.refused.request"))
        found = core_setup.status(self.root)
        linked = bool(self.link.status().get("ready"))
        if not found["short"]["found"]:
            self.short_missing = True
        elif self.short_missing:
            self.short_missing = False
            self.ready.reopen = linked
        if self.ready.reopen and not linked:
            self.ready.reopen = False
        return dict(found, reopen=self.ready.reopen)

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

    def steer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task, found = self.target(data)
        text, problem = chatsend.steer_text(str(data.get("text", "")), str(data.get("lang", "")))
        if problem:
            raise CommandError(self.refusal("text." + problem))
        text = chatsend.with_english(self.root, task, str(data.get("lang", "")), text)
        model = chatsend.model_of(found)
        files = self.files_of(data)
        try:
            done = self.link.dispatch("steer", task, text, model, files)
        except vslink.Refused as error:
            raise Fallback(self.refusal(error.why), text) from None
        except Exception as error:  # noqa: BLE001
            raise Fallback(ahp_scrub(error), text) from None
        return self.sent(task, found, "steer", text, done, {"model": model or {}, "files": chatsend.listed(files)})

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
                "limit": chatnew.MAX_TEXT,
                "domains": intake.kb_domains(self.root)}  # the knowledge base domains a task may be about (none is a choice); empty: no knowledge base has one

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """`step` options: what the dialog offers. `preview`: the first message, whole, and whether it can go now. `act`: make the chat in VS Code and send it. Every field is checked here again."""
        step = str(data.get("step", "act"))
        if step == "options":
            return self.create_options()
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
            if size and size not in [item["id"] for item in (listed[wanted].get("context") or {}).get("sizes") or []]:
                raise CommandError(self.refusal("context"))
            config = {**({"thinkingLevel": level} if level else {}), **({"contextSize": size} if size else {})}
            model = {"id": wanted, **({"config": config} if config else {})}
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
        """Take the last message of the person out of the chat, with what answered it, and give back its words for the reply box. The chat must be idle."""
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

        def token(self) -> str:
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
            limit = MAX_INBOX_BODY if urlparse(self.path).path in ("/api/inbox", "/api/intake") else MAX_FILES_BODY if urlparse(self.path).path in ("/api/send", "/api/steer", "/api/create") else MAX_SEND_BODY if urlparse(self.path).path == "/api/answer" else MAX_BODY
            try:
                size = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(size, limit)).decode("utf-8") or "{}") if 0 <= size <= limit else None
            except (ValueError, UnicodeDecodeError):
                data = None
            if not isinstance(data, dict):
                return self.answer(400, {"error": say("serve.refused.body")})
            path = urlparse(self.path).path
            if path == "/api/pair":
                token = board.pair(str(data.get("code", "")))
                if token is None:
                    return self.answer(403, {"error": say("serve.pair.wrong")})
                cookie = f"{board.cookie}={token}; HttpOnly; SameSite=Strict; Path=/"
                return self.answer(200, {"paired": True}, {"Set-Cookie": cookie})
            if path == "/api/status":
                return self.answer(200, {"paired": board.paired(self.token()), "started": board.version, "now": disk_version(board.root), "vscode": board.link.status()})
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
                asked = board.link.open_window()
                if asked != "queued":
                    return self.answer(409, {"error": say("serve.open.off") if asked == "off" else say("serve.open.no-cli")})
                return self.answer(200, {"result": {"queued": True}})
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
            if path in ("/api/send", "/api/steer", "/api/stop", "/api/compact", "/api/draft", "/api/setting", "/api/chatconfig", "/api/undo", "/api/verdict", "/api/export", "/api/confirm", "/api/answer"):  # talk to the chat, its settings, the Gate verdicts: the paired browser, nothing else
                if not board.paired(self.token()):
                    return self.answer(403, {"error": say("serve.pair.needed"), "unpaired": True})
                try:
                    if path == "/api/send":
                        result = board.send(data) if str(data.get("step", "act")) == "act" else board.preview(data)
                    else:
                        result = getattr(board, path[len("/api/"):])(data)
                    if path != "/api/send" or str(data.get("step", "act")) == "act":
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
                        return self.answer(200, {"result": {"rounds": chatrounds.listing(board.root, row["task"])}})
                    found = chatrounds.one(board.root, row["task"], data.get("n"))
                    return self.answer(200, {"result": found}) if found else self.answer(404, {"error": say("serve.refused.request")})
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
                result = board.act(action, task, step, str(data.get("code", "")), bool(data.get("with_req")), data.get("n"))
            except Exception as error:  # noqa: BLE001 - a refusal is shown on the page, as the terminal shows it
                return self.answer(409, {"error": str(error)})
            print(say("serve.did", action=action, task=task_ops.name_of(task) if task else "-"), flush=True)
            return self.answer(200, {"result": result})

    return Handler


def already_serving(root: Path, port: int) -> bool:
    """The board of this same copy has this port and answers: a second double-click opens its page and leaves it running."""
    if board_serve_port(root) != port:
        return False
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}/api/status", data=b"{}", headers={HEADER: "1", "Content-Type": "application/json"}), timeout=3) as answer:
            return answer.status == 200
    except (OSError, ValueError):
        return False


def serve(root: Path, everything: bool = True, port: Optional[int] = None, out: Any = None, interactive: Optional[bool] = None, opener: Callable[[str], Any] = webbrowser.open, ready: Optional[Callable[[Any], None]] = None,
          link: Optional[vslink.VsLink] = None) -> Dict[str, Any]:
    """Run until Ctrl+C. `opener`, `ready` and `link` exist for the tests: `ready` gets the server once it listens; `link`, a link made by hand (a fake host, or none)."""
    task_ops.person("task board --serve", interactive, typed=False)
    out = out or sys.stdout
    found = settings(root)
    link = link if link is not None else vslink.VsLink(root, enabled=vslink.enabled_by_policy(root))
    board = Board(root, everything, port or found["port"], found["actions"], link, found["refresh"])
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", board.port), handler_for(board))
    except OSError as error:
        if already_serving(root, board.port):
            print(say("serve.already", url=f"http://127.0.0.1:{board.port}/"), file=out, flush=True)
            opener(f"http://127.0.0.1:{board.port}/")
            return {"served": f"http://127.0.0.1:{board.port}/", "stopped": False, "already": True}
        raise CommandError(say("serve.port.busy", port=board.port, error=error))
    taskarchive.prune_transcripts(root, taskarchive.remembered(root))
    link.start()  # the thread only; the board does not wait for VS Code
    path = board_serve_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"port": board.port, "pid": os.getpid(), "started": utc_now()}), encoding="utf-8")
    address = f"http://127.0.0.1:{board.port}/"
    opened = False
    try:
        opened = bool(opener(f"{address}#pair={board.code}"))
    except Exception:  # noqa: BLE001 - the person can pair by hand
        opened = False
    print(say("serve.started", address=address, actions=", ".join(board.actions)), file=out, flush=True)
    print(say("serve.opened" if opened else "serve.not_opened"), file=out, flush=True)
    if ready is not None:
        ready(server)
    else:
        threading.Thread(target=wait_for_enter, args=(board, address, out), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        board.runner.stop_all()
        link.stop()
        server.server_close()
        try:
            path.unlink()
        except OSError:
            pass
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