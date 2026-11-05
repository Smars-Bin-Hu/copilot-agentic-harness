"""The stage ribbon of a task (M32): the steps its kind has, which are done, which is the one now, and the reviewer's checks.

Worked out from the files and the state each time, nothing is kept. So a task that starts over (the requirement changed and
the plan is asked for again, a new round after a write-back) falls back to the right step by itself.

  qa                    no ribbon
  rca, design, other    doing, done (done = the task is closed)
  dev, kb               requirement, plan, developing, write-back, done
                        developing: from the approved plan to the approved write-back; done: the write-back is made
                        DEV/ holds only DEV/_manual/ (1.6.110): requirement, plan, developing, run by hand, done
                        developing ends when the run is handed over; run by hand, when its result is recorded; done, when the task is closed
  test                  guide, one step per environment of TEST-GUIDE.md (DEV, IST, UAT when it names none), done
                        an environment is done when its results file holds `Verdict for <env>: PASS`
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import tasks

SIMPLE = ("rca", "design", "other")
WRITES_BACK = ("dev", "kb")
DEFAULT_ENVS = ("DEV", "IST", "UAT")
GUIDE = "TEST-GUIDE.md"
ENV_HEADING = re.compile(r"^##\s+([A-Za-z][A-Za-z0-9_-]{0,11})\s*$", re.MULTILINE)  # `## DEV`; the template's `## <DEV>` is not one
RUNNER_LINE = re.compile(r"^\s*\**Runner\**\s*:\s*\**\s*(agent|person)\b", re.IGNORECASE | re.MULTILINE)  # `Runner: agent` in an environment's part of the guide: the agent proposes to run it itself (1.7.2)
VERDICT = re.compile(r"Verdict for[^:\n]*:\s*\**\s*(PASS|FAIL|NEEDS MORE)", re.IGNORECASE)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def steps_of(names: List[Dict[str, str]], finished: List[bool], flags: Dict[int, str]) -> Dict[str, Any]:
    """Every step before the first one that is not finished is done; that one is now; the rest are to come."""
    at = next((index for index, ok in enumerate(finished) if not ok), len(finished) - 1)
    out = []
    for index, name in enumerate(names):
        state = "done" if finished[index] and index <= at else "now" if index == at else "todo"
        out.append({**name, "state": state, "flag": flags.get(index, "") if state == "now" else ""})
    return {"steps": out, "at": at}


def write_back(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    from . import task as task_ops

    promote = data.get("promote") or {}
    done = promote.get("state") == "done"
    approved = done or "approved_plan_sha256" in promote
    planned = tasks.plan_approved(root, task, data)
    if not approved and promote.get("state", "none") in ("none", "dry_run") and not data.get("deletes") and tasks.by_hand_only(root, task):
        return by_hand(root, task, data, planned)
    finished = [task_ops.req_state(root, task) == "confirmed" or planned or approved, planned, approved, done, done]
    flags = {3: "partial"} if promote.get("state") == "partial" else {}
    return steps_of([{"id": name} for name in ("requirement", "plan", "developing", "writeback", "done")], finished, flags)


def by_hand(root: Path, task: str, data: Dict[str, Any], planned: bool) -> Dict[str, Any]:
    """The ribbon of a task whose result the person runs by hand: a run recorded after the plan was approved ends that step."""
    from . import task as task_ops

    events = [event for event in data.get("events") or [] if isinstance(event, dict)]
    last_plan = max((index for index, event in enumerate(events) if event.get("what") == "approve-plan"), default=-1)
    later = [str(event.get("what", "")) for event in events[last_plan + 1:]] if last_plan >= 0 else []
    ran = "run-record" in later
    handed = ran or bool(data.get("handoff")) or "handoff" in later
    closed = data.get("status") == "closed"
    finished = [task_ops.req_state(root, task) == "confirmed" or planned or ran, planned, handed or closed, ran or closed, closed]
    return steps_of([{"id": name} for name in ("requirement", "plan", "developing", "byhand", "done")], finished, {})


def verdicts_in(text: str) -> List[str]:
    """Every `Verdict for <environment>: X` line of a results file, in order, outside code blocks: what the user pasted (it is in a code block) cannot say it."""
    kept: List[str] = []
    fence = ""
    for line in text.splitlines():
        stripped = line.strip()
        if fence:
            if stripped.startswith(fence) and not stripped.strip("`"):
                fence = ""
            continue
        opening = re.match(r"^(`{3,})", stripped)
        if opening:
            fence = opening.group(1)
            continue
        kept.append(line)
    return [word.upper() for word in VERDICT.findall("\n".join(kept))]


def env_of(stem: str, envs: List[str]) -> str:
    """The environment a results file belongs to: `results-IST.md` is IST's; `results-IST-run2.md` is IST's too, unless the guide has an environment `IST-RUN2`."""
    name = stem[len("results-"):].upper()
    exact = [env for env in envs if env.upper() == name]
    if exact:
        return exact[0].upper()
    near = [env for env in envs if name.startswith(env.upper() + "-") or name.startswith(env.upper() + "_")]
    return max(near, key=len).upper() if near else ""


def test_results(root: Path, task: str) -> tuple:
    """What a test task holds: the text of TEST-GUIDE.md, its environments (the `## DEV` headings, else DEV, IST and UAT) and, for each environment
    that has a results file with a verdict, `{ENV: (verdict, path)}`. The verdict of a file is the last `Verdict for ...` line in it (a new run goes at
    the end); of several files of one environment, the one written last counts."""
    folder = tasks.task_dir(root, task)
    guide = read(folder / GUIDE)
    envs = list(dict.fromkeys(ENV_HEADING.findall(guide))) or list(DEFAULT_ENVS)
    found: Dict[str, tuple] = {}
    newest: Dict[str, float] = {}
    for path in sorted((folder / "TEST").glob("results-*.md")) if (folder / "TEST").is_dir() else []:
        verdicts = verdicts_in(read(path))
        env = env_of(path.stem, envs)
        if not verdicts or not env:
            continue
        stamp = path.stat().st_mtime
        if env not in found or stamp >= newest[env]:
            found[env], newest[env] = (verdicts[-1], path), stamp
    return guide, envs, found


def guide_parts(guide: str, envs: List[str]) -> Dict[str, str]:
    """Each environment's part of the guide, `{ENV: text}`: from its `## ENV` heading to the next one. An environment with no heading has no part."""
    found: Dict[str, str] = {}
    names = {env.upper() for env in envs}
    at = None
    for line in guide.splitlines():
        heading = ENV_HEADING.match(line)
        if heading and heading.group(1).upper() in names:
            at = heading.group(1).upper()
            found[at] = ""
        elif at:
            found[at] += line + "\n"
    return found


def proposed_runners(guide: str, envs: List[str]) -> Dict[str, str]:
    """The runner each environment's part of the guide proposes (`Runner: agent` or `Runner: person`), `{ENV: runner}`; person when the part says nothing."""
    out: Dict[str, str] = {}
    for env, part in guide_parts(guide, envs).items():
        found = RUNNER_LINE.search(part)
        out[env] = found.group(1).lower() if found else "person"
    return out


def env_files(root: Path, task: str, envs: List[str]) -> Dict[str, List[Path]]:
    """Every results file of each environment, `{ENV: [paths]}` (a file with no verdict line is listed too)."""
    folder = tasks.task_dir(root, task) / "TEST"
    out: Dict[str, List[Path]] = {}
    for path in sorted(folder.glob("results-*.md")) if folder.is_dir() else []:
        env = env_of(path.stem, envs)
        if env:
            out.setdefault(env, []).append(path)
    return out


def tests(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    guide, envs, results = test_results(root, task)
    verdicts = {env: pair[0] for env, pair in results.items()}
    finished = [bool(guide)] + [verdicts.get(env.upper()) == "PASS" for env in envs]
    finished.append(bool(guide) and all(finished[1:]))
    flags = {index + 1: "failed" for index, env in enumerate(envs) if verdicts.get(env.upper()) == "FAIL"}
    out = steps_of([{"id": "guide"}] + [{"id": "env", "label": env} for env in envs] + [{"id": "done"}], finished, flags)
    out["handoff"] = str((data.get("handoff") or {}).get("env") or "")
    return out


def reviewer(root: Path, task: str, data: Dict[str, Any], number: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The checks the person asked for (`[review]=n`), one mark each for the version of the work as it is now.
    `number`: an earlier round instead, as it ended: its own checks, and the n of that time (from the history)."""
    from . import taskreview

    review = taskreview.state_of(data)
    if number is not None:
        wanted = taskreview.n_of_round(data, number)
        data = dict(data, round=number, status="closed")  # settled: the checks as they stood, not compared with the files of today
        if not wanted and not taskreview.done_now(data):
            return None
    elif not review["n"] and not review["rounds"]:
        return None
    info = taskreview.summary(root, task, data, settled=True)
    n = info["n"] if number is None else wanted
    states = ["pass"] * info["passes"]
    total = max(n, len(states))
    if info["pending_round"] and len(states) < total:
        states.append("run")
    elif info["last_verdict"] == "FAIL" and len(states) < total and not info["waived"]:
        states.append("fail")
    states += ["todo"] * (total - len(states))
    return {"n": n, "states": states, "waived": info["waived"], "stamp": n > 0 and info["passes"] >= n}


# The event that ends each step, by kind (the first of the names that the current round has): the time of a step is from the end of the one before it to its own end.
ENDS = {
    "requirement": ("confirm-req", "approve-plan"), "plan": ("approve-plan",), "developing": ("approve-promote", "promote", "handoff"),
    "writeback": ("promote",), "byhand": ("run-record",), "doing": ("close",),
}


def with_timing(found: Dict[str, Any], data: Dict[str, Any]) -> None:
    """Add to each step what the history knows of its time: `s` (seconds, a step that is done and has both ends) or `since` (a step that is now, from when it began). Nothing is guessed:
    a step with an end missing has neither. The test kind has no such events. Time put aside is not part of a step: `since` moves on by it, and a step of a task put aside has `s`, which stands still."""
    from core import copilot_events

    from . import taskinsight  # it needs this module

    steps = found.get("steps") or []
    round_now = int(data.get("round") or 1)
    events = [event for event in data.get("events") or [] if isinstance(event, dict) and int(event.get("round") or 1) == round_now]
    start = None
    if round_now == 1:
        start = copilot_events.seconds(data.get("created_at"))
    else:
        opened = [copilot_events.seconds(event.get("at")) for event in events if event.get("what") == "new-round"]
        start = opened[0] if opened and opened[0] is not None else None
    begin = start
    marks = [(copilot_events.seconds(event.get("at")), str(event.get("what", ""))) for event in data.get("events") or [] if isinstance(event, dict)]
    aside = taskinsight.pauses(sorted(item for item in marks if item[0] is not None))
    now = time.time()
    for step in steps:
        names = ENDS.get(step.get("id", ""), ())
        end = None
        for name in names:
            marks = [copilot_events.seconds(event.get("at")) for event in events if event.get("what") == name]
            marks = [mark for mark in marks if mark is not None]
            if marks:
                end = marks[0] if name != "promote" else marks[-1]
                break
        if step.get("state") == "done" and begin is not None and end is not None and end >= begin:
            step["s"] = round(end - begin - taskinsight.aside(aside, begin, end), 1)
        elif step.get("state") == "now" and begin is not None:
            spent = taskinsight.aside(aside, begin, now)
            if aside and aside[-1][1] == float("inf"):
                step["s"] = round(now - begin - spent, 1)
            else:
                from datetime import datetime, timezone
                step["since"] = datetime.fromtimestamp(begin + spent, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        begin = end if end is not None else None


def of(root: Path, task: str, data: Optional[Dict[str, Any]] = None, timing: bool = False) -> Optional[Dict[str, Any]]:
    """The ribbon of a task, or None for a kind that has none (a question), a task not started, or one that cannot be read. `timing`: the task page also wants the time of each step."""
    try:
        data = data if data is not None else tasks.read(root, task)
        kind = (data or {}).get("kind", "")
        if not data or kind not in SIMPLE + WRITES_BACK + ("test",):
            return None
        if kind in SIMPLE:
            closed = data.get("status") == "closed"
            found = steps_of([{"id": "doing"}, {"id": "done"}], [closed, closed], {})
        elif kind == "test":
            found = tests(root, task, data)
        else:
            found = write_back(root, task, data)
        found.update(kind=kind, round=int(data.get("round") or 1), review=reviewer(root, task, data))
        if timing and kind != "test":
            with_timing(found, data)
        return found
    except Exception:  # noqa: BLE001 - a ribbon is a picture: a task that cannot be read has none
        return None
