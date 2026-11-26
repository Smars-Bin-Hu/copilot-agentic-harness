"""Independent checks of a task: `[review]=n` (M11-5).

The user sets n on the task page (`task review set`, a person only; 1.6), or writes `[review]=n` in a prompt of the task (still read, no longer shown).
The result must then pass n checks in a row, each by a new reviewer, all of them on the result as it is at the end: a result that changed starts the count again.

  task review start    the CLI snapshots the result, writes REVIEW/round-NNN/package.md and opens the round;
                       only then does the gate let the reviewer be called
  (hook)               the reviewer's answer is stored as REVIEW/round-NNN/verdict.md and the round is closed
  task review status   n, how many passes count now, how many checks were used
  task review set      the person sets n (0 to max_n), as the chips of the task page do (terminal or paired board only)
  task review extend   the person allows more checks after the limit (terminal only)
  task review waive    the person lets the promote go ahead without the passes (terminal only)
  task review dismiss  the person says a check judged wrong: it is given back (terminal only, or the board)

What a script can hold the reviewer to is in reviewcheck.py: `review start` is refused while the person's run is
not back, and a FAIL whose findings are all dropped (only items checked after the write-back, a `file:line` that does
not exist) is invalid and given back, up to `review.free_invalid` in a round of the task.

The number of checks is limited: n + `review.extra_checks` (task.json) + what the person allowed.
A promote dry-run is refused until the passes are there or the person waived them.
The state is `review` in task.json. Passes are not stored as a number: they are counted from the rounds and the
digest of the result as it is now, so nobody has to remember to reset them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import approval, config, filecache, messages, tasks
from core.paths import cli_command, utc_now

from . import evidence, task as task_ops
from . import reviewcheck, tasksnap
from .common import CommandError
from .policy import POLICY_NAME

AGENT = "reviewer"
DEFAULTS = {"extra_checks": 2, "max_n": 5, "free_invalid": 2}
PACKAGE = "package.md"
VERDICT_FILE = "verdict.md"
VERDICT_LINES = 3  # the verdict is looked for in this many non-empty lines from the top
CHANGED_SHOWN = 5  # the files changed after a pass that a message names; the rest are counted
_MARKER = re.compile(r"\[\s*review\s*\]\s*[=＝]\s*(\d{1,2})", re.IGNORECASE)
_CONFIRM_LABEL = re.compile(r"用户确认|user confirmed", re.IGNORECASE)
_CONFIRMED = re.compile(r"已确认|confirmed|\d{4}-\d{2}-\d{2}")
_NOT_CONFIRMED = re.compile(r"还没确认|not yet|not confirmed|yyyy-mm-dd")
_VERDICT = re.compile(r"^VERDICT\s*[:：]\s*(PASS|FAIL)\b", re.IGNORECASE)
# These kinds give back files of a target repository: before DEV/ holds something there is nothing to check yet.
DEV_KINDS = ("dev", "kb")
RESULTS_PREFIX = "test/results-"  # a test task writes nothing back: what it has to show are the results files of its environments (M40-5)


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
        text = filecache.read_text(tasks.task_dir(root, task) / tasks.REQ_FILE, "utf-8", "replace")
    except OSError:
        return None
    filled = confirm_line_filled(text)
    return None if filled is None else filled and not req_changed(root, task)


def confirm_line_filled(text: str) -> Optional[bool]:
    """Is the confirmation line of this text of REQ.md filled in? None: there is no such line."""
    for line in text.splitlines():
        found = _CONFIRM_LABEL.search(line)
        if found:
            value = line[found.end():].lower()
            return bool(_CONFIRMED.search(value)) and not _NOT_CONFIRMED.search(value)  # the template has both on the line
    return None


def req_changed(root: Path, task: str) -> bool:
    """The person confirmed a version of REQ.md (the harness kept what it asks for), and it asks for something else now."""
    kept = ((tasks.read(root, task) or {}).get("req") or {}).get("confirmed_sha256")
    return bool(kept) and kept != tasks.req_digest(root, task)


# --- state ---------------------------------------------------------------------------------------


def state_of(data: Dict[str, Any]) -> Dict[str, Any]:
    review = data.setdefault("review", {})
    review.setdefault("n", 0)
    review.setdefault("rounds", [])
    review.setdefault("extra", 0)
    review.setdefault("waived", None)
    return review


def counted(item: Dict[str, Any]) -> bool:
    """A finished check that counts: not given back (an invalid FAIL within the limit) and not dismissed by the person."""
    return bool(item.get("verdict")) and not item.get("refunded") and not item.get("dismissed")


def done_now(data: Dict[str, Any], after: bool = False) -> List[Dict[str, Any]]:
    """The finished checks of the current round of the task that count, in order. `after`: the checks after the close instead."""
    return [item for item in rounds_now(data, after) if counted(item)]


def rounds_now(data: Dict[str, Any], after: bool = False) -> List[Dict[str, Any]]:
    """The checks of the task's current round (a new round after a promote starts the count again). The checks after the close (`after`, 1.8.18)
    are kept apart: they are never the task's own checks, so they move no gate, dot or count of the work."""
    return [item for item in state_of(data)["rounds"] if item.get("task_round") == data["round"] and bool(item.get("after")) == after]


def pending(data: Dict[str, Any], after: bool = False) -> Optional[Dict[str, Any]]:
    found = [item for item in rounds_now(data, after) if not item.get("verdict")]
    return found[-1] if found else None


def passes(data: Dict[str, Any], digest: str, after: bool = False) -> int:
    """Passes in a row, counted back from the last check, all on the result as it is now."""
    count = 0
    for item in reversed(done_now(data, after)):
        if item["verdict"] != "PASS" or item["digest"] != digest or not digest:
            break
        count += 1
    return count


def outdated(root: Path, task: str, data: Dict[str, Any], digest: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The last check of the task that counts passed, but the result changed after it, so it counts no more (1.8.59). `{round, files, more}`: the
    result files added, removed or changed since that check, the first CHANGED_SHOWN of them, and how many more. None: no such check, or the task
    is settled (its checks are history). A run recorded in RUNS/ after the check is a change too: the evidence is part of what is checked."""
    if is_settled(data):
        return None
    done = done_now(data)
    if not done or done[-1]["verdict"] != "PASS" or not done[-1].get("digest"):
        return None
    last = done[-1]
    now = tasksnap.listing(root, task) if digest is None else None
    if (digest if now is None else tasksnap.digest_of(now)) == last["digest"]:
        return None  # the usual case: the files are listed again only when the pass is gone
    files = changed_since(root, task, last, now if now is not None else tasksnap.listing(root, task))
    return {"round": int(last.get("number") or 0), "files": files[:CHANGED_SHOWN], "more": max(0, len(files) - CHANGED_SHOWN)}


def changed_since(root: Path, task: str, entry: Dict[str, Any], now: List[Dict[str, Any]]) -> List[str]:
    """The result files that differ from what the check `entry` was given: from its snapshot, else from the file table of its package (the snapshot
    may be pruned; the table keeps 16 characters of each sha256). Empty when neither can be read."""
    old: Dict[str, str] = {}
    try:
        listed = json.loads((root / str(entry.get("snapshot") or "") / tasksnap.MANIFEST).read_text(encoding="utf-8")).get("files") or []
        old = {str(item["path"]): str(item["sha256"]) for item in listed if isinstance(item, dict) and item.get("path")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        old = {}
    if not old:
        prefix = f"| {task}/"
        try:
            text = (root / round_dir(task, int(entry.get("number") or 0)) / PACKAGE).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines():
            cells = [cell.strip() for cell in line.split("|")]
            if line.startswith(prefix) and len(cells) >= 4:
                old[cells[1][len(task) + 1:]] = cells[2]
        if not old:
            return []
    current = {item["path"]: item["sha256"] for item in now}
    return sorted(path for path in set(old) | set(current) if path not in old or path not in current or not current[path].startswith(old[path]))


def changed_text(found: Dict[str, Any]) -> str:
    """The sentence that says which pass no longer counts and what changed after it."""
    files = ", ".join(f"`{path}`" for path in found["files"]) or say("review.changed.unknown")
    if found["more"]:
        files += " " + say("review.changed.more", count=found["more"])
    return say("review.changed", round=found["round"], files=files)


def limit(root: Path, data: Dict[str, Any], after: bool = False) -> int:
    review = state_of(data)
    if after:
        found = after_of(data)
        return int(found.get("n") or 0) + settings(root)["extra_checks"] + int(found.get("extra") or 0)
    return review["n"] + settings(root)["extra_checks"] + review["extra"]


def used(data: Dict[str, Any], after: bool = False) -> int:
    return len(done_now(data, after))


# --- checks after the close (1.8.18) -----------------------------------------------------------------
# A closed task that had no checks can be checked afterwards: the person sets n (`task review set` on the closed task, or `[review]=n` in a prompt
# of a session that holds no open task), the agent binds its session with `task review after`, then runs `review start` and the reviewer as usual.
# The task stays closed: no new round, DEV/ is not moved, nothing is promoted. A FAIL is only recorded; a fix is a new task (`task fork`).


def after_of(data: Dict[str, Any]) -> Dict[str, Any]:
    """`review.after` of the task: n, who set it and when, the session that checks it. Empty when the person never asked for checks after the close."""
    found = state_of(data).get("after")
    return found if isinstance(found, dict) else {}


def is_after(data: Dict[str, Any]) -> bool:
    """The task is closed: a check of it now is a check after the close."""
    return data.get("status") == "closed"


def after_n(data: Dict[str, Any]) -> int:
    return int(after_of(data).get("n") or 0)


def has_something(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is there a result to check? A task that changes a target repository: files in DEV/. A test task: a results file. Any other: a file besides REQ.md."""
    names = [relative for relative, _ in tasksnap.result_files(root, task)]
    if data.get("kind") in DEV_KINDS:
        return any(name.lower().startswith(tasks.DEV_NAME.lower() + "/") for name in names)
    if data.get("kind") == "test":
        return any(name.lower().startswith(RESULTS_PREFIX) for name in names)
    return any(name.lower() != tasks.REQ_FILE.lower() for name in names)


def is_settled(data: Dict[str, Any]) -> bool:
    """The write-back is done, or the task is closed: its checks are history, no longer a gate."""
    return data.get("status") == "closed" or (data.get("promote") or {}).get("state") == "done"


def streak(data: Dict[str, Any], after: bool = False) -> int:
    """The passes in a row at the end of the checks of this round, all on the version the last check looked at. From the records alone."""
    done = done_now(data, after)
    if not done:
        return 0
    last, count = done[-1].get("digest"), 0
    for item in reversed(done):
        if item["verdict"] != "PASS" or item.get("digest") != last:
            break
        count += 1
    return count


def n_change(event: Dict[str, Any]) -> Optional[Tuple[Optional[int], int]]:
    """A line of the history that changed n: (n before or None, n after). `review` "n=2" (a prompt's mark), `review-set` "1 -> 2" (the person)."""
    detail = str(event.get("detail") or "")
    try:
        if event.get("what") == "review" and detail.startswith("n="):
            return None, int(detail[2:])
        if event.get("what") == "review-set" and "->" in detail:
            before, after = detail.split("->", 1)
            return int(before), int(after)
    except ValueError:
        return None
    return None


def n_of_round(data: Dict[str, Any], number: int) -> int:
    """The n wanted when an earlier round ended: the last change in it or before it; else the n before the first change after it; else n now (nothing changed it since).
    The history keeps its last lines only, so a round long ago can be read as n now."""
    found: Optional[int] = None
    for event in data.get("events") or []:
        change = n_change(event) if isinstance(event, dict) else None
        if change is None:
            continue
        if int(event.get("round") or 1) <= number:
            found = change[1]
        else:
            return found if found is not None else change[0] if change[0] is not None else int(state_of(data)["n"] or 0)
    return found if found is not None else int(state_of(data)["n"] or 0)


def dots(data: Dict[str, Any], root: Optional[Path] = None, task: str = "") -> Dict[str, Any]:
    """What the board draws for the checks of a task, from its records: `n` (the checks wanted), `passes` (in a row, at the end),
    `total` (finished checks that count this round), `fails` (of those, not passed), `last` (the last verdict or ""), `pending` (one is running),
    `waived`, `old` and `old_round`. The board shows one dot per wanted check: green for each pass in a row, red when the last one did not pass, hollow for the rest, a turning one while a check runs.
    With `root` and `task`, an open task's passes are counted on its files as they are now, as the gate counts them (1.8.59): passes the result changed
    after count no more; `old` says how many there were (a green ring each) and `old_round` the round of the last one. Without them, or for a settled
    task, the records alone: the passes at the end, on the version the last check looked at."""
    review = state_of(data)
    done = done_now(data)
    waived = bool(review["waived"]) and review["waived"].get("task_round") == data.get("round")
    found = {
        "n": int(review["n"] or 0), "passes": streak(data), "total": len(done), "fails": len([item for item in done if item["verdict"] != "PASS"]),
        "last": done[-1]["verdict"] if done else "", "pending": pending(data) is not None, "waived": waived, "old": 0, "old_round": 0,
    }
    if root is not None and task and found["n"] and found["passes"] and not waived and not is_settled(data) and done[-1].get("digest"):
        if tasksnap.results_digest(root, task) != done[-1]["digest"]:
            found.update(passes=0, old=min(found["passes"], found["n"]), old_round=int(done[-1].get("number") or 0))
    return found


def summary(root: Path, task: str, data: Dict[str, Any], settled: bool = False) -> Dict[str, Any]:
    """The checks of the task now. For a gate (`require`, autorun, the Stop check) the passes are counted on the files as they are now. `settled` is for what is
    shown: a task whose write-back is done, or that is closed, shows the checks as they stood (the last version checked), not compared again with files that
    changed afterwards (the patch promote writes, a draft written after the close)."""
    review = state_of(data)
    done = done_now(data)
    if settled and is_settled(data):
        waived = bool(review["waived"]) and review["waived"].get("task_round") == data["round"]
        found = {"passes": streak(data), "waived": waived, "digest": done[-1].get("digest", "") if done else "", "changed": None}
    else:
        digest = tasksnap.results_digest(root, task)
        waived = bool(review["waived"]) and review["waived"].get("digest") == digest and review["waived"].get("task_round") == data["round"]
        found = {"passes": passes(data, digest), "waived": waived, "digest": digest, "changed": None if waived else outdated(root, task, data, digest)}
    return {
        "n": review["n"], "passes": found["passes"], "checks_used": used(data), "checks_limit": limit(root, data),
        "pending_round": (pending(data) or {}).get("number"), "last_verdict": done[-1]["verdict"] if done else "",
        "waived": found["waived"], "digest": found["digest"], "changed": found["changed"],
    }


def after_summary(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """The checks after the close, with the keys of `summary`. The passes are counted on the files as they are now: a closed task's result does not change."""
    done = done_now(data, True)
    digest = tasksnap.results_digest(root, task)
    return {
        "n": after_n(data), "passes": passes(data, digest, True), "checks_used": used(data, True), "checks_limit": limit(root, data, True),
        "pending_round": (pending(data, True) or {}).get("number"), "last_verdict": done[-1]["verdict"] if done else "", "waived": False, "digest": digest, "changed": None,
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
    if entry.get("after"):
        lines += ["", say("review.package.after")]
    lines += ["", say("review.package.requirement"), ""]
    folder = tasks.task_dir(root, task)
    for name in (tasks.REQ_FILE, tasks.PLAN_NAME):
        if (folder / name).is_file():
            lines.append(f"- {task}/{name}")
    if (folder / "REQ").is_dir() and any((folder / "REQ").iterdir()):
        lines.append(f"- {task}/REQ/")
    if req_confirmed(root, task) is False:  # only the person fills that line in: the author cannot fix it, so it must not cost a check
        lines += ["", say("review.package.unconfirmed", req=f"{task}/{tasks.REQ_FILE}")]
    items = reviewcheck.done_items(root, task)
    if items["T"] or items["R"] or items["A"]:
        lines += ["", say("review.package.items", req=f"{task}/{tasks.REQ_FILE}", runs=f"{task}/{reviewcheck.RUNS_DIR}/",
                          after=", ".join(items["A"]) or "-")]
    if diff_file:
        lines += ["", say("review.package.diff", path=diff_file)]
    lines += ["", say("review.package.files"), "", say("review.package.table"), "| --- | --- | --- |"]
    lines += [f"| {task}/{item['path']} | {item['sha256'][:16]} | {item['bytes']} |" for item in files]
    runs = evidence.listing(root, task)
    if runs:  # the runs the task cites (1.7.9): the reviewer may run the reads again itself; a write or a procedure is refused to it
        lines += ["", say("review.package.evidence"), ""]
        lines += [f"- {item['id']} · {item['env']} · {say('desk.evidence.by.agent') if item['by'] == 'agent' else say('desk.evidence.by.person')} · {task}/{item['file']}" + (f" · `{item['command'].splitlines()[0][:160]}`" if item["command"] else "") for item in runs]
    if previous is not None and previous.get("refunded"):
        lines += ["", say("review.package.given_back", path=f"{round_dir(task, previous['number'])}/{VERDICT_FILE}"), ""]
        lines += [f"- {why_text(item)}: {item.get('text', '')[:200]}" for item in previous.get("dropped") or []]
    elif previous is not None:
        lines += ["", say("review.package.previous", path=f"{round_dir(task, previous['number'])}/{VERDICT_FILE}"), ""]
        lines += ["> " + line for line in previous.get("answer", "").splitlines()[:40]]
        if previous.get("dropped"):
            lines += ["", say("review.package.dropped"), ""]
            lines += [f"- {why_text(item)}: {item.get('text', '')[:200]}" for item in previous["dropped"]]
    lines += ["", say("review.package.output"), ""]
    return "\n".join(lines)


def not_ready(root: Path, task: str, data: Dict[str, Any]) -> str:
    """Why the result cannot be checked yet, or "": the person's run (a handoff) is not back, or an R item of REQ.md has no result in RUNS/.
    Refused before a round is opened, so it costs no check."""
    handed = data.get("handoff")
    if isinstance(handed, dict) and handed.get("what"):
        return say("review.handoff_open", what=handed.get("what", ""), env=handed.get("env", ""), task=task)
    missing = reviewcheck.missing_runs(root, task)
    if missing:
        return say("review.runs_missing", folders=", ".join(f"`{task}/{item}`" for item in missing), req=f"{task}/{tasks.REQ_FILE}", task=task)
    return ""


def why_text(item: Dict[str, Any]) -> str:
    """Why the script dropped a finding, in words."""
    keys = {"after": "review.dropped.after", "no_file": "review.dropped.no_file", "no_line": "review.dropped.no_line"}
    return say(keys.get(str(item.get("why")), "review.dropped.no_place"), items=", ".join(item.get("items") or []), file=item.get("file", ""), line=item.get("line", 0), lines=item.get("lines", 0))


def mark_run(root: Path, task: str, data: Dict[str, Any]) -> str:
    """`review start` was refused for a run that is not back: the harness hands the run to the person itself (1.5.34), so the
    board says the task waits for it whether or not the agent runs `task handoff run`. The first environment that has no
    result, with the words of its R items. Says what it marked, or "" (a handoff is open, or no item names an environment)."""
    if data.get("handoff"):
        return ""
    items = reviewcheck.done_items(root, task)
    envs = [folder.split("/")[1] for folder in reviewcheck.missing_runs(root, task, items) if folder.count("/") == 2]
    if not envs:
        return ""
    env = envs[0]
    lead = re.compile(rf"^{re.escape(env)}\s*[:：-]\s*", re.IGNORECASE)  # `[R1] DEV: ...`: the environment is said once, by the card (B63)
    what = " ".join(" ".join(lead.sub("", items["text"].get(name, name).strip()) for name in items["R"] if items["envs"].get(name) == env).split())
    from .tasklife import WHAT_LENGTH  # tasklife imports this module

    what = what if len(what) <= WHAT_LENGTH else what[: WHAT_LENGTH - 1] + "…"
    data["handoff"] = {"what": "run", "env": env, "since": utc_now(), "detail": what, "by": "harness"}
    task_ops.note(data, "handoff", f"run {env}: {what}")
    return say("review.runs_marked", env=env, what=what, folder=f"{task}/{reviewcheck.RUNS_DIR}/{env}/", req=f"{task}/{tasks.REQ_FILE}")


def require_checkable(data: Dict[str, Any]) -> bool:
    """An open task, or a closed one whose person asked for checks after the close. True for the latter."""
    if is_after(data):
        if after_n(data) == 0:
            raise CommandError(say("review.after.off", task=data["task"]))
        return True
    task_ops.require_open(data)
    if state_of(data)["n"] == 0:
        raise CommandError(say("review.off"))
    return False


def start(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    early = ""
    with task_ops.locked(root, task) as data:  # what refuses before a round: no check is used; a run that is not back is handed to the person
        after = require_checkable(data)
        if not has_something(root, task, data):
            raise CommandError(say("review.nothing", task=task))
        early = not_ready(root, task, data)
        if early and not data.get("handoff") and not after:
            early = mark_run(root, task, data) or early
    if early:
        raise CommandError(early)
    with task_ops.locked(root, task) as data:
        after = require_checkable(data)
        review = state_of(data)
        wanted = after_n(data) if after else review["n"]
        early = not_ready(root, task, data)
        if early:
            raise CommandError(early)
        digest = tasksnap.results_digest(root, task)
        if passes(data, digest, after) >= wanted:
            raise CommandError(say("review.after.enough" if after else "review.enough", n=wanted))
        waiting = pending(data, after)
        if waiting is None and used(data, after) >= limit(root, data, after):
            gone = None if after else outdated(root, task, data, digest)  # the last check passed: say what undid it, not where its problems are (1.8.59)
            if gone:
                raise CommandError(say("review.limit.changed", changed=changed_text(gone), used=used(data), limit=limit(root, data)))
            raise CommandError(say("review.after.limit" if after else "review.limit", used=used(data, after), limit=limit(root, data, after), task=task))
        diff_file = ""
        if any(relative.lower().startswith(tasks.DEV_NAME.lower() + "/") for relative, _ in tasksnap.result_files(root, task)) and (data.get("target_files") or data.get("manual_files")):
            _, text = task_ops.changes(root, task, data)
            path = tasks.task_dir(root, task) / tasks.CHANGES_NAME
            path.write_text(text, encoding="utf-8")
            diff_file = f"{task}/{tasks.CHANGES_NAME}"
        done = done_now(data, after)
        number = waiting["number"] if waiting else len(review["rounds"]) + 1
        snapshot = tasksnap.take(root, task, f"review-{number:03d}")
        entry = waiting or {"number": number, "task_round": data["round"], **({"after": True} if after else {})}
        entry.update(digest=snapshot["digest"], started_at=utc_now(), snapshot=snapshot["snapshot"], ordinal=len(done) + 1, verdict="")
        if waiting is None:
            review["rounds"].append(entry)
        previous = done[-1] if done and done[-1]["verdict"] != "PASS" else None
        given_back = [item for item in rounds_now(data, after) if item.get("refunded") and item.get("number") != number]
        if given_back and (not done or given_back[-1]["number"] > done[-1]["number"]):
            previous = given_back[-1]
        folder = root / round_dir(task, number)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PACKAGE).write_text(package_text(root, task, data, entry, snapshot["files"], diff_file, previous), encoding="utf-8")
        task_ops.note(data, "review-start", f"round-{number:03d}" + (" after" if after else ""))
        package = f"{round_dir(task, number)}/{PACKAGE}"
        info = {"n": wanted, "passes": passes(data, snapshot["digest"], after), "checks_used": used(data, after), "checks_limit": limit(root, data, after), "after": after}
    following = say("review.after.start.next", agent=AGENT, package=package, task=task_ops.name_of(task)) if after else say("review.start.next", agent=AGENT, package=package)
    return {"task": task, "round": number, "package": package, "snapshot": snapshot["snapshot"], **info, "next": following}


def record(root: Path, task: str, answer: str) -> Optional[Dict[str, Any]]:
    """Called by the hook when the reviewer's call has finished: close the open round with what it said. None if no round is open."""
    with task_ops.locked(root, task) as data:
        after = is_after(data)
        entry = pending(data, after)
        if entry is None:
            return None
        verdict = parse_verdict(answer)
        entry.update(verdict=verdict, finished_at=utc_now(), answer=answer[:6000])
        if verdict == "FAIL":
            try:
                found = reviewcheck.check(root, task, answer)
            except Exception:  # noqa: BLE001 - the check of the form must never lose the reviewer's answer
                found = {"dropped": [], "invalid": False}
            entry["dropped"] = found["dropped"]
            if found["invalid"]:
                given = len([item for item in rounds_now(data, after) if item.get("refunded")])
                entry["invalid"] = True
                entry["refunded"] = given < settings(root)["free_invalid"]
        folder = root / round_dir(task, entry["number"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / VERDICT_FILE).write_text(answer.rstrip() + "\n", encoding="utf-8")
        task_ops.note(data, "review", f"round-{entry['number']:03d} {verdict}" + (" invalid" if entry.get("invalid") else "") + (" after" if after else ""))
        digest = tasksnap.results_digest(root, task)
        info = {"verdict": verdict, "invalid": bool(entry.get("invalid")), "refunded": bool(entry.get("refunded")), "dropped": len(entry.get("dropped") or []), "round": entry["number"], "n": after_n(data) if after else state_of(data)["n"], "passes": passes(data, digest, after), "checks_used": used(data, after), "checks_limit": limit(root, data, after), "after": after}
    return info


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    info = after_summary(root, task, data) if is_after(data) and after_of(data) else summary(root, task, data, settled=True)
    info.pop("digest")
    info["task"] = task
    info["next"] = next_text(root, task, data)
    return info


def after_next(root: Path, task: str, data: Dict[str, Any]) -> str:
    """What comes next in the checks after the close. A FAIL changes nothing in the task: a fix is a new task."""
    info = after_summary(root, task, data)
    if info["n"] == 0:
        return say("review.after.off", task=task)
    if info["pending_round"]:
        return say("review.after.start.next", agent=AGENT, package=f"{round_dir(task, info['pending_round'])}/{PACKAGE}", task=task_ops.name_of(task))
    done = done_now(data, True)
    fail = f"{round_dir(task, done[-1]['number'])}/{VERDICT_FILE}" if done and done[-1]["verdict"] != "PASS" else ""
    if info["passes"] >= info["n"]:
        return say("review.after.done", n=info["n"])
    if not has_something(root, task, data):
        return say("review.nothing", task=task)
    if info["checks_used"] >= info["checks_limit"]:
        return say("review.after.limit", used=info["checks_used"], limit=info["checks_limit"], task=task) + (" " + say("review.after.fail", verdict=fail, name=task_ops.name_of(task)) if fail else "")
    if fail:
        return say("review.after.fail", verdict=fail, name=task_ops.name_of(task)) + " " + say("review.after.more", left=info["n"] - info["passes"], task=task_ops.name_of(task))
    return say("review.after.more", left=info["n"] - info["passes"], task=task_ops.name_of(task))


def next_text(root: Path, task: str, data: Dict[str, Any]) -> str:
    if is_after(data) and after_of(data):
        return after_next(root, task, data)
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
    handed = data.get("handoff")
    if isinstance(handed, dict) and handed.get("what"):
        return say("review.handoff_open", what=handed.get("what", ""), env=handed.get("env", ""), task=task)  # the person's result first, whatever the last verdict said
    if info["changed"]:
        return undone_text(info)
    if info["checks_used"] >= info["checks_limit"]:
        return say("review.limit", used=info["checks_used"], limit=info["checks_limit"], task=task)
    left = info["n"] - info["passes"]
    if info["last_verdict"] and info["last_verdict"] != "PASS":
        return say("review.next.fix", left=left, verdict=f"{round_dir(task, done_now(data)[-1]['number'])}/{VERDICT_FILE}")
    return say("review.next.more", left=left, n=info["n"])


def undone_text(info: Dict[str, Any]) -> str:
    """The pass of the last check counts no more (`info` is a `summary` with `changed`): why, and what comes next. Past the limit only the person
    can go on, and the agent is not sent to a verdict that passed."""
    reason = changed_text(info["changed"])
    if info["checks_used"] >= info["checks_limit"]:
        return say("review.limit.changed", changed=reason, used=info["checks_used"], limit=info["checks_limit"])
    return say("review.next.changed", changed=reason, left=info["n"] - info["passes"], n=info["n"])


def undone(root: Path, task: str, data: Dict[str, Any]) -> str:
    """For a command that wrote a result file (`task run record`): when the pass of the last check counts no more, say so and what comes next; else ""."""
    if is_after(data) or not state_of(data)["n"]:
        return ""
    info = summary(root, task, data)
    if info["waived"] or not info["changed"] or info["pending_round"]:
        return ""
    return undone_text(info)


def person(command: str, interactive: Optional[bool], typed: bool = True) -> None:
    task_ops.person(command, interactive, typed)


def set_by_person(root: Path, raw_task: str, number: int, interactive: Optional[bool] = None) -> Dict[str, Any]:
    """The person sets the n of the task (the chips of the task page). No code is typed: it changes nothing that cannot be changed back. The limit, the cap (`review.max_n`),
    the count and the reset when files change are those of `[review]=n`: n moves the limit (n + extra checks + what the person allowed), nothing else.
    The agent is told by the rules of its next prompt (`review.inject`, or `review.inject.off` once the person has set 0 after checks were on)."""
    person("task review set", interactive, typed=False)
    top = settings(root)["max_n"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 0 or number > top:
        raise CommandError(say("review.set.range", max=top))
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        if is_after(data):
            return set_after(root, task, data, number, "person")
        task_ops.require_open(data)
        review = state_of(data)
        before = review["n"]
        if before != number:
            review["n"] = number
            review["set"] = {"n": number, "at": utc_now()}
            task_ops.note(data, "review-set", f"{before} -> {number}")
        return {"task": task, "n": number, "was": before, "changed": before != number, "checks_limit": limit(root, data), "next": say("review.set.next", n=number)}


def set_after(root: Path, task: str, data: Dict[str, Any], number: int, by: str) -> Dict[str, Any]:
    """Set n of the checks after the close, inside the caller's lock. `by`: `person` (the page or the terminal) or `prompt` (`[review]=n` in the person's words)."""
    found = state_of(data).setdefault("after", {})
    before = int(found.get("n") or 0)
    number = min(number, settings(root)["max_n"])
    if before != number:
        found["n"] = number
        found["set"] = {"n": number, "at": utc_now(), "by": by}
        task_ops.note(data, "review-after-set", f"{before} -> {number}")
    return {"task": task, "n": number, "was": before, "changed": before != number, "after": True, "checks_limit": limit(root, data, True), "next": say("review.after.set.next", n=number, task=task_ops.name_of(task))}


def bind_after(root: Path, raw_task: str, session_id: str, surface: str = "vscode") -> Dict[str, Any]:
    """`task review after`: this session checks a closed task. n is the person's: set on the page or at a terminal, or the `[review]=n` the hook kept from
    the person's prompt in this session (`review_n`, set again by every prompt). The task stays closed; the session keeps it as `after_review`, where the
    gate finds the task of a reviewer call when the session holds no open task."""
    from core.state import admin_on, session, state_path

    task = task_ops.resolve(root, raw_task)
    if not state_path(root, surface, session_id).exists():
        raise CommandError(say("task.session.missing", session_id=session_id))
    with session(root, surface, session_id) as state:
        if state.get("parent_session_id") or admin_on(state):
            raise CommandError(say("review.after.session"))
        asked = (state["modules"].get("task") or {}).get("review_n")
        with task_ops.locked(root, task) as data:
            if not is_after(data):
                raise CommandError(say("review.after.open", task=task_ops.name_of(task)))
            if isinstance(asked, int) and not isinstance(asked, bool) and asked > 0:
                set_after(root, task, data, asked, "prompt")
            if after_n(data) == 0:
                raise CommandError(say("review.after.off", task=task))
            if not has_something(root, task, data):
                raise CommandError(say("review.nothing", task=task))
            after_of(data).update(session=session_id, surface=surface, bound_at=utc_now())
            task_ops.note(data, "review-after", say("task.note.session", session_id=session_id))
        state["after_review"] = task
    data = task_ops.read(root, task)
    info = after_summary(root, task, data)
    return {"task": task, "n": info["n"], "after": True, "passes": info["passes"], "checks_used": info["checks_used"], "checks_limit": info["checks_limit"], "next": after_next(root, task, data)}


def checks_ok(root: Path, number: Any) -> bool:
    """Is this a number of checks the board may set (`set_by_person` would take it): a whole number from 0 up to the cap (`review.max_n`), never a bool."""
    return isinstance(number, int) and not isinstance(number, bool) and 0 <= number <= settings(root)["max_n"]


def set_pending(root: Path, raw_task: str, number: int) -> bool:
    """A person's n for a task that is closed (1.8.17, reopen from the super view): kept in `pending_checks` of the task state, applied by `apply_pending` once the task is open.
    True when the task is open already (the caller applies it now). It changes nothing the person cannot change back; the checks are never set from a request the paired browser did not make."""
    task = task_ops.resolve(root, raw_task)
    with task_ops.locked(root, task) as data:
        data["pending_checks"] = number
        return data["status"] == "open"


def apply_pending(root: Path, raw_task: str) -> Optional[Dict[str, Any]]:
    """Set the n kept by `set_pending` through `set_by_person` (the board's `review set`) when the task is open, then forget it (a value that cannot be set any more, as the cap fell, is forgotten too).
    A closed task keeps it. None when nothing was pending or nothing was done."""
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    number = data.get("pending_checks")
    if number is None or data["status"] != "open":
        return None
    try:
        done = set_by_person(root, task, number if isinstance(number, int) else -1, interactive=True)
    except CommandError:
        done = None
    with task_ops.locked(root, task) as again:
        again.pop("pending_checks", None)
    return done


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
        again["waiting"] = {"since": utc_now(), "why": "go-review"}  # the agent is not told: the board says so until the next prompt
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
        again["waiting"] = {"since": utc_now(), "why": "go-review"}
    return {"task": task, "waived": True, "next": say("review.waive.next")}


def dismissable(data: Dict[str, Any], number: int = 0) -> Optional[Dict[str, Any]]:
    """The finished check the person may dismiss: round `number`, or the newest that counts. Only one that did not pass, of the current round of the task."""
    found = [item for item in done_now(data) if not number or int(item.get("number") or 0) == number]
    return found[-1] if found and found[-1]["verdict"] != "PASS" else None  # a FAIL with a PASS after it is settled: the page must not say the newest check failed


def dismiss(root: Path, raw_task: str, number: int = 0, reader: Optional[Callable[[str], str]] = None, interactive: Optional[bool] = None, out: Any = None) -> Dict[str, Any]:
    """The person says a check judged wrong: it no longer counts, as a check used or as a FAIL. Recorded in the task's history and LOG.md."""
    person("task review dismiss", interactive)
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    task_ops.require_open(data)
    entry = dismissable(data, number)
    if entry is None:
        raise CommandError(say("review.dismiss.none", task=task, round=f"round-{number:03d}" if number else "-"))
    name = f"round-{int(entry['number']):03d}"
    approval.say(out, say("review.dismiss.screen", task=task, round=name, verdict=entry["verdict"], path=f"{round_dir(task, int(entry['number']))}/{VERDICT_FILE}"))
    task_ops.typed(say("review.dismiss.ask"), entry.get("digest") or "0" * 64, say("review.dismiss.no"), reader)
    with task_ops.locked(root, task) as again:
        fresh = next((item for item in rounds_now(again) if item.get("number") == entry["number"]), None)
        if fresh is None or not counted(fresh):
            raise CommandError(say("review.dismiss.none", task=task, round=name))
        fresh["dismissed"] = {"at": utc_now()}
        task_ops.note(again, "review-dismiss", name)
        again["waiting"] = {"since": utc_now(), "why": "go-review"}
        info = {"checks_used": used(again), "checks_limit": limit(root, again)}
    from . import testrecord  # the one writer of a LOG.md line

    testrecord.log_update(tasks.task_dir(root, task), say("review.dismiss.log", day=utc_now()[:10], round=name, verdict=entry["verdict"]))
    return {"task": task, "dismissed": name, **info, "next": say("review.dismiss.next")}


def require(root: Path, task: str, data: Dict[str, Any]) -> None:
    """Before a promote dry-run: the passes are there, or the person waived them."""
    if satisfied(root, task, data):
        return
    info = summary(root, task, data)
    raise CommandError(say("review.promote.refused", n=info["n"], passes=info["passes"], task=task) + next_text(root, task, data))
