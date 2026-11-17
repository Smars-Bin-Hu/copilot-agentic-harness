"""The super agent chat (1.8.1, steps 5 and 7): one Copilot chat that the board opens and owns. It only talks to the person about their tasks; it never works. Code decides when to call it and what to send.

  digest   `digest(view)`: one short text from `superview.build(rows)`, at most DIGEST_CHARS. Names, states, what waits and for how long; no file body, no long text.
  chat     one a local day (the next day, a new one), made with the custom agent `.github/agents/super.agent.md` and Claude Haiku 5.5, Allow all. The link (`vslink`) makes it and sends to it on its thread;
           the chat stays subscribed, so replies are read from the link's cache. What is kept of it: `.harness/runtime/super.json` (the chat, the conversation of the day, what each turn cost).
  turn     `ask(text)` / `summary()`: `/harness-super` (the mark the gate knows the chat by), the digest, then the person's words. Refused, with the reason in `why`, when VS Code is not linked (`asleep`),
           when the day's spend reached the limit (`limit`), or when a turn is running (`busy`). `empty`, `long`, `timeout` and `error` are the other reasons.
  talk     `talk()`: the state (`asleep`, `thinking`, `tired`, `idle`), the Credits spent today, the limit, and the conversation read back from the turns of the chat.
  history  When a new day starts, the conversation of the day before is kept in `.harness/runtime/super-history/<day>.json` (what was said, and what the day spent) before `super.json` starts again.
           `history()` lists the days, newest first; `history_day(day)` reads one back; `history_act(day, action)` archives one (into `archived/`, hidden from the list), restores it, or deletes it.
           Today is never in the history: its record holds the spend of the day, so the daily limit cannot be undone by a delete. Nothing is deleted by itself.
  spend    The Credits of the day: the sum of the `usage._meta.copilotUsage.totalNanoAiu` of the turns that ended, or what the events file of the chat's Copilot session says (read from where it was last read,
           `autorun_spend.lines_of`), whichever is more. The limit is `super.daily_credits` of `policies/task.json` (50). At the limit nothing new is sent; code notices are not affected.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import ahp, config, copilot_events
from core.paths import runtime_dir, utc_now
from core.state import atomic_write

from . import autorun_spend, superview, vslink

MARKER = "/harness-super"  # the same as `modules/gate/superagent.MARKER`: the gate knows the chat by its first message
AGENT_FILE = ".github/agents/super.agent.md"
MODEL_ID = "claude-haiku-5.5"
APPROVE = "autoApprove"  # `config.autoApprove` of the host; the tools the agent has are only read ones
DIGEST_CHARS = 2000
MAX_TEXT = 1000  # characters of what the person types
CLIP_NAME, CLIP_TITLE = 60, 100
DEFAULT_LIMIT = 50.0  # Credits a local day
LOST_AFTER = 180.0  # seconds after which a turn that the chat does not show and that does not run is given up
NANO = copilot_events.NANO
SUMMARY_ASK = "Give a short summary of what waits for me now, most urgent first."
SUMMARY_SHOWN = "Summary of what waits"
STATES = {"you": "needs the person", "work": "working", "idle": "idle"}


def file_of(root: Path) -> Path:
    return runtime_dir(root) / "super.json"


DAY = re.compile(r"\d{4}-\d{2}-\d{2}$")
ACTIONS = ("archive", "restore", "delete")


def history_dir(root: Path, archived: bool = False) -> Path:
    base = runtime_dir(root) / "super-history"
    return base / "archived" if archived else base


def messages_of(exchanges: List[Dict[str, Any]], partial: str = "") -> List[Dict[str, Any]]:
    """The person's and the agent's messages of a day, oldest first: `{id, role: you|agent, text, at}`, `kind: summary` on a request for the summary, `end` on an answer that did not complete normally.
    `partial`: the running turn's text so far, for the last exchange that has no answer yet."""
    messages: List[Dict[str, Any]] = []
    for item in exchanges:
        messages.append({"id": item["turn"] + ":you", "role": "you", "text": item["you"], "at": item["you_at"], **({"kind": item["kind"]} if item.get("kind") != "ask" else {})})
        text = (item.get("agent") if item.get("end") else partial) or ""
        if item.get("end") or text:
            messages.append({"id": item["turn"] + ":agent", "role": "agent", "text": text, "at": item.get("agent_at") or item["you_at"], **({"end": item["end"]} if item.get("end") not in ("", "complete", None) else {})})
    return messages


def agent_uri(root: Path) -> str:
    return ahp.folder_uri(Path(root) / AGENT_FILE)


def limit_of(root: Path) -> float:
    found = (config.policy_or_empty(root, "task").get("super") or {}).get("daily_credits")
    return float(found) if isinstance(found, (int, float)) and not isinstance(found, bool) and found >= 0 else DEFAULT_LIMIT


# --- the digest ---------------------------------------------------------------------------------------------------------

def clip(text: Any, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def how_long(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
        return ""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h{minutes % 60:02d}m" if hours < 24 else f"{hours // 24}d{hours % 24}h"


def digest(view: Dict[str, Any], at: str = "") -> str:
    """The text the agent is given about the tasks, from `superview.build`: a head, then one line for each open task, the ones that wait for the person first (longest wait first). At most DIGEST_CHARS."""
    status, mates, items = view.get("status") or {}, view.get("mates") or [], view.get("items") or []
    by_task = {item["task"]: item for item in items}
    order = [mate for item in items for mate in mates if mate["task"] == item["task"]]
    order += [mate for mate in mates if mate["task"] not in by_task]
    head = f"Open tasks: {len(mates)} ({status.get('waiting', 0)} wait for the person, {status.get('working', 0)} working, {status.get('idle', 0)} idle)." + (f" As of {at}." if at else "")
    lines: List[str] = []
    size = len(head)
    for index, mate in enumerate(order):
        item = by_task.get(mate["task"])
        line = f"- {clip(mate['task'], CLIP_NAME)} ({clip(mate.get('kind'), 20)}): {STATES.get(mate['state'], mate['state'])}"
        if item:
            line += f" | waits for: {item['why']}" + (f" - {clip(item['title'], CLIP_TITLE)}" if item.get("title") else "") + (f" | {how_long(item.get('waited_s'))}" if how_long(item.get("waited_s")) else "")
        rest = len(order) - index - 1
        if size + len(line) + 1 + (len(f"(+{rest} more tasks not shown)") + 1 if rest else 0) > DIGEST_CHARS:
            lines.append(f"(+{len(order) - index} more tasks not shown)")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join([head] + lines) if lines else head + "\nNo task is open."


# --- the chat ------------------------------------------------------------------------------------------------------------

def turn_text(turn: Dict[str, Any]) -> str:
    """What the agent wrote in a turn: its text parts, in order."""
    return "\n".join(str(part.get("content") or "").strip() for part in turn.get("responseParts") or [] if isinstance(part, dict) and part.get("kind") == "markdown" and str(part.get("content") or "").strip())


def turn_nano(turn: Dict[str, Any]) -> Optional[float]:
    usage = turn.get("usage") if isinstance(turn.get("usage"), dict) else {}
    meta = usage.get("_meta") if isinstance(usage.get("_meta"), dict) else {}
    used = meta.get("copilotUsage") if isinstance(meta.get("copilotUsage"), dict) else {}
    return copilot_events.number(used.get("totalNanoAiu"))


class Brain:
    """One per board. `link`: the `VsLink`; `rows`: what `BoardServer.rows()` is (called when a digest is made); `now`: the local time (the tests set it)."""

    def __init__(self, root: Path, link: Any, rows: Callable[[], Dict[str, Any]], now: Optional[Callable[[], datetime]] = None) -> None:
        self.root = Path(root)
        self.link = link
        self.rows = rows
        self.now = now or datetime.now
        self.lock = threading.RLock()
        self.sending = False
        self.partial = ""  # what the running turn has written so far (memory only)
        self.watched = ""  # the chat the link was told to keep (memory only)

    # -- the file --

    def fresh(self) -> Dict[str, Any]:
        return {"day": self.now().date().isoformat(), "session": "", "chat": "", "sdk": "", "exchanges": [], "turn_nano": {}, "cost": {"session": "", "pos": 0, "nano": 0}, "prior_nano": 0}

    def load(self) -> Dict[str, Any]:
        """The record of today. A file of another day, or one that cannot be read, gives a new one (no chat: the next turn makes it)."""
        try:
            found = json.loads(file_of(self.root).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            found = None
        if not isinstance(found, dict) or found.get("day") != self.now().date().isoformat() or not isinstance(found.get("exchanges"), list):
            self.watched = ""
            if isinstance(found, dict) and isinstance(found.get("exchanges"), list) and DAY.match(str(found.get("day") or "")):  # a day that ended: into the history, then a new record
                fresh = self.fresh()
                if self.keep(found):
                    self.save(fresh)
                return fresh
            return self.fresh()
        base = self.fresh()
        base.update({key: found[key] for key in base if key in found})
        return base

    def keep(self, rec: Dict[str, Any]) -> bool:
        """Put a day that ended into the history (an empty day is not kept). False when it could not be written: `super.json` then stays as it is, and the next load tries again."""
        exchanges = [item for item in rec.get("exchanges") or [] if isinstance(item, dict) and item.get("turn")]
        if not exchanges:
            return True
        day = str(rec["day"])
        if (history_dir(self.root, True) / f"{day}.json").exists():
            return True  # kept before and archived since
        record = {"day": day, "spent": round(self.spent(rec), 3),
                  "exchanges": [{key: item.get(key) for key in ("turn", "kind", "you", "you_at", "agent", "agent_at", "end")} for item in exchanges]}
        try:
            atomic_write(history_dir(self.root) / f"{day}.json", record)
        except OSError:
            return False
        return True

    def save(self, rec: Dict[str, Any]) -> None:
        try:
            atomic_write(file_of(self.root), rec)
        except OSError:
            pass  # the day goes on in memory of the next load; the cost of a turn is read again from the events file

    # -- reading back --

    def sync(self, rec: Dict[str, Any]) -> bool:
        """Take what the chat shows into `rec`: the answers of turns that ended, what they cost, the Copilot session id; then the events file. True when `rec` changed."""
        changed = False
        if rec["chat"] and self.watched != rec["chat"] and self.link.status().get("ready"):
            self.link.super_watch(rec["session"], rec["chat"])
            self.watched = rec["chat"]
        view = self.link.super_view() if rec["chat"] else None
        self.partial = ""
        if view and view.get("state"):
            state = view["state"]
            ended = {str(turn.get("id")): turn for turn in state.get("turns") or [] if isinstance(turn, dict) and turn.get("id")}
            active = state.get("activeTurn") if isinstance(state.get("activeTurn"), dict) else None
            for item in rec["exchanges"]:
                if item.get("end"):
                    continue
                turn = ended.get(item["turn"])
                if turn is not None:
                    item.update(agent=turn_text(turn), agent_at=utc_now(), end=str(turn.get("state") or "complete"))
                    nano = turn_nano(turn)
                    if nano is not None:
                        rec["turn_nano"][item["turn"]] = nano
                    changed = True
                elif active is not None and str(active.get("id")) == item["turn"]:
                    self.partial = turn_text(active)
                elif active is None and time.time() - float(item.get("sent_ts") or 0) > LOST_AFTER:
                    item.update(agent="", agent_at=utc_now(), end="lost")
                    changed = True
            if not rec["sdk"]:
                found = sorted(ahp.sdk_ids(state))
                if found:
                    rec["sdk"] = found[-1]
                    changed = True
        return self.read_events(rec) or changed

    def read_events(self, rec: Dict[str, Any]) -> bool:
        """Move the cost forward from the events file of the Copilot session of the chat (new whole lines only). False when nothing is known or nothing moved."""
        if not rec["sdk"]:
            return False
        path = copilot_events.events_path(rec["sdk"])
        if path is None:
            return False
        cost = rec["cost"] if isinstance(rec.get("cost"), dict) else {}
        pos = int(cost.get("pos") or 0) if cost.get("session") == rec["sdk"] else 0
        nano = float(cost.get("nano") or 0) if cost.get("session") == rec["sdk"] else 0.0
        got = autorun_spend.lines_of(path, pos)
        if got is None:
            return False
        rows, end = got
        for row in rows:
            if row.get("type") == "session.usage_record":
                nano += autorun_spend.nano_of(row)
        moved = (end, nano) != (pos, float(cost.get("nano") or 0))
        rec["cost"] = {"session": rec["sdk"], "pos": end, "nano": nano}
        return moved

    @staticmethod
    def spent(rec: Dict[str, Any]) -> float:
        """Credits of the day: the turns that ended, or the events file, whichever is more (a turn that still runs is only in the file)."""
        return max(sum(float(value) for value in rec["turn_nano"].values()), float(rec.get("prior_nano") or 0) + float((rec.get("cost") or {}).get("nano") or 0)) / NANO

    def running(self, rec: Dict[str, Any]) -> bool:
        view = self.link.super_view() if rec["chat"] else None
        asked = any(not item.get("end") for item in rec["exchanges"])
        if view and view.get("state") is not None:  # the chat's own turns are the truth; the status of the session may still be the stub the board made it with
            return self.sending or asked or bool(view["state"].get("activeTurn"))
        return self.sending or asked or bool(view and view.get("status") in ("busy", "input"))

    # -- the page side --

    def talk(self) -> Dict[str, Any]:
        """`{state, spent, limit, messages}`: `state` is asleep (VS Code is not linked), thinking (a turn runs), tired (today's limit is reached) or idle; `messages`: the person's and the agent's, oldest first,
        as `messages_of` gives them (the running turn's text so far is shown as it grows)."""
        with self.lock:
            rec = self.load()
            if self.sync(rec):
                self.save(rec)
            limit, spent = limit_of(self.root), self.spent(rec)
            messages = messages_of(rec["exchanges"], self.partial)
            ready = bool(self.link.status().get("ready"))
            state = "asleep" if not ready else "thinking" if self.running(rec) else "tired" if spent >= limit else "idle"
            return {"state": state, "spent": round(spent, 3), "limit": limit, "messages": messages}

    # -- the history of earlier days --

    def history(self) -> Dict[str, Any]:
        """`{days: [{day, turns, spent, archived}]}`, newest first, the archived ones too (the page shows them on request). A file that cannot be read is left out."""
        with self.lock:
            self.load()  # a day that just ended goes into the history first
            days = []
            for archived in (False, True):
                folder = history_dir(self.root, archived)
                for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                    found = self.read_day(path)
                    if found:
                        days.append({"day": found["day"], "turns": len(found["exchanges"]), "spent": found.get("spent") or 0, "archived": archived})
            days.sort(key=lambda one: one["day"], reverse=True)
            return {"days": days}

    def read_day(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            found = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        if not isinstance(found, dict) or found.get("day") != path.stem or not isinstance(found.get("exchanges"), list):
            return None
        found["exchanges"] = [item for item in found["exchanges"] if isinstance(item, dict) and item.get("turn") and isinstance(item.get("you"), str)]
        return found

    def where(self, day: str) -> Optional[Path]:
        for archived in (False, True):
            path = history_dir(self.root, archived) / f"{day}.json"
            if path.is_file():
                return path
        return None

    def history_day(self, day: Any) -> Dict[str, Any]:
        """One earlier day: `{ok, day, spent, archived, messages}` (as `messages_of` gives them), or `{ok: false, why: missing}`."""
        day = str(day or "")
        with self.lock:
            self.load()  # a day that just ended goes into the history first
            path = self.where(day) if DAY.match(day) else None
            found = self.read_day(path) if path else None
            if not found:
                return {"ok": False, "why": "missing"}
            return {"ok": True, "day": day, "spent": found.get("spent") or 0, "archived": path.parent.name == "archived", "messages": messages_of(found["exchanges"])}

    def history_act(self, day: Any, action: Any) -> Dict[str, Any]:
        """Archive an earlier day (hidden from the list), restore it, or delete it for good. `{ok: true}`, or `{ok: false, why: missing | today | action | error}`."""
        day, action = str(day or ""), str(action or "")
        if action not in ACTIONS:
            return {"ok": False, "why": "action"}
        if day == self.now().date().isoformat():
            return {"ok": False, "why": "today"}
        with self.lock:
            self.load()
            path = self.where(day) if DAY.match(day) else None
            if not path:
                return {"ok": False, "why": "missing"}
            try:
                if action == "delete":
                    path.unlink()
                else:
                    target = history_dir(self.root, action == "archive") / f"{day}.json"
                    if target != path:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(path, target)
            except OSError:
                return {"ok": False, "why": "error"}
            return {"ok": True}

    def ask(self, text: Any) -> Dict[str, Any]:
        """The person's words go to the agent with the digest. `{ok: true}` or `{ok: false, why}`."""
        words = str(text or "").strip()
        if not words:
            return {"ok": False, "why": "empty"}
        if len(words) > MAX_TEXT:
            return {"ok": False, "why": "long"}
        return self.turn("ask", "Person asks: " + words, words)

    def summary(self) -> Dict[str, Any]:
        """A request for the short summary (the morning one, or when the person presses for it)."""
        return self.turn("summary", SUMMARY_ASK, SUMMARY_SHOWN)

    def turn(self, kind: str, request: str, shown: str) -> Dict[str, Any]:
        with self.lock:
            rec = self.load()
            if self.sync(rec):
                self.save(rec)
            if not self.link.status().get("ready"):
                return {"ok": False, "why": "asleep"}
            if self.spent(rec) >= limit_of(self.root):
                return {"ok": False, "why": "limit"}
            if self.running(rec):
                return {"ok": False, "why": "busy"}
            try:
                view = superview.build(self.rows())
            except Exception:  # noqa: BLE001 - no digest, no turn
                return {"ok": False, "why": "error"}
            self.sending = True
        message = f"{MARKER}\n{digest(view, self.now().strftime('%H:%M'))}\n\n{request}"
        done: Dict[str, Any] = {}
        why = ""
        try:
            done = self.send(rec, message)
        except vslink.Refused as error:
            why = "asleep" if error.why in ("off", "not-ready") else "busy" if error.why == "not-idle" else error.why
        except Exception as error:  # noqa: BLE001 - the host's words are not for the page
            why = "error"
            self.link.host_said(error)
        with self.lock:
            self.sending = False
            if why == "timeout":  # the chat may have been made after the wait ended: keep it, so the next ask does not make a second one
                made = getattr(self.link, "super_chat", None)
                rec = self.load()
                if isinstance(made, dict) and made.get("chat") and not rec["chat"]:
                    rec.update(session=str(made.get("session") or ""), chat=str(made["chat"]))
                    self.save(rec)
            if why:
                return {"ok": False, "why": why}
            rec = self.load()  # the day may have turned while the host was told: the turn belongs to the chat that got it
            if rec["chat"] and rec["chat"] != done["chat"]:  # a new chat in the same day: what the old one spent stays counted
                rec.update(prior_nano=float(rec.get("prior_nano") or 0) + float((rec.get("cost") or {}).get("nano") or 0), sdk="", cost={"session": "", "pos": 0, "nano": 0})
            rec.update(session=done["session"], chat=done["chat"])
            rec["exchanges"].append({"turn": done["turn"], "kind": kind, "you": shown, "you_at": utc_now(), "sent_ts": time.time(), "agent": None, "agent_at": "", "end": ""})
            self.watched = done["chat"]
            self.save(rec)
        return {"ok": True}

    def send(self, rec: Dict[str, Any], message: str) -> Dict[str, Any]:
        """Tell the link to send one turn, making the chat when today has none. A chat the host does not know any more (VS Code lost it) is made again, once."""
        models = self.link.model_list()
        found = next((item for item in models if item.get("id") == MODEL_ID), None)
        plan = {"session": rec["session"], "chat": rec["chat"], "agent": agent_uri(self.root), "model": ahp.model_choice(found) if found else {"id": MODEL_ID}, "approve": APPROVE}
        try:
            return self.link.super_send(plan, message)
        except vslink.Refused:
            raise
        except ahp.AhpError:
            if not (rec["session"] or rec["chat"]):
                raise
        return self.link.super_send(dict(plan, session="", chat=""), message)
