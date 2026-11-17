"""The files of a task in autorun that the gate and the task module both read and write (1.8): TODO.md steps, QUESTIONS.md, the run ledger, the tally of the running worker call,
and the held-call line. Here, in core, so that the gate does not import the task module (a module imports only core). Standard library plus `core.tasks`, `core.state` only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import tasks
from .state import atomic_write

STEP = re.compile(r"^\s*[-*]\s+\[( |x|X|\?)\]\s*(.*)$")
MODEL = re.compile(r"\s*\(model:\s*([^\s()]+)\)\s*$")
QUESTION = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+Q(\d+)\s+\(step\s+(\d+)\)\s*(.*)$")
PLACEHOLDER = re.compile(r"^<[^<>]*>$")  # the line the template comes with: not a step yet
STEP_SHOWN = 120
QUESTIONS_FILE = "QUESTIONS.md"
LEDGER_FILE = "autorun-run.jsonl"
TALLY_FILE = "autorun-call.json"  # what the running worker call did so far: files edited, calls refused, calls held (the end line of the ledger reads it)
HELD_SHOWN = 200


def state_dir(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.STATE_DIR


def steps_of(root: Path, task: str) -> List[Dict[str, Any]]:
    """The steps of TODO.md: {done, parked, text, model, n}. `[?]` is parked (`done` stays False); a trailing `(model: x)` is cut from the text. A line that is not a checkbox is not a step."""
    try:
        text = (tasks.task_dir(root, task) / tasks.TODO_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = STEP.match(line)
        if not match:
            continue
        body = match.group(2).strip()
        model = ""
        tail = MODEL.search(body)
        if tail:
            model = tail.group(1)
            body = body[: tail.start()].strip()
        if body and not PLACEHOLDER.match(body):
            found.append({"done": match.group(1) in ("x", "X"), "parked": match.group(1) == "?", "text": body, "model": model, "n": len(found) + 1})
    return found


def open_steps_of(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [step for step in steps if not step["done"] and not step["parked"]]


def questions_of(root: Path, task: str) -> List[Dict[str, Any]]:
    """QUESTIONS.md: {id, n, step, text, took, answer, open, held}. An unreadable file has none."""
    try:
        text = (tasks.task_dir(root, task) / QUESTIONS_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        match = QUESTION.match(line)
        if not match:
            continue
        body, _sep, answer = match.group(4).partition(" | answer:")
        asked, sep, took = body.rpartition(" | took:")
        if not sep:
            asked, took = body, ""
        asked = asked.strip()
        found.append({
            "id": f"Q{match.group(2)}", "n": int(match.group(2)), "step": int(match.group(3)), "text": asked, "took": took.strip(), "answer": answer.strip(),
            "open": match.group(1) == " ", "held": asked.startswith("[held:"),
        })
    return found


def ledger_append(root: Path, task: str, row: Dict[str, Any]) -> None:
    """Never raises: a missing line must not stop a run."""
    try:
        path = state_dir(root, task) / LEDGER_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001
        pass


def ledger_read(root: Path, task: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with (state_dir(root, task) / LEDGER_FILE).open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def tally_of(root: Path, task: str) -> Dict[str, Any]:
    try:
        found = json.loads((state_dir(root, task) / TALLY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def tally_add(root: Path, task: str, key: str, value: Any = 1) -> None:
    """`key` is `files` (a path is added once), `denied` or `held` (a count). Never raises."""
    try:
        found = tally_of(root, task)
        if key == "files":
            files = found.setdefault("files", [])
            if value not in files:
                files.append(value)
        else:
            found[key] = int(found.get(key, 0)) + int(value)
        atomic_write(state_dir(root, task) / TALLY_FILE, found)
    except Exception:  # noqa: BLE001
        pass


def open_call(root: Path, task: str) -> Optional[Dict[str, Any]]:
    """The last `start` line that has no `end` line yet."""
    rows = ledger_read(root, task)
    ended = {row.get("call") for row in rows if row.get("event") == "end"}
    started = [row for row in rows if row.get("event") == "start" and row.get("call") not in ended]
    return started[-1] if started else None


def one_line(text: str, limit: int = HELD_SHOWN) -> str:
    return " ".join(str(text).split())[:limit]


def park_held_call(root: Path, task: str, tool: str, summary: str, denied: bool = False) -> None:
    """A call of the worker was held (or refused): a line in QUESTIONS.md for the person, `took: held`. The next number, the running step (else the first open one).
    `took: held`, not `none`: a held call is an open question for the end, never the park of a step
    (the worker may have found another way and finished it). Only the worker's own `took: none` parks. The same call twice in a row is one line. Counts it in the tally of the call. Never raises."""
    try:
        tally_add(root, task, "denied" if denied else "held")
        what = f"[held: {one_line(tool, 60)}] {one_line(summary)}"
        asked = questions_of(root, task)
        if asked and asked[-1]["text"] == what:
            return
        started = open_call(root, task)
        step = started.get("step") if started else None
        if not isinstance(step, int):
            open_ones = open_steps_of(steps_of(root, task))
            step = open_ones[0]["n"] if open_ones else 0
        number = max([item["n"] for item in asked], default=0) + 1
        path = tasks.task_dir(root, task) / QUESTIONS_FILE
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
        head = existing if existing.strip() else "# Open questions\n\n"
        if not head.endswith("\n"):
            head += "\n"
        path.write_bytes(f"{head}- [ ] Q{number} (step {step}) {what} | took: held\n".encode("utf-8"))  # the text as written: Windows must not turn \n into \r\n
    except Exception:  # noqa: BLE001
        pass
