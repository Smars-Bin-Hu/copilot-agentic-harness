"""The run of a script is judged (1.7.38, C13 FR 17b).

The agent may write a script into its task folder (that is what a task is for) and run it. The gate does not read what a script does when it writes it, and it did not read it when it ran it: a script that rewrites an
engine file or a policy was a way round every guardrail (`helper.py` writes `.harness/engine/modules/gate/pin.py`, then everything passes). A line that runs a script file (`python3 x.py`, `node x.js`, `bash x.sh`,
`pwsh -File x.ps1`, `./x.sh`, `source x.sh`) is read here: the script is refused when its text names a guardrail path and also writes (opens a file for writing, `write_text`, `shutil`, `os.remove`, a redirection, `rm`,
`Set-Content`...). The way is to tell the user what must change. This is best effort: a path built from pieces, a script that imports another, a program that writes by itself pass this check. `docs/12` says so; the guardrail
files themselves are checked against the list the person accepted (`integrity.py`) whatever is run. The harness's own engine and tests are not read (they are what runs).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core import guardrails, messages

from . import external
from .gitcmd import join_lines, split_segments

MAX_BYTES = 200 * 1024
EXTRA = (r"\.harness\b", r"\.github[\\/]+hooks", r"AGENTS\.md", r"Start Harness\.(?:command|cmd)")  # named whole, even when the policy lists fewer

WRITES = re.compile(
    r"""open\s*\([^)]*,\s*(?:mode\s*=\s*)?['"][^'"]*[wax+]"""  # python: open(path, "w")
    r"""|\.(?:write_text|write_bytes|unlink|rmdir|touch|chmod|rename|replace|mkdir|symlink_to|hardlink_to|truncate)\s*\("""
    r"""|\bshutil\.\w+|\bos\.(?:remove|unlink|rename|replace|rmdir|removedirs|makedirs|mkdir|chmod|chown|truncate|symlink|link|utime|system|popen)\b"""
    r"""|\bsubprocess\b|\bfs(?:\.promises)?\.(?:write|append|rm|unlink|rename|copy|mkdir|chmod|truncate|symlink|link)\w*"""  # node
    r"""|\b(?:writeFile|appendFile|writeFileSync|createWriteStream)\b"""
    r"""|\b(?:Set-Content|Add-Content|Out-File|Remove-Item|New-Item|Copy-Item|Move-Item|Rename-Item|Clear-Content)\b"""  # powershell
    r"""|(?<![<>=-])>{1,2}\s*[\"']?[\w./~$\\{-]"""  # a shell redirection: `> file`, `>> file`
    r"""|(?:^|[\s;&|(`])(?:rm|mv|cp|ln|chmod|chown|tee|truncate|rsync|install|patch|touch|mkdir|rmdir|dd|del|erase|ren|move|copy|xcopy)\s"""
    r"""|\bsed\s+-[a-z]*i\b|\bgit\s+(?:checkout|restore|apply|reset|stash|rm|mv|clean|am)\b""",
    re.IGNORECASE,
)


def names_of(policy: Dict[str, Any]) -> "re.Pattern[str]":
    """The guardrail paths as one pattern over the text of a script: each path of the policy without its `/**`, and the names that are always guarded (`EXTRA`)."""
    parts = list(EXTRA)
    for path in guardrails.guardrail_paths(policy or {}):
        plain = re.sub(r"(?:/\*\*|/\*)$", "", str(path)).strip("/")
        if plain and not plain.startswith(("*", "!")) and "*" not in plain:
            parts.append(re.escape(plain).replace(r"\/", r"[\\/]+"))
    return re.compile("|".join(parts), re.IGNORECASE)


def _read(path: str, ctx: "external._Ctx") -> Optional[str]:
    """The text of a script this line runs, looked for as `external._file_state` looks; None when there is none to read (missing, too big, a binary, or the harness's own program and tests)."""
    if not path or path.startswith(("-", "$")) or "$(" in path or path in ("/dev/null", "NUL"):
        return None
    if re.search(r"(?:^|[\\/])\.harness[\\/](?:engine|tests)[\\/]", path):
        return None
    root = os.path.realpath(str(ctx.root)) if ctx.root is not None else ""
    bases = [os.path.join(ctx.cwd or ".", item) for item in reversed(ctx.dirs)] + [ctx.cwd or "", root or "."]
    if ctx.folder is not None:
        bases.append(str(ctx.folder))
    for base in bases:
        full = os.path.normpath(os.path.join(base or ".", os.path.expanduser(path.replace("\\", "/") if os.sep == "/" and not re.match(r"^[A-Za-z]:", path) else path)))
        if not os.path.isfile(full):
            continue
        real = os.path.realpath(full)
        if root:
            try:
                inside = os.path.commonpath([real, root]) == root
            except ValueError:
                inside = False
            if inside and os.path.relpath(real, root).replace("\\", "/").startswith((".harness/engine/", ".harness/tests/")):
                return None
        try:
            if os.path.getsize(full) > MAX_BYTES:
                return None
            data = open(full, "rb").read()
        except OSError:
            return None
        return None if b"\0" in data[:8000] else data.decode("utf-8", errors="replace")
    return None


def refusal(command: str, root: Any, cwd: str, folder: Any, policy: Dict[str, Any]) -> Optional[str]:
    """The words of the refusal when the line runs a script file that names a guardrail path and writes; None when it runs none, or none such. Never raises."""
    try:
        if not command.strip() or root is None:
            return None
        names = names_of(policy)
        ctx = external._Ctx(root, cwd, hold=True, folder=folder, line=command)  # noqa: SLF001
        for text in [command] + external.nested(command):
            plain, _bodies = external._heredocs(join_lines(text))  # noqa: SLF001
            for tokens in split_segments(plain):
                tokens = external._without_redirects(external._setting_words(tokens))  # noqa: SLF001
                at = external._head_index(tokens)  # noqa: SLF001
                if at is None:
                    continue
                for path in external._runs_files(tokens, at, tokens, False):  # noqa: SLF001
                    path = path[1:] if path.startswith("?") else path  # a file a one-liner opens by name
                    body = _read(path, ctx)
                    if body is None:
                        continue
                    named, wrote = names.search(body), WRITES.search(body)
                    if named and wrote:
                        return messages.text("gate.script.refused", file=path, path=named.group(0), write=" ".join(wrote.group(0).split())[:40])
                if external._name(tokens[at]) == "cd" and len(tokens) > at + 1:  # noqa: SLF001
                    ctx.dirs.append(tokens[at + 1])
    except Exception:  # noqa: BLE001 - the other checks of the gate stand; this one is best effort
        return None
    return None
