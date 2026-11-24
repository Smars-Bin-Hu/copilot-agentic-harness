"""The link from the board to the agent host that runs the chats (1.6, B71). One background thread holds the connection and a cache; a page request only reads the cache.

- The thread starts (or adopts) the board's own agent host (`core.agenthost`, 1.8.x: `code agent host`, no VS Code window), connects, hands it gh's token, and lists the chats of Copilot. The root notifications of the host keep the list true; a new list is asked
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
  A chat made to go on with a task that exists (1.6.97, "go on in a new chat") is bound the same way, at the next look: the board does not wait for its agent to answer.
- 1.6.105: the chats of the subagents a bound chat started (`ahp.sub_chat`: a chat of the same session made by one of its tool calls) are subscribed too, the newest `SUB_FOLLOW` (16), and
  the Live tab shows a small summary of each on its tool call (`chatlive.attach_subs`); `sub` gives a subagent's whole chat for the side panel (from memory, else from the stream file).
- B75: the session of each bound chat is subscribed too, for its `inputNeeded[]` (the host pushes `session/inputNeededSet` and `Removed`). `ask_of` gives a task's oldest tool confirmation or question
  (`chatask`; any other kind is ignored). A person's allow, deny or answer is a job (`respond`): the thread reads the session again, refuses when the item is gone or is not what the page showed, then
  dispatches the actions that `chatask` made.
"""

from __future__ import annotations

import copy
import datetime
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core import agenthost, ahp, config, ghauth, launchenv, messages, pace, shortcmd, tasks
from core.paths import utc_now
from core import connections as conn_core

from . import autorun, autorun_relay, autorun_start, chatask, chatctx, chatlink, chatlive, chatnew, chatsend, chatstream, rewind, task as task_ops, tasklife, tasksub

TASKS_EVERY = 3.0  # seconds between two looks at the tasks and their chats
RELIST_EVERY = 180.0  # a whole new list of chats, in case a notification was missed
MODELS_EVERY = 15.0  # the models again: the host says no event when Copilot signs out or in, it only lists none or some
EXPECT_EVERY = 2.0  # a chat the board made that the host does not list yet: asked again this often ...
EXPECT_FOR = 120.0  # ... for this long
SCAN_PER_TURN = 3  # chats read in one turn to find their Copilot session id
SCAN_MAX = 300  # chats read at most, newest first
RESCAN_BUSY = 5.0  # seconds between two reads of a chat that is at work and had no Copilot id when read (1.6.111)
NO_CLI_WAIT = 300.0  # no `code` command: look again only now and then
JOB_WAIT = 25.0  # seconds a page request waits for the thread to send, steer or stop
CREATE_WAIT = 60.0  # a create makes the chat, sends, then waits for the host to list it (1.8.6: 45 before; `createSession` may take ahp.CREATE_TIMEOUT)
REREAD_AFTER_ANSWER = 10.0  # seconds after a person answered in which a session that still says "input" is not read again for a missed item
INITIATOR_WAIT = 10.0  # seconds after the first message in which the host is asked who made the chat
UNDO_WAIT = 12.0  # seconds a Withdraw waits for the turn it stopped to end
ASK_REST = 3  # what the chat waits for past the first, each with a card of its own
SUB_FOLLOW = 16  # chats of subagents followed for each bound chat, the newest: a safety cap, every subagent of a normal turn is followed (1.6.105: 3; B4a: 16)
SLOW_LIMIT = 3  # 1.7.45: calls in a row the host did not answer in time before the connection is given up; one slow answer of a busy computer is not a lost VS Code
SLOW_RETRY = 30.0  # seconds before a list the host did not answer in time is asked again
RELAY_EVERY = 1.0  # 1.8: seconds between two looks at the bound chats of tasks in autorun (relay and pit stop)
RELAY_HOLD = 10.0  # 1.8: seconds a relay that was refused (the chat changed, was not idle) waits before it is tried again
BACKGROUND_TIMEOUT = 120.0  # 1.8.7: seconds a read of the background lane waits (a busy computer); a read that runs out is made again on the next look, and its late answer is only noted
PERSON_LANES = 3  # 1.8.7: threads of the person's lane: a job that waits on one task does not hold up the others
GATE_WAIT = 10.0  # 1.8.7: seconds a job waits for another job on the same task before it is refused (the page says the chat is busy)
PERSON_POLL = 0.5  # 1.8.7: seconds the person's lane waits for a job before it looks whether the connection is still there
FRESH_TURN = 30.0  # 1.8.7: seconds a turn the board itself started counts as running, whatever a slow list of sessions still says (a second send to that chat is refused)
STAGE_SLOW = 180.0  # 1.8.7: seconds after which "being created" says VS Code has not answered for a while (it still waits)
OPEN_WAIT = 3.0  # 1.8.x: seconds one try to open waits for the board's own agent host to be ready; it is tried again every HOST_POLL while it starts
HOST_POLL = 1.0
MODELS_QUICK = 2.0  # 1.8.x: seconds between two reads of the models for a while after a GitHub token was handed (they come a few seconds later)
QUICK_FOR = 45.0
KEEP_SHOWN = 120.0  # 1.7.45: seconds the rows keep the chat they showed after the connection went away, while it comes back and the chats are found again, so a task does not flash idle


def enabled_by_policy(root: Path) -> bool:
    return (config.policy_or_empty(root, "task").get("board") or {}).get("vscode", True) is not False


def elapsed_ms(started: Any) -> int:
    """Milliseconds since a turn began (`startedAt`, an ISO time); the host wants a number, and a turn whose start is not readable gets 1000."""
    try:
        begun = datetime.datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        return max(1, int((datetime.datetime.now(datetime.timezone.utc) - begun).total_seconds() * 1000))
    except (ValueError, TypeError):
        return 1000


def turn_at(turns: List[Dict[str, Any]], at: Any) -> Optional[int]:
    """The place of the turn a person started that matches a restore point taken at `at` (seconds): the hook takes it a moment after the message was sent. None: no such turn."""
    if not isinstance(at, (int, float)):
        return None
    near = []
    for index, turn in enumerate(turns):
        message = turn.get("message") if isinstance(turn.get("message"), dict) else {}
        if (message.get("origin") or {}).get("kind") != "user":
            continue
        try:
            started = datetime.datetime.fromisoformat(str(turn.get("startedAt")).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        gap = at - started
        if -rewind.MATCH_BEFORE <= gap <= rewind.MATCH_AFTER:
            near.append((abs(gap), index))
    return min(near)[1] if near else None


def chat_state(summary: Dict[str, Any], cached: Dict[str, Any]) -> str:
    """The state of a bound chat: the session's status bits, except that a chat whose last turn ended in an error and runs none is `error` (1.8.5).
    The list of sessions can still say idle or busy then (seen on a work computer: the task stayed "working" after an error), while the chat itself has the error."""
    state = ahp.status_name(summary.get("status"))
    if state in ("idle", "busy", "unknown") and cached.get("state") and ahp.last_error(cached["state"]):
        return "error"
    return state


class Refused(Exception):
    """A send, steer or stop that was not done, and why (`why` is a key of `send.refused.*`): off, not-ready, unbound, unsure, changed, not-idle, not-busy, no-turn, timeout."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


class Guarded:
    """The connection as one job of the person's lane sees it (1.8.7): a job whose page stopped waiting (`cancelled`) sends nothing more, so the page that said "nothing was sent" was right."""

    def __init__(self, link: Any, job: "Job") -> None:
        self._link, self._job = link, job

    def dispatch(self, channel: str, action: Dict[str, Any]) -> None:
        if self._job.cancelled:
            raise Refused("timeout")
        self._link.dispatch(channel, action)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._link, name)


class Job:
    """One thing for the thread to do to a chat. The page request waits on `done`."""

    def __init__(self, kind: str, task: str, text: str = "", model: Optional[Dict[str, Any]] = None, plan: Optional[Dict[str, Any]] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> None:
        self.kind, self.task, self.text, self.model, self.plan, self.attachments = kind, task, text, model, plan, attachments
        self.done = threading.Event()
        self.cancelled = False
        self.result: Dict[str, Any] = {}
        self.error: Optional[BaseException] = None


# "": any state: a setting of the chat holds from its next turn; a Withdraw stops a running turn first (1.6.99); Try again and taking back a queued message are checked by the thread
NEEDS = {"send": "idle", "steer": "busy", "queue": "busy", "stop": "busy", "confirm": "input", "answer": "input", "say": "input", "config": "", "undo": "", "resume": "", "unqueue": "", "rewind": "idle", "relay": "", "super": "", "bgstop": ""}  # bgstop (B16): stop a shell that runs in the background; relay (1.8, autorun): the board wakes the agent or sends `/compact`; the chat must be idle or in error, which `_do` checks


class VsLink:
    def __init__(self, root: Path, enabled: bool = True, opener: Optional[Callable[[], ahp.Connection]] = None, persist: bool = True,
                 turn: float = 1.0, backoff: Optional[ahp.Backoff] = None) -> None:
        self.root = root
        self.enabled = enabled
        self.persist = persist
        self.stream_lost = 0  # records of the task streams (`chatstream`) a failed write left out; the chat goes on
        self.turn = turn
        self.backoff = backoff or ahp.Backoff()
        self._opener = opener or self._open  # a test gives its own (a fake host); the board opens its own agent host
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.wake = threading.Event()
        self.jobs: "queue.Queue[Any]" = queue.Queue()  # "auth", or a Job
        self.thread: Optional[threading.Thread] = None
        self.ready = False
        self.down_at = 0.0  # monotonic time the link first failed to reach the host since it was last connected; 0 when connected (`harness speed`)
        self.losses = 0  # how many times a working link went away: VS Code was closed, however soon it came back
        self.why = "off" if not enabled else "starting"
        self.sessions: Dict[str, Dict[str, Any]] = {}  # the chats of this folder, by resource
        self.everywhere: Dict[str, Dict[str, Any]] = {}  # every chat the host lists, of any folder: resource -> {title, status}. VS Code asks before it quits for one that runs or waits (`veto.chat`)
        self.sdk: Dict[str, Set[str]] = {}
        self.scanned: Dict[str, str] = {}  # resource -> modifiedAt when it was read for its Copilot id
        self.read_at: Dict[str, float] = {}  # resource -> when it was read with no error (monotonic)
        self.bound: Dict[str, Dict[str, Any]] = {}  # task -> binding
        self.unbound: Dict[str, str] = {}  # task -> why
        self.chats: Dict[str, Dict[str, Any]] = {}  # chat resource -> {state, tool_at}
        self.sub_seen: Dict[str, str] = {}  # id of an item in a subagent's chat -> when first seen (the start of its wait)
        self.sess: Dict[str, Dict[str, Any]] = {}  # session resource of a bound chat -> {channel, state (trimmed: inputNeeded), seen: {item id: when first seen}}
        self.limits: Dict[str, Dict[str, int]] = {}  # model id -> what decides its context window, every model the host lists (for the context meter)
        self.models: List[Dict[str, Any]] = []  # what a person may pick (`ahp.models_of`); empty until the host said
        self.list_asked = 0.0  # 1.8.7: when the list in place was asked for
        self.gates: Dict[str, threading.RLock] = {}  # 1.8.7: one per task: what is sent to a task's chat goes one at a time, whichever lane sends it
        self.just_sent: Dict[str, Tuple[str, float, str]] = {}  # 1.8.7: chat -> (the turn the board started, when, its session); gone when VS Code says anything new of it
        self.super_making = False  # 1.8.7: the super agent chat is being made (no limit): a second is not made beside it
        self.created: List[Dict[str, Any]] = []  # chats this board made whose task does not exist yet (`chatnew.pending`); memory only
        self.expect: Dict[str, Dict[str, Any]] = {}  # session resource of a chat this board made that the host has not listed yet -> {stub, until}; memory only
        self.listed_at = 0.0
        self.dirty = True
        self.slow = 0  # calls in a row the host did not answer in time (SLOW_LIMIT)
        self.shown: Dict[str, Dict[str, Any]] = {}  # task -> what its row showed of the chat when the connection went away (KEEP_SHOWN)
        self.lost_at = 0.0
        self.relay_at = 0.0  # monotonic time of the last look at the autorun chats
        self.relay_hold: Dict[str, float] = {}  # task -> monotonic time before which its relay is not tried again
        self.starts: Dict[str, Dict[str, Any]] = {}  # 1.8 step 9: task -> the Start order of the board (`autorun_start`), done here on the thread; memory only
        self.start_at = 0.0  # monotonic time of the last look at the Start orders
        self.super_chat: Optional[Dict[str, str]] = None  # 1.8.1: the super agent chat the board owns ({session, chat}); it is kept subscribed while set; memory only (`superbrain` keeps it in a file)
        self.follow: Dict[str, Dict[str, Any]] = {}  # 1.8.2: task -> the second message of a chat made for a skill only a person starts (`chatnew.follow_up`), sent when the first turn is over; memory only
        self.follow_at = 0.0
        self.own: Optional[agenthost.Host] = None  # 1.8.x: the board's own agent host (made at the first open)
        self.signin: Dict[str, Any] = {"state": "", "login": "", "at": 0.0}  # 1.8.x: the last hand-over of gh's token: handed, no-gh, not-signed-in, cannot-run, slow, refused
        self.models_quick_until = 0.0
        self.gh_login: Optional[ghauth.Login] = None  # 1.8.x: the sign-in the Enter page started (`gh auth login --web`)
        self.gh_login_handed = False

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

    def drops(self) -> int:
        with self.lock:
            return self.losses

    def status(self) -> Dict[str, Any]:
        """`{ready, bound, unbound, why}`: for `/api/status` and `/api/board`. `bound` and `unbound` count the open tasks."""
        with self.lock:
            return {"ready": self.ready, "bound": len(self.bound) if self.ready else 0, "unbound": len(self.unbound) if self.ready else 0, "why": "ok" if self.ready else self.why}

    def copilot(self) -> Dict[str, Any]:
        """For the Enter screen, from the cache: how many models the host lists (those the policy allows)."""
        with self.lock:
            return {"models": len(self.models) if self.ready else 0}

    def chat_of(self, task: str, name: str = "") -> Dict[str, Any]:
        """What a row or a task page shows of the chat: `{bound, why, state, title, model, how}` and, when the chat said something, `sub` and `recent`.
        Shortly after the connection went away (KEEP_SHOWN), a chat that is not found again yet is shown as it was, with `kept: true` (1.7.45)."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding:
                if task in self.shown and time.monotonic() - self.lost_at < KEEP_SHOWN:
                    return dict(self.shown[task], kept=True)
                return {"bound": False, "why": self.unbound.get(task, "") if self.ready else self.why}
            summary = self.sessions.get(binding["session"]) or {}
            cached = self.chats.get(binding["chat"]) or {}
            out: Dict[str, Any] = {"bound": True, "how": binding.get("how", ""), "title": str(summary.get("title") or binding.get("title") or ""), "state": chat_state(summary, cached)}
            if cached.get("state"):
                if out["state"] == "error":
                    out["error"] = ahp.last_error(cached["state"])  # 1.8.4: what the last turn failed with, and whether Try again can run it (the super view)
                found = tasksub.facts(cached["state"], self.root)
                out["model"] = found["model"]
                out["model_name"] = next((str(item.get("name") or "") for item in self.models if item.get("id") == found["model"]), "")  # as the pickers call it; not listed: the page falls back on the id
                if found["busy"] and found["started"]:
                    out["started_at"] = found["started"]  # the run time of the latest turn is counted by the page, only while it runs
                out["context"] = chatctx.meter(cached["state"], self.limits)  # None: unknown, shown empty
                out["effort"] = chatctx.effort(cached["state"], found["model"])  # only what a message said; None: not known
                out["fusion"] = chatctx.fusion(cached["state"])
                out["window"] = chatctx.capacity(found["model"], self.limits, chatctx.chosen_size(cached["state"], found["model"]))  # None: not listed
                sub = tasksub.sub_of(found, cached.get("tool_at", "") if found["busy"] else "")
                if sub:
                    out["sub"] = sub
                if found["reply"]:
                    out["recent"] = tasksub.recent_text(found["reply"])
            return out

    def live(self, task: str, last: str = "", have: int = -1) -> Dict[str, Any]:
        """For the Live tab of an open task, from the cache only (no file, no call to the host): `{rev, n, bound, why | state, started, now, items, more, before}`. `last` is the `rev` the page already has:
        when nothing changed the answer is only `{rev, same: true}`. `task` is the folder name of the task. The items are those of the last turn, all of them (`chatlive.build`); `n` is the number of
        the chat's last change, which the page sends back as `have`: an item that has not changed since is then a stub (`{id, k, same: true}`). `before`: where the steps that fell out of memory
        begin (`older` gives them), else None."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding and last and task in self.shown and time.monotonic() - self.lost_at < KEEP_SHOWN:
                return {"rev": last, "same": True}  # 1.7.45: the connection came and goes: the page keeps what it shows for a while
            if not binding:
                why = self.unbound.get(task, "") if self.ready else self.why
                rev = "x:" + why
                return {"rev": rev, "same": True} if rev == last else {"rev": rev, "bound": False, "why": why}
            cached = self.chats.get(binding["chat"])
            state = chat_state(self.sessions.get(binding["session"]) or {}, cached or {})
            subs = self._subs_of(binding)
            steps = ",".join(f"{sub['call']}.{(self.chats.get(sub['chat']) or {}).get('rev', -1)}.{sub.get('status')}" for sub in subs)  # a subagent's step changes the answer too
            rev = f"{binding['chat']}:{cached.get('rev', 0) if cached else -1}:{state}:{steps}"
            if rev == last:
                return {"rev": rev, "same": True}
            if cached is None:  # bound, the chat is being read
                return {"rev": rev, "bound": True, "state": state, "now": int(time.time() * 1000), "items": [], "more": False, "started": "", "before": None, "turn": "", "loading": True}
            number = cached.get("rev", 0)
            if not last.startswith(binding["chat"] + ":"):
                have = -1  # the page last saw another chat (the task was bound again) or nothing: no item of this chat is on it
            found = chatlive.build(cached["state"], cached.get("marks") or {}, self.root, cached.setdefault("memo", {}), have, number, {sub["call"] for sub in subs})  # a call with a subagent is whole: `sub` goes on it
            chatlive.attach_subs(found["items"], [(sub, self.chats.get(sub["chat"])) for sub in subs], self.root, cached["state"])
            # `queued`: the messages that go after the running turn; `retry`: the last turn ended in an error that Try again can run again (1.6.99)
            return {"rev": rev, "n": number, "bound": True, "state": state, "now": int(time.time() * 1000), **found, "queued": ahp.queued(cached["state"]), "retry": bool(ahp.resumable_turn(cached["state"])),
                    "round": chatlive.round_facts(cached["state"]),  # B9: the live numbers of the title of the round
                    "activity": cached["state"].get("activity") or "", "background": list(cached["state"].get("backgroundWork") or [])}  # B15, B16

    def older(self, task: str, turn: str, before: int, count: int = 60) -> Dict[str, Any]:
        """The steps of the turn `turn` that came before part `before` (the `before` of `live`), from the task's stream file: `{items, before}`, the newest `count` of them, oldest first. `before`: where
        the next older ones end (`{turn, i}`), None when nothing older is left. The person's own message is among the items only when the first part of the turn is. A task that is not bound, a turn
        the file does not hold, a file that cannot be read: `{items: [], before: None}`. Never raises; the file is read after the lock is let go."""
        nothing: Dict[str, Any] = {"items": [], "before": None}
        try:
            with self.lock:
                binding = self.bound.get(task) if self.ready else None
                chat = str(binding["chat"]) if binding else ""
            if not chat or not isinstance(turn, str) or not isinstance(before, int) or isinstance(before, bool):
                return nothing
            found = next((item for item in chatstream.read(self.root, task, chat)["turns"] if item["id"] == turn and not item.get("sub")), None)
            if found is None:
                return nothing
            parts = found["parts"]
            earlier = [part for part in parts if part["i"] < before]
            chosen = earlier[-max(1, int(count)):]
            if not chosen:
                return nothing
            view: Dict[str, Any] = {"id": found["id"], "parts": chosen}
            if chosen[0] is parts[0]:  # the start of the turn: what the person said goes with it
                view.update(text=found["text"], files=found["files"])
            marks = {}  # the times are in the parts themselves
            more = len(earlier) > len(chosen)
            return {"items": chatlive.items_of(view, False, marks, self.root), "before": {"turn": found["id"], "i": chosen[0]["i"]} if more else None}
        except Exception:  # a page's question must not break the link
            return nothing

    def call(self, task: str, turn: str, ident: str, sub: str = "") -> Dict[str, Any]:
        """What an opened tool call shows (`chatlive.detail`): the call with tool call id `ident` in turn `turn` of the task's chat. The board's memory first (the part is copied out under the lock, the detail
        is built after it), else the task's stream file (read after the lock is let go). `sub`: the id of the tool call of the main chat that started a subagent: the call is then looked for in that
        subagent's chat (memory when it is followed, else the turns of the stream file with that `sub.call`; works for a task that is closed or not bound). Without `sub` a call of a subagent's chat is not looked
        for. Not found, any failure: `{}`. Never raises."""
        try:
            if not isinstance(turn, str) or not isinstance(ident, str) or not ident or not isinstance(sub, str):
                return {}
            held: Optional[Dict[str, Any]] = None
            chat = ""
            with self.lock:
                binding = self.bound.get(task) if self.ready else None
                parent = str(binding["chat"]) if binding else ""
                chat = parent
                if sub:
                    chat = next((str(item["chat"]) for item in self._all_subs(binding) if item.get("call") == sub), "") if binding else ""
                state = (self.chats.get(chat) or {}).get("state") if chat else None
                if isinstance(state, dict):
                    for one in chatlive.all_turns(state):
                        if str(one.get("id") or "") == turn:
                            part = next((part for part in one.get("responseParts") or [] if chatlive.part_id(part) == ident and isinstance(part, dict) and isinstance(part.get("toolCall"), dict)), None)
                            if part is not None:
                                held = dict(part["toolCall"])
                                if isinstance(part.get("_meta"), dict) and not isinstance(held.get("_meta"), dict):
                                    held["_meta"] = part["_meta"]
            if held is not None:
                return chatlive.detail(held, self.root)
            if sub:
                found = next((item for item in self._sub_turns(task, sub, parent) if item["id"] == turn), None)
            else:  # the bound chat's turns; a task that is not bound (closed, C1): a turn of any of its chats
                found = next((item for item in chatstream.read(self.root, task, chat or None)["turns"] if item["id"] == turn and not item.get("sub")), None)
            for part in (found["parts"] if found else []):
                if chatlive.part_id(part) == ident and isinstance(part.get("toolCall"), dict):
                    return chatlive.detail(part["toolCall"], self.root)
            return {}
        except Exception:  # a page's question must not break the link
            return {}

    def receipt(self, task: str, turn: str) -> Dict[str, Any]:
        """The receipt of turn `turn` of the task's chat, once it ended (B6): `chatlive.receipt` (calls, files with their lines and call ids) and `{turn, at, ms, ctx, credits}`. `at`: when it began;
        `ms`: how long it took (the host's duration); `ctx`: `{from, to}`, the percent of the context window after the turn before and after this one (`from` is 0 for the chat's first turn,
        None when not known); `credits`: what the session's total grew by in this turn, None when the host did not say for both. From memory when the turn is there whole; when its parts fell out
        of memory (`dropped`) or it is gone, from the task's stream file (read after the lock is let go: there `credits` is None and `ctx` only when the window is known). A turn that runs, one
        not found, any failure: `{}`. Kept per chat and turn: a turn that ended does not change. Never raises."""
        try:
            if not isinstance(turn, str) or not turn:
                return {}
            with self.lock:
                binding = self.bound.get(task) if self.ready else None
                chat = str(binding["chat"]) if binding else ""
                cached = self.chats.get(chat) if chat else None
                if cached is None:
                    return {}
                kept = cached.setdefault("receipts", {})
                if turn in kept:
                    return dict(kept[turn])
                state = cached["state"]
                active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
                if active and str(active.get("id") or "") == turn:
                    return {}
                turns = [one for one in state.get("turns") or [] if isinstance(one, dict)]
                at = next((n for n, one in enumerate(turns) if str(one.get("id") or "") == turn), -1)
                held = turns[at] if at >= 0 else None
                before = turns[at - 1] if at > 0 else None
                first = at == 0 and len(turns) == 1  # the memory keeps the last two turns: one alone is the chat's first
                parts = [dict(part) for part in held.get("responseParts") or [] if isinstance(part, dict)] if held and not held.get("dropped") else None
                limits = dict(self.limits)
                state_copy = {"turns": [dict(one) for one in turns], "activeTurn": active}
            usage = held.get("usage") if held else None
            started, length = (held.get("startedAt"), held.get("duration")) if held else ("", None)
            if parts is None:  # not whole in memory: the file has every part
                found = next((one for one in chatstream.read(self.root, task, chat)["turns"] if one["id"] == turn and not one.get("sub")), None)
                if found is None or not found.get("state"):
                    return {}
                parts = found["parts"]
                usage = usage or found.get("usage")
                started = started or found.get("at")
                length = length if length is not None else found.get("duration")
            out = chatlive.receipt(parts, self.root)
            after = chatctx.percent_of(usage, state_copy, limits)
            prior = chatctx.percent_of(before.get("usage"), state_copy, limits) if before else (0.0 if first else None)
            spent_now = chatctx.session_total(usage)
            spent_then = chatctx.session_total(before.get("usage")) if before else (0.0 if first else None)
            out.update(turn=turn, at=str(started or ""), ms=length if isinstance(length, (int, float)) and not isinstance(length, bool) and length >= 0 else None,
                       ctx={"from": prior, "to": after} if after is not None else None,
                       credits=round(max(0.0, spent_now - spent_then), 2) if spent_now is not None and spent_then is not None else None)
            with self.lock:
                again = self.chats.get(chat)
                if again is not None:
                    store = again.setdefault("receipts", {})
                    store[turn] = out
                    while len(store) > 8:
                        store.pop(next(iter(store)))
            return dict(out)
        except Exception:  # a page's question must not break the link
            return {}

    def turn_items(self, task: str, turn: str) -> Dict[str, Any]:
        """(C1) The whole of one turn of the task's chats as Live items, for the Agent actions tab: `{items, turn}`. From the board's memory when the turn is there whole, else from the task's
        stream file (any of its chats: the task need not be bound or open). Not found, any failure: `{items: [], turn}`. Never raises; the file is read after the lock is let go."""
        nothing: Dict[str, Any] = {"items": [], "turn": turn if isinstance(turn, str) else ""}
        try:
            if not isinstance(turn, str) or not turn:
                return nothing
            with self.lock:
                binding = self.bound.get(task) if self.ready else None
                state = (self.chats.get(str(binding["chat"])) or {}).get("state") if binding else None
                held = None
                if isinstance(state, dict):
                    held = next((dict(one) for one in chatlive.all_turns(state) if str(one.get("id") or "") == turn and not one.get("dropped") and one is not state.get("activeTurn")), None)
                    marks = dict((self.chats.get(str(binding["chat"])) or {}).get("marks") or {})
            if held is not None:
                return {"items": chatlive.items_of(held, False, marks, self.root), "turn": turn}
            found = next((one for one in chatstream.read(self.root, task)["turns"] if one["id"] == turn and not one.get("sub")), None)
            if found is None:
                return nothing
            return {"items": chatlive.items_of(found, False, {}, self.root), "turn": turn}
        except Exception:  # a page's question must not break the link
            return nothing

    def _whole_turn(self, task: str, turn: str) -> Optional[Dict[str, Any]]:
        """Turn `turn` of the task's chats with every part, for a search (B20): from memory when it holds the turn whole; else the task's stream file (the bound chat, else any of the task's), with
        the parts memory has and the file not yet (the newest of a turn that runs) after them. None when neither has it. The parts are copied under the lock; the file is read after it."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            chat = str(binding["chat"]) if binding else ""
            state = (self.chats.get(chat) or {}).get("state") if chat else None
            held = None
            if isinstance(state, dict):
                one = next((one for one in chatlive.all_turns(state) if str(one.get("id") or "") == turn), None)
                if one is not None:
                    held = dict(one, responseParts=[dict(part) for part in one.get("responseParts") or [] if isinstance(part, dict)])
        if held is not None and not held.get("dropped"):
            return held
        found = next((one for one in chatstream.read(self.root, task, chat or None)["turns"] if one["id"] == turn and not one.get("sub")), None)
        if found is None:
            return held
        known = {chatlive.part_id(part) for part in found["parts"]}
        extra = [part for part in (held or {}).get("responseParts") or [] if chatlive.part_id(part) and chatlive.part_id(part) not in known]
        view = dict(found, parts=list(found["parts"]) + extra)
        if held is not None and isinstance(held.get("message"), dict):
            view["message"] = held["message"]
        return view

    def find(self, task: str, turn: str, query: str) -> Dict[str, Any]:
        """(B20) Where `query` is in turn `turn` of the task's chat, every part of it, also those memory let go of: `chatlive.search` and `{turn}`. Not found, any failure: no hit. Never raises."""
        nothing: Dict[str, Any] = {"hits": [], "more": False, "turn": turn if isinstance(turn, str) else ""}
        try:
            if not isinstance(turn, str) or not turn or not isinstance(query, str):
                return nothing
            whole = self._whole_turn(task, turn)
            if whole is None:
                return nothing
            return dict(chatlive.search(whole, query, self.root), turn=turn)
        except Exception:  # a page's question must not break the link
            return nothing

    def counts(self, task: str, turn: str, before: int) -> Dict[str, Any]:
        """(B19) How many of the steps of turn `turn` before part `before` (those the page has not loaded) are in each filter: `chatlive.facets`, with `{turn, before}`. Those steps are over: they do
        not change, so the page asks once per place. Never raises."""
        try:
            found = self.older(task, turn, before, 1000000) if isinstance(before, int) and not isinstance(before, bool) and before > 0 else {"items": []}
            return dict(chatlive.facets(found["items"]), turn=turn, before=before)
        except Exception:  # a page's question must not break the link
            return dict(chatlive.facets([]), turn=turn, before=before)

    def sub(self, task: str, call: str, have: int = -1) -> Dict[str, Any]:
        """The whole chat of the subagent that tool call `call` of the task's chat started, for the side panel (B4a): `{call, title, st, items, turn, n, usage: {calls, ms?}}`. `items`: all the items of all the
        turns of that chat in order (`chatlive.build_all`), the first of each turn is the prompt the subagent was given (kind `me`). `st`: `run`, `wait`, `done` or `fail` (as on the call's summary); `turn`: the id
        of the last turn (the page opens a call with it: `call(..., sub=call)`); `n`: the number of the chat's last change, which the page sends back as `have`: from memory an item not changed since is
        a stub `{id, k, same: true}` (as in `live`; the memo is kept on the subagent's own cache entry). From memory when the chat is followed and holds all of its parts; else from the task's stream file (turns with
        that `sub.call`, the bound chat as `parent` when known, else any): then the items are whole and `n` is -1. A chat whose memory dropped parts (`dropped`) is read from the file whole, its
        state still from memory. The task need not be bound or open. `usage.calls`: tool calls counted; `ms`: the turns' durations the host or the file knows. Unknown call or any failure: `{}`. Never raises; the file is
        read after the lock is let go."""
        try:
            if not isinstance(task, str) or not isinstance(call, str) or not call:
                return {}
            have = have if isinstance(have, int) and not isinstance(have, bool) else -1
            out: Optional[Dict[str, Any]] = None
            parent, title, known = "", "", ""  # `known`: the state memory gives (run, wait, done, fail); empty: the chat is not in memory
            with self.lock:
                binding = self.bound.get(task) if self.ready else None
                if binding:
                    parent = str(binding["chat"])
                    entry = next((item for item in self._all_subs(binding) if item.get("call") == call), None)
                    title = str((entry or {}).get("title") or "")
                    held = self.chats.get(entry["chat"]) if entry else None
                    if held is not None and isinstance(held.get("state"), dict):
                        main = (self.chats.get(parent) or {}).get("state") or {}
                        mine = next((one for turn in chatlive.all_turns(main) for ident, one in chatlive._calls_of(turn) if ident == call), None)
                        known = chatlive.sub_status(held["state"], chatlive.state_of(mine, bool(main.get("activeTurn"))) if mine else "")
                        number = held.get("rev", 0)
                        built = chatlive.build_all(held["state"], held.get("marks") or {}, self.root, held.setdefault("memo", {}), have, number)
                        if built["items"] and not built["dropped"]:
                            out = {"call": call, "title": title, "st": known, "items": built["items"], "turn": built["turn"], "n": number, "usage": self._sub_usage(chatlive.all_turns(held["state"]))}
            if out is not None:
                return out
            turns = self._sub_turns(task, call, parent)
            if not turns:
                return {}
            st = known or ("fail" if turns[-1]["state"] == "error" else "done")  # no memory: nothing runs (a turn of the file that never ended was cut off with the board)
            items: List[Dict[str, Any]] = []
            for at, one in enumerate(turns):
                items.extend(chatlive.items_of(one, known in ("run", "wait") and at == len(turns) - 1, {}, self.root))
            return {"call": call, "title": title, "st": st, "items": items, "turn": turns[-1]["id"], "n": -1, "usage": self._sub_usage(turns)}
        except Exception:  # a page's question must not break the link
            return {}

    @staticmethod
    def _sub_usage(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """`{calls, ms?}` of the turns of a subagent's chat, from memory (`responseParts`) or from the file (`parts`): the tool calls and the durations the host gave."""
        calls = sum(1 for one in turns for part in (one.get("responseParts") if isinstance(one.get("responseParts"), list) else one.get("parts") or []) if isinstance(part, dict) and part.get("kind") == "toolCall")
        took = sum(int(one["duration"]) for one in turns if isinstance(one.get("duration"), (int, float)) and not isinstance(one.get("duration"), bool))
        return {"calls": calls, **({"ms": took} if took > 0 else {})}

    def _sub_turns(self, task: str, call: str, parent: str = "") -> List[Dict[str, Any]]:
        """The turns of the stream file that a subagent worked in, the one chat whose turns say `sub.call == call` (the turns of `parent`'s task chat first when it is known and has one, else any chat), oldest first.
        Reads the file: not under the lock."""
        found = [one for one in chatstream.read(self.root, task)["turns"] if isinstance(one.get("sub"), dict) and one["sub"].get("call") == call]
        chats = [one["chat"] for one in found if parent and one["sub"].get("parent") == parent] or [one["chat"] for one in found]
        return [one for one in found if one["chat"] == chats[0]] if chats else []

    def _all_subs(self, binding: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Every chat of a subagent the session lists for the bound chat (followed or not). The caller holds the lock."""
        held = self.sess.get(binding["session"]) or {}
        return [item for item in (held.get("state") or {}).get("subchats") or [] if item.get("parent") == binding["chat"]]

    def _subs_of(self, binding: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The chats of the subagents the bound chat started, the newest `SUB_FOLLOW`, as the session says. The caller holds the lock."""
        held = self.sess.get(binding["session"]) or {}
        return [item for item in (held.get("state") or {}).get("subchats") or [] if item.get("parent") == binding["chat"]][-SUB_FOLLOW:]

    def _sub_targets(self, binding: Dict[str, Any]) -> List[Dict[str, str]]:
        """The subagent calls that run now in the bound chat, with the chat of each subagent (1.8): from the running `task` calls of the chat's turn (`chatask.sub_calls`), and the chats the session
        lists for a call that still runs. `{chat, agent, call}`. A call that ended is not here: its chat is let go at the next look. The caller holds the lock."""
        main = self.chats.get(binding["chat"])
        if not main:
            return []
        found = chatask.sub_calls(main["state"])
        running = {str(call.get("toolCallId")) for call in self._running_calls(main["state"]) if call.get("status") in chatask.RUNNING}
        for sub in self._subs_of(binding):  # the session says which chat a call made (`origin`); the call must still run in the chat of the task
            if sub["call"] in running and all(item["chat"] != sub["chat"] for item in found):
                found.append({"chat": sub["chat"], "agent": chatask.one_line(sub.get("title") or "", 60), "call": sub["call"]})
        return found

    @staticmethod
    def _running_calls(state: Dict[str, Any]) -> List[Dict[str, Any]]:
        active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else {}
        return [part["toolCall"] for part in active.get("responseParts") or [] if isinstance(part, dict) and isinstance(part.get("toolCall"), dict)]

    def _sub_items(self, binding: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The tool calls that wait for a confirmation in the chats of the running subagents, as items (`chatask.sub_item`). The caller holds the lock."""
        items = []
        for target in self._sub_targets(binding):
            cached = self.chats.get(target["chat"])
            item = chatask.sub_item(target["chat"], target["agent"], cached["state"]) if cached else None
            if item:
                items.append(item)
        return items

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

    def running_chats(self) -> List[Dict[str, str]]:
        """The chats VS Code would ask about when it quits (`veto.chat`): the host lists them as running or as waiting for the person, in any folder, not only the chats of tasks. From the cache; empty when the link is not up.
        `{title, state (busy | input), task}`: `task` is the folder of the open task the chat is bound to, else empty."""
        with self.lock:
            if not self.ready:
                return []
            owner = {binding["session"]: task for task, binding in self.bound.items()}
            out = []
            for resource, summary in self.everywhere.items():
                state = ahp.status_name(summary.get("status"))
                if state in ("busy", "input"):
                    out.append({"title": str(summary.get("title") or ""), "state": state, "task": owner.get(resource, "")})
            return out

    def waiting_names(self) -> List[str]:
        """The names of the tasks the board made a chat for and whose task is not there yet."""
        with self.lock:
            return [item["name"] for item in self.created]

    def making(self) -> List[Dict[str, Any]]:
        """The tasks the board made a chat for that are not there yet, for the board's placeholders, oldest first (1.8.5): `{name, kind, since, stage, stage_since, slow, error}`.
        `stage` (1.8.7): `asking` (VS Code is making the chat), `sent` (made, the first message went), `opening` (VS Code lists it: its first turn runs), `refused` (with `error`),
        `lost` (the connection went before VS Code answered: picked up again when it comes back). `slow`: `asking` for longer than STAGE_SLOW."""
        now = time.monotonic()
        with self.lock:
            out = []
            for item in self.created:
                stage = str(item.get("stage") or "sent")
                if stage == "sent" and item.get("session") and item["session"] not in self.expect and item["session"] in self.sessions:
                    stage = "opening"
                out.append({"name": str(item.get("name") or ""), "kind": str(item.get("kind") or ""), "since": str(item.get("made_at") or ""), "stage": stage,
                            "stage_since": str(item.get("stage_at") or item.get("made_at") or ""), "slow": stage == "asking" and now - float(item.get("stage_clock") or now) > STAGE_SLOW,
                            "error": str(item.get("error") or ""), "initiator": str(item.get("initiator") or "")})
            return out

    def made_stage(self, name: str) -> str:
        """1.8.7: how far the chat the board is making for the task `name` is (`asking`, `sent`, ...), or "" when none is being made."""
        with self.lock:
            found = [item for item in self.created if item.get("name") == name]
            return str(found[-1].get("stage") or "") if found else ""

    def dismiss_making(self, name: str) -> bool:
        """Take away a task being made that VS Code refused, or whose connection went before VS Code answered (1.8.7, the × of its placeholder). One that is being asked cannot be taken away."""
        with self.lock:
            found = [item for item in self.created if item.get("name") == name and item.get("stage") in ("refused", "lost")]
            self.created = [item for item in self.created if item not in found]
            return bool(found)

    def _stage(self, made: Dict[str, Any], stage: str, error: str = "") -> None:
        with self.lock:
            made.update(stage=stage, stage_at=utc_now(), stage_clock=time.monotonic(), error=error)
            self.dirty = True

    def turn_mark(self, task: str) -> Tuple[str, str, str]:
        """1.8.5: where the chat of `task` stands, to tell that a new turn began after the board sent something: (chat, id of the last turn, id of the running turn). Empty parts: not known."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            if not binding:
                return ("", "", "")
            state = (self.chats.get(binding["chat"]) or {}).get("state") or {}
            turns = [turn for turn in state.get("turns") or [] if isinstance(turn, dict)]
            active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else {}
            return (str(binding["chat"]), str(turns[-1].get("id") or "") if turns else "", str(active.get("id") or ""))

    def create_blocked(self) -> str:
        """Why a chat cannot be made now (`off`, `not-ready`), from the cache. Empty: it can."""
        with self.lock:
            return "off" if not self.enabled else "" if self.ready else "not-ready"

    def create(self, plan: Dict[str, Any], text: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Make a chat for the task of `plan` and send `text` to it, on a thread of its own, with no time limit (1.8.7): a VS Code that answers late still gets its first message,
        so no empty chat is left. A chat for a task (`plan["name"]`) is handed over and this returns at once: `{session, pending: True}`; the board's "being created" shows how it
        goes (`making`). A chat with no task (a one-click skill) is waited for as before: {session, chat, initiator, turn}, or Refused (`off`, `not-ready`, `timeout`) or the host's
        error; after `timeout` it still goes on."""
        why = self.create_blocked()
        if why:
            raise Refused(why)
        resource = "ahp-session:/" + str(uuid.uuid4())
        made = {"name": plan["name"], "kind": plan["kind"], "source": plan["source"], "lang": plan["lang"], "permission": plan["permission"], "model": plan["model"], "text": text,
                "files": chatsend.listed(attachments or []), "session": resource, "chat": "", "title": "", "made_at": utc_now(), "clock": time.monotonic(),
                "keep_model": plan.get("keep_model", True), "then": plan.get("then") or "", "stage": "asking", "stage_at": utc_now(), "stage_clock": time.monotonic(), "error": "",
                "approve": plan["approve"], "initiator": ""}
        job = Job("create", "", text, plan["model"], dict(plan, session=resource, made=made), attachments)
        if made["name"]:
            with self.lock:
                self.created.append(made)  # before anything is asked: a chat that is being made is never lost track of
                self.dirty = True
        self.jobs.put(job)
        self.wake.set()
        if made["name"]:
            return {"session": resource, "pending": True}
        job.done.wait()  # 1.8.7: a chat with no task (a one-click skill) is waited for with no limit too: "failed" while it still goes on would make a second one
        if job.error is not None:
            raise job.error
        return job.result

    def super_watch(self, session: str, chat: str) -> None:
        """1.8.1: keep this chat (the super agent's) subscribed, from the next look. Empty `chat`: let go."""
        with self.lock:
            self.super_chat = {"session": session, "chat": chat} if session and chat else None
            self.dirty = True
        self.wake.set()

    def super_view(self) -> Optional[Dict[str, Any]]:
        """1.8.1, from the cache: `{state, status}` of the super agent chat (`state`: its trimmed snapshot, None until it is read; `status`: idle, busy, input, error, unknown), or None when the link is not ready or no chat is watched."""
        with self.lock:
            if not self.enabled or not self.ready or not self.super_chat:
                return None
            held = self.chats.get(self.super_chat["chat"])
            return {"state": copy.deepcopy(held["state"]) if held else None, "status": ahp.status_name((self.sessions.get(self.super_chat["session"]) or {}).get("status"))}

    def super_send(self, plan: Dict[str, Any], text: str) -> Dict[str, Any]:
        """1.8.1: send one turn to the super agent chat on the thread, making the chat first when `plan` names none. `plan`: {session, chat (both empty: make one), agent (file uri), model, approve}.
        The answer: {session, chat, turn}. Raises Refused (`off`, `not-ready`, `not-idle`, `timeout`) or the host's error."""
        why = self.create_blocked()
        if why:
            raise Refused(why)
        job = Job("super", "", text, plan.get("model"), plan)
        self.jobs.put(job)
        self.wake.set()
        job.done.wait()  # 1.8.7: making the chat is never given up (an empty chat would be left); the view shows the agent at work meanwhile
        if job.error is not None:
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
            if NEEDS[kind] and state != NEEDS[kind] and not (kind in ("confirm", "answer") and self._sub_targets(binding)):  # a subagent's chat can wait while the chat of the task says "in progress"
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
        if not job.done.wait(pace.scaled(JOB_WAIT)):
            job.cancelled = True  # a late thread must not send what the person was told failed
            raise Refused("timeout")
        if job.error is not None:
            raise job.error
        return job.result

    def ask_of(self, task: str) -> Optional[Dict[str, Any]]:
        """What the chat of this task waits for a person to answer, from the cache: the oldest tool confirmation or question (`chatask.shown`, plus `count` of them and `since`). None: nothing, or the
        task has no chat, or the item is of another kind. The page may be seconds old: `respond` reads it again."""
        with self.lock:
            binding = self.bound.get(task) if self.ready else None
            held = self.sess.get(binding["session"]) if binding else None
            if not binding:
                return None
            subs = self._sub_targets(binding)
            items = list((held["state"].get("inputNeeded") if held else None) or []) + self._sub_items(binding)  # 1.8: a confirmation in a running subagent's chat is the task's too
            mine = chatask.all_for(items, [binding["chat"]] + [item["chat"] for item in subs])
            if not mine:
                return None
            seen = lambda one: (held["seen"].get(one["id"]) if held else None) or self.sub_seen.setdefault(one["id"], utc_now())  # noqa: E731
            view = mine[0]
            # `rest`: the next ones (ASK_REST at most), each with its own buttons on the page: a call to allow must not wait behind a question (UX round 2 of the board chat)
            return dict(view, count=len(mine), since=seen(view), rest=[dict(one, count=1, since=seen(one)) for one in mine[1:1 + ASK_REST]])

    def respond(self, kind: str, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Allow or deny a tool call (`confirm`), or answer a question (`answer`), on the thread. `payload`: {id, digest, tool_call_id | request_id, approved | answers}. Raises Refused
        (`ask-gone`, `ask-changed`, `not-input`, `unbound`, ...) or a chatask.AnswerError. Returns when the host has been told."""
        why = self.check(task, kind)
        if why:
            raise Refused(why)
        job = Job(kind, task, "", None, payload)
        self.jobs.put(job)
        self.wake.set()
        if not job.done.wait(pace.scaled(JOB_WAIT)):
            job.cancelled = True  # a late thread must not answer what the person was told failed
            raise Refused("timeout")
        if job.error is not None:
            raise job.error
        return job.result

    # --- the thread ---------------------------------------------------------------------------------------------------------

    def installed(self) -> Dict[str, Any]:
        """1.8.x: is VS Code installed here (its `code` command found; it never has to be open), and which version. Files only, no program started."""
        folders = launchenv.tool_folders(self.root)
        code = ahp.find_code(folders=folders)  # O1: a folder a person gave counts too
        how = "" if not code else "standard" if code in ahp.standard_places() else "folder" if str(Path(code).parent) in folders else "path"
        return {"found": bool(code), "version": ahp.code_version(code) if code else "", "off": ahp.switched_off(), "path": code or "", "how": how}

    def own_host(self) -> agenthost.Host:
        """1.8.x: the board's own agent host, made once (`core.agenthost`); it gets the tool folders and the CA bundle of Local when it starts."""
        with self.lock:
            if self.own is None:
                self.own = agenthost.Host(self.root, extra=lambda: launchenv.extra(self.root), identities=lambda: conn_core.host_identities(self.root),
                                          path=shortcmd.fresh_path)  # H5b: and the identities chosen; H6: and the PATH of a new terminal
            return self.own

    def host_stale(self) -> bool:
        """H5: the board's own agent host runs with older Local settings (tool folders, CA bundle, proxy) than `launchenv.extra` gives now."""
        with self.lock:
            own = self.own
        return own is not None and own.stale()

    def stop_host(self) -> bool:
        """The board stops on purpose: its agent host stops too (the next start takes a few seconds; only a VS Code update makes it download again). False when there was none."""
        with self.lock:
            own = self.own
        if own is None or own.status().get("state") not in ("starting", "preparing", "ready"):
            return False
        own.stop()
        return True

    def host_outdate(self) -> None:
        """H6: the short command was just put on PATH: the running host does not have it until it starts again (the board restarts it once no chat works)."""
        with self.lock:
            own = self.own
        if own is not None:
            own.outdate()

    def restart_host(self) -> Dict[str, Any]:
        """H5: stop the board's own agent host and start it again with the Local settings of now. The connection drops and the link opens it again (and hands gh's token).
        A chat with a running turn stops: the caller asks only when none runs."""
        with self.lock:
            own = self.own
        return own.restart() if own is not None else {"state": "stopped"}

    def host_state(self) -> Dict[str, Any]:
        """1.8.x: where the board's own agent host is (`agenthost.Host.status`: state, download, version), for the Enter page. `stopped` before the first open."""
        with self.lock:
            own = self.own
        return own.status() if own is not None else {"state": "off" if not self.enabled or ahp.switched_off() else "stopped"}

    def _open(self) -> ahp.Connection:
        """1.8.x: start (or adopt) the board's own agent host, connect over its TCP port, and hand it gh's token. No VS Code window is needed."""
        if ahp.switched_off():
            raise ahp.NotReady("off")
        host = self.own_host()
        host.start()
        try:
            endpoint = host.wait_ready(OPEN_WAIT)
        except ahp.NotReady as error:
            raise ahp.NotReady("starting" if error.why == "cli-slow" else error.why, str(error)) from None
        link = ahp.connect(endpoint)
        self._hand_token(link)
        return link

    def _hand_token(self, link: Any) -> None:
        """Sign the host in with gh's token (`core.ghauth`). The token is read here, handed over the connection and dropped; what happened is kept for the Enter page."""
        extra = launchenv.extra(self.root)
        gh = ghauth.find_gh(ghauth.folders_of(self.root))
        state = "handed"
        if not gh:
            state = "no-gh"
        else:
            try:
                link.authenticate(ghauth.token(gh, extra))
            except ghauth.GhError as error:
                state = error.why
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                state = "refused"
        with self.lock:
            self.signin = {"state": state, "login": self.signin.get("login", ""), "at": time.monotonic()}
            if state == "handed":
                self.models_quick_until = time.monotonic() + QUICK_FOR

    def signin_state(self) -> Dict[str, Any]:
        """1.8.x: the last hand-over of gh's token (`state`), and seconds since (`ago`)."""
        with self.lock:
            out = dict(self.signin)
        out["ago"] = round(time.monotonic() - out.pop("at"), 1) if out.get("at") else None
        return out

    def begin_login(self) -> Dict[str, Any]:
        """1.8.x: start gh's web sign-in for the Enter page (one at a time). `{state: no-gh}` when there is no gh."""
        with self.lock:
            running = self.gh_login is not None and self.gh_login.status()["state"] in ("starting", "waiting")
            if running:
                return self.gh_login.status()  # type: ignore[union-attr]
        gh = ghauth.find_gh(ghauth.folders_of(self.root))
        if not gh:
            return {"state": "no-gh", "download": ghauth.DOWNLOAD_PAGE}
        login = ghauth.Login(gh, launchenv.extra(self.root)).start()
        with self.lock:
            self.gh_login, self.gh_login_handed = login, False
        self.wake.set()
        return login.status()

    def sign_out(self) -> Dict[str, Any]:
        """The person signed out (1.8.33): gh signs out of github.com (`ghauth.logout`), and the agent host, which holds the token in its memory, is marked outdated: the board starts it again once no chat
        works (`host_outdate`), and the new host finds gh not signed in. A turn that runs now is not stopped. `{done, login}`; `ghauth.GhError` when gh is missing or refuses."""
        gh = ghauth.find_gh(ghauth.folders_of(self.root))
        if not gh:
            raise ghauth.GhError("no-gh", "gh is not installed")
        found = ghauth.logout(gh, launchenv.extra(self.root))
        with self.lock:
            self.signin = {"state": "signed-out", "login": "", "at": time.monotonic()}
        self.host_outdate()
        return found

    def login_state(self) -> Dict[str, Any]:
        with self.lock:
            login = self.gh_login
        return login.status() if login is not None else {"state": "none"}

    def cancel_login(self) -> None:
        with self.lock:
            login = self.gh_login
        if login is not None:
            login.cancel()

    def sign_in_again(self) -> None:
        """Hand gh's token to the host again (after gh signed in): done on the thread."""
        self.jobs.put("auth")
        self.wake.set()

    def _login_done(self, link: Any) -> None:
        """A sign-in the Enter page started has ended well: the host gets the new token now, not at the next start."""
        with self.lock:
            login = self.gh_login
            due = login is not None and not self.gh_login_handed and login.status()["state"] == "done"
            if due:
                self.gh_login_handed = True
        if due:
            self._hand_token(link)

    def _set(self, ready: bool, why: str) -> None:
        with self.lock:
            self.losses += 1 if self.ready and not ready else 0
            self.ready, self.why = ready, why
            if not ready and not self.down_at:
                self.down_at = time.monotonic()
            waited = time.monotonic() - self.down_at if ready and self.down_at else 0.0
            if ready:
                self.down_at = 0.0  # a later loss counts its wait from then, not from before this connection
        if waited > 0:
            try:
                from core import speednet
                speednet.record_vscode_start(self.root, waited)  # `harness speed`: seconds from the first failed try to connected (the agent host starting)
            except Exception:  # noqa: BLE001 - a helper must not disturb the link
                pass

    def _wait(self, seconds: float) -> None:
        """Wait `seconds` (the grown wait), or less when something wakes the thread (a job, a stop)."""
        if not self.stop_flag.is_set():
            self.wake.wait(seconds)
        self.wake.clear()

    def _run(self) -> None:
        while not self.stop_flag.is_set():
            self._jobs()  # no connection: a send that is waiting is refused
            try:
                link = self._opener()
            except ahp.NotReady as error:
                self._set(False, error.why)
                self._wait(NO_CLI_WAIT if error.why in ("no-cli", "off") else HOST_POLL if error.why == "starting" else self.backoff.next())
                continue
            except (ahp.AhpError, OSError, ValueError):
                self._set(False, "error")
                self._wait(self.backoff.next())
                continue
            self.backoff.reset()
            if hasattr(link, "start_reader"):
                link.start_reader()  # 1.8.7: one thread reads; the lanes call at once, and nobody waits in place for another's answer
                link.default_timeout = pace.scaled(BACKGROUND_TIMEOUT)
            try:
                self._serve(link)
            except (ahp.AhpError, OSError, ValueError):
                pass
            finally:
                link.close()
                kept = self.keep_shown()
                with self.lock:
                    if kept:  # a connection that went away before it was ready keeps what an earlier one left
                        self.shown, self.lost_at = kept, time.monotonic()
                    self.slow = 0
                    self.losses += 1 if self.ready else 0
                    self.ready, self.why = False, "lost"
                    self.chats.clear()
                    self.sess.clear()
                    self.sessions.clear()
                    self.bound.clear()
                    self.unbound.clear()
                    self.sdk.clear()
                    self.models = []
                    self.scanned.clear()
                    self.read_at.clear()
                    self.listed_at = 0.0
                    self.expect.clear()
            self._wait(self.backoff.next())

    def _jobs(self, link: Optional[ahp.Connection] = None) -> None:
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            if job == "auth":
                if link is not None:
                    self._hand_token(link)
                continue  # no connection: the next open hands the token anyway
            if isinstance(job, Job):
                if link is None or job.cancelled:
                    made = (job.plan or {}).get("made") if job.kind == "create" else None
                    if isinstance(made, dict) and link is None:
                        self._stage(made, "lost")  # 1.8.7: the connection went before the chat was asked for: made when it comes back
                    job.error = Refused("not-ready")
                    job.done.set()
                else:
                    self._do(link, job)

    def _models(self, link: ahp.Connection) -> None:
        """The models of the host, read from its root state once and then with every new list. One read, then we let go of the channel."""
        try:
            root_state = link.subscribe("ahp-root:/")
            found, limits = ahp.models_of(root_state), ahp.limits_of(root_state)
            link.unsubscribe("ahp-root:/")
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError:
            return
        with self.lock:
            self.models, self.limits = found, limits

    def _list(self, link: ahp.Connection) -> None:
        asked = time.monotonic()
        items = link.sessions()
        mine = {item["resource"]: item for item in items if ahp.is_ours(item) and ahp.session_in(item, str(self.root)) and item.get("resource")}
        with self.lock:
            if asked < self.list_asked:
                return  # 1.8.7: the two lanes may list at once; a list asked for earlier than the one in place is older, and is not put back over it
            self.list_asked = asked
            self.everywhere = {str(item["resource"]): {key: item.get(key) for key in ("title", "status")} for item in items if item.get("resource")}
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
        lanes = getattr(link, "reading", lambda: False)()
        ended = threading.Event()
        person = threading.Thread(target=self._person, args=(link, ended), name="board-person", daemon=True) if lanes else None
        if person is not None:
            person.start()
            self._resume_made(link)
        try:
            self._background(link, lanes)
        finally:
            ended.set()
            if person is not None:
                person.join(5)

    @staticmethod
    def lane_of(task: str) -> int:
        """1.8.7: the lane a task's jobs go to: always the same one, so two messages to one chat go in the order they were sent."""
        return sum(task.encode("utf-8")) % PERSON_LANES

    def _person(self, link: ahp.Connection, ended: threading.Event) -> None:
        """1.8.7, the person's lane: what a page asked for (send, steer, stop, answer, allow...) is done here, never behind the background reads. The jobs of one task go to
        one of PERSON_LANES threads, in order; a job that waits on one task does not hold up the others. A chat to make goes to a thread of its own: VS Code may take minutes, with no limit."""
        queues: List["queue.Queue[Any]"] = [queue.Queue() for _ in range(PERSON_LANES)]
        lanes = [threading.Thread(target=self._lane, args=(link, ended, waiting), name=f"board-person-{n}", daemon=True) for n, waiting in enumerate(queues)]
        for lane in lanes:
            lane.start()
        try:
            while not ended.is_set() and not self.stop_flag.is_set() and not getattr(link, "closed", False):
                try:
                    job = self.jobs.get(timeout=PERSON_POLL)
                except queue.Empty:
                    continue
                if isinstance(job, Job) and job.kind in ("create", "super"):
                    threading.Thread(target=self._do_alone, args=(link, job), name="board-create", daemon=True).start()
                elif isinstance(job, Job):
                    queues[self.lane_of(job.task)].put(job)
                elif job == "auth":
                    self._hand_token(link)
        finally:
            ended.set()
            for lane in lanes:
                lane.join(5)
            for waiting in queues:  # what no lane took: refused, as a job is when the connection goes
                while True:
                    try:
                        job = waiting.get_nowait()
                    except queue.Empty:
                        break
                    job.error = Refused("not-ready")
                    job.done.set()

    def _lane(self, link: ahp.Connection, ended: threading.Event, waiting: "queue.Queue[Any]") -> None:
        while not ended.is_set() and not self.stop_flag.is_set() and not getattr(link, "closed", False):
            try:
                job = waiting.get(timeout=PERSON_POLL)
            except queue.Empty:
                continue
            if job.cancelled:
                job.error = Refused("not-ready")
                job.done.set()
                continue
            try:
                self._do(Guarded(link, job), job)  # type: ignore[arg-type]
            except ahp.ConnectionClosed:
                return  # the job says so; the link opens a new connection
            except Exception as error:  # noqa: BLE001 - one job that fails (a refused answer) never stops the lane: the page gets the error, the next job goes on
                if job.error is None:
                    job.error = error
                job.done.set()

    def _do_alone(self, link: ahp.Connection, job: Job) -> None:
        """A job on a thread of its own (a chat to make): a connection that closes ends it quietly; the job and the board's "being created" say so."""
        try:
            self._do(link, job)
        except ahp.ConnectionClosed:
            pass
        except Exception as error:  # noqa: BLE001 - see `_person`
            made = (job.plan or {}).get("made")
            if isinstance(made, dict) and made.get("stage") == "asking":
                self._stage(made, "refused", "other")  # never left "being made" with nobody making it
            if job.error is None:
                job.error = error
            job.done.set()

    def _resume_made(self, link: ahp.Connection) -> None:
        """1.8.7: a chat that was being made when the connection went is picked up again: VS Code may have made it meanwhile, so the board looks and sends the first message if it has none."""
        with self.lock:
            lost = [made for made in self.created if made.get("stage") == "lost"]
            for made in lost:
                made.update(stage="asking", stage_at=utc_now(), stage_clock=time.monotonic())  # taken: a second look does not start it twice
        for made in lost:
            plan = {"name": made["name"], "kind": made["kind"], "source": made["source"], "lang": made["lang"], "permission": made["permission"], "model": made["model"],
                    "approve": made.get("approve") or "autoApprove", "session": made["session"], "made": made, "again": bool(made.get("asked"))}  # never asked: made now, as new
            job = Job("create", "", made["text"], made["model"], plan)
            threading.Thread(target=self._do_alone, args=(link, job), name="board-create", daemon=True).start()

    def _background(self, link: ahp.Connection, lanes: bool) -> None:
        last = 0.0
        read_models = time.monotonic()
        while not self.stop_flag.is_set():
            note = link.next_notice(self.turn)
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)
            if not lanes:
                self._jobs(link)  # a connection with no reader (some tests): one thread does it all, as before
            now = time.monotonic()
            if now - self.listed_at >= (EXPECT_EVERY if self.expect else RELIST_EVERY):
                self._calm(lambda: self._list(link))
                self._models(link)
                read_models = now
            elif now - read_models >= (MODELS_QUICK if now < self.models_quick_until else MODELS_EVERY):
                read_models = now
                self._models(link)
            self._login_done(link)
            if self.dirty or now - last >= TASKS_EVERY:
                last = now
                self.dirty = False
                self._look(link)
                self._autorun(link)
            self._starts(link)  # its own pace (RELAY_EVERY): a Start order does not wait for the next look at the tasks
            self._follow(link)

    def start_order(self, task: str, model: Dict[str, Any], allow: str) -> None:
        """1.8, step 9: the board switched autorun on. The thread does the Start order (Allow all, `/compact` when the chat has history, `/harness-autorun` with `model`) on the bound chat as it is, and nothing else
        sends to that chat until the order has reached its last stage (the relay waits). `allow`: the host's value for Allow all, or "" to leave it."""
        with self.lock:
            self.starts[task] = autorun_start.new_order(model, allow, datetime.datetime.now(datetime.timezone.utc))
        self.backoff.reset()
        self.wake.set()

    def cancel_start(self, task: str) -> None:
        with self.lock:
            self.starts.pop(task, None)

    def starting(self, task: str) -> bool:
        """Is the Start order of this task before its last stage (the relay and the pit stop keep away)?"""
        with self.lock:
            return (self.starts.get(task) or {}).get("stage") in autorun_start.BEFORE_VERIFY

    def _follow(self, link: ahp.Connection) -> None:
        """1.8.2: send `/<skill> <words>` to a chat the board made for a skill only a person starts, once its first turn (open the task) is over: the chat is bound to the task and idle.
        Sent once; a chat that never comes back idle within `chatnew.KEEP_PENDING` is let go, with a line on the task. A failure here never stops the link."""
        now = time.monotonic()
        with self.lock:
            items = list(self.follow.items())
        if not items or now - self.follow_at < RELAY_EVERY:
            return
        self.follow_at = now
        for task, item in items:
            try:
                if now - item["clock"] > chatnew.KEEP_PENDING:
                    with self.lock:
                        self.follow.pop(task, None)
                    with task_ops.locked(self.root, task) as data:
                        task_ops.note(data, "send", messages.text("create.follow.lost", text=chatsend.summary(item["text"])))
                    continue
                with self.lock:
                    binding = self.bound.get(task)
                    status = ahp.status_name((self.sessions.get(binding["session"]) or {}).get("status")) if binding else ""
                if not binding or binding.get("chat") != item["chat"] or status != "idle":
                    continue
                job = Job("send", task, item["text"], item["model"])
                self._do(link, job)  # on this thread: it looks at the binding and the chat again, and refuses rather than guess
                if job.error is not None:
                    continue
                with self.lock:
                    self.follow.pop(task, None)
                done = job.result or {}
                chatsend.record(self.root, task, {"at": utc_now(), "task": task, "kind": "send", "chat": done.get("chat", ""), "title": done.get("title", ""), "turn": done.get("turn", ""),
                                                  "text": item["text"], "model": item["model"] or {}})
                with task_ops.locked(self.root, task) as data:
                    task_ops.note(data, "send", (done.get("title") or "-")[:60] + ": " + chatsend.summary(item["text"]))
            except ahp.ConnectionClosed:
                raise
            except Exception:  # noqa: BLE001 - a helper: tried again at the next look
                pass

    def _starts(self, link: ahp.Connection) -> None:
        """Do the next step of each Start order. A failure here never stops the link; an order that fails ends the run (`autorun_start.fail`)."""
        now = time.monotonic()
        with self.lock:
            orders = list(self.starts.items())
        if not orders or now - self.start_at < RELAY_EVERY:
            return
        self.start_at = now
        for task, order in orders:
            try:
                with self.lock:
                    binding = self.bound.get(task)
                    held = self.chats.get(binding["chat"]) if binding else None
                    state = copy.deepcopy(held["state"]) if held else None
                    status = ahp.status_name((self.sessions.get(binding["session"]) or {}).get("status")) if binding else ""
                if state is None:
                    continue

                def do(kind: str, text: str, model: Optional[Dict[str, Any]], plan: Optional[Dict[str, Any]], task: str = task) -> Optional[BaseException]:
                    job = Job(kind, task, text, model, plan)
                    self._do(link, job)  # on this thread: it looks at the binding and the chat again, and refuses rather than guess
                    return job.error

                autorun_start.step(self.root, task, order, state, status, do)
            except ahp.ConnectionClosed:
                raise
            except Exception:  # noqa: BLE001 - a helper: the order is tried again at the next look
                pass
            with self.lock:
                if order.get("stage") == "over" and self.starts.get(task) is order:
                    del self.starts[task]

    def _autorun(self, link: ahp.Connection) -> None:
        """1.8, steps 7 and 8 of autorun: for each bound task whose autorun is on, look at its chat and, when the run needs it, wake the agent (relay) or end a turn to compact (pit stop). `autorun_relay.step` decides;
        only this thread sends. Only bound chats of tasks in autorun are looked at, about once a second; a failure here never stops the link."""
        now = time.monotonic()
        if now - self.relay_at < RELAY_EVERY:
            return
        self.relay_at = now
        with self.lock:
            bound = [(task, binding["chat"], binding["session"]) for task, binding in self.bound.items() if binding.get("chat")]
        for task, chat, resource in bound:
            if self.relay_hold.get(task, 0.0) > now or self.starting(task):
                continue
            try:
                data = tasks.read(self.root, task)
                if not data or not autorun.is_on(data):
                    self.relay_hold.pop(task, None)
                    continue
                with self.lock:
                    held = self.chats.get(chat)
                    state = copy.deepcopy(held["state"]) if held else None
                    status = ahp.status_name((self.sessions.get(resource) or {}).get("status"))
                    windows = dict(self.limits)
                if state is None:
                    continue
                sent: List[Optional[BaseException]] = []

                def send(text: str, model: Optional[Dict[str, Any]], task: str = task) -> Optional[BaseException]:
                    job = Job("relay", task, text, model)
                    self._do(link, job)  # on this thread: it looks at the binding and the chat again, and refuses rather than guess
                    sent.append(job.error)
                    return job.error

                autorun_relay.step(self.root, task, state, status, windows, send)
                if sent and sent[0] is not None:
                    self.relay_hold[task] = time.monotonic() + RELAY_HOLD
            except ahp.ConnectionClosed:
                raise
            except Exception:  # noqa: BLE001 - a helper: the run waits for the next look
                self.relay_hold[task] = time.monotonic() + RELAY_HOLD

    def _calm(self, step: Callable[[], None]) -> None:
        """One step of the loop whose call the host may not answer in time (1.7.45): that is a slow host, not a lost one, until SLOW_LIMIT of them come in a row.
        A closed connection is lost at once."""
        try:
            step()
            self.slow = 0
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError:
            self.slow += 1
            if self.slow >= SLOW_LIMIT:
                raise
            self.listed_at = time.monotonic() - RELIST_EVERY + SLOW_RETRY  # asked again soon, not at once

    def keep_shown(self) -> Dict[str, Dict[str, Any]]:
        """What the rows show of their chats now, for the open tasks that have one: kept for a while after the connection goes away. Never raises."""
        try:
            with self.lock:
                tasks_now = list(self.bound) if self.ready else []
            return {task: chat for task in tasks_now for chat in [self.chat_of(task)] if chat.get("bound")}
        except Exception:  # noqa: BLE001 - a helper: the rows then say the link is lost, as before
            return {}

    def _notice(self, note: Dict[str, Any]) -> None:
        method, params = str(note.get("method") or ""), note.get("params") or {}
        stream: Optional[Tuple[str, List[Dict[str, Any]]]] = None  # (task, records due): written after the lock, never under it
        with self.lock:
            if method == "root/sessionAdded":
                item = params.get("summary") or {}
                if item.get("resource"):
                    self.everywhere[str(item["resource"])] = {key: item.get(key) for key in ("title", "status")}
                if ahp.is_ours(item) and ahp.session_in(item, str(self.root)) and item.get("resource"):
                    self.sessions[item["resource"]] = item
                    self.dirty = True
            elif method == "root/sessionSummaryChanged":
                for chat, started in list(self.just_sent.items()):
                    if started[2] == str(params.get("session") or ""):
                        del self.just_sent[chat]  # VS Code has said how the chat stands since the board sent its turn: its word counts
                seen = self.everywhere.get(str(params.get("session") or ""))
                if seen is not None and isinstance(params.get("changes"), dict):
                    seen.update({key: value for key, value in params["changes"].items() if key in ("title", "status")})
                known = self.sessions.get(str(params.get("session") or ""))
                if known is not None and isinstance(params.get("changes"), dict):
                    known.update(params["changes"])
                    self.dirty = True
            elif method == "root/sessionRemoved":
                self.everywhere.pop(str(params.get("session") or ""), None)
                self.sessions.pop(str(params.get("session") or ""), None)
                self.dirty = True
            elif method == "action":
                channel = str(params.get("channel") or "")
                cached = self.chats.get(channel)
                action = params.get("action")
                if isinstance(action, dict) and action.get("type") in ("chat/turnComplete", "chat/turnCancelled", "chat/error"):
                    self.just_sent.pop(channel, None)
                if cached is not None and isinstance(action, dict):
                    ahp.reduce_chat(cached["state"], action)
                    chatlive.stamp(cached, action, int(time.time() * 1000))  # before the stream takes the action: it stores the part times
                    if self.persist and chatstream.wants(action):  # 1.8.x: what the board sees of the chat is kept in the task's stream; collected here, written below once the lock is let go
                        try:
                            owner = self._stream_task(channel)
                            if owner is not None:
                                stream = (owner[0], chatstream.take(cached, channel, action, owner[1]))
                        except Exception:  # the stream is a record beside the chat: a fault in it must never stop the chat
                            self.stream_lost += 1
                    cached["rev"] = cached.get("rev", 0) + 1  # the Live tab asks only for what changed since this number
                    if action.get("type") in ("chat/toolCallStart", "chat/toolCallReady"):
                        cached["tool_at"] = utc_now()
                held = next((item for item in self.sess.values() if item["channel"] and item["channel"] == channel), None)
                if held is not None and isinstance(action, dict):
                    ahp.reduce_session(held["state"], action)
                    self._stamp(held)
                    self.dirty = True
        if stream is not None and stream[1]:
            self.stream_lost += chatstream.append(self.root, stream[0], stream[1])

    def _stream_task(self, chat: str) -> Optional[Tuple[str, Optional[Dict[str, str]]]]:
        """The task a chat belongs to and, for the chat of a subagent, where it was started (`{parent, call}`): the task whose binding names the chat, or whose session lists it among its
        `subchats`. None for a chat of no task (the super agent's, one made for a task not yet bound). It walks the few bound tasks; the caller asks only for an action that can give a record.
        The caller holds the lock."""
        for task, binding in self.bound.items():
            if binding.get("chat") == chat:
                return task, None
        for task, binding in self.bound.items():
            for item in ((self.sess.get(binding.get("session")) or {}).get("state") or {}).get("subchats") or []:
                if item.get("chat") == chat:
                    return task, {"parent": item.get("parent"), "call": item.get("call")}
        return None

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
        if chatlink.unsettled(next((entry for entry in entries if entry["task"] == task), {}), binding, sdk):
            with self.lock:
                self.dirty = True  # the next look reads the chats and settles it
            raise Refused("changed")  # another chat may have picked the task up a moment ago: nothing goes to the old one
        state = ahp.status_name(sessions[binding["session"]].get("status"))
        if NEEDS[kind] and state != NEEDS[kind]:
            with self.lock:
                subagent = kind in ("confirm", "answer") and bool(self._sub_targets(binding))
            if not subagent:
                raise Refused("not-" + NEEDS[kind])
        return binding

    def _initiator(self, link: ahp.Connection, resource: str, state: Dict[str, Any]) -> str:
        """Who the host says made the chat (`vscode` is right). The host lists a chat only after its first turn began: asked for a few seconds. Empty: not known."""
        found = ahp.initiator_of(state.get("_meta"))
        tail = resource.rsplit("/", 1)[-1]
        end = time.monotonic() + pace.scaled(INITIATOR_WAIT)
        while not found:
            for item in link.sessions():
                if str(item.get("resource") or "").rsplit("/", 1)[-1] == tail:
                    found = ahp.initiator_of(item.get("_meta"))
                    break
            if found or time.monotonic() >= end:
                break
            if getattr(link, "reading", lambda: False)():
                time.sleep(0.5)  # 1.8.7: the background lane reads the notices; this thread only asks again
                continue
            note = link.next_notice(0.5)  # the host's notices keep coming while we wait
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)
        return found

    def _create(self, link: ahp.Connection, job: Job) -> None:
        """Make the chat, send the first message, and keep what is needed to bind the task when the agent has made it. Every step waits for VS Code with no limit (1.8.7): a late
        answer still goes on, so no empty chat is left. `made` (the board's "being created") says how far it is. `again`: picked up after the connection went (`_resume_made`)."""
        plan = job.plan or {}
        made = plan.get("made") if isinstance(plan.get("made"), dict) else None
        resource = str(plan.get("session") or "ahp-session:/" + str(uuid.uuid4()))
        wait = None if getattr(link, "reading", lambda: False)() else ahp.create_timeout()  # without a reader nobody would read a late answer
        try:
            if plan.get("again"):
                try:
                    state = link.subscribe(resource, timeout=wait)  # is it there? An unknown channel is the host's error: it never made it
                except ahp.ConnectionClosed:
                    raise
                except ahp.AhpError:
                    if made is not None:
                        self._stage(made, "refused", "never")
                    raise Refused("never") from None  # not the host's words: VS Code does not have the chat
                chat = str(state.get("defaultChat") or "")
                if chat:
                    known = ahp.trimmed(link.subscribe(chat, timeout=wait))
                    if [turn for turn in known.get("turns") or [] if isinstance(turn, dict)] or known.get("activeTurn"):  # it has its first message: nothing more to send
                        with self.lock:
                            if made is not None:
                                made["chat"] = chat
                            self.chats[chat] = {"state": known, "tool_at": ""}
                        if made is not None:
                            self._stage(made, "sent")
                        job.result = {"session": resource, "chat": chat, "initiator": "", "turn": ""}
                        return
            else:
                if job.cancelled:
                    raise Refused("timeout")
                if made is not None:
                    with self.lock:
                        made["asked"] = True  # from now on VS Code may make it, even if the connection goes
                link.call("createSession", {"channel": resource, "provider": ahp.LOCAL_PROVIDER, "workingDirectories": [ahp.folder_uri(self.root)],
                                            "config": {"isolation": "folder", "mode": "interactive", "autoApprove": plan["approve"]}}, timeout=wait)  # `model` here would not be honoured: it goes on the message
                state = link.subscribe(resource, timeout=wait)
                chat = str(state.get("defaultChat") or "")
            if not chat:
                raise ahp.AhpError("createSession: no chat in the new session")
            held = {"state": ahp.trimmed(link.subscribe(chat, timeout=wait)), "tool_at": ""}
        except ahp.ConnectionClosed:
            if made is not None:
                self._stage(made, "lost")
            raise
        except (ahp.AhpError, OSError, ValueError) as error:
            if made is not None:
                kind, detail = ahp.problem_of(error)
                self._stage(made, "refused", detail if kind == "said" else kind)
            raise
        message: Dict[str, Any] = {"text": job.text, "origin": {"kind": "user"}}
        if job.model:
            message["model"] = job.model
        if job.attachments:
            message["attachments"] = job.attachments
        action = {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message}
        stub = {"resource": resource, "provider": ahp.LOCAL_PROVIDER, "title": "", "status": ahp.IN_PROGRESS, "defaultChat": chat, "chats": [{"resource": chat}],
                "workingDirectories": [ahp.folder_uri(self.root)], "modifiedAt": ahp.utc_stamp()}
        with self.lock:
            if made is None and str(plan.get("name") or ""):  # made without `create` (a caller of the old shape): kept now
                made = {"name": plan["name"], "kind": plan["kind"], "source": plan["source"], "lang": plan["lang"], "permission": plan["permission"], "model": job.model, "text": job.text,
                        "files": chatsend.listed(job.attachments or []), "session": resource, "chat": chat, "title": "", "made_at": utc_now(), "clock": time.monotonic(),
                        "keep_model": plan.get("keep_model", True), "then": plan.get("then") or "", "stage": "asking", "stage_at": utc_now(), "stage_clock": time.monotonic(), "error": ""}
                self.created.append(made)
            if made is not None:
                made["chat"] = chat
            self.expect[resource] = {"stub": stub, "until": time.monotonic() + pace.scaled(EXPECT_FOR)}  # the host lists it only once the first turn runs: until then the cache holds the stub
            self.chats[chat] = held
            self.sess[resource] = {"channel": resource, "state": ahp.trimmed_session(state), "seen": {}}
        try:
            link.dispatch(chat, action)
        except (ahp.ConnectionClosed, OSError, ValueError):
            if made is not None:
                self._stage(made, "lost")  # the chat is there and empty: its first message goes when the connection comes back
            raise ahp.ConnectionClosed("the connection closed before the first message went")
        with self.lock:
            ahp.reduce_chat(held["state"], {**action, "message": {key: value for key, value in message.items() if key != "attachments"}})  # the bytes are not kept here
            self.sessions.setdefault(resource, dict(stub))  # tracked at once; `_list` asks again every EXPECT_EVERY seconds until the host lists it
            self.dirty = True
        if made is not None:
            self._stage(made, "sent")
        initiator = self._initiator(link, resource, state)
        if made is not None:
            with self.lock:
                made["initiator"] = initiator
        job.result = {"session": resource, "chat": chat, "initiator": initiator, "turn": str(action["turnId"])}

    def _super(self, link: ahp.Connection, job: Job) -> None:
        """1.8.1: one turn for the super agent chat. The chat is made with the custom agent (`agent.uri` in `createSession` and in the message), Allow all, no worktree; the model goes on the message.
        A chat that exists must have no running turn (`not-idle`). The chat is kept subscribed (`super_chat`), so the board reads the reply from the cache."""
        plan = job.plan or {}
        if job.cancelled:
            raise Refused("timeout")
        agent = {"uri": str(plan["agent"])}
        resource, chat = str(plan.get("session") or ""), str(plan.get("chat") or "")
        stub: Optional[Dict[str, Any]] = None
        wait = None if getattr(link, "reading", lambda: False)() else ahp.create_timeout()  # 1.8.7: making the chat waits for VS Code with no limit
        if not resource or not chat:
            with self.lock:
                if self.super_making:
                    raise Refused("not-idle")  # one super agent chat is being made already: a second would be made beside it
                self.super_making = True
            try:
                resource = "ahp-session:/" + str(uuid.uuid4())
                link.call("createSession", {"channel": resource, "provider": ahp.LOCAL_PROVIDER, "workingDirectories": [ahp.folder_uri(self.root)], "agent": agent,
                                            "config": {"isolation": "folder", "mode": "interactive", "autoApprove": str(plan.get("approve") or "autoApprove")}}, timeout=wait)
                state = link.subscribe(resource, timeout=wait)
                chat = str(state.get("defaultChat") or "")
                if not chat:
                    raise ahp.AhpError("createSession: no chat in the new session")
                held = {"state": ahp.trimmed(link.subscribe(chat, timeout=wait)), "tool_at": ""}
            finally:
                with self.lock:
                    self.super_making = False
            stub = {"resource": resource, "provider": ahp.LOCAL_PROVIDER, "title": "", "status": ahp.IN_PROGRESS, "defaultChat": chat, "chats": [{"resource": chat}],
                    "workingDirectories": [ahp.folder_uri(self.root)], "modifiedAt": ahp.utc_stamp()}
            with self.lock:
                self.expect[resource] = {"stub": stub, "until": time.monotonic() + pace.scaled(EXPECT_FOR)}  # the host lists it only once the first turn runs
                self.chats[chat] = held
                self.sess[resource] = {"channel": resource, "state": ahp.trimmed_session(state), "seen": {}}
        else:
            with self.lock:
                held = self.chats.get(chat)
                known = self.sessions.get(resource)
            if held is None:
                held = {"state": ahp.trimmed(link.subscribe(chat)), "tool_at": ""}
                with self.lock:
                    self.chats[chat] = held
            with self.lock:
                busy = bool(held["state"].get("activeTurn")) or ahp.status_name((known or {}).get("status")) in ("busy", "input")
            if busy:
                raise Refused("not-idle")
        message: Dict[str, Any] = {"text": job.text, "origin": {"kind": "user"}, "agent": agent}
        if job.model:
            message["model"] = job.model
        action = {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message}
        with self.lock:
            self.super_chat = {"session": resource, "chat": chat}
        if job.cancelled:  # the page was told it timed out while the chat was being made: keep the chat, send nothing (no spend nobody waits for)
            raise Refused("timeout")
        link.dispatch(chat, action)
        with self.lock:
            ahp.reduce_chat(held["state"], action)
            if stub is not None:
                self.sessions.setdefault(resource, dict(stub))
            known = self.sessions.get(resource)
            if known is not None:
                known["status"] = ahp.IN_PROGRESS | (int(known.get("status") or 0) & (ahp.IS_READ | ahp.ARCHIVED))
            chatlive.stamp(held, action, int(time.time() * 1000))
            held["rev"] = held.get("rev", 0) + 1
            self.dirty = True
        job.result = {"session": resource, "chat": chat, "turn": str(action["turnId"])}

    def _gate(self, task: str) -> threading.RLock:
        with self.lock:
            return self.gates.setdefault(task, threading.RLock())

    def _do(self, link: ahp.Connection, job: Job) -> None:
        gate: Optional[threading.RLock] = None
        try:
            if job.kind == "create":
                return self._create(link, job)
            if job.kind == "super":
                return self._super(link, job)
            if job.cancelled:
                raise Refused("timeout")
            gate = self._gate(job.task)
            if not gate.acquire(timeout=pace.scaled(GATE_WAIT)):  # 1.8.7: the person's lane and the background (relay, follow, Start) may send to one chat at once: one at a time
                gate = None
                raise Refused("not-idle")
            binding = self._recheck(link, job.task, job.kind)
            if job.kind == "relay":  # a chat that ended in an error takes the next message (measured: status 34, then 33)
                with self.lock:
                    if ahp.status_name((self.sessions.get(binding["session"]) or {}).get("status")) not in ("idle", "error"):
                        raise Refused("not-idle")
            if job.kind in ("confirm", "answer"):
                return self._respond(link, job, binding)
            if job.kind == "say":
                return self._say(link, job, binding)
            chat, resource = binding["chat"], binding["session"]
            with self.lock:
                held = self.chats.get(chat)
            if held is None:
                held = {"state": ahp.trimmed(link.subscribe(chat)), "tool_at": ""}
                with self.lock:
                    self.chats[chat] = held
            if job.kind == "bgstop":  # B16: a shell the chat runs in the background, stopped by the host's own request (only a shell can be)
                known = {str(item.get("id")) for item in held["state"].get("backgroundWork") or [] if isinstance(item, dict)}
                if job.text not in known:
                    raise Refused("ask-gone")
                answer = link.call("vscode/stopBackgroundWork", {"chat": chat, "id": job.text}, timeout=pace.scaled(30))
                job.result = {"chat": chat, "stopped": bool((answer or {}).get("stopped")) if isinstance(answer, dict) else False}
                return
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
            if job.kind == "rewind":
                return self._rewind(link, job, chat, held)
            if job.kind in ("resume", "unqueue"):
                return self._again(link, job, chat, held)
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
                if job.kind in ("send", "relay"):
                    with self.lock:
                        started = self.just_sent.get(chat)
                        running = held["state"].get("activeTurn") if isinstance(held["state"].get("activeTurn"), dict) else {}
                    if started and time.monotonic() - started[1] < FRESH_TURN and running.get("id") == started[0]:
                        raise Refused("not-idle")  # the board started a turn here a moment ago; a slow list still says idle
                    action = {"type": "chat/turnStarted", "turnId": str(uuid.uuid4()), "startedAt": ahp.utc_stamp(), "message": message}
                else:  # steer goes into the turn that runs; queue (1.6.99) waits for its end, and Copilot sends it then as the next turn
                    action = {"type": "chat/pendingMessageSet", "kind": "queued" if job.kind == "queue" else "steering", "id": str(uuid.uuid4()), "message": message}
            link.dispatch(chat, action)
            with self.lock:
                known = self.sessions.get(resource)
                if job.kind in ("send", "relay"):
                    self.just_sent[chat] = (str(action["turnId"]), time.monotonic(), resource)
                    if known is not None:
                        known["status"] = ahp.IN_PROGRESS | (int(known.get("status") or 0) & (ahp.IS_READ | ahp.ARCHIVED))  # not idle at once: a second send finds it busy
                    ahp.reduce_chat(held["state"], {**action, "message": {key: value for key, value in message.items() if key != "attachments"}})  # the bytes are not kept here
                    chatlive.stamp(held, action, int(time.time() * 1000))
                    held["rev"] = held.get("rev", 0) + 1
                elif job.kind == "queue":  # on the page at once; the host pushes the same
                    ahp.reduce_chat(held["state"], {**action, "message": {"text": job.text}})
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
            if gate is not None:
                gate.release()
            job.done.set()

    def _settle(self, link: ahp.Connection, held: Dict[str, Any]) -> None:
        """Wait until the chat has no running turn (a stop takes a moment), reading the host's notices meanwhile; at most `UNDO_WAIT` seconds."""
        end = time.monotonic() + pace.scaled(UNDO_WAIT)
        while time.monotonic() < end:
            with self.lock:
                if not held["state"].get("activeTurn"):
                    return
            if getattr(link, "reading", lambda: False)():
                time.sleep(0.3)  # 1.8.7: the background lane reads the notices and keeps `held` up to date
                continue
            note = link.next_notice(0.3)
            while note is not None:
                self._notice(note)
                note = link.next_notice(0.0)

    def _undo(self, link: ahp.Connection, job: Job, chat: str, held: Dict[str, Any]) -> None:
        """Take the last turn out of the chat: the message of the person and all that answered it. The host cuts Copilot's own history too (the model forgets it: checked on a real chat), but files
        the agent changed stay changed. A turn that runs is stopped first (1.6.99: a message sent by mistake is taken back in one step). The chat is read again first, for the whole text and the
        last turn as it is now."""
        active = held["state"].get("activeTurn") if isinstance(held["state"].get("activeTurn"), dict) else None
        if active and active.get("id"):
            link.dispatch(chat, {"type": "chat/turnCancelled", "turnId": active["id"], "duration": elapsed_ms(active.get("startedAt"))})
            self._settle(link, held)
        link.unsubscribe(chat)
        full = link.subscribe(chat)
        turns = [turn for turn in full.get("turns") or [] if isinstance(turn, dict)]
        if not turns or full.get("activeTurn"):
            with self.lock:
                held["state"] = ahp.trimmed(full)
            raise Refused("not-stopped" if full.get("activeTurn") else "no-turn")
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

    def _rewind(self, link: ahp.Connection, job: Job, chat: str, held: Dict[str, Any]) -> None:
        """Go back to before a message of the person (1.6.109). `plan.at`: when its restore point was taken; its turn is the one the person started nearest before it. `plan.dry`: only
        say how many turns would go. Else `plan.restore()` puts the files back (given by the board), and then the chat is cut before that turn; the turn not found, nothing is done.
        Read again in full first: the board keeps only the last turns."""
        plan = job.plan or {}
        link.unsubscribe(chat)
        full = link.subscribe(chat)
        with self.lock:
            held["state"] = ahp.trimmed(full)
        if full.get("activeTurn"):
            raise Refused("not-idle")
        turns = [turn for turn in full.get("turns") or [] if isinstance(turn, dict)]
        index = turn_at(turns, plan.get("at"))
        if index is None:
            raise Refused("rewind-turn")
        message = turns[index].get("message") if isinstance(turns[index].get("message"), dict) else {}
        job.result = {"turns": len(turns) - index, "text": str(message.get("text") or ""), "files": [str(item["label"]) for item in message.get("attachments") or [] if isinstance(item, dict) and item.get("label")]}
        if plan.get("dry"):
            return
        job.result["changed"] = plan["restore"]() if callable(plan.get("restore")) else {}
        action: Dict[str, Any] = {"type": "chat/truncated"}
        if index > 0:
            action["turnId"] = turns[index - 1].get("id")
        link.dispatch(chat, action)
        ahp.reduce_chat(full, action)
        with self.lock:
            held["state"] = ahp.trimmed(full)
            held["rev"] = held.get("rev", 0) + 1
            self.dirty = True

    def _again(self, link: ahp.Connection, job: Job, chat: str, held: Dict[str, Any]) -> None:
        """Try again (`resume`): the last turn ended in an error the host can retry, and it runs again. Take back (`unqueue`): one queued message leaves the queue, and its words come back.
        Both act only on what the chat holds now; anything else is refused."""
        with self.lock:
            if job.kind == "resume":
                turn = ahp.resumable_turn(held["state"])
                if not turn:
                    raise Refused("no-retry")
                action: Dict[str, Any] = {"type": "chat/turnResume", "turnId": turn}
                job.result = {"chat": chat, "turn": turn}
            else:
                ident = str((job.plan or {}).get("id") or "")
                found = next((item for item in ahp.queued(held["state"]) if item["id"] == ident), None)
                if found is None:
                    raise Refused("queue-gone")
                action = {"type": "chat/pendingMessageRemoved", "kind": "queued", "id": ident}
                job.result = {"chat": chat, "text": found["text"]}
        link.dispatch(chat, action)
        with self.lock:
            ahp.reduce_chat(held["state"], action)
            held["rev"] = held.get("rev", 0) + 1
            self.dirty = True

    def _respond(self, link: ahp.Connection, job: Job, binding: Dict[str, Any]) -> None:
        """Allow, deny or answer one waiting item of the chat of a task. The session is read again from the host first, and the item must be there, in this chat, and be what the page
        showed (the same `digest`): else nothing is sent. The person confirms one `toolCallId` (or one request), never whatever is pending."""
        plan = job.plan or {}
        if str(plan.get("id") or "").startswith(chatask.SUB):
            return self._respond_sub(link, job, binding)
        with self.lock:
            held = self.sess.get(binding["session"])
            channel = held["channel"] if held else ""
            subs = {target["chat"] for target in self._sub_targets(binding)}
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
        if item is None or item.get("chat") not in ({binding["chat"]} | subs):
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

    def _say(self, link: ahp.Connection, job: Job, binding: Dict[str, Any]) -> None:
        """1.8.4: the person writes while the agent waits for the answer to its question. The session is read again; the questions of this chat are all skipped, then the words go in as a steering
        message (a steer alone does not unblock a waiting question: measured in 1.8.3). A confirmation of the chat waiting makes it `confirm-waits`; no question makes it `ask-gone`: nothing is sent."""
        with self.lock:
            held = self.sess.get(binding["session"])
            channel = held["channel"] if held else ""
        if held is None or not channel:
            raise Refused("ask-gone")
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
        mine = [item for item in fresh.get("inputNeeded") or [] if isinstance(item, dict) and item.get("chat") == binding["chat"]]
        if any(item.get("kind") == chatask.CONFIRM for item in mine):
            raise Refused("confirm-waits")
        asks = [item for item in mine if item.get("kind") == chatask.CHAT_INPUT and isinstance(item.get("request"), dict) and item["request"].get("id")]
        if not asks:
            raise Refused("ask-gone")
        actions = [action for item in asks for action in chatask.skip_actions(item)]
        message: Dict[str, Any] = {"text": job.text, "origin": {"kind": "user"}}
        if job.model:
            message["model"] = job.model
        if job.attachments:
            message["attachments"] = job.attachments
        steer = {"type": "chat/pendingMessageSet", "kind": "steering", "id": str(uuid.uuid4()), "message": message}
        if job.cancelled:
            raise Refused("timeout")
        for action in actions:
            link.dispatch(binding["chat"], action)  # a failure here goes up before the words: they are not sent
        link.dispatch(binding["chat"], steer)
        with self.lock:
            for item in asks:
                ahp.reduce_session(held["state"], {"type": "session/inputNeededRemoved", "id": item["id"]})
            self._stamp(held)
            held["answered_at"] = time.monotonic()
            known = self.sessions.get(binding["session"])
            self.dirty = True
            title = str((known or {}).get("title") or binding.get("title") or "")
        titles = [chatask.one_line(question.get("title") or question.get("message") or question.get("id"), 80) for item in asks for question in item["request"].get("questions") or [] if isinstance(question, dict)]
        job.result = {"chat": binding["chat"], "title": title, "skipped": titles[:10], "text": job.text}

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
        self._adopt(link, entries)
        with self.lock:
            sessions = dict(self.sessions)
            wanted = chatlink.wants_scan(entries, sessions, self.sdk, chatlink.decide(entries, sessions, self.sdk))  # from the tasks as they are now, not the binding of the last look
        if wanted:
            self._scan(link, sessions)
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

    def _adopt(self, link: ahp.Connection, entries: List[Dict[str, Any]]) -> None:
        """A chat the board made is bound to its task as soon as the agent has made the task (an open task of that name): `chat.how = "board"`, and the model of the dialog on the task, so that
        the next messages carry it. The first message goes to `.task/sent.jsonl` and the history. A chat whose task never came is let go after `chatnew.KEEP_PENDING`; the SDK binding (the
        session id of the task, found in the chat) still works for it."""
        with self.lock:
            waiting = list(self.created)
        if not waiting:
            return
        by_name = {str(entry.get("name") or ""): entry for entry in entries}
        for made in waiting:
            if not made.get("chat"):  # 1.8.7: VS Code has not made it yet (or the connection went): it is waited for, with no limit
                continue
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
            self._name_chat(link, made["chat"], str(entry.get("name") or ""))
            try:
                chatsend.record(self.root, entry["task"], {"at": utc_now(), "task": entry["task"], "kind": "create", "chat": made["chat"], "text": made["text"], "lang": made["lang"],
                                                           "source": made["source"], "model": made["model"] or {}, "permission": made["permission"], "files": made.get("files") or []})
                with task_ops.locked(self.root, entry["task"]) as data:
                    task_ops.note(data, "create", chatsend.summary(made["text"]))
            except Exception:  # noqa: BLE001 - the binding is made; a missing line of history must not undo it
                pass
            if made.get("then"):
                with self.lock:
                    self.follow[entry["task"]] = {"text": made["then"], "model": made["model"], "chat": made["chat"], "clock": time.monotonic()}

    @staticmethod
    def _name_chat(link: ahp.Connection, chat: str, name: str) -> None:
        """A chat the board made for a task takes the task's name as its title, so the person finds it in VS Code (1.6.99). The host keeps a title a client set and makes none over it.
        A chat a person made in VS Code keeps the title it has."""
        if not name:
            return
        try:
            link.dispatch(chat, {"type": "session/titleChanged", "title": name[:120]})
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError:
            pass  # a title is a help, not the binding

    def _forget(self, made: Dict[str, Any]) -> None:
        with self.lock:
            self.created = [item for item in self.created if item is not made]

    def _scan(self, link: ahp.Connection, sessions: Dict[str, Dict[str, Any]]) -> None:
        """Read chats for their Copilot ids, when a task needs one (`chatlink.wants_scan`). A chat with no id is read again when it changed, or every `RESCAN_BUSY` while it is at work:
        a chat read before its first model call has no id yet, and the host may change its `modifiedAt` only when the turn ends (1.6.111)."""
        now = time.monotonic()
        wanted = sorted(sessions.values(), key=lambda item: str(item.get("modifiedAt") or ""), reverse=True)[:SCAN_MAX]
        todo = []
        for item in wanted:
            resource = item["resource"]
            if item.get("defaultChat") in self.chats or not item.get("defaultChat"):
                continue  # a chat held here is left alone: the unsubscribe below would end its updates, and nothing would subscribe it again
            if resource not in self.scanned:
                todo.append(item)
            elif not self.sdk.get(resource) and (self.scanned[resource] != item.get("modifiedAt")
                                                 or (ahp.status_name(item.get("status")) in ("busy", "input") and resource in self.read_at and now - self.read_at[resource] >= RESCAN_BUSY)):
                todo.append(item)
        for item in todo[:SCAN_PER_TURN]:
            resource, chat = item["resource"], item["defaultChat"]
            try:
                ids = ahp.sdk_ids(link.subscribe(chat))
                link.unsubscribe(chat)
                self.read_at[resource] = time.monotonic()
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                ids = set()  # this chat cannot be opened now: it is not read again until it changes
                self.read_at.pop(resource, None)
            with self.lock:
                self.sdk[resource] = ids
                self.scanned[resource] = str(item.get("modifiedAt") or "")
            self.dirty = True

    def _respond_sub(self, link: ahp.Connection, job: Job, binding: Dict[str, Any]) -> None:
        """Allow or deny a tool call that waits in the chat of a running subagent (1.8). The chat is read again from the host; the call must still be pending there, the call of the subagent must still run
        in the chat of the task, and it must be what the page showed. The decision goes to the subagent's chat, not to the chat of the task."""
        plan = job.plan or {}
        parts = str(plan.get("id") or "").split("|")
        chat = parts[1] if len(parts) == 3 else ""
        with self.lock:
            target = next((item for item in self._sub_targets(binding) if item["chat"] == chat), None)
        if target is None or job.kind != "confirm":
            raise Refused("ask-gone")
        try:
            link.unsubscribe(chat)
        except ahp.ConnectionClosed:
            raise
        except ahp.AhpError:
            pass
        fresh = ahp.trimmed(link.subscribe(chat))
        with self.lock:
            cached = self.chats.get(chat)
            if cached is None:
                cached = self.chats[chat] = {"state": fresh, "tool_at": ""}
            cached["state"] = fresh
            cached["rev"] = cached.get("rev", 0) + 1
        item = chatask.sub_item(chat, target["agent"], fresh)
        if item is None or item["id"] != plan.get("id"):
            raise Refused("ask-gone")
        view = chatask.shown(item)
        if view is None or view["kind"] != "confirm" or view["digest"] != plan.get("digest") or view["tool_call_id"] != plan.get("key"):
            raise Refused("ask-changed")
        if job.cancelled:
            raise Refused("timeout")
        link.dispatch(chat, chatask.confirm_action(item, bool(plan.get("approved"))))
        with self.lock:
            for call in self._running_calls(cached["state"]):
                if call.get("toolCallId") == view["tool_call_id"]:
                    call["status"] = ("completed" if plan.get("approved") else "cancelled") if view.get("stage") == "result" else "running" if plan.get("approved") else "failed"  # the card goes at once; the host pushes the same
            self.sub_seen.pop(item["id"], None)
            self.dirty = True
            known = self.sessions.get(binding["session"])
            title = str((known or {}).get("title") or binding.get("title") or "")
        job.result = {"chat": chat, "title": title, "view": view, "line": ""}

    def _subscribe(self, link: ahp.Connection) -> None:
        with self.lock:
            wanted = {binding["chat"]: binding["session"] for binding in self.bound.values() if binding.get("chat")}
            wanted.update({item["chat"]: item["session"] for item in self.created if item.get("chat")})  # a chat the board just made stays subscribed until its task is bound
            if self.super_chat:
                wanted[self.super_chat["chat"]] = self.super_chat["session"]  # 1.8.1: the super agent chat, so its replies are read from the cache
            wanted.update({sub["chat"]: binding["session"] for binding in self.bound.values() if binding.get("chat") for sub in self._subs_of(binding)})  # what its subagents do (1.6.105)
            wanted.update({target["chat"]: binding["session"] for binding in self.bound.values() if binding.get("chat") for target in self._sub_targets(binding)})  # 1.8: the chat of a subagent whose call runs: for its confirmations
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
                self.sub_seen = {key: when for key, when in self.sub_seen.items() if key.split("|")[1:2] != [chat]}
        for chat in set(wanted) - have:
            try:
                full = link.subscribe(chat)
                state = ahp.trimmed(full)
            except ahp.ConnectionClosed:
                raise
            except ahp.AhpError:
                continue
            with self.lock:
                self.chats[chat] = {"state": state, "tool_at": ""}
                owner = self._stream_task(chat) if self.persist else None
            if owner is not None:  # 1.8.x: the finished turns of this chat that the task's stream does not hold yet (the file work is done outside the lock)
                try:
                    self.stream_lost += chatstream.append(self.root, owner[0], chatstream.backfill(full, chat, chatstream.known(self.root, owner[0]).get(chat, set()), owner[1]))
                except Exception:  # as in `_notice`: never in the way of the chat
                    self.stream_lost += 1
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
                except ahp.AhpError:
                    continue
            with self.lock:
                self.sess[resource] = held
                self._stamp(held)
