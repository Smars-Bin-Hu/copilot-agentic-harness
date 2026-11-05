"""Evidence (1.7.3): every run saved in a task has one number, `E<n>`, whichever way it came: a run the person did (`task run record`), a run the
agent did itself (`--run-by agent`), or a test run (`task test record`). The number is given by the task (`evidence_n` in task.json) when the run is
recorded, written in the run's heading (`## Run 2 (E7)`) and in a marker line under it that the page reads; the files REQ.md, PLAN.md, RCA.md, LOG.md
and the others at the root of the task cite it as `[E7]`. The agent cites a number only for a run that is saved: a figure with no `[E…]` is a claim.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from core import tasks

from . import cmdview

KEY = "evidence_n"
HEADING = re.compile(r"^## Run (\d+)(?:\s*\((E\d+)\))?\s*$", re.MULTILINE)
MARKER = re.compile(r"^<!-- evidence (E\d+) by (agent|person) at (\S+) env (\S+) -->$", re.MULTILINE)
CITATION = re.compile(r"\[(E\d+)\]")
CITING = ("*.md", "TEST/*.md", "DEV/**/*.md")  # where a citation is looked for: the task's own documents, not the results files
OUTPUT_CHARS = 20_000  # what the window shows of an output; the file has it whole
_FENCE = re.compile(r"^(`{3,})text?\s*$")
_RAN = "### What was run"
_GIVEN = ("### As the agent saved them", "### As the user gave them")


def allocate(data: Dict[str, Any]) -> str:
    """The next number of this task. Called with the task locked, by the command that records the run."""
    number = int(data.get(KEY) or 0) + 1
    data[KEY] = number
    return f"E{number}"


def marker(evidence_id: str, by: str, at: str, env: str) -> str:
    return f"<!-- evidence {evidence_id} by {by} at {at} env {env} -->"


def section_parts(text: str) -> Dict[str, Any]:
    """The command and the output of one run's section, read from its fenced blocks: `{command, output, output_cut, run_by}`. A part that is not there is empty."""
    found: Dict[str, Any] = {"command": "", "output": "", "output_cut": False, "run_by": ""}
    lines = text.splitlines()
    index = 0
    want = ""
    while index < len(lines):
        line = lines[index]
        if line.startswith("Run by:") and not found["run_by"]:
            found["run_by"] = line[len("Run by:"):].split(". Recorded")[0].strip()
        if line.strip() == _RAN:
            want = "command"
        elif line.strip() in _GIVEN:
            want = "output"
        elif line.startswith("### "):
            want = ""
        fence = _FENCE.match(line)
        if fence and want:
            mark = fence.group(1)
            body: List[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != mark:
                body.append(lines[index])
                index += 1
            whole = "\n".join(body)
            if want == "command":
                found["command"] = whole.strip()
            else:
                found["output"], found["output_cut"] = whole[:OUTPUT_CHARS], len(whole) > OUTPUT_CHARS
            want = ""
        index += 1
    return found


def listing(root: Path, task: str) -> List[Dict[str, Any]]:
    """Every saved run of the task that has a number, newest last: `{id, env, by, at, kind, file, run, cited_in}`. A results file written before 1.7.3 has runs with no number: not listed."""
    folder = tasks.task_dir(root, task)
    files = sorted(folder.glob("RUNS/*/results.md")) + sorted(folder.glob("TEST/results-*.md"))
    found: List[Dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        marks = {item.group(1): item for item in MARKER.finditer(text)}
        heads = list(HEADING.finditer(text))
        for number, head in enumerate(heads):
            evidence_id = head.group(2)
            if not evidence_id:
                continue
            mark = marks.get(evidence_id)
            section = text[head.end():heads[number + 1].start() if number + 1 < len(heads) else len(text)]
            parts = section_parts(section)
            found.append({
                "id": evidence_id, "run": int(head.group(1)), "kind": "test" if path.parent.name == "TEST" else "run",
                "env": mark.group(4) if mark else path.parent.name if path.parent.name != "TEST" else path.stem.split("-", 1)[-1],
                "by": mark.group(2) if mark else "person", "at": mark.group(3) if mark else "",
                "file": path.relative_to(folder).as_posix(), "cited_in": [],
                "command": parts["command"], "layout": cmdview.layout(parts["command"], folder) if parts["command"] else None, "output": parts["output"], "output_cut": parts["output_cut"], "run_by": parts["run_by"],
            })
    if not found:
        return []
    cited: Dict[str, List[str]] = {item["id"]: [] for item in found}
    for pattern in CITING:
        for path in sorted(folder.glob(pattern)):
            if path.is_file() and path.name.lower() != "results.md" and not path.name.lower().startswith("results-"):
                try:
                    names = set(CITATION.findall(path.read_text(encoding="utf-8-sig", errors="replace")))
                except OSError:
                    continue
                for name in names & set(cited):
                    cited[name].append(path.relative_to(folder).as_posix())
    for item in found:
        item["cited_in"] = cited[item["id"]]
    return sorted(found, key=lambda item: int(item["id"][1:]))
