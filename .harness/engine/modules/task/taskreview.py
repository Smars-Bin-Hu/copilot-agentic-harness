"""Independent checks of a task: `[review]=n` (M11-5).

The user writes `[review]=n` in a prompt of the task. The result must then pass n checks in a row, each by a new
reviewer, all of them on the result as it is at the end: a result that changed starts the count again.

  task review start    the CLI snapshots the result, writes REVIEW/round-NNN/package.md and opens the round;
                       only then does the gate let the reviewer be called
  (hook)               the reviewer's answer is stored as REVIEW/round-NNN/verdict.md and the round is closed
  task review status   n, how many passes count now, how many checks were used
  task review extend   the person allows more checks after the limit (terminal only)
  task review waive    the person lets the promote go ahead without the passes (terminal only)

The number of checks is limited: n + `review.extra_checks` (task.json) + what the person allowed.
A promote dry-run is refused until the passes are there or the person waived them.
The state is `review` in task.json. Passes are not stored as a number: they are counted from the rounds and the
digest of the result as it is now, so nobody has to remember to reset them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, messages, tasks
from core.paths import cli_command, utc_now

from . import task as task_ops
from . import tasksnap
from .common import CommandError
from .policy import POLICY_NAME

AGENT = "reviewer"
DEFAULTS = {"extra_checks": 2, "max_n": 5}
PACKAGE = "package.md"
VERDICT_FILE = "verdict.md"
VERDICT_LINES = 3  # the verdict is looked for in this many non-empty lines from the top
_MARKER = re.compile(r"\[\s*review\s*\]\s*[=＝]\s*(\d{1,2})", re.IGNORECASE)
_CONFIRM_LABEL = re.compile(r"用户确认|user confirmed", re.IGNORECASE)
_CONFIRMED = re.compile(r"已确认|confirmed|\d{4}-\d{2}-\d{2}")
_NOT_CONFIRMED = re.compile(r"还没确认|not yet|not confirmed|yyyy-mm-dd")
_VERDICT = re.compile(r"^VERDICT\s*[:：]\s*(PASS|FAIL)\b", re.IGNORECASE)
# These kinds give back files of a target repository: before DEV/ holds something there is nothing to check yet.
DEV_KINDS = ("dev", "test", "kb")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def settings(root: Path) -> Dict[str, int]:
    found = config.policy_or_empty(root, POLICY_NAME).get("review") or {}  # a broken policy must not open or close a gate by accident
    return {key: found[key] if config.whole(found.get(key), -1) >= 0 else value for key, value in DEFAULTS.items()}


def marker(prompt: str) -> Optional[int]:
    """The n the user wrote in this prompt, or None."""
    found = _MARKER.search(prompt)
    return int(found.group(1)) if found else None


def parse_verdict(response: str) -> str:
    """`PASS`, `FAIL`, or `unknown`: the verdict line among the first non-empty lines, markdown marks around it ignored.

    It is meant to be the first line. A reviewer that says a sentence before it must not use up a check for that.
    """
    seen = 0
    for line in response.splitlines():
        line = line.strip().strip("*#>`_ ")
        if not line:
            continue
        found = _VERDICT.match(line)
        if found:
            return found.group(1).upper()
        seen += 1
        if seen >= VERDICT_LINES:
            break
    return "unknown"


def req_confirmed(root: Path, task: str) -> Optional[bool]:
    """Has the person filled in the confirmation line of REQ.md? None: no REQ.md, or no such line.

    The line is found by its label, in either language, so a task made in one language is still read in the other.
    It counts as filled in when what follows the label has a date or the word for confirmed, and not the words the
    template starts with.
    """
    try:
        text = (tasks.task_dir(root, task) / tasks.REQ_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        found = _CONFIRM_LABEL.search(line)
        if found:
            value = line[found.end():].lower()
            return bool(_CONFIRMED.search(value)) and not _NOT_CONFIRMED.search(value)  # the template has both on the line
    return None


# --- state ---------------------------------------------------------------------------------------


def state_of(data: Dict[str, Any]) -> Dict[str, Any]:
    review = data.setdefault("review", {})
    review.setdefault("n", 0)
    review.setdefault("rounds", [])
    review.setdefault("extra", 0)
    review.setdefault("waived", None)
    return review


def rounds_now(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The checks of the task's current round (a new round after a promote starts the count again)."""
    return [item for item in state_of(data)["rounds"] if item.get("task_round") == data["round"]]


def pending(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    found = [item for item in rounds_now(data) if not item.get("verdict")]
    return found[-1] if found else None


def passes(data: Dict[str, Any], digest: str) -> int:
    """Passes in a row, counted back from the last check, all on the result as it is now."""
    count = 0
    for item in reversed([item for item in rounds_now(data) if item.get("verdict")]):
        if item["verdict"] != "PASS" or item["digest"] != digest or not digest:
            break
        count += 1
    return count


def limit(root: Path, data: Dict[str, Any]) -> int:
    review = state_of(data)
    return review["n"] + settings(root)["extra_checks"] + review["extra"]


def used(data: Dict[str, Any]) -> int:
    return len([item for item in rounds_now(data) if item.get("verdict")])


def has_something(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is there a result to check? A task that changes a target repository: files in DEV/. Any other: a file besides REQ.md."""
    names = [relative for relative, _ in tasksnap.result_files(root, task)]
    if data.get("kind") in DEV_KINDS:
        return any(name.lower().startswith(tasks.DEV_NAME.lower() + "/") for name in names)
    return any(name.lower() != tasks.REQ_FILE.lower() for name in names)


def summary(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    review = state_of(data)
    digest = tasksnap.results_digest(root, task)
    done = [item for item in rounds_now(data) if item.get("verdict")]
    waived = bool(review["waived"]) and review["waived"].get("digest") == digest and review["waived"].get("task_round") == data["round"]
    return {
        "n": review["n"], "passes": passes(data, digest), "checks_used": used(data), "checks_limit": limit(root, data),
        "pending_round": (pending(data) or {}).get("number"), "last_verdict": done[-1]["verdict"] if done else "",
        "waived": waived, "digest": digest,
    }


def satisfied(root: Path, task: str, data: Dict[str, Any]) -> bool:
    info = summary(root, task, data)
    return info["n"] == 0 or info["passes"] >= info["n"] or info["waived"]


def set_n(root: Path, task: str, number: int) -> Dict[str, Any]:
    """Called by the hook when the user writes the marker in a prompt of the task."""
    number = min(number, settings(root)["max_n"])
    with task_ops.locked(root, task) as data:
        review = state_of(data)
        if review["n"] != number:
            review["n"] = number
            task_ops.note(data, "review", f"n={number}")
    return data


# --- the CLI -------------------------------------------------------------------------------------


def round_dir(task: str, number: int) -> str:
    return f"{task}/{tasksnap.REVIEW_DIR}/round-{number:03d}"


def package_text(root: Path, task: str, data: Dict[str, Any], entry: Dict[str, Any], files: List[Dict[str, Any]], diff_file: str, previous: Optional[Dict[str, Any]]) -> str:
    lines = [say("review.package.title", name=task_ops.name_of(task), number=entry["number"]), ""]
    lines.append(say("review.package.first") if entry["ordinal"] == 1 else say("review.package.later", ordinal=entry["ordinal"]))
    lines += ["", say("review.package.requirement"), ""]
    folder = tasks.task_dir(root, task)
    for name in (tasks.REQ_FILE, tasks.PLAN_NAME):
        if (folder / name).is_file():
            lines.append(f"- {task}/{name}")
    if (folder / "REQ").is_dir() and any((folder / "REQ").iterdir()):
        lines.append(f"- {task}/REQ/")
    if req_confirmed(root, task) is False:  # only the person fills that line in: the author cannot fix it, so it must not cost a check
        lines += ["", say("review.package.unconfirmed", req=f"{task}/{tasks.REQ_FILE}")]
    if diff_file:
        lines += ["", say("review.package.diff", path=diff_file)]
    lines += ["", say("review.package.files"), "", say("review.package.table"), "| --- | --- | --- |"]
    lines += [f"| {task}/{item['path']} | {item['sha256'][:16]} | {item['bytes']} |" for item in files]
    if previous is not None:
        lines += ["", say("review.package.previous", path=f"{round_dir(task, previous['number'])}/{VERDICT_FILE}"), ""]
        lines += ["> " + line for line in previous.get("answer", "").splitlines()[:40]]
    lines += ["", say("review.package.output"), ""]
    return "\n".join(lines)


def start(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        review = state_of(data)
        if review["n"] == 0:
            raise CommandError(say("review.off"))
        if not has_something(root, task, data):
            raise CommandError(say("review.nothing", task=task))
        digest = tasksnap.results_digest(root, task)
        if passes(data, digest) >= review["n"]:
            raise CommandError(say("review.enough", n=review["n"]))
        waiting = pending(data)
        if waiting is None and used(data) >= limit(root, data):
            raise CommandError(say("review.limit", used=used(data), limit=limit(root, data), task=task))
        diff_file = ""
        if any(relative.lower().startswith(tasks.DEV_NAME.lower() + "/") for relative, _ in tasksnap.result_files(root, task)) and data.get("target_files"):
            _, text = task_ops.changes(root, task, data)
            path = tasks.task_dir(root, task) / tasks.CHANGES_NAME
            path.write_text(text, encoding="utf-8")
            diff_file = f"{task}/{tasks.CHANGES_NAME}"
        done = [item for item in rounds_now(data) if item.get("verdict")]
        number = waiting["number"] if waiting else len(review["rounds"]) + 1
        snapshot = tasksnap.take(root, task, f"review-{number:03d}")
        entry = waiting or {"number": number, "task_round": data["round"]}
        entry.update(digest=snapshot["digest"], started_at=utc_now(), snapshot=snapshot["snapshot"], ordinal=len(done) + 1, verdict="")
        if waiting is None:
            review["rounds"].append(entry)
        previous = done[-1] if done and done[-1]["verdict"] != "PASS" else None
        folder = root / round_dir(task, number)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PACKAGE).write_text(package_text(root, task, data, entry, snapshot["files"], diff_file, previous), encoding="utf-8")
        task_ops.note(data, "review-start", f"round-{number:03d}")
        package = f"{round_dir(task, number)}/{PACKAGE}"
        info = {"n": review["n"], "passes": passes(data, snapshot["digest"]), "checks_used": used(data), "checks_limit": limit(root, data)}
    return {"task": task, "round": number, "package": package, "snapshot": snapshot["snapshot"], **info, "next": say("review.start.next", agent=AGENT, package=package)}


def record(root: Path, task: str, answer: str) -> Optional[Dict[str, Any]]:
    """Called by the hook when the reviewer's call has finished: close the open round with what it said. None if no round is open."""
    with task_ops.locked(root, task) as data:
        entry = pending(data)
        if entry is None:
            return None
        verdict = parse_verdict(answer)
        entry.update(verdict=verdict, finished_at=utc_now(), answer=answer[:6000])
        folder = root / round_dir(task, entry["number"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / VERDICT_FILE).write_text(answer.rstrip() + "\n", encoding="utf-8")
        task_ops.note(data, "review", f"round-{entry['number']:03d} {verdict}")
        digest = tasksnap.results_digest(root, task)
        info = {"verdict": verdict, "round": entry["number"], "n": state_of(data)["n"], "passes": passes(data, digest), "checks_used": used(data), "checks_limit": limit(root, data)}
    return info


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    info = summary(root, task, data)
    info.pop("digest")
    info["task"] = task
    info["next"] = next_text(root, task, data)
    return info


def next_text(root: Path, task: str, data: Dict[str, Any]) -> str:
    info = summary(root, task, data)
    if info["n"] == 0:
        return say("review.off")
    if info["waived"]:
        return say("review.next.waived")
    if info["passes"] >= info["n"]:
        return say("review.next.done", n=info["n"])
    if info["pending_round"]:
        return say("review.start.next", agent=AGENT, package=f"{round_dir(task, info['pending_round'])}/{PACKAGE}")
    if not has_something(root, task, data):
        return say("review.nothing", task=task)
    if info["checks_used"] >= info["checks_limit"]:
        return say("review.limit", used=info["checks_used"], limit=info["checks_limit"], task=task)
    left = info["n"] - info["passes"]
    if info["last_verdict"] and info["last_verdict"] != "PASS":
        return say("review.next.fix", left=left, verdict=f"{round_dir(task, used(data) and [item for item in rounds_now(data) if item.get('verdict')][-1]['number'])}/{VERDICT_FILE}")
    return say("review.next.more", left=left, n=info["n"])


def person(command: str, interactive: Optional[bool]) -> None:
    task_ops.person(command, interactive)


def extend(root: Path, raw_task: str, checks: int, reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None) -> Dict[str, Any]:
    person("task review extend", interactive)
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    info = summary(root, task, data)
    approval.say(out, say("review.extend.screen", task=task, used=info["checks_used"], limit=info["checks_limit"], checks=checks, last=info["last_verdict"] or "-"))
    task_ops.typed(say("review.extend.ask"), info["digest"] or "0" * 64, say("review.extend.no"), reader)
    with task_ops.locked(root, task) as again:
        state_of(again)["extra"] += checks
        task_ops.note(again, "review-extend", f"+{checks}")
        new_limit = limit(root, again)
    return {"task": task, "checks_limit": new_limit, "next": say("review.extend.next")}


def waive(root: Path, raw_task: str, reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None) -> Dict[str, Any]:
    person("task review waive", interactive)
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    info = summary(root, task, data)
    if info["n"] == 0 or info["passes"] >= info["n"]:
        raise CommandError(say("review.waive.unneeded"))
    approval.say(out, say("review.waive.screen", task=task, n=info["n"], passes=info["passes"], used=info["checks_used"], last=info["last_verdict"] or "-"))
    task_ops.typed(say("review.waive.ask"), info["digest"] or "0" * 64, say("review.waive.no"), reader)
    with task_ops.locked(root, task) as again:
        if tasksnap.results_digest(root, task) != info["digest"]:
            raise CommandError(say("review.waive.changed"))
        state_of(again)["waived"] = {"digest": info["digest"], "at": utc_now(), "task_round": again["round"]}
        task_ops.note(again, "review-waive", info["digest"][:12])
    return {"task": task, "waived": True, "next": say("review.waive.next")}


def require(root: Path, task: str, data: Dict[str, Any]) -> None:
    """Before a promote dry-run: the passes are there, or the person waived them."""
    if satisfied(root, task, data):
        return
    info = summary(root, task, data)
    raise CommandError(say("review.promote.refused", n=info["n"], passes=info["passes"], task=task) + next_text(root, task, data))
