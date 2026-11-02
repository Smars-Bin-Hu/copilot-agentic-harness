"""Get ready (1.6.57): what the page `/setup` shows and writes. No agent, no premium request.

Everything goes into the person's own `*.override.json`, next to what is already there. A broken file stops the write; nothing is overwritten. One wrong field: nothing is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import config, messages, shortcmd, standards, state as files, targets

MAX_NAME = 100
MAX_PATH = 1024
MAX_INSTALL = 500
GIT_WAIT = 5.0
GIT_RULE = ".git/**"
BRANCH_LINE = "ref: refs/heads/"
PREFIX = re.compile(r"[a-z][a-z0-9]{0,30}")


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def kept(root: Path, name: str) -> Dict[str, Any]:
    path = config.override_path(root, name)
    if not path.exists():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(say("setup.file.broken", file=str(path), error=error)) from None
    if not isinstance(found, dict):
        raise ValueError(say("setup.file.broken", file=str(path), error="not an object"))
    return found


def write(root: Path, name: str, values: Dict[str, Any]) -> None:
    found = kept(root, name)
    found.update(values)
    path = config.override_path(root, name)
    try:
        files.atomic_write(path, found)
    except OSError as error:
        raise ValueError(say("setup.file.nowrite", file=str(path), error=error.strerror or error)) from None


def git_name() -> str:
    try:
        done = subprocess.run(["git", "config", "--global", "user.name"], capture_output=True, text=True, timeout=GIT_WAIT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()[:MAX_NAME]


def clean_path(text: Any) -> str:
    value = str(text if text is not None else "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return os.path.expanduser(value)


def forced_language() -> str:
    """The language the environment sets, when it is one the harness has."""
    value = os.environ.get(messages.ENVIRONMENT, "").strip().lower()
    return value if value in messages.LANGUAGES else ""


def has_git(path: Path) -> bool:
    try:
        return (path / ".git").exists()
    except OSError:
        return False


def own_folders(root: Optional[Path]) -> Dict[Path, str]:
    """This harness and its knowledge base: never a code repository of its own. {folder: the message that says why}."""
    if root is None:
        return {}
    return {root.resolve(): "setup.repos.self", (root / targets.KB_DIR).resolve(): "setup.repos.kb"}


def repositories(text: Any) -> Dict[str, Any]:
    """What is in the folder of code repositories: `{ok, n, names, why}`. Read only. Empty: a person may set it later."""
    value = clean_path(text)
    if not value:
        return {"ok": True, "n": 0, "names": [], "why": ""}
    path = Path(value)
    if len(value) > MAX_PATH or "\x00" in value or not path.is_absolute():
        return {"ok": False, "n": 0, "names": [], "why": say("setup.repos.absolute")}
    if not path.is_dir():
        return {"ok": False, "n": 0, "names": [], "why": say("setup.repos.file" if path.is_file() else "setup.repos.missing")}
    try:
        names = sorted(item.name for item in path.iterdir() if targets.REPO_NAME.match(item.name) and has_git(item))
    except OSError as error:
        return {"ok": False, "n": 0, "names": [], "why": str(error)[:200]}
    return {"ok": True, "n": len(names), "names": names[:3], "why": "" if names else say("setup.repos.none")}


def add_repo(text: Any, root_text: Any = "", singles: Any = (), root: Optional[Path] = None) -> Dict[str, Any]:
    """What a path added to the code repositories is: one git repository, or a folder with the repositories to pick from. ValueError: why it cannot be added."""
    value = clean_path(text).rstrip("/\\") or clean_path(text)
    path = Path(value)
    if len(value) > MAX_PATH or "\x00" in value or not path.is_absolute():
        raise ValueError(say("setup.repos.absolute"))
    if not path.is_dir():
        raise ValueError(say("setup.repos.file" if path.is_file() else "setup.repos.missing"))
    own = own_folders(root)
    if path.resolve() in own:
        raise ValueError(say(own[path.resolve()]))
    base = clean_path(root_text)
    held = {Path(clean_path(item)).name for item in singles}
    if base and Path(base).is_dir():
        held |= {item.name for item in Path(base).iterdir() if has_git(item)}
    if not has_git(path):
        try:
            names = sorted((item.name for item in path.iterdir() if has_git(item) and targets.REPO_NAME.match(item.name)), key=str.lower)
        except OSError as error:
            raise ValueError(str(error)[:200]) from None
        if not names:
            raise ValueError(say("setup.repos.none"))
        rows = [{"name": name, "path": str(path / name), "held": name in held, **({"off": say("setup.repos.own")} if (path / name).resolve() in own else {"off": say("setup.repos.nocommit")} if head_branch(path / name) and not has_ref(path / name, head_branch(path / name)) else {})} for name in names]
        return {"kind": "folder", "path": value, "n": len(names), "names": names[:3], "repos": rows}
    if not targets.REPO_NAME.match(path.name):
        raise ValueError(say("setup.repos.name", name=path.name))
    if path.name in held:
        raise ValueError(say("setup.repos.twice", name=path.name))
    return {"kind": "repo", "name": path.name, "path": value}


def single_list(data: Dict[str, Any]) -> List[str]:
    found = data.get("singles")
    return [clean_path(item) for item in found] if isinstance(found, list) else []


def refused(root_text: Any, text: Any, singles: Any = ()) -> Dict[str, str]:
    """A path the agent must not touch, written whole, as the rule of its repository (`refused_paths` is relative to a repository). ValueError: why it cannot be one."""
    value = clean_path(text)
    base = clean_path(root_text)
    if not base and not singles:
        raise ValueError(say("setup.refused.first"))
    path = Path(value)
    if not value or not path.is_absolute():
        raise ValueError(say("setup.repos.absolute"))
    for item in singles:
        try:
            parts = path.relative_to(clean_path(item)).parts
        except ValueError:
            continue
        if parts:
            rule = "/".join(parts)
            return {"repo": Path(clean_path(item)).name, "rule": rule + "/**" if path.is_dir() else rule, "path": value}
    if not base:
        raise ValueError(say("setup.refused.inside"))
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        raise ValueError(say("setup.refused.outside", folder=base)) from None
    if len(parts) < 2 or not (Path(base) / parts[0] / ".git").exists():
        raise ValueError(say("setup.refused.inside"))
    rule = "/".join(parts[1:])
    return {"repo": parts[0], "rule": rule + "/**" if path.is_dir() else rule, "path": value}


def head_branch(path: Path) -> str:
    """The branch a repository is on. Read from the file: a folder of 300 repositories must not start 300 programs."""
    try:
        text = (path / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text[len(BRANCH_LINE):] if text.startswith(BRANCH_LINE) else ""


def has_ref(path: Path, name: str) -> bool:
    """Does the repository have this branch, local or of a remote? Read from the files. Cannot tell (a worktree): yes, and doctor checks it."""
    folder = path / ".git"
    if not folder.is_dir():
        return True
    wanted = [f"refs/heads/{name}", f"refs/remotes/{name}", f"refs/tags/{name}"]
    if any((folder / ref).is_file() for ref in wanted):
        return True
    try:
        packed = (folder / "packed-refs").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return False
    return any(ref in packed for ref in wanted)


def is_single(entry: Any) -> bool:
    """A repository added by itself: not one found in `repos_root`, and not a knowledge base."""
    return isinstance(entry, dict) and bool(str(entry.get("path") or "").strip()) and not entry.get("knowledge_base")


def short_state(root: Path) -> Dict[str, Any]:
    """Whether a new terminal finds the short command. It asks a login shell: the board keeps the answer a while."""
    path = shortcmd.fresh_path()
    found = shortcmd.found(path)
    return {"found": found, "command": "" if found else shortcmd.command_for(root, path), "windows": os.name == "nt"}


def stamp(root: Path) -> str:
    """Changes when what the form shows changes. Finish sends the one it opened with: what a terminal wrote meanwhile is not overwritten."""
    try:
        user, target, tools = kept(root, "user"), kept(root, "target"), kept(root, "tools")
    except ValueError:
        return ""
    shown = [user.get("name"), user.get("language"), user.get("skill_prefix"), target.get("repos_root"), target.get("repos"), (tools.get("python") or {}).get("install_command")]
    return hashlib.sha256(json.dumps(shown, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def rules_of(target: Dict[str, Any]) -> List[Dict[str, str]]:
    """The paths not to touch that the person's file holds. `.git/**` goes with every rule, so it is not one to choose."""
    return [{"repo": name, "rule": rule} for name, entry in sorted((target.get("repos") or {}).items()) if isinstance(entry, dict) and isinstance(entry.get("refused_paths"), list) for rule in entry["refused_paths"] if rule != GIT_RULE]


def kb_state(root: Path) -> Dict[str, Any]:
    """What is in place: the form says so, and does not ask for a knowledge base a person already has."""
    for _name, path in targets.knowledge_bases(root):
        if targets.knowledge_base_content(path):
            try:
                domains = sum(1 for item in (path / "domains").iterdir() if item.is_dir())
            except OSError:
                domains = 0
            found: Dict[str, Any] = {}
            try:
                found = json.loads((path / targets.COMPANY_DIR / "company.json").read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                pass
            return {"here": True, "domains": domains, "prefix": str(found.get("skill_prefix") or "").strip().lower() if isinstance(found, dict) else ""}
    return {"here": False, "domains": 0, "prefix": ""}


def status(root: Path, short: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the page needs. Reading a broken override file is told, not raised: the page must open to say so."""
    problem = ""
    user: Dict[str, Any] = {}
    target: Dict[str, Any] = {}
    tools: Dict[str, Any] = {}
    try:
        user, target, tools = kept(root, "user"), kept(root, "target"), kept(root, "tools")
    except ValueError as error:
        problem = str(error)
    singles = [str(entry["path"]) for entry in (target.get("repos") or {}).values() if is_single(entry)]
    forced = forced_language()
    return {"problem": problem, "name": str(user.get("name") or "") or git_name(), "language": forced or str(user.get("language") or messages.language()), "language_forced": bool(forced), "repos_root": str(target.get("repos_root") or ""), "root": repositories(target.get("repos_root")), "singles": singles, "broken": [path for path in singles if not has_git(Path(path))], "skill_prefix": str(user.get("skill_prefix") or ""),
            "install_command": str((tools.get("python") or {}).get("install_command") or ""), "rules": rules_of(target), "kb": kb_state(root), "stamp": stamp(root),
            "short": short_state(root) if short is None else short, "example": r"C:\Users\me\repos\orders\deploy" if os.name == "nt" else "/Users/me/repos/orders/deploy"}


def try_short(root: Path) -> Dict[str, Any]:
    """What the test button of the short command shows: its output, and on Windows whether hooks can run."""
    found = shortcmd.test(root)
    problem = shortcmd.python_problem()
    return {**found, "why": "" if found["ok"] else say("setup.short.bad"), "python": say("setup.python.stub") if problem == "stub" else say("setup.python.missing") if problem else ""}


def check(root: Path, data: Dict[str, Any]) -> None:
    """Every field, before anything is written. ValueError: all that is wrong."""
    name = " ".join(str(data.get("name") or "").split())
    language = str(data.get("language") or "").strip().lower()
    repos = repositories(data.get("repos_root"))
    wrong: List[str] = []
    if not name or len(name) > MAX_NAME:
        wrong.append(say("setup.name.need", limit=MAX_NAME))
    if language not in messages.LANGUAGES:
        wrong.append(say("setup.language.need"))
    if not repos["ok"]:
        wrong.append(repos["why"])
    held: List[str] = []
    for item in single_list(data):
        try:
            if add_repo(item, data.get("repos_root"), held, root)["kind"] != "repo":
                wrong.append(say("setup.repos.none"))
            held.append(item)
        except ValueError as error:
            wrong.append(f"{item}: {error}")
    for item in data.get("refused") if isinstance(data.get("refused"), list) else []:
        try:
            refused(data.get("repos_root"), item, single_list(data))
        except ValueError as error:
            wrong.append(f"{item}: {error}")
    if len(str(data.get("install_command") or "")) > MAX_INSTALL:
        wrong.append(say("setup.install.long", limit=MAX_INSTALL))
    now = stamp(root)
    if not now:
        try:
            kept(root, "user"), kept(root, "target"), kept(root, "tools")
        except ValueError as error:
            wrong.append(str(error))
    elif data.get("stamp") and data["stamp"] != now:
        wrong.append(say("setup.changed"))
    forced = forced_language()
    if forced and forced != language:
        wrong.append(say("serve.language.env", name=messages.ENVIRONMENT))
    mode = str(data.get("kb_mode") or "none")
    if mode not in ("none", "package", "folder"):
        wrong.append(say("setup.kb.mode"))
    elif mode != "none" and not clean_path(data.get("kb_path")):
        wrong.append(say("setup.kb.path"))
    prefix = str(data.get("skill_prefix") or "").strip()
    if prefix and not PREFIX.fullmatch(prefix):
        wrong.append(say("setup.prefix.bad"))
    if wrong:
        raise ValueError(" ".join(wrong))


def steps(root: Path, data: Dict[str, Any]) -> List[Tuple[str, Callable[[], str]]]:
    """The writes of the person's own files, in order. Each can be run again."""

    def user() -> str:
        name = " ".join(str(data.get("name") or "").split())
        write(root, "user", {"name": name, "skill_prefix": str(data.get("skill_prefix") or "").strip(), **({} if forced_language() else {"language": str(data.get("language")).strip().lower()})})
        return name

    def target() -> str:
        value = clean_path(data.get("repos_root"))
        singles = single_list(data)
        held = kept(root, "target")
        was = held.get("repos") or {}
        named = {clean_path(entry["path"]): name for name, entry in was.items() if is_single(entry)}  # a name a person gave stays: one path, one entry
        name_of = lambda path: named.get(path, Path(path).name)  # noqa: E731
        by_folder = {Path(path).name: name_of(path) for path in singles}
        rules: Dict[str, Any] = {}
        for path in data.get("refused") if isinstance(data.get("refused"), list) else []:
            found = refused(value, path, singles)
            rules.setdefault(by_folder.get(found["repo"], found["repo"]), {GIT_RULE}).add(found["rule"])
        repos = {name: dict(entry) for name, entry in was.items() if not is_single(entry) or clean_path(entry["path"]) in singles}  # one taken off the list on the page goes
        if not value and not singles and not was and not held.get("repos_root"):
            return say("setup.line.later")
        for path in singles:
            repos[name_of(path)] = {**(repos.get(name_of(path)) or {}), "path": path}
        if isinstance(data.get("rules"), list):  # the form shows every rule: the ones it no longer sends were taken off
            for entry in repos.values():
                entry.pop("refused_paths", None)
            for item in data["rules"]:
                rules.setdefault(str(item.get("repo")), {GIT_RULE}).add(str(item.get("rule")))
        inside = {item.name for item in Path(value).iterdir() if has_git(item)} if value and Path(value).is_dir() else set()
        for name, wanted in rules.items():
            if name in repos or name in inside:
                entry = dict(repos.get(name) or {})
                entry["refused_paths"] = sorted(set(entry.get("refused_paths") or []) | wanted)
                repos[name] = entry
        base = str(config.policy_or_empty(root, targets.POLICY_NAME).get("base_ref") or "main")
        for name in inside:  # a repository on another branch than the common one says which, or doctor stops the setup
            if "base_ref" not in (repos.get(name) or {}) and not has_ref(Path(value) / name, base) and head_branch(Path(value) / name):
                repos[name] = {**(repos.get(name) or {}), "base_ref": head_branch(Path(value) / name)}
        for path in singles:
            if "base_ref" not in repos[name_of(path)] and not has_ref(Path(path), base) and head_branch(Path(path)):
                repos[name_of(path)]["base_ref"] = head_branch(Path(path))
        repos = {name: entry for name, entry in repos.items() if entry and (str(entry.get("path") or "").strip() or name in inside)}  # an entry with no path lives in the folder: the folder went, so it goes too
        write(root, "target", {"repos_root": value, **({"repos": repos} if repos or was else {})})
        total = repositories(value)["n"] + len(singles)
        return say("setup.line.repos", n=total) if total else say("setup.line.later")

    def tools() -> str:
        python = dict(kept(root, "tools").get("python") or {})
        python.setdefault("interpreter", sys.executable)
        command = str(data.get("install_command") or "").strip()
        if command:
            python["install_command"] = command
        elif "install_command" in data:
            python.pop("install_command", None)  # the form shows it: an empty box takes it off
        write(root, "tools", {"python": python})
        return str(python["interpreter"])

    return [("user", user), ("target", target), ("tools", tools)]


SECTIONS = (("repos", "Target repositories"), ("kb", "Knowledge base"), ("instructions", "Company content"), ("skills", "Skills"), ("standards", "Code standards"), ("python", "Python packages"))  # the headings of docs/03-configure.md: a test holds them
CAN_DECLARE = ("skills", "standards")  # a team may have none of these


def no_such(root: Path) -> List[str]:
    """What the person said the team has none of."""
    try:
        found = kept(root, "user").get("none")
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def missing(root: Path) -> List[str]:
    """What the big warning of the board lists: repos, domains, instructions, skills, standards. Quick: a few file looks, nothing that runs."""
    user = {}
    try:
        user = kept(root, "user")
    except ValueError:
        pass
    declared = no_such(root)
    company = targets.company_folder(root)
    out: List[str] = []
    try:
        kb = {name for name, _path in targets.knowledge_bases(root)}
        if not [name for name in targets.load(root).repos if name not in kb]:
            out.append("repos")
    except Exception:  # noqa: BLE001 - a broken policy is doctor's to report
        out.append("repos")
    if not any(targets.knowledge_base_content(path) for _name, path in targets.knowledge_bases(root)):
        out.append("domains")
    if not (company and (company / "instructions" / "knowledgebase.instructions.md").is_file()):
        out.append("instructions")
    if not str(user.get("skill_prefix") or "").strip() and "skills" not in declared:
        out.append("skills")
    if not (company and (company / standards.COMPANY_FILE).is_file()) and "standards" not in declared:
        out.append("standards")
    return out


def declare(root: Path, key: Any, on: Any) -> List[str]:
    """`We have none` of the guide: it goes in `none` of `user.override.json`."""
    if key not in CAN_DECLARE:
        raise ValueError(say("serve.refused.request"))
    held = kept(root, "user").get("none")
    found = set(held if isinstance(held, list) else [])
    found.add(key) if on else found.discard(key)
    write(root, "user", {"none": sorted(found)})
    return sorted(found)


def guide(root: Path) -> Dict[str, Any]:
    """The explanation of each section, cut out of docs/03-configure.md: the page keeps no copy of it. A heading that moved shows no text; the test catches it first."""
    from modules.task import mdtree  # noqa: PLC0415 - a module of the board; core is imported by it

    try:
        text = (root / "docs" / "03-configure.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    parts = re.split(r"^## ", text, flags=re.M)
    found = {part.split("\n", 1)[0].strip(): part.split("\n", 1)[1] if "\n" in part else "" for part in parts[1:]}
    return {"sections": [{"key": key, "title": title, "blocks": mdtree.parse(found.get(title, ""))["blocks"], "can_declare": key in CAN_DECLARE} for key, title in SECTIONS], "missing": missing(root), "declared": no_such(root)}


def sample(root: Path) -> Dict[str, str]:
    """The example task of the empty board: `scenario.override.md` of the lesson if a team wrote one, else `scenario.md`. {} when the table cannot be read; the page then has no sample."""
    folder = root / ".github" / "skills" / "harness-rookie-quick-start" / "references"
    for name in ("scenario.override.md", "scenario.md"):
        try:
            text = (folder / name).read_text(encoding="utf-8")
        except OSError:
            continue
        rows = {cells[0].strip(): cells[1].strip() for cells in (line.strip().strip("|").split("|") for line in text.splitlines() if line.startswith("|")) if len(cells) >= 2}
        kind = rows.get("Kind", "").split("`")
        label = next((key for key in rows if key.startswith("Example prompt")), "")
        found = {"name": rows.get("Task name", "").strip("`"), "kind": kind[1] if len(kind) > 1 else "", "text": rows.get(label, "")}
        if all(found.values()):
            return found
    return {}
