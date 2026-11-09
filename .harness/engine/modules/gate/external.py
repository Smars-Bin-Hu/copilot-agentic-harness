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

from core import inputfiles, messages, statements
from core.systems import (  # noqa: F401 - the names the handler, doctor and the tests use from here
    ALLOW, DECISIONS, DEFAULT_RULES, DENY, DESTROY, ENVS, EXEC, HUMAN, OUTBOX, PROBE_SECONDS, PROD, PROD_RULES, READ, TASK, VERBS, WRITE, by_address, clis, reach, run_probe, validate, warnings,
)

from . import buildtools, pin, shellwords
from .gitcmd import LEADING_KEYWORDS, MAX_DEPTH, READ_ONLY as READ_ONLY_GIT, SEPARATORS, SHELLS, WRAPPERS, _is_environment, _name, head_index as _head_index, join_lines, shell_code, split_segments
from .shellwords import quote as shlex_quote


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
    file_why: str = ""  # "destroy" (the file holds a destroy of the `verbs`, a type with no lists: refused), "refuse" (the file holds a statement of the refuse list), "unread" (missing, too big, not text: asks the person), "twice" (the line names the file again and may change it: asks the person)
    zone: str = ""  # (1.7.38) a type with lists (`reads`): "refuse" (a statement is on the refuse list), "read" (every statement is on the read list), "write" (every statement is on the read or write list: an opened connection passes it), "ask" (the rest); "broken" (G-1: a program of a tool pack whose file is faulty: always held, `note` says which file and what is wrong); "unpinned" (1.7.38, C13 F2: a program whose type pins its calls to a connection, and this call names none the gate can read: refused, `why` says what is wrong: none, many, unread, word, other, unknown; `note` and `reason` are the refuse list's, when it caught a statement); "blocked" (a program or code the gate cannot judge: refused, `reason` says what to do instead); "" for a type with no lists
    note: str = ""  # the statement that decided: the one the refuse list caught, or the first that is on no list (cut short)
    reason: str = ""  # zone "refuse": the type's reason for it, in the language of the session: tells the agent the right way
    option: str = ""  # zone "unpinned" (1.7.38, C13 F2): the option the type names the target with (`-S`), for the words that tell the agent the right way
    via: str = ""  # zone "unpinned" (1.7.38, C13 FR 5): the connection the call was written for with `harness as <alias> --`: that gives its sign-in, not its server, so the words say how to write the server

    def facts(self) -> Dict[str, Any]:
        facts: Dict[str, Any] = {"system": self.system, "env": self.env, "verb": self.verb, "target": self.target}
        if not self.named:
            facts["named"] = False  # said only when it matters: the log and the draft stay as they were for a named verb
        if self.file_why:
            facts["file"], facts["file_why"] = self.file, self.file_why  # said only when it matters
        if self.zone in ("refuse", "ask", "broken", "unpinned", "blocked"):
            facts["zone"] = self.zone
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


_BLOCK_HEADS = frozenset(["%", "?", "foreach-object", "where-object", "{"])  # the head of a PowerShell script block (`1..3 | % { irm ... }`): the block's command is the call (1.7.38, C13 F2)


def _start(tokens: List[str], programs: Dict[str, List[str]]) -> Optional[int]:
    """Index of the program of a listed system, when only wrappers, environment settings, options, numbers and the head of a script block stand before it."""
    for index, token in enumerate(tokens):
        if _program(token) in programs:
            return index
        if not (_name(token) in WRAPPERS or _is_environment(token) or token.startswith("-") or token.isdigit() or token.lower() in _BLOCK_HEADS):
            return None
    return None


URL_HOST = re.compile(r"(?:https?:)?//(?:[^/\s'\"@]*@)?([^/\s'\"?#]+)", re.IGNORECASE)


def addresses_fit(system: Dict[str, Any], args: str) -> bool:
    """For a program a system has only `by_address` (1.7.38): the command names at least one address, and every address it names (the web address of the call, the text it sends, a header) is one of the
    system's (`reach.when`). A `curl` to the cloud that also names another place is not the system's call: it is judged as any other `curl`."""
    when = str((system.get("reach") or {}).get("when") or "")
    hosts = URL_HOST.findall(args)
    return bool(when and hosts and all(re.search(when, "//" + host, re.IGNORECASE) for host in hosts))


_CONTINUED = re.compile(r"`[ \t]*\r?\n")


def _cut_short(args: List[str], line: str) -> bool:
    """(1.7.38, D1-7) A web call that PowerShell goes on with where the line was cut: a backtick at the end of a line, or a hashtable (`@{a=1; b=2}`) whose `;` ended the command. The rest (`-Method Delete`) is
    in the next command, which the gate does not connect to this one, so this one is not judged by the address alone: the rule of the network asks."""
    return bool(_CONTINUED.search(line or "")) or sum(item.count("{") for item in args) > sum(item.count("}") for item in args)


def _owner(systems: Dict[str, Any], names: List[str], args: str) -> Optional[str]:
    """The system a call belongs to, of those that use the program: the one whose `when` pattern matches the most of the arguments (1.7.10: two servers on
    one host, told apart by the port, both match `-S host`; the one that also matches the port wins); on a tie the first; one with no `when` only when no other matches."""
    best, best_len, fallback = None, -1, None
    for name in names:
        if systems[name].get("broken"):
            return name  # a tool pack whose file is faulty owns every call of its programs (1.7.38, G-1): they are held, not left to a system that may not name them
    for name in names:
        when = (systems[name].get("reach") or {}).get("when")
        if not when:
            fallback = fallback or name
            continue
        found = re.search(when, args, re.IGNORECASE)
        if found and len(found.group(0)) > best_len:
            best, best_len = name, len(found.group(0))
    return best or fallback


INTERPRETERS = shellwords.INTERPRETERS  # one list, in shellwords.py: where the gate reads the words of a shell
_SCRIPT_EXTENSIONS = (".py", ".js", ".mjs", ".ps1", ".sh", ".rb", ".pl", ".cmd", ".bat")
MAX_SCRIPT_BYTES = 200 * 1024
_REDIRECT = re.compile(r"^\d*(?:>>?|<<-?|<)$")  # a redirection operator alone: its file (or here-document tag) is the next word
_REDIRECT_WITH_FILE = re.compile(r"^\d*(?:>>?|<<-?|<)[^\s<]")  # `>f`, `2>/dev/null`, `<f`, `<<EOF`

# Programs whose arguments are data to them (1.7.25): a word in their arguments that is the name of an outside system's program is only a word (`grep ado`, `cat .../ado`, `git
# commit -m 'ado: fix'`). This is the one list; `_data_only` adds the conditions (`find` without `-exec`, `git` without `-c`...). Every other program that has the name of a listed program
# among its arguments makes the line held: the gate cannot tell what the program does with it.
READ_ONLY_PROGRAMS = frozenset(
    "grep egrep fgrep rg cat tac echo printf head tail less more wc sort uniq cut nl ls dir tree stat file du diff cmp which whereis type pwd cd test [ [[ true false basename dirname "
    "realpath readlink jq column fold rev md5sum sha1sum sha256sum shasum od xxd strings date man apropos whatis sed find git gh harness where get-help "
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


_is_interpreter = shellwords.is_interpreter
_family = shellwords.family
_interp = shellwords.interp


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
    for word in _WORD.findall(re.sub(r"\\[nrt]", " ", text)):  # `printf 'sqlcmd\n'`: a backslash and a letter that a program turns into a line break is a space
        plain = _program(word.strip(".!?*#@%+"))
        if plain in names:
            return plain
    return ""


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
    if name in ("less", "more"):  # `less +'!command'` runs a command (1.7.38, C13 FR 20)
        return not any(item.startswith("+") for item in args)
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
        self.direct: set = set()  # programs only a `direct_only` system lists (a pack that is off and that no connection uses, 1.7.38, C13 F2c): a direct call is refused, their name in a script or a word of a line is no call
        self.reasons: Dict[str, str] = {}  # system -> its `blocked` text, in the language of the session
        self.as_alias = ""  # the connection of the `harness as <alias> --` whose command is being read (1.7.38, C13 FR 5)
        self.type_lists: Optional[Dict[str, Dict[str, Any]]] = None  # (1.7.38, C13 FR 2) the lists of the types that can be read, for a call of a faulty pack: read when the first such call comes
        self.code: List[Tuple[Any, str]] = []  # (pattern of the words, system) of the systems that name `reach.code`: words a one-liner interpreter must not run (1.7.38, C13 F2)


def _file_state(path: str, names: List[str], ctx: _Ctx, folders: Optional[List[str]] = None) -> Tuple[str, str]:
    """Read a file a command line runs (1.7.25). `("names", program)`: a listed program is a word in it. `("ok", "")`: it names none, is a binary, or is the harness's own engine or
    tests. `("missing", "")`: there is no such file. `("unreadable", "")`: too big (over 200 KB) or not readable."""
    if not path or path.startswith(("-", "$")) or "$(" in path:
        return "missing", ""
    if path in ("/dev/null", "NUL"):
        return "ok", ""  # nothing to run
    if re.search(r"(?:^|[\\/])\.harness[\\/](?:engine|tests)[\\/]", path):
        return "ok", ""  # the harness's own program and tests: the gate guards them in other ways
    root = os.path.realpath(str(ctx.root)) if ctx.root is not None else ""
    bases = list(folders or []) + [os.path.join(ctx.cwd or ".", item) for item in reversed(ctx.dirs)] + [ctx.cwd or "", root or "."]
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


def _setting_words(tokens: List[str]) -> List[str]:
    """A command that sets an environment variable, as the plain `NAME=value` words the rest of the gate reads (1.7.38, C13 F2): `export A=1`, `declare -x A=1`, `typeset -x A=1`, `export -n A=1`, `$env:A=1`, `$env:A = 1`,
    `$env:A='1'`. Any other command is returned as it was."""
    if not tokens:
        return tokens
    if tokens[0] in _DECLARE:
        rest = tokens[1:]
        while rest and rest[0].startswith("-") and rest[0] != "--":
            rest = rest[1:]  # `declare -x`, `typeset -gx`
        return rest
    found = re.match(r"^\$env:([A-Za-z_]\w*)(=.*)?$", tokens[0], re.IGNORECASE)
    if found:
        if found.group(2) is not None:
            return [found.group(1) + found.group(2)] + tokens[1:]
        if len(tokens) >= 2 and tokens[1].startswith("="):
            return [found.group(1) + "=" + (tokens[1][1:] if len(tokens[1]) > 1 else (tokens[2] if len(tokens) > 2 else ""))] + tokens[3 if len(tokens[1]) == 1 else 2:]
    return tokens


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


NOTE_CHARS = 100


def _short(text: str) -> str:
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 1].rstrip() + "\u2026"


# The other commands of a line that runs a script file (1.7.38, C13 F2). `sqlcmd -i x.sql` is judged by what x.sql holds when the gate looks, and the line may change x.sql before sqlcmd runs it (`cp drop.sql o[k].sql && sqlcmd -i ok.sql`:
# a glob, a quote or a bracket hides the name). So the rest of the line may only read: any program that is not on this list can write a file. A redirection and `tee` may write another file, never one the call reads.
LINE_READERS = frozenset(
    "cd pushd popd true false : test [ [[ echo printf pwd ls dir tree stat file du wc head tail cat tac nl less more sort uniq cut tr grep egrep fgrep rg basename dirname realpath readlink jq column fold rev "
    "md5sum sha1sum sha256sum shasum od strings date sleep which type diff cmp harness set unset read exit return wait for in case esac select tee "
    "get-content gc select-string sls get-childitem gci write-output write-host test-path set-location sl resolve-path measure-object tee-object".split()
)
_REDIRECT_TARGET = re.compile(r"^(?:\d*|&)(?:>>?\|?)(.*)$")
_SPECIAL = re.compile(r"[$`*?\[\]{}~!]")
_QUIET_FILES = frozenset(["/dev/null", "/dev/stdout", "/dev/stderr", "nul", "con"])


def _redirect_targets(tokens: List[str]) -> List[str]:
    """The files a command writes with `>` and `>>` (`> f`, `>f`, `2>f`, `&>f`); `2>&1` and `>&2` name none."""
    found: List[str] = []
    for index, token in enumerate(tokens):
        match = _REDIRECT_TARGET.match(token)
        if not match:
            continue
        rest = match.group(1)
        if rest:
            if not rest.startswith("&"):
                found.append(rest)
        elif index + 1 < len(tokens):
            found.append(tokens[index + 1])
    return found


def _identities(name: str, ctx: "_Ctx") -> set:
    """What a file name may be: the real paths it has from each place a relative name is looked for, and the file itself (device and inode) when it exists, so a link or a second name for it is found."""
    from pathlib import Path

    from core import pinfiles

    out: set = set()
    bases = pinfiles.bases(Path(str(ctx.root)), Path(str(ctx.folder)) if ctx.folder else Path(str(ctx.root)), ctx.cwd, ctx.line) if ctx.root is not None else [Path(ctx.cwd or ".")]
    shaped = os.path.expanduser(name.replace("\\", "/") if os.sep == "/" and not re.match(r"^[A-Za-z]:", name) else name)
    for base in bases:
        full = shaped if os.path.isabs(shaped) else os.path.join(str(base), shaped)
        out.add(os.path.normcase(os.path.realpath(full)))
        try:
            found = os.stat(full)
            out.add((found.st_dev, found.st_ino))
        except OSError:
            pass
    return out


def _safe_target(target: str, inputs: List[str], ctx: "_Ctx") -> bool:
    """May a command of the line write this file? Only a plain name that is none of the files the call reads: no variable, no glob, no bracket, and not a second name for one of them."""
    if target.lower() in _QUIET_FILES:
        return True
    if not target or _SPECIAL.search(target):
        return False
    mine = _identities(target, ctx)
    return not any(mine & _identities(name, ctx) for name in inputs)


def _line_writer(line: str, inputs: List[str], ctx: "_Ctx", allowed: set, depth: int = 0) -> str:
    """The first command of the line (other than a call of `allowed`, the program of the call itself) that may write a file the call reads, as it stands in the line (cut short); "" when none can. See `LINE_READERS`."""
    text, _bodies = _heredocs(join_lines(line))
    for tokens in split_segments(text):
        tokens = _setting_words(tokens)
        if not tokens or all(_is_environment(item) for item in tokens):
            continue
        shown = _short(" ".join(tokens))
        files = [item for item in _redirect_targets(tokens)]
        if any(not _safe_target(item, inputs, ctx) for item in files):
            return shown
        args = _without_redirects(tokens)
        at = _head_index(args)
        if at is None:
            continue
        head = args[at]
        if head.startswith("$") or "$(" in head:
            return shown  # a program the line does not name
        name = _program(head)
        rest = args[at + 1:]
        if name in allowed:
            continue
        if name in SHELLS or name == "eval":
            inners = (_evaluated(args) or []) if name == "eval" else (shell_code(args) or (0, []))[1]  # the command lines the shell is given, as `shellwords.readings` reads them (1.7.38, C13 FR3)
            if not inners or depth >= MAX_DEPTH or any(_line_writer(inner, inputs, ctx, allowed, depth + 1) for inner in inners):
                return shown
            continue
        if _starts_cli(args, at):
            wrapped, waited = as_run(args), _wait_run(args)
            inner = wrapped[1] if wrapped else waited
            if inner is not None and (depth >= MAX_DEPTH or _line_writer(inner, inputs, ctx, allowed, depth + 1)):
                return shown
            continue
        if name == "tee" and all(_safe_target(item, inputs, ctx) for item in rest if not item.startswith("-")):
            continue
        if name == "sort" and any(item in ("-o", "--output") or item.startswith(("--output=", "-o")) for item in rest):
            return shown
        if name == "git":
            word = next((item for item in rest if not item.startswith("-")), "")
            if word in READ_ONLY_GIT:
                continue
            return shown
        if name in LINE_READERS - {"tee"}:
            continue
        return shown
    return ""


RESERVED_IN_TASK = (".task", "OUTBOX", "REVIEW", "SNAPSHOT")  # places of a task folder that only the harness writes (`gate.json` `cli_owned_paths`): an output file is never one of them


def _in_task_folder(path: str, ctx: "_Ctx") -> bool:
    """Is this file (as the shell resolves it, from the folder the call runs in) a place inside the task folder the agent may write: not a variable, a glob, `~`, a place the harness owns, nor a link or `..` that leaves the folder?"""
    if ctx.folder is None or not path or _SPECIAL.search(path) or "$" in path:
        return False
    folder = os.path.realpath(str(ctx.folder))
    base = ctx.cwd or str(ctx.root or ".")
    full = os.path.realpath(os.path.join(base, os.path.expanduser(path)))
    try:
        if os.path.commonpath([full, folder]) != folder or full == folder:
            return False
    except ValueError:
        return False
    parts = os.path.relpath(full, folder).replace("\\", "/").split("/")
    return parts[0] not in RESERVED_IN_TASK and not (len(parts) == 1 and (parts[0].endswith(".diff") or parts[0] in ("TASK.md", "REQ.md")))


def _without_task_outputs(system: Dict[str, Any], args: List[str], ctx: "_Ctx") -> List[str]:
    """The words of the call without each output option (`outputs.options` of the type: `-o`, `--output-file`) and its file, when the file is inside the task folder (`_in_task_folder`). An output file anywhere else stays in
    the words: the call asks, as a write."""
    options = [str(one) for one in ((system.get("outputs") or {}).get("options") or [])]
    if not options:
        return args
    out: List[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        value, step = "", 0
        for option in options:
            if word == option and index + 1 < len(args):
                value, step = args[index + 1], 2
            elif option.startswith("--") and word.startswith(option + "="):
                value, step = word[len(option) + 1:], 1
            elif not option.startswith("--") and word.startswith(option) and len(word) > len(option):
                value, step = word[len(option):], 1
            if step:
                break
        if step and _in_task_folder(value, ctx):
            index += step
            continue
        out.append(word)
        index += 1
    return out


def _by_lists(system: Dict[str, Any], name: str, env: str, target: str, text: str, call: str, args: List[str], ctx: "_Ctx", lead: List[str]) -> Action:
    """A call of a type with lists (1.7.38, C12: pass, refuse, ask). The statements of the text and of the files it reads are cut (`statements.py`) and judged by `reads`, `writes` and `refuse`:
    refuse list first (whatever else is wrong with the call), then a call that gave the gate nothing to read, a text with a shell variable in it or a file the gate could not read (asks), then the lists.
    `verbs` do not decide the zone: they say what kind of call the card shows (write, exec), and a destroy rule that matches a statement is one more refusal."""
    args = _without_task_outputs(system, args, ctx)  # 1.7.38 (C13 FR 22): `-o file` into the task folder is a local write: the call is judged by its statements as without it
    read = inputfiles.read(system, args, ctx.root, ctx.folder, ctx.cwd, ctx.line or text)
    rest = inputfiles.verb_of_text(system, " ".join(lead + ([read.rest] if read else args)))  # the words that are no statement: the settings before the program (`SQLCMDINI=file`) and its options (`-o file`, `-q`)
    if read is None or not read.sources:  # the program reads what it is given on its input: nothing the gate sees
        return Action(name, env, strict([rest, WRITE]), target, text, named=rest is not None, call=call, zone=statements.ASK)
    joined = " ; ".join(item.text for item in read.items)
    label = inputfiles.strictest([inputfiles.verb_of_text(system, joined), rest])
    verdict = statements.judge(system, read.items)
    if verdict.zone != statements.REFUSE and label == DESTROY:  # a rule of `verbs` that names a destroy: refused as before, with the line of a destroy
        gone = next((item for item in read.items if inputfiles.verb_of_text(system, item.text) == DESTROY), None)
        verdict = statements.Verdict(statements.REFUSE, gone.text if gone else joined, "", quote=(gone.raw or gone.text) if gone else joined)
    file = read.files.get(verdict.statement, "") if verdict.zone == statements.REFUSE else read.file
    if verdict.zone == statements.REFUSE:
        return Action(name, env, DESTROY, target, text, call=call, file=file, file_why="refuse" if file else "", zone=statements.REFUSE, note=_short(verdict.quote or verdict.statement), reason=messages.pick(verdict.reason) if verdict.reason else "")
    if read.named:  # 1.7.38 (C13 F2): another command of the line may change the script file before it runs: refused, the file change and the call go in two calls
        changing = _line_writer(ctx.line or text, read.named, ctx, set(clis(system)))
        if changing:
            return Action(name, env, DESTROY, target, text, call=call, file=read.named[0], zone=statements.REFUSE, note=changing, reason=messages.text("gate.external.same_line"))
    why = read.state  # "unread", "twice": a file the gate could not read, or may change before it runs
    if why or read.unsure or verdict.zone == statements.ASK or rest in (WRITE, EXEC):
        about = read.file if why else read.unsure or ((verdict.quote or verdict.statement) if verdict.zone == statements.ASK else read.rest)
        return Action(name, env, strict([label, WRITE]), target, text, named=label is not None and not why, call=call, file=read.file if why else "", file_why=why, zone=statements.ASK, note=_short(about))
    if verdict.zone == statements.WRITE:
        return Action(name, env, strict([label, WRITE]), target, text, named=True, call=call, zone=statements.WRITE)
    return Action(name, env, READ, target, text, call=call, zone=statements.READ)


def _pin_owner(systems: Dict[str, Any], pinned: List[str], args: List[str]) -> Tuple[Optional[str], pin.Pinned]:
    """The connection a call of a pinned program reaches (1.7.38, C13 F2): the one whose address the server of the call, folded as the type says, matches; `(None, what is wrong)` when the call names none the gate can read."""
    seen = pin.read(systems[pinned[0]]["pin"], args)
    if seen.state != pin.OK:
        return None, seen
    name = _owner(systems, pinned, f"{seen.option} {seen.canon}")  # only the server is matched: a `-S host,port` inside a statement is no server
    return name, (seen if name is not None else pin.Pinned("unknown", seen.value, seen.canon, seen.option))


def _caught(first: Dict[str, Any], name: str, tokens: List[str], start: int, ctx: "_Ctx", variables: Dict[str, str]) -> Optional[Action]:
    """The refusal of the refuse list of a type, when the call holds a statement on it (the lists are read whatever else is wrong with the call: a `DROP` is never decided by the server); None when it holds none."""
    args = tokens[start + 1:]
    text = " ".join(tokens)
    call = " ".join([_program(tokens[start])] + args)
    caught: Optional[Action] = None
    if first.get("reads"):
        zoned = _by_lists(first, name, "none", "", text, call, args, ctx, tokens[:start] + [f"{key}={value}" for key, value in variables.items()])
        caught = zoned if zoned.zone == statements.REFUSE else None
    if caught is None and (first.get("refuse") or first.get("reads")):  # a statement the gate does not cut (`sqlcmd query "DROP TABLE t"`): its words are read as one text
        entry = statements.refuse_entry(first, " ".join(args))
        if entry:
            caught = Action(name, "none", DESTROY, "", text, zone=statements.REFUSE, note=_short(" ".join(args)), reason=messages.pick(entry.get("reason") or ""))
    return caught


def _broken_refusal(system: Dict[str, Any], name: str, tokens: List[str], start: int, ctx: "_Ctx", variables: Dict[str, str]) -> Optional[Action]:
    """(1.7.38, C13 FR 2) A call of a program of a pack whose file is faulty is held, because the gate cannot judge it. But when the type of the program can still be read as JSON, the refuse list of the type is read first: a
    `DROP` is refused with the type's reason, as it is when the pack is good, and does not go to a card that someone may approve. None when there is no type to read, or nothing on the list catches the call."""
    if ctx.root is None:
        return None
    try:
        from pathlib import Path

        from core import govern

        if ctx.type_lists is None:
            ctx.type_lists = govern.type_lists(Path(str(ctx.root)))
        found = ctx.type_lists.get(_program(tokens[start]))
        return _caught(dict(system, **found), str(system.get("toolpack") or name), tokens, start, ctx, variables) if found else None  # named by its pack: "sqlserver", not "broken-sqlserver"
    except Exception:  # noqa: BLE001 - the call is held anyway: a list that cannot be read is no reason to let it through
        return None


def _unpinned(systems: Dict[str, Any], pinned: List[str], seen: pin.Pinned, tokens: List[str], start: int, ctx: "_Ctx", variables: Dict[str, str]) -> Optional[Action]:
    """The refusal of a call of a pinned program that reaches no connection the gate can name (1.7.38, C13 F2). The refuse list of the type is read first, so a `DROP` is never decided by the server: the refusal then says
    both. A call that only asks for help (`sqlcmd -?`) reaches nothing: None, it passes when the refuse list has nothing."""
    caught = _caught(systems[pinned[0]], pinned[0], tokens, start, ctx, variables)
    if seen.state == pin.FREE:
        return caught
    program = _program(tokens[start])
    call = " ".join([program] + tokens[start + 1:])
    return Action("", "none", DESTROY, (seen.value or program)[:120], " ".join(tokens), call=call, why=seen.state, zone="unpinned", option=seen.option, via=ctx.as_alias, note=caught.note if caught else "", reason=caught.reason if caught else "", file=caught.file if caught else "", file_why=caught.file_why if caught else "")


def _free(info: Dict[str, Any], args: List[str]) -> bool:
    """Does the call only print help or the version (`free` of the type: `--help`, `-?`)? Such a call reaches no one. A type with a `pin` also needs that no server is named (`sqlcmd -S x --help` is judged like any call with a server).
    A type that declares no `free` has the default words (`systems.DEFAULT_FREE`), and a call of nothing but those."""
    words = [str(one) for one in info.get("free") or []]
    if info.get("default"):  # 1.7.38 (C13 F2c): the words the protocol gives a type that declares none: the call is made of them and nothing else, so no argument names a target
        return bool(args) and all(word in words for word in args)
    if not words or not any(word in words for word in args):
        return False
    return pin.read(dict(info["pin"], free=words), args).state == pin.FREE if isinstance(info.get("pin"), dict) else True


def _unconnected(system: Dict[str, Any], name: str, tokens: List[str], start: int, ctx: "_Ctx", variables: Dict[str, str]) -> Optional[Action]:
    """The refusal of a call of a program that a tool pack declares and no connection lists (1.7.38, C13 F2b): the computer has no connection of its type, so there is no place the call could be judged for. The refuse
    list is read first and its reason comes with the refusal; a call that only prints help or the version (`free`) passes when the refuse list has nothing."""
    info = system["noconn"]
    program = _program(tokens[start])
    caught = _caught(system, name, tokens, start, ctx, variables)
    if _free(info, tokens[start + 1:]):
        return None if caught is None else Action("", "none", DESTROY, program, " ".join(tokens), call=" ".join([program] + tokens[start + 1:]), zone="blocked",
                                                  reason=messages.text("gate.external.noconn.refused", statement=caught.note, reason=caught.reason))
    also = messages.text("gate.external.noconn.also", statement=caught.note, reason=caught.reason) if caught is not None else ""
    return Action("", "none", DESTROY, program, " ".join(tokens), call=" ".join([program] + tokens[start + 1:]), zone="blocked",
                  reason=messages.text("gate.external.noconn", program=program, type=info.get("type") or "", also=also))


def _code_blocked(tokens: List[str], ctx: "_Ctx") -> Optional[Action]:
    """The code a one-liner interpreter is given (`python3 -c`, `node -e`), when it names a word a system lists in `reach.code`: a program the gate cannot judge talks to the outside system from inside it (1.7.38, C13 F2)."""
    if not ctx.code:
        return None
    at = _head_index(tokens)
    if at is None or not _is_interpreter(tokens[at]):
        return None
    kind, index = _interp(tokens, at)
    if kind != "code" or index is None:
        return None
    code = " ".join(tokens[index + 1:])
    for regex, system in ctx.code:
        if regex.search(code):
            return Action("", "none", DESTROY, _program(tokens[at]), " ".join(tokens), call=" ".join(tokens), zone="blocked", reason=ctx.reasons.get(system, ""))
    return None


def strict(verbs: List[Optional[str]]) -> str:
    return inputfiles.strictest(verbs) or WRITE


def _scan(text: str, systems: Dict[str, Any], programs: Dict[str, List[str]], depth: int, found: List[Action], variables: Optional[Dict[str, str]] = None, ctx: Optional[_Ctx] = None) -> None:
    variables = {} if variables is None else variables
    ctx = ctx or _Ctx()
    text, bodies = _heredocs(join_lines(text))
    segments = split_segments(text)
    names = [program for program in programs if program not in ctx.quiet and program not in ctx.direct]
    feeds = ctx.hold and (any(_feeds_code(_without_redirects(tokens)) for tokens in segments) or ("<(" in text and any(_head_name(tokens) in ("source", ".") or _head_is_interpreter(tokens) for tokens in segments)))
    if ctx.hold:
        _hidden_in_line(segments, text, programs, feeds, found)
        _text_runners(text, bodies, names, ctx, found)  # 1.7.38 (C13 FR 20): a runner of text (make, tclsh, m4, crontab, at...) whose text names a governed program
    elif ctx.direct:
        _launched(segments, programs, found)
    for body, expands in bodies:
        if depth < MAX_DEPTH and expands:  # an unquoted here-document: the shell runs what is in `$( )` and backticks
            for inner in _substitutions(join_lines(body)):
                _scan(inner, systems, programs, depth + 1, found, variables, ctx)
        hit = _mentioned(body, names) if (ctx.hold and feeds) else ""
        if hit:  # the body goes to an interpreter as its code
            found.append(Action("", "none", WRITE, hit, body[:200], named=False, call=body[:200], unseen=True))
    for tokens in segments:
        tokens = _setting_words(tokens)
        if tokens and all(_is_environment(item) for item in tokens):  # `A=ado`, `export A=ado`: remembered, not a call
            for item in tokens:
                key, _, value = item.partition("=")
                variables[key] = value
            continue
        raw = tokens
        tokens = _without_redirects(_expand(tokens, variables))
        if not tokens:
            continue
        if len(tokens) > 2 and _name(tokens[0]) == "command" and tokens[1] in ("-v", "-V"):
            continue  # `command -v sqlcmd` looks a program up: it runs nothing
        plain = _unescaped(tokens)
        if plain != tokens:
            _scan(" ".join(shlex_quote(item) for item in plain), systems, programs, depth + 1, found, variables, ctx) if depth < MAX_DEPTH else None
        tokens = _through_interpreter(tokens, programs)
        if depth < MAX_DEPTH:
            for token in tokens:
                for inner in (_substitutions(token) if "$(" in token else []):
                    _scan(inner, systems, programs, depth + 1, found, variables, ctx)
        start = _start(tokens, programs)
        owners = programs[_program(tokens[start])] if start is not None else []
        pinned = [one for one in owners if systems[one].get("pin") and not systems[one].get("broken")]  # a program whose type pins its calls to a connection (1.7.38, C13 F2)
        name = _owner(systems, [one for one in owners if one not in pinned], " ".join(tokens[start + 1:])) if start is not None else None
        if start is not None and name is None and pinned:
            name, seen = _pin_owner(systems, pinned, tokens[start + 1:])
            if name is None:
                held = _unpinned(systems, pinned, seen, tokens, start, ctx, variables)
                if held is not None:
                    found.append(held)
                continue
        blocked = _code_blocked(tokens, ctx)  # `python3 -c "..."` that names a word of `reach.code`: code the gate cannot judge
        if blocked is not None:
            found.append(blocked)
        if name is not None and _program(tokens[start]) in ctx.quiet and (not addresses_fit(systems[name], " ".join(tokens[start + 1:])) or _cut_short(tokens[start + 1:], ctx.line)):
            name = None  # a program that only an address makes a call (curl) names an address that is not the system's: the system does not own it (nor a call whose end the line cut off: below)
        if name is not None and systems[name].get("noconn"):  # 1.7.38 (C13 F2b): a program a tool pack declares and no connection lists
            held = _unconnected(systems[name], name, tokens, start, ctx, variables)
            if held is not None:
                found.append(held)
            continue
        if name is not None:
            system = systems[name]
            line = " ".join(tokens)  # the environment settings in front of the program say something too
            if system.get("blocked"):  # 1.7.38 (C13 F2): a program the gate cannot judge, listed so that it is not taken for a free one: refused, with what to do instead
                found.append(Action("", "none", DESTROY, _program(tokens[start]), " ".join(tokens), call=" ".join([_program(tokens[start])] + tokens[start + 1:]), zone="blocked", reason=messages.pick(system["blocked"])))
                continue
            target = ""
            if system.get("target"):
                match = re.search(system["target"], line, re.IGNORECASE)
                target = (match.group(1) if match and match.groups() else match.group(0) if match else "")[:120]
            if system.get("broken"):  # 1.7.38 (G-1): the pack's file is faulty, so the gate cannot judge this program: held, and the card says why
                caught = _broken_refusal(system, name, tokens, start, ctx, variables)
                if caught is not None:  # 1.7.38 (C13 FR 2): its type file can still be read, and a statement on the refuse list is refused, as it is when the pack is good
                    found.append(caught)
                    continue
                found.append(Action(name, "none", WRITE, "", " ".join(tokens), named=True, call=" ".join([_program(tokens[start])] + tokens[start + 1:]), zone="broken", note=str(system["broken"])))
                continue
            word = unknown_command(system, " ".join(tokens[start + 1:]))
            if word:  # the pack's own program has no such command: refused, with a line (the gate's `unknown` answer)
                found.append(Action(name, environment(system, line), WRITE, word[:120], " ".join(tokens), call=" ".join([_program(tokens[start])] + tokens[start + 1:]), why="command"))
                continue
            call = " ".join([_program(tokens[start])] + tokens[start + 1:])
            if system.get("reads"):  # 1.7.38: a type with lists: the statements are cut and judged by the lists, `verbs` only label the call
                found.append(_by_lists(system, name, environment(system, line), target, " ".join(tokens), call, tokens[start + 1:], ctx, tokens[:start] + [f"{key}={value}" for key, value in variables.items()]))  # a variable the line set before (`export SQLCMDINI=...;`) is a setting of this call too
                continue
            verb = verb_named(system, " ".join(tokens[start + 1:]))
            file, file_why = "", ""
            if ctx.root is not None and system.get("input"):  # 1.7.38, C12 RC-G1: the statements of `sqlcmd -i file` are in the file: judged as the same words in the line are
                read = inputfiles.read(system, tokens[start + 1:], ctx.root, ctx.folder, ctx.cwd, ctx.line or " ".join(tokens))
                if read is not None:
                    if read.named and not read.state and _line_writer(ctx.line or " ".join(tokens), read.named, ctx, set(clis(system))):
                        read.state = "twice"  # 1.7.38 (C13 F2): another command of the line may change the file: the call asks
                    verb = inputfiles.strictest([verb_named(system, read.rest), read.verb])
                    if read.state == "destroy":
                        verb, file, file_why = DESTROY, read.file, "destroy"
                    elif read.state:  # a file the gate cannot judge: the call is at least a write
                        verb = inputfiles.strictest([verb, WRITE])
                        file, file_why = (read.file, read.state) if verb == WRITE else ("", "")
            found.append(Action(name, environment(system, line), verb or WRITE, target, " ".join(tokens), named=verb is not None and file_why not in ("unread", "twice"), call=call, file=file, file_why=file_why))
            continue
        if start is not None:
            continue  # the program of a listed system, none of whose systems owns this call: judged, and nothing to hold
        evaluated = _evaluated(tokens)
        if evaluated and depth < MAX_DEPTH:  # `eval "<command>"`: the string is the call; the words are read as they were given and as eval joins them
            for inner in evaluated:
                _scan(inner, systems, programs, depth + 1, found, variables, ctx)
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
            before, ctx.as_alias = ctx.as_alias, wrapped[0]
            try:
                _scan(wrapped[1], systems, programs, depth + 1, found, variables, ctx)
            finally:
                ctx.as_alias = before
            continue
        checked = len(tokens)
        shelled = _shell_string(tokens) if depth < MAX_DEPTH else None
        if shelled is not None:
            for inner in shelled[1]:  # the words after `-c` as they were given, as the shell that gets them joins them, and without its escape (`shellwords.readings`): every reading is scanned, the strictest answer stands
                _scan(inner, systems, programs, depth + 1, found, variables, ctx)
            checked = shelled[0] + 1  # the command string was read as a command line
        if ctx.hold:
            _account(tokens[:checked], raw, names, feeds, ctx, found)
        if tokens and _name(tokens[0]) == "cd" and len(tokens) > 1:
            ctx.dirs.append(tokens[1])


# Programs that run the text they are given (1.7.38, C13 FR 20): on their input (a here-document, a here-string, a pipe, `-f -`), in a file (`make -f x`, the Makefile they find themselves, `at -f x`) or in their own
# words (`less +'!cmd'`, `awk 'BEGIN{system(...)}'`). They are no shell and no interpreter the gate has a reading for (`_is_interpreter`), and a governed program named in what they run was a call nobody judged: `make -f -
# <<EOF ... sqlcmd ... DROP ... EOF` dropped a table. The line is refused when the text of such a runner names a governed program: the way is to run the program itself. THIS LIST GROWS: put a runner here when one is found;
# the value is how it finds a file when it is given none (the names it looks for in the folder it runs in).
TEXT_RUNNERS = {
    "make": ("Makefile", "makefile", "GNUmakefile"), "gmake": ("Makefile", "makefile", "GNUmakefile"), "bmake": ("Makefile", "makefile"), "just": ("justfile", "Justfile", ".justfile"), "rake": ("Rakefile", "rakefile"),
    "ninja": ("build.ninja",), "tclsh": (), "wish": (), "expect": (), "m4": (), "awk": (), "gawk": (), "mawk": (), "nawk": (), "lua": (), "luajit": (), "php": (), "r": (), "rscript": (), "julia": (), "crontab": (), "at": (), "batch": (),
    "ed": (), "ex": (), "vi": (), "vim": (), "nvim": (), "emacs": (), "osascript": (), "cscript": (), "wscript": (), "mshta": (), "sqlite3": (), "psql": (), "gdb": (), "lldb": (), "ftp": (), "sftp": (), "telnet": (), "nc": (), "ncat": (),
    "cmake": (), "scons": (), "gradle": (), "mvn": (), "ant": (), "npm": (), "npx": (), "yarn": (), "pnpm": (), "swift": (), "go": (), "dotnet": (), "groovy": (), "scala": (), "kotlin": (), "deno": (), "bun": (), "tsx": (), "ts-node": (),
}
TEXT_RUNNERS.update({name: tuple(spec.get("files") or ()) for name, spec in buildtools.TOOLS.items()})  # (1.7.38, C13 FR2 2) the build tools: their default files are read in the folder the line is in (`buildtools.py`)
POSITIONAL_PROGRAM = frozenset("tclsh wish expect m4 lua luajit php julia rscript r crontab osascript cscript wscript mshta".split())  # a file word given to these is the text they run (to `awk`, `vim` and the build tools it is data or a target)
_FILE_OPTIONS = ("-f", "--file", "--makefile", "--justfile", "-file", "-c")  # the option that names the file to run (`make -f x`, `at -f x`)


def _segments_with_operators(text: str) -> List[Tuple[str, List[str]]]:
    """`split_segments` that also says how each command is joined to the one before: `|` (a pipe: it gets the output), or another operator (`;`, `&&`, `||`, a new line). `("", tokens)` for the first."""
    text = join_lines(text)
    out: List[Tuple[str, List[str]]] = []
    tokens: List[str] = []
    token: Optional[str] = None
    quote = ""
    current = ""  # the operator in front of the command being read
    run = ""  # the operator characters seen since the last command ended
    index = 0

    def end_token() -> None:
        nonlocal token, current, run
        if token is not None:
            if not tokens:
                current, run = run, ""
            tokens.append(token)
            token = None

    def end_segment() -> None:
        nonlocal tokens
        end_token()
        if tokens:
            out.append((current, tokens))
            tokens = []

    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'" and index + 1 < len(text) and text[index + 1] == '"':
            token = (token or "") + '"'
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            else:
                token = (token or "") + char
        elif char in "\"'":
            quote = char
            token = token or ""
        elif char in SEPARATORS:
            end_segment()
            run += char if char in "|&;\n" else ""
        elif char.isspace():
            end_token()
        else:
            token = (token or "") + char
        index += 1
    end_segment()
    cleaned: List[Tuple[str, List[str]]] = []
    for how, item in out:
        while item and item[0] in LEADING_KEYWORDS:
            item = item[1:]
        if item:
            cleaned.append(("|" if how in ("|", "|&") else how, item))
    return cleaned


def _runner_files(name: str, args: List[str]) -> List[str]:
    """The files a runner is told to run in its words: the value of its file option, a file it is given on its input (`< x`), and a plain word that may be a file; and, when it names none, the files it looks for itself."""
    files: List[str] = []
    for index, item in enumerate(args):
        if item in _FILE_OPTIONS and index + 1 < len(args):
            files.append(args[index + 1])
        elif item.startswith(("--file=", "--makefile=", "--justfile=")):
            files.append(item.split("=", 1)[1])
        elif item == "<" and index + 1 < len(args):
            files.append(args[index + 1])
        elif item.startswith("<") and not item.startswith("<<") and len(item) > 1:
            files.append(item[1:])
        elif name in POSITIONAL_PROGRAM and not item.startswith(("-", "+", "<", "$")) and ("/" in item or "." in item):
            files.append(item)
    return [item for item in files if item not in ("-", "/dev/stdin", "")] or (list(TEXT_RUNNERS.get(name, ())) if not any(item in _FILE_OPTIONS for item in args) else [])


_CD_HEADS = frozenset(["cd", "pushd", "chdir", "set-location", "sl", "push-location"])


def _after_cd(folders: List[str], tokens: List[str], at: int) -> List[str]:
    """The folders a line can be in after a `cd`: the ones before (the `cd` may fail) and each of them moved by the target. A target made at run time (`cd $X`, `cd -`) moves nothing."""
    words = [item for item in tokens[at + 1:] if item.lower() not in ("/d", "-l", "-p", "-e", "--")]
    target = words[0] if words else "~"
    if target.startswith(("$", "%", "-")) or "$(" in target or "`" in target:
        return folders
    moved = [buildtools._join(base, target) for base in folders]  # noqa: SLF001
    return list(dict.fromkeys(folders + moved))[:40]


def _start_folders(ctx: "_Ctx") -> List[str]:
    """The folders a command of the line can run in before the line changes any: the folder of the terminal and the root, moved by the `cd` the earlier commands of the line made (`ctx.dirs`)."""
    first = [os.path.abspath(ctx.cwd or ".")]
    if ctx.root is not None:
        first.append(os.path.realpath(str(ctx.root)))
    folders = list(dict.fromkeys(first))
    for target in ctx.dirs:
        folders = _after_cd(folders, ["cd", target], 0)
    return folders


def _runner_of(tokens: List[str], at: int) -> Tuple[str, List[str]]:
    """`(the runner, the words it is given)`: the program, or the tool a `python3 -m <module>` starts (`invoke`, `tox`, `nox`...)."""
    if _is_interpreter(tokens[at]):
        kind, index = _interp(tokens, at)
        if kind == "module" and index is not None and index < len(tokens):
            tool = buildtools.MODULES.get(tokens[index].split(".")[0].lower())
            if tool:
                return tool, tokens[index + 1:]
    return _program(tokens[at]), tokens[at + 1:]


def _shown_path(path: str, ctx: "_Ctx") -> str:
    """A file as the words of a refusal name it: from the root of the repository when it is inside it."""
    try:
        root = os.path.realpath(str(ctx.root)) if ctx.root is not None else ""
        real = os.path.realpath(path.split(" (script ")[0])
        if root and os.path.commonpath([real, root]) == root:
            return os.path.relpath(real, root).replace("\\", "/") + (" (script " + path.split(" (script ", 1)[1] if " (script " in path else "")
    except (ValueError, OSError):
        pass
    return path


def _text_runners(text: str, bodies: List[Tuple[str, bool]], names: List[str], ctx: "_Ctx", found: List[Action]) -> None:
    """The rule for a runner (`TEXT_RUNNERS`): what it is given to run (its own words, the text piped into it and the here-documents of that, the file it is told to run or finds itself) is read, and a governed program named
    in it makes the line refused, with the way (run the program itself). One refusal for the line. A build tool (`buildtools.py`: make, just, rake, ninja, task, npm run...) finds a file in the folder it runs in: the folder
    of the terminal, a folder of a `cd` that came before in the line, `-C dir`; the file is read there. A file of it that cannot be read holds the line."""
    if not names:
        return
    pairs = _segments_with_operators(text)
    owner: List[List[str]] = []  # the here-documents of each command, in the order the shell takes them
    queue = list(bodies)
    for _how, tokens in pairs:
        count = sum(1 for item in tokens if item.startswith("<<") and not item.startswith("<<<"))
        owner.append([queue.pop(0)[0] for _ in range(min(count, len(queue)))])
    folders = _start_folders(ctx)
    for index, (_how, tokens) in enumerate(pairs):
        at = _head_index(tokens)
        if at is None:
            continue
        if _program(tokens[at]) in _CD_HEADS:
            folders = _after_cd(folders, tokens, at)
            continue
        runner, words = _runner_of(tokens, at)
        if runner not in TEXT_RUNNERS:
            continue
        given = [" ".join(tokens[at + 1:])] + owner[index]
        back = index
        while back > 0 and pairs[back][0] == "|":  # what is piped in, and the here-documents of the commands that pipe it
            back -= 1
            given += [" ".join(pairs[back][1])] + owner[back]
        hit = _mentioned("\n".join(given), names)
        shown, unread = "", ""
        if not hit and runner in buildtools.TOOLS:
            read = buildtools.collect(runner, words, folders)
            for path, body in read.texts:
                program = _mentioned(body, names)
                if program:
                    hit, shown = program, _shown_path(path, ctx)
                    break
            unread = read.unreadable[0] if read.unreadable and not hit else ""
        elif not hit:
            for path in _runner_files(runner, tokens[at + 1:]):
                state, program = _file_state(path, names, ctx, folders)
                if state == "names":
                    hit, shown = program, path
                    break
        if hit:
            found.append(_hidden("runner_file" if shown else "runner", " ".join(tokens), program=hit, runner=runner, file=shown))
            return
        if unread:
            found.append(Action("", "none", WRITE, _shown_path(unread, ctx), " ".join(tokens), named=False, call=" ".join(tokens), unseen=True, why="file"))


def _head_name(tokens: List[str]) -> str:
    at = _head_index(tokens)
    return _program(tokens[at]) if at is not None else ""


def _head_is_interpreter(tokens: List[str]) -> bool:
    at = _head_index(tokens)
    return at is not None and _is_interpreter(tokens[at])


def _encoded(tokens: List[str]) -> bool:
    """PowerShell given an encoded command (`-EncodedCommand`, `-enc`, `-e`: any start of the word)."""
    at = _head_index(tokens)
    return at is not None and shellwords.encoded(tokens, at)


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
        maybe = path.startswith("?")
        path = path[1:] if maybe else path
        state, program = _file_state(path, names, ctx)
        if state == "names":
            hold(program)
            return
        if maybe:
            continue
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
        elif kind == "code" and index is not None:
            code = " ".join(tokens[index + 1:])
            if _EXEC_WORDS.search(code):  # (1.7.38, C13 FR2 3) a file the code only reads (`print(open('notes.md').read())`) is data; it is a program when the code runs what it loads
                files.extend("?" + one for one in _code_files(code))  # `python3 -c "exec(open('x.py').read())"`: the file is the program (1.7.38, C13 FR 20). A `?` says it may be data: no file, or none the gate can read, is no reason to hold the line
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


_EXEC_WORDS = re.compile(r"(?<![\w.])(?:exec|eval|compile|execfile|dofile|loadfile|require|source)\s*\(|\b(?:run_path|run_module|import_module|__import__|importlib|runpy|Invoke-Expression|iex|vm\.run\w+)\b|\bnew\s+Function\b", re.IGNORECASE)  # code that runs what it loads
_CODE_FILE = re.compile(r"""(?:\bopen|\brun_path|\bexecfile|\breadFileSync|\breadFile|\brequire|\bdofile|\bloadfile|\bGet-Content|\bgc|\bImport-Module)\s*\(?\s*(?:[A-Za-z_]+\s*=\s*)?['"]([^'"\n]{1,300})['"]""", re.IGNORECASE)


def _code_files(code: str) -> List[str]:
    """The files that the code of a one-liner opens by a name written in it (`open('x.py')`, `runpy.run_path('x.py')`, `readFileSync('x.js')`, `require('./x')`): when the code runs what it reads, they are its program. Best effort."""
    return [name for name in dict.fromkeys(_CODE_FILE.findall(code or "")) if "/" in name or "\\" in name or "." in name]  # a bare name (`require('fs')`) is a module, not a file


def _evaluated(tokens: List[str]) -> Optional[List[str]]:
    """The command lines `eval` is given, or None: its words as they were given and as `eval` joins them with spaces (a `;` inside one word stays inside it in the first reading, and splits in the second)."""
    head = _head(tokens)
    if head is None or _name(head) != "eval":
        return None
    return shellwords.readings(tokens[tokens.index(head) + 1:], "eval")


def _shell_string(tokens: List[str]) -> Optional[Tuple[int, List[str]]]:
    """`(index of the flag, the command lines the shell is given)` when this segment gives a shell a command line (`bash -c '...'`, `pwsh -Command '...'`, `pwsh -com '...'`, `cmd /c ...`, `ksh -c`); else None. See `gitcmd.shell_code`."""
    return shell_code(tokens)


def _wrapped(tokens: List[str]) -> List[str]:
    """The command lines this segment gives to a shell, to `eval`, to `harness as` or to `harness wait --run`: what the gate reads as a line of its own (`nested`)."""
    shelled = shell_code(tokens)
    if shelled:
        return shelled[1]
    evaluated = _evaluated(tokens)
    if evaluated:
        return evaluated
    wrapped = as_run(tokens)
    if wrapped:
        return [wrapped[1]] if wrapped[1].strip() else []
    waited = _wait_run(tokens)
    return [waited] if waited else []


def _too_deep(tokens: List[str], names: List[str]) -> Optional[Action]:
    """A wrapper (a shell with a command line, `eval`, `harness as`, `harness wait --run`) nested deeper than the gate reads, whose command line names a governed program: refused, never passed (1.7.38, C13 FR3). The command
    cannot be judged, and a program the gate cannot judge is not let through by being hidden under one more wrapper. A command line that names none is no call."""
    inner = "\n".join(_wrapped(tokens))
    hit = _mentioned(inner, names) if inner else ""
    return _hidden("deep", " ".join(tokens), program=hit) if hit else None


def nested(command: str, depth: int = 0) -> List[str]:
    """The command strings a shell is given inside a line (1.7.38, C13 F2): `bash -c '...'`, `pwsh -Command '...'`, `eval '...'`, `harness as x -- ...`, `harness wait --run '...'`, and the ones inside those. The gate
    judges each of them as it judges a bare line (the rules of the terminal too), so a call wrapped in `pwsh -Command` is no freer than the same call written alone. A shell given several words gives each reading of them (`shellwords.readings`)."""
    found: List[str] = []
    if depth >= MAX_DEPTH or not command.strip():
        return found
    text, _bodies = _heredocs(join_lines(command))
    for tokens in split_segments(text):
        for inner in _wrapped(tokens):
            found.append(inner)
            found.extend(nested(inner, depth + 1))
    return list(dict.fromkeys(found))


# Commands whose output is text the gate can read in the line (what they print is what stands in the line, or a file it reads): a shell that runs what they print is not a hidden call.
VISIBLE = frozenset(
    "echo printf cat type get-content gc tac head tail write-output write-host cd pushd popd export set unset true false : test [ [[ sleep wait pwd read local declare typeset readonly".split()
)
_IEX = frozenset(["iex", "invoke-expression"])
_START = frozenset(["start-process", "saps", "start"])


def _hidden(kind: str, call: str, **values: Any) -> Action:
    """A call of text the gate cannot read (1.7.38, C13 F2): refused with the way (write the command out in the line)."""
    return Action("", "none", DESTROY, "", call, call=call, zone="blocked", reason=messages.text(f"gate.external.hidden.{kind}", **values))


def _launched(segments: List[List[str]], programs: Dict[str, List[str]], found: List[Action]) -> None:
    """`Start-Process <program>`, and `iex "<program> ..."`, of a program a `direct_only` system lists (1.7.38, C13 F2c): a line of a computer where nothing else is read for names (`unseen` is off) still refuses them, as a direct call.
    An `iex` of text that names none of them (`iex "Write-Host hi"`) is left alone."""
    for tokens in segments:
        at = _head_index(tokens)
        if at is None or _program(tokens[at]) not in _START | _IEX:
            continue
        named = _mentioned(" ".join(tokens[at + 1:]), list(programs))
        if named:
            found.append(_hidden("iex" if _program(tokens[at]) in _IEX else "start", " ".join(tokens), program=named))
            return


def _hidden_in_line(segments: List[List[str]], text: str, programs: Dict[str, List[str]], feeds: bool, found: List[Action]) -> None:
    """The text of a line that runs what it is not shown (1.7.38, C13 F2): `iex`, text piped into a shell or an interpreter (`base64 -d | sh`), `source <(...)`, `Start-Process` of a program a system governs.
    `echo '...' | sh` and a here-document are read as before (their text is a word of the line). Each is refused: the way is to run the command itself."""
    for tokens in segments:
        at = _head_index(tokens)
        if at is None:
            continue
        name = _program(tokens[at])
        call = " ".join(tokens)
        if name in _IEX:
            found.append(_hidden("iex", call))
            return
        if name in _START:
            named = _mentioned(" ".join(tokens[at + 1:]), list(programs))
            if named:
                found.append(_hidden("start", call, program=named))
                return
    shells = [tokens for tokens in segments if _head_index(tokens) is not None and _is_interpreter(tokens[_head_index(tokens)]) and _family(tokens[_head_index(tokens)]) in ("shell", "power")]  # a shell, not python or node: what a program prints and a python reads is data to a person's eyes (K5)
    if feeds and any(_interp(tokens, _head_index(tokens))[0] == "stdin" for tokens in shells):
        for tokens in segments:
            at = _head_index(tokens)
            if at is None or _feeds_code(_without_redirects(tokens)) or _program(tokens[at]) in VISIBLE or all(_is_environment(item) for item in tokens):
                continue
            found.append(_hidden("pipe", " ".join(tokens)))
            return
    if feeds and "<(" in text and (shells or any(_head_name(tokens) in ("source", ".") for tokens in segments)):
        found.append(_hidden("pipe", text[:200]))


JSON_FLAG = "--json"  # the one option the command line takes anywhere: `cli.py` takes it away before it reads the other words
_CLI_MODULES = ("cli", "engine.cli", ".harness.engine.cli")


def _harness_words(tokens: List[str]) -> Optional[Tuple[int, List[str]]]:
    """`(where the harness command line starts in this segment, the words after it without `--json`)`: `harness`, `harness.cmd`, `.harness/bin/harness`, `cli.py`, `python3 .harness/engine/cli.py`, `python3 -m cli`; else None. The
    word may stand after any wrapper (`setsid harness as`, `nohup`, `env X=1`), but not among the words of a program that only reads them (`echo harness as x`, `grep harness as notes`): that is no call."""
    for index, token in enumerate(tokens):
        if _program(token) == "harness" or _name(token) == "cli.py" or (_is_interpreter(token) and _starts_cli(tokens, index)):
            at = _head_index(tokens)
            if at is not None and at < index and _data_only(tokens, at):
                return None
            if _is_interpreter(token) and not (_program(token) == "harness" or _name(token) == "cli.py"):
                _kind, module = _interp(tokens, index)
                return index, [word for word in tokens[(module or index) + 1:] if word != JSON_FLAG]
            return index, [word for word in tokens[index + 1:] if word != JSON_FLAG]
    return None


def _starts_cli(tokens: List[str], at: int) -> bool:
    """Does the command at `tokens[at]` start the command line of the harness (`harness`, `cli.py`, `python3 .harness/engine/cli.py`, `python3 -m cli`)?"""
    if _is_harness(tokens, at):
        return True
    if _is_interpreter(tokens[at]):
        kind, index = _interp(tokens, at)
        return kind == "module" and index is not None and index < len(tokens) and tokens[index].lower() in _CLI_MODULES
    return False


def _harness_sub(words: List[str]) -> Optional[Tuple[int, str]]:
    """`(where the sub-command is, the sub-command)`: the first word that is no option. `cli.py` is `argparse`: the options of the harness (`--short`, `--sh`, `--version`, `-h`, `--`) may stand before it, in any spelling of a start of
    them, so every word that starts with `-` is skipped (1.7.38, C13 FR3: it was only the word right after `harness`)."""
    for index, word in enumerate(words):
        if not word.startswith("-"):
            return index, word.lower()
    return None


def as_run(tokens: List[str]) -> Optional[Tuple[str, str]]:
    """(alias, the command) when this segment is `harness as <alias> -- <command>` (1.7.10); else None. Read as the command line does (`cli.py` uses argparse): with or without the `--`, the `--` before the alias, options of the harness
    before `as`, `python3 .harness/engine/cli.py`, `python3 -m cli`, in front of anything (`env X=1`, `bash -c`), and `--json` anywhere is taken away before the program sees its words (1.7.38, C13 FR3). The command is read more
    freely than it runs, never less: a shape that fails when it runs is still judged as the call it would have been."""
    found = _harness_words(tokens)
    if found is None:
        return None
    head, words = found
    sub = _harness_sub(words)
    if sub is None or sub[1] != "as":
        return None
    rest = words[sub[0] + 1:]
    at = next((index for index, word in enumerate(rest) if not word.startswith("-")), None)
    if at is None:
        return None
    command = rest[at + 1:]
    while command and command[0] == "--":  # argparse takes one `--` away and `run_as` another, and which of them does it depends on the Python: every `--` in front of the command is
        command = command[1:]
    settings = [item for item in tokens[:head] if _is_environment(item)]  # `SQLCMDINI=x harness as ...`: the settings stand before the program the command runs, as they do without the prefix
    return rest[at], " ".join(shlex_quote(item) for item in settings + command)  # 1.7.38 (C13 FR2 1): as the program is given its words (`run_as` joins them with quotes): a statement with a `;` or a space in one word stays one word


_WAIT_RUN_OPTIONS = ("--r", "--ru", "--run")  # argparse takes a start of an option that no other option starts with


def _wait_run(tokens: List[str]) -> Optional[str]:
    """The command(s) `harness wait` is given with `--run`, one to a line, when this segment is such a call (`harness`, `harness.cmd`, `cli.py`, with the options of the harness before `wait`, `--run=<command>`, `--ru`, the
    option twice: the program runs the last one, the gate reads all of them); else None."""
    found = _harness_words(tokens)
    if found is None:
        return None
    sub = _harness_sub(found[1])
    if sub is None or sub[1] != "wait":
        return None
    rest = found[1][sub[0] + 1:]
    values: List[str] = []
    for index, word in enumerate(rest):
        if word in _WAIT_RUN_OPTIONS and index + 1 < len(rest):
            values.append(rest[index + 1])
        else:
            values.extend(word[len(option) + 1:] for option in _WAIT_RUN_OPTIONS if word.startswith(option + "="))
    return "\n".join(values) if values else None


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
    direct = {program for system in systems.values() if system.get("direct_only") for program in clis(system)} - {program for system in systems.values() if not system.get("direct_only") for program in clis(system)} - quiet
    found: List[Action] = []
    context = _Ctx(root, cwd, hold=unseen, folder=folder, line=command)
    context.quiet = quiet
    context.direct = direct
    for name, system in systems.items():  # words a one-liner interpreter must not run (1.7.38, C13 F2)
        words = [str(one) for one in (system.get("reach") or {}).get("code") or []]
        if words and system.get("blocked"):
            context.code.append((re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(one) for one in words) + r")(?![\w])", re.IGNORECASE), name))
            context.reasons[name] = messages.pick(system["blocked"])
    _scan(command, systems, programs, 0, found, ctx=context)
    plain = shellwords.dialect(command, "power")  # 1.7.38 (C13 FR3): a line with a PowerShell escape in it (`` s`qlcmd ``) is also read with the escape taken away: that is what PowerShell runs. The strictest answer stands
    if plain:
        again = _Ctx(root, cwd, hold=unseen, folder=folder, line=plain)
        again.quiet, again.direct, again.code, again.reasons = context.quiet, context.direct, context.code, context.reasons
        _scan(plain, systems, programs, 0, found, ctx=again)
    return [(action, HUMAN if action.unseen else DENY if action.why == "command" or action.zone in ("refuse", "unpinned", "blocked") else decide(systems[action.system], action.env, action.verb)) for action in found if unseen or not action.unseen]


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
