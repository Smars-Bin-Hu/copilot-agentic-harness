"""`harness task test record`: the results of a test environment are written by a script, not by hand (1.5.28).

The agent hands over what the user gave back (a file), and one row for each criterion: `criterion::evidence::PASS|FAIL|NEEDS MORE`. The script
works out the verdict of the environment from the rows (any FAIL: FAIL; else any NEEDS MORE: NEEDS MORE; else PASS, and a PASS row needs its
evidence), adds a `## Run N` at the END of `TEST/results-<environment>.md` (the board reads the last `Verdict for` line), puts the user's words in
as they were given, updates `TEST/summary.md` and `LOG.md`, takes the handoff mark of that environment away, and syncs the defects.
What it does not write is judgement in words: `TASK.md`, `TODO.md`, the defects themselves, the reason in the log.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, tasks
from core.paths import cli_command, utc_now

from . import mdtree, task as task_ops, taskstages, testdefects
from .common import CommandError

VERDICTS = ("PASS", "FAIL", "NEEDS MORE")
MAX_GIVEN_BYTES = 400_000
MAX_EVIDENCE = 10  # screenshots in one run
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
EVIDENCE_DIR = "evidence"
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


def read_text_file(raw: str) -> str:
    """The commands the person ran, from a file the agent wrote, as they were."""
    path = Path(raw).expanduser()
    path = path if path.is_absolute() else Path.cwd() / path
    try:
        return path.read_bytes().decode("utf-8-sig", errors="replace").strip("\n")[:MAX_GIVEN_BYTES]
    except OSError:
        raise CommandError(say("task.test.ran_missing", path=raw)) from None


def save_evidence(folder: Path, env: str, number: int, items: List[str], base: str = "TEST", sub: str = "") -> List[Dict[str, str]]:
    """Copy the pictures the person gave (`PATH` or `PATH::caption`) into `TEST/evidence/<ENV>/run<N>-<k>.<type>`, and say what each one is. The copy is the evidence:
    the place a chat keeps a pasted picture is not the task's, and it can be cleaned away. Nothing is copied unless every item is good.
    `base`: the folder of the results file in the task (`TEST`, or `RUNS/<ENV>` for the run of a development task); `relative` is from that folder. `sub`: the folder for the pictures in it (`evidence/<ENV>` when left out)."""
    if len(items) > MAX_EVIDENCE:
        raise CommandError(say("task.test.evidence_many", limit=MAX_EVIDENCE))
    found = []
    for index, raw in enumerate(items, 1):
        where, _, caption = str(raw).partition("::")
        source = Path(where.strip()).expanduser()
        source = source if source.is_absolute() else Path.cwd() / source
        suffix = source.suffix.lower()
        if suffix not in mdtree.IMAGE_TYPES:
            raise CommandError(say("task.test.evidence_type", path=where, types=", ".join(sorted(mdtree.IMAGE_TYPES))))
        try:
            size = source.stat().st_size
            if not source.is_file():
                raise OSError
        except OSError:
            raise CommandError(say("task.test.evidence_missing", path=where)) from None
        if size > MAX_EVIDENCE_BYTES:
            raise CommandError(say("task.test.evidence_big", path=where, mb=MAX_EVIDENCE_BYTES // (1024 * 1024)))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        relative = f"{sub or EVIDENCE_DIR + '/' + env.upper()}/run{number}-{index}{'.jpg' if suffix == '.jpeg' else suffix}"
        found.append({"source": str(source), "relative": relative, "caption": " ".join(caption.split()) or say("task.test.evidence_caption", n=index), "sha": digest, "name": source.name})
    for item in found:
        target = folder / base / item["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item["source"], target)
    return found


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


def record(root: Path, raw_task: str, env: str, given_file: str, rows: List[str], run_by: str = "", follow_up: str = "", ran_file: str = "", evidence: Optional[List[str]] = None) -> Dict[str, Any]:
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
    given = read_given(root, given_file) if given_file else ""
    if not given and not evidence:
        raise CommandError(say("task.test.given_none"))
    ran = read_text_file(ran_file) if ran_file else ""
    verdict = verdict_of(parsed)
    folder = tasks.task_dir(root, task)
    name = f"results-{chosen}.md"
    path = folder / "TEST" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else f"# Results: {chosen}\n"
    number = last_run(before) + 1
    now = utc_now()
    pictures = save_evidence(folder, chosen, number, list(evidence or []))
    section = [
        "", f"## Run {number}", "",
        f"Run by: {cell(run_by) or 'the user'}. Recorded {now[:16].replace('T', ' ')} UTC.", "",
        *(["### What was run", "", *fenced(ran), ""] if ran else []),
        *(["### As the user gave them", "", *fenced(given), ""] if given else []),
        *(["### Screenshots", "", *[line for item in pictures for line in (f"![{cell(item['caption']).replace(']', ')')}]({item['relative']})", "", f"{cell(item['caption'])} (file `{item['name']}`, sha256 {item['sha'][:12]})", "")]] if pictures else []),
        "### Judgement", "", "| Criterion | Evidence | Verdict |", "| --- | --- | --- |",
        *[f"| {cell(row['criterion'])} | {cell(row['evidence']) or '-'} | {row['verdict']} |" for row in parsed], "",
    ]
    if follow_up.strip():
        section += ["### Follow-up", "", f"- {cell(follow_up)}", ""]
    section.append(f"**Verdict for {chosen}: {verdict}**")  # the last line of the run: the board reads the last one of the file
    path.write_text(before.rstrip("\n") + "\n" + "\n".join(section) + "\n", encoding="utf-8")
    warnings: List[str] = ([] if ran else [say("task.test.missing_ran")]) + ([] if pictures else [say("task.test.missing_screenshot")])  # the run has three supports: the commands, the words, the pictures; a gap is said, not refused
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
        "file": f"TEST/{name}", "evidence": [f"TEST/{item['relative']}" for item in pictures], "summary": summary, "log": log, "handoff_cleared": cleared, "defects": defects if defects["file"] else None,
        "warnings": warnings, "next": step,
    }
