"""Independent checks of a task: `[review]=n` (M11-5).

The user writes `[review]=n` in a prompt of the task. The result must then pass n checks in a row, each by a new
reviewer, all of them on the result as it is at the end: a result that changed starts the count again.

  task review start    the CLI snapshots the result, writes REVIEW/round-NNN/package.md and opens the round;
                       only then does the gate let the reviewer be called
  (hook)               the reviewer's answer is stored as REVIEW/round-NNN/verdict.md and the round is closed
  task review status   n, how many passes count now, how many checks were used
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

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core import approval, config, messages, tasks
from core.paths import cli_command, utc_now

from . import task as task_ops
from . import reviewcheck, tasksnap
from .common import CommandError
from .policy import POLICY_NAME

AGENT = "reviewer"
DEFAULTS = {"extra_checks": 2, "max_n": 5, "free_invalid": 2}
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
            filled = bool(_CONFIRMED.search(value)) and not _NOT_CONFIRMED.search(value)  # the template has both on the line
            return filled and not req_changed(root, task)
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


def done_now(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The finished checks of the current round of the task that count, in order."""
    return [item for item in rounds_now(data) if counted(item)]


def rounds_now(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The checks of the task's current round (a new round after a promote starts the count again)."""
    return [item for item in state_of(data)["rounds"] if item.get("task_round") == data["round"]]


def pending(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    found = [item for item in rounds_now(data) if not item.get("verdict")]
    return found[-1] if found else None


def passes(data: Dict[str, Any], digest: str) -> int:
    """Passes in a row, counted back from the last check, all on the result as it is now."""
    count = 0
    for item in reversed(done_now(data)):
        if item["verdict"] != "PASS" or item["digest"] != digest or not digest:
            break
        count += 1
    return count


def limit(root: Path, data: Dict[str, Any]) -> int:
    review = state_of(data)
    return review["n"] + settings(root)["extra_checks"] + review["extra"]


def used(data: Dict[str, Any]) -> int:
    return len(done_now(data))


def has_something(root: Path, task: str, data: Dict[str, Any]) -> bool:
    """Is there a result to check? A task that changes a target repository: files in DEV/. Any other: a file besides REQ.md."""
    names = [relative for relative, _ in tasksnap.result_files(root, task)]
    if data.get("kind") in DEV_KINDS:
        return any(name.lower().startswith(tasks.DEV_NAME.lower() + "/") for name in names)
    return any(name.lower() != tasks.REQ_FILE.lower() for name in names)


def is_settled(data: Dict[str, Any]) -> bool:
    """The write-back is done, or the task is closed: its checks are history, no longer a gate."""
    return data.get("status") == "closed" or (data.get("promote") or {}).get("state") == "done"


def streak(data: Dict[str, Any]) -> int:
    """The passes in a row at the end of the checks of this round, all on the version the last check looked at. From the records alone."""
    done = done_now(data)
    if not done:
        return 0
    last, count = done[-1].get("digest"), 0
    for item in reversed(done):
        if item["verdict"] != "PASS" or item.get("digest") != last:
            break
        count += 1
    return count


def summary(root: Path, task: str, data: Dict[str, Any], settled: bool = False) -> Dict[str, Any]:
    """The checks of the task now. For a gate (`require`, autorun, the Stop check) the passes are counted on the files as they are now. `settled` is for what is
    shown: a task whose write-back is done, or that is closed, shows the checks as they stood (the last version checked), not compared again with files that
    changed afterwards (the patch promote writes, a draft written after the close)."""
    review = state_of(data)
    done = done_now(data)
    if settled and is_settled(data):
        waived = bool(review["waived"]) and review["waived"].get("task_round") == data["round"]
        found = {"passes": streak(data), "waived": waived, "digest": done[-1].get("digest", "") if done else ""}
    else:
        digest = tasksnap.results_digest(root, task)
        waived = bool(review["waived"]) and review["waived"].get("digest") == digest and review["waived"].get("task_round") == data["round"]
        found = {"passes": passes(data, digest), "waived": waived, "digest": digest}
    return {
        "n": review["n"], "passes": found["passes"], "checks_used": used(data), "checks_limit": limit(root, data),
        "pending_round": (pending(data) or {}).get("number"), "last_verdict": done[-1]["verdict"] if done else "",
        "waived": found["waived"], "digest": found["digest"],
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
    items = reviewcheck.done_items(root, task)
    if items["T"] or items["R"] or items["A"]:
        lines += ["", say("review.package.items", req=f"{task}/{tasks.REQ_FILE}", runs=f"{task}/{reviewcheck.RUNS_DIR}/",
                          after=", ".join(items["A"]) or "-")]
    if diff_file:
        lines += ["", say("review.package.diff", path=diff_file)]
    lines += ["", say("review.package.files"), "", say("review.package.table"), "| --- | --- | --- |"]
    lines += [f"| {task}/{item['path']} | {item['sha256'][:16]} | {item['bytes']} |" for item in files]
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
    what = " ".join(" ".join(items["text"].get(name, name) for name in items["R"] if items["envs"].get(name) == env).split())
    from .tasklife import WHAT_LENGTH  # tasklife imports this module

    what = what if len(what) <= WHAT_LENGTH else what[: WHAT_LENGTH - 1] + "…"
    data["handoff"] = {"what": "run", "env": env, "since": utc_now(), "detail": what, "by": "harness"}
    task_ops.note(data, "handoff", f"run {env}: {what}")
    return say("review.runs_marked", env=env, what=what, folder=f"{task}/{reviewcheck.RUNS_DIR}/{env}/", req=f"{task}/{tasks.REQ_FILE}")


def start(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    early = ""
    with task_ops.locked(root, task) as data:  # what refuses before a round: no check is used; a run that is not back is handed to the person
        task_ops.require_open(data)
        review = state_of(data)
        if review["n"] == 0:
            raise CommandError(say("review.off"))
        if not has_something(root, task, data):
            raise CommandError(say("review.nothing", task=task))
        early = not_ready(root, task, data)
        if early and not data.get("handoff"):
            early = mark_run(root, task, data) or early
    if early:
        raise CommandError(early)
    with task_ops.locked(root, task) as data:
        task_ops.require_open(data)
        review = state_of(data)
        early = not_ready(root, task, data)
        if early:
            raise CommandError(early)
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
        done = done_now(data)
        number = waiting["number"] if waiting else len(review["rounds"]) + 1
        snapshot = tasksnap.take(root, task, f"review-{number:03d}")
        entry = waiting or {"number": number, "task_round": data["round"]}
        entry.update(digest=snapshot["digest"], started_at=utc_now(), snapshot=snapshot["snapshot"], ordinal=len(done) + 1, verdict="")
        if waiting is None:
            review["rounds"].append(entry)
        previous = done[-1] if done and done[-1]["verdict"] != "PASS" else None
        given_back = [item for item in rounds_now(data) if item.get("refunded") and item.get("number") != number]
        if given_back and (not done or given_back[-1]["number"] > done[-1]["number"]):
            previous = given_back[-1]
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
        if verdict == "FAIL":
            try:
                found = reviewcheck.check(root, task, answer)
            except Exception:  # noqa: BLE001 - the check of the form must never lose the reviewer's answer
                found = {"dropped": [], "invalid": False}
            entry["dropped"] = found["dropped"]
            if found["invalid"]:
                given = len([item for item in rounds_now(data) if item.get("refunded")])
                entry["invalid"] = True
                entry["refunded"] = given < settings(root)["free_invalid"]
        folder = root / round_dir(task, entry["number"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / VERDICT_FILE).write_text(answer.rstrip() + "\n", encoding="utf-8")
        task_ops.note(data, "review", f"round-{entry['number']:03d} {verdict}" + (" invalid" if entry.get("invalid") else ""))
        digest = tasksnap.results_digest(root, task)
        info = {"verdict": verdict, "invalid": bool(entry.get("invalid")), "refunded": bool(entry.get("refunded")), "dropped": len(entry.get("dropped") or []), "round": entry["number"], "n": state_of(data)["n"], "passes": passes(data, digest), "checks_used": used(data), "checks_limit": limit(root, data)}
    return info


def status(root: Path, raw_task: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = task_ops.read(root, task)
    info = summary(root, task, data, settled=True)
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
    handed = data.get("handoff")
    if isinstance(handed, dict) and handed.get("what"):
        return say("review.handoff_open", what=handed.get("what", ""), env=handed.get("env", ""), task=task)  # the person's result first, whatever the last verdict said
    if info["checks_used"] >= info["checks_limit"]:
        return say("review.limit", used=info["checks_used"], limit=info["checks_limit"], task=task)
    left = info["n"] - info["passes"]
    if info["last_verdict"] and info["last_verdict"] != "PASS":
        return say("review.next.fix", left=left, verdict=f"{round_dir(task, done_now(data)[-1]['number'])}/{VERDICT_FILE}")
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
    found = [item for item in done_now(data) if item["verdict"] != "PASS" and (not number or int(item.get("number") or 0) == number)]
    return found[-1] if found else None


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
