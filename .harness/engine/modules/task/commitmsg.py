"""The commit message of a write-back (1.5.29): the agent writes it, the page shows it with the contributor line, the person copies it.

A write-back puts the files on a branch of a code repository and does not commit (the person reviews and commits). So that the person need not
write the message, the agent writes `COMMIT-MESSAGE.md` in the task folder: a subject line, a blank line, the body. The page adds the trailer
`Co-authored-by: GitHub Copilot Coding Agents` itself, so the agent cannot forget it or write it wrong. The name is `commit.coauthor` of `task.json`
(`.harness/policies/task.override.json` changes it; a name alone is enough, `Name <address>` also works, and an empty string leaves the line out).
A task that wrote to more than one repository may have one section per repository: `## <repository name>`. What comes before the first section
(the subject line, a shared body) is the start of every repository's message (B63: a subject on top and the body in `## sim_repo` lost its subject).

The page gives the person the commands to commit, for macOS/Linux and for Windows PowerShell (M37-10): go to the repository, switch to the
branch of the write-back, `git add -A` (the write-back starts on a clean repository, so only its files are changed) and commit with the message
read from standard input, quoted so that nothing in it (a backtick, a `$`) is run by the shell.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config, tasks

from .policy import POLICY_NAME

FILE = "COMMIT-MESSAGE.md"
DEFAULT_COAUTHOR = "GitHub Copilot Coding Agents"
SUBJECT_MAX = 72
TRAILER = re.compile(r"^[A-Za-z][A-Za-z0-9-]*:\s+\S")


def coauthor(root: Path) -> str:
    try:
        value = (config.policy_or_empty(root, POLICY_NAME).get("commit") or {}).get("coauthor")
    except Exception:  # noqa: BLE001 - a broken policy must not take the page down
        value = None
    return value.strip() if isinstance(value, str) else DEFAULT_COAUTHOR  # an empty string turns the line off


def compose(raw: str, author: str) -> str:
    """The message as it is committed: the agent's text, then the contributor trailer. One blank line before the trailers; a trailer block the agent
    wrote is kept and the contributor line goes into it (never twice)."""
    if not author:
        return raw.strip() + "\n"
    line = f"Co-authored-by: {author}"
    lines = [item.rstrip() for item in raw.strip().splitlines()]
    lines = [item for item in lines if item.strip().lower() != line.lower()]
    while lines and not lines[-1].strip():
        lines.pop()
    last = len(lines)
    while last > 0 and lines[last - 1].strip():
        last -= 1
    block = lines[last:]
    if len(lines) > 1 and last > 0 and block and all(TRAILER.match(item) for item in block):
        return "\n".join(lines + [line]) + "\n"
    return "\n".join(lines + ([""] if lines else []) + [line]) + "\n"


def warnings(raw: str) -> List[str]:
    """Codes: `empty`, `subject_long` (more than 72 characters), `no_blank` (no blank line after the subject)."""
    lines = raw.strip().splitlines()
    if not lines or not lines[0].strip():
        return ["empty"]
    found = []
    if len(lines[0]) > SUBJECT_MAX:
        found.append("subject_long")
    if len(lines) > 1 and lines[1].strip():
        found.append("no_blank")
    return found


def sections(raw: str, names: List[str]) -> Dict[str, str]:
    """`{repository: text}` when the file has a `## <repository>` section for any of `names`; else empty (one message for every repository).
    The lines before the first `## ` heading start each section's text."""
    found: Dict[str, List[str]] = {}
    head: List[str] = []
    current: Optional[str] = None
    seen = False
    for line in raw.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:  # any `## ` heading ends the section before it; one that names a repository starts the next
            seen = True
            current = match.group(1) if match.group(1) in names else None
            if current:
                found[current] = []
        elif current is not None:
            found[current].append(line)
        elif not seen:
            head.append(line)
    start = "\n".join(head).strip()
    out = {}
    for name, body in found.items():
        text = "\n".join(body).strip()
        out[name] = f"{start}\n\n{text}" if start and text else start or text
    return out


def posix_commands(path: str, branch: str, text: str) -> str:
    quote = lambda value: "'" + value.replace("'", "'\\''") + "'"  # noqa: E731 - inside single quotes nothing is run
    mark = "EOF"
    while any(line.strip() == mark for line in text.splitlines()):
        mark += "_MSG"
    return "\n".join([f"cd {quote(path)}", f"git switch {quote(branch)}", f"git add -A && git commit -F - <<'{mark}'", text.rstrip("\n"), mark]) + "\n"


def powershell_commands(path: str, branch: str, text: str) -> str:
    """A single-quoted here-string runs nothing that is in it. Windows PowerShell 5.1 pipes to a program in ASCII unless told: UTF-8, so non-English text stays."""
    quote = lambda value: "'" + value.replace("'", "''") + "'"  # noqa: E731
    body = [(" " + line) if line.startswith("'@") else line for line in text.rstrip("\n").splitlines()]  # `'@` at the start of a line would end the string
    return "\n".join([
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)", f"Set-Location -LiteralPath {quote(path)}", f"git switch {quote(branch)}", "git add -A",
        "@'", *body, "'@ | git commit -F -",
    ]) + "\n"


def to_commit(data: Dict[str, Any]) -> List[str]:
    """The repositories of the write-back the person still has to commit: the ones nothing committed (a knowledge base is committed by the write-back itself)."""
    repos = (data.get("promote") or {}).get("repos") or {}
    return [name for name, item in repos.items() if isinstance(item, dict) and not item.get("commit")]


def view(root: Path, task: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The commit message the Changes tab shows at its top; None when the write-back is not done or has nothing for the person to commit."""
    if (data.get("promote") or {}).get("state") != "done":
        return None
    names = to_commit(data)
    if not names:
        return None
    path = tasks.task_dir(root, task) / FILE
    raw = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else ""
    author = coauthor(root)
    parts = sections(raw, names)
    promote = data.get("promote") or {}
    branch = str(promote.get("branch") or data.get("branch") or "")
    messages = []
    for name in names:
        text = parts.get(name, "") if parts else raw.strip()
        if not text:
            continue
        message = compose(text, author)
        path = str((promote.get("repos") or {}).get(name, {}).get("path") or "")
        messages.append({"repo": name, "text": message, "warnings": warnings(text), "path": path, "branch": branch,
                         "commands": {"posix": posix_commands(path, branch, message), "powershell": powershell_commands(path, branch, message)} if path and branch else None})
    return {"written": bool(raw.strip()), "repos": names, "messages": messages, "coauthor": author, "file": FILE}
