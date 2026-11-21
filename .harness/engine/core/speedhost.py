"""What is slow on this computer right now (`harness speed`, part "now"): a snapshot.

It gives: the time to start a Python and a shell process (median of 3 each), CPU busy and the 5 busiest processes over one shared 2 s sample, and memory.

The target is a work PC where every new process takes 1 to 1.5 s (two endpoint-security products scan it). The measure must not add to that load, so the only
processes started here are the 6 start measures (3 Python, 3 shell). On Windows everything else is system calls through ctypes (`GetSystemTimes`,
`GlobalMemoryStatusEx`, a toolhelp snapshot, `GetProcessTimes`, `GetProcessMemoryInfo`): no `tasklist`, `wmic`, `powershell`.
On Linux it reads `/proc` (no process). On macOS it uses ctypes too (`sysctlbyname`, `host_statistics`, `host_statistics64`, libproc `proc_pidinfo`);
only when libproc gives no process list at all, ONE `ps -A -o %cpu=,rss=,comm=` call replaces it (its %cpu is a decaying average, not the 2 s sample: it is
good enough to name the busy ones). A process that cannot be opened (other users', protected) is skipped.

The arithmetic (ticks into busy %, process time into a share of the whole machine, grouping by name) is pure and tested; the system calls are thin.
Stdlib only. Never raises: a piece that fails gives None or [] and the others still come.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import pace

SAMPLE_S = 2.0  # seconds between the two readings
TOP = 5  # rows in the list of the busiest processes
STARTS = 3  # starts of each kind; the median is the answer
WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"

# A reading: {"cpu": (idle, total) in any one unit or None, "procs": {pid: (name, cpu_seconds_used, mem_mb)}}
Reading = Dict[str, Any]


def platform_name() -> str:
    return "windows" if WINDOWS else "mac" if MAC else "linux"


# --- pure arithmetic ------------------------------------------------------------------------------------------------------------------------------------------

def busy_pct(before: Tuple[float, float], after: Tuple[float, float]) -> Optional[float]:
    """CPU busy in % between two `(idle, total)` readings (total includes idle). None when time did not move."""
    idle = after[1] - before[1] - (after[0] - before[0])
    total = after[1] - before[1]
    if total <= 0:
        return None
    return round(min(max(idle / total * 100.0, 0.0), 100.0), 1)


def shares(before: Dict[int, Tuple[str, float, float]], after: Dict[int, Tuple[str, float, float]], elapsed: float, cores: int) -> List[Dict[str, Any]]:
    """Per process: its CPU seconds used between the readings as a share of the whole machine (`elapsed * cores` seconds), and its memory at the end.
    A process only in `after` started inside the sample and counts from zero (a hook's Python is such a process); one only in `before` ended and is left out.
    A process only in `after` that used more CPU than the sample holds was there before and could not be read then (Windows refuses some): it is left out."""
    if elapsed <= 0 or cores <= 0:
        return []
    rows = []
    for pid, (name, used, mem) in after.items():
        known = pid in before and before[pid][0] == name
        if not known and used > elapsed * cores:
            continue
        start = before[pid][1] if known else 0.0
        delta = max(used - start, 0.0)
        rows.append({"name": name, "cpu_pct": delta / (elapsed * cores) * 100.0, "mem_mb": mem})
    return rows


def group_top(rows: List[Dict[str, Any]], count: int = TOP) -> List[Dict[str, Any]]:
    """Rows with the same name become one (cpu and memory summed, `count` of processes), the `count` busiest first. A tie is told by memory, then name."""
    groups: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "?")
        found = groups.setdefault(name, {"name": name, "cpu_pct": 0.0, "mem_mb": 0.0, "count": 0})
        found["cpu_pct"] += float(row.get("cpu_pct") or 0.0)
        found["mem_mb"] += float(row.get("mem_mb") or 0.0)
        found["count"] += 1
    ordered = sorted(groups.values(), key=lambda g: (-g["cpu_pct"], -g["mem_mb"], g["name"]))[: max(count, 0)]
    return [{"name": g["name"], "cpu_pct": round(g["cpu_pct"], 1), "mem_mb": int(round(g["mem_mb"])), "count": g["count"]} for g in ordered]


def parse_ps(text: str, cores: int) -> List[Dict[str, Any]]:
    """Rows of `ps -A -o %cpu=,rss=,comm=` (rss in KB; %cpu of one core, so it is divided by the cores). Name = last part of the path."""
    rows = []
    for line in (text or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            cpu, rss = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        rows.append({"name": parts[2].strip().rsplit("/", 1)[-1] or parts[2], "cpu_pct": cpu / max(cores, 1), "mem_mb": rss / 1024.0})
    return rows


def median_ms(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


# --- process starts (the only place processes are started) -------------------------------------------------------------------------------------------------------

def time_starts(args: List[str], limit: float, run: Callable[..., Any], clock: Callable[[], float]) -> Optional[float]:
    """Median of STARTS timed runs in ms; a run that fails or runs out counts for nothing. None when none worked."""
    found: List[float] = []
    for _ in range(STARTS):
        try:
            began = clock()
            result = run(args, limit)
            took = (clock() - began) * 1000.0
        except Exception:  # noqa: BLE001 - a start that fails is no number
            continue
        if getattr(result, "returncode", 0) == 0:
            found.append(took)
    return median_ms(found)


def measure_starts(root: Path, run: Optional[Callable[..., Any]], clock: Callable[[], float]) -> Dict[str, Optional[float]]:
    if run is None:
        from core import procrun

        run = procrun.run
    try:
        limit = pace.scaled(30, root)
    except Exception:  # noqa: BLE001
        limit = 30
    shell = ["cmd", "/c", "exit"] if WINDOWS else ["/bin/sh", "-c", "true"]
    return {"python_ms": time_starts([sys.executable, "-c", "pass"], limit, run, clock), "shell_ms": time_starts(shell, limit, run, clock)}


# --- Windows (ctypes) -----------------------------------------------------------------------------------------------------------------------------------------

class _Win:
    """Thin ctypes wrappers; only built on Windows. Times are FILETIME: 100 ns units."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.c = ctypes
        self.w = wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k = k
        c_void_p, dword = ctypes.c_void_p, wintypes.DWORD

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

        class PMC(ctypes.Structure):
            _fields_ = [("cb", dword), ("PageFaultCount", dword), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        self.FILETIME, self.MEMSTATUS, self.PROCENTRY, self.PMC = FILETIME, MEMSTATUS, PROCENTRY, PMC
        pft = ctypes.POINTER(FILETIME)
        k.GetSystemTimes.argtypes, k.GetSystemTimes.restype = [pft, pft, pft], wintypes.BOOL
        k.GlobalMemoryStatusEx.argtypes, k.GlobalMemoryStatusEx.restype = [ctypes.POINTER(MEMSTATUS)], wintypes.BOOL
        k.CreateToolhelp32Snapshot.argtypes, k.CreateToolhelp32Snapshot.restype = [dword, dword], c_void_p
        k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [c_void_p, ctypes.POINTER(PROCENTRY)]
        k.Process32FirstW.restype = k.Process32NextW.restype = wintypes.BOOL
        k.OpenProcess.argtypes, k.OpenProcess.restype = [dword, wintypes.BOOL, dword], c_void_p
        k.GetProcessTimes.argtypes, k.GetProcessTimes.restype = [c_void_p, pft, pft, pft, pft], wintypes.BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [c_void_p], wintypes.BOOL
        self.mem_info = getattr(k, "K32GetProcessMemoryInfo", None)
        if self.mem_info is not None:
            self.mem_info.argtypes, self.mem_info.restype = [c_void_p, ctypes.POINTER(PMC), dword], wintypes.BOOL

    @staticmethod
    def _ticks(ft: Any) -> int:
        return (ft.hi << 32) | ft.lo

    def cpu_times(self) -> Tuple[float, float]:
        """(idle, total) in seconds; GetSystemTimes' kernel time already includes idle."""
        idle, kernel, user = self.FILETIME(), self.FILETIME(), self.FILETIME()
        if not self.k.GetSystemTimes(self.c.byref(idle), self.c.byref(kernel), self.c.byref(user)):
            raise OSError("GetSystemTimes failed")
        return self._ticks(idle) / 1e7, (self._ticks(kernel) + self._ticks(user)) / 1e7

    def memory(self) -> Dict[str, Optional[int]]:
        status = self.MEMSTATUS()
        status.dwLength = self.c.sizeof(self.MEMSTATUS)
        if not self.k.GlobalMemoryStatusEx(self.c.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return mem_dict(status.ullTotalPhys, status.ullAvailPhys)

    def processes(self) -> Dict[int, Tuple[str, float, float]]:
        """{pid: (exe name, cpu seconds used so far, working set MB)}; what cannot be opened is left out."""
        found: Dict[int, Tuple[str, float, float]] = {}
        snap = self.k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == self.c.c_void_p(-1).value:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry = self.PROCENTRY()
            entry.dwSize = self.c.sizeof(self.PROCENTRY)
            ok = self.k.Process32FirstW(snap, self.c.byref(entry))
            while ok:
                pid, name = int(entry.th32ProcessID), entry.szExeFile
                if pid:
                    item = self._one(pid, name)
                    if item:
                        found[pid] = item
                ok = self.k.Process32NextW(snap, self.c.byref(entry))
        finally:
            self.k.CloseHandle(snap)
        return found

    def _one(self, pid: int, name: str) -> Optional[Tuple[str, float, float]]:
        handle = self.k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel, user = self.FILETIME(), self.FILETIME(), self.FILETIME(), self.FILETIME()
            if not self.k.GetProcessTimes(handle, self.c.byref(created), self.c.byref(exited), self.c.byref(kernel), self.c.byref(user)):
                return None
            mem = 0.0
            if self.mem_info is not None:
                counters = self.PMC()
                counters.cb = self.c.sizeof(self.PMC)
                if self.mem_info(handle, self.c.byref(counters), counters.cb):
                    mem = counters.WorkingSetSize / 1048576.0
            return name, (self._ticks(kernel) + self._ticks(user)) / 1e7, mem
        finally:
            self.k.CloseHandle(handle)


def mem_dict(total_bytes: Any, free_bytes: Any) -> Dict[str, Optional[int]]:
    """Memory in MB from bytes; used = total - free."""
    total, free = int(total_bytes) // 1048576, int(free_bytes) // 1048576
    return {"total_mb": total, "used_mb": max(total - free, 0), "free_mb": free}


# --- macOS (ctypes) -------------------------------------------------------------------------------------------------------------------------------------------

class _Mac:
    """Thin ctypes wrappers over libSystem (sysctlbyname, host_statistics, host_statistics64, libproc)."""

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
        self.scale = self._timebase()

    def sysctl_int(self, name: str, size: int = 8) -> int:
        value = self.c.c_uint64(0) if size == 8 else self.c.c_uint32(0)
        length = self.c.c_size_t(self.c.sizeof(value))
        if self.lib.sysctlbyname(name.encode(), self.c.byref(value), self.c.byref(length), None, 0) != 0:
            raise OSError(f"sysctl {name} failed")
        return int(value.value)

    def _timebase(self) -> float:
        """Nanoseconds per mach time unit (1 on Intel, 125/3 on Apple silicon)."""
        info = (self.c.c_uint32 * 2)()
        if self.lib.mach_timebase_info(info) != 0 or not info[1]:
            return 1.0
        return info[0] / info[1]

    def cpu_ticks(self) -> Tuple[float, float]:
        """(idle, total) ticks of HOST_CPU_LOAD_INFO: user, system, idle, nice."""
        ticks = (self.c.c_uint32 * 4)()
        count = self.c.c_uint32(4)
        if self.lib.host_statistics(self.host, 3, ticks, self.c.byref(count)) != 0:
            raise OSError("host_statistics failed")
        return float(ticks[2]), float(sum(ticks))

    def memory(self) -> Dict[str, Optional[int]]:
        """vm_statistics64: first four u32 are free, active, inactive, wire page counts; speculative_count is the u32 at byte 92 (after 9 u64 counters).
        Available to new programs = free + inactive + speculative pages."""
        total = self.sysctl_int("hw.memsize", 8)
        page = self.sysctl_int("hw.pagesize", 8)
        buf = (self.c.c_uint32 * 38)()
        count = self.c.c_uint32(38)
        if self.lib.host_statistics64(self.host, 4, buf, self.c.byref(count)) != 0:
            raise OSError("host_statistics64 failed")
        free_pages = buf[0] + buf[2] + buf[23]
        return mem_dict(total, min(free_pages * page, total))

    def processes(self) -> Dict[int, Tuple[str, float, float]]:
        """{pid: (name, cpu seconds, resident MB)} by libproc PROC_PIDTASKINFO; processes of other users are refused by the system and left out."""
        pids = (self.c.c_int * 8192)()
        got = self.lib.proc_listallpids(pids, self.c.sizeof(pids))
        found: Dict[int, Tuple[str, float, float]] = {}
        info = (self.c.c_uint64 * 12)()  # proc_taskinfo is 96 bytes: virtual, resident, user, system (u64) then counters
        name = self.c.create_string_buffer(256)
        for pid in list(pids)[: max(got, 0)]:
            if pid <= 0:
                continue
            if self.lib.proc_pidinfo(pid, 4, 0, info, self.c.sizeof(info)) != self.c.sizeof(info):
                continue
            if self.lib.proc_name(pid, name, 256) <= 0:
                continue
            seconds = (info[2] + info[3]) * self.scale / 1e9
            found[pid] = (name.value.decode("utf-8", "replace"), seconds, info[1] / 1048576.0)
        return found


# --- Linux (/proc) --------------------------------------------------------------------------------------------------------------------------------------------

def linux_cpu() -> Tuple[float, float]:
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        fields = [float(x) for x in handle.readline().split()[1:]]
    return fields[3] + (fields[4] if len(fields) > 4 else 0.0), sum(fields[:8])


def linux_memory() -> Dict[str, Optional[int]]:
    values: Dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, _, rest = line.partition(":")
            bits = rest.split()
            if bits and bits[0].isdigit():
                values[key] = int(bits[0]) * 1024
    return mem_dict(values["MemTotal"], values.get("MemAvailable", values.get("MemFree", 0)))


def linux_processes() -> Dict[int, Tuple[str, float, float]]:
    hertz = float(os.sysconf("SC_CLK_TCK") or 100)
    page = float(os.sysconf("SC_PAGE_SIZE") or 4096)
    found: Dict[int, Tuple[str, float, float]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            head, _, tail = text.rpartition(")")  # the name is in brackets and may hold spaces
            name = head.partition("(")[2]
            rest = tail.split()
            found[int(entry)] = (name, (float(rest[11]) + float(rest[12])) / hertz, float(rest[21]) * page / 1048576.0)
        except (OSError, ValueError, IndexError):
            continue
    return found


# --- the snapshot ---------------------------------------------------------------------------------------------------------------------------------------------

def reader() -> Tuple[Callable[[], Optional[Tuple[float, float]]], Callable[[], Dict[int, Tuple[str, float, float]]], Callable[[], Dict[str, Optional[int]]]]:
    """(cpu reading, process reading, memory reading) of this system; raises where the system calls cannot be set up."""
    if WINDOWS:
        win = _Win()
        return win.cpu_times, win.processes, win.memory
    if MAC:
        mac = _Mac()
        return mac.cpu_ticks, mac.processes, mac.memory
    return linux_cpu, linux_processes, linux_memory


def _try(make: Callable[[], Any], fallback: Any) -> Any:
    try:
        return make()
    except Exception:  # noqa: BLE001 - one piece failing never stops the others
        return fallback


def ps_rows(cores: int) -> List[Dict[str, Any]]:
    """The one `ps` call (macOS only, when libproc gave nothing)."""
    from core import procrun

    result = procrun.run(["ps", "-A", "-o", "%cpu=,rss=,comm="], 20)
    out = result.stdout
    return parse_ps(out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out or ""), cores)


def snapshot(cores: Optional[int], sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
             read: Optional[Any] = None) -> Dict[str, Any]:
    """CPU, top list and memory; CPU and processes share one SAMPLE_S wait. `read` = (cpu, processes, memory) readers (tests)."""
    out: Dict[str, Any] = {"cpu": {"busy_pct": None, "cores": cores}, "top": [], "memory": {"total_mb": None, "used_mb": None, "free_mb": None}}
    try:
        cpu_read, proc_read, mem_read = read or reader()
    except Exception:  # noqa: BLE001
        return out
    out["memory"] = _try(mem_read, out["memory"])
    began = clock()
    cpu_a = _try(cpu_read, None)
    procs_a = _try(proc_read, None)
    sleep(SAMPLE_S)
    cpu_b = _try(cpu_read, None)
    procs_b = _try(proc_read, None)
    elapsed = clock() - began
    if cpu_a and cpu_b:
        out["cpu"]["busy_pct"] = _try(lambda: busy_pct(cpu_a, cpu_b), None)
    if procs_a is not None and procs_b is not None and cores:
        rows = shares(procs_a, procs_b, elapsed, cores)
        if rows:
            out["top"] = group_top(rows)
    if not out["top"] and MAC and not read:
        out["top"] = _try(lambda: group_top(ps_rows(cores or 1)), [])
    return out


def collect(root: Path, run: Optional[Callable[..., Any]] = None, clock: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """The snapshot. `run(args, timeout)` starts a process (tests inject a fake); `clock` is a monotonic clock in seconds."""
    clock = clock or time.monotonic
    cores = _try(os.cpu_count, None)
    process = _try(lambda: measure_starts(root, run, clock), {"python_ms": None, "shell_ms": None})
    sample = _try(lambda: snapshot(cores, clock=clock), None) or {}
    return {
        "platform": platform_name(),
        "process": process,
        "cpu": sample.get("cpu") or {"busy_pct": None, "cores": cores},
        "memory": sample.get("memory") or {"total_mb": None, "used_mb": None, "free_mb": None},
        "top": sample.get("top") or [],
    }
