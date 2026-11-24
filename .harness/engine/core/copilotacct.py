"""The Copilot account of the person signed in to gh (1.8.38): this month's credits, the seat, the organization's switches. Python standard library only.

Read with `gh api /copilot_internal/user`, the endpoint Copilot's own editor extension reads for its quota. It is not documented and may change shape, so it is a helper:
- Only the fields named here are kept. Ids, the analytics id, the endpoints and the login are dropped; the token never leaves gh.
- Anything not as expected (gh missing, an error, a timeout, not JSON, too long, a field of another type) is no answer: the page then shows nothing of it, never a guess.
- gh runs at most once every KEEP seconds, on a thread of its own; a request gets what was last read and never waits for gh.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import ghauth

ENDPOINT = "/copilot_internal/user"
KEEP = 300  # seconds an answer is used before gh is asked again
RETRY = 60  # seconds after a failed read before the next try
TIMEOUT = 20  # seconds gh may take (a slow computer, a proxy)
MAX_BYTES = 256 * 1024  # a longer answer is not what we expect
NAME_KEEP = 200  # characters of one name (an organization, a plan)
NAMES_KEEP = 20  # names of organizations or enterprises kept
SWITCHES = ("cli_enabled", "is_mcp_enabled", "chat_enabled", "cloud_sessions_enabled")  # the organization's switches the harness depends on


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) < 1e15 else None  # not NaN, not absurd


def _text(value: Any) -> str:
    return value.strip()[:NAME_KEEP] if isinstance(value, str) else ""


def _names(value: Any) -> List[str]:
    """Names from a list of strings, or of objects with `login` or `name`."""
    out: List[str] = []
    for item in value if isinstance(value, list) else []:
        name = _text(item) if isinstance(item, str) else _text(item.get("login") or item.get("name")) if isinstance(item, dict) else ""
        if name and name not in out:
            out.append(name)
        if len(out) >= NAMES_KEEP:
            break
    return out


def credits_of(snapshot: Any) -> Optional[Dict[str, Any]]:
    """The premium credits of one quota snapshot: `{unlimited}` or `{unlimited: False, total, used, left, over, over_ok}`. None when it cannot be read as one."""
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("unlimited") is True:
        return {"unlimited": True}
    total = _number(snapshot.get("entitlement"))
    left = _number(snapshot.get("quota_remaining"))
    if left is None:
        left = _number(snapshot.get("remaining"))
    if total is None or total <= 0 or left is None:
        return None
    used = _number(snapshot.get("credits_used"))
    if used is None:
        used = total - left
    over = _number(snapshot.get("overage_count")) or 0.0
    return {"unlimited": False, "total": total, "used": max(0.0, used), "left": max(0.0, left), "over": max(0.0, over), "over_ok": snapshot.get("overage_permitted") is True}


def read(text: Any) -> Optional[Dict[str, Any]]:
    """What the page may show, from gh's answer. None when it is not the answer we know."""
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            return None
        text = text.decode("utf-8", "replace")
    if not isinstance(text, str) or len(text) > MAX_BYTES:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    snapshots = data.get("quota_snapshots") if isinstance(data.get("quota_snapshots"), dict) else {}
    found: Dict[str, Any] = {
        "plan": _text(data.get("copilot_plan")),
        "sku": _text(data.get("access_type_sku")),
        "since": _text(data.get("assigned_date")),
        "resets": _text(data.get("quota_reset_date_utc") or data.get("quota_reset_date")),
        "orgs": _names(data.get("organization_login_list")) or _names(data.get("organization_list")),
        "enterprises": _names(data.get("enterprise_list")),
        "credits": credits_of(snapshots.get("premium_interactions")),
        "taken": _text(((snapshots.get("premium_interactions") or {}) if isinstance(snapshots.get("premium_interactions"), dict) else {}).get("timestamp_utc")),
        "switches": {key: data[key] for key in SWITCHES if isinstance(data.get(key), bool)},
    }
    if not found["plan"] and found["credits"] is None and not found["switches"]:
        return None  # nothing we know: another answer (an error page, a changed shape)
    return found


def fetch(root: Any = None, extra: Optional[Dict[str, str]] = None, find: Callable[..., Optional[str]] = ghauth.find_gh, run: Callable[..., Any] = ghauth.run_gh) -> Optional[Dict[str, Any]]:
    """Ask gh once. None on any failure."""
    gh = find(ghauth.folders_of(root))
    if not gh:
        return None
    try:
        done = run(gh, ["api", ENDPOINT], timeout=TIMEOUT, extra=extra)
    except ghauth.GhError:
        return None
    if getattr(done, "returncode", 1) != 0:
        return None
    return read(getattr(done, "stdout", b""))


class Keeper:
    """The last answer, and a thread that asks gh again when it is old. `latest()` never waits."""

    def __init__(self, fetch_now: Callable[[], Optional[Dict[str, Any]]], clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 start: Callable[[Callable[[], None]], Any] = lambda job: threading.Thread(target=job, name="copilot-account", daemon=True).start()) -> None:
        self.fetch_now, self.clock, self.wall, self.start = fetch_now, clock, wall, start
        self.lock = threading.Lock()
        self.data: Optional[Dict[str, Any]] = None
        self.read_at = 0.0  # wall clock of the last good read, for "read 2 min ago"
        self.asked_at: Optional[float] = None  # monotonic clock of the last ask, good or not
        self.ok = False
        self.busy = False
        self.round = 0  # a read started before `forget()` is about the account before: its answer is dropped

    def _due(self, fresh: bool) -> bool:
        if self.busy:
            return False
        if self.asked_at is None or fresh:
            return True
        return self.clock() - self.asked_at >= (KEEP if self.ok else RETRY)

    def _job(self, round_: int) -> None:
        try:
            found = self.fetch_now()
        except Exception:  # noqa: BLE001 - a helper: a broken read shows nothing, it never stops the board
            found = None
        with self.lock:
            if round_ != self.round:
                return
            self.busy = False
            self.ok = found is not None
            if found is not None:
                self.data, self.read_at = found, self.wall()
            else:
                self.data = None  # an old answer is not shown as if it were true now

    def latest(self, fresh: bool = False) -> Dict[str, Any]:
        """`{state, account?, read_at?}`: `state` is `ok`, `reading` (first read under way) or `none` (could not be read)."""
        with self.lock:
            go = self._due(fresh)
            if go:
                self.busy, self.asked_at = True, self.clock()
            data, read_at, busy, round_ = self.data, self.read_at, self.busy, self.round
        if go:
            self.start(lambda: self._job(round_))
        if data is not None:
            return {"state": "ok", "account": data, "read_at": read_at, "reading": busy}
        return {"state": "reading" if busy else "none"}

    def forget(self) -> None:
        """After a sign-out or a sign-in: what was read is about another account, or none."""
        with self.lock:
            self.data, self.ok, self.asked_at, self.busy = None, False, None, False
            self.round += 1
