"""External actions (M43-2): the protocol for a call that reaches a system outside this repository (a cloud, a database, a ticket system).

The harness ships no system. A company lists its own under `systems`, in a tool pack (`rules.json`, copied from the knowledge base) or in `tools.override.json`; each entry says how a call to
it is recognised (`reach`), in which environment it runs (`env`), what the call does (`verbs`) and what the gate decides
(`rules`). Every call becomes one action: `{system, env, verb, target}`. This file only turns a terminal command into actions
and the policy into a decision; the handler applies the decision.

  verb       read, write, destroy, exec
  env        dev, ist, qat, prod, none (a system that has no environments, such as a ticket system)
  decision   allow, task (an open task with an approved plan), outbox, human, deny   (the order is from loosest to strictest)

Two floors, written down here so no company file can lower them by leaving something out:
  - a call to a listed system that no `verbs` rule names is a write;
  - an environment that no `env` rule names is prod.

A system may say what it needs before a call can reach it (`needs`, 1.7.1): `probe`, a read-only command that answers only when the
session has the right identity (a database that takes the identity of the process: `SELECT SUSER_SNAME()`), `expect`, a pattern its
output must match, and `launch`, the sentence for the person when it does not (how to start VS Code so that the identity is there).
The harness runs the probe for `tools check`, `doctor` and the board's Enter screen; it never stores a password or an identity.

Only a terminal command (`reach.cli`) is recognised for now. One program may serve several systems (one command line tool can run a ticket board and a cloud):
give each one a `reach.when` pattern, matched against the arguments after the program; the first system that matches owns the call. Like the git rules, this is a net, not a sandbox. The rule of 1.7.25: every word of a command line that is the name of a listed program must be accounted
for (a judged call, or an argument of a program in READ_ONLY_PROGRAMS), or the line is held; the files a line runs are read. What is still not seen is in the tool pack protocol.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.systems import (  # noqa: F401 - the names the handler, doctor and the tests use from here
    ALLOW, DECISIONS, DEFAULT_RULES, DENY, DESTROY, ENVS, EXEC, HUMAN, OUTBOX, PROBE_SECONDS, PROD, PROD_RULES, READ, TASK, VERBS, WRITE, by_address, clis, reach, run_probe, validate, warnings,
)

from . import inputfiles
from .gitcmd import MAX_DEPTH, SHELLS, SHELL_FLAGS, WRAPPERS, _is_environment, _name, join_lines, split_segments


@dataclass(frozen=True)
class Action:
    system: str
    env: str
    verb: str
    target: str
    text: str  # the command it came from, one command of the line
    named: bool = True  # False: no verbs rule matched, the verb is the write floor (a query in a shell variable or a file the gate cannot read)
    call: str = ""  # this one command from the program on (the program as its plain name): what a system's `item` pattern is matched against (1.7.21)
    why: str = ""  # an unseen call that is not an unreadable program name: "file" (a script the gate cannot read), "encoded" (an encoded PowerShell command); "command" (1.7.38): a word the system's own program does not have, its `target`
    unseen: bool = False  # a segment the gate cannot read (a program in a variable it cannot expand): held, never guessed (1.7.21)
    file: str = ""  # (1.7.38, C12 RC-G1) a file the call names as its input (`sqlcmd -i`): the one whose text made the call a destroy, or the first one the gate could not judge
    file_why: str = ""  # "destroy" (the file holds one: refused), "unread" (missing, too big, not text: held as a write), "twice" (the line names the file again and may change it: held as a write), "directive" (a line the gate cannot judge, such as `!!` or `:connect`: held as a write)

    def facts(self) -> Dict[str, Any]:
        facts: Dict[str, Any] = {"system": self.system, "env": self.env, "verb": self.verb, "target": self.target}
        if not self.named:
            facts["named"] = False  # said only when it matters: the log and the draft stay as they were for a named verb
        if self.file_why:
            facts["file"], facts["file_why"] = self.file, self.file_why  # said only when it matters
        return facts


def environment(system: Dict[str, Any], text: str) -> str:
    if system.get("env"):
        return system["env"]
    for rule in system.get("env_from") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["env"]
    return system.get("default_env") or PROD


def verb_named(system: Dict[str, Any], text: str) -> Optional[str]:
    """The verb of the first `verbs` rule that matches; None when none does (the gate then counts a write: the floor)."""
    for rule in system.get("verbs") or []:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule["verb"]
    return None


def verb_of(system: Dict[str, Any], text: str) -> str:
    return verb_named(system, text) or WRITE


def unknown_command(system: Dict[str, Any], args: str) -> str:
    """The subcommand a call names when the system lists the subcommands of its own program (`commands`) and this is none of them; else "" (1.7.38, C12 TB-03). A program that has no such word
    (`ado --help`, `ado --version`) is left to the verbs. An agent that makes a command up (`ado workitem 5`) gets a line and nothing runs, where it used to get a held card for a write that is no command."""
    commands = system.get("commands")
    if not commands:
        return ""
    try:
        found = re.search(str(system.get("command") or r"^([A-Za-z][\w-]*)"), args, re.IGNORECASE)
    except re.error:
        return ""
    word = found.group(1) if found and found.groups() and found.group(1) else ""
    return word if word and word.lower() not in {str(one).lower() for one in commands} else ""


def decide(system: Dict[str, Any], env: str, verb: str) -> str:
    rules = system.get("rules") or {}
    for key in ((env,) if env == PROD else (env, "*")):  # prod takes only a rule written for prod by name: a catch-all never loosens it (1.7.10)
        found = (rules.get(key) or {}).get(verb)
        if found:
            return found
    return (PROD_RULES if env == PROD else DEFAULT_RULES)[verb]


def _program(token: str) -> str:
    name = _name(token)
    for suffix in (".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _start(tokens: List[str], programs: Dict[str, List[str]]) -> Optional[int]:
    """Index of the program of a listed system, when only wrappers, environment settings, options and numbers stand before it."""
    for index, token in enumerate(tokens):
        if _program(token) in programs:
            return index
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return None
    return None


URL_HOST = re.compile(r"(?:https?:)?//(?:[^/\s'\"@]*@)?([^/\s'\"?#]+)", re.IGNORECASE)


def addresses_fit(system: Dict[str, Any], args: str) -> bool:
    """For a program a system has only `by_address` (1.7.38): the command names at least one address, and every address it names (the web address of the call, the text it sends, a header) is one of the
    system's (`reach.when`). A `curl` to the cloud that also names another place is not the system's call: it is judged as any other `curl`."""
    when = str((system.get("reach") or {}).get("when") or "")
    hosts = URL_HOST.findall(args)
    return bool(when and hosts and all(re.search(when, "//" + host, re.IGNORECASE) for host in hosts))


def _owner(systems: Dict[str, Any], names: List[str], args: str) -> Optional[str]:
    """The system a call belongs to, of those that use the program: the one whose `when` pattern matches the most of the arguments (1.7.10: two servers on
    one host, told apart by the port, both match `-S host`; the one that also matches the port wins); on a tie the first; one with no `when` only when no other matches."""
    best, best_len, fallback = None, -1, None
    for name in names:
        when = (systems[name].get("reach") or {}).get("when")
        if not when:
            fallback = fallback or name
            continue
        found = re.search(when, args, re.IGNORECASE)
        if found and len(found.group(0)) > best_len:
            best, best_len = name, len(found.group(0))
    return best or fallback


INTERPRETERS = frozenset("python python3 py node bash sh zsh dash pwsh powershell ruby perl".split())
_SCRIPT_EXTENSIONS = (".py", ".js", ".mjs", ".ps1", ".sh", ".rb", ".pl", ".cmd", ".bat")
MAX_SCRIPT_BYTES = 200 * 1024
_REDIRECT = re.compile(r"^\d*(?:>>?|<<-?|<)$")  # a redirection operator alone: its file (or here-document tag) is the next word
_REDIRECT_WITH_FILE = re.compile(r"^\d*(?:>>?|<<-?|<)[^\s<]")  # `>f`, `2>/dev/null`, `<f`, `<<EOF`

# Programs whose arguments are data to them (1.7.25): a word in their arguments that is the name of an outside system's program is only a word (`grep ado`, `cat .../ado`, `git
# commit -m 'ado: fix'`). This is the one list; `_data_only` adds the conditions (`find` without `-exec`, `git` without `-c`...). Every other program that has the name of a listed program
# among its arguments makes the line held: the gate cannot tell what the program does with it.
READ_ONLY_PROGRAMS = frozenset(
    "grep egrep fgrep rg cat tac echo printf head tail less more wc sort uniq cut nl ls dir tree stat file du diff cmp which whereis type pwd cd test [ [[ true false basename dirname "
    "realpath readlink jq column fold rev md5sum sha1sum sha256sum shasum od xxd strings date man apropos whatis sed find git gh harness "
    "get-content gc select-string sls get-childitem gci write-output write-host get-item test-path set-location sl resolve-path measure-object".split()
)
# Programs that manage files (1.7.27): they do not run their arguments, so a program name among them is only a name (`cp .../ado /tmp`, `chmod +x .../ado`, `mkdir out/ado`). The program that was
# copied is read when it is run later. `_data_only` takes away the options that make `tar` and `zip` run a command. `FILE_PLAIN` has no such option: it may stand after `xargs` too.
FILE_PLAIN = frozenset("mkdir touch cp mv rm rmdir chmod ln".split())
FILE_PROGRAMS = FILE_PLAIN | frozenset("tar zip unzip code".split())
FILE_MODULES = frozenset("py_compile compileall pyflakes flake8 black ruff isort".split())  # `python3 -m <one of these> file`
FILE_TOOLS = frozenset("flake8 ruff black pyflakes isort".split())
_FILE_RUNS = ("--use-compress-program", "--to-command", "--checkpoint-action", "--rsh-command", "--info-script", "--new-volume-script", "-I", "-F", "-TT", "-T", "--unzip-command")
_READERS = frozenset("cat tac head tail type get-content gc nl sort uniq less more".split())  # print files: into an interpreter they are its code
_SED_RUNS = re.compile(r"(?:^|[;{}\n])\s*(?:\d+(?:,\d+)?|\$)?\s*e\b|/[gpiImM0-9]*e[gpiImM0-9]*\s*$")  # sed's `e` command and `s///e`: runs a command
_CODE_INTERPRETERS = frozenset("python python3 py node bash sh zsh dash fish pwsh powershell ruby perl".split())
_ENCODED = "encodedcommand"


def _plain_name(token: str) -> str:
    name = _name(token)
    for suffix in _SCRIPT_EXTENSIONS:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_interpreter(token: str) -> bool:
    name = _name(token)
    return name in INTERPRETERS or bool(re.fullmatch(r"python\d(?:\.\d+)?", name))


def _family(token: str) -> str:
    name = _name(token)
    if name in ("bash", "sh", "zsh", "dash", "fish"):
        return "shell"
    if name in ("pwsh", "powershell"):
        return "power"
    if name in ("node",):
        return "node"
    if name in ("ruby", "perl"):
        return "ruby"
    return "python"


def _interp(tokens: List[str], at: int) -> Tuple[str, Optional[int]]:
    """What the interpreter at `tokens[at]` is given (1.7.25): `("script", i)` a file, `("module", i)` a module (`-m`), `("code", i)` code in the line (`-c`, `-e`, `-Command`,
    `-EncodedCommand`), or `("stdin", None)` nothing: it reads its code from the pipe or the terminal."""
    family = _family(tokens[at])
    index = at + 1
    while index < len(tokens):
        word = tokens[index]
        low = word.lower()
        if word in ("-", "<<<"):
            return "stdin", None
        if family == "shell":
            if word in ("-o", "+o"):
                index += 2
                continue
            if word == "-s":
                return "stdin", None
            if re.fullmatch(r"-[A-Za-z]*c", word):
                return "code", index
            if word.startswith("-") or word.startswith("+"):
                index += 1
                continue
        elif family == "power":
            flag = low.lstrip("-/") if word[:1] in "-/" else ""
            if flag:
                if "command".startswith(flag) or _ENCODED.startswith(flag) or flag == "ec":
                    return "code", index
                if "file".startswith(flag):
                    return ("script", index + 1) if index + 1 < len(tokens) else ("stdin", None)
                index += 2 if flag in ("executionpolicy", "ep", "windowstyle", "w", "workingdirectory", "wd", "inputformat", "outputformat", "version", "v", "configurationname", "settingsfile") else 1
                continue
        elif family == "node":
            if low in ("-e", "-p", "--eval", "--print"):
                return "code", index
            if low in ("-r", "--require"):
                index += 2
                continue
            if word.startswith("-"):
                index += 1
                continue
        elif family == "ruby":
            if low == "-e" or re.fullmatch(r"-[0-9A-DF-HJ-Za-hj-z]*[eE]", word):  # `-ne`, `-pe`, `-lane` (not `-i`: it takes the rest of the word as a suffix)
                return "code", index
            if word.startswith("-"):
                index += 1
                continue
        else:
            if word == "-c":
                return "code", index
            if word == "-m":
                return ("module", index + 1) if index + 1 < len(tokens) else ("stdin", None)
            if word in ("-X", "-W", "-Q") or low in ("-w",):
                index += 2
                continue
            if word.startswith("-"):
                index += 1
                continue
        return "script", index
    return "stdin", None


def _script_index(tokens: List[str], at: int) -> Optional[int]:
    """Index of the script (or module) an interpreter at `tokens[at]` is given, or None (no script: `-c`, a pipe, a prompt)."""
    kind, index = _interp(tokens, at)
    return index if kind in ("script", "module") else None


def _through_interpreter(tokens: List[str], programs: Dict[str, List[str]]) -> List[str]:
    """`python3 <pack>/bin/ado comment ...`, `bash tools/ado ...`, `node ado.js ...`: the script is the call when its file name is the program of a listed system (1.7.23)."""
    for at, token in enumerate(tokens):
        if _is_interpreter(token):
            index = _script_index(tokens, at)
            if index is not None and _plain_name(tokens[index]) in programs:
                return tokens[:0] + [_plain_name(tokens[index])] + tokens[index + 1:]
            return tokens
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return tokens
    return tokens


def _without_redirects(tokens: List[str]) -> List[str]:
    """The arguments of a command without its redirections (`2>&1`, `> f`, `2>/dev/null`, `>> f`, `< f`, `<<EOF`): they are not words of the call (1.7.23). A here-string
    (`<<< 'text'`) keeps its text: it is a word the command is given."""
    out: List[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token.startswith("<<<"):
            out.append("<<<")  # stays, to say that what follows is the command's input
            if token[3:]:
                out.append(token[3:])
            continue
        if _REDIRECT.match(token):
            skip = True
            continue
        if _REDIRECT_WITH_FILE.match(token):
            continue
        out.append(token)
    return out


def _input_files(tokens: List[str]) -> List[str]:
    """The files a command reads with `<` (`bash < x.sh`)."""
    files: List[str] = []
    for index, token in enumerate(tokens):
        if re.fullmatch(r"\d*<", token) and index + 1 < len(tokens):
            files.append(tokens[index + 1])
        elif re.match(r"^\d*<[^<(\s]", token):
            files.append(token.lstrip("0123456789")[1:])
    return files


def _unescaped(tokens: List[str]) -> List[str]:
    """The words with a lone backslash in them read as the shell does: `a\\do` is `ado`. A Windows path (a drive, `.\\`, two backslashes) is left."""
    out = []
    for token in tokens:
        if "\\" in token and not (re.match(r"^(?:[A-Za-z]:|\.{1,2}\\|\\\\)", token) or token.count("\\") > 1):
            token = re.sub(r"\\(.)", r"\1", token)
        out.append(token)
    return out


_WORD = re.compile(r"[^\s;&|(){}<>`'\"=,:$]+")


def _mentioned(text: str, names: List[str]) -> str:
    """The first program of a listed system that this text names as a word (1.7.25): a word equal to the name, with `.exe`, `.cmd`, `.bat` or a path in front of it (`/x/bin/ado`)."""
    for word in _WORD.findall(text):
        plain = _program(word.strip(".!?*#@%+"))
        if plain in names:
            return plain
    return ""


def _head_index(tokens: List[str]) -> Optional[int]:
    for index, token in enumerate(tokens):
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return index
    return None


def _is_harness(tokens: List[str], at: int) -> bool:
    """The harness's own command line (`harness task link add ado:1`, `python3 .harness/engine/cli.py ...`): its words are data to it."""
    if _program(tokens[at]) == "harness" or _name(tokens[at]) == "cli.py":
        return True
    if _is_interpreter(tokens[at]):
        kind, index = _interp(tokens, at)
        return kind == "script" and index is not None and _name(tokens[index]) == "cli.py"
    return False


def _data_only(tokens: List[str], at: int) -> bool:
    """Are the arguments of this command only data to it? Its name is in `READ_ONLY_PROGRAMS`, and no argument makes it run another command."""
    name = _program(tokens[at])
    if _is_harness(tokens, at):
        return True
    if _is_interpreter(tokens[at]):
        kind, index = _interp(tokens, at)
        return kind == "module" and index is not None and _name(tokens[index]) in FILE_MODULES  # `python3 -m py_compile file`
    plain = "/" not in tokens[at] and "\\" not in tokens[at]
    if name in FILE_PROGRAMS | FILE_TOOLS and plain:
        args = tokens[at + 1:]
        if name in ("tar", "zip", "unzip", "code"):
            return not any(item.startswith(_FILE_RUNS) or (item.startswith("-") and not item.startswith("--") and re.search(r"[IFTj]", item[1:]) and name in ("tar", "zip")) for item in args)
        return True
    if name not in READ_ONLY_PROGRAMS:
        return False
    args = tokens[at + 1:]
    if name == "find":
        return _find_data(args)
    if name == "git":
        words = []
        for index, item in enumerate(args):
            if not item.startswith("-"):
                words.append(item)
        before = args[: next((i for i, item in enumerate(args) if not item.startswith("-") and (i == 0 or args[i - 1] not in ("-C", "--git-dir", "--work-tree", "-c"))), len(args))]
        if "-c" in before or any(item.startswith(("--config-env", "--exec-path", "--ext-diff", "--textconv", "--extcmd", "--exec")) for item in args) or any("=!" in item or item.startswith("!") for item in args):
            return False  # an alias that starts with `!` runs a command; `-c` can set one
        return not (words and words[0].lower() in ("difftool", "mergetool", "bisect", "filter-branch", "submodule", "rebase", "instaweb", "daemon", "credential", "config", "gc"))
    if name == "man":
        return not any(item in ("-P", "--pager", "-H", "--html") or item.startswith(("--pager=", "-P")) for item in args)
    if name == "rg":
        return not any(item == "--pre" or item.startswith("--pre=") for item in args)
    if name == "sort":
        return not any(item.startswith("--compress-program") for item in args)
    if name == "sed":
        return not any(_SED_RUNS.search(item) for item in args)
    return True


def _find_data(args: List[str]) -> bool:
    """`find` with no action that writes, and whose `-exec` programs only read (`-exec grep -l ado {} \\;`): the words after `-exec` are that program's data (1.7.27)."""
    if any(item in ("-delete", "-fprint", "-fprintf", "-fls", "-fprint0") for item in args):
        return False
    index = 0
    while index < len(args):
        if args[index] in ("-exec", "-execdir", "-ok", "-okdir"):
            end = next((i for i in range(index + 1, len(args)) if args[i] in (";", "\\;", "\\", "+")), None)
            if end is None or end == index + 1:
                return False
            inner = args[index + 1: end]
            if inner[0] in ("{}", "{") or inner[0].startswith("$") or not _data_only(inner, 0):
                return False
            index = end
        index += 1
    return True


def _xargs_runs_code(tokens: List[str]) -> bool:
    """`xargs` that runs what it is given (a placeholder, a variable, a program that is not a plain reader): its input is code. `xargs -n1 echo` is not."""
    at = next((i for i, item in enumerate(tokens[:3]) if _name(item) == "xargs"), None)
    if at is None:
        return False
    index = at + 1
    while index < len(tokens):
        word = tokens[index]
        if word in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "-i", "-l"):
            index += 2
            continue
        if word.startswith("-") and word != "--":
            index += 1
            continue
        return not ((_program(word) in READ_ONLY_PROGRAMS or word in FILE_PLAIN) and word.isalpha() and not word.startswith("$"))
    return False


def _feeds_code(tokens: List[str]) -> bool:
    """Does this command run what it is given on its input (a shell or an interpreter with no script and no code in the line, `xargs` with a program to be named)?"""
    at = _head_index(tokens)
    if at is None:
        return False
    if _name(tokens[at]) == "cmd":
        return False
    if _is_interpreter(tokens[at]) or _name(tokens[at]) in ("fish",):
        return _interp(tokens, at)[0] == "stdin"
    return _xargs_runs_code(tokens)


def _heredocs(text: str) -> Tuple[str, List[Tuple[str, bool]]]:
    """The text without the bodies of its here-documents, and the bodies: `[(body, expands)]` (`expands` False for a quoted tag: the shell puts nothing in). A `<<` inside quotes is not one."""
    lines = text.split("\n")
    out: List[str] = []
    bodies: List[Tuple[str, bool]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        tags: List[Tuple[str, bool, bool]] = []
        quote = ""
        at = 0
        while at < len(line):
            char = line[at]
            if char == "\\" and quote != "'":
                at += 2
                continue
            if quote:
                quote = "" if char == quote else quote
            elif char in "\"'":
                quote = char
            elif line.startswith("<<", at) and not line.startswith("<<<", at):
                found = re.match(r"<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2", line[at:])
                if found:
                    tags.append((found.group(3), bool(found.group(2)), bool(found.group(1))))
                    at += found.end()
                    continue
            at += 1
        for tag, quoted, dash in tags:
            body: List[str] = []
            seen = False
            start = index
            while index < len(lines):
                row = lines[index]
                index += 1
                if (row.lstrip("\t") if dash else row) == tag:
                    seen = True
                    break
                body.append(row)
            if not seen:
                index = start  # no end line: the shell would give the rest of the text to it, but the gate reads it as commands, never hides it
                break
            bodies.append(("\n".join(body), not quoted))
    return "\n".join(out), bodies


class _Ctx:
    """What a scan of a command line needs besides the text (1.7.25). `hold`: the gate is asking, so the reading checks run (a script file is read, a word is accounted for)."""

    def __init__(self, root: Optional[Any] = None, cwd: str = "", hold: bool = False, folder: Optional[Any] = None, line: str = "") -> None:
        self.root, self.cwd, self.hold = root, cwd, hold
        self.folder, self.line = folder, line  # the task's folder (a place a relative path is looked for) and the whole line as written: for the files a call names as its input (1.7.38)
        self.dirs: List[str] = []  # directories this line changes to (`cd tools && ./run.sh`)
        self.quiet: set = set()  # programs a system lists `by_address`: not among the names that must be accounted for


def _file_state(path: str, names: List[str], ctx: _Ctx) -> Tuple[str, str]:
    """Read a file a command line runs (1.7.25). `("names", program)`: a listed program is a word in it. `("ok", "")`: it names none, is a binary, or is the harness's own engine or
    tests. `("missing", "")`: there is no such file. `("unreadable", "")`: too big (over 200 KB) or not readable."""
    if not path or path.startswith(("-", "$")) or "$(" in path:
        return "missing", ""
    if path in ("/dev/null", "NUL"):
        return "ok", ""  # nothing to run
    if re.search(r"(?:^|[\\/])\.harness[\\/](?:engine|tests)[\\/]", path):
        return "ok", ""  # the harness's own program and tests: the gate guards them in other ways
    root = os.path.realpath(str(ctx.root)) if ctx.root is not None else ""
    bases = [os.path.join(ctx.cwd or ".", item) for item in reversed(ctx.dirs)] + [ctx.cwd or "", root or "."]
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
            relative = os.path.relpath(real, root).replace("\\", "/") if inside else ""
            if relative.startswith((".harness/engine/", ".harness/tests/")):
                return "ok", ""
        try:
            if os.path.getsize(full) > MAX_SCRIPT_BYTES:
                return "unreadable", ""
            with open(full, "rb") as handle:
                data = handle.read()
        except OSError:
            return "unreadable", ""
        if b"\0" in data[:8000]:
            return "ok", ""  # a program, not a script: the gate goes by its name (a limit)
        found = _mentioned(data.decode("utf-8", errors="replace"), names)
        return ("names", found) if found else ("ok", "")
    return "missing", ""


_VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
_DECLARE = frozenset(["export", "declare", "typeset", "local", "readonly"])


def _expand(tokens: List[str], variables: Dict[str, str]) -> List[str]:
    """The simple shell variables of this command line that were set in it (`A=ado; $A item 1`, `export X=...`), put in. What is not known stays as it is."""
    out: List[str] = []
    for token in tokens:
        whole = _VARIABLE.fullmatch(token)
        value = _VARIABLE.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), token)
        if whole and value != token:
            out.extend(value.split())  # a variable that stands for a whole word may stand for a command and its words
        else:
            out.append(value)
    return out


def _head(tokens: List[str]) -> Optional[str]:
    """The word that names the program of a segment: the first one that is not a wrapper, an environment setting, an option or a number."""
    for token in tokens:
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit()):
            return token
    return None


def _substitutions(token: str) -> List[str]:
    """The commands inside `$( ... )` of one word (backticks became `$( )` in `join_lines`): a double quote does not hide them from the shell (1.7.21)."""
    found: List[str] = []
    index = token.find("$(")
    while index != -1:
        depth, end = 1, index + 2
        while end < len(token) and depth:
            depth += {"(": 1, ")": -1}.get(token[end], 0)
            end += 1
        found.append(token[index + 2: end - 1 if depth == 0 else end])
        index = token.find("$(", end)
    return found


def shlex_quote(token: str) -> str:
    return "'" + token.replace("'", "'\"'\"'") + "'" if re.search(r"[\s;&|()$`<>\"'\\]", token) or not token else token


def _scan(text: str, systems: Dict[str, Any], programs: Dict[str, List[str]], depth: int, found: List[Action], variables: Optional[Dict[str, str]] = None, ctx: Optional[_Ctx] = None) -> None:
    variables = {} if variables is None else variables
    ctx = ctx or _Ctx()
    text, bodies = _heredocs(join_lines(text))
    segments = split_segments(text)
    names = [program for program in programs if program not in ctx.quiet]
    feeds = ctx.hold and (any(_feeds_code(_without_redirects(tokens)) for tokens in segments) or ("<(" in text and any(_head_name(tokens) in ("source", ".") or _head_is_interpreter(tokens) for tokens in segments)))
    for body, expands in bodies:
        if depth < MAX_DEPTH and expands:  # an unquoted here-document: the shell runs what is in `$( )` and backticks
            for inner in _substitutions(join_lines(body)):
                _scan(inner, systems, programs, depth + 1, found, variables, ctx)
        hit = _mentioned(body, names) if (ctx.hold and feeds) else ""
        if hit:  # the body goes to an interpreter as its code
            found.append(Action("", "none", WRITE, hit, body[:200], named=False, call=body[:200], unseen=True))
    for tokens in segments:
        if tokens and tokens[0] in _DECLARE:
            tokens = tokens[1:]
        if tokens and all(_is_environment(item) for item in tokens):  # `A=ado`, `export A=ado`: remembered, not a call
            for item in tokens:
                key, _, value = item.partition("=")
                variables[key] = value
            continue
        raw = tokens
        tokens = _without_redirects(_expand(tokens, variables))
        if not tokens:
            continue
        plain = _unescaped(tokens)
        if plain != tokens:
            _scan(" ".join(shlex_quote(item) for item in plain), systems, programs, depth + 1, found, variables, ctx) if depth < MAX_DEPTH else None
        tokens = _through_interpreter(tokens, programs)
        if depth < MAX_DEPTH:
            for token in tokens:
                for inner in (_substitutions(token) if "$(" in token else []):
                    _scan(inner, systems, programs, depth + 1, found, variables, ctx)
        start = _start(tokens, programs)
        name = _owner(systems, programs[_program(tokens[start])], " ".join(tokens[start + 1:])) if start is not None else None
        if name is not None and _program(tokens[start]) in ctx.quiet and not addresses_fit(systems[name], " ".join(tokens[start + 1:])):
            name = None  # a program that only an address makes a call (curl) names an address that is not the system's: the system does not own it
        if name is not None:
            system = systems[name]
            line = " ".join(tokens)  # the environment settings in front of the program say something too
            target = ""
            if system.get("target"):
                match = re.search(system["target"], line, re.IGNORECASE)
                target = (match.group(1) if match and match.groups() else match.group(0) if match else "")[:120]
            word = unknown_command(system, " ".join(tokens[start + 1:]))
            if word:  # the pack's own program has no such command: refused, with a line (the gate's `unknown` answer)
                found.append(Action(name, environment(system, line), WRITE, word[:120], " ".join(tokens), call=" ".join([_program(tokens[start])] + tokens[start + 1:]), why="command"))
                continue
            verb = verb_named(system, " ".join(tokens[start + 1:]))
            file, file_why = "", ""
            if ctx.root is not None and system.get("input"):  # 1.7.38, C12 RC-G1: the statements of `sqlcmd -i file` are in the file: judged as the same words in the line are
                read = inputfiles.read(system, tokens[start + 1:], ctx.root, ctx.folder, ctx.cwd, ctx.line or " ".join(tokens))
                if read is not None:
                    verb = inputfiles.strictest([verb_named(system, read.rest), read.verb])
                    if read.state == "destroy":
                        verb, file, file_why = DESTROY, read.file, "destroy"
                    elif read.state:  # a file the gate cannot judge: the call is at least a write
                        verb = inputfiles.strictest([verb, WRITE])
                        file, file_why = (read.file, read.state) if verb == WRITE else ("", "")
            found.append(Action(name, environment(system, line), verb or WRITE, target, " ".join(tokens), named=verb is not None and file_why not in ("unread", "twice", "directive"), call=" ".join([_program(tokens[start])] + tokens[start + 1:]), file=file, file_why=file_why))
            continue
        if start is not None:
            continue  # the program of a listed system, none of whose systems owns this call: judged, and nothing to hold
        if _evaluated(tokens) is not None and depth < MAX_DEPTH:  # `eval "<command>"`: the string is the call
            _scan(_evaluated(tokens) or "", systems, programs, depth + 1, found, variables, ctx)
            continue
        head = _head(tokens)
        if head is not None and head.startswith("$"):  # a program the gate cannot read the name of: it may be a listed one
            found.append(Action("", "none", WRITE, "", " ".join(tokens), named=False, call=" ".join(tokens), unseen=True))
            continue
        waited = _wait_run(tokens)
        if waited is not None and depth < MAX_DEPTH:  # `harness wait --run "<command>"` (1.7.5): the command inside is the call
            _scan(waited, systems, programs, depth + 1, found, variables, ctx)
            continue
        wrapped = as_run(tokens)
        if wrapped is not None and depth < MAX_DEPTH:  # `harness as <alias> -- <command>` (1.7.10): the command inside is the call
            _scan(wrapped[1], systems, programs, depth + 1, found, variables, ctx)
            continue
        checked = len(tokens)
        shell_at = next((i for i, item in enumerate(tokens) if _name(item) in SHELLS), None)
        if shell_at is not None and depth < MAX_DEPTH:
            for i in range(shell_at + 1, len(tokens)):
                if tokens[i].lower() in SHELL_FLAGS and i + 1 < len(tokens):
                    _scan(" ".join(tokens[i + 1:]) if len(tokens) > i + 2 else tokens[i + 1], systems, programs, depth + 1, found, variables, ctx)
                    checked = i + 1  # the command string was read as a command line
                    break
        if ctx.hold:
            _account(tokens[:checked], raw, names, feeds, ctx, found)
        if tokens and _name(tokens[0]) == "cd" and len(tokens) > 1:
            ctx.dirs.append(tokens[1])


def _head_name(tokens: List[str]) -> str:
    at = _head_index(tokens)
    return _program(tokens[at]) if at is not None else ""


def _head_is_interpreter(tokens: List[str]) -> bool:
    at = _head_index(tokens)
    return at is not None and _is_interpreter(tokens[at])


def _encoded(tokens: List[str]) -> bool:
    """PowerShell given an encoded command (`-EncodedCommand`, `-enc`, `-e`: any start of the word)."""
    at = _head_index(tokens)
    if at is None or _name(tokens[at]) not in ("pwsh", "powershell"):
        return False
    return any(item[:1] in "-/" and len(item) > 1 and (_ENCODED.startswith(item[1:].lower()) or item[1:].lower() == "ec") for item in tokens[at + 1:])


def _account(tokens: List[str], raw: List[str], names: List[str], feeds: bool, ctx: _Ctx, found: List[Action]) -> None:
    """The rule of 1.7.25: every word of the line that is the name of an outside system's program must be accounted for. It is the program of a command that was judged (the caller
    went on), or an argument of a program that only reads (`READ_ONLY_PROGRAMS`). Anything else is held: the gate cannot tell what the program that has the name among its words
    will do with it. The files that the line runs or gives to an interpreter are read the same way (`_file_state`)."""
    text = " ".join(tokens)

    def hold(target: str, why: str = "") -> None:
        found.append(Action("", "none", WRITE, target, text, named=False, call=text, unseen=True, why=why))

    at = _head_index(tokens)
    if at is None:
        return
    if _encoded(tokens):
        hold("", "encoded")
        return
    data = _data_only(tokens, at) and not feeds
    if not data:
        hit = _mentioned(" ".join(tokens), names)
        if hit:
            hold(hit)
            return
    for path in _runs_files(tokens, at, raw, feeds):
        state, program = _file_state(path, names, ctx)
        if state == "names":
            hold(program)
            return
        if state in ("unreadable", "missing") and not (state == "missing" and _program(tokens[at]) in _READERS):
            hold(path, "file")
            return


def _runs_files(tokens: List[str], at: int, raw: List[str], feeds: bool) -> List[str]:
    """The files this command runs, or gives to an interpreter to run (1.7.25): a script (`./x.sh`, `bash x.sh`, `pwsh -File x.ps1`, `source x.sh`, `. x.sh`), a file on its input
    (`bash < x.sh`, `cat x.sh | bash`)."""
    files: List[str] = []
    head = tokens[at]
    name = _program(head)
    if _is_interpreter(head):
        kind, index = _interp(tokens, at)
        if kind == "script" and index is not None and index < len(tokens):
            files.append(tokens[index])
    elif name in ("source", ".") and at + 1 < len(tokens):
        files.append(tokens[at + 1])
    elif name in READ_ONLY_PROGRAMS or _is_harness(tokens, at):
        pass
    elif ("/" in head or "\\" in head or head.startswith("~") or head.lower().endswith(_SCRIPT_EXTENSIONS)) and not head.startswith("$"):
        files.append(head)
    if _is_interpreter(head) and _interp(tokens, at)[0] == "stdin":
        files.extend(_input_files(raw))
    if feeds and name in _READERS:
        files.extend(item for item in tokens[at + 1:] if not item.startswith("-"))
    return files


def _evaluated(tokens: List[str]) -> Optional[str]:
    head = _head(tokens)
    if head is None or _name(head) != "eval":
        return None
    return " ".join(tokens[tokens.index(head) + 1:])


def as_run(tokens: List[str]) -> Optional[Tuple[str, str]]:
    """(alias, the command) when this segment is `harness as <alias> -- <command>` (1.7.10); else None."""
    head = [index for index, token in enumerate(tokens) if _program(token) == "harness" or _name(token) == "cli.py"]
    if not head or len(tokens) < head[0] + 5 or tokens[head[0] + 1].lower() != "as" or tokens[head[0] + 3] != "--":
        return None
    return tokens[head[0] + 2], " ".join(tokens[head[0] + 4:])


def _wait_run(tokens: List[str]) -> Optional[str]:
    """The command `harness wait --run` is given, when this segment is such a call (`harness`, `harness.cmd` or `cli.py`, then `wait`); else None."""
    head = [index for index, token in enumerate(tokens) if _program(token) == "harness" or _name(token) == "cli.py"]
    if not head or len(tokens) <= head[0] + 1 or tokens[head[0] + 1].lower() != "wait":
        return None
    for index, token in enumerate(tokens):
        if token == "--run" and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith("--run="):
            return token[len("--run="):]
    return None


def classify(command: str, systems: Dict[str, Any], unseen: bool = False, root: Optional[Any] = None, cwd: str = "", folder: Optional[Any] = None) -> List[Tuple[Action, str]]:
    """Each call to a listed system in a command line, with what the policy decides for it. Empty when there is none.
    With `unseen` (the gate), a segment whose program the gate cannot read comes too, as a held call of no system (1.7.21).
    With `root` (the gate, 1.7.38), the files a call names as its input are read and judged too (`input` of the system); `folder` is the task's folder, a place a relative path is looked for."""
    if not systems or not command.strip():
        return []
    programs: Dict[str, List[str]] = {}
    quiet: set = set()  # programs that only an address makes a call (1.7.38): `curl` to an Azure DevOps address; the name alone is no call and holds no line
    for name, system in systems.items():
        for program in clis(system):
            programs.setdefault(program, []).append(name)
        for program in by_address(system):
            programs.setdefault(program, []).append(name)
            quiet.add(program)
    quiet -= {program for system in systems.values() for program in clis(system)}  # a program some system lists by name is a listed program for all
    found: List[Action] = []
    context = _Ctx(root, cwd, hold=unseen, folder=folder, line=command)
    context.quiet = quiet
    _scan(command, systems, programs, 0, found, ctx=context)
    return [(action, HUMAN if action.unseen else DENY if action.why == "command" else decide(systems[action.system], action.env, action.verb)) for action in found if unseen or not action.unseen]


def strictest(judged: List[Tuple[Action, str]]) -> Optional[Tuple[Action, str]]:
    """The call that decides the whole line: the strictest decision, the first of them."""
    best: Optional[Tuple[Action, str]] = None
    for item in judged:
        if best is None or DECISIONS.index(item[1]) > DECISIONS.index(best[1]):
            best = item
    return best


def report(systems: Any, run: Optional[Callable[[str], Tuple[Optional[int], str]]] = None) -> Dict[str, Any]:
    """For `tools check`: what the policy lists, what the gate decides for each environment, what is wrong, what looks like a mistake; with `run`, the probes too (`reach`)."""
    errors = validate(systems)
    listed: List[Dict[str, Any]] = []
    if not errors:
        for name, system in (systems or {}).items():
            fixed = system.get("env")
            effective = {
                env: " ".join(f"{verb}={decide(system, env, verb)}" for verb in VERBS)
                for env in ([fixed] if fixed else [item for item in ENVS if item != "none"])
            }
            listed.append({"system": name, "cli": clis(system), "verbs_listed": len(system.get("verbs") or []), "decides": effective})
    return {
        "systems": listed,
        "errors": errors,
        "warnings": [] if errors else warnings(systems or {}),
        **({"reach": reach(systems or {}, run)} if run is not None and not errors else {}),
        "ok": not errors,
        **({"exit_code": 1} if errors else {}),
    }
