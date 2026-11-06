"""A run the agent did as steps (1.7.9): one step per command, each with its title, what it shows, the command and its output. The agent writes a steps file;
the record commands (`task test record`, `task run record`, `--steps-file`) keep that shape in the results file, so the page can lay each step out
(the command parsed, the output as tables) instead of one block of commands and one block of output that nobody can match up.

The steps file (Markdown):

    ## <title of the step>

    <one or two sentences: what it checks, what the output shows>

    ```command
    <the whole command, as it was run>
    ```

    ```output
    <what it printed, as it came>
    ```

In the results file each step is `#### Step <n> · <title>`, its words, a `command` block and an `output` block (fences long enough for anything inside).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from core import messages

from . import cmdview, outview
from .common import CommandError

HEAD = "### Steps"
_STEP = re.compile(r"^##\s+(.+?)\s*$")
_SAVED_STEP = re.compile(r"^####\s+Step\s+\d+\s*·\s*(.+?)\s*$")
_FENCE = re.compile(r"^(`{3,}|~{3,})\s*([\w-]*)\s*$")
MAX_STEPS = 60


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def _read(lines: List[str], title_of: "re.Pattern[str]") -> List[Dict[str, str]]:
    """The steps in `lines`: a line that matches `title_of` opens one; its fences named `command` and `output` (else the first and the second fence) are its parts; the rest is its words."""
    found: List[Dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        head = title_of.match(line)
        if head:
            found.append({"title": head.group(1).strip(), "note": [], "fences": []})
            index += 1
            continue
        fence = _FENCE.match(line.strip())
        if fence and found:
            mark, lang = fence.group(1), fence.group(2).lower()
            body: List[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != mark:
                body.append(lines[index])
                index += 1
            found[-1]["fences"].append((lang, "\n".join(body)))
            index += 1
            continue
        if found and line.strip():
            found[-1]["note"].append(line.strip())
        index += 1
    out: List[Dict[str, str]] = []
    for step in found:
        named = {lang: text for lang, text in step["fences"] if lang in ("command", "output")}
        plain = [text for lang, text in step["fences"] if lang not in ("command", "output")]
        command = named.get("command", plain[0] if plain else "")
        output = named.get("output", plain[1] if len(plain) > 1 else plain[0] if plain and "command" in named else "")
        out.append({"title": step["title"], "note": " ".join(step["note"]), "command": command.strip("\n"), "output": output.strip("\n")})
    return out


def parse(text: str) -> List[Dict[str, str]]:
    """The steps of a steps file the agent wrote. Refused when there is none, or a step has no command (a step is one command and what it printed)."""
    found = _read(text.splitlines(), _STEP)
    if not found:
        raise CommandError(say("task.steps.none"))
    if len(found) > MAX_STEPS:
        raise CommandError(say("task.steps.many", n=len(found), most=MAX_STEPS))
    empty = [step["title"] for step in found if not step["command"].strip()]
    if empty:
        raise CommandError(say("task.steps.no_command", titles=", ".join(empty)))
    return found


def saved(text: str) -> List[Dict[str, str]]:
    """The steps of one run's section of a results file, as `lines` wrote them."""
    return _read(text.splitlines(), _SAVED_STEP)


def _fence(lang: str, text: str) -> List[str]:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    mark = "`" * max(3, longest + 1)
    return [mark + lang, *text.splitlines(), mark]


def lines(found: List[Dict[str, str]]) -> List[str]:
    """The steps in the results file."""
    out = [HEAD, ""]
    for number, step in enumerate(found, 1):
        out += [f"#### Step {number} · {' '.join(step['title'].split())}", ""]
        if step["note"]:
            out += [step["note"], ""]
        out += [*_fence("command", step["command"]), ""]
        out += [*_fence("output", step["output"] or say("task.steps.no_output")), ""]
    return out


def commands(found: List[Dict[str, str]]) -> str:
    """Every command of the steps, one per line (a command over several lines is joined), for what let them through (core.calls)."""
    return "\n".join(" ".join(step["command"].split()) for step in found)


def laid_out(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A ```command block gets its layout (the program, each option), a ```output block the tables the reader found (1.7.9): the steps of a run the agent recorded."""
    for block in blocks:
        if block.get("t") == "code" and block.get("lang") == "command":
            block["layout"] = cmdview.layout(block.get("text", ""), None)
        elif block.get("t") == "code" and block.get("lang") == "output":
            block["view"] = outview.layout(block.get("text", ""))
        elif block.get("t") == "quote":
            laid_out(block.get("blocks") or [])
    return blocks
