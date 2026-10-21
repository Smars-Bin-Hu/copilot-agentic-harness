"""The stage ribbon of a task (M32): the steps its kind has, which are done, which is the one now, and the reviewer's checks.

Worked out from the files and the state each time, nothing is kept. So a task that starts over (the requirement changed and
the plan is asked for again, a new round after a write-back) falls back to the right step by itself.

  qa                    no ribbon
  rca, design, other    doing, done (done = the task is closed)
  dev, kb               requirement, plan, developing, write-back, done
                        developing: from the approved plan to the approved write-back; done: the write-back is made
  test                  guide, one step per environment of TEST-GUIDE.md (DEV, IST, UAT when it names none), done
                        an environment is done when its results file holds `Verdict for <env>: PASS`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import tasks

SIMPLE = ("rca", "design", "other")
WRITES_BACK = ("dev", "kb")
DEFAULT_ENVS = ("DEV", "IST", "UAT")
GUIDE = "TEST-GUIDE.md"
ENV_HEADING = re.compile(r"^##\s+([A-Za-z][A-Za-z0-9_-]{0,11})\s*$", re.MULTILINE)  # `## DEV`; the template's `## <DEV>` is not one
VERDICT = re.compile(r"Verdict for[^:\n]*:\s*\**\s*(PASS|FAIL|NEEDS MORE)", re.IGNORECASE)
WRITTEN = ("open", "confirmed", "changed")  # of tasks.req_state: REQ.md has more than the template


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
    finished = [task_ops.req_state(root, task) in WRITTEN, tasks.plan_approved(root, task, data), approved, done, done]
    flags = {3: "partial"} if promote.get("state") == "partial" else {}
    return steps_of([{"id": name} for name in ("requirement", "plan", "developing", "writeback", "done")], finished, flags)


def test_results(root: Path, task: str) -> tuple:
    """What a test task holds: the text of TEST-GUIDE.md, its environments (the `## DEV` headings, else DEV, IST and UAT) and, for each environment
    that has a results file with a verdict, `{ENV: (verdict, path)}`."""
    folder = tasks.task_dir(root, task)
    guide = read(folder / GUIDE)
    envs = list(dict.fromkeys(ENV_HEADING.findall(guide))) or list(DEFAULT_ENVS)
    found: Dict[str, tuple] = {}
    for path in sorted((folder / "TEST").glob("results-*.md")) if (folder / "TEST").is_dir() else []:
        verdicts = VERDICT.findall(read(path))
        if verdicts:
            found[path.stem[len("results-"):].upper()] = (verdicts[-1].upper(), path)
    return guide, envs, found


def tests(root: Path, task: str, data: Dict[str, Any]) -> Dict[str, Any]:
    guide, envs, results = test_results(root, task)
    verdicts = {env: pair[0] for env, pair in results.items()}
    finished = [bool(guide)] + [verdicts.get(env.upper()) == "PASS" for env in envs]
    finished.append(bool(guide) and all(finished[1:]))
    flags = {index + 1: "failed" for index, env in enumerate(envs) if verdicts.get(env.upper()) == "FAIL"}
    out = steps_of([{"id": "guide"}] + [{"id": "env", "label": env} for env in envs] + [{"id": "done"}], finished, flags)
    out["handoff"] = str((data.get("handoff") or {}).get("env") or "")
    return out


def reviewer(root: Path, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The checks the person asked for (`[review]=n`), one mark each for the version of the work as it is now."""
    from . import taskreview

    review = taskreview.state_of(data)
    if not review["n"] and not review["rounds"]:
        return None
    info = taskreview.summary(root, task, data)
    n = info["n"]
    states = ["pass"] * info["passes"]
    total = max(n, len(states))
    if info["pending_round"] and len(states) < total:
        states.append("run")
    elif info["last_verdict"] == "FAIL" and len(states) < total and not info["waived"]:
        states.append("fail")
    states += ["todo"] * (total - len(states))
    return {"n": n, "states": states, "waived": info["waived"], "stamp": n > 0 and info["passes"] >= n}


def of(root: Path, task: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The ribbon of a task, or None for a kind that has none (a question), a task not started, or one that cannot be read."""
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
        return found
    except Exception:  # noqa: BLE001 - a ribbon is a picture: a task that cannot be read has none
        return None
