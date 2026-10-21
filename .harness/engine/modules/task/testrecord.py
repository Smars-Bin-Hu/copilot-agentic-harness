"""`harness task test record`: the results of a test environment are written by a script, not by hand (1.5.28).

The agent hands over what the user gave back (a file), and one row for each criterion: `criterion::evidence::PASS|FAIL|NEEDS MORE`. The script
works out the verdict of the environment from the rows (any FAIL: FAIL; else any NEEDS MORE: NEEDS MORE; else PASS, and a PASS row needs its
evidence), adds a `## Run N` at the END of `TEST/results-<environment>.md` (the board reads the last `Verdict for` line), puts the user's words in
as they were given, updates `TEST/summary.md` and `LOG.md`, takes the handoff mark of that environment away, and syncs the defects.
What it does not write is judgement in words: `TASK.md`, `TODO.md`, the defects themselves, the reason in the log.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core import messages, tasks
from core.paths import cli_command, utc_now

from . import task as task_ops, taskstages, testdefects
from .common import CommandError

VERDICTS = ("PASS", "FAIL", "NEEDS MORE")
MAX_GIVEN_BYTES = 400_000
LOG_MARK = "<!-- New entries go here -->"
SUMMARY = "summary.md"
SUMMARY_HEAD = ["| Environment | Verdict | Date | Results |", "| --- | --- | --- | --- |"]


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def cell(text: str) -> str:
    """One line, with the bars that would break a table escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


def parse_row(raw: str) -> Dict[str, str]:
    parts = [part.strip() for part in str(raw).split("::")]
    if len(parts) != 3 or not parts[0]:
        raise CommandError(say("task.test.row", row=raw))
    verdict = " ".join(parts[2].upper().split())
    if verdict not in VERDICTS:
        raise CommandError(say("task.test.row_verdict", row=raw, allowed=", ".join(VERDICTS)))
    if verdict == "PASS" and not parts[1]:
        raise CommandError(say("task.test.evidence", criterion=parts[0]))
    return {"criterion": parts[0], "evidence": parts[1], "verdict": verdict}


def verdict_of(rows: List[Dict[str, str]]) -> str:
    """Any FAIL is FAIL; else any NEEDS MORE is NEEDS MORE; else PASS. A criterion with no evidence cannot be PASS (parse_row)."""
    found = {row["verdict"] for row in rows}
    return "FAIL" if "FAIL" in found else "NEEDS MORE" if "NEEDS MORE" in found else "PASS"


def read_given(root: Path, raw: str) -> str:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        data = path.read_bytes()
    except OSError:
        raise CommandError(say("task.test.given_missing", path=raw)) from None
    if len(data) > MAX_GIVEN_BYTES:
        raise CommandError(say("task.test.given_big", path=raw, kb=MAX_GIVEN_BYTES // 1000))
    text = data.decode("utf-8-sig", errors="replace").strip("\n")
    if not text.strip():
        raise CommandError(say("task.test.given_empty", path=raw))
    return text


def fenced(text: str) -> List[str]:
    """The user's words as they were given: in a code block whose fence is longer than any run of backticks inside, so nothing in them is read as markdown."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence + "text", *text.splitlines(), fence]


def last_run(text: str) -> int:
    """The number of the last run in a results file: the highest `## Run N`; a file written by hand that has a verdict and no such heading is run 1."""
    numbers = [int(found) for found in re.findall(r"^## Run (\d+)\b", text, re.MULTILINE)]
    return max(numbers) if numbers else 1 if taskstages.verdicts_in(text) else 0


def summary_update(folder: Path, env: str, verdict: str, date: str, name: str) -> str:
    path = folder / "TEST" / SUMMARY
    row = f"| {env} | {verdict} | {date} | [{name}](./{name}) |"
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if path.is_file() else []
    index = next((i for i, line in enumerate(lines) if re.match(rf"^\|\s*{re.escape(env)}\s*\|", line, re.IGNORECASE)), None)
    if index is not None:
        lines[index] = row
    else:
        head = next((i for i, line in enumerate(lines) if re.match(r"^\|\s*Environment\s*\|", line, re.IGNORECASE)), None)
        if head is None:
            lines += ([""] if lines else ["# Summary", ""]) + SUMMARY_HEAD + [row]
        else:
            end = head + 1
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            lines.insert(end, row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"TEST/{SUMMARY}"


def log_update(folder: Path, line: str) -> str:
    path = folder / "LOG.md"
    text = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else "# LOG\n\n" + LOG_MARK + "\n"
    if LOG_MARK in text:
        text = text.replace(LOG_MARK, LOG_MARK + "\n\n" + line, 1)
    else:
        text = text.rstrip("\n") + "\n\n" + line + "\n"
    path.write_text(text, encoding="utf-8")
    return "LOG.md"


def record(root: Path, raw_task: str, env: str, given_file: str, rows: List[str], run_by: str = "", follow_up: str = "") -> Dict[str, Any]:
    task = task_ops.resolve(root, raw_task)
    data = tasks.read(root, task)
    task_ops.require_open(data)
    if data.get("kind") != "test":
        raise CommandError(say("task.test.kind", name=task_ops.name_of(task)))
    guide, envs, found = taskstages.test_results(root, task)
    chosen = next((name for name in envs if name.upper() == " ".join(str(env).split()).upper()), "")
    if not chosen:
        raise CommandError(say("task.test.env", env=env, envs=", ".join(envs)))
    if not rows:
        raise CommandError(say("task.test.rows"))
    parsed = [parse_row(row) for row in rows]
    given = read_given(root, given_file)
    verdict = verdict_of(parsed)
    folder = tasks.task_dir(root, task)
    name = f"results-{chosen}.md"
    path = folder / "TEST" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else f"# Results: {chosen}\n"
    number = last_run(before) + 1
    now = utc_now()
    section = [
        "", f"## Run {number}", "",
        f"Run by: {cell(run_by) or 'the user'}. Recorded {now[:16].replace('T', ' ')} UTC.", "",
        "### As the user gave them", "", *fenced(given), "",
        "### Judgement", "", "| Criterion | Evidence | Verdict |", "| --- | --- | --- |",
        *[f"| {cell(row['criterion'])} | {cell(row['evidence']) or '-'} | {row['verdict']} |" for row in parsed], "",
    ]
    if follow_up.strip():
        section += ["### Follow-up", "", f"- {cell(follow_up)}", ""]
    section.append(f"**Verdict for {chosen}: {verdict}**")  # the last line of the run: the board reads the last one of the file
    path.write_text(before.rstrip("\n") + "\n" + "\n".join(section) + "\n", encoding="utf-8")
    warnings: List[str] = []
    for earlier in envs[:envs.index(chosen)]:
        if found.get(earlier.upper(), ("", None))[0] != "PASS":
            warnings.append(say("task.test.order", env=chosen, earlier=earlier))
    count = {word: sum(1 for row in parsed if row["verdict"] == word) for word in VERDICTS}
    summary = summary_update(folder, chosen, verdict, now[:10], name)
    log = log_update(folder, f"- {now[:10]}: test {chosen}, run {number}: {verdict} ({count['PASS']} of {len(parsed)} criteria pass). Results: TEST/{name}.")
    cleared = False
    with task_ops.locked(root, task) as fresh:
        handed = fresh.get("handoff")
        if isinstance(handed, dict) and str(handed.get("env", "")).upper() == chosen.upper():
            fresh.pop("handoff", None)
            task_ops.note(fresh, "handoff-clear", f"{handed.get('what', '')} {handed.get('env', '')}".strip())
            cleared = True
        elif isinstance(handed, dict):
            warnings.append(say("task.test.other_handoff", handed=handed.get("env", ""), env=chosen))
        task_ops.note(fresh, "test-record", f"{chosen} run {number} {verdict}")
    defects = testdefects.sync(root, task)
    warnings += defects["warnings"]
    _guide, _envs, after = taskstages.test_results(root, task)
    later = next((item for item in envs if after.get(item.upper(), ("", None))[0] != "PASS"), "")
    if verdict == "PASS":
        step = say("task.test.next.pass_next", env=later) if later else say("task.test.next.pass_done")
    elif verdict == "FAIL":
        step = say("task.test.next.fail", env=chosen)
    else:
        step = say("task.test.next.more", env=chosen)
    return {
        "task": task, "env": chosen, "run": number, "verdict": verdict, "criteria": {"pass": count["PASS"], "fail": count["FAIL"], "needs_more": count["NEEDS MORE"]},
        "file": f"TEST/{name}", "summary": summary, "log": log, "handoff_cleared": cleared, "defects": defects if defects["file"] else None,
        "warnings": warnings, "next": step,
    }
