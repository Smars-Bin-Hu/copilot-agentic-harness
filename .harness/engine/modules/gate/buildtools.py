"""Build tools: programs that run what a file of the project says (1.7.38, C13 FR2 2). Standard library only; the gate (`external.py`) calls it.

`make`, `just`, `rake`, `ninja`, `npm run`, `task`, `invoke`... find a file by themselves (`Makefile`, `justfile`, `package.json`, `Taskfile.yml`...) in the folder they run in, or in the one a `cd`, `-C` or `--directory` names, or
read the file their `-f` names. Whatever the file runs is a call the line does not show: `cd mk && make` ran a `sqlcmd` that was in `mk/Makefile` and nobody judged it. This module finds the texts such a call will read, so that
the gate can read them like it reads a script. THIS TABLE GROWS: put a tool here when one is found (`TOOLS`: its default files, the options that name a file or a folder, whether it looks in the folders above, what it
includes).

What is read: the default files of the tool in each folder the line can be in (the folder of the terminal and the folders of the `cd` that came before, with `-C` and its like added); the files named with `-f` and its like; the
files they include by a literal name; the scripts they run by a literal name (`bash run.sh`, `python3 tools/x.py`, `./run.sh`: one step, not the scripts of those); for `npm`, `pnpm`, `yarn` and `bun`, the scripts of
`package.json` that the command runs (and the ones those call). What is not read: a name made at run time (`include $(X)`, `npm run $S` is read as every script), a script that runs another script, a tool that finds its work in
another place (a plugin, a global config). `docs/12` says so."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_BYTES = 200 * 1024
MAX_FILES = 24
MAX_DEPTH = 4

_MAKE_INCLUDE = re.compile(r"^[ \t]*-?(?:s?include)[ \t]+(.+?)[ \t]*(?:#.*)?$", re.MULTILINE)
_MAKE = {"files": ("GNUmakefile", "makefile", "Makefile"), "file": ("-f", "--file", "--makefile"), "dir": ("-C", "--directory"), "include": _MAKE_INCLUDE}
_NINJA_INCLUDE = re.compile(r"^(?:subninja|include)[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_JUST_INCLUDE = re.compile(r"""^[ \t]*(?:import|mod\s+\w+)[ \t]+\??[ \t]*['"]([^'"]+)['"]""", re.MULTILINE)
_TASKFILES = ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml", "taskfile.yaml", "Taskfile.dist.yml", "Taskfile.dist.yaml")
_INVOKE = {"files": ("tasks.py", "tasks/__init__.py"), "file": ("-c", "--collection"), "dir": ("-r", "--search-root"), "up": True, "suffix": (".py", "/__init__.py")}

TOOLS: Dict[str, Dict[str, Any]] = {
    "make": _MAKE, "gmake": _MAKE, "bmake": dict(_MAKE, files=("makefile", "Makefile")), "pmake": dict(_MAKE, files=("makefile", "Makefile")), "mingw32-make": _MAKE,
    "nmake": {"files": ("Makefile",), "file": ("/f", "/F"), "dir": (), "include": _MAKE_INCLUDE},
    "just": {"files": ("justfile", "Justfile", ".justfile"), "file": ("-f", "--justfile"), "dir": ("-d", "--working-directory"), "up": True, "include": _JUST_INCLUDE},
    "rake": {"files": ("Rakefile", "rakefile", "Rakefile.rb", "rakefile.rb"), "file": ("-f", "--rakefile"), "dir": ("-C", "--directory"), "up": True},
    "ninja": {"files": ("build.ninja",), "file": ("-f",), "dir": ("-C",), "include": _NINJA_INCLUDE},
    "task": {"files": _TASKFILES, "file": ("-t", "--taskfile"), "dir": ("-d", "--dir"), "up": True},
    "invoke": _INVOKE, "inv": _INVOKE,
    "fab": {"files": ("fabfile.py", "fabfile/__init__.py"), "file": ("-f", "--fabfile"), "dir": (), "up": True},
    "doit": {"files": ("dodo.py",), "file": ("-f", "--file"), "dir": ("-d", "--dir")},
    "nox": {"files": ("noxfile.py",), "file": ("-f", "--noxfile"), "dir": ()},
    "tox": {"files": ("tox.ini", "pyproject.toml", "setup.cfg", "tox.toml"), "file": ("-c", "--conf"), "dir": ("--workdir", "--root")},
    "pdm": {"files": ("pyproject.toml",), "file": (), "dir": ("-p", "--project")},
    "hatch": {"files": ("pyproject.toml", "hatch.toml"), "file": (), "dir": ("-p", "--project")},
    "poe": {"files": ("pyproject.toml", "poe_tasks.toml"), "file": (), "dir": ("-C", "--directory", "--root")},
    "pipenv": {"files": ("Pipfile",), "file": (), "dir": ()},
    "composer": {"files": ("composer.json",), "file": (), "dir": ("-d", "--working-dir")},
    "gulp": {"files": ("gulpfile.js", "gulpfile.mjs", "gulpfile.cjs", "gulpfile.ts", "gulpfile.babel.js"), "file": ("--gulpfile",), "dir": ("--cwd",), "up": True},
    "grunt": {"files": ("Gruntfile.js", "gruntfile.js", "Gruntfile.coffee"), "file": ("--gruntfile",), "dir": ("--base",)},
    "mage": {"files": ("magefile.go", "magefiles/magefile.go"), "file": (), "dir": ("-d", "--dir")},
    "cmake": {"files": ("CMakeLists.txt",), "file": (), "dir": ("-S", "-H")},
    "scons": {"files": ("SConstruct", "Sconstruct", "sconstruct", "SConscript"), "file": ("-f", "--file", "--makefile", "--sconstruct"), "dir": ("-C", "--directory")},
    "gradle": {"files": ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"), "file": ("-b", "--build-file", "-c", "--settings-file"), "dir": ("-p", "--project-dir"), "up": True},
    "gradlew": {"files": ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"), "file": ("-b", "--build-file", "-c", "--settings-file"), "dir": ("-p", "--project-dir"), "up": True},
    "mvn": {"files": ("pom.xml",), "file": ("-f", "--file"), "dir": ()}, "mvnw": {"files": ("pom.xml",), "file": ("-f", "--file"), "dir": ()},
    "ant": {"files": ("build.xml",), "file": ("-f", "-file", "-buildfile"), "dir": ()},
    "sbt": {"files": ("build.sbt",), "file": (), "dir": ()},
    "deno": {"files": ("deno.json", "deno.jsonc"), "file": ("-c", "--config"), "dir": ()},
    "npm": {"package": True, "files": ("package.json",), "dir": ("--prefix", "-C", "--cwd")},
    "pnpm": {"package": True, "files": ("package.json",), "dir": ("-C", "--dir", "--prefix")},
    "yarn": {"package": True, "files": ("package.json",), "dir": ("--cwd",)},
    "bun": {"package": True, "files": ("package.json",), "dir": ("--cwd",)},
}
MODULES = {"invoke": "invoke", "nox": "nox", "tox": "tox", "doit": "doit", "poethepoet": "poe", "pdm": "pdm", "hatch": "hatch"}  # `python3 -m <module>` is the tool of that name

_SCRIPT_REF = re.compile(r"""(?:^|[\s;&|(@+=`$-])(?:(?:bash|sh|zsh|python3?|py|node|pwsh|powershell|ruby|perl)\s+(?:-[\w-]+\s+)*)?['"]?(\.{0,2}[\w./\\~-]*[\w-]\.(?:sh|bash|py|js|mjs|cjs|ps1|rb|pl))\b""", re.MULTILINE)
_CALLS_SCRIPT = re.compile(r"(?:^|[\s;&|(\"'`])(?:npm|pnpm|yarn|bun)\s+(?:run(?:-script)?\s+)?([\w:.@/-]+)|(?:^|[\s;&|(\"'`])(?:run-s|run-p|npm-run-all)\s+((?:[\w:.*-]+\s*)+)")
_RUN_WORDS = frozenset(["run", "run-script", "rum", "urn"])
_NPM_LIFECYCLE = ("preinstall", "install", "postinstall", "prepublish", "preprepare", "prepare", "postprepare", "prepack", "postpack", "prepublishOnly", "publish", "postpublish", "preversion", "version", "postversion")
_NPM_LIFECYCLE_COMMANDS = frozenset("install i add ci cit install-ci-test install-test it rebuild rb pack publish version".split())
_KNOWN_COMMANDS = {  # words that are no script name for `pnpm`, `yarn` and `bun` (they run the script of that name when the word is none of these)
    "pnpm": frozenset("add install i update up upgrade remove rm uninstall exec dlx create init link ln unlink list ls outdated why audit config set get patch prune rebuild store publish pack env server setup import deploy fetch dedupe doctor".split()),
    "yarn": frozenset("add install remove upgrade upgrade-interactive global workspace workspaces init link unlink list ls outdated why audit config cache info bin generate-lock-entry import licenses login logout owner pack publish tag team unplug version versions exec dlx create set plugin".split()),
    "bun": frozenset("add install i remove rm update upgrade pm link unlink x create init build test dev repl exec".split()),
}


def _read(path: str) -> Tuple[str, str]:
    """`(state, text)`: `ok` (a text, or a binary that has none to read), `missing` (no such file), `unreadable` (too big or not readable)."""
    if not os.path.isfile(path):
        return "missing", ""
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return "unreadable", ""
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return "unreadable", ""
    if b"\0" in data[:8000]:
        return "ok", ""
    return "ok", data.decode("utf-8", errors="replace")


def _join(base: str, name: str) -> str:
    name = os.path.expanduser(name.replace("\\", "/") if os.sep == "/" and not re.match(r"^[A-Za-z]:", name) else name)
    return os.path.normpath(os.path.join(base or ".", name))


def _values(args: List[str], names: Tuple[str, ...]) -> List[str]:
    """The values of an option in the words of a call, in order: `-C d`, `-Cd`, `--directory d`, `--directory=d`."""
    out: List[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        for name in names:
            if word == name and index + 1 < len(args):
                out.append(args[index + 1])
                index += 1
                break
            if name.startswith("--") and word.startswith(name + "="):
                out.append(word[len(name) + 1:])
                break
            if len(name) == 2 and name.startswith("-") and not name.startswith("--") and word.startswith(name) and len(word) > 2 and not word.startswith("--"):
                out.append(word[2:])
                break
        index += 1
    return out


def _folders(spec: Dict[str, Any], args: List[str], dirs: List[str]) -> List[str]:
    """The folders the call looks in: the ones the line can be in, moved by each folder option in turn; with `up`, the folders above them too."""
    current = list(dirs)
    for value in _values(args, tuple(spec.get("dir") or ())):
        if value and not value.startswith(("$", "%")) and "$(" not in value:
            current = list(dict.fromkeys(_join(base, value) for base in current)) or current
    if spec.get("up"):
        more: List[str] = []
        for base in current:
            parent = os.path.dirname(base)
            for _ in range(10):
                if not parent or parent == os.path.dirname(parent):
                    break
                more.append(parent)
                parent = os.path.dirname(parent)
        current = list(dict.fromkeys(current + more))
    return current


def _named_files(spec: Dict[str, Any], args: List[str], folders: List[str]) -> List[str]:
    out: List[str] = []
    for value in _values(args, tuple(spec.get("file") or ())):
        if value in ("-", "/dev/stdin", "") or value.startswith("$") or "$(" in value:
            continue
        for base in folders:
            for suffix in ("",) + tuple(spec.get("suffix") or ()):
                out.append(_join(base, value + suffix))
    return out


def _exact(path: str) -> bool:
    """Is there a file with exactly this name (a case-blind disk finds `Makefile` for `makefile`: one file, named as it is)?"""
    try:
        return os.path.basename(path) in os.listdir(os.path.dirname(path) or ".")
    except OSError:
        return False


def _default_files(spec: Dict[str, Any], folders: List[str]) -> List[str]:
    return [path for path in (_join(base, name) for base in folders for name in spec.get("files") or ()) if _exact(path)]


def _identity(path: str) -> Any:
    """The file itself (device and inode) when it exists, so a second name for it is read once; else its real path."""
    try:
        found = os.stat(path)
        return (found.st_dev, found.st_ino)
    except OSError:
        return os.path.realpath(path)


class Texts:
    """What a call of a build tool will read: `texts` are `(file shown, text)`, `unreadable` are files that exist and cannot be read (too big, no right)."""

    def __init__(self) -> None:
        self.texts: List[Tuple[str, str]] = []
        self.unreadable: List[str] = []
        self.seen: set = set()

    def add(self, path: str) -> Optional[str]:
        """Read a file once; the text, or None when it is missing, read before, or unreadable (then it is noted)."""
        real = _identity(path)
        if real in self.seen or len(self.seen) >= MAX_FILES:
            return None
        state, text = _read(path)
        if state == "missing":
            return None
        self.seen.add(real)
        if state == "unreadable":
            self.unreadable.append(path)
            return None
        self.texts.append((path, text))
        return text


def _follow(spec: Dict[str, Any], out: Texts, path: str, text: str, folders: List[str], depth: int) -> None:
    """The files a file includes by a literal name (`include x.mk`, `subninja x`, `import 'x.just'`)."""
    pattern = spec.get("include")
    if pattern is None or depth >= MAX_DEPTH:
        return
    for found in pattern.finditer(text):
        for group in found.groups():
            for word in (group or "").split():
                word = word.strip("'\"")
                if not word or any(char in word for char in "$%*?(){}"):
                    continue  # a name made at run time: not read (the limit is in the module's text)
                for base in [os.path.dirname(path)] + folders:
                    inner = _join(base, word)
                    body = out.add(inner)
                    if body is not None:
                        _follow(spec, out, inner, body, folders, depth + 1)
                        break
                    if inner in out.unreadable:
                        break


def _scripts_of(out: Texts, folders: List[str]) -> None:
    """The scripts the texts run by a literal name (`bash run.sh`, `python3 tools/x.py`, `./run.sh`): one step."""
    for path, text in list(out.texts):
        for found in _SCRIPT_REF.finditer(text):
            name = found.group(1)
            if not name or name.startswith(("-", "$")) or "$(" in name:
                continue
            for base in [os.path.dirname(path)] + folders:
                inner = _join(base, name)
                if os.path.isfile(inner):
                    out.add(inner)
                    break


def _nearest(base: str, name: str) -> str:
    """The nearest file of this name in the folder or the ones above it (what `npm run` finds); "" when there is none."""
    current = base
    for _ in range(40):
        path = os.path.join(current, name)
        if os.path.isfile(path):
            return path
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
    return ""


def _called(text: str, scripts: Dict[str, Any]) -> List[str]:
    """The scripts of `package.json` that this script text calls by name (`npm run build`, `yarn test`, `run-s a b`)."""
    names: List[str] = []
    for found in _CALLS_SCRIPT.finditer(text):
        if found.group(1):
            names.append(found.group(1))
        else:
            for item in (found.group(2) or "").split():
                names.extend(list(scripts) if "*" in item else [item])
    return names


def _package_scripts(tool: str, args: List[str], folders: List[str], out: Texts) -> None:
    """`npm run x`, `npm test`, `yarn x`, `pnpm run x`, `bun run x`: the scripts of the nearest `package.json` that the command runs, and the scripts those call by name."""
    spec = TOOLS[tool]
    skip = set(_values(args, tuple(spec.get("dir") or ()) + ("-w", "--workspace", "--filter", "-F")))
    words = [word for word in args if not word.startswith("-") and word not in skip]
    command = words[0] if words else ""
    wanted: Optional[List[str]] = []
    if tool == "npm":
        if command in _RUN_WORDS:
            wanted = [words[1]] if len(words) > 1 else []
        elif command in ("test", "t", "tst"):
            wanted = ["test"]
        elif command in ("start", "stop", "restart"):
            wanted = [command]
        elif command in _NPM_LIFECYCLE_COMMANDS:
            wanted = list(_NPM_LIFECYCLE)
    elif not command:
        wanted = list(_NPM_LIFECYCLE) if tool == "yarn" else []
    elif command in _RUN_WORDS or (tool == "pnpm" and command in ("-r", "recursive")):
        wanted = [words[1]] if len(words) > 1 else []
    elif command in ("install", "i", "add", "ci", "rebuild"):
        wanted = list(_NPM_LIFECYCLE)
    elif command not in _KNOWN_COMMANDS.get(tool, frozenset()) and not command.endswith((".ts", ".js", ".mjs", ".cjs", ".tsx", ".jsx")):
        wanted = [command]
    if not wanted:
        return
    unknown = any(name.startswith("$") or "$(" in name or "`" in name for name in wanted)  # a script named at run time: every script is read
    for start in _folders(dict(spec, up=False), args, folders):
        path = _nearest(start, "package.json")
        if not path or _identity(path) in out.seen:
            continue
        out.seen.add(_identity(path))
        state, text = _read(path)
        if state == "unreadable":
            out.unreadable.append(path)
            continue
        try:
            scripts = json.loads(text).get("scripts") or {}
            if not isinstance(scripts, dict):
                scripts = {}
        except (ValueError, AttributeError):
            out.texts.append((path, text))  # not JSON: the text itself is read like any other file
            continue
        chosen: List[str] = list(scripts) if unknown else []
        pending = [] if unknown else list(wanted)
        while pending and len(chosen) < 80:
            name = pending.pop(0)
            for each in (name, "pre" + name, "post" + name):
                if each in scripts and each not in chosen:
                    chosen.append(each)
                    pending.extend(_called(str(scripts[each]), scripts))
        for name in chosen:
            out.texts.append((f"{path} (script {name})", str(scripts[name])))
    _scripts_of(out, _folders(dict(spec, up=False), args, folders))


def collect(tool: str, args: List[str], dirs: List[str]) -> Texts:
    """The texts a call of `tool` with these words (after the program) will read, looked for in the folders `dirs` (absolute) the line can be in. Never raises."""
    out = Texts()
    spec = TOOLS.get(tool)
    if spec is None:
        return out
    try:
        if spec.get("package"):
            _package_scripts(tool, args, [item for item in dirs if item], out)
            return out
        folders = _folders(spec, args, [item for item in dirs if item])
        named = _named_files(spec, args, folders)
        for path in named or _default_files(spec, folders):
            text = out.add(path)
            if text is not None:
                _follow(spec, out, path, text, folders, 0)
        _scripts_of(out, folders)
    except Exception:  # noqa: BLE001 - the other checks of the gate stand; this one is best effort
        return out
    return out
