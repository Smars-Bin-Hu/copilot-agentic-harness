#!/usr/bin/env python3
"""harness-watch: a standalone monitor for the harness (hooks + local board). Python 3.9, standard library only, Windows and Mac (Linux too).

    python harness-watch.py [folder] [--every 15] [--once] [--detail CODE]

Every EVERY seconds it reads a few cheap sources, applies fixed diagnosis rules and redraws one screen (at most 40 lines, 100 columns).
Sources: the board's meter (`POST /api/meter`, one request a round, waited for up to 10 s; `/api/status` only until the board is identified), the
hook log (`.harness/runtime/logs/<surface>/<session>.jsonl`, new bytes only), Copilot's `events.jsonl` under `$COPILOT_HOME` or `~/.copilot` (new
bytes only), machine numbers by system calls (no process started), and one timed `python -S -c pass` at most every 5 minutes. The two log folders
are listed only once a minute; between listings only the files known to be active are looked at. It never writes into the harness folder; its
record file (numbers only) is in the system temp folder.

Rates: the meter keeps its own one-minute window (`min1`) and every log row has a time, so a screen needs no earlier screen for them.
`--once` therefore takes only a 2 s machine sample (CPU and busiest processes need two readings), not a second 15 s round.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

# --- the meter row names this script reads (one table: rename here when the board renames a row) --------------------------------------------------
ROWS = {
    "acts_done": "acts.done", "acts_failed": "acts.failed", "acts_fallback": "acts.fallback", "acts_running": "acts.running",
    "hs_queue": "hookserve.queue", "hs_judge": "hookserve.judge", "hs_call": "hookserve.call", "hs_late": "hookserve.late",
    "hs_refused": "hookserve.refused.", "hs_busy": "hookserve.busy",
    "longtask": "page.longtask", "longtask_max": "page.longtask",  # max_ms of page.longtask is the longest one (meter `peak`)
    "lag": "page.lag", "stream_open": "stream.open", "stream_poll": "stream.poll",
    "fc_stat": "fc.stat", "fc_hit": "fc.hit", "fc_miss": "fc.miss", "fc_pass": "fc.pass_hit",
    "build_full": "hub.build.full", "build_part": "hub.build.part", "build_light": "hub.build.light", "missed": "hub.missed",
    "part_same": "part.same.memo", "part_new": "part.computed",
    "bg": ("bg.link_look", "bg.sweep", "bg.ready", "bg.models"),
    "http": "http POST /api/",
}
# Rows of the newer meter. If none of them exists in a snapshot, the board's version is taken not to have the newer codes ("这一版没有"); if some do,
# a missing one means "has not happened yet" and counts as 0. (A counter row only appears at its first count.)
NEW_GEN = ("acts.", "hookserve.", "page.", "stream.open", "stream.poll")
BASE_GEN = ("fc.", "hub.", "http ", "bg.", "part.")  # rows every meter has once it counted something
# Requests that are held open or are this script's own: left out of "B1 接口耗时" and of "F5 后台的页面还在问".
LONG_REQUESTS = ("http POST /api/stream", "http POST /api/state", "http POST /api/live")
OWN_REQUESTS = ("http POST /api/meter", "http POST /api/status", "http POST /api/look", "http POST /api/notice")

# --- thresholds: initial value, calibrate after the 5/10/20-task runs ----------------------------------------------------------------------------
H1_MED_MS = 2000.0  # initial value, calibrate: PreToolUse median above this is slow
H1_MAX_MS = 10000.0  # initial value, calibrate
H2_SHARE = 0.5  # initial value, calibrate: queue share of H1 that makes it "queue"
H3_MS = 1000.0  # initial value, calibrate
H4_MS = 1000.0  # initial value, calibrate
H5_PCT = 5.0  # initial value, calibrate
B1_AVG_MS = 300.0  # initial value, calibrate
B1_MAX_MS = 3000.0  # initial value, calibrate
B2_PER_TASK_MIN = 300.0  # initial value, calibrate: file checks per minute per open task
B3_FULL_COST_S = 5.0  # initial value, calibrate: seconds of full rebuilds a minute before R6 speaks
B3_FULL_PER_MIN = 1.0  # initial value, calibrate
B3_EACH_S = 2.0  # initial value, calibrate
B5_PER_MIN = 1.0  # initial value, calibrate
B6_PER_MIN = 30.0  # initial value, calibrate
B8_MIN_RATIO = 0.8  # initial value, calibrate
F1_PER_MIN = 2.0  # initial value, calibrate
F1_MAX_MS = 200.0  # initial value, calibrate
F2_MS = 1000.0  # initial value, calibrate
F4_PCT = 30.0  # initial value, calibrate
M1_PCT, M1_RULE_PCT = 70.0, 90.0  # initial value, calibrate (normal, rule)
M2_PCT, M2_RULE_PCT = 85.0, 90.0  # initial value, calibrate
M3_S = 1.0  # initial value, calibrate
C1_FIRST_S, C1_RULE_S = 5.0, 10.0  # initial value, calibrate
A1_AVG_MS, A1_MAX_MS = 1000.0, 5000.0  # initial value, calibrate

WINDOW_S = 60.0  # hook log window
COPILOT_WINDOW_S = 120.0  # Copilot rows are rarer than hook rows: a wider window
KEEP_S = 600.0  # rows older than this are dropped from memory
RECENT_S = 3600.0  # only files changed in the last hour are read
FIRST_TAIL = 256 * 1024  # first sight of a file: its last 256 KB at most
READ_CAP = 2 * 1024 * 1024  # bytes read from one file in one round at most
STAGE_MAX_MS = 600000.0  # a hook is stopped by Copilot after 600 s: a longer `pre` or `since` is not a measure of this call
BOARD_WAIT_S = 10.0  # the harness's own launcher waits 10 s for the board and takes a timeout for "busy"
LIST_EVERY_S = 60.0  # the log folders are listed this often; between listings only the known active files are looked at
OLD_RECHECK_S = 600.0  # a file once seen old is looked at again this rarely
CLEAN_EVERY_S = 3600.0
PROBE_EVERY_S = 300.0
MACHINE_SAMPLE_S = 2.0
MAX_LINES = 40
MAX_COLS = 100
MIN_COLS = 20
# Whole process names only (a substring such as "arc" also matches SearchIndexer.exe, "msedge" the webview runtime other programs use).
BROWSER_EXACT = frozenset((
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe", "iexplore.exe",
    "chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "google chrome", "microsoft edge", "brave browser", "safari", "arc", "firefox-bin",
    "com.apple.webkit.gpu", "com.apple.webkit.webcontent", "com.apple.webkit.networking",
))
BROWSER_HELPER_BASES = ("google chrome helper", "microsoft edge helper", "brave browser helper", "arc helper", "vivaldi helper", "opera helper", "firefox helper")
# Root causes before their symptoms (bottleneck pick); a finding with evidence about the harness comes before "the machine is full" at the same severity.
PRIORITY = ("R3", "R5", "R2", "R1", "R0", "R16", "R8", "R12", "R13", "R15", "R6", "R7", "R4", "R11", "R10", "R9", "R14")

SEV_RANK = {"!!": 2, "!": 1}


# --- text width ----------------------------------------------------------------------------------------------------------------------------------------
def cw(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1  # ambiguous width counts 2: a CJK console draws it wide


def width(text: str) -> int:
    return sum(cw(ch) for ch in text)


def cut(text: str, cols: int) -> str:
    """Cut at `cols` display columns; a cut line ends in three ASCII dots."""
    if width(text) <= cols:
        return text
    out, used = [], 0
    for ch in text:
        w = cw(ch)
        if used + w > cols - 3:
            break
        out.append(ch)
        used += w
    return "".join(out) + "..."


def pad(text: str, cols: int) -> str:
    return text + " " * max(0, cols - width(text))


def wrap(text: str, cols: int) -> List[str]:
    """Hard wrap by display width."""
    lines, cur, used = [], "", 0
    for ch in text:
        w = cw(ch)
        if used + w > cols:
            lines.append(cur)
            cur, used = "", 0
        cur += ch
        used += w
    if cur or not lines:
        lines.append(cur)
    return lines


BREAKS = " ，；、：）｜"


def _tokens(text: str) -> List[str]:
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in BREAKS:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def wrap_indent(text: str, cols: int, indent: str = "   ") -> List[str]:
    """Wrap at the screen width, preferably after a separator; a continuation line starts with `indent`. Nothing is cut: the cause and the check stay whole."""
    lines: List[str] = []
    cur = ""
    for tok in _tokens(text):
        if width((cur + tok).rstrip()) <= cols:
            cur += tok
            continue
        if cur.strip():
            lines.append(cur.rstrip())
            cur = indent
            tok = tok.lstrip()
        while width((cur + tok).rstrip()) > cols:  # one token wider than a line: hard split
            take = ""
            for ch in tok:
                if width(cur + take + ch) > cols:
                    break
                take += ch
            take = take or tok[0]
            lines.append((cur + take).rstrip())
            cur, tok = indent, tok[len(take):]
        cur += tok
    if cur.strip() or not lines:
        lines.append(cur.rstrip())
    return lines


def wrap_segments(segments: List[str], cols: int, indent: str = "  ", gap: str = "  ") -> List[str]:
    """Whole segments side by side; a segment that does not fit goes to the next line (one wider than a line is wrapped by itself)."""
    lines: List[str] = []
    cur = ""
    for seg in segments:
        if not seg:
            continue
        if not cur:
            cur = seg
        elif width(cur + gap + seg) <= cols:
            cur += gap + seg
        else:
            lines.append(cur)
            cur = indent + seg
    if cur:
        lines.append(cur)
    out: List[str] = []
    for line in lines:
        out += wrap_indent(line, cols, indent) if width(line) > cols else [line]
    return out


def rjust(text: str, cols: int) -> str:
    """Right-align by display width (str.rjust counts characters, and a CJK character is two columns)."""
    return " " * max(0, cols - width(text)) + text


def fs(ms: Optional[float]) -> str:
    if ms is None:
        return "-"
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def fn(x: Optional[float], digits: int = 0) -> str:
    return "-" if x is None else f"{x:,.{digits}f}"


# --- time ----------------------------------------------------------------------------------------------------------------------------------------------
_TS = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?")


def parse_ts(text: Any) -> Optional[float]:
    """ISO time to epoch seconds; no zone means UTC. None when it is not understood."""
    if not isinstance(text, str):
        return None
    found = _TS.match(text)
    if not found:
        return None
    y, mo, d, h, mi, s, frac, zone = found.groups()
    try:
        secs = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s), 0, 0, 0))
    except (ValueError, OverflowError):
        return None
    if frac:
        secs += float(frac)
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        secs -= sign * (int(digits[:2]) * 3600 + int(digits[2:4] or 0) * 60)
    return float(secs)


def med(values: List[float]) -> Optional[float]:
    return float(statistics.median(values)) if values else None


# --- own cost ------------------------------------------------------------------------------------------------------------------------------------------
class Cost:
    """What this script itself spent in one round."""

    def __init__(self) -> None:
        self.requests = 0
        self.bytes = 0
        self.procs = 0
        self.cpu_mark = time.process_time()
        self.wall_mark = time.perf_counter()
        self.last_cpu = 0.0
        self.last_wall = 0.0  # on a slow PC a round mostly waits on file operations: that is wall time, not CPU time

    def start_round(self) -> None:
        self.requests = self.bytes = self.procs = 0
        self.cpu_mark = time.process_time()
        self.wall_mark = time.perf_counter()

    def end_round(self) -> None:
        self.last_cpu = time.process_time() - self.cpu_mark
        self.last_wall = time.perf_counter() - self.wall_mark


# --- reading only the new bytes of a growing file ---------------------------------------------------------------------------------------------------------
class Tail:
    """Offsets per file. First sight: start at the end minus FIRST_TAIL (the cut first line is dropped). A shorter file starts again from 0."""

    def __init__(self, cost: Cost) -> None:
        self.pos: Dict[str, int] = {}
        self.cost = cost

    def read(self, path: Path, size: int, first_tail: int = FIRST_TAIL, cap: int = READ_CAP) -> List[str]:
        key = str(path)
        off = self.pos.get(key)
        drop_first = False
        if off is None:
            off = max(0, size - first_tail)
            drop_first = off > 0
        elif size < off:
            off, drop_first = 0, False
        if size <= off:
            self.pos[key] = off
            return []
        try:
            with open(path, "rb") as handle:
                handle.seek(off)
                chunk = handle.read(min(size - off, cap))
        except OSError:
            return []
        self.cost.bytes += len(chunk)
        end = chunk.rfind(b"\n")
        if end < 0:
            self.pos[key] = off + len(chunk) if len(chunk) >= cap else off  # one huge line is skipped; a half line waits
            return []
        self.pos[key] = off + end + 1
        text = chunk[:end].decode("utf-8", "replace")
        lines = text.split("\n")
        if drop_first and lines:
            lines = lines[1:]
        return lines

    def forget_except(self, keep: List[str]) -> None:
        live = set(keep)
        for key in [k for k in self.pos if k not in live]:
            del self.pos[key]


# --- which files are active -------------------------------------------------------------------------------------------------------------------------------
class Active:
    """The files of a folder that changed in the last hour. The folder is listed (and its entries looked at) only every LIST_EVERY_S; between listings only the
    files already known to be active are looked at. An entry seen old is remembered and looked at again only every OLD_RECHECK_S, so a big folder of old
    sessions is not looked at whole every minute."""

    def __init__(self, lister: Callable[[], List[Path]]) -> None:
        self.lister = lister
        self.active: Dict[Path, int] = {}
        self.old: set = set()
        self.next_list = 0.0
        self.next_recheck = 0.0
        self.listings = 0
        self.stats = 0

    def _stat(self, path: Path) -> Optional[os.stat_result]:
        self.stats += 1
        try:
            return path.stat()
        except OSError:
            return None

    def poll(self, now: float) -> bool:
        """Refresh `active`. True when the folder was listed in this call."""
        if now >= self.next_list:
            self.next_list = now + LIST_EVERY_S
            self.listings += 1
            try:
                paths = self.lister()
            except OSError:
                paths = []
            recheck = now >= self.next_recheck
            if recheck:
                self.next_recheck = now + OLD_RECHECK_S
            active: Dict[Path, int] = {}
            old: set = set()
            for path in paths:
                if path in self.old and not recheck:
                    old.add(path)
                    continue
                st = self._stat(path)
                if st is not None and now - st.st_mtime <= RECENT_S:
                    active[path] = st.st_size
                else:
                    old.add(path)
            self.active, self.old = active, old
            return True
        for path in list(self.active):
            st = self._stat(path)
            if st is not None and now - st.st_mtime <= RECENT_S:
                self.active[path] = st.st_size
            else:
                del self.active[path]
                self.old.add(path)
        return False


# --- the hook log --------------------------------------------------------------------------------------------------------------------------------------
class HookLog:
    def __init__(self, root: Path, cost: Cost) -> None:
        self.dir = root / ".harness" / "runtime" / "logs"
        self.tail = Tail(cost)
        self.rows: Deque[Dict[str, Any]] = deque()
        self.files = Active(lambda: list(self.dir.glob("*/*.jsonl")))
        self.sessions_hour = 0
        self.exists = False
        self.last_row_at = 0.0

    def poll(self, now: float) -> None:
        if now >= self.files.next_list:
            self.exists = self.dir.is_dir()
        self.files.poll(now)
        files = sorted(self.files.active.items())
        self.sessions_hour = len(files)
        self.tail.forget_except([str(p) for p, _ in files])
        for path, size in files:
            for line in self.tail.read(path, size):
                row = parse_hook_line(line, path.stem)
                if row:
                    self.rows.append(row)
        while self.rows and now - self.rows[0]["at"] > KEEP_S:
            self.rows.popleft()
        if self.rows:
            self.last_row_at = max(r["at"] for r in self.rows)

    def window(self, now: float, seconds: float = WINDOW_S) -> List[Dict[str, Any]]:
        return [r for r in self.rows if now - r["at"] <= seconds]


def parse_hook_line(line: str, stem: str) -> Optional[Dict[str, Any]]:
    """One hook-log row to the few numbers it holds. A bad line is None, never an error."""
    if '"event"' not in line or len(line) > 200000:
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    at = parse_ts(row.get("at"))
    event = row.get("event")
    ms = row.get("ms")
    if at is None or not isinstance(event, str) or isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    t = row.get("t") if isinstance(row.get("t"), dict) else {}
    keep = {k: float(t[k]) for k in ("queue", "lock_wait", "lock_hold", "pre", "since", "integrity", "cpu") if isinstance(t.get(k), (int, float)) and not isinstance(t.get(k), bool)}
    if any(not 0.0 <= keep[k] <= STAGE_MAX_MS for k in ("pre", "since") if k in keep):  # a payload whose timestamp is not the call's (seen in lab rows: 331 days) gives no wait: the parts that hang on it go, `ms` stays
        keep.pop("pre", None)
        keep.pop("since", None)
    via = row.get("via") if row.get("via") in ("service", "local") else None
    sid = row.get("session_id")
    # `ms` is measured from the start of the judgment and already contains `t.lock_wait` and `t.lock_hold`; `t.queue` is outside it. `t.since` runs from
    # Copilot's timestamp of the call to the answer: what the agent waits. H1 takes `since` when the row has it; `judge_ms` is always the judgment's own `ms`.
    wait = keep.get("since", float(ms))
    return {"at": at, "event": event, "ms": wait, "judge_ms": float(ms), "via": via, "t": keep, "sid": sid if isinstance(sid, str) and len(sid) < 200 else stem}


def copilot_home() -> Path:
    """Copilot's own folder: `COPILOT_HOME` when set (as the harness reads it), else ~/.copilot."""
    custom = os.environ.get("COPILOT_HOME", "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".copilot"


# --- Copilot's records ---------------------------------------------------------------------------------------------------------------------------------
class Copilot:
    PREFIX = '{"type":"'
    WANT = ("session.usage_record", "hook.start", "hook.end", "tool.execution_start", "tool.execution_complete")

    def __init__(self, cost: Cost, home: Optional[Path] = None) -> None:
        self.base = (home or copilot_home()) / "session-state"
        self.files = Active(lambda: [folder / "events.jsonl" for folder in self.base.iterdir()])
        self.tail = Tail(cost)
        self.events: Deque[Tuple[float, str, float, str]] = deque()  # (at, kind, ms, session)
        self.hook_open: Dict[str, Tuple[float, str]] = {}
        self.tool_open: Dict[str, Tuple[float, bool]] = {}
        self.exists = False

    def poll(self, now: float) -> None:
        if now >= self.files.next_list:
            self.exists = self.base.is_dir()
        self.files.poll(now)
        files = sorted(self.files.active.items())
        self.tail.forget_except([str(p) for p, _ in files])
        for path, size in files:
            for line in self.tail.read(path, size):
                self.feed(line, path.parent.name)
        while self.events and now - self.events[0][0] > KEEP_S:
            self.events.popleft()
        for table in (self.hook_open, self.tool_open):
            if len(table) > 400:
                for key in list(table)[:200]:
                    del table[key]

    def feed(self, line: str, sid: str) -> None:
        if not line.startswith(self.PREFIX):
            return
        end = line.find('"', len(self.PREFIX))
        kind = line[len(self.PREFIX):end] if end > 0 else ""
        if kind not in self.WANT or len(line) > 400000:
            return
        try:
            row = json.loads(line)
        except ValueError:
            return
        at = parse_ts(row.get("timestamp")) if isinstance(row, dict) else None
        data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
        if at is None:
            return
        try:
            if kind == "session.usage_record":
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                took, first = usage.get("duration"), usage.get("timeToFirstTokenMs")
                if isinstance(took, (int, float)) and took >= 0:
                    self.events.append((at, "model", float(took), sid))
                if isinstance(first, (int, float)) and first >= 0:
                    self.events.append((at, "first", float(first), sid))
            elif kind == "hook.start":
                self.hook_open[str(data.get("hookInvocationId"))] = (at, str(data.get("hookType") or "").lower())
            elif kind == "hook.end":
                began = self.hook_open.pop(str(data.get("hookInvocationId")), None)
                if began and at >= began[0] and began[1] in ("pretooluse", "posttooluse"):
                    self.events.append((at, "hook", (at - began[0]) * 1000.0, sid))
            elif kind == "tool.execution_start":
                name = str(data.get("toolName") or "").lower()
                self.tool_open[str(data.get("toolCallId"))] = (at, "ask" in name)  # a tool that waits for the person is no tool time
            elif kind == "tool.execution_complete":
                began = self.tool_open.pop(str(data.get("toolCallId")), None)
                if began and not began[1] and at >= began[0] and at - began[0] < 600:
                    self.events.append((at, "tool", (at - began[0]) * 1000.0, sid))
        except (TypeError, ValueError, AttributeError):
            return

    def values(self, now: float, kind: str, seconds: float = COPILOT_WINDOW_S) -> List[float]:
        return [ms for at, k, ms, _ in self.events if k == kind and now - at <= seconds]

    def by_session(self, now: float, kind: str, seconds: float) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {}
        for at, k, ms, sid in self.events:
            if k == kind and now - at <= seconds:
                out.setdefault(sid, []).append(ms)
        return out


# --- the machine (system calls only) ---------------------------------------------------------------------------------------------------------------------
# Copied and trimmed from the harness's own `speed` measure; stdlib ctypes. A piece that fails gives None and the others still come.
class _Win:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.c, self.w = ctypes, wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k = k
        dword, c_void_p = wintypes.DWORD, ctypes.c_void_p

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", dword), ("hi", dword)]

        class MEMSTATUS(ctypes.Structure):
            _fields_ = [("dwLength", dword), ("dwMemoryLoad", dword), ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64),
                        ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]

        class PROCENTRY(ctypes.Structure):
            _fields_ = [("dwSize", dword), ("cntUsage", dword), ("th32ProcessID", dword), ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", dword),
                        ("cntThreads", dword), ("th32ParentProcessID", dword), ("pcPriClassBase", ctypes.c_long), ("dwFlags", dword),
                        ("szExeFile", ctypes.c_wchar * 260)]

        self.FILETIME, self.MEMSTATUS, self.PROCENTRY = FILETIME, MEMSTATUS, PROCENTRY
        pft = ctypes.POINTER(FILETIME)
        k.GetSystemTimes.argtypes, k.GetSystemTimes.restype = [pft, pft, pft], wintypes.BOOL
        k.GlobalMemoryStatusEx.argtypes, k.GlobalMemoryStatusEx.restype = [ctypes.POINTER(MEMSTATUS)], wintypes.BOOL
        k.CreateToolhelp32Snapshot.argtypes, k.CreateToolhelp32Snapshot.restype = [dword, dword], c_void_p
        k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [c_void_p, ctypes.POINTER(PROCENTRY)]
        k.Process32FirstW.restype = k.Process32NextW.restype = wintypes.BOOL
        k.OpenProcess.argtypes, k.OpenProcess.restype = [dword, wintypes.BOOL, dword], c_void_p
        k.GetProcessTimes.argtypes, k.GetProcessTimes.restype = [c_void_p, pft, pft, pft, pft], wintypes.BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [c_void_p], wintypes.BOOL

    @staticmethod
    def _t(ft: Any) -> int:
        return (ft.hi << 32) | ft.lo

    def cpu(self) -> Tuple[float, float]:
        idle, kernel, user = self.FILETIME(), self.FILETIME(), self.FILETIME()
        if not self.k.GetSystemTimes(self.c.byref(idle), self.c.byref(kernel), self.c.byref(user)):
            raise OSError("GetSystemTimes")
        return self._t(idle) / 1e7, (self._t(kernel) + self._t(user)) / 1e7

    def memory(self) -> Tuple[int, int]:
        status = self.MEMSTATUS()
        status.dwLength = self.c.sizeof(self.MEMSTATUS)
        if not self.k.GlobalMemoryStatusEx(self.c.byref(status)):
            raise OSError("GlobalMemoryStatusEx")
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    def procs(self) -> Dict[int, Tuple[str, float]]:
        found: Dict[int, Tuple[str, float]] = {}
        snap = self.k.CreateToolhelp32Snapshot(0x2, 0)
        if not snap or snap == self.c.c_void_p(-1).value:
            raise OSError("snapshot")
        try:
            entry = self.PROCENTRY()
            entry.dwSize = self.c.sizeof(self.PROCENTRY)
            ok = self.k.Process32FirstW(snap, self.c.byref(entry))
            while ok:
                pid = int(entry.th32ProcessID)
                if pid:
                    handle = self.k.OpenProcess(0x1000, False, pid)
                    if handle:
                        try:
                            a, b, kernel, user = self.FILETIME(), self.FILETIME(), self.FILETIME(), self.FILETIME()
                            if self.k.GetProcessTimes(handle, self.c.byref(a), self.c.byref(b), self.c.byref(kernel), self.c.byref(user)):
                                found[pid] = (entry.szExeFile, (self._t(kernel) + self._t(user)) / 1e7)
                        finally:
                            self.k.CloseHandle(handle)
                ok = self.k.Process32NextW(snap, self.c.byref(entry))
        finally:
            self.k.CloseHandle(snap)
        return found


class _Mac:
    def __init__(self) -> None:
        import ctypes
        import ctypes.util

        self.c = ctypes
        self.lib = ctypes.CDLL(ctypes.util.find_library("System") or "/usr/lib/libSystem.dylib", use_errno=True)
        self.lib.mach_host_self.restype = ctypes.c_uint32
        self.host = self.lib.mach_host_self()
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_name.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self.lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        info = (ctypes.c_uint32 * 2)()
        self.scale = info[0] / info[1] if self.lib.mach_timebase_info(info) == 0 and info[1] else 1.0

    def sysctl(self, name: str) -> int:
        value = self.c.c_uint64(0)
        length = self.c.c_size_t(8)
        if self.lib.sysctlbyname(name.encode(), self.c.byref(value), self.c.byref(length), None, 0) != 0:
            raise OSError(name)
        return int(value.value)

    def cpu(self) -> Tuple[float, float]:
        ticks = (self.c.c_uint32 * 4)()
        count = self.c.c_uint32(4)
        if self.lib.host_statistics(self.host, 3, ticks, self.c.byref(count)) != 0:
            raise OSError("host_statistics")
        return float(ticks[2]), float(sum(ticks))

    def memory(self) -> Tuple[int, int]:
        total, page = self.sysctl("hw.memsize"), self.sysctl("hw.pagesize")
        buf = (self.c.c_uint32 * 38)()
        count = self.c.c_uint32(38)
        if self.lib.host_statistics64(self.host, 4, buf, self.c.byref(count)) != 0:
            raise OSError("host_statistics64")
        return total, min((buf[0] + buf[2] + buf[23]) * page, total)  # free + inactive + speculative pages

    def procs(self) -> Dict[int, Tuple[str, float]]:
        pids = (self.c.c_int * 8192)()
        got = self.lib.proc_listallpids(pids, self.c.sizeof(pids))
        found: Dict[int, Tuple[str, float]] = {}
        info = (self.c.c_uint64 * 12)()
        name = self.c.create_string_buffer(256)
        for pid in list(pids)[: max(got, 0)]:
            if pid <= 0 or self.lib.proc_pidinfo(pid, 4, 0, info, self.c.sizeof(info)) != self.c.sizeof(info) or self.lib.proc_name(pid, name, 256) <= 0:
                continue
            found[pid] = (name.value.decode("utf-8", "replace"), (info[2] + info[3]) * self.scale / 1e9)
        return found


class _Linux:
    def cpu(self) -> Tuple[float, float]:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            f = [float(x) for x in handle.readline().split()[1:]]
        return f[3] + (f[4] if len(f) > 4 else 0.0), sum(f[:8])

    def memory(self) -> Tuple[int, int]:
        values: Dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                bits = rest.split()
                if bits and bits[0].isdigit():
                    values[key] = int(bits[0]) * 1024
        return values["MemTotal"], values.get("MemAvailable", values.get("MemFree", 0))

    def procs(self) -> Dict[int, Tuple[str, float]]:
        hertz = float(os.sysconf("SC_CLK_TCK") or 100)
        found: Dict[int, Tuple[str, float]] = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat", "r", encoding="utf-8", errors="replace") as handle:
                    head, _, tail = handle.read().rpartition(")")
                rest = tail.split()
                found[int(entry)] = (head.partition("(")[2], (float(rest[11]) + float(rest[12])) / hertz)
            except (OSError, ValueError, IndexError):
                continue
        return found


def busy_pct(a: Tuple[float, float], b: Tuple[float, float]) -> Optional[float]:
    total = b[1] - a[1]
    if total <= 0:
        return None
    return round(min(max((total - (b[0] - a[0])) / total * 100.0, 0.0), 100.0), 1)


def proc_shares(before: Dict[int, Tuple[str, float]], after: Dict[int, Tuple[str, float]], elapsed: float, cores: int) -> List[Dict[str, Any]]:
    """Per process: its CPU seconds between the readings as a share of the whole machine. A process that started inside the sample counts from zero;
    one that was there before but could not be read then is left out."""
    rows: List[Dict[str, Any]] = []
    if elapsed <= 0 or cores <= 0:
        return rows
    for pid, (name, used) in after.items():
        known = pid in before and before[pid][0] == name
        if not known and used > elapsed * cores:
            continue
        delta = max(used - (before[pid][1] if known else 0.0), 0.0)
        rows.append({"pid": pid, "name": name, "pct": delta / (elapsed * cores) * 100.0})
    return rows


def group_top(rows: List[Dict[str, Any]], board_pid: Optional[int], count: int = 3) -> List[Dict[str, Any]]:
    groups: Dict[str, float] = {}
    for row in rows:
        label = "看板(python)" if board_pid and row["pid"] == board_pid else row["name"]
        lower = label.lower()
        if "helper (plugin)" in lower or "extensionhost" in lower or lower in ("code.exe", "code - insiders.exe"):
            label = "VS Code " + label if "VS Code" not in label else label
        groups[label] = groups.get(label, 0.0) + row["pct"]
    ordered = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))[:count]
    return [{"name": n, "pct": round(p, 1)} for n, p in ordered]


def is_browser(name: str) -> bool:
    """A browser process by its whole name (the Mac helpers by their app's name), never by a piece of it."""
    lower = name.strip().lower()
    return lower in BROWSER_EXACT or lower.startswith(BROWSER_HELPER_BASES)


def is_gpu_like(name: str) -> bool:
    return is_browser(name)


class Machine:
    def __init__(self) -> None:
        self.reader: Any = None
        try:
            self.reader = _Win() if sys.platform == "win32" else _Mac() if sys.platform == "darwin" else _Linux()
        except Exception:  # noqa: BLE001 - the machine part is a helper
            self.reader = None
        self.cores = os.cpu_count() or 1
        self.prev: Optional[Tuple[float, Any, Any]] = None

    def _take(self) -> Optional[Tuple[float, Any, Any]]:
        if self.reader is None:
            return None
        cpu = _try(self.reader.cpu)
        procs = _try(self.reader.procs)
        return time.monotonic(), cpu, procs

    def prime(self) -> None:
        self.prev = self._take()

    def sample(self, board_pid: Optional[int]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"cpu": None, "mem": None, "top": None, "gpu": None}
        if self.reader is None:
            return out
        mem = _try(self.reader.memory)
        if mem and mem[0] > 0:
            out["mem"] = round((mem[0] - mem[1]) / mem[0] * 100.0, 1)
        now = self._take()
        prev, self.prev = self.prev, now
        if not prev or not now:
            return out
        if prev[1] and now[1]:
            out["cpu"] = busy_pct(prev[1], now[1])
        if prev[2] is not None and now[2] is not None:
            rows = proc_shares(prev[2], now[2], now[0] - prev[0], self.cores)
            out["top"] = group_top(rows, board_pid)
            gpu = [r["pct"] for r in rows if is_gpu_like(r["name"])]
            out["gpu"] = round(max(gpu), 1) if gpu else 0.0  # the busiest single browser or GPU process (a Windows name cannot tell "GPU" apart)
        return out


def _try(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception:  # noqa: BLE001
        return None


class Probe:
    """How long it takes to start a process: `python -S -c pass`, timed, at most once in PROBE_EVERY_S. The only process this script starts."""

    def __init__(self, cost: Cost) -> None:
        self.last_at = -1e9
        self.value: Optional[float] = None
        self.cost = cost

    def maybe(self, now: float) -> None:
        if now - self.last_at < PROBE_EVERY_S:
            return
        self.last_at = now
        began = time.perf_counter()
        try:
            self.cost.procs += 1
            result = subprocess.run([sys.executable, "-S", "-c", "pass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if result.returncode == 0:
                self.value = time.perf_counter() - began
        except (OSError, subprocess.SubprocessError):
            pass


# --- the board ------------------------------------------------------------------------------------------------------------------------------------------
def is_timeout(error: BaseException) -> bool:
    """A wait that ran out (a busy board), not a refused connection (no board)."""
    if isinstance(error, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


class Board:
    """Finds the board of this folder and reads its meter once a round. State: absent / other / busy / nometer / off / ok.
    A board that does not answer within BOARD_WAIT_S is busy, not absent: it stays identified (no second /api/status) and no rule speaks of it."""

    def __init__(self, root: Path, cost: Cost) -> None:
        self.root = root
        self.cost = cost
        self.port_file = root / ".harness" / "runtime" / "board-serve.json"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # a company proxy must not see (or break) a call to this computer
        self.ident: Optional[Tuple[int, float]] = None  # (port, file mtime) of the board last identified
        self.mine = False
        self.status: Dict[str, Any] = {}
        self.pid: Optional[int] = None
        self.epoch: Optional[str] = None
        self.uptime = 0.0
        self.restarted = False
        self.last_tasks: Optional[int] = None

    def _ask(self, port: int, path: str) -> Any:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}", method="POST",
                                     headers={"X-Harness-Board": "1", "X-Harness-Probe": "1", "Content-Type": "application/json"})
        self.cost.requests += 1
        with self.opener.open(req, timeout=BOARD_WAIT_S) as answer:
            body = answer.read(4 * 1024 * 1024)
        self.cost.bytes += len(body)
        return json.loads(body.decode("utf-8", "replace"))

    def poll(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"state": "absent", "rows": [], "hub": None, "status": {}, "version": "", "restarted": False}
        try:
            st = self.port_file.stat()
            info = json.loads(self.port_file.read_text(encoding="utf-8"))
            port = int(info["port"])
            self.pid = int(info["pid"]) if isinstance(info.get("pid"), int) else None
        except (OSError, ValueError, KeyError, TypeError):
            self.ident, self.mine, self.pid = None, False, None
            return out
        if self.ident != (port, st.st_mtime):  # a new port file: ask which folder this board serves (once)
            self.mine = False
            try:
                status = self._ask(port, "/api/status")
                theirs = str(status.get("root") or "") if isinstance(status, dict) else ""
                self.mine = bool(theirs) and Path(theirs).resolve() == self.root.resolve()
                self.status = status if isinstance(status, dict) else {}
                self.ident = (port, st.st_mtime)
            except (OSError, ValueError) as error:
                self.ident = None  # not identified: ask again next round (one /api/status a round at most)
                out["state"] = "busy" if is_timeout(error) else "absent"
                return out
        if not self.mine:
            out["state"] = "other"
            return out
        out["status"] = self.status
        out["version"] = str(self.status.get("started") or "").split(" (")[0]
        try:
            found = self._ask(port, "/api/meter")
        except urllib.error.HTTPError:
            out["state"] = "nometer"  # an older board has no such path
            return out
        except (OSError, ValueError) as error:
            if is_timeout(error):
                out["state"] = "busy"  # it is there and slow: keep it identified, do not ask /api/status again
                return out
            out["state"] = "absent"
            self.ident = None
            return out
        result = found.get("result") if isinstance(found, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
            out["state"] = "nometer"
            return out
        if not result.get("on"):
            out["state"] = "off"
            return out
        hub = found.get("hub") if isinstance(found.get("hub"), dict) else None
        epoch = hub.get("epoch") if hub else None
        uptime = float(result.get("uptime_s") or 0.0)
        self.restarted = (self.epoch is not None and epoch != self.epoch) or uptime + 1.0 < self.uptime
        self.epoch, self.uptime = epoch, uptime
        out.update({"state": "ok", "rows": [r for r in result["rows"] if isinstance(r, dict)], "hub": hub, "restarted": self.restarted})
        return out


class MaxTrack:
    """The meter's `max_ms` is since the start. A row's worst of the last minute is its max when that grew inside the minute, else None."""

    def __init__(self) -> None:
        self.hist: Deque[Tuple[float, Dict[str, float]]] = deque()

    def reset(self) -> None:
        self.hist.clear()

    def update(self, now: float, rows: List[Dict[str, Any]]) -> Dict[str, float]:
        cur = {str(r.get("name")): float(r.get("max_ms") or 0.0) for r in rows}
        while len(self.hist) > 1 and now - self.hist[1][0] >= WINDOW_S:
            self.hist.popleft()
        ref = self.hist[0][1] if self.hist and now - self.hist[0][0] >= 20 else None
        self.hist.append((now, cur))
        if ref is None:
            return {}
        return {name: m for name, m in cur.items() if m > ref.get(name, 0.0)}


def min1(row: Any) -> Tuple[float, float]:
    """(n, wall_ms) of a meter row's last minute; a row without `min1` (or with a bad one) counts as 0 for that minute."""
    one = row.get("min1") if isinstance(row, dict) else None
    if not isinstance(one, dict):
        return 0.0, 0.0
    out = []
    for key in ("n", "wall_ms"):
        x = one.get(key)
        out.append(float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0)
    return out[0], out[1]


class MeterView:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.r = {str(x.get("name")): x for x in rows}

    def has(self, name: str) -> bool:
        return name in self.r

    def n1(self, name: str) -> Optional[float]:
        row = self.r.get(name)
        return min1(row)[0] if row is not None else None

    def wall1(self, name: str) -> Optional[float]:
        row = self.r.get(name)
        return min1(row)[1] if row is not None else None

    def avg1(self, name: str) -> Optional[float]:
        n, wall = self.n1(name), self.wall1(name)
        return wall / n if n else None

    def prefix(self, start: str) -> List[Dict[str, Any]]:
        return [row for name, row in self.r.items() if name.startswith(start)]

    def any_new(self) -> bool:
        return any(name.startswith(NEW_GEN) for name in self.r)

    def any_base(self) -> bool:
        return any(name.startswith(BASE_GEN) for name in self.r)


# --- metrics ---------------------------------------------------------------------------------------------------------------------------------------------
class Snap:
    """Everything one round read."""

    def __init__(self) -> None:
        self.now = time.time()
        self.board: Dict[str, Any] = {"state": "absent", "rows": [], "hub": None, "status": {}, "version": ""}
        self.machine: Dict[str, Any] = {}
        self.probe_s: Optional[float] = None
        self.hook_rows: List[Dict[str, Any]] = []
        self.hook_exists = False
        self.cop = False
        self.cop_vals: Dict[str, List[float]] = {}
        self.c3: Optional[float] = None
        self.sessions_hour = 0
        self.worst: Dict[str, float] = {}


def compute(s: Snap) -> Tuple[Dict[str, Optional[float]], Dict[str, str], Dict[str, Any]]:
    """(values, unavailable, extra). `values`: numbers only (the record file takes them). `unavailable`: code -> why there is no number:
    board (no board), ver (this version has no such row), nolog, nocop, nomach. `extra`: texts for the screen (not recorded)."""
    v: Dict[str, Optional[float]] = {}
    un: Dict[str, str] = {}
    ex: Dict[str, Any] = {"slow": []}
    # machine
    m = s.machine
    v["M1"], v["M2"], v["M3"] = m.get("cpu"), m.get("mem"), s.probe_s
    ex["top"] = m.get("top")
    v["F4"] = m.get("gpu")
    for code, key in (("M1", "cpu"), ("M2", "mem"), ("M4", "top"), ("F4", "gpu")):
        if m.get(key) is None:
            un[code] = "nomach"
    # hook log
    rows = s.hook_rows
    pre = [r for r in rows if r["event"] == "PreToolUse"]
    post = [r for r in rows if r["event"] == "PostToolUse"]
    prompt = [r for r in rows if r["event"] == "UserPromptSubmit"]
    v["H1_n"] = float(len(pre))
    v["H1_med"], v["H1_max"] = med([r["ms"] for r in pre]), (max(r["ms"] for r in pre) if pre else None)
    v["H1_over"] = float(sum(1 for r in pre if r["ms"] > H1_MAX_MS))  # rows over the worst-case limit: one alone is an outlier, not a jam
    v["H1_post"], v["H1_prompt"] = med([r["ms"] for r in post]), med([r["ms"] for r in prompt])
    waits = [r["t"].get("queue", 0.0) + r["t"].get("lock_wait", 0.0) for r in pre if "queue" in r["t"] or "lock_wait" in r["t"]]
    holds = [r["t"]["lock_hold"] for r in pre if "lock_hold" in r["t"]]
    pres = [r["t"]["pre"] for r in pre if "pre" in r["t"]]
    vias = [r["via"] for r in pre if r["via"]]
    v["H2"], v["H3"], v["H4"] = med(waits), med(holds), med(pres)
    # Where one call's wait goes (rows that have `since` and `pre`). `ms` is measured from the start of the judgment and already holds lock_wait and lock_hold;
    # `queue` is outside it. So: start = pre; wait = queue + lock_wait; judge = ms - lock_wait (the judgment itself, lock hold included);
    # before the judgment = since - pre - queue - ms (connecting, the service taking it), never below 0. The four add up to `since`.
    segs = [r for r in pre if "since" in r["t"] and "pre" in r["t"]]
    if segs:
        def before(r):
            return max(0.0, r["t"]["since"] - r["t"]["pre"] - r["t"].get("queue", 0.0) - r["judge_ms"])

        def judge(r):
            return max(0.0, r["judge_ms"] - r["t"].get("lock_wait", 0.0))
        v["Hs_start"] = med([r["t"]["pre"] for r in segs])
        v["Hs_before"] = med([before(r) for r in segs])
        v["Hs_wait"] = med([r["t"].get("queue", 0.0) + r["t"].get("lock_wait", 0.0) for r in segs])
        v["Hs_judge"] = med([judge(r) for r in segs])
        v["Hs_hold"] = med([r["t"].get("lock_hold", 0.0) for r in segs])
        v["Hs_integrity"] = med([r["t"].get("integrity", 0.0) for r in segs])
        v["Hs_cpu"] = med([r["t"].get("cpu", 0.0) for r in segs])
    v["H5"] = (sum(1 for x in vias if x == "local") / len(vias) * 100.0) if vias else None
    v["H5_n"] = float(sum(1 for x in vias if x == "local")) if vias else None
    v["H7"] = float(len({r["sid"] for r in rows}))
    if not s.hook_exists:
        for code in ("H1", "H2", "H3", "H4", "H5", "H7"):
            un[code] = "nolog"
    else:
        for code, have in (("H2", waits), ("H3", holds), ("H4", pres), ("H5", vias)):
            if not have and pre:
                un[code] = "ver"  # rows came, but without this field
    # Copilot
    if not s.cop:
        for code in ("C1", "C2", "C3"):
            un[code] = "nocop"
    v["C1"] = med(s.cop_vals.get("model", [])) if s.cop else None
    v["C1_first"] = med(s.cop_vals.get("first", [])) if s.cop else None
    v["C2"] = med(s.cop_vals.get("tool", [])) if s.cop else None
    v["C3"] = s.c3
    # board
    state = s.board["state"]
    tasks: Optional[float] = None
    if state != "ok":
        reason = "board" if state in ("absent", "other") else "busy" if state == "busy" else "ver"
        for code in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "F1", "F2", "F3", "F5", "A1", "A2", "A3", "H6"):
            un[code] = reason
    else:
        mv = MeterView(s.board["rows"])
        hub = s.board.get("hub")
        gen = mv.any_new()
        gone_base = "notyet" if mv.any_base() else "ver"  # the board has rows of the base generation, only not this one yet / has none at all
        gone_new = "notyet" if gen else "ver"
        # B1: the one-minute average of every request that is not held open and not ours; the worst is the row's max when it grew in the minute
        n_all = wall_all = 0.0
        slow: List[Tuple[str, float, float]] = []
        for name, row in mv.r.items():
            if not name.startswith("http ") or name in LONG_REQUESTS or name in OWN_REQUESTS:
                continue
            n, wall = min1(row)
            if n <= 0:
                continue
            n_all += n
            wall_all += wall
            slow.append((name.replace("http POST ", "").replace("http GET ", "GET "), wall / n, s.worst.get(name, wall / n)))
        v["B1_avg"] = wall_all / n_all if n_all else None
        v["B1_n"] = n_all
        v["B1_worst"] = max((w for _, _, w in slow), default=None)
        ex["slow"] = sorted(slow, key=lambda x: -max(x[1], x[2]))[:3]
        # B2
        v["B2"] = mv.n1(ROWS["fc_stat"])
        if v["B2"] is None:
            un["B2"] = gone_base
        hit, miss = mv.n1(ROWS["fc_hit"]), mv.n1(ROWS["fc_miss"])
        v["B2_hit"] = (hit / (hit + miss) * 100.0) if hit is not None and miss is not None and hit + miss > 0 else None
        # B3
        for key, row in (("full", "build_full"), ("part", "build_part"), ("light", "build_light")):
            v[f"B3_{key}"] = mv.n1(ROWS[row]) or 0.0
            v[f"B3_{key}_s"] = (mv.avg1(ROWS[row]) / 1000.0) if mv.avg1(ROWS[row]) is not None else None
        if not hub and not mv.has("hub.build"):
            un["B3"] = gone_base
        # B4, B7
        scan = hub.get("scan") if hub else None
        looks = hub.get("looks") if hub else None
        v["B4_every_min"] = (float(scan["every_s"]) / 60.0) if isinstance(scan, dict) and "every_s" in scan else None
        v["B4_diffs"] = float(scan.get("diffs", 0)) if isinstance(scan, dict) else None
        if not isinstance(scan, dict):
            un["B4"] = "ver"
        v["B7_pages"] = float(looks.get("pages", 0)) if isinstance(looks, dict) else None
        v["B7_front"] = float(looks.get("in_front", 0)) if isinstance(looks, dict) else None
        if not isinstance(looks, dict):
            un["B7"] = "ver"
        tasks = float(hub["rows"]) if hub and isinstance(hub.get("rows"), int) else None
        v["tasks"] = tasks
        # B5, B6
        v["B5"] = (mv.n1(ROWS["missed"]) or 0.0) if (hub or mv.has("hub.touch")) else None
        if v["B5"] is None:
            un["B5"] = gone_base
        bg = [(name, mv.n1(name)) for name in ROWS["bg"] if mv.has(name)]
        v["B6_max"] = max((n for _, n in bg if n is not None), default=None)
        if not bg:
            un["B6"] = gone_base
        same, new = mv.n1(ROWS["part_same"]), mv.n1(ROWS["part_new"])
        v["B8"] = (same / (same + new) * 100.0) if same is not None and new is not None and same + new > 0 else None
        # F, A, H6: the newer rows
        if not gen:
            for code in ("F1", "F2", "F3", "A1", "A2", "A3", "H6"):
                un[code] = gone_new
        else:
            if isinstance(looks, dict) and not looks.get("pages") and not mv.has(ROWS["stream_open"]):
                for code in ("F1", "F2", "F3"):
                    un[code] = "nopage"
            v["F1_n"] = mv.n1(ROWS["longtask"]) or 0.0
            v["F1_max"] = s.worst.get(ROWS["longtask_max"], 0.0)
            v["F2"] = mv.avg1(ROWS["lag"])
            v["F3"] = (mv.n1(ROWS["stream_poll"]) or 0.0)
            v["F3_open"] = mv.n1(ROWS["stream_open"]) or 0.0
            v["A1_avg"] = mv.avg1(ROWS["acts_done"])
            v["A1_max"] = s.worst.get(ROWS["acts_done"])
            v["A1_n"] = mv.n1(ROWS["acts_done"]) or 0.0
            v["A2"] = mv.n1(ROWS["acts_failed"]) or 0.0
            v["A3"] = mv.n1(ROWS["acts_fallback"]) or 0.0
            v["H6_late"] = mv.n1(ROWS["hs_late"]) or 0.0
            v["H6_refused"] = float(sum(min1(r)[0] for r in mv.prefix(ROWS["hs_refused"])))
            v["H6_busy"] = mv.n1(ROWS["hs_busy"]) or 0.0
            v["H6_queue"] = mv.avg1(ROWS["hs_queue"])
        # F5: pages that exist but none in front, and requests still going up
        if isinstance(looks, dict):
            if looks.get("pages") and not looks.get("in_front"):
                v["F5"] = float(sum(min1(row)[0] for name, row in mv.r.items() if name.startswith("http ") and name not in OWN_REQUESTS and name not in LONG_REQUESTS))
            else:
                v["F5"] = 0.0
        else:
            un["F5"] = "ver"
    if tasks is None:
        tasks = float(max(s.sessions_hour, 0))
    v["tasks_used"] = tasks
    v["b2_limit"] = B2_PER_TASK_MIN * max(1.0, tasks)  # the file-check limit scales with the open tasks
    return v, un, ex


# --- rules -----------------------------------------------------------------------------------------------------------------------------------------------
class Rule:
    def __init__(self, rid: str, name: str, codes: str, check: Callable[[Dict[str, Optional[float]], Dict[str, Any]], Optional[Tuple[str, str, str]]],
                 symptom: str, cause: str, fix: str, how: str, cause_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], str]] = None) -> None:
        self.id, self.name, self.codes, self.check = rid, name, codes, check
        self.symptom, self.cause, self.fix, self.how = symptom, cause, fix, how
        self.cause_fn = cause_fn  # a cause that depends on which numbers are there (no cause is stated from a missing number)

    def cause_for(self, v: Dict[str, Any], c: Dict[str, Any]) -> str:
        return self.cause_fn(v, c) if self.cause_fn else self.cause


def gap(c: Dict[str, Any]) -> str:
    """What stands in place of a number that is missing: why it is missing."""
    state = c.get("state")
    if state == "busy":
        return "看板忙"
    if state in ("absent", "other"):
        return "看板没开"
    return "这一版没有"


def nf(x: Optional[float], c: Dict[str, Any], fmt: Callable[[Optional[float]], str] = fn) -> str:
    """A number, or the reason there is none; never a bare dash."""
    return fmt(x) if x is not None else gap(c)


def _h1_sev(v: Dict[str, Optional[float]]) -> Optional[str]:
    """None: not slow. "!": slow by the worst call only (one outlier, or two). "!!": the median is over the limit, or at least 3 calls in the minute are over the worst-case limit."""
    med_slow = v.get("H1_med") is not None and v["H1_med"] > H1_MED_MS  # type: ignore[operator]
    max_slow = v.get("H1_max") is not None and v["H1_max"] > H1_MAX_MS  # type: ignore[operator]
    if med_slow or (max_slow and (v.get("H1_over") or 0.0) >= 3):
        return "!!"
    return "!" if max_slow else None


def _b1_slow(v: Dict[str, Optional[float]]) -> bool:
    return (v.get("B1_avg") or 0.0) > B1_AVG_MS or (v.get("B1_worst") or 0.0) > B1_MAX_MS


def _gt(x: Optional[float], limit: float) -> bool:
    return x is not None and x > limit


SEG_NAMES = {"Hs_start": "起进程", "Hs_before": "到判断前", "Hs_wait": "排队", "Hs_judge": "判断"}


def _hook_top(v: Dict[str, Any]) -> Optional[str]:
    """The largest part of a slow hook call's wait (segment key), or None when the rows have no parts (an older version)."""
    found = {key: v.get(key) for key in SEG_NAMES if v.get(key) is not None}
    return max(found, key=lambda key: found[key]) if found else None


def _hook_line(v: Dict[str, Any]) -> str:
    head = f"PreToolUse 中位 {fs(v['H1_med'])}，最坏 {fs(v['H1_max'])}（{v['H1_n']:.0f} 次" + (f"，超 {fs(H1_MAX_MS)} 的 {v['H1_over']:.0f} 次" if v.get("H1_over") else "") + "）"
    if _hook_top(v) is None:
        return head
    judge = f"判断 {fs(v.get('Hs_judge'))}（含持锁 {fs(v.get('Hs_hold'))}，完整性 {fs(v.get('Hs_integrity'))}，CPU {fs(v.get('Hs_cpu'))}）"
    return f"{head}\n起进程 {fs(v.get('Hs_start'))}｜到判断前 {fs(v.get('Hs_before'))}｜排队 {fs(v.get('Hs_wait'))}｜{judge}"


def _hook_slow_by(v: Dict[str, Any], key: str) -> Optional[Tuple[str, str, str]]:
    sev = _h1_sev(v)
    if sev and _hook_top(v) == key:
        return sev, _hook_line(v), f"正常 中位 < {fs(H1_MED_MS)}"
    return None


def r0(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """A slow hook is always told, also when this version's log has no parts to say why."""
    sev = _h1_sev(v)
    if sev and _hook_top(v) is None:
        return sev, _hook_line(v) + "（这一版的 hook 日志没有分段）", f"正常 中位 < {fs(H1_MED_MS)}"
    return None


def r1(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    return _hook_slow_by(v, "Hs_wait")


def r2(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    return _hook_slow_by(v, "Hs_start")


def r3(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    return _hook_slow_by(v, "Hs_judge")


def r16(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    return _hook_slow_by(v, "Hs_before")


def r4(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("H5"), H5_PCT):
        late = v.get("H6_late")
        return ("!!" if v["H5"] > 30 else "!"), f"自己判 {v['H5']:.0f}%（{v.get('H5_n') or 0:.0f} 次），晚了放行 {nf(late, c)}", f"正常 < {H5_PCT:.0f}%"
    return None


def r4_cause(v: Dict[str, Any], c: Dict[str, Any]) -> str:
    late = v.get("H6_late")
    if late is None:
        return f"屏上看不出是没起还是答晚了（{gap(c)} H6）"
    if late > 0:
        return "判断服务答晚了，hook 自己判（晚了放行 > 0）"
    return "判断服务没起或连不上（没有晚了放行）"


def r5(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("B2"), v["b2_limit"]):
        return ("!!" if v["B2"] > 2 * v["b2_limit"] else "!"), f"文件检查 {fn(v['B2'])}/分（{v['tasks_used']:.0f} 个任务）", f"正常 < {fn(v['b2_limit'])}"
    return None


def r6(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    each = v.get("B3_full_s")
    if _gt(v.get("B3_full"), B3_FULL_PER_MIN) and (each is None or each * v["B3_full"] >= B3_FULL_COST_S):  # many cheap rebuilds cost nothing: only rebuilds that add up to time count
        return "!", f"全量重算 {v['B3_full']:.0f} 次/分，每次 {each:.1f} s" if each is not None else f"全量重算 {v['B3_full']:.0f} 次/分", f"正常 < {B3_FULL_PER_MIN:.0f} 次/分"
    return None


def r7(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("B5"), B5_PER_MIN):
        return "!", f"漏的通知 {v['B5']:.0f} 次/分，自己判 H5 {nf(v.get('H5'), c, lambda x: f'{x:.0f}%')}", f"正常 < {B5_PER_MIN:.0f} 次/分"
    return None


def r8(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _b1_slow(v):
        top = "，".join(f"{n} {fs(a)}" for n, a, _ in c.get("slow", [])[:2])
        return "!", f"接口平均 {nf(v.get('B1_avg'), c, fs)}，最慢 {nf(v.get('B1_worst'), c, fs)}" + (f"：{top}" if top else ""), f"正常 < {fs(B1_AVG_MS)}，最坏 < {fs(B1_MAX_MS)}"
    return None


def r9(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("F5"), 0):
        return "!", f"没有页面在前台，1 分钟内仍有 {v['F5']:.0f} 个请求", "正常 0"
    return None


def r10(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if (_gt(v.get("F1_n"), F1_PER_MIN) or _gt(v.get("F1_max"), F1_MAX_MS) or _gt(v.get("F4"), F4_PCT)) and not _b1_slow(v):
        return ("!", f"长任务 {nf(v.get('F1_n'), c)} 次，最长 {nf(v.get('F1_max'), c, fs)}，浏览器最忙 F4 {nf(v.get('F4'), c, lambda x: f'{x:.0f}%')}",
                f"正常 <= {F1_PER_MIN:.0f} 次/分，< {fs(F1_MAX_MS)}，F4 < {F4_PCT:.0f}%")
    return None


def r11(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("F2"), F2_MS):
        return "!", f"推送晚到 {fs(v['F2'])}，断流/改轮询 F3 {nf(v.get('F3'), c)} 次", f"正常 < {fs(F2_MS)}"
    return None


def r12(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("A1_avg"), A1_AVG_MS):
        return "!", f"动作平均 {fs(v['A1_avg'])}（{v.get('A1_n') or 0:.0f} 次），失败 {nf(v.get('A2'), c)}，回落 {nf(v.get('A3'), c)}", f"正常 < {fs(A1_AVG_MS)}"
    return None


def r13(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("M1"), M1_RULE_PCT) or _gt(v.get("M2"), M2_RULE_PCT):
        tops = (c.get("top") or [])[:3]
        names = "，".join(f"{t['name'][:14]} {t['pct']:.0f}%" for t in tops)
        total = sum(t["pct"] for t in tops)
        spread = "，其余分散" if v.get("M1") is None or total < 0.8 * v["M1"] else ""  # the busy CPU is not explained by the three
        who = f"最忙：{names}（前三名合计 {total:.0f}%{spread}）" if tops else "最忙：没读到进程表"
        cpu = f"{v['M1']:.0f}%" if v.get("M1") is not None else "没读到"
        mem = f"{v['M2']:.0f}%" if v.get("M2") is not None else "没读到"
        return "!!", f"CPU {cpu}，内存 {mem}；{who}", f"正常 CPU < {M1_PCT:.0f}%，内存 < {M2_PCT:.0f}%"
    return None


def r14(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    if _gt(v.get("C1_first"), C1_RULE_S * 1000):
        return "!", f"模型首字 {fs(v['C1_first'])}，一次调用 {nf(v.get('C1'), c, fs)}", f"正常 < {C1_FIRST_S:.0f} s"
    return None


def r15(v: Dict[str, Any], c: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """Never for a busy board: busy is not absent."""
    state = c.get("state")
    if state == "absent":
        return "!", "看板没开（读不到这个文件夹的看板）", "正常 hub 核心在跑"
    if state == "other":
        return "!", "端口上的看板是别的文件夹的", "正常 hub 核心在跑"
    if state in ("nometer", "off"):
        return "!", "看板在，但没有计量（旧版或没开）", "正常 hub 核心在跑"
    if state == "ok" and not c.get("hub"):
        return "!", "看板在，但不是 hub 核心（classic）", "正常 hub 核心在跑"
    return None


RULES: List[Rule] = [
    Rule("R0", "hook 慢", "H1", r0, "agent 每次调工具都要等", "说不清是哪一段（这一版的日志没有分段）", "升级后再看；hook 并发、hook 扩展", "--detail H1"),
    Rule("R1", "hook 排队", "H1+H2", r1, "agent 每次调工具都要等，最大的一段是排队", "判断窗口或状态锁被占着", "hook 并发（并排判断、乐观状态、忙时只放行读）", "--detail H2；H3 看谁持锁久"),
    Rule("R2", "hook 起得慢", "H1+H4", r2, "agent 每次调工具都要等，最大的一段是起进程", "起进程慢（安全软件、机器忙）", "hook 扩展（hook 放进 extension，16 ms 对 0.6 s）", "看 M3、M1；--detail H4"),
    Rule("R3", "判断慢", "H1+B2", r3, "agent 每次调工具都要等，最大的一段是判断", "CPU 小、时间长：在等文件（文件操作慢或道满了）；完整性占大头：完整性核对慢", "1.9 步骤 44、45、46、47；hook 提速（完整性核对）", "--detail H1 看完整性和 CPU；--detail B2；M1"),
    Rule("R16", "到判断前慢", "H1+H6", r16, "agent 每次调工具都要等，最大的一段在起进程之后、判断之前", "hook 进程连上判断服务、服务接手慢（服务忙、机器忙）", "hook 并发；hook 扩展", "--detail H6 看忙不忙；M1"),
    Rule("R4", "自己判多", "H5", r4, "有的调用慢很多，看板晚知道", "判断服务没起、答晚了", "判断服务（1.8.56 F 项）、hook 并发", "看 H6 晚了放行；看板日志", r4_cause),
    Rule("R5", "文件检查多", "B2", r5, "看板和 hook 一起变慢", "任务多、文件多；看谁在看", "1.9 步骤 44、46、47、48（少看文件）", "--detail B2：http 路径、bg.*、hub.watch 分组"),
    Rule("R6", "全量重算多", "B3", r6, "一个变化等很久才到各处", "有不点名的告知（「全部」），或块算不出", "1.9 步骤 32、33、44", "--detail B3：hub.touch / hub.marks.all 谁多"),
    Rule("R7", "漏的通知", "B5", r7, "画面晚 15 s 左右", "有进程改了任务没告诉看板", "1.9 步骤 44（通知）、48", "和 H5 对；--detail B5"),
    Rule("R8", "接口慢", "B1", r8, "任务页的块转圈、按钮等", "最慢接口：/api/part 的 core 遍历被丢；scripts/rounds 读大文件", "1.9 步骤 46、47、39", "--detail B1 看最慢的块"),
    Rule("R9", "后台在问", "F5", r9, "没人看也在花", "页面在后台仍在轮询", "1.9 步骤 35+40", "--detail F5 哪些路径"),
    Rule("R10", "前端卡", "F1+F4", r10, "点了不动、滚动卡", "页面自己画得慢（大列表重画、动画）", "前端重画（进 BACKLOG）", "--detail F1；看是哪个视图开着"),
    Rule("R11", "推送晚", "F2+F3", r11, "几处不同步", "状态中心发得晚（重算慢）或连接挤", "1.9 交付 1 的推送；步骤 33", "看 B3 每次秒数；F3"),
    Rule("R12", "动作慢", "A1", r12, "点了以后 Working... 很久", "动作自己的活慢（git、文件），或同任务的在排", "1.9 步骤 13", "--detail A1"),
    Rule("R13", "机器满", "M1+M2", r13, "什么都慢", "机器本身；看谁占", "不是 harness 的", "看 M4 前三名"),
    Rule("R14", "模型慢", "C1", r14, "agent 想得慢", "Copilot 服务或网络", "不是 harness 的", "harness speed 的网络部分"),
    Rule("R15", "看板没有/旧核心", "B0", r15, "后端的数都没有", "看板没开、没用新核心", "无", "开看板；board.core 设为 hub"),
]


# The codes a rule speaks about itself (taken out of the "正常" lines); the other codes in `Rule.codes` are only where to look next.
OWN_CODES = {"R0": ("H1",), "R1": ("H1", "H2"), "R2": ("H1", "H4"), "R3": ("H1",), "R16": ("H1",)}


def evaluate(v: Dict[str, Optional[float]], ex: Dict[str, Any]) -> List[Tuple[Rule, str, str, str]]:
    """The rules that fire, most severe first (ties by PRIORITY: root causes before symptoms)."""
    fired: List[Tuple[Rule, str, str, str]] = []
    for rule in RULES:
        try:
            got = rule.check(v, ex)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - one rule that fails never stops the screen
            got = None
        if got:
            fired.append((rule, got[0], got[1], got[2]))
    order = {rid: i for i, rid in enumerate(PRIORITY)}
    fired.sort(key=lambda f: (-SEV_RANK[f[1]], order.get(f[0].id, 99)))
    return fired


def load_word(fired: List[Tuple[Rule, str, str, str]]) -> str:
    if not fired:
        return "低"
    if any(f[0].id == "R13" for f in fired):
        return "满"
    return "高" if any(f[1] == "!!" for f in fired) else "中"


# --- the screen ------------------------------------------------------------------------------------------------------------------------------------------
def fl(ms: float) -> str:
    """A limit in the shortest form: 300 ms, 2 s."""
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:g} s"


def normal_items(v: Dict[str, Optional[float]], un: Dict[str, str], ex: Dict[str, Any], flagged: set) -> List[Tuple[str, str]]:
    def put(code: str, text: str, ok: bool = True) -> Optional[Tuple[str, str]]:
        if ok and code not in un and code not in flagged:
            return code, text
        return None

    def bang(code: str, value: Optional[float], limit: float) -> str:
        """The code, with a ! after it when its number is over its limit but no rule has spoken (the hook rules name only the largest part)."""
        return code + ("!" if value is not None and value > limit else "")

    top = ex.get("top") or []
    b2 = f"B2 文件检查 {fn(v.get('B2'))}" + (f"/{fn(v['b2_limit'])}" if v.get("b2_limit") else "") + " 每分" + (f" 命中 {v['B2_hit']:.0f}%" if v.get("B2_hit") is not None else "")
    cand = [
        put("M1", f"M1 CPU {fn(v.get('M1'))}%/{M1_PCT:.0f}%", v.get("M1") is not None),
        put("M2", f"M2 内存 {fn(v.get('M2'))}%/{M2_PCT:.0f}%", v.get("M2") is not None),
        put("M3", f"{bang('M3', v.get('M3'), M3_S)} 起进程 {v['M3']:.1f} s/{M3_S:g} s" if v.get("M3") is not None else "", v.get("M3") is not None),
        put("M4", "M4 最忙 " + " ".join(f"{t['name'][:12]} {t['pct']:.0f}%" for t in top[:2]), bool(top)),
        put("B1", f"B1 接口 均 {fs(v.get('B1_avg'))}/{fl(B1_AVG_MS)}" if v.get("B1_avg") is not None else "B1 接口 这一分钟没有请求", True),
        put("B2", b2, True),
        put("B3", f"B3 重算 全量 {fn(v.get('B3_full'))}/{B3_FULL_PER_MIN:g} 部分 {fn(v.get('B3_part'))}/分", True),
        put("B4", f"B4 扫描 {fn(v.get('B4_every_min'))} 分钟档 差异 {fn(v.get('B4_diffs'))}", True),
        put("B5", f"B5 漏通知 {fn(v.get('B5'))}/{B5_PER_MIN:g} 每分", True),
        put("B6", f"B6 后台 最多 {fn(v.get('B6_max'))}/{B6_PER_MIN:g} 每分", True),
        put("B7", f"B7 页面 {fn(v.get('B7_pages'))}（前台 {fn(v.get('B7_front'))}）", True),
        put("B8", f"B8 备忘 {v['B8']:.0f}%/{B8_MIN_RATIO * 100:.0f}%" if v.get("B8") is not None else "B8 备忘 这一分钟没有请求", True),
        put("F1", f"F1 卡顿 {fn(v.get('F1_n'))}/{F1_PER_MIN:g}" + (f" 最长 {fs(v.get('F1_max'))}" if v.get("F1_max") else ""), True),
        put("F2", f"F2 推送晚 {fs(v.get('F2'))}/{fl(F2_MS)}" if v.get("F2") is not None else "F2 推送晚 没有推送", True),
        put("F3", f"F3 断流 {fn(v.get('F3'))}", True),
        put("F4", f"F4 浏览器 {fn(v.get('F4'))}%/{F4_PCT:.0f}%", v.get("F4") is not None),
        put("F5", f"F5 后台问 {fn(v.get('F5'))}", True),
        put("H1", f"H1 hook 中位 {fs(v.get('H1_med'))}/{fl(H1_MED_MS)}（{fn(v.get('H1_n'))} 次）" if v.get("H1_med") is not None else "H1 hook 这一分钟没有调用", True),
        put("H2", f"{bang('H2', v.get('H2'), 500)} 排队 {fs(v.get('H2'))}/{fl(500)}", v.get("H2") is not None),
        put("H3", f"{bang('H3', v.get('H3'), H3_MS)} 持锁 {fs(v.get('H3'))}/{fl(H3_MS)}", v.get("H3") is not None),
        put("H4", f"{bang('H4', v.get('H4'), H4_MS)} 启动 {fs(v.get('H4'))}/{fl(H4_MS)}", v.get("H4") is not None),
        put("H5", f"{bang('H5', v.get('H5'), H5_PCT)} 自己判 {fn(v.get('H5'))}%/{H5_PCT:.0f}%", v.get("H5") is not None),
        put("H6", f"H6 判断服务 晚{fn(v.get('H6_late'))} 拒{fn(v.get('H6_refused'))}", True),
        put("H7", f"H7 并发 {fn(v.get('H7'))}", True),
        put("A1", f"A1 动作 {fs(v.get('A1_avg'))}/{fl(A1_AVG_MS)}" if v.get("A1_avg") is not None else "A1 动作 这一分钟没有", True),
        put("A2", f"A2 失败 {fn(v.get('A2'))}", True),
        put("A3", f"A3 回落 {fn(v.get('A3'))}", True),
        put("C1", f"C1 模型首字 {fs(v.get('C1_first'))}/{C1_FIRST_S:g} s" if v.get("C1_first") is not None else "C1 模型 这两分钟没有", True),
        put("C2", f"C2 工具 {fs(v.get('C2'))}" if v.get("C2") is not None else "C2 工具 这两分钟没有", True),
        put("C3", f"C3 hook 启动另算 {fs(v.get('C3'))}/{fl(1000)}" if v.get("C3") is not None else "C3 hook 启动 这两分钟没有", True),
    ]
    return [item for item in cand if item]


REASONS = (("board", "看板没开"), ("busy", "看板忙，这一轮没读到"), ("nopage", "没有页面"), ("ver", "这一版没有"), ("notyet", "还没出现"), ("nolog", "没有 hook 日志"),
           ("nocop", "没有 Copilot 记录"), ("nomach", "读不到机器数"))
BOARD_TEXT = {"absent": "没开", "other": "没开（端口上是别的文件夹的看板）", "nometer": "在（没有计量：旧版）", "off": "在（计量没开）", "busy": "忙"}


def pack(items: List[str], cols: int, max_lines: int, lead: str = "") -> List[str]:
    """Items side by side, a line at most `cols` wide; items that do not fit in `max_lines` are counted in the last line."""
    lines: List[str] = []
    cur = lead
    first = True
    for i, item in enumerate(items):
        piece = ("" if first or cur == lead else "  ") + item
        if width(cur + piece) > cols and cur.strip():
            lines.append(cur)
            if len(lines) >= max_lines:
                lines[-1] = cut(lines[-1], cols - 12) + f" 等共 {len(items)} 项"
                return lines
            cur = " " * width(lead) + item
        else:
            cur += piece
        first = False
    if cur.strip():
        lines.append(cur)
    return [cut(line, cols) for line in lines]


def header_lines(s: Snap, v: Dict[str, Optional[float]], un: Dict[str, str], fired: List[Tuple[Rule, str, str, str]], every: int, cols: int, compact: bool = False) -> List[str]:
    state = s.board["state"]
    hub = s.board.get("hub")
    clock = time.strftime("%H:%M:%S", time.localtime(s.now))
    board = ("在（hub 核心，有计量）" if hub else "在（classic 核心，有计量）") if state == "ok" else BOARD_TEXT.get(state, "?")
    looks = hub.get("looks") if hub else None
    if isinstance(looks, dict):
        pages = f"页面 {looks.get('pages', 0)}（前台 {looks.get('in_front', 0)}）"
    elif state == "busy":
        pages = "页面 看板忙"
    elif state in ("absent", "other"):
        pages = ""
    else:
        pages = "页面 这一版没有"
    working = f"，{v['H7']:.0f} 个在干活" if v.get("H7") is not None and "H7" not in un else ""
    tasks = f"任务 {v['tasks']:.0f} 个开着{working}" if v.get("tasks") is not None else f"会话 {s.sessions_hour} 个（1 小时内有动静）{working}"
    restart = "  看板重启过" if s.board.get("restarted") else ""
    lines = wrap_segments([f"harness 监测 {clock} 每 {every} s", f"看板 {board}", tasks, pages, restart.strip()], cols)
    if fired:
        main = fired[0][0]
        rest = "、".join(f"{r.name}（{r.codes}）" for r, *_ in fired[1:3])
        second = f"负荷：{load_word(fired)}  头号瓶颈：{main.name}（{main.codes}）" + (f"  次要：{rest}" if rest else "")
    else:
        second = f"负荷：{load_word(fired)}  没有规则触发"
    if compact:  # a very small window: one line each
        return [cut(lines[0], cols), cut(second, cols)]
    return lines + wrap_segments(second.split("  "), cols)


def finding_block(rule: Rule, sev: str, data: str, norm: str, v: Dict[str, Any], ex: Dict[str, Any], cols: int) -> List[str]:
    """One finding, every line wrapped at the screen width (never cut: the cause and the check stay whole)."""
    head, _, parts = data.partition("\n")
    out = wrap_indent(f"{sev:<2} {rule.id} {rule.name}  {head}  {norm}", cols, "   ")
    if parts:
        out += wrap_indent(f"   分段：{parts}", cols, "      ")
    out += wrap_indent(f"   症状：{rule.symptom}  可能根因：{rule.cause_for(v, ex)}", cols, "      ")
    out += wrap_indent(f"   优化项：{rule.fix}  排查：{rule.how}", cols, "      ")
    return out


def cost_lines(cost: Cost, record_path: Path, cols: int) -> List[str]:
    procs = f"{cost.procs}（本轮量了一次起进程，每 5 分钟一次）" if cost.procs else "0"
    text = f"监测自己：每轮 {cost.requests} 个请求、读 {cost.bytes / 1024:.1f} KB、新进程 {procs}、CPU {cost.last_cpu:.2f} s、耗时 {cost.last_wall:.2f} s  记录：{short_path(record_path)}"
    return wrap_indent(text, cols, "   ")


def render(s: Snap, v: Dict[str, Optional[float]], un: Dict[str, str], ex: Dict[str, Any], fired: List[Tuple[Rule, str, str, str]], every: int,
           cost: Cost, record_path: Path, cols: int, max_lines: int = MAX_LINES) -> List[str]:
    """The screen: at most `max_lines` lines of at most `cols` columns. Findings wrap; only the "正常" lines and the last line are ever cut."""
    cols = max(MIN_COLS, min(cols, MAX_COLS))
    max_lines = max(1, min(max_lines, MAX_LINES))
    sep = "-" * cols
    head = header_lines(s, v, un, fired, every, cols)
    tiny = header_lines(s, v, un, fired, every, cols, True)
    ex = dict(ex)
    ex.setdefault("state", s.board["state"])
    flagged = set()
    for rule, *_ in fired:
        flagged.update(OWN_CODES.get(rule.id) or [c for c in re.split(r"[+]", rule.codes) if c])
    items = [t for _, t in normal_items(v, un, ex, flagged)]
    blocks = [finding_block(rule, sev, data, norm, v, ex, cols) for rule, sev, data, norm in fired]
    foot = cost_lines(cost, record_path, cols)
    miss_all = []
    for code, text in REASONS:
        codes = sorted(k for k, r in un.items() if r == code)
        if codes:
            miss_all.append(f"{text}：" + " ".join(codes))
    bare = False
    for norm_budget, merge, small, bare in ((5, False, False, False), (3, False, False, False), (2, True, False, False), (1, True, True, False), (1, True, True, True)):
        # the "正常" and missing lines give way first, so the worst finding stays whole; the last step also drops the rules between the parts and the missing lines
        if small:
            head = tiny
        if bare:
            foot = [cut(" ".join(x.strip() for x in cost_lines(cost, record_path, 1000)), cols)]
        normal = pack(items, cols, norm_budget, "正常：") if items else ["正常：没有"]
        if merge:
            miss = [cut("  ".join(miss_all), cols)] if miss_all else []
        else:
            miss = [line for text in miss_all for line in wrap_indent(text, cols, "  ")]
        if bare:
            miss = []
        seps = 0 if bare else (3 if blocks else 2)
        fixed = len(head) + seps + len(foot) + len(normal) + len(miss)
        room = max_lines - fixed
        need = (len(blocks[0]) + (1 if len(blocks) > 1 else 0)) if blocks else 0
        if room >= need:
            break
    shown, used = 0, 0
    if blocks and sum(len(b) for b in blocks) <= room:
        shown = len(blocks)
    else:
        for block in blocks:
            if used + len(block) > room - 1:
                break
            used += len(block)
            shown += 1
    body: List[str] = []
    if blocks and shown == 0:  # no room even for the worst finding: its lines up to the room, the last one cut
        first = blocks[0][:max(room, 1)]
        first[-1] = cut(first[-1] + " ...", cols) if len(first) < len(blocks[0]) else first[-1]
        body = first
    else:
        for block in blocks[:shown]:
            body += block
        if len(blocks) > shown:
            body.append(cut(f"另有 {len(blocks) - shown} 条：" + " ".join(r.id for r, *_ in fired[shown:]), cols))
    if bare:
        lines = head + body + normal + foot
    else:
        lines = head + [sep] + body + ([sep] if blocks else []) + normal + miss + [sep] + foot
    if len(lines) > max_lines:  # a window too small for everything: the foot stays, the rest is cut from the end
        lines = lines[:max_lines - 1] + [cut(foot[-1], cols)]
    return [cut(line, cols) for line in lines]


def short_path(path: Path) -> str:
    return f".../{path.parent.name}/{path.name}"


# --- the record file --------------------------------------------------------------------------------------------------------------------------------------
def record_dir() -> Path:
    own = os.environ.get("HARNESS_WATCH_RECORDS")  # the tests point it elsewhere: a made-up row must never land in the real record
    return Path(own) if own else Path(tempfile.gettempdir()) / "harness-watch"


def record_file(now: float) -> Path:
    return record_dir() / (time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl")


def clean_old(now: float) -> None:
    try:
        for path in record_dir().glob("*.jsonl"):
            try:
                if now - path.stat().st_mtime > 86400:
                    path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def write_record(now: float, v: Dict[str, Optional[float]], fired: List[Tuple[Rule, str, str, str]]) -> None:
    nums = {k: round(x, 3) for k, x in v.items() if isinstance(x, (int, float)) and not isinstance(x, bool)}
    row = {"t": round(now, 1), "v": nums, "fired": [f"{r.id}:{sev}" for r, sev, *_ in fired]}
    try:
        record_dir().mkdir(parents=True, exist_ok=True)
        with open(record_file(now), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError:
        pass


def read_record(now: float, minutes: int = 20) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for stamp in (now - 86400, now):
        path = record_file(stamp)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and isinstance(row.get("t"), (int, float)) and now - row["t"] <= minutes * 60:
                        rows.append(row)
        except OSError:
            continue
        if record_file(now) == record_file(now - 86400):
            break
    rows.sort(key=lambda r: r["t"])
    return rows


# --- --detail ----------------------------------------------------------------------------------------------------------------------------------------------
# code -> (name, how it is worked out, normal, what to check, meter row prefixes to list)
DEFS: Dict[str, Tuple[str, str, str, str, Tuple[str, ...]]] = {
    "M1": ("CPU", "整机忙的比例，两轮之间（系统调用，不起进程）。", "< 70%；规则 R13 在 > 90%", "看 M4 谁占；不是 harness 的就别优化", ()),
    "M2": ("内存", "已用比例（总内存减可用）。", "< 85%；规则 R13 在 > 90%", "看 M4；内存满时 hook 起进程也变慢", ()),
    "M3": ("起一个进程", "起一次 python -S -c pass 的秒数，5 分钟一次，是本脚本唯一起的进程。", "< 1 s（公司电脑约 1.5 s 算已知慢）", "和 H4、C3 对：起得慢，hook 就慢（R2）", ()),
    "M4": ("最忙的进程", "CPU 前三名的名字和占整机的比例；认出看板的 python（按看板文件里的 pid）、VS Code 的 extension host。", "无", "占满的是谁：浏览器 GPU、extension host、看板 python？", ()),
    "B1": ("接口耗时", "看板计量里 http POST /api/... 每行 1 分钟内的平均；最坏取该行历史最大值在这一分钟内变大的那个。长连接（stream、state、live）和本脚本自己的请求不算。", "平均 < 300 ms，最坏 < 3 s", "最慢的几个接口在下面列出；/api/part 看 core 和 scripts", ("http POST",)),
    "B2": ("文件检查", "计量 fc.stat 1 分钟的次数；命中率 = fc.hit / (hit + miss)。上限随开着的任务数放大（每任务每分钟 300 次）。", "< 300 x 开着的任务数 / 分钟", "谁在看文件：http 路径、bg.*、hub.watch；任务多文件多", ("fc.", "bg.", "hub.watch")),
    "B3": ("重算", "hub.build.full / part / light 每分钟次数；每次秒数 = 1 分钟内的总时间 / 次数。", "全量 < 1 次/分；每次 < 2 s", "hub.touch / hub.marks.all 谁多：不点名的告知引起全量重算", ("hub.build", "hub.touch", "hub.marks")),
    "B4": ("兜底扫描", "hub 的 scan：档位（15 分钟 / 30 / 1 小时 / 2 小时）、找到的差异数。", "档位往上走，差异 0", "差异不为 0：有进程改了任务没告诉看板（看 B5）", ("hub.scan",)),
    "B5": ("漏的通知", "hub.missed 每分钟：盯着的文件动了，却没人告诉看板。", "< 1 / 分", "和 H5 对：hook 自己判时不通知看板", ("hub.missed", "hub.touch.hook")),
    "B6": ("后台循环", "bg.link_look、bg.sweep、bg.ready、bg.models 每分钟次数和耗时。", "每个 < 30 / 分", "哪个循环次数多、每次长", ("bg.",)),
    "B7": ("页面", "hub 的 looks：连着的页面数、在前台的数。本脚本不算页面（它带探测头，不碰 stream、state、look）。", "无", "页面多会让兜底扫描和文件监看一直开着", ("hub.look",)),
    "B8": ("任务页备忘", "part.same.memo / (part.same.memo + part.computed) 1 分钟内：问一块，答没变的比例。", "> 80%", "低：块总被重算，看 B3、B2", ("part.",)),
    "F1": ("页面卡顿", "页面报的长任务（> 50 ms）1 分钟次数，和最长一次。", "0-2 次/分，最长 < 200 ms", "看是哪个视图开着；B1 不慢而它多，是前端自己画得慢", ("page.",)),
    "F2": ("推送晚到", "页面收到一条变更比看板发出晚多少（page.lag 的 1 分钟平均）。", "< 1 s", "看 B3 每次秒数；F3 断流", ("page.", "stream.")),
    "F3": ("断流", "改用长轮询的次数（stream.poll）；重新连流的次数（stream.open）。", "0", "连接挤或看板重启", ("stream.",)),
    "F4": ("浏览器最忙进程", "机器上名字像浏览器或 GPU 的进程里最忙的一个，占整机的比例（Windows 的进程名分不出 GPU 进程，所以取浏览器进程里最忙的）。", "< 30%", "页面动画和大列表重画", ()),
    "F5": ("后台的页面还在问", "有页面连着、但在前台的数为 0 时，1 分钟内计量里的请求数（不含 stream、state、live 和本脚本的）。", "0", "哪些路径还在涨：见下面的接口列表", ("http POST",)),
    "H1": ("hook 总时间", "hook 日志 PreToolUse 的 t.since（Copilot 记下这次调用到 hook 答复，agent 真正等的；旧版没有时用 ms，只是判断那一段），1 分钟内的中位、最坏、次数；PostToolUse、UserPromptSubmit 的中位另记。分段：起进程 = pre；排队 = queue + lock_wait；判断 = ms - lock_wait（含持锁）；到判断前 = since - pre - queue - ms。", "中位 < 2 s，最坏 < 10 s（单独一次超过只算 !，中位超过或一分钟内 3 次超过才算 !!）", "分段：H2 排队、H3 持锁、H4 启动", ()),
    "H2": ("排队", "t.queue（等判断窗口）+ t.lock_wait（等状态锁）的中位。", "< 0.5 s", "占 H1 一半以上：R1；看 H3 谁持锁", ()),
    "H3": ("持锁", "t.lock_hold 的中位：一次判断拿着状态锁多久。", "< 1 s", "大而且 B2 高：R3，文件操作慢或满", ()),
    "H4": ("启动", "t.pre：Copilot 记下这次调用到 hook 进程开始干活（起进程、加载）。", "< 1 s（公司电脑约 0.6 s 起）", "大：起进程慢，看 M3、M1（R2）", ()),
    "H5": ("自己判", "via 是 local 的比例：判断服务没在、答晚了，hook 进程自己判。", "< 5%", "看 H6 晚了放行；自己判时看板晚知道（B5）", ()),
    "H6": ("判断服务", "计量 hookserve.*：晚了放行 (late)、拒绝 (refused.*)、忙 (busy)、排队 (queue)。", "晚了 0", "晚了放行多：判断服务答不及，看 H3", ("hookserve.",)),
    "H7": ("并发", "1 分钟内 hook 日志里不同 session 的数（屏上第一行的「在干活」）。", "无", "同时在干活的会话数", ()),
    "A1": ("动作做完", "计量 acts.done 的 1 分钟平均：收到到结果。", "平均 < 1 s，最坏 < 5 s", "git、文件慢，或同任务动作在排队", ("acts.",)),
    "A2": ("动作失败", "acts.failed 1 分钟次数。", "无", "看看板日志里失败的动作", ("acts.",)),
    "A3": ("回落旧路", "acts.fallback：没有线程或太多在跑，按旧的方式答。", "0", "太多动作同时在跑", ("acts.",)),
    "C1": ("模型调用", "Copilot 记录里 session.usage_record：每次的秒数中位、首字秒数中位（2 分钟窗口）。", "首字 < 5 s", "高：Copilot 服务或网络（R14），不是 harness 的", ()),
    "C2": ("工具调用", "tool.execution_start 到 complete 的中位（不含等人的工具）。", "无", "无", ()),
    "C3": ("hook 启动另算", "Copilot 记的 hook 时间（pre/post）减 hook 日志里判断自己的 ms（不是 since），同一会话，2 分钟窗口：起进程和加载的花销。", "< 1 s", "大：R2", ()),
}
for _r in RULES:
    DEFS[_r.id] = (_r.name, f"规则：看 {_r.codes}。症状：{_r.symptom}。可能根因：{_r.cause}。", "见屏上「正常」", f"优化项：{_r.fix}。排查：{_r.how}。", ())


Limit = Optional[Any]  # None: no limit; a number or a record key (over it is marked); (number, "<"): under it is marked


def detail_rows(code: str) -> List[Tuple[str, str, Limit]]:
    """(column title, record key, limit) of a code."""
    keys: Dict[str, List[Tuple[str, str, Limit]]] = {
        "M1": [("CPU%", "M1", M1_PCT)], "M2": [("内存%", "M2", M2_PCT)], "M3": [("起进程s", "M3", M3_S)], "M4": [("CPU%", "M1", M1_PCT)],
        "B1": [("平均ms", "B1_avg", B1_AVG_MS), ("最坏ms", "B1_worst", B1_MAX_MS), ("次数", "B1_n", None)],
        "B2": [("次/分", "B2", "b2_limit"), ("命中%", "B2_hit", None), ("上限", "b2_limit", None)],
        "B3": [("全量", "B3_full", B3_FULL_PER_MIN), ("部分", "B3_part", None), ("轻", "B3_light", None), ("全量s", "B3_full_s", B3_EACH_S)],
        "B4": [("档(分)", "B4_every_min", None), ("差异", "B4_diffs", 0.0)],
        "B5": [("次/分", "B5", B5_PER_MIN)], "B6": [("最多/分", "B6_max", B6_PER_MIN)], "B7": [("页面", "B7_pages", None), ("前台", "B7_front", None)],
        "B8": [("%", "B8", (B8_MIN_RATIO * 100.0, "<"))],
        "F1": [("次", "F1_n", F1_PER_MIN), ("最长ms", "F1_max", F1_MAX_MS)], "F2": [("ms", "F2", F2_MS)], "F3": [("轮询", "F3", 0.0), ("连流", "F3_open", None)],
        "F4": [("%", "F4", F4_PCT)], "F5": [("请求", "F5", 0.0)],
        "H1": [("中位ms", "H1_med", H1_MED_MS), ("最坏ms", "H1_max", H1_MAX_MS), ("次数", "H1_n", None), ("起进程", "Hs_start", None), ("到判断前", "Hs_before", None),
               ("排队", "Hs_wait", None), ("判断", "Hs_judge", None), ("完整性", "Hs_integrity", None)],
        "H2": [("ms", "H2", 500.0)], "H3": [("ms", "H3", H3_MS)], "H4": [("ms", "H4", H4_MS)],
        "H5": [("%", "H5", H5_PCT), ("次", "H5_n", None)], "H6": [("晚了", "H6_late", 0.0), ("拒绝", "H6_refused", None), ("忙", "H6_busy", None)], "H7": [("会话", "H7", None)],
        "A1": [("平均ms", "A1_avg", A1_AVG_MS), ("次数", "A1_n", None)], "A2": [("次", "A2", None)], "A3": [("次", "A3", 0.0)],
        "C1": [("模型ms", "C1", None), ("首字ms", "C1_first", C1_FIRST_S * 1000.0)], "C2": [("ms", "C2", None)], "C3": [("ms", "C3", 1000.0)],
    }
    if code in keys:
        return keys[code]
    for rule in RULES:  # a rule: the columns of its codes
        if rule.id == code:
            out: List[Tuple[str, str, Limit]] = []
            for part in rule.codes.split("+"):
                out.extend(keys.get(part, [])[:2])
            return out[:4]
    return []


# What the meter's row names mean, for the --detail list (a prefix; the first column is what is shown).
GLOSS = (("fc.stat", ("fc.stat",), "一次文件检查"), ("fc.hit", ("fc.hit", "fc.pass_hit"), "用了记住的结果没读盘"), ("bg.*", ("bg.",), "后台循环"),
         ("hub.watch", ("hub.watch",), "盯文件"))


def gloss_line(names: List[str]) -> str:
    bits = []
    for label, prefixes, meaning in GLOSS:
        found = sorted({n for n in names if n.startswith(prefixes)})
        if found:
            bits.append(f"{' / '.join(found) if label != 'bg.*' else 'bg.*'} = {meaning}")
    return "行名：" + "；".join(bits) if bits else ""


def column_format(values: List[Optional[float]]) -> Callable[[Optional[float]], str]:
    """One format for a whole column: no 95.0 next to 118."""
    nums = [abs(x) for x in values if x is not None]
    top = max(nums) if nums else 0.0
    whole = all(float(x).is_integer() for x in values if x is not None)
    digits = 0 if top >= 100 or whole else 1
    return lambda x: "-" if x is None else f"{x:,.{digits}f}"


def over_limit(value: Optional[float], limit: Limit, row_v: Dict[str, Any]) -> bool:
    if value is None or limit is None:
        return False
    if isinstance(limit, tuple):
        return value < limit[0]
    lim = row_v.get(limit) if isinstance(limit, str) else limit
    return isinstance(lim, (int, float)) and value > lim


def render_detail(code: str, now: float, rows: List[Dict[str, Any]], live: Optional[List[Dict[str, Any]]], cols: int, max_lines: int = MAX_LINES) -> List[str]:
    cols = max(MIN_COLS, min(cols, MAX_COLS))
    max_lines = max(8, min(max_lines, MAX_LINES))
    code = code.upper()
    sep = "-" * cols
    if code not in DEFS:
        return wrap_indent(f"没有这个代号：{code}。可用：" + " ".join(sorted(DEFS, key=lambda c: (c[0], int(c[1:])))), cols, "  ")
    name, how, normal, check, prefixes = DEFS[code]
    out = [f"{code} {name}  （--detail）  {time.strftime('%H:%M:%S', time.localtime(now))}", sep]
    for label, text in (("定义", how), ("正常", normal)):
        out += wrap_indent(f"{label}：{text}", cols, "  ")
    out.append(sep)
    cols_def = detail_rows(code)
    is_rule = code.startswith("R")
    by_min: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        by_min[int(row["t"] // 60)] = row
    stamps = sorted(by_min)[-20:]
    if len(by_min) < 20:
        out.append(f"只有 {len(by_min)} 分钟的数（最多看 20 分钟）")
    out.append("时间      " + ("".join(rjust(t, 10) for t, _, _ in cols_def)) + ("  规则" if is_rule else ""))
    live_lines: List[str] = []
    if live:
        live_lines.append("看板此刻的相关行（1 分钟）：")
        for row in live[:6]:
            n, wall = min1(row)
            peak = row.get("max_ms")
            peak = float(peak) if isinstance(peak, (int, float)) and not isinstance(peak, bool) else 0.0
            live_lines.append(cut(f"  {row.get('name')}  {n:.0f} 次 共 {wall:,.0f} ms，最长 {peak:,.0f} ms", cols))
        note = gloss_line([str(r.get("name")) for r in live[:6]])
        if note:
            live_lines += wrap_indent(note, cols, "  ")
    tail = [sep] + wrap_indent(f"检查：{check}", cols, "  ")
    budget = max_lines - len(out) - len(live_lines) - len(tail)
    step = 1 if len(stamps) <= budget else 2
    shown = stamps[::-1][::step][::-1][-max(budget, 1):]
    if not shown:
        out.append("还没有记录：先让监测跑一会儿（每 15 s 记一行）。")
    formats = {key: column_format([by_min[st].get("v", {}).get(key) for st in shown]) for _, key, _ in cols_def}
    for stamp in shown:
        row = by_min[stamp]
        vals = row.get("v", {})
        cells = ""
        for _, key, limit in cols_def:
            text = formats[key](vals.get(key))
            cells += rjust(text, 9) + ("!" if over_limit(vals.get(key), limit, vals) else " ")
        fired = [f.split(":")[1] for f in row.get("fired", []) if f.startswith(code + ":")]
        out.append(time.strftime("%H:%M     ", time.localtime(stamp * 60)) + cells + (("  " + (fired[0] if fired else "-")) if is_rule else ""))
    out += live_lines + tail
    return [cut(line, cols) for line in out][:max_lines]


# --- the loop --------------------------------------------------------------------------------------------------------------------------------------------
class Watch:
    def __init__(self, root: Path, copilot_home: Optional[Path] = None) -> None:
        self.root = root
        self.cost = Cost()
        self.board = Board(root, self.cost)
        self.hooks = HookLog(root, self.cost)
        self.cop = Copilot(self.cost, copilot_home)
        self.machine = Machine()
        self.probe = Probe(self.cost)
        self.track = MaxTrack()
        self.last_clean = -1e12

    def maybe_clean(self, now: float) -> None:
        """Record files older than a day go once an hour while the loop runs (not only at start)."""
        if now - self.last_clean >= CLEAN_EVERY_S:
            self.last_clean = now
            clean_old(now)

    def round(self) -> Snap:
        self.cost.start_round()
        s = Snap()
        s.now = time.time()
        self.maybe_clean(s.now)
        s.board = self.board.poll()
        if s.board.get("restarted"):
            self.track.reset()
        if s.board["state"] == "ok":
            s.worst = self.track.update(time.monotonic(), s.board["rows"])
        self.hooks.poll(s.now)
        self.cop.poll(s.now)
        self.probe.maybe(s.now)
        s.probe_s = self.probe.value
        s.machine = self.machine.sample(self.board.pid)
        s.hook_rows = self.hooks.window(s.now)
        s.hook_exists = self.hooks.exists
        s.sessions_hour = self.hooks.sessions_hour
        s.cop = self.cop.exists
        for kind in ("model", "first", "tool"):
            s.cop_vals[kind] = self.cop.values(s.now, kind)
        s.c3 = self.c3(s.now)
        return s

    def c3(self, now: float) -> Optional[float]:
        """Copilot's hook time minus the hook log's own judgment `ms` (what is left: starting the process and loading), for sessions that have both in the window."""
        theirs = self.cop.by_session(now, "hook", COPILOT_WINDOW_S)
        mine: Dict[str, List[float]] = {}
        for r in self.hooks.window(now, COPILOT_WINDOW_S):
            if r["event"] in ("PreToolUse", "PostToolUse"):
                mine.setdefault(r["sid"], []).append(r["judge_ms"])  # the judgment's own `ms`, not `since`
        a = [x for sid in theirs if sid in mine for x in theirs[sid]]
        b = [x for sid in theirs if sid in mine for x in mine[sid]]
        if not a or not b:
            return None
        return max(0.0, float(statistics.median(a)) - float(statistics.median(b)))

    def screen(self, every: int, cols: int, rows_avail: int) -> Tuple[List[str], Snap]:
        s = self.round()
        v, un, ex = compute(s)
        ex["state"], ex["hub"] = s.board["state"], s.board.get("hub")
        fired = evaluate(v, ex)
        self.cost.end_round()
        write_record(s.now, v, fired)
        return render(s, v, un, ex, fired, every, self.cost, record_file(s.now), cols, min(MAX_LINES, rows_avail)), s


def enable_vt() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001
        return False


def term_size() -> Tuple[int, int]:
    size = shutil.get_terminal_size((MAX_COLS, MAX_LINES + 1))
    return size.columns, size.lines


USAGE = "用法：harness-watch.py [文件夹] [--every 秒数（整数，不小于 5）] [--once] [--detail 代号]"


def parse_args(args: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(options, error). A wrong argument is one clear line, never a traceback."""
    opts: Dict[str, Any] = {"every": 15, "once": False, "detail": None, "folder": None, "help": False}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--every":
            if i + 1 >= len(args):
                return None, "--every 后面要一个整数（秒），不小于 5，例如 --every 15"
            try:
                every = int(args[i + 1])
            except ValueError:
                return None, f"--every 要一个整数（秒），不小于 5，收到「{args[i + 1]}」"
            if every < 5:
                return None, f"--every 不能小于 5 秒（收到 {every}）：每一轮要读文件，太密会拖慢被看的机器"
            opts["every"] = every
            i += 1
        elif a == "--once":
            opts["once"] = True
        elif a == "--detail":
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                return None, "--detail 后面要一个代号，例如 --detail H1（代号见屏上的正常行）"
            opts["detail"] = args[i + 1]
            i += 1
        elif a in ("-h", "--help"):
            opts["help"] = True
        elif a.startswith("-") and len(a) > 1:
            return None, f"不认识的选项：{a}"
        else:
            opts["folder"] = a
        i += 1
    return opts, ""


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    opts, error = parse_args(args)
    if opts is None:
        print(f"{error}\n{USAGE}", file=sys.stderr)
        return 2
    if opts["help"]:
        print(__doc__)
        return 0
    every, once, detail = opts["every"], opts["once"], opts["detail"]
    root = Path(opts["folder"] or ".").expanduser().resolve()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    cols, lines = term_size()
    now = time.time()
    if detail:
        clean_old(now)
        watch = Watch(root)
        live: Optional[List[Dict[str, Any]]] = None
        code = detail.upper()
        prefixes = DEFS.get(code, ("", "", "", "", ()))[4]
        if not prefixes and code.startswith("R"):
            prefixes = tuple(p for part in next((r.codes for r in RULES if r.id == code), "").split("+") for p in DEFS.get(part, ("",) * 5)[4])
        if prefixes:
            snap = watch.board.poll()
            if snap["state"] == "ok":
                live = sorted([r for r in snap["rows"] if str(r.get("name", "")).startswith(prefixes) and r.get("name") not in OWN_REQUESTS],
                              key=lambda r: -min1(r)[1])
        print("\n".join(render_detail(detail, now, read_record(now), live, cols)))
        return 0
    watch = Watch(root)
    vt = sys.stdout.isatty() and enable_vt()
    watch.machine.prime()
    time.sleep(MACHINE_SAMPLE_S)
    try:
        while True:
            began = time.monotonic()
            try:
                cols, lines = term_size()
                avail = max(1, min(MAX_LINES, lines - 1)) if sys.stdout.isatty() else MAX_LINES  # one row less than the window: the in-place redraw never scrolls
                screen, _ = watch.screen(every, cols, avail)
            except Exception as error:  # noqa: BLE001 - a round that fails is one line, never the end
                screen = [cut(f"harness 监测：这一轮出错：{type(error).__name__}: {str(error)[:60]}", max(MIN_COLS, min(cols, MAX_COLS)))]
            text = "\n".join(screen)
            if once:
                print(text)
                return 0
            if vt:
                sys.stdout.write("\x1b[H" + "".join(line + "\x1b[K\n" for line in screen) + "\x1b[J")
            else:
                sys.stdout.write("=" * min(cols, MAX_COLS) + "\n" + text + "\n")
            sys.stdout.flush()
            time.sleep(max(0.5, every - (time.monotonic() - began)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
