"""`harness task run record` (1.5.42): the result of a run the person did before the write-back, written by a script.

A development task that needs a job run in an environment hands it over (`task handoff run`); the person runs it and brings back the output, the commands and
screenshots. This writes them into `RUNS/<ENV>/results.md` the way `task test record` writes a test run: a `## Run N` at the end with what was run, what the person
gave (whole, in a code block) and the screenshots (copied into `RUNS/<ENV>/evidence/`), and takes the handoff mark of that environment away.
A check of the task judges its `[R…]` items by what is in `RUNS/<ENV>/`. What it does not write is judgement: the agent compares the result with each `[R…]`
item and says so in `LOG.md` and to the person.
1.7.3: the agent records a run it did itself the same way, with `--run-by agent` (a read on a listed outside system needs no one's leave; a write ran only
because the gate let it), in any kind of task; the run gets the task's next evidence number (`evidence.py`), to cite as `[E<n>]`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core import messages, tasks
from core.paths import cli_command, local_stamp, utc_now

from . import evidence as evidence_ids, steps as step_parts, task as task_ops
from .common import CommandError
from .taskinbox import ENV_NAME
from .testrecord import AGENT, cell, fenced, last_run, leave_lines, leave_word, read_given, read_text_file, save_evidence

RESULTS = "results.md"
EVIDENCE = "evidence"


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def record(root: Path, raw_task: str, env: str, given_file: str = "", run_by: str = "", ran_file: str = "", evidence: Optional[List[str]] = None, follow_up: str = "", steps_file: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = tasks.read(root, task)
    task_ops.require_open(data)
    env = " ".join(str(env).split())
    if not ENV_NAME.match(env):
        raise CommandError(say("task.run.env"))
    env = env.upper()
    given = read_given(root, given_file) if given_file else ""
    steps = step_parts.parse(read_text_file(steps_file)) if steps_file else []
    if not given and not evidence and not steps:
        raise CommandError(say("task.run.empty"))
    ran = step_parts.commands(steps) if steps else read_text_file(ran_file) if ran_file else ""
    folder = tasks.task_dir(root, task)
    base = f"RUNS/{env}"
    existing = {path.name.upper(): path for path in (folder / "RUNS").iterdir() if path.is_dir()} if (folder / "RUNS").is_dir() else {}
    if env in existing:
        base = f"RUNS/{existing[env].name}"  # the folder is found in any case: the agent or the person may have made it in lower case
    path = folder / base / RESULTS
    before = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else f"# Run results: {env}\n"
    number = last_run(before) + 1
    by_agent = run_by.strip().lower() == AGENT
    with task_ops.locked(root, task) as fresh:
        evidence_id = evidence_ids.allocate(fresh)
    pictures = save_evidence(folder, env, number, list(evidence or []), base, EVIDENCE)
    who = say("task.run.by_agent") if by_agent else cell(run_by) or "the user"
    section = [
        "", f"## Run {number} ({evidence_id})", "", evidence_ids.marker(evidence_id, AGENT if by_agent else "person", utc_now(), env, leave_word(root, task, ran, by_agent)), "",
        f"Run by: {who}. Recorded {local_stamp()}.", *leave_lines(root, task, ran, by_agent), "",
        *(step_parts.lines(steps) + [""] if steps else []),  # one step per command: its title, what it shows, the command, the output (1.7.9)
        *(["### What was run", "", *fenced(ran), ""] if ran and not steps else []),
        *([("### As the agent saved them" if by_agent else "### As the user gave them"), "", *fenced(given), ""] if given else []),
        *(["### Screenshots", "", *[line for item in pictures for line in (f"![{cell(item['caption']).replace(']', ')')}]({item['relative']})", "", f"{cell(item['caption'])} (file `{item['name']}`, sha256 {item['sha'][:12]})", "")]] if pictures else []),
    ]
    if follow_up.strip():
        section += ["### Follow-up", "", f"- {cell(follow_up)}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(before.rstrip("\n") + "\n" + "\n".join(section).rstrip("\n") + "\n", encoding="utf-8")
    cleared = False
    with task_ops.locked(root, task) as fresh:
        handed = fresh.get("handoff")
        if isinstance(handed, dict) and str(handed.get("env", "")).upper() == env:
            fresh.pop("handoff", None)
            task_ops.note(fresh, "handoff-clear", f"{handed.get('what', '')} {handed.get('env', '')}".strip())
            cleared = True
        task_ops.note(fresh, "run-record", f"{env} run {number} {evidence_id}" + (" by the agent" if by_agent else ""))
    warnings = ([] if ran else [say("task.test.missing_ran")]) + ([] if pictures or by_agent else [say("task.test.missing_screenshot")])  # the agent's run has no screenshot: its output is the record
    return {"task": task, "env": env, "run": number, "evidence_id": evidence_id, "run_by": AGENT if by_agent else "person", "file": f"{base}/{RESULTS}", "evidence": [f"{base}/{item['relative']}" for item in pictures], "handoff_cleared": cleared,
            "warnings": warnings, "next": say("task.run.next", file=f"{base}/{RESULTS}", id=evidence_id)}
