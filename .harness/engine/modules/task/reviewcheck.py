"""What a script can hold the reviewer to (1.5.31). The reviewer's judgment itself is not checked here: only its form.

  done_items    the numbered items of "Done when" in REQ.md: `[T1]` shown by the task files, `[R1] DEV: ...` shown by a
                run the person does before the write-back, `[A1]` shown after the write-back (not the reviewer's)
  missing_runs  the environments of the R items with no file in `RUNS/<env>/` yet: `task review start` is refused
  check         the findings of a FAIL: one whose basis is only A items, or whose `file:line` does not exist, is
                dropped; a FAIL with no finding left is invalid (the check is given back, up to a limit)

A REQ.md without numbered items is checked as before: only `file:line` is looked at.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import tasks

RUNS_DIR = "RUNS"
_DONE_HEADINGS = ("done when", "做完的标准")
_HEADING = re.compile(r"^(#{1,6})\s*(.*?)\s*$")
_ITEM = re.compile(r"\[([TRA])(\d{1,3})\]")
_RUN_ENV = re.compile(r"\[R(\d{1,3})\]\s*`?([A-Za-z][A-Za-z0-9_-]{0,39})`?\s*[:：]")
_CITED = re.compile(r"(?<![A-Za-z0-9])\[?([TRA])(\d{1,3})\]?(?![A-Za-z0-9])")  # an item named in a basis, with or without its brackets
_PLACEHOLDER = re.compile(r"\[[TRA]\d{1,3}\]\s*<")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_BASIS = re.compile(r"\|\s*(?:basis|依据)\s*[:：]", re.IGNORECASE)
_PLACE = re.compile(r"^\s*[`*]*([^\s`*|]+?):(\d+)(?:\s*[-–]\s*\d+)?[`*]*(?=[\s,;:)]|$)")  # markdown marks around it are allowed
MAX_LINES_BYTES = 20 * 1024 * 1024
MAX_SEARCH = 5000  # files of a task folder looked through for a bare file name


def done_items(root: Path, task: str) -> Dict[str, Any]:
    """The numbered items of the "Done when" section (either language), by group. `envs`: the environment of each R item, upper case."""
    found: Dict[str, Any] = {"T": [], "R": [], "A": [], "envs": {}}
    try:
        text = (tasks.task_dir(root, task) / tasks.REQ_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    inside, level = False, 0
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            depth, title = len(heading.group(1)), heading.group(2).strip("*_ ").lower()
            if title in _DONE_HEADINGS:
                inside, level = True, depth
                continue
            if inside and depth <= level:
                inside = False
            continue
        if not inside or _PLACEHOLDER.search(line):
            continue  # a line of the template left as it was is not an item
        for group, number in _ITEM.findall(line):
            name = f"{group}{int(number)}"
            if name not in found[group]:
                found[group].append(name)
        for number, env in _RUN_ENV.findall(line):
            found["envs"][f"R{int(number)}"] = env.upper()
    return found


def missing_runs(root: Path, task: str, items: Optional[Dict[str, Any]] = None) -> List[str]:
    """The environments named by R items that have no file under `RUNS/<env>/` (any case) yet."""
    items = items if items is not None else done_items(root, task)
    if not items["R"]:
        return []
    runs = tasks.task_dir(root, task) / RUNS_DIR
    envs, anything = set(), False
    for path in runs.rglob("*") if runs.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            anything = True
            parts = path.relative_to(runs).parts
            if len(parts) > 1:
                envs.add(parts[0].upper())
    wanted = sorted({items["envs"].get(name, "") for name in items["R"]})
    missing = [f"{RUNS_DIR}/{env}/" for env in wanted if env and env not in envs]
    if "" in wanted and not anything:  # an R item that names no environment: any file in RUNS/ will do
        missing.append(f"{RUNS_DIR}/")
    return missing


def findings(answer: str) -> List[Dict[str, Any]]:
    """The finding lines of an answer: bullets that carry a `| basis:` part (the others are evidence). A bullet may run on over the next lines."""
    bullets: List[str] = []
    going = False
    for line in answer.splitlines():
        found = _BULLET.match(line)
        if found:
            bullets.append(found.group(1).strip())
            going = True
        elif going and line.strip() and not line.lstrip().startswith("#"):
            bullets[-1] += " " + line.strip()
        else:
            going = False
    out = []
    for text in bullets:
        split = _BASIS.search(text)
        if not split:
            continue
        place = _PLACE.match(text[:split.start()])
        out.append({
            "text": text, "file": place.group(1).strip("`'\"") if place else "", "line": int(place.group(2)) if place else 0,
            "basis": text[split.end():].strip(),
        })
    return out


def _bases(root: Path) -> List[Path]:
    found = [root]
    try:
        from core import targets

        found += [repo.path for _name, repo in sorted(targets.load(root).repos.items())]
    except Exception:  # noqa: BLE001 - a broken targets policy: only the harness and the task folder are looked in
        pass
    return found


def _lines(path: Path) -> int:
    try:
        if path.stat().st_size > MAX_LINES_BYTES:
            return 1 << 30  # too big to count: any line is taken
        data = path.read_bytes()
    except OSError:
        return -1
    return data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


def place_lines(root: Path, task: str, name: str) -> int:
    """The most lines of a file the reviewer may mean by `name`, or -1 when no such file is found.
    Looked for from the repository root, the task folder, the target repositories and the knowledge base, then as the end of a path inside the task folder."""
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    if not name:
        return -1
    folder = tasks.task_dir(root, task)
    candidates = [Path(name)] if Path(name).is_absolute() else [base / name for base in [folder] + _bases(root)]
    best = max((_lines(path) for path in candidates if path.is_file()), default=-1)
    if best >= 0:
        return best
    tail = "/" + name.lower()
    seen = 0
    for path in folder.rglob("*") if folder.is_dir() else []:
        seen += 1
        if seen > MAX_SEARCH:
            break
        if path.is_file() and ("/" + path.relative_to(folder).as_posix().lower()).endswith(tail):
            best = max(best, _lines(path))
    return best


def check(root: Path, task: str, answer: str, items: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The findings of a FAIL as a script sees them. `dropped`: each with its text and why. `invalid`: no finding is left."""
    items = items if items is not None else done_items(root, task)
    after = set(items["A"])
    dropped, kept = [], 0
    for item in findings(answer):
        cited = {f"{group}{int(number)}" for group, number in _CITED.findall(item["basis"])}
        why: Dict[str, Any] = {}
        if cited and cited <= after:
            why = {"why": "after", "items": sorted(cited)}
        elif not item["file"]:
            why = {"why": "no_place"}
        else:
            lines = place_lines(root, task, item["file"])
            if lines < 0:
                why = {"why": "no_file", "file": item["file"]}
            elif item["line"] < 1 or item["line"] > max(lines, 1):
                why = {"why": "no_line", "file": item["file"], "line": item["line"], "lines": lines}
        if why:
            dropped.append({"text": item["text"][:300], **why})
        else:
            kept += 1
    return {"dropped": dropped, "kept": kept, "invalid": kept == 0}
