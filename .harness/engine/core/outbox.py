"""The outbox (M43-4): a call to an outside system the policy marks `outbox` waits for a person.

The gate refuses the call, records it with a code (approvals.py, file action-approvals.json) and, in a session that holds a
task, writes a draft into the task: `OUTBOX/<code>-<system>.md`, the action and the exact command. Only the CLI writes there
(gate.json, cli_owned_paths), so the draft is what the person approves. The person runs `approve-action`, reads the command
and types the code. Then the same command, in the same session, runs once within the time limit; a changed command is a
new draft with a new code. The state line of the draft follows: waiting, approved, sent.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import sys
from typing import Callable, List

from . import approvals, config, messages, pinfiles
from .paths import utc_now
from .systems import place

FOLDER = "OUTBOX"
STATE_MARK = "<!-- state -->"
_STATE_LINE = re.compile(r"^.*" + re.escape(STATE_MARK) + r"\s*$", re.MULTILINE)


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def draft_path(task: str, code: str, system: str) -> str:
    return f"{task}/{FOLDER}/{code}-{system}.md"


def write_draft(root: Path, task: str, code: str, action: Any, command: str, session_id: str, minutes: int) -> str:
    """The draft of one outside call in the task folder; kept as it is when the same call asks again. Returns its path."""
    relative = draft_path(task, code, action.system)
    path = root / relative
    if path.exists():
        return relative
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        say("outbox.draft.title", code=code, place=place(action.system, action.env)),
        "",
        f"- {say('outbox.draft.state')}: {say('outbox.state.waiting')} {STATE_MARK}",
        f"- {say('outbox.draft.verb')}: {action.verb}" + ("" if getattr(action, "named", True) else f" ({say('outbox.draft.unnamed')})"),
        f"- {say('outbox.draft.target')}: {action.target or '-'}",
        f"- {say('outbox.draft.session')}: {session_id}",
        f"- {say('outbox.draft.asked_at')}: {utc_now()}",
        "",
        f"## {say('outbox.draft.command')}",
        "",
        "```",
        command,
        "```",
        "",
        say("outbox.draft.how", code=code, minutes=minutes),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return relative


_SEPARATORS = re.compile(r"\n|;|&&|\|\||\|")


def merge_into_waiting(root: Path, task: str, session_id: str, command: str, action: Any, minutes: int, offers: Optional[List[Dict[str, Any]]] = None, cwd: str = "") -> str:
    """The code of a waiting card this command takes over, or "" (1.7.27). The agent sent a line of several commands (a read, then a write); it was held whole. It then sends the write alone:
    the same write, the same task, not yet approved. That is the same card, not a second one: the waiting entry gets the short command, keeps its code, and its draft is written again."""
    text = approvals.collapse(command)
    if not task or not text or _SEPARATORS.search(text):
        return ""
    waiting = pending_for(root, task)
    if any(approvals.collapse(str(item.get("command", ""))) == text for item in waiting):
        return ""  # the short command already has its card
    for item in waiting:
        old = str(item.get("command", ""))
        parts = [approvals.collapse(part) for part in _SEPARATORS.split(old)]
        if old == text or len(parts) < 2 or text not in parts or item.get("system", "") != action.system:
            continue
        if approvals.rewrite(root, str(item["code"]), session_id, text, minutes, extra=entry_extra(action, task, offers, cwd), file=approvals.ACTIONS):
            try:
                (root / draft_path(task, item["code"], action.system)).unlink()
            except OSError:
                pass
            write_draft(root, task, item["code"], action, text, session_id, minutes)
            return str(item["code"])
    return ""


def mark(root: Path, relative: Optional[str], state: str, reason: str = "") -> None:
    """Set the state line of a draft: `approved` or `sent`, with the time (`dismissed` with the reason, when there is one). A draft that is gone is left alone."""
    if not relative:
        return
    path = root / relative
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    key = f"outbox.state.{state}"
    words = say(key, at=utc_now()) + (say("outbox.state.reason", reason=say(f"outbox.reason.{reason}")) if reason in REASONS else "")
    line = f"- {say('outbox.draft.state')}: {words} {STATE_MARK}"
    path.write_text(_STATE_LINE.sub(lambda _match: line, text, count=1), encoding="utf-8")


def entry_extra(action: Any, task: Optional[str], offers: Optional[List[Dict[str, Any]]] = None, cwd: str = "") -> Dict[str, Any]:
    """What the person sees in `approve-action` besides the command. The draft is `draft_of(entry)`. `offers` (1.7.38): the connections of the line that the card may open for the task
    (`{system, env, scope: all|items, refs?}`); a request to open one is accepted only for a connection named here. `cwd` (1.7.38): where the agent's terminal was, to find the files the line names."""
    extra = {"system": action.system, "env": action.env, "verb": action.verb, "target": action.target, "task": task or "", "cwd": cwd or ""}
    if not getattr(action, "named", True):
        extra["named"] = False  # no verbs rule matched: the card and the draft say so
    if offers:
        extra["offers"] = offers
    return extra


def offer_for(root: Path, task: str, code: str, name: str) -> Optional[Dict[str, Any]]:
    """The offer of the held call with this code, for this connection (1.7.38): what the card's "Open <name> for this task" may ask. None when the code names no call of this task that waits for
    the person, or the call offers nothing for that connection. This is what binds an opening to a real held call: the board checks it, and the agent cannot ask the board."""
    entry = next((item for item in pending_for(root, task) if str(item.get("code")) == str(code or "").strip().upper()), None)
    if not entry:
        return None
    return next((dict(one) for one in entry.get("offers") or [] if isinstance(one, dict) and one.get("system") == name), None)


def draft_of(entry: Dict[str, Any]) -> str:
    """The draft of an approval entry: only a call made in a session that held a task has one."""
    return draft_path(entry["task"], entry["code"], entry.get("system", "")) if entry.get("task") else ""


GATE_POLICY = "gate"


def pending_for(root: Path, task: str) -> List[Dict[str, Any]]:
    """The calls of this task that wait for the person, oldest first: the pending entries of the action approvals whose `task` is this one, within the time limit."""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    found = [item for item in approvals.pending(root, minutes, file=approvals.ACTIONS) if item.get("task") == task]
    return sorted(found, key=lambda item: str(item.get("created_at", "")))


WAIT_FRESH_S = 20  # a wait on a code that wrote its beat within this is running (it writes one every 5 seconds)
START_GRACE_S = 120  # a call held this long ago may have no wait yet: the agent is on its way to run it


def running_wait(item: Dict[str, Any], now: Optional[float] = None) -> bool:
    """Is the agent's `harness wait --approval` on this held call running now (1.7.38)? Its beat is fresh. A wait whose terminal was stopped stops beating and is not running."""
    wait = item.get("wait") if isinstance(item.get("wait"), dict) else {}
    now = time.time() if now is None else now
    try:
        return wait.get("state") == "running" and now - float(wait.get("beat", 0)) <= WAIT_FRESH_S
    except (TypeError, ValueError):
        return False


def agent_place(item: Dict[str, Any], now: Optional[float] = None) -> str:
    """Where the agent stands towards this held call (1.7.38, C11 Q21): `wait` (its `harness wait --approval` on the code is running), `ended` (its wait ran out and it was told to end its turn and say what waits
    for this card; a call held a moment ago counts too, for the agent has had no time to start its wait), or `away` (it did neither: it went on, or it delivered the work: `agent_left`)."""
    now = time.time() if now is None else now
    wait = item.get("wait") if isinstance(item.get("wait"), dict) else {}
    if running_wait(item, now):
        return "wait"
    if wait.get("state") == "timeout":
        return "ended"
    try:
        return "ended" if not wait and now - float(item.get("at", 0)) <= START_GRACE_S else "away"
    except (TypeError, ValueError):
        return "away"


def agent_left(root: Path, task: str) -> int:
    """The agent delivered the work of this task and stops (1.7.38, C12 TB-03): a held call it never started a wait on is a call it went on without, at once, not after the grace of `START_GRACE_S`.
    A call it waits on, or ended its turn on, is left as it is. How many calls were marked."""
    count = 0
    try:
        minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
        for item in pending_for(root, task):
            if not isinstance(item.get("wait"), dict) and approvals.wait_mark(root, str(item.get("code")), "left", minutes, file=approvals.ACTIONS):
                count += 1
    except Exception:  # noqa: BLE001 - a mark that cannot be written must not stop a delivery
        pass
    return count


def agent_waits(item: Dict[str, Any], now: Optional[float] = None) -> bool:
    return agent_place(item, now) != "away"


def agent_waiting(root: Path, task: str) -> bool:
    """Does the agent of this task sit in `harness wait --approval` on one of its held calls (1.7.38)? It makes no tool call and calls no model then, so the task is not at work: it waits for the person,
    and the person can answer (the page would otherwise say "working" and refuse Approve for the minutes that the log shows no call). Never in the way of a look: a file that cannot be read says no."""
    try:
        minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
        now = time.time()
        return any(item.get("task") == task and running_wait(item, now) for item in approvals.pending(root, minutes, file=approvals.ACTIONS))
    except Exception:  # noqa: BLE001
        return False


def moved_on(root: Path, entries: List[Dict[str, Any]]) -> set:
    """The codes of held calls the agent does not wait for (1.7.38; before it guessed from the commands the agent ran after the held one). The gate tells the agent to run
    `harness wait --approval <code>` and to end its turn when that runs out; an agent that did neither has gone on without this call. Such a call stays in the outbox, the person may still
    approve or dismiss it, but the task is not "waiting for you" because of it."""
    now = time.time()
    return {str(item.get("code")) for item in entries if not agent_waits(item, now)}


def opened_for(root: Path, task: str) -> List[Dict[str, Any]]:
    """The held calls of this task whose connections the person has opened from the card, and the agent has not run again yet (1.7.38), oldest first. Not approvals: the command is judged anew."""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    found = [item for item in approvals.opened_all(root, minutes, file=approvals.ACTIONS) if item.get("task") == task]
    return sorted(found, key=lambda item: str(item.get("opened_at", "")))


def mark_opened(root: Path, task: str, code: str, names: List[str]) -> Optional[Dict[str, Any]]:
    """The card of a held call opened these connections for the task (1.7.38): see `approvals.mark_opened`. The draft says what happened."""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    done = approvals.mark_opened(root, str(code or ""), names, minutes, file=approvals.ACTIONS)
    if done and done.get("state") == "opened":
        mark(root, draft_of(done), "opened")
    return done


def mark_opened_everywhere(root: Path, task: str, names: List[str]) -> int:
    """A connection is open for the task now (1.7.38): every held call of the task that offered it has done its part, not only the card the button was on. How many entries changed."""
    changed = 0
    for item in pending_for(root, task):
        reached = [name for name in names if any(isinstance(one, dict) and one.get("system") == name for one in item.get("offers") or [])]
        if reached and mark_opened(root, task, str(item["code"]), reached):
            changed += 1
    return changed


def settle_opened(root: Path, task: str, command: str) -> int:
    """The agent runs a command again whose connection was opened from its card: the green card goes (1.7.38)."""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    return approvals.settle(root, task, command, minutes, file=approvals.ACTIONS)


def approved_for(root: Path, task: str) -> List[Dict[str, Any]]:
    """The calls of this task that the person approved and the agent has not run yet (the approval is used up when the command runs), oldest approval first."""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    found = [item for item in approvals.approved_all(root, minutes, file=approvals.ACTIONS) if item.get("task") == task]
    return sorted(found, key=lambda item: str(item.get("approved_at", "")))


def approve_action(root: Any, reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None) -> Dict[str, Any]:
    """Show the outside calls waiting in the outbox, then approve the one whose code is typed. Terminal only, like `approve-command`; the board calls it with `interactive=True` and the code
    typed on the page (1.7.7). The draft of the entry is marked approved."""
    out = out or sys.stdout
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise ValueError(say("gate.action.terminal_only"))
    minutes = approvals.minutes(config.load_policy(root, GATE_POLICY))
    waiting = approvals.pending(root, minutes, file=approvals.ACTIONS)
    if not waiting:
        raise ValueError(say("gate.action.none", minutes=minutes))
    print(say("gate.action.header", minutes=minutes), file=out)
    for number, item in enumerate(waiting, 1):
        draft = draft_of(item)
        print(say(
            "gate.action.item", number=number, place=place(item.get("system", "?"), item.get("env", "?")), verb=item.get("verb", "?"),
            target=f" {item['target']}" if item.get("target") else "", session_id=item["session_id"], created_at=item["created_at"],
            draft=f"; {draft}" if draft else "",
        ), file=out)
        print(f"      {item['command']}", file=out)
    answer = (reader or input)(say("gate.action.prompt")).strip()
    chosen = next((item for item in waiting if str(item.get("code")) == answer.upper()), None) if answer else None
    kept = pinfiles.pins(str(chosen["command"]), Path(root), str(chosen.get("task") or ""), str(chosen.get("cwd") or "")) if chosen else {}  # the files the line names, as the person read them (1.7.38, C12 TB-05)
    done = approvals.approve(root, answer, minutes, file=approvals.ACTIONS, files=kept) if answer else None
    if done is None:
        raise ValueError(say("gate.action.refused"))
    mark(Path(root), draft_of(done), "approved")
    return {"approved": True, "command": done["command"], "system": done.get("system", ""), "valid_minutes": minutes, "draft": draft_of(done), "next": say("gate.action.next")}


REASONS = ("command", "connection", "later", "other_way")  # why the person did not approve (1.7.38): the command is wrong, a wrong connection or environment, not now, do it another way
LINE_REASONS = ("command", "other_way")  # these two may carry a line of the person's own words
NOTE_CHARS = 500


def dismiss_action(root: Path, code: str, interactive: Optional[bool] = None, reason: str = "", note: str = "") -> Dict[str, Any]:
    """The person says no to a held call (the board, 1.7.7): the entry goes, the draft says dismissed. Nothing is run. `reason` (1.7.38, one of REASONS, or none) and `note` (a line, for the two reasons
    that take one) are what the agent is told: at once by its wait on the code, else by a message from the board when it has a reason (the board decides; `agent` says where the agent stood)."""
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        raise ValueError(say("gate.action.terminal_only"))
    reason = str(reason or "").strip()
    if reason and reason not in REASONS:
        raise ValueError(say("gate.action.reason.bad", reasons=", ".join(REASONS)))
    note = " ".join(str(note or "").split())[:NOTE_CHARS] if reason in LINE_REASONS else ""
    minutes = approvals.minutes(config.policy_or_empty(root, GATE_POLICY))
    before = approvals.find(root, code, minutes, file=approvals.ACTIONS)
    done = approvals.dismiss(root, code, minutes, file=approvals.ACTIONS, reason=reason, note=note)
    if done is None:
        raise ValueError(say("gate.action.refused"))
    mark(root, draft_of(done), "dismissed", reason=reason)
    return {"dismissed": True, "code": done["code"], "command": done["command"], "system": done.get("system", ""), "task": done.get("task", ""), "draft": draft_of(done), "reason": reason, "note": note,
            "agent": agent_place(before or done), "next": say("gate.action.dismissed")}


def reason_text(reason: str, note: str = "") -> str:
    """The reason in words, for the agent and the draft: the kind, then the person's line."""
    words = say(f"outbox.reason.{reason}") if reason in REASONS else say("outbox.reason.none")
    return f"{words}: {note}" if note else words


def decided(entry: Dict[str, Any], minutes: int = approvals.DEFAULT_MINUTES) -> Dict[str, Any]:
    """What `harness wait --approval` answers once the person decided: the facts of the entry and the text for the agent (1.7.38). `state`: approved, opened or dismissed."""
    state = entry.get("state")
    if state == "approved":
        return {"approved": True, "state": "approved", "next": say("wait.approval.approved", minutes=minutes)}
    if state == "opened":
        names = ", ".join(str(name) for name in entry.get("opened_for") or [])
        return {"approved": False, "state": "opened", "opened": True, "names": names, "next": say("wait.approval.opened", names=names)}
    reason, note = str(entry.get("reason") or ""), str(entry.get("note") or "")
    why = reason_text(reason, note)
    return {"approved": False, "state": "dismissed", "dismissed": True, "reason": reason or "none", "note": note, "why": why, "next": say("wait.approval.not_approved", why=why, follow=follow_text(reason)), "exit_code": 1}


def follow_text(reason: str) -> str:
    """What the agent is to do after a call was not approved, by the reason (the rules for the agent: one source, here)."""
    return say(f"wait.approval.follow.{reason}") if reason in REASONS else say("wait.approval.follow.none")


def wake_dismissed(entry: Dict[str, Any]) -> str:
    """The message the board sends to an agent whose turn ended on a call the person did not approve, and gave a reason for (1.7.38)."""
    reason, note = str(entry.get("reason") or ""), str(entry.get("note") or "")
    return say("wake.dismissed", code=str(entry.get("code") or ""), why=reason_text(reason, note), follow=follow_text(reason))
