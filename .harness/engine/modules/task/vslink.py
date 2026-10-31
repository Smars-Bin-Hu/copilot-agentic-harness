"""The link from the board to the VS Code that runs the chats (1.6, B71). One background thread holds the connection and a cache; a page request only reads the cache.

- The thread finds `code`, reads the endpoint (`core.ahp`), connects, and lists the chats of Copilot. The root notifications of the host keep the list true; a new list is asked
  for every few minutes in case one was missed. Nothing is subscribed but the chats bound to an open task (and, for one moment, a chat read to find its Copilot session id).
- Where it cannot connect, it tries again with longer waits. The board works as before: no error, no wait. A request never starts `code` or touches the host.
- Which chat belongs to which task: `chatlink`. What a task's line shows: `tasksub`.
- The token of the host is in the connection object only.
- `HARNESS_VSCODE_CLI=off`, or `board.vscode = false` in `task.override.json`, switches the whole link off.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from core import ahp, config, tasks
from core.paths import utc_now

from . import chatlink, task as task_ops, tasklife, tasksub

TASKS_EVERY = 3.0  # seconds between two looks at the tasks and their chats
RELIST_EVERY = 180.0  # a whole new list of chats, in case a notification was missed
SCAN_PER_TURN = 3  # chats read in one turn to find their Copilot session id
SCAN_MAX = 300  # chats read at most, newest first
NO_CLI_WAIT = 300.0  # no `code` command: look again only now and then


def enabled_by_policy(root: Path) -> bool:
    return (config.policy_or_empty(root, "task").get("board") or {}).get("vscode", True) is not False


def choose(found: List[ahp.Endpoint], root: Path, connect: Callable[[ahp.Endpoint], ahp.Connection] = ahp.connect) -> ahp.Connection:
    """One endpoint: that one. Several (several VS Code programs): the one that has chats of this harness folder; none or two of them: not ready, never a guess."""
    if len(found) == 1:
        return connect(found[0])
    matches = []
    for endpoint in found:
        try:
            link = connect(endpoint)
        except (ahp.AhpError, OSError):
            continue
        try:
            mine = any(ahp.session_in(item, str(root)) for item in link.sessions() if ahp.is_ours(item))
        except ahp.AhpError:
            mine = False
        if mine:
            matches.append(link)
        else:
            link.close()
    if len(matches) == 1:
        return matches[0]
    for link in matches:
        link.close()
    raise ahp.NotReady("many")


class VsLink:
    def __init__(self, root: Path, enabled: bool = True, opener: Optional[Callable[[], ahp.Connection]] = None, persist: bool = True,
                 turn: float = 1.0, backoff: Optional[ahp.Backoff] = None) -> None:
        self.root = root
        self.enabled = enabled
        self.persist = persist
        self.turn = turn
        self.backoff = backoff or ahp.Backoff()
        self._opener = opener or self._open
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.wake = threading.Event()
        self.jobs: "queue.Queue[str]" = queue.Queue()
        self.thread: Optional[threading.Thread] = None
        self.ready = False
        self.why = "off" if not enabled else "starting"
        self.sessions: Dict[str, Dict[str, Any]] = {}  # the chats of this folder, by resource
        self.sdk: Dict[str, Set[str]] = {}
        self.scanned: Dict[str, str] = {}  # resource -> modifiedAt when it was read for its Copilot id
        self.bound: Dict[str, Dict[str, Any]] = {}  # task -> binding
        self.unbound: Dict[str, str] = {}  # task -> why
        self.chats: Dict[str, Dict[str, Any]] = {}  # chat resource -> {state, tool_at}
        self.listed_at = 0.0
        self.dirty = True

    # --- the page side: reads only ------------------------------------------------------------------------------------------

    def start(self) -> None:
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self._run, name="vscode-link", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(5)

    def status(self) -> Dict[str, Any]:
        """`{ready, bound, unbound, why}`: for `/api/status` and `/api/board`. `bound` and `unbound` count the open tasks."""
        with self.lock:
            return {"ready": self.ready, "bound": len(self.bound) if self.ready else 0, "unbound": len(self.unbound) if self.ready else 0, "why": "ok" if self.ready else self.why}

    def chat_of(self, task: str, name: str = "") -> Dict[str, Any]:
        """What a row or a task page shows of the chat: `{bound, why, state, title, model, how}` and, when the chat said something, `sub` and `recent`."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding:
                return {"bound": False, "why": self.unbound.get(task, "") if self.ready else self.why}
            summary = self.sessions.get(binding["session"]) or {}
            cached = self.chats.get(binding["chat"]) or {}
            out: Dict[str, Any] = {"bound": True, "how": binding.get("how", ""), "title": str(summary.get("title") or binding.get("title") or ""), "state": ahp.status_name(summary.get("status"))}
            if cached.get("state"):
                found = tasksub.facts(cached["state"], self.root)
                out["model"] = found["model"]
                sub = tasksub.sub_of(found, cached.get("tool_at", "") if found["busy"] else "")
                if sub:
                    out["sub"] = sub
                if found["reply"]:
                    out["recent"] = tasksub.recent_text(found["reply"])
            return out

    def overlay(self, rows: List[Dict[str, Any]]) -> None:
        """Put `chat` on every open row, and `sub` where the chat has something newer than the hook log gave. No I/O."""
        for row in rows:
            if row.get("status") != "open":
                continue
            chat = self.chat_of(row["task"], row.get("name", ""))
            sub = chat.pop("sub", None)
            chat.pop("recent", None)
            row["chat"] = chat
            if sub:
                row["sub"] = sub

    def open_window(self) -> str:
        """Ask the thread to bring the VS Code window of this folder to the front (`code <folder>`, never `-r`). Returns at once: `queued`, or why it cannot (`off`, `no-cli`)."""
        with self.lock:
            if not self.enabled or self.why in ("off", "no-cli"):
                return "off" if not self.enabled else self.why
        self.jobs.put("open")
        self.wake.set()
        return "queued"

    # --- the thread ---------------------------------------------------------------------------------------------------------

    def _open(self) -> ahp.Connection:
        code = ahp.find_code()
        if not code:
            raise ahp.NotReady("off" if ahp.switched_off() else "no-cli")
        found = ahp.read_endpoints(code)
        if not found:
            raise ahp.NotReady("none")
        return choose(found, self.root)

    def _set(self, ready: bool, why: str) -> None:
        with self.lock:
            self.ready, self.why = ready, why

    def _wait(self, seconds: float) -> None:
        self.wake.wait(seconds)
        self.wake.clear()

    def _run(self) -> None:
        while not self.stop_flag.is_set():
            self._jobs()
            try:
                link = self._opener()
            except ahp.NotReady as error:
                self._set(False, error.why)
                self._wait(NO_CLI_WAIT if error.why in ("no-cli", "off") else self.backoff.next())
                continue
            except (ahp.AhpError, OSError, ValueError):
                self._set(False, "error")
                self._wait(self.backoff.next())
                continue
            self.backoff.reset()
            try:
                self._serve(link)
            except (ahp.AhpError, OSError, ValueError):
                pass
            finally:
                link.close()
                with self.lock:
                    self.ready, self.why = False, "lost"
                    self.chats.clear()
                    self.sessions.clear()
                    self.bound.clear()
                    self.unbound.clear()
                    self.sdk.clear()
                    self.scanned.clear()
                    self.listed_at = 0.0
            self._wait(self.backoff.next())

    def _jobs(self) -> None:
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                return
            code = ahp.find_code()
            if code:
                try:
                    ahp.run_code(code, [str(self.root)])  # the folder, no `-r`: a window that has it is brought forward
                except ahp.AhpError:
                    pass

    def _list(self, link: ahp.Connection) -> None:
        mine = {item["resource"]: item for item in link.sessions() if ahp.is_ours(item) and ahp.session_in(item, str(self.root)) and item.get("resource")}
        with self.lock:
            self.sessions = mine
            self.listed_at = time.monotonic()
            self.dirty = True

    def _serve(self, link: ahp.Connection) -> None:
        self._list(link)
        self._set(True, "ok")
        last = 0.0
        while not self.stop_flag.is_set():
            note = link.next_notice(self.turn)
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)
            self._jobs()
            now = time.monotonic()
            if now - self.listed_at >= RELIST_EVERY:
                self._list(link)
            if self.dirty or now - last >= TASKS_EVERY:
                last = now
                self.dirty = False
                self._look(link)

    def _notice(self, note: Dict[str, Any]) -> None:
        method, params = str(note.get("method") or ""), note.get("params") or {}
        with self.lock:
            if method == "root/sessionAdded":
                item = params.get("summary") or {}
                if ahp.is_ours(item) and ahp.session_in(item, str(self.root)) and item.get("resource"):
                    self.sessions[item["resource"]] = item
                    self.dirty = True
            elif method == "root/sessionSummaryChanged":
                known = self.sessions.get(str(params.get("session") or ""))
                if known is not None and isinstance(params.get("changes"), dict):
                    known.update(params["changes"])
                    self.dirty = True
            elif method == "root/sessionRemoved":
                self.sessions.pop(str(params.get("session") or ""), None)
                self.dirty = True
            elif method == "action":
                cached = self.chats.get(str(params.get("channel") or ""))
                action = params.get("action")
                if cached is not None and isinstance(action, dict):
                    ahp.reduce_chat(cached["state"], action)
                    if action.get("type") in ("chat/toolCallStart", "chat/toolCallReady"):
                        cached["tool_at"] = utc_now()

    def _entries(self) -> List[Dict[str, Any]]:
        out = []
        for task in tasks.folders(self.root):
            data = tasks.read(self.root, task)
            if data and data.get("status") == "open":
                out.append({"task": task, "name": data.get("name") or task_ops.name_of(task), "session_id": str(data.get("session_id") or ""), "held": tasklife.held(self.root, data), "chat": data.get("chat")})
        return out

    def _look(self, link: ahp.Connection) -> None:
        """Read the tasks, read the chats that are still unknown, bind, and subscribe to the bound chats (and let go of the others)."""
        entries = self._entries()
        with self.lock:
            sessions = dict(self.sessions)
        self._scan(link, entries, sessions)
        with self.lock:
            found = chatlink.decide(entries, sessions, self.sdk)
            self.bound = {task: binding for task, (binding, _why) in found.items() if binding}
            self.unbound = {task: why for task, (binding, why) in found.items() if not binding}
        if self.persist:
            for entry in entries:
                binding, _why = found[entry["task"]]
                if binding is not None or (entry.get("chat") or {}).get("how") != "board":
                    chatlink.keep(self.root, entry["task"], binding)
        self._subscribe(link)

    def _scan(self, link: ahp.Connection, entries: List[Dict[str, Any]], sessions: Dict[str, Dict[str, Any]]) -> None:
        with self.lock:
            done = set(self.bound)
        if not any(entry["session_id"] and entry["task"] not in done and (entry.get("chat") or {}).get("how") != "board" for entry in entries):
            return  # every task that can be bound is: no chat needs reading
        wanted = sorted(sessions.values(), key=lambda item: str(item.get("modifiedAt") or ""), reverse=True)[:SCAN_MAX]
        todo = []
        for item in wanted:
            resource = item["resource"]
            if resource in self.chats or not item.get("defaultChat"):
                continue
            if resource not in self.scanned or (not self.sdk.get(resource) and self.scanned[resource] != item.get("modifiedAt")):
                todo.append(item)
        for item in todo[:SCAN_PER_TURN]:
            resource, chat = item["resource"], item["defaultChat"]
            try:
                ids = ahp.sdk_ids(link.subscribe(chat))
                link.unsubscribe(chat)
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                ids = set()  # this chat cannot be opened now: it is not read again until it changes
            with self.lock:
                self.sdk[resource] = ids
                self.scanned[resource] = str(item.get("modifiedAt") or "")
            self.dirty = True

    def _subscribe(self, link: ahp.Connection) -> None:
        with self.lock:
            wanted = {binding["chat"]: binding["session"] for binding in self.bound.values() if binding.get("chat")}
            have = set(self.chats)
        for chat in have - set(wanted):
            try:
                link.unsubscribe(chat)
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                pass
            with self.lock:
                self.chats.pop(chat, None)
        for chat in set(wanted) - have:
            try:
                state = ahp.trimmed(link.subscribe(chat))
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                continue
            with self.lock:
                self.chats[chat] = {"state": state, "tool_at": ""}
