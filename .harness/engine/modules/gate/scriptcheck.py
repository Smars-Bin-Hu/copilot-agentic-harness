"""The run of a script is judged (1.7.38, C13 FR 17b, narrowed in FR2 3).

The agent may write a script into its task folder (that is what a task is for) and run it. The gate does not read what a script does when it writes it, and it did not read it when it ran it: a script that rewrites an
engine file or a policy was a way round every guardrail (`helper.py` writes `.harness/engine/modules/gate/pin.py`, then everything passes). A line that runs a script file (`python3 x.py`, `node x.js`, `bash x.sh`,
`pwsh -File x.ps1`, `./x.sh`, `source x.sh`), or code in the line itself (`python3 -c`, `node -e`), is read here.

It is refused when the script WRITES TO a guardrail path: the target of a write (the file `open(..., "w")` opens, what `write_text`, `shutil.copy`, `os.remove`, `fs.writeFileSync`, `Set-Content`, `rm`, `mv`, `tee`, a
redirection names) is a guardrail path, written in it (`.harness/engine/x.py`) or put together in the same expression (`os.path.join(".harness", "engine")`, `".har" + "ness"`, a name the script set a line before). A script
that only reads a guardrail file, that names one in a comment, or that writes somewhere else, runs. This is best effort: a path made at run time from pieces in several statements, a script that imports another, a program
that writes by itself pass this check. `docs/12` says so; the guardrail files themselves are checked against the list the person accepted (`integrity.py`) whatever is run, and that list lies in a folder that is guarded too
(`core/guardrails.py`). The harness's own engine and tests are not read (they are what runs).
"""

from __future__ import annotations

import os
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

from core import guardrails, messages

from . import external
from . import shellwords
from .gitcmd import join_lines, split_segments

MAX_BYTES = 200 * 1024
EXTRA = (r"\.harness\b", r"\.github[\\/]+hooks", r"\.copilot-harness\b", r"HARNESS_INTEGRITY_DIR")  # named whole, even when the policy lists fewer; the folder of the lists the guardrails trust (1.7.38, C13 FR2 11b) too
EXACT = ("AGENTS.md", "Start Harness.command", "Start Harness.cmd")  # file names: the whole name, not a part of a longer one
SHOWN = 90  # characters of the write that a refusal quotes
SHELL_SUFFIXES = (".sh", ".bash", ".zsh", ".ps1", ".psm1", ".cmd", ".bat")


def names_of(policy: Dict[str, Any], admin: bool = False) -> "re.Pattern[str]":
    """The guardrail paths as one pattern over the text of a write target: each path of the policy without its `/**`, and the names that are always guarded (`EXTRA`). In an admin session only what stays closed there."""
    parts: List[str] = [] if admin else list(EXTRA[:2])
    parts += list(EXTRA[2:])
    exact: List[str] = [] if admin else list(EXACT)
    for path in (guardrails.admin_locked(policy or {}) if admin else guardrails.guardrail_paths(policy or {})):
        plain = re.sub(r"(?:/\*\*|/\*)$", "", str(path)).strip("/")
        if plain and not plain.startswith(("*", "!")) and "*" not in plain:
            (parts if "/" in plain or plain.startswith(".") else exact).append(re.escape(plain).replace(r"\/", r"[\\/]+"))
    for folder in guardrails.home_folders():  # a folder `HARNESS_INTEGRITY_DIR` names, written by its full path
        parts.append(re.escape(folder).replace(r"\/", r"[\\/]+"))
    body = "(?:" + "|".join(parts) + ")(?![\\w-])" if parts else ""
    whole = "(?<![\\w.-])(?:" + "|".join(re.escape(item) for item in exact) + ")(?![\\w.-])" if exact else ""
    return re.compile("|".join(item for item in (body, whole) if item) or "(?!x)x", re.IGNORECASE)


# --- reading a text: assignments, expressions, calls ---------------------------------------------------------------------------------------------------------------------------------------------------

_ASSIGN = re.compile(r"^[ \t]*(?:export[ \t]+|const[ \t]+|let[ \t]+|var[ \t]+|local[ \t]+|readonly[ \t]+|declare[ \t]+(?:-\w+[ \t]+)*|\$script:|\$)?([A-Za-z_]\w*)[ \t]*(\+?=|:=)(?!=)[ \t]*(.+?)[ \t]*;?[ \t]*$", re.MULTILINE)
_FOR = re.compile(r"^[ \t]*for[ \t(]+(?:const[ \t]+|let[ \t]+|var[ \t]+)?\$?([\w, \t]+?)[ \t]+(?:in|of)[ \t]+(.+?)[ \t]*[:{;)]?(?:[ \t]*(?:do|then))?[ \t]*$", re.MULTILINE)
_QUOTED = re.compile(r"""'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`""")
_LITERAL = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`""")
_IDENT = re.compile(r"\$?\{?\b([A-Za-z_]\w*)\b\}?")
_INSIDE = re.compile(r"\$\{(\w+)\}|\$(\w+)\b|%(\w+)%|\{(\w+)\}")


def _assignments(body: str) -> Dict[str, str]:
    """What the script sets by simple assignments and `for` heads (`BASE = ".harness"`, `P += "/engine"`, `for p in [".harness/engine"]:`): the text on the right of each name, as written. Best effort."""
    found: Dict[str, str] = {}
    for match in _ASSIGN.finditer(body):
        name, operator, value = match.group(1), match.group(2), match.group(3)
        found[name] = (found.get(name, "") + " " + value) if operator == "+=" else value
    for match in _FOR.finditer(body):
        for name in re.split(r"[,\s]+", match.group(1).strip()):
            if name:
                found[name] = found.get(name, "") + " " + match.group(2)
    return found


def _expand(expression: str, assigned: Dict[str, str]) -> str:
    """The expression with the names the script set put in: outside quotes each plain name, inside a quote the forms a string takes names in (`{x}`, `${x}`, `$x`, `%x%`)."""
    text = expression
    for _ in range(4):
        out: List[str] = []
        last = 0
        for quoted in _QUOTED.finditer(text):
            out.append(_IDENT.sub(lambda m: assigned.get(m.group(1), m.group(0)), text[last:quoted.start()]))
            out.append(_INSIDE.sub(lambda m: assigned.get(next(g for g in m.groups() if g), m.group(0)), quoted.group(0)))
            last = quoted.end()
        out.append(_IDENT.sub(lambda m: assigned.get(m.group(1), m.group(0)), text[last:]))
        again = "".join(out)[:4000]
        if again == text:
            break
        text = again
    return text


def _pieces(text: str) -> List[str]:
    return [next(part for part in item if part) if any(item) else "" for item in _LITERAL.findall(text)]


def _named(expression: str, names: "re.Pattern[str]", assigned: Dict[str, str]) -> str:
    """The guardrail path this expression names (written in it, or put together from its own pieces), or "". The pieces are tried joined as they are (`".har" + "ness"`) and with a slash between (`os.path.join(".harness", "engine")`)."""
    for text in (expression, _expand(expression, assigned)):
        found = names.search(text)
        if found:
            return found.group(0)
        for joined in _joins(_pieces(text)):
            found = names.search(joined)
            if found:
                return found.group(0)
    return ""


def _joins(pieces: List[str]) -> List[str]:
    """The ways the pieces of an expression can be joined into one path: each place between two of them may be nothing (`".har" + "ness"`) or a slash (`os.path.join(".harness", "engine")`), and both can be in one expression."""
    if not pieces:
        return []
    if len(pieces) > 8:
        return ["".join(pieces), "/".join(pieces)]
    out = [""]
    for index, piece in enumerate(pieces):
        out = [(item + sep + piece) if index else piece for item in out for sep in (("", "/") if index else ("",))]
    return list(dict.fromkeys(item.replace("//", "/") for item in out))


def _arguments(text: str, at: int) -> Tuple[List[str], int]:
    """The arguments of the call whose `(` stands just before `at` (quotes and brackets kept whole), and where the call ends."""
    args: List[str] = []
    depth, quote, begin, index = 0, "", at, at
    while index < len(text) and index - at < 4000:
        char = text[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                args.append(text[begin:index].strip())
                return [item for item in args if item], index + 1
            depth -= 1
        elif char == "," and depth == 0:
            args.append(text[begin:index].strip())
            begin = index + 1
        index += 1
    args.append(text[begin:index].strip())
    return [item for item in args if item], index


def _receiver(text: str, dot: int) -> str:
    """The expression a method is called on, as it stands before the `.` at `dot`: names, dots and brackets back to the start of it."""
    index, depth = dot, 0
    while index > 0:
        char = text[index - 1]
        if char in ")]}":
            depth += 1
        elif char in "([{":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and not (char.isalnum() or char in "_.$"):
            if char in "'\"`":
                begin = text.rfind(char, 0, index - 1)
                if begin == -1:
                    break
                index = begin + 1
            else:
                break
        index -= 1
    return text[index:dot]


# --- what writes -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

_MODULES = frozenset("io codecs gzip bz2 lzma tarfile os fs fsp promises file fileutils shutil zipfile builtins pathlib".split())
_OPEN = re.compile(r"(?<![\w$.])(?:(?:io|codecs|gzip|bz2|lzma|tarfile|os|fs|fsp|promises|File|zipfile|builtins)\.)?(open|openSync|fopen|ZipFile|TarFile)\s*\(")
_METHOD_OPEN = re.compile(r"\.\s*open\s*\(")
_PATH_METHODS = frozenset("write_text write_bytes unlink rmdir touch chmod lchmod chown mkdir symlink_to hardlink_to truncate".split())
_PATH_MOVES = frozenset("rename replace".split())
_FIRST_ARG_METHODS = frozenset("save to_csv to_json to_excel to_parquet to_pickle to_feather to_hdf savefig savetxt tofile extractall extract".split())
_METHOD = re.compile(r"\.\s*(" + "|".join(sorted(_PATH_METHODS | _PATH_MOVES | _FIRST_ARG_METHODS)) + r")\s*\(")
_FUNCTIONS = (
    "remove unlink rename renames replace rmdir removedirs makedirs mkdir chmod chown lchown lchmod truncate symlink link utime copy copy2 copyfile copyfileobj copymode copystat copytree move rmtree make_archive unpack_archive "
    "write writeFile writeFileSync appendFile appendFileSync createWriteStream rm rmSync rmdirSync unlinkSync renameSync copyFile copyFileSync cp cpSync mkdirSync chmodSync truncateSync symlinkSync linkSync utimes binwrite "
    "delete rm_f rm_rf rm_r mv cp_r touch ln ln_s install safe_unlink mkdir_p remove_entry writeAllText writeAllBytes writeAllLines appendAllText"
).split()
_FUNCTION = re.compile(r"(?<![\w$])(?:os|shutil|fs|fsp|promises|File|FileUtils|IO|Dir|Pathname|\[(?:System\.)?IO\.(?:File|Directory)\]:)\s*[.:]+\s*(" + "|".join(sorted(_FUNCTIONS, key=len, reverse=True)) + r")\s*\(", re.IGNORECASE)
_BARE_FUNCTION = re.compile(r"(?<![\w$])(writeFileSync|appendFileSync|createWriteStream|rmSync|unlinkSync|renameSync|copyFileSync|cpSync|mkdirSync|rmdirSync|truncateSync|chmodSync|symlinkSync|file_put_contents)\s*\(|(?<![\w$.])(unlink|rmdir)\s*\(")
_SHELL_CALL = re.compile(r"(?<![\w$])(?:os\s*\.\s*(?:system|popen|exec\w*|spawn\w*)|subprocess\s*\.\s*\w+|child_process\s*\.\s*\w+|execSync|execFileSync|spawnSync|execFile|system|popen|Popen|check_output|check_call|getoutput)\s*\(")
_CHDIR = re.compile(r"(?:^|[;&|(\s])(?:cd|pushd|chdir|set-location|sl|push-location)[ \t]+(?:/d[ \t]+)?[\"']?([^\s;&|\"')]+)|\b(?:os|process)\s*\.\s*chdir\s*\(([^)]*)\)", re.IGNORECASE)
_ALL_ARGS_SHELL = frozenset(
    "rm rmdir unlink del erase rd remove-item ri shred truncate touch mkdir md chmod chown chgrp attrib icacls setfacl new-item ni set-content sc add-content ac clear-content clc out-file set-itemproperty sp rename-item rni ren rename mv move move-item mi "
    "tee tee-object patch mkfifo mknod export-csv export-clixml expand-archive set-acl".split()
)
_DESTINATION_SHELL = frozenset("cp copy copy-item cpi install rsync xcopy robocopy ln scp".split())
_GIT_WRITES = frozenset("checkout restore reset stash rm mv clean apply am cherry-pick revert switch merge rebase pull".split())
_REDIRECT = re.compile(r"""(?<![<>=&\w-])(?:\d?>>?|&>>?|>\|)[ \t]*["']?([^\s"';&|<>)(`]+)""")
_WRAPPERS = frozenset("sudo env nohup time command exec nice timeout call start builtin".split())
_VALUE_OPTIONS = {"curl": ("-o", "--output", "-D", "--dump-header", "--stderr", "-c", "--cookie-jar", "--trace", "--trace-ascii"), "wget": ("-O", "--output-document", "-P", "--directory-prefix", "-o", "--output-file", "-a", "--append-output"),
                  "invoke-webrequest": ("-outfile",), "iwr": ("-outfile",), "invoke-restmethod": ("-outfile",), "irm": ("-outfile",), "start-bitstransfer": ("-destination",)}


def _mode_of(args: List[str], at: int, keyword: str = "mode") -> Optional[str]:
    """The mode argument of an `open`: the keyword form, else the positional one at `at`; None when there is none."""
    for item in args:
        found = re.match(keyword + r"\s*=\s*(.+)$", item)
        if found:
            return found.group(1)
    return args[at] if len(args) > at else None


def _is_write_mode(mode: Optional[str], assigned: Dict[str, str]) -> bool:
    """Does the mode argument of an `open` write? No mode reads; a literal with `w`, `a`, `x` or `+` writes; a mode that is no literal (a variable that cannot be read) is taken as a write."""
    if mode is None:
        return False
    text = _expand(mode, assigned)
    if re.search(r"O_(?:WRONLY|RDWR|APPEND|CREAT|TRUNC)|FileMode\.(?:Create|Append|OpenOrCreate|Truncate)", text):
        return True
    literals = _pieces(text)
    if not literals:
        return bool(text.strip()) and not re.fullmatch(r"None|undefined|null|nil", text.strip())
    return any(re.search(r"[wax+]", item) or item.lstrip().startswith((">", "+<", "|")) for item in literals)


def _shell_writes(text: str) -> List[Tuple[str, str]]:
    """The writes of the shell commands in a text: `(the command, the words that name what it writes)`. A redirection names its file; `rm`, `mv`, `tee`, `touch`... name all their words; `cp`, `install`, `ln`... their
    destination; `sed -i` and `perl -i` their files; `git checkout` and the like what they are given; `curl -o`, `wget -O`... their file."""
    out: List[Tuple[str, str]] = []
    for line in re.split(r"[;\n]|&&|\|\||(?<![&>])&(?![&>])|\|", text):
        for found in _REDIRECT.finditer(line):
            out.append((found.group(0).strip()[:SHOWN], found.group(1)))
        try:
            words = shlex.split(line.replace("\\", "/"), posix=True)  # a Windows path (`.harness\engine\x.py`) keeps its names: its backslash is a separator
        except ValueError:
            words = line.replace("\\", "/").split()
        while words and (words[0].lower() in _WRAPPERS or re.match(r"^[A-Za-z_]\w*=", words[0]) or re.fullmatch(r"\d+", words[0]) or (words[0].startswith("-") and len(words) > 1)):
            words = words[1:]
        if not words:
            continue
        name = os.path.basename(words[0].replace("\\", "/")).lower()
        name = name[:-4] if name.endswith(".exe") else name
        rest = words[1:]
        positional = [item for item in rest if not item.startswith("-")]
        shown = " ".join(words)[:SHOWN]
        if name in _ALL_ARGS_SHELL:
            out.append((shown, " ".join(rest)))
        elif name in _DESTINATION_SHELL:
            targets = [rest[i + 1] for i, item in enumerate(rest[:-1]) if item.lower() in ("-t", "--target-directory", "-destination", "-dest")]
            out.append((shown, " ".join(targets) if targets else (positional[-1] if positional else "")))
        elif name == "dd":
            out.append((shown, " ".join(item[3:] for item in rest if item.startswith("of="))))
        elif name in ("sed", "perl", "ruby", "gawk", "awk"):
            if any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z]*", item) or item.startswith("--in-place") or item == "inplace" for item in rest):
                out.append((shown, " ".join(rest)))
        elif name == "git":
            word = next((item for item in rest if not item.startswith("-")), "")
            if word in _GIT_WRITES:
                out.append((shown, " ".join(rest)))
        elif name in _VALUE_OPTIONS:
            wanted = _VALUE_OPTIONS[name]
            targets = [rest[i + 1] for i, item in enumerate(rest[:-1]) if item.lower() in wanted] + [item.split("=", 1)[1] for item in rest if "=" in item and item.split("=", 1)[0].lower() in wanted]
            out.append((shown, " ".join(targets)))
        elif name in ("tar", "unzip", "7z", "7za", "gunzip", "bunzip2", "xz", "unxz"):
            if name != "tar" or any(re.fullmatch(r"-?[a-zA-Z]*x[a-zA-Z]*", item) or item == "--extract" for item in rest[:2]):
                out.append((shown, " ".join(rest)))
    return [item for item in out if item[1]]


_FIRST_ARG = frozenset(
    "write writefile writefilesync appendfile appendfilesync createwritestream binwrite writealltext writeallbytes writealllines appendalltext truncate chmod chown lchown lchmod utime utimes mkdir makedirs mkdirsync rm rmsync rmdir rmdirsync "
    "unlink unlinksync remove removedirs rmtree delete rm_f rm_rf rm_r touch safe_unlink mkdir_p remove_entry chmodsync truncatesync file_put_contents".split()
)
_LAST_ARG = frozenset("copy copy2 copyfile copyfileobj copymode copystat copytree copyfilesync cp cpsync cp_r install symlink symlinksync link linksync ln ln_s unpack_archive".split())


def _target_args(name: str, args: List[str]) -> str:
    """The arguments of a call that name what it writes: the first for a call that writes or removes one file, the last for a copy or a link (the destination), all for a move (the place it leaves is written too)."""
    lower = name.lower()
    if lower in _FIRST_ARG or lower in ("make_archive",):
        return args[0]
    if lower in _LAST_ARG:
        return args[-1]
    return " ".join(args)


def writes_of(body: str, assigned: Dict[str, str], shell: bool) -> List[Tuple[str, str]]:
    """Every write in a text as `(the write as it stands, the expression that names what it writes)`. `shell`: the text is shell (or PowerShell): its lines are commands, and a redirection writes."""
    out: List[Tuple[str, str]] = []

    def add(start: int, end: int, target: str) -> None:
        out.append((" ".join(body[start:end].split())[:SHOWN], target))

    for match in _OPEN.finditer(body):
        args, end = _arguments(body, match.end())
        mode = _mode_of(args, 1)
        if args and _is_write_mode(mode, assigned):
            perl = any(item.lstrip().startswith((">", "+<", "|")) for item in _pieces(_expand(mode or "", assigned)))  # `open(my $fh, ">", $path)`, `open(FH, ">$path")`: the path comes after
            add(match.start(), end, " ".join(args[1:]) if perl else args[0])
    for match in _METHOD_OPEN.finditer(body):  # `Path(x).open("w")`
        receiver = _receiver(body, match.start())
        if receiver.split(".")[-1].lower() in _MODULES:
            continue
        args, end = _arguments(body, match.end())
        if _is_write_mode(_mode_of(args, 0), assigned):
            add(max(match.start() - len(receiver), 0), end, receiver)
    for match in _METHOD.finditer(body):
        method = match.group(1)
        receiver = _receiver(body, match.start())
        if receiver.split(".")[-1].lower() in _MODULES and method not in _FIRST_ARG_METHODS:
            continue  # `os.unlink(...)`, `shutil.move(...)`: read below, as a function
        args, end = _arguments(body, match.end())
        if method in _FIRST_ARG_METHODS:
            if args:
                add(match.start(), end, args[0])
        elif method in _PATH_METHODS or re.search(r"Path\s*\(|PurePath|pathlib|\bos\.path\b|Pathname", _expand(receiver, assigned)):  # `s.replace(a, b)` on a string is no path
            add(max(match.start() - len(receiver), 0), end, receiver + " " + " ".join(args) if method in _PATH_MOVES or method in ("symlink_to", "hardlink_to") else receiver)
    for pattern in (_FUNCTION, _BARE_FUNCTION):
        for match in pattern.finditer(body):
            args, end = _arguments(body, match.end())
            if args:
                add(match.start(), end, _target_args(match.group(1) or match.group(2) or "", args))
    for match in _SHELL_CALL.finditer(body):  # `os.system("rm -rf .harness/x")`, `subprocess.run(["rm", ".harness/x"])`: the words of the call are a command line
        args, _end = _arguments(body, match.end())
        flat = re.sub(r"[\[\](),]", " ", " ".join(args)).replace("'", " ").replace('"', " ")
        out.extend(_shell_writes(flat))
    if shell:
        out.extend(_shell_writes(body))
    return out


def written_guard(body: str, names: "re.Pattern[str]", shell: bool, in_guard: bool = False) -> Optional[Tuple[str, str]]:
    """`(the guardrail path, the write)` when a text writes to a guardrail path; None when it does not. `in_guard`: the line went into a guardrail folder before it ran the text (`cd .harness/engine && python3 x.py`): any
    write counts, for a short name written there is a guardrail file."""
    assigned = _assignments(body)
    writes = writes_of(body, assigned, shell)
    if not writes:
        return None
    if in_guard:
        return "cd", writes[0][0]
    for shown, target in writes:
        found = _named(target, names, assigned)
        if found:
            return found, shown
    for found in _CHDIR.finditer(body):  # the script goes into a guardrail folder itself and writes there by a short name
        entered = found.group(1) or found.group(2) or ""
        named = _named(entered, names, assigned) if entered else ""
        if named:
            return named, writes[0][0]
    return None


# --- the line ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

_EXECUTES = external._EXEC_WORDS  # noqa: SLF001 - code that runs what it loads: the file it opens is then a script


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


def _is_shell_script(path: str, body: str) -> bool:
    """Are the lines of this script file shell commands? By its suffix; a file with no suffix and a shell on its first line (`#!/bin/sh`) or none at all is."""
    name = path.lower()
    if name.endswith(SHELL_SUFFIXES):
        return True
    if "." in os.path.basename(name):
        return False
    first = body.split("\n", 1)[0]
    return not first.startswith("#!") or bool(re.search(r"\b(?:ba|z|da|k|c)?sh\b|pwsh", first))


def refusal(command: str, root: Any, cwd: str, folder: Any, policy: Dict[str, Any], admin: bool = False) -> Optional[str]:
    """The words of the refusal when the line runs a script file or code that writes to a guardrail path; None when it runs none, or none such. In an admin session only what stays closed there counts. Never raises."""
    try:
        if not command.strip() or root is None:
            return None
        names = names_of(policy, admin)
        ctx = external._Ctx(root, cwd, hold=True, folder=folder, line=command)  # noqa: SLF001
        in_guard = False
        plain = shellwords.dialect(command, "power")  # a PowerShell escape in the line (`` .harness/eng`ine ``): the line is read with it taken away too (1.7.38, C13 FR3)
        for text in [command] + external.nested(command) + ([plain] + external.nested(plain) if plain else []):
            plain, bodies = external._heredocs(join_lines(text))  # noqa: SLF001
            for tokens in split_segments(plain):
                tokens = external._without_redirects(external._setting_words(tokens))  # noqa: SLF001
                at = external._head_index(tokens)  # noqa: SLF001
                if at is None:
                    continue
                code = None
                if external._is_interpreter(tokens[at]):  # noqa: SLF001
                    kind, index = external._interp(tokens, at)  # noqa: SLF001
                    shell = external._family(tokens[at]) in ("shell", "power", "cmd")  # noqa: SLF001
                    if kind == "code" and index is not None and not shell:
                        code = " ".join(tokens[index + 1:])  # `python3 -c "..."`, `node -e "..."`: the code is read as a script is
                    elif kind == "stdin":
                        for body, _expands in bodies:  # a here-document that the interpreter is given
                            hit = written_guard(body, names, shell, in_guard)
                            if hit:
                                return messages.text("gate.script.refused", file=f"{tokens[at]} (here-document)", path=hit[0], write=hit[1])
                if code is not None:
                    hit = written_guard(code, names, False, in_guard)
                    if hit:
                        return messages.text("gate.script.refused", file=" ".join(tokens[at:at + 2]) + " ...", path=hit[0], write=hit[1])
                for path in external._runs_files(tokens, at, tokens, False):  # noqa: SLF001
                    maybe = path.startswith("?")  # a file a one-liner opens by name: it is a script only when the code runs what it reads
                    path = path[1:] if maybe else path
                    if maybe and not (code is not None and _EXECUTES.search(code)):
                        continue
                    body = _read(path, ctx)
                    if body is None:
                        continue
                    hit = written_guard(body, names, _is_shell_script(path, body), in_guard)
                    if hit:
                        return messages.text("gate.script.refused", file=path, path=hit[0], write=hit[1])
                if external._name(tokens[at]) in ("cd", "pushd", "chdir", "set-location", "sl") and len(tokens) > at + 1:  # noqa: SLF001
                    ctx.dirs.append(tokens[at + 1])
                    if _named(tokens[at + 1], names, {}):
                        in_guard = True  # what runs after a `cd` into a guardrail folder writes there by short names
    except Exception:  # noqa: BLE001 - the other checks of the gate stand; this one is best effort
        return None
    return None
