"""The link from the board to the VS Code that runs the chats (1.6, B71). One background thread holds the connection and a cache; a page request only reads the cache.

- The thread finds `code`, reads the endpoint (`core.ahp`), connects, and lists the chats of Copilot. The root notifications of the host keep the list true; a new list is asked
  for every few minutes in case one was missed. Nothing is subscribed but the chats bound to an open task (and, for one moment, a chat read to find its Copilot session id).
- Where it cannot connect, it tries again with longer waits. A page gets no error and no wait; the Enter screen says what is missing. A request never starts `code` or touches the host.
- Which chat belongs to which task: `chatlink`. What a task's line shows: `tasksub`.
- The token of the host is in the connection object only.
- `HARNESS_VSCODE_CLI=off`, or `board.vscode = false` in `task.override.json`, switches the whole link off.
- B72: a person's send, steer or stop is a job for the thread (`dispatch`): only that thread talks to the host. Before it acts, the thread looks again: a fresh list of chats, the binding
  worked out again, the state of the chat now. It refuses (`Refused`) rather than guess. The model chosen on the task page goes on every message (`message.model`; it sticks in the chat).
- B73: `create` makes a chat for a task that does not exist yet (`createSession`, `isolation: folder`, mode `interactive`), sends its first message at once (the host does not list a chat
  before its first turn; the model must be on that message, `createSession.model` is not honoured), and reads back who the host says made it. The task is made later by the agent: the
  thread remembers the chat (`created`) and, when the task with that name is open, binds it (`chatlink.adopt`) and keeps the model on the task. `disposeSession` is never called.
- B75: the session of each bound chat is subscribed too, for its `inputNeeded[]` (the host pushes `session/inputNeededSet` and `Removed`). `ask_of` gives a task's oldest tool confirmation or question
  (`chatask`; any other kind is ignored). A person's allow, deny or answer is a job (`respond`): the thread reads the session again, refuses when the item is gone or is not what the page showed, then
  dispatches the actions that `chatask` made.
"""

from __future__ import annotations

import datetime
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core import ahp, config, tasks
from core.paths import utc_now

from . import chatask, chatctx, chatlink, chatlive, chatnew, chatsend, task as task_ops, tasklife, tasksub

TASKS_EVERY = 3.0  # seconds between two looks at the tasks and their chats
RELIST_EVERY = 180.0  # a whole new list of chats, in case a notification was missed
MODELS_EVERY = 15.0  # the models again: the host says no event when Copilot signs out or in, it only lists none or some
EXPECT_EVERY = 2.0  # a chat the board made that the host does not list yet: asked again this often ...
EXPECT_FOR = 120.0  # ... for this long
SCAN_PER_TURN = 3  # chats read in one turn to find their Copilot session id
SCAN_MAX = 300  # chats read at most, newest first
NO_CLI_WAIT = 300.0  # no `code` command: look again only now and then
JOB_WAIT = 25.0  # seconds a page request waits for the thread to send, steer or stop
CREATE_WAIT = 45.0  # a create makes the chat, sends, then waits for the host to list it
REREAD_AFTER_ANSWER = 10.0  # seconds after a person answered in which a session that still says "input" is not read again for a missed item
PROBLEM_FOR = 120.0  # seconds a "Copilot is not usable" answer of the host is still told after it was heard
INITIATOR_WAIT = 10.0  # seconds after the first message in which the host is asked who made the chat


def enabled_by_policy(root: Path) -> bool:
    return (config.policy_or_empty(root, "task").get("board") or {}).get("vscode", True) is not False


def elapsed_ms(started: Any) -> int:
    """Milliseconds since a turn began (`startedAt`, an ISO time); the host wants a number, and a turn whose start is not readable gets 1000."""
    try:
        begun = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        return max(1, int((datetime.datetime.now(datetime.timezone.utc) - begun).total_seconds() * 1000))
    except (ValueError, TypeError):
        return 1000


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


class Refused(Exception):
    """A send, steer or stop that was not done, and why (`why` is a key of `send.refused.*`): off, not-ready, unbound, unsure, changed, not-idle, not-busy, no-turn, timeout."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


class Job:
    """One thing for the thread to do to a chat. The page request waits on `done`."""

    def __init__(self, kind: str, task: str, text: str = "", model: Optional[Dict[str, Any]] = None, plan: Optional[Dict[str, Any]] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> None:
        self.kind, self.task, self.text, self.model, self.plan, self.attachments = kind, task, text, model, plan, attachments
        self.done = threading.Event()
        self.cancelled = False
        self.result: Dict[str, Any] = {}
        self.error: Optional[BaseException] = None


NEEDS = {"send": "idle", "steer": "busy", "stop": "busy", "confirm": "input", "answer": "input", "config": "", "undo": "idle"}  # "": any state: a setting of the chat holds from its next turn


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
        self.jobs: "queue.Queue[Any]" = queue.Queue()  # "open", or a Job
        self.thread: Optional[threading.Thread] = None
        self.ready = False
        self.why = "off" if not enabled else "starting"
        self.sessions: Dict[str, Dict[str, Any]] = {}  # the chats of this folder, by resource
        self.sdk: Dict[str, Set[str]] = {}
        self.scanned: Dict[str, str] = {}  # resource -> modifiedAt when it was read for its Copilot id
        self.bound: Dict[str, Dict[str, Any]] = {}  # task -> binding
        self.unbound: Dict[str, str] = {}  # task -> why
        self.chats: Dict[str, Dict[str, Any]] = {}  # chat resource -> {state, tool_at}
        self.sess: Dict[str, Dict[str, Any]] = {}  # session resource of a bound chat -> {channel, state (trimmed: inputNeeded), seen: {item id: when first seen}}
        self.limits: Dict[str, Dict[str, int]] = {}  # model id -> what decides its context window, every model the host lists (for the context meter)
        self.models: List[Dict[str, Any]] = []  # what a person may pick (`ahp.models_of`); empty until the host said
        self.created: List[Dict[str, Any]] = []  # chats this board made whose task does not exist yet (`chatnew.pending`); memory only
        self.expect: Dict[str, Dict[str, Any]] = {}  # session resource of a chat this board made that the host has not listed yet -> {stub, until}; memory only
        self.listed_at = 0.0
        self.problem: Tuple[str, float] = ("", 0.0)  # what the host last said that means Copilot is not usable: ("provider" | "client" | "", when); the Enter screen shows it
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

    def host_said(self, error: BaseException) -> None:
        """Remember the two things the host says when Copilot itself is not usable (`Provider copilotcli is not ready`, `Client is not connected`); any other error is not Copilot's sign-in."""
        text = str(error).lower()
        found = "provider" if "provider" in text and "not ready" in text else "client" if "not connected" in text else ""
        if found:
            with self.lock:
                self.problem = (found, time.monotonic())

    def copilot(self) -> Dict[str, Any]:
        """For the Enter screen, from the cache: how many models the host lists (those the policy allows) and what it last said about Copilot (`provider`, `client`, or empty; forgotten after 2 minutes)."""
        with self.lock:
            kind, at = self.problem
            return {"models": len(self.models) if self.ready else 0, "problem": kind if kind and time.monotonic() - at < PROBLEM_FOR else ""}

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
                out["model_name"] = next((str(item.get("name") or "") for item in self.models if item.get("id") == found["model"]), "")  # as the pickers call it; not listed: the page falls back on the id
                if found["busy"] and found["started"]:
                    out["started_at"] = found["started"]  # the run time of the latest turn is counted by the page, only while it runs
                out["context"] = chatctx.meter(cached["state"], self.limits)  # None: unknown, shown empty
                out["effort"] = chatctx.effort(cached["state"], found["model"])  # only what a message said; None: not known
                out["window"] = chatctx.capacity(found["model"], self.limits, chatctx.chosen_size(cached["state"], found["model"]))  # None: not listed
                sub = tasksub.sub_of(found, cached.get("tool_at", "") if found["busy"] else "")
                if sub:
                    out["sub"] = sub
                if found["reply"]:
                    out["recent"] = tasksub.recent_text(found["reply"])
            return out

    def live(self, task: str, last: str = "") -> Dict[str, Any]:
        """For the Live tab of an open task, from the cache only (no file, no call to the host): `{rev, bound, why | state, started, now, items, more}`. `last` is the `rev` the page already has:
        when nothing changed the answer is only `{rev, same: true}`. `task` is the folder name of the task."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding:
                why = self.unbound.get(task, "") if self.ready else self.why
                rev = "x:" + why
                return {"rev": rev, "same": True} if rev == last else {"rev": rev, "bound": False, "why": why}
            state = ahp.status_name((self.sessions.get(binding["session"]) or {}).get("status"))
            cached = self.chats.get(binding["chat"])
            rev = f"{binding['chat']}:{cached.get('rev', 0) if cached else -1}:{state}"
            if rev == last:
                return {"rev": rev, "same": True}
            if cached is None:  # bound, the chat is being read
                return {"rev": rev, "bound": True, "state": state, "now": int(time.time() * 1000), "items": [], "more": False, "started": "", "loading": True}
            found = chatlive.build(cached["state"], cached.get("marks") or {}, self.root)
            return {"rev": rev, "bound": True, "state": state, "now": int(time.time() * 1000), **found}

    def context_card(self, task: str) -> Dict[str, Any]:
        """For the context card of the task page: `parts` (what the context holds, `chatctx.parts`; None: the chat says nothing) and `cost` (credits of the session; None: not known)."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            state = (self.chats.get(binding["chat"]) or {}).get("state") if binding else None
            if not isinstance(state, dict):
                return {"parts": None, "cost": None}
            found = chatctx.meter(state, self.limits)
            return {"parts": chatctx.parts(state, found["percent"] if found else None), "cost": chatctx.session_cost(state)}

    def chat_options(self, task: str) -> Dict[str, Any]:
        """The settings of the chat of `task` a person may change, from the cache: `{mode: {value, choices}, autoApprove: {value, choices}}`, the choices as the host offers them. A value set on
        the chat goes over the session's. Empty: no chat, or the host has not told us."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding:
                return {}
            config = ((self.sess.get(binding["session"]) or {}).get("state") or {}).get("config") or {}
            chat = ahp.config_values((self.chats.get(binding["chat"]) or {}).get("state") or {})
            return {key: {"value": chat.get(key) or (config.get("values") or {}).get(key), "choices": (config.get("choices") or {}).get(key) or []} for key in ahp.CHAT_SETTINGS if (config.get("choices") or {}).get(key)}

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

    def model_list(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(item) for item in self.models] if self.ready else []

    def waiting_names(self) -> List[str]:
        """The names of the tasks the board made a chat for and whose task is not there yet."""
        with self.lock:
            return [item["name"] for item in self.created]

    def create_blocked(self) -> str:
        """Why a chat cannot be made now (`off`, `not-ready`), from the cache. Empty: it can."""
        with self.lock:
            return "off" if not self.enabled else "" if self.ready else "not-ready"

    def create(self, plan: Dict[str, Any], text: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Make a chat for the task of `plan` and send `text` to it, on the thread. The answer: {session, chat, initiator, title}. Raises Refused (`off`, `not-ready`, `timeout`) or the host's error."""
        why = self.create_blocked()
        if why:
            raise Refused(why)
        job = Job("create", "", text, plan["model"], plan, attachments)
        self.jobs.put(job)
        self.wake.set()
        if not job.done.wait(CREATE_WAIT):
            job.cancelled = True  # a thread that has not begun must not make a chat the person was told failed
            raise Refused("timeout")
        if job.error is not None:
            self.host_said(job.error)
            raise job.error
        return job.result

    def check(self, task: str, kind: str) -> str:
        """From the cache, so a page can say at once: why `kind` (send, steer, stop) cannot be done to the chat of this task now. Empty: it can. The thread looks again before it acts."""
        with self.lock:
            if not self.enabled:
                return "off"
            if not self.ready:
                return "not-ready"
            binding = self.bound.get(task)
            if not binding:
                return "unsure" if self.unbound.get(task) == "ambiguous" else "unbound"
            state = ahp.status_name((self.sessions.get(binding["session"]) or {}).get("status"))
            if NEEDS[kind] and state != NEEDS[kind]:
                return "not-" + NEEDS[kind]
            return ""

    def dispatch(self, kind: str, task: str, text: str = "", model: Optional[Dict[str, Any]] = None, attachments: Optional[List[Dict[str, Any]]] = None, plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a message, steer, or stop the turn of the chat of `task`; the answer of the thread: {chat, turn}. Raises Refused. Returns when the host has been told, not when the agent has answered."""
        why = self.check(task, kind)
        if why:
            raise Refused(why)
        job = Job(kind, task, text, model, plan, attachments)
        self.jobs.put(job)
        self.wake.set()
        if not job.done.wait(JOB_WAIT):
            job.cancelled = True  # a late thread must not send what the person was told failed
            raise Refused("timeout")
        if job.error is not None:
            self.host_said(job.error)
            raise job.error
        return job.result

    def open_window(self) -> str:
        """Ask the thread to bring the VS Code window of this folder to the front (`code <folder>`, never `-r`). Returns at once: `queued`, or why it cannot (`off`, `no-cli`)."""
        with self.lock:
            if not self.enabled or self.why in ("off", "no-cli"):
                return "off" if not self.enabled else self.why
        self.jobs.put("open")
        self.wake.set()
        return "queued"

    def ask_of(self, task: str) -> Optional[Dict[str, Any]]:
        """What the chat of this task waits for a person to answer, from the cache: the oldest tool confirmation or question (`chatask.shown`, plus `count` of them and `since`). None: nothing, or the
        task has no chat, or the item is of another kind. The page may be seconds old: `respond` reads it again."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            held = self.sess.get(binding["session"]) if binding else None
            if not binding or held is None:
                return None
            view, count = chatask.first_for(held["state"].get("inputNeeded"), binding["chat"])
            if view is None:
                return None
            return dict(view, count=count, since=held["seen"].get(view["id"]) or utc_now())

    def respond(self, kind: str, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Allow or deny a tool call (`confirm`), or answer a question (`answer`), on the thread. `payload`: {id, digest, tool_call_id | request_id, approved | answers}. Raises Refused
        (`ask-gone`, `ask-changed`, `not-input`, `unbound`, ...) or a chatask.AnswerError. Returns when the host has been told."""
        why = self.check(task, kind)
        if why:
            raise Refused(why)
        job = Job(kind, task, "", None, payload)
        self.jobs.put(job)
        self.wake.set()
        if not job.done.wait(JOB_WAIT):
            job.cancelled = True  # a late thread must not answer what the person was told failed
            raise Refused("timeout")
        if job.error is not None:
            self.host_said(job.error)
            raise job.error
        return job.result

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
            self._jobs()  # no connection: a send that is waiting is refused
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
                    self.sess.clear()
                    self.sessions.clear()
                    self.bound.clear()
                    self.unbound.clear()
                    self.sdk.clear()
                    self.models = []
                    self.scanned.clear()
                    self.listed_at = 0.0
                    self.expect.clear()
            self._wait(self.backoff.next())

    def _jobs(self, link: Optional[ahp.Connection] = None) -> None:
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            if isinstance(job, Job):
                if link is None or job.cancelled:
                    job.error = Refused("not-ready")
                    job.done.set()
                else:
                    self._do(link, job)
                continue
            code = ahp.find_code()
            if code:
                try:
                    ahp.run_code(code, [str(self.root)])  # the folder, no `-r`: a window that has it is brought forward
                except ahp.AhpError:
                    pass

    def _models(self, link: ahp.Connection) -> None:
        """The models of the host, read from its root state once and then with every new list. One read, then we let go of the channel."""
        try:
            root_state = link.subscribe("ahp-root:/")
            found, limits = ahp.models_of(root_state), ahp.limits_of(root_state)
            link.unsubscribe("ahp-root:/")
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError as error:
            self.host_said(error)
            return
        with self.lock:
            self.models, self.limits = found, limits

    def _list(self, link: ahp.Connection) -> None:
        mine = {item["resource"]: item for item in link.sessions() if ahp.is_ours(item) and ahp.session_in(item, str(self.root)) and item.get("resource")}
        with self.lock:
            tails = {resource.rsplit("/", 1)[-1] for resource in mine}
            for resource, wait in list(self.expect.items()):
                if resource.rsplit("/", 1)[-1] in tails or time.monotonic() > wait["until"]:
                    del self.expect[resource]  # the host lists it now (or it never will): the real entry stands
                else:
                    mine.setdefault(resource, dict(wait["stub"]))  # not listed yet: the chat is tracked from what we know, not lost until the next full list
            self.sessions = mine
            self.listed_at = time.monotonic()
            self.dirty = True

    def _serve(self, link: ahp.Connection) -> None:
        self._list(link)
        self._models(link)
        self._set(True, "ok")
        last = 0.0
        read_models = time.monotonic()
        while not self.stop_flag.is_set():
            note = link.next_notice(self.turn)
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)
            self._jobs(link)
            now = time.monotonic()
            if now - self.listed_at >= (EXPECT_EVERY if self.expect else RELIST_EVERY):
                self._list(link)
                self._models(link)
                read_models = now
            elif now - read_models >= MODELS_EVERY:
                read_models = now
                self._models(link)
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
                channel = str(params.get("channel") or "")
                cached = self.chats.get(channel)
                action = params.get("action")
                if cached is not None and isinstance(action, dict):
                    ahp.reduce_chat(cached["state"], action)
                    chatlive.stamp(cached, action, int(time.time() * 1000))
                    cached["rev"] = cached.get("rev", 0) + 1  # the Live tab asks only for what changed since this number
                    if action.get("type") in ("chat/toolCallStart", "chat/toolCallReady"):
                        cached["tool_at"] = utc_now()
                held = next((item for item in self.sess.values() if item["channel"] and item["channel"] == channel), None)
                if held is not None and isinstance(action, dict):
                    ahp.reduce_session(held["state"], action)
                    self._stamp(held)
                    self.dirty = True

    @staticmethod
    def _stamp(held: Dict[str, Any]) -> None:
        """Note when each waiting item was first seen (that is the start of the wait); forget the ones that went. The caller holds the lock."""
        ids = [str(item.get("id")) for item in held["state"].get("inputNeeded") or []]
        for ident in ids:
            held["seen"].setdefault(ident, utc_now())
        held["seen"] = {ident: when for ident, when in held["seen"].items() if ident in ids}

    def _recheck(self, link: ahp.Connection, task: str, kind: str) -> Dict[str, Any]:
        """The binding of `task` worked out again from a fresh list of chats (and the ids read from the chats we hold), the same as the page was shown, and the state of the chat now."""
        self._list(link)
        entries = self._entries()
        with self.lock:
            sessions = dict(self.sessions)
            sdk = {resource: set(ids) for resource, ids in self.sdk.items()}
            for resource, item in sessions.items():
                held = self.chats.get(str(item.get("defaultChat") or ""))
                if held is not None:
                    sdk.setdefault(resource, set()).update(ahp.sdk_ids(held["state"]))
            shown = self.bound.get(task)
        binding, why = chatlink.decide(entries, sessions, sdk).get(task, (None, "no-session"))
        if not binding:
            raise Refused("unsure" if why == "ambiguous" else "unbound")
        if not chatlink.same(shown, binding):
            raise Refused("changed")  # the page showed another chat (or none): it is looked at again before anything is sent
        state = ahp.status_name(sessions[binding["session"]].get("status"))
        if NEEDS[kind] and state != NEEDS[kind]:
            raise Refused("not-" + NEEDS[kind])
        return binding

    def _initiator(self, link: ahp.Connection, resource: str, state: Dict[str, Any]) -> str:
        """Who the host says made the chat (`vscode` is right). The host lists a chat only after its first turn began: asked for a few seconds. Empty: not known."""
        found = ahp.initiator_of(state.get("_meta"))
        tail = resource.rsplit("/", 1)[-1]
        end = time.monotonic() + INITIATOR_WAIT
        while not found:
            for item in link.sessions():
                if str(item.get("resource") or "").rsplit("/", 1)[-1] == tail:
                    found = ahp.initiator_of(item.get("_meta"))
                    break
            if found or time.monotonic() >= end:
                break
            note = link.next_notice(0.5)  # the host's notices keep coming while we wait
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)
        return found

    def _create(self, link: ahp.Connection, job: Job) -> None:
        """The thread makes the chat, sends the first message, and keeps what it needs to bind the task when the agent has made it."""
        plan = job.plan or {}
        if job.cancelled:
            raise Refused("timeout")
        resource = "ahp-session:/" + str(uuid.uuid4())
        link.call("createSession", {"channel": resource, "provider": ahp.LOCAL_PROVIDER, "workingDirectories": [ahp.folder_uri(self.root)],
                                    "config": {"isolation": "folder", "mode": "interactive", "autoApprove": plan["approve"]}})  # `model` here would not be honoured: it goes on the message
        state = link.subscribe(resource)
        chat = str(state.get("defaultChat") or "")
        if not chat:
            raise ahp.AhpError("createSession: no chat in the new session")
        held = {"state": ahp.trimmed(link.subscribe(chat)), "tool_at": ""}
        message: Dict[str, Any] = {"text": job.text, "origin": {"kind": "user"}}
        if job.model:
            message["model"] = job.model
        if job.attachments:
            message["attachments"] = job.attachments
        action = {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message}
        made = {"name": plan["name"], "kind": plan["kind"], "source": plan["source"], "lang": plan["lang"], "permission": plan["permission"], "model": job.model, "text": job.text, "files": chatsend.listed(job.attachments or []),
                "session": resource, "chat": chat, "title": "", "clock": time.monotonic()}
        stub = {"resource": resource, "provider": ahp.LOCAL_PROVIDER, "title": "", "status": ahp.IN_PROGRESS, "defaultChat": chat, "chats": [{"resource": chat}],
                "workingDirectories": [ahp.folder_uri(self.root)], "modifiedAt": ahp.utc_stamp()}
        with self.lock:
            self.created.append(made)  # before the message: a chat that was made is never lost track of
            self.expect[resource] = {"stub": stub, "until": time.monotonic() + EXPECT_FOR}  # the host lists it only once the first turn runs: until then the cache holds the stub
            self.chats[chat] = held
            self.sess[resource] = {"channel": resource, "state": ahp.trimmed_session(state), "seen": {}}
        link.dispatch(chat, action)
        with self.lock:
            ahp.reduce_chat(held["state"], {**action, "message": {key: value for key, value in message.items() if key != "attachments"}})  # the bytes are not kept here
        with self.lock:
            self.sessions.setdefault(resource, dict(stub))  # tracked at once; `_list` asks again every EXPECT_EVERY seconds until the host lists it
            self.dirty = True
        initiator = self._initiator(link, resource, state)
        self._list(link)  # marks the board dirty
        job.result = {"session": resource, "chat": chat, "initiator": initiator, "turn": str(action["turnId"])}

    def _do(self, link: ahp.Connection, job: Job) -> None:
        try:
            if job.kind == "create":
                return self._create(link, job)
            if job.cancelled:
                raise Refused("timeout")
            binding = self._recheck(link, job.task, job.kind)
            if job.kind in ("confirm", "answer"):
                return self._respond(link, job, binding)
            chat, resource = binding["chat"], binding["session"]
            with self.lock:
                held = self.chats.get(chat)
            if held is None:
                held = {"state": ahp.trimmed(link.subscribe(chat)), "tool_at": ""}
                with self.lock:
                    self.chats[chat] = held
            if job.kind == "config":
                action = {"type": "chat/configChanged", "config": dict(job.plan or {})}
                link.dispatch(chat, action)
                with self.lock:
                    ahp.reduce_chat(held["state"], action)
                    self.dirty = True
                job.result = {"chat": chat}
                return
            if job.kind == "undo":
                return self._undo(link, job, chat, held)
            if job.kind == "stop":
                active = held["state"].get("activeTurn") if isinstance(held["state"].get("activeTurn"), dict) else None
                if not active or not active.get("id"):
                    raise Refused("no-turn")
                action: Dict[str, Any] = {"type": "chat/turnCancelled", "turnId": active["id"], "duration": elapsed_ms(active.get("startedAt"))}  # without `duration` the host does nothing
            else:
                message: Dict[str, Any] = {"text": job.text, "origin": {"kind": "user"}}
                if job.model:
                    message["model"] = job.model  # on every message: the host keeps the last one, whoever sent it
                if job.attachments:
                    message["attachments"] = job.attachments  # the host keeps a copy of each and lists its own address in the chat
                if job.kind == "send":
                    action = {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message}
                else:
                    action = {"type": "chat/pendingMessageSet", "kind": "steering", "id": str(uuid.uuid4()), "message": message}
            link.dispatch(chat, action)
            with self.lock:
                known = self.sessions.get(resource)
                if job.kind == "send":
                    if known is not None:
                        known["status"] = ahp.IN_PROGRESS | (int(known.get("status") or 0) & (ahp.IS_READ | ahp.ARCHIVED))  # not idle at once: a second send finds it busy
                    ahp.reduce_chat(held["state"], {**action, "message": {key: value for key, value in message.items() if key != "attachments"}})  # the bytes are not kept here
                    chatlive.stamp(held, action, int(time.time() * 1000))
                    held["rev"] = held.get("rev", 0) + 1
                title = str((known or {}).get("title") or binding.get("title") or "")
                self.dirty = True
            job.result = {"chat": chat, "title": title, "turn": str(action.get("turnId") or "")}
        except ahp.ConnectionClosed as error:
            job.error = error
            raise
        except (Refused, ahp.AhpError, OSError) as error:
            job.error = error
        finally:
            job.done.set()

    def _undo(self, link: ahp.Connection, job: Job, chat: str, held: Dict[str, Any]) -> None:
        """Take the last turn out of the chat: the message of the person and all that answered it. The host cuts Copilot's own history too (the model forgets it: checked on a real chat), but files
        the agent changed stay changed. The chat is read again first, for the whole text and the last turn as it is now."""
        link.unsubscribe(chat)
        full = link.subscribe(chat)
        turns = [turn for turn in full.get("turns") or [] if isinstance(turn, dict)]
        if not turns or full.get("activeTurn"):
            held["state"] = ahp.trimmed(full)
            raise Refused("no-turn")
        message = turns[-1].get("message") if isinstance(turns[-1].get("message"), dict) else {}
        action: Dict[str, Any] = {"type": "chat/truncated"}
        if len(turns) > 1:
            action["turnId"] = turns[-2].get("id")
        link.dispatch(chat, action)
        ahp.reduce_chat(full, action)
        with self.lock:
            held["state"] = ahp.trimmed(full)
            held["rev"] = held.get("rev", 0) + 1
            self.dirty = True
        job.result = {"text": str(message.get("text") or ""), "files": [str(item["label"]) for item in message.get("attachments") or [] if isinstance(item, dict) and item.get("label")]}

    def _respond(self, link: ahp.Connection, job: Job, binding: Dict[str, Any]) -> None:
        """Allow, deny or answer one waiting item of the chat of a task. The session is read again from the host first, and the item must be there, in this chat, and be what the page
        showed (the same `digest`): else nothing is sent. The person confirms one `toolCallId` (or one request), never whatever is pending."""
        plan = job.plan or {}
        with self.lock:
            held = self.sess.get(binding["session"])
            channel = held["channel"] if held else ""
        if held is None or not channel:
            raise Refused("ask-gone")  # the session of the chat could not be read: nothing is answered blind
        try:
            link.unsubscribe(channel)
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError:
            pass
        fresh = ahp.trimmed_session(link.subscribe(channel))
        with self.lock:
            held["state"] = fresh
            self._stamp(held)
        item = chatask.find(fresh["inputNeeded"], str(plan.get("id") or ""))
        if item is None or item.get("chat") != binding["chat"]:
            raise Refused("ask-gone")
        view = chatask.shown(item)
        wanted = "confirm" if job.kind == "confirm" else "question"
        if view is None or view["kind"] != wanted or view["digest"] != plan.get("digest") or view.get("tool_call_id", view.get("request_id")) != plan.get("key"):
            raise Refused("ask-changed")
        if job.kind == "confirm":
            actions, line = [chatask.confirm_action(item, bool(plan.get("approved")))], ""
        else:
            actions, line = chatask.answer_actions(item, plan.get("answers"))  # AnswerError: nothing has been sent yet
        if job.cancelled:
            raise Refused("timeout")
        for action in actions:
            link.dispatch(item["chat"], action)
        with self.lock:
            ahp.reduce_session(held["state"], {"type": "session/inputNeededRemoved", "id": item["id"]})  # the host pushes the same; the page need not show it again
            self._stamp(held)
            held["answered_at"] = time.monotonic()  # the host may still say "input" for a moment: `_reread_waiting` leaves the session alone for REREAD_AFTER_ANSWER
            known = self.sessions.get(binding["session"])
            self.dirty = True
            title = str((known or {}).get("title") or binding.get("title") or "")
        job.result = {"chat": binding["chat"], "title": title, "view": view, "line": line}

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
        self._adopt(entries)
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

    def _adopt(self, entries: List[Dict[str, Any]]) -> None:
        """A chat the board made is bound to its task as soon as the agent has made the task (an open task of that name): `chat.how = "board"`, and the model of the dialog on the task, so that
        the next messages carry it. The first message goes to `.task/sent.jsonl` and the history. A chat whose task never came is let go after `chatnew.KEEP_PENDING`; the SDK binding (the
        session id of the task, found in the chat) still works for it."""
        with self.lock:
            waiting = list(self.created)
        if not waiting:
            return
        by_name = {str(entry.get("name") or ""): entry for entry in entries}
        for made in waiting:
            entry = by_name.get(made["name"])
            if entry is None:
                if time.monotonic() - made["clock"] > chatnew.KEEP_PENDING:
                    self._forget(made)
                continue
            sdk = self.sdk.get(made["session"]) or set()
            if entry.get("session_id") and sdk and entry["session_id"] not in sdk:
                self._forget(made)  # a task of that name, made in another chat: not ours
                continue
            if not self.persist:
                continue
            found = chatlink.adopt(self.root, entry["task"], made)
            if found is None:
                continue
            entry["chat"] = found
            self._forget(made)
            try:
                chatsend.record(self.root, entry["task"], {"at": utc_now(), "task": entry["task"], "kind": "create", "chat": made["chat"], "text": made["text"], "lang": made["lang"],
                                                           "source": made["source"], "model": made["model"] or {}, "permission": made["permission"], "files": made.get("files") or []})
                with task_ops.locked(self.root, entry["task"]) as data:
                    task_ops.note(data, "create", chatsend.summary(made["text"]))
            except Exception:  # noqa: BLE001 - the binding is made; a missing line of history must not undo it
                pass

    def _forget(self, made: Dict[str, Any]) -> None:
        with self.lock:
            self.created = [item for item in self.created if item is not made]

    def _scan(self, link: ahp.Connection, entries: List[Dict[str, Any]], sessions: Dict[str, Dict[str, Any]]) -> None:
        with self.lock:
            done = set(self.bound)
        if not any(entry["session_id"] and entry["task"] not in done and (entry.get("chat") or {}).get("how") != "board" for entry in entries):
            return  # every task that can be bound is: no chat needs reading
        wanted = sorted(sessions.values(), key=lambda item: str(item.get("modifiedAt") or ""), reverse=True)[:SCAN_MAX]
        todo = []
        for item in wanted:
            resource = item["resource"]
            if item.get("defaultChat") in self.chats or not item.get("defaultChat"):
                continue  # a chat held here is left alone: the unsubscribe below would end its updates, and nothing would subscribe it again
            if resource not in self.scanned or (not self.sdk.get(resource) and self.scanned[resource] != item.get("modifiedAt")):
                todo.append(item)
        for item in todo[:SCAN_PER_TURN]:
            resource, chat = item["resource"], item["defaultChat"]
            try:
                ids = ahp.sdk_ids(link.subscribe(chat))
                link.unsubscribe(chat)
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError as error:
                self.host_said(error)
                ids = set()  # this chat cannot be opened now: it is not read again until it changes
            with self.lock:
                self.sdk[resource] = ids
                self.scanned[resource] = str(item.get("modifiedAt") or "")
            self.dirty = True

    def _subscribe(self, link: ahp.Connection) -> None:
        with self.lock:
            wanted = {binding["chat"]: binding["session"] for binding in self.bound.values() if binding.get("chat")}
            wanted.update({item["chat"]: item["session"] for item in self.created})  # a chat the board just made stays subscribed until its task is bound
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
            except ahp.AhpError as error:
                self.host_said(error)
                continue
            with self.lock:
                self.chats[chat] = {"state": state, "tool_at": ""}
                self.problem = ("", 0.0)  # a chat of Copilot was read: Copilot works
        self._subscribe_sessions(link, set(wanted.values()))
        self._reread_waiting(link, set(wanted.values()))

    def _reread_waiting(self, link: ahp.Connection, wanted: Set[str]) -> None:
        """A session whose status says it waits for a person, while we hold no item for it, is read again at once: an action may have come before the session was subscribed. This runs with every look
        (a status change marks the link dirty), so a missed item is found in a turn, not at the next full list."""
        with self.lock:
            stale = [(resource, held["channel"]) for resource, held in self.sess.items()
                     if resource in wanted and held["channel"] and not held["state"].get("inputNeeded")
                     and time.monotonic() - held.get("answered_at", -REREAD_AFTER_ANSWER) >= REREAD_AFTER_ANSWER and ahp.status_name((self.sessions.get(resource) or {}).get("status")) == "input"]
        for resource, channel in stale:
            try:
                state = ahp.trimmed_session(link.subscribe(channel))
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                continue
            with self.lock:
                held = self.sess.get(resource)
                if held is not None and state.get("inputNeeded"):
                    held["state"] = state
                    self._stamp(held)

    def _subscribe_sessions(self, link: ahp.Connection, wanted: Set[str]) -> None:
        """The sessions of the bound chats are subscribed, for `inputNeeded[]`; the others are let go. A session that cannot be read is noted once (no channel) and not tried again until the link is made anew:
        its chat then shows nothing new, and a person answers in VS Code."""
        with self.lock:
            have = dict(self.sess)
        for resource in set(have) - wanted:
            if have[resource]["channel"]:
                try:
                    link.unsubscribe(have[resource]["channel"])
                except ahp.ConnectionClosed:
                    raise
                except ahp.AhpError:
                    pass
            with self.lock:
                self.sess.pop(resource, None)
        for resource in wanted - set(have):
            tail = resource.rsplit("/", 1)[-1]
            held: Dict[str, Any] = {"channel": "", "state": {"inputNeeded": []}, "seen": {}}
            for channel in dict.fromkeys([resource, "ahp-session:/" + tail]):  # the host lists a session under one address and takes the other: both are tried
                try:
                    held["state"] = ahp.trimmed_session(link.subscribe(channel))
                    held["channel"] = channel
                    break
                except ahp.ConnectionClosed:
                    raise
                except ahp.AhpError as error:
                    self.host_said(error)
                    continue
            with self.lock:
                self.sess[resource] = held
                self._stamp(held)
