"""The company's own content: `<knowledge base>/company/`, kept apart from the harness so that a copy of the harness stays clean.

  company/company.json      { "skill_prefix": "<word>" }
  company/standards/        code-standards.md, read where it is (`standards.py`)
  company/skills/           `<prefix>-<name>/`, copied to `.github/skills/`: Copilot finds a skill there only
  company/instructions/     knowledgebase.instructions.md, copied to `.github/instructions/`, for the same reason
  company/tools/            packs.json (`{"use": ["ado", ...]}`: the factory packs of `.harness/toolpacks/` this company turns on), packs/<name>/: a tool pack
                            the company wrote (core.toolpacks); both are read where they lie, and `sync` copies only their skills to `.github/skills/` (1.7.30);
                            connections.json (`{"connections": {...}}`), copied to `.harness/policies/connections.company.json` (1.7.17). These paths are fixed:
                            pack, update and sync count on them
                            computer.json (`{"ca_bundle": {host, proxy}, "tool_folders": [{label, hint}]}`), copied to `.harness/policies/computer.company.json` (1.7.31)
  company/manifest.json     what a package holds; made by `pack`, written last by `update`

`sync` makes the copies, and never touches any other file. `pack` makes a zip of what git has in the knowledge base;
`update` puts one in place, for a team with no git server to pull from. It keeps a copy of the files changed here first.
`update --apply` is for a person at a terminal.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from . import approval, gitread, kbstd, messages, skillcheck, standards, targets
from .paths import runtime_dir
from .registry import harness_version

CONFIG_FILE = "company.json"
MANIFEST_FILE = "manifest.json"
MANIFEST_PATH = f"{targets.COMPANY_DIR}/{MANIFEST_FILE}"
SKILLS_DIR = ".github/skills"
INSTRUCTIONS_DIR = ".github/instructions"
INSTRUCTION_FILES = ("knowledgebase.instructions.md",)  # one name only: a copy must never replace a file the harness ships for itself
TOOLS_DIR = "tools"
CONNECTIONS_FILE = "connections.json"
CONNECTIONS_COPY = ".harness/policies/connections.company.json"
COMPUTER_FILE = "computer.json"  # 1.7.31: the recipe for "This computer" (core.launchenv.recipe): CA bundle host and proxy, hints for the tool folders. No secret
COMPUTER_COPY = ".harness/policies/computer.company.json"
NOT_CONTENT = {".git", ".DS_Store", "Thumbs.db"}
PLACEHOLDER = {"README.md", ".gitkeep"}  # what an empty knowledge base ships with
BACKUP_DIR = "company-backup"
COPIES_LEDGER = "company-copies.json"  # in `.harness/runtime/`: the skills the last sync put in `.github/skills/`; with it a sync takes back a copy whose name the company has left (a new `skill_prefix`)
SHOWN = 20
DIFF_SHOWN = 200  # lines of `diff`; `total` has them all
GIT_SECONDS = 60


class CompanyError(Exception):
    pass


class BadSkills(CompanyError):
    """Company skills a package would not carry: each with its reason, so that the words say what to change."""

    def __init__(self, skills: List[str], word: str) -> None:
        super().__init__(say("company.pack.bad_skills", names="; ".join(skills), word=word))
        self.skills = skills


class DirtyError(CompanyError):
    """The knowledge base has changes git does not hold. The board lists them and offers to commit them."""

    def __init__(self, kb: Path, lines: Optional[List[str]] = None) -> None:
        super().__init__(say("company.pack.dirty", path=str(kb)))
        self.path = str(kb)
        self.lines = list(lines or [])


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_program(name: str) -> bool:
    """A file in the `bin/` of a tool pack the company wrote: `company/tools/packs/<pack>/bin/<file>`. It must run, so its zip entry says so (1.7.38)."""
    parts = PurePosixPath(name).parts
    return len(parts) >= 6 and parts[:3] == (targets.COMPANY_DIR, TOOLS_DIR, "packs") and parts[4] == "bin"


def zip_mode(kb: Path, name: str, data: bytes) -> int:
    """The mode a file gets in the package: 755 when the file runs here, or is a program of a company pack that starts with `#!` (a package made on Windows has no run bit to read), else 644."""
    try:
        runs = bool((kb / name).stat().st_mode & 0o111)
    except OSError:
        runs = False
    return 0o755 if runs or (is_program(name) and data[:2] == b"#!") else 0o644


def zip_entry(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix: the mode in `external_attr` counts
    info.external_attr = (mode & 0o777) << 16
    return info


def run_bit(path: Path) -> None:
    """Give a file the run bit where it can be read. Windows ignores it; a file that cannot be changed stays as it is."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode | ((mode & 0o444) >> 2))
    except OSError:
        pass


def restore_modes(kb: Path, package: zipfile.ZipFile, names: List[str]) -> None:
    """After a package is put in place: a file the package marks as one that runs gets its run bit (also when its content did not change), and so does a program of a company pack that starts with
    `#!` in a package that says nothing about modes (an older one). Without it the program cannot run on macOS or Linux (1.7.38)."""
    for name in names:
        path = kb / name
        if not path.is_file():
            continue
        info = package.getinfo(name)
        marked = info.create_system == 3 and bool((info.external_attr >> 16) & 0o111)
        if (marked or (is_program(name) and path.read_bytes()[:2] == b"#!")) and not path.stat().st_mode & 0o111:
            run_bit(path)


def digests(folder: Path) -> Dict[str, str]:
    """{path from the folder: hash} of its files, without git's folder and the files an OS leaves behind."""
    found: Dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if path.is_file() and not NOT_CONTENT.intersection(relative.parts):
            found[relative.as_posix()] = digest(path.read_bytes())
    return found


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise CompanyError(say("company.bad_file", path=str(path), error=error)) from None
    if not isinstance(data, dict):
        raise CompanyError(say("company.bad_file", path=str(path), error="not a JSON object"))
    return data


def git(folder: Path, *arguments: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(gitread.command(folder, arguments), capture_output=True, timeout=GIT_SECONDS, env=gitread.env(), check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise CompanyError(say("company.git_failed", error=error)) from None


# --- sync: the copies Copilot needs -------------------------------------------------------------------------------------------------------------------------


def copies(root: Path, folder: Path) -> Dict[str, Any]:
    """What the company content asks of `.github/`: `pairs` (name, source, target), `refused` (a skill not to copy, and why), `only_here` (ours, no longer in the content)."""
    wanted = str(read_json(folder / CONFIG_FILE).get("skill_prefix") or "")
    have = skillcheck.company_prefix(root)
    source = folder / "skills"
    skills = sorted(item for item in source.iterdir() if item.is_dir()) if source.is_dir() else []
    if skills and not have:
        raise CompanyError(say("company.no_prefix", word=wanted or "<word>"))
    if wanted and have and wanted.casefold() != have.casefold():  # `BNS` in the file and `bns` here are one word: the form of a word is the harness's, not the company's
        raise CompanyError(say("company.other_prefix", wanted=wanted, have=have))
    pairs: List[Tuple[str, Path, Path]] = []
    refused: List[Dict[str, str]] = []
    for item in skills:
        errors = skillcheck.check(item, have)["errors"]
        if not item.name.startswith(have + "-"):
            refused.append({"skill": item.name, "why": say("company.why.prefix", word=have)})
        elif errors:
            refused.append({"skill": item.name, "why": "; ".join(errors)})
        else:
            pairs.append((f"{SKILLS_DIR}/{item.name}", item, root / SKILLS_DIR / item.name))
    for name in INSTRUCTION_FILES:
        if (folder / "instructions" / name).is_file():
            pairs.append((f"{INSTRUCTIONS_DIR}/{name}", folder / "instructions" / name, root / INSTRUCTIONS_DIR / name))
    if (folder / TOOLS_DIR / CONNECTIONS_FILE).is_file():
        pairs.append((CONNECTIONS_COPY, folder / TOOLS_DIR / CONNECTIONS_FILE, root / CONNECTIONS_COPY))
    if (folder / TOOLS_DIR / COMPUTER_FILE).is_file():
        pairs.append((COMPUTER_COPY, folder / TOOLS_DIR / COMPUTER_FILE, root / COMPUTER_COPY))
    named = {item.name for item in skills}
    here = root / SKILLS_DIR
    from . import toolpacks  # the skills a tool pack put are not the company's content

    put = {skill for entry in toolpacks.ledger(root)["packs"].values() for skill in entry.get("skills") or []}
    only_here = sorted(item.name for item in here.glob(f"{have}-*") if item.is_dir() and item.name not in named and item.name not in put) if have else []
    # 1.7.38: a copy the last sync put under another word (the company changed `skill_prefix`) is taken back, with the same backup; a skill that is not in the ledger is none of our business
    left = sorted(name for name in ledger_names(root) if have and not name.startswith(have + "-") and name not in put and (here / name).is_dir())
    return {"pairs": pairs, "refused": refused, "only_here": sorted(set(only_here) | set(left))}


def ledger_names(root: Path) -> List[str]:
    """The skills the last sync put in `.github/skills/` (the company's own)."""
    try:
        found = json.loads((runtime_dir(root) / COPIES_LEDGER).read_text(encoding="utf-8"))
        return [str(name) for name in found.get("skills") or [] if isinstance(name, str) and name and "/" not in name]
    except (OSError, ValueError, AttributeError):
        return []


def write_ledger(root: Path, names: List[str]) -> None:
    names = sorted(dict.fromkeys(names))
    if names == sorted(ledger_names(root)):
        return
    try:
        target = runtime_dir(root) / COPIES_LEDGER
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"skills": names}, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # only the taking back of an old name needs it


def same(source: Path, target: Path) -> bool:
    if source.is_dir():
        return target.is_dir() and digests(source) == digests(target)
    return target.is_file() and source.read_bytes() == target.read_bytes()


def sync(root: Path, remove: bool = False) -> Dict[str, Any]:
    """Copy the content to `.github/`. `remove`: a skill of the company's word that left the content goes too, into the backup folder (a person asked for this sync; a sync at the end of another command removes nothing).
    1.7.38: a company pack in `company/tools/packs/` with the name of a factory pack stops the sync as a whole, before anything is copied, removed or written: `{found, failed: True, clashes, error, next, exit_code: 1}`.
    What the last good sync put stays as it was. The failure is read from the files each time (`toolpacks.clashes`), so there is nothing to clear once the pack is renamed."""
    from . import toolpacks  # it reads the policies this module's copies feed

    folder = targets.company_folder(root)
    if folder is None:
        packs = toolpacks.sync_skills(root)  # a folder added here for a trial still has skills to put
        return {"found": False, "next": say("company.sync.none"), **({"toolpacks": packs} if packs["lines"] or packs["put"] or packs["removed"] else {})}
    stop = toolpacks.clash_stop(root)
    if stop:
        return {"found": True, "failed": True, "company": str(folder), "copied": [], "clashes": toolpacks.clashes(root), "error": stop, "refused": [], "only_here": [], "already_same": 0, "next": stop, "exit_code": 1,
                "toolpacks": {"put": [], "removed": [], "updated": [], "refused": [], "unknown_use": [], "lines": toolpacks.clash_lines(root), "failed": True}}
    plan = copies(root, folder)
    done: List[str] = []
    for name, source, target in plan["pairs"]:
        if same(source, target):
            continue
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(*NOT_CONTENT))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        done.append(name)
    if remove and plan["only_here"]:
        backup = runtime_dir(root) / BACKUP_DIR / time.strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        for name in plan["only_here"]:
            shutil.move(str(root / SKILLS_DIR / name), str(backup / name))
            done.append(f"{SKILLS_DIR}/{name}")
        plan["only_here"] = []
    same_now = len(plan["pairs"]) - len(done)
    kept = [name for name in ledger_names(root) if (root / SKILLS_DIR / name).is_dir()]  # one that was taken back is gone from the folder now
    write_ledger(root, [Path(name).name for name, _source, _target in plan["pairs"] if name.startswith(SKILLS_DIR + "/")] + kept)
    packs = toolpacks.sync_skills(root)  # the skills of the active tool packs: put, renamed with the company's word, taken back, put again when the version changed
    done += [f"{SKILLS_DIR}/{name}" for name in packs["put"] + packs["removed"]]
    plan["refused"] += [{"skill": item["skill"], "why": item["why"]} for item in packs["refused"]]
    return {"found": True, "company": str(folder), "copied": done, "toolpacks": packs, "already_same": same_now, "refused": plan["refused"], "only_here": plan["only_here"],
            "next": " ".join([say("company.sync.problems" if plan["refused"] else "company.sync.done"), *([say("company.sync.only_here", names=", ".join(plan["only_here"]))] if plan["only_here"] else [])]), "exit_code": 1 if plan["refused"] else 0}


def sync_after(root: Path) -> Optional[Dict[str, Any]]:
    """`sync` at the end of another command: a problem goes in that command's answer, it does not undo what was done."""
    try:
        found = sync(root)
    except (CompanyError, OSError) as error:
        return {"error": str(error)}
    found.pop("exit_code", None)
    if found.get("failed"):  # the same shape as any other problem of a sync at the end of a command (1.7.38)
        return {"error": found["error"], "clashes": found.get("clashes") or []}
    return found if found["found"] or found.get("toolpacks") else None


def drift(root: Path) -> Optional[Dict[str, Any]]:
    """For `doctor`: the copies that differ from the company content; None when there is no company content."""
    folder = targets.company_folder(root)
    if folder is None:
        return None
    try:
        plan = copies(root, folder)
    except CompanyError as error:
        return {"problem": str(error), "stale": [], "refused": []}
    return {"problem": "", "stale": [name for name, source, target in plan["pairs"] if not same(source, target)] + [row["path"] for row in pack_changes(root)],
            "refused": [item["skill"] for item in plan["refused"]], "version": str(read_json(folder / MANIFEST_FILE).get("version") or "")}


def difference(name: str, source: Path, target: Path) -> List[Dict[str, str]]:
    """What a sync would do to one copy, file by file: `add`, `change` or `remove`."""
    if not source.is_dir():
        return [] if same(source, target) else [{"path": name, "change": "change" if target.exists() else "add"}]
    new, old = digests(source), digests(target) if target.is_dir() else {}
    return [{"path": f"{name}/{path}", "change": "add" if path not in old else "remove" if path not in new else "change"} for path in sorted(set(new) | set(old)) if new.get(path) != old.get(path)]


def pack_changes(root: Path) -> List[Dict[str, str]]:
    """What `sync` would do to the skills of the tool packs: a skill to put, to change, or to take back."""
    from . import toolpacks

    try:
        plan = toolpacks.skill_plan(root)
    except Exception:  # noqa: BLE001 - a broken pack must not stop the comparison
        return []
    out = [{"path": f"{SKILLS_DIR}/{final}", "change": "change" if (root / SKILLS_DIR / final).is_dir() else "add"} for final, _files, _origin, _name in plan["put"]]
    kept = {skill for entry in plan["entries"].values() for skill in entry["skills"]}
    return out + [{"path": f"{SKILLS_DIR}/{skill}", "change": "remove"} for _pack, skill in plan["drop"] if skill not in kept and (root / SKILLS_DIR / skill).is_dir()]


def wanted_prefix(folder: Path) -> str:
    """The word of `company.json`, in the form the harness takes; "" when it cannot be read."""
    try:
        return str(read_json(folder / CONFIG_FILE).get("skill_prefix") or "").strip().lower()
    except CompanyError:
        return ""


def diff(root: Path) -> Dict[str, Any]:
    """The company content against its copies, and what a sync would change. It reads files only, so the board can ask every 2 minutes.
    An instructions file taken out of the content cannot be seen: the copy then looks like the file the harness ships."""
    folder = targets.company_folder(root)
    if folder is None:
        return {"found": False, "in_sync": True, "changes": [], "total": 0, "refused": [], "problem": "", "next": say("company.sync.none")}
    from . import toolpacks

    stop = toolpacks.clash_stop(root)
    if stop:  # a sync would stop at once (1.7.38): the window says why instead of offering it
        return {"found": True, "in_sync": False, "changes": [], "total": 0, "refused": [], "problem": stop, "clashes": toolpacks.clashes(root), "next": stop}
    try:
        plan = copies(root, folder)
    except CompanyError as error:
        word, have = skillcheck.usable(wanted_prefix(folder)), skillcheck.company_prefix(root)
        problem = (say("company.prefix.board", word=word, have=have) if have else say("company.prefix.board.none", word=word)) if word else str(error)  # 1.7.38: "another one" only when there is one
        return {"found": True, "in_sync": False, "changes": [], "total": 0, "refused": [], "problem": problem, "fix": word, "next": str(error)}
    changes = [row for name, source, target in plan["pairs"] for row in difference(name, source, target)] + [{"path": f"{SKILLS_DIR}/{name}", "change": "remove"} for name in plan["only_here"]]
    changes += pack_changes(root)
    same_now = not changes and not plan["refused"]
    return {"found": True, "in_sync": same_now, "changes": changes[:DIFF_SHOWN], "total": len(changes), "refused": plan["refused"], "problem": "", "next": say("company.diff.same" if same_now else "company.diff.differs.one" if len(changes) == 1 else "company.diff.differs", count=len(changes))}


# --- pack: the owner's zip ----------------------------------------------------------------------------------------------------------------------------------


def listed_files(folder: Path) -> List[Path]:
    """The files right in a folder; none when it cannot be read."""
    try:
        return sorted(item for item in folder.iterdir() if item.is_file())
    except OSError:
        return []


def misplaced(kb: Path, word: str, wanted: str) -> List[str]:
    """Files in the usual places whose name has `word`, other than the one the harness reads, as paths inside the knowledge base: a person put it in the wrong place or spelled it another way."""
    places = (kb, kb / targets.COMPANY_DIR, (kb / wanted).parent)
    found = {item.relative_to(kb).as_posix() for place in places for item in listed_files(place) if word in item.name.casefold() and item.suffix.casefold() == ".md"}
    return sorted(found - {wanted})[:3]


def layout(kb: Path) -> List[Dict[str, Any]]:
    """How a knowledge base folder stands against the layout the harness reads, part by part: `{key, ok, count, text}`. A look at files; nothing runs and nothing is refused."""
    company = kb / targets.COMPANY_DIR
    domains = kb / "domains"
    try:
        count = sum(1 for item in domains.iterdir() if item.is_dir() and not item.name.startswith("."))
    except OSError:
        count = 0
    out: List[Dict[str, Any]] = [{"key": "domains", "ok": count > 0, "count": count, "text": say("setup.layout.domains", n=count) if count else say("setup.layout.domains.none")}]
    if not company.is_dir():
        out.append({"key": "company", "ok": False, "count": 0, "text": say("setup.layout.company.none")})
    guide = f"{targets.COMPANY_DIR}/instructions/{INSTRUCTION_FILES[0]}"
    near = misplaced(kb, "instructions", guide)
    if (kb / guide).is_file():
        out.append({"key": "instructions", "ok": True, "count": 1, "text": say("setup.layout.instructions")})
    elif near or company.is_dir():
        out.append({"key": "instructions", "ok": False, "count": 0, "text": say("setup.layout.moved", found=near[0], wanted=guide) if near else say("setup.layout.instructions.none", wanted=guide)})
    rules = f"{targets.COMPANY_DIR}/{standards.COMPANY_FILE}"
    near = misplaced(kb, "standard", rules)
    if (kb / rules).is_file():
        out.append({"key": "standards", "ok": True, "count": 1, "text": say("setup.layout.standards")})
    elif near or company.is_dir():
        out.append({"key": "standards", "ok": False, "count": 0, "text": say("setup.layout.moved", found=near[0], wanted=rules) if near else say("setup.layout.standards.none", wanted=rules)})
    if company.is_dir():
        out += skills_part(company)
        out += tools_part(company)
    return out


def tools_part(company: Path) -> List[Dict[str, Any]]:
    """The tools of a company pack (`tools/packs.json`, `tools/packs/`, `tools/connections.json`): how many packs and connections, or what is wrong. None is no fault: a team may reach no tool."""
    from . import toolpacks  # it reads what this module syncs

    base = company / toolpacks.COMPANY_PACKS
    packs = sorted(item for item in base.iterdir() if item.is_dir()) if base.is_dir() else []
    path = company / TOOLS_DIR / CONNECTIONS_FILE
    recipe = company / TOOLS_DIR / COMPUTER_FILE
    use_file = company / toolpacks.USE_FILE
    if not packs and not path.is_file() and not recipe.is_file() and not use_file.is_file():
        return []
    errors: List[str] = []
    if recipe.is_file():
        from . import launchenv

        try:
            for fault in launchenv.recipe_errors(json.loads(recipe.read_text(encoding="utf-8-sig"))):
                errors.append(f"{COMPUTER_FILE}: {fault}")
        except ValueError as error:
            errors.append(f"{COMPUTER_FILE}: {error}")
    for folder in packs:
        try:
            toolpacks.manifest(folder)
        except toolpacks.ToolpackError as error:
            errors.append(str(error))
    used: List[Any] = []
    if use_file.is_file():
        try:
            used = read_json(use_file).get("use") or []
            if not isinstance(used, list) or not all(isinstance(item, str) for item in used):
                raise ValueError("`use` is a list of pack names")
        except Exception as error:  # noqa: BLE001 - told here, in one line
            errors.append(f"{use_file.name}: {error}")
            used = []
    listed: Dict[str, Any] = {}
    if path.is_file():
        try:
            listed = read_json(path).get("connections") or {}
            if not isinstance(listed, dict):
                raise ValueError("`connections` is not an object")
        except Exception as error:  # noqa: BLE001 - told here, in one line
            errors.append(f"{CONNECTIONS_FILE}: {error}")
    if errors:
        return [{"key": "tools", "ok": False, "count": 0, "text": say("setup.layout.tools.bad", error=errors[0])}]
    return [{"key": "tools", "ok": True, "count": len(packs) + len(used) + len(listed), "text": say("setup.layout.tools", packs=len(packs) + len(used), n=len(listed))}]


def skills_part(company: Path) -> List[Dict[str, Any]]:
    """The company skills of a knowledge base: their word in `company.json`, and each folder under that word. No skills is no fault: a team may have none."""
    try:
        word = skillcheck.usable(str(read_json(company / CONFIG_FILE).get("skill_prefix") or "").strip().lower())
    except Exception:  # noqa: BLE001 - a broken file is told by the sync; here it is a word that is not there
        word = ""
    try:
        names = sorted(item.name for item in (company / "skills").iterdir() if item.is_dir() and not item.name.startswith("."))
    except OSError:
        names = []
    if not names:
        return []
    if not word:
        return [{"key": "skills", "ok": False, "count": 0, "text": say("setup.layout.skills.word", file=f"{targets.COMPANY_DIR}/{CONFIG_FILE}")}]
    other = [name for name in names if not name.startswith(word + "-")]
    if other:
        return [{"key": "skills", "ok": False, "count": len(names) - len(other), "text": say("setup.layout.skills.names", names=", ".join(other[:5]), word=word)}]
    return [{"key": "skills", "ok": True, "count": len(names), "text": say("setup.layout.skills", n=len(names))}]


def found_in_place(root: Path) -> List[str]:
    """What the board shows in green: the parts of the knowledge base in place that are right. Quick: a few file looks. Empty with no knowledge base."""
    for _name, path in targets.knowledge_bases(root):
        if targets.knowledge_base_content(path):
            return [item["text"] for item in layout(path) if item["ok"]]
    return []


def skill_trouble(folder: Path, word: str) -> str:
    """Why a company skill would not reach a colleague, with its name; "" when it would."""
    why = say("company.why.prefix", word=word) if not folder.name.startswith(word + "-") else next(iter(skillcheck.check(folder, word)["errors"]), "")
    return f"{folder.name}: {why.rstrip('. \u3002')}" if why else ""  # the message that holds the list ends with its own full stop


def changed_lines(status: bytes) -> List[str]:
    """The lines of `git status --porcelain` that count. A `__pycache__` is no change of a person's, and a package holds only what git has anyway."""
    return [line for line in status.decode("utf-8", "replace").splitlines() if line.strip() and "__pycache__" not in line and not line.endswith(".pyc")]


def check_for_pack(root: Path, kb: Path) -> str:
    """The word of the company's skills, once what would go in the package passes the same checks a colleague's copy will run."""
    if not (kb / ".git").exists():
        raise CompanyError(say("company.pack.no_git", path=str(kb)))
    state = git(kb, "status", "--porcelain")
    if state.returncode != 0:
        raise CompanyError(say("company.git_failed", error=state.stderr.decode("utf-8", "replace").strip()))
    dirty = changed_lines(state.stdout)
    if dirty:
        raise DirtyError(kb, dirty)
    word = skillcheck.usable(read_json(kb / targets.COMPANY_DIR / CONFIG_FILE).get("skill_prefix", ""))
    if not word:
        raise CompanyError(say("company.pack.no_word", path=f"{targets.COMPANY_DIR}/{CONFIG_FILE}"))
    source = kb / targets.COMPANY_DIR / "skills"
    bad = [why for why in (skill_trouble(item, word) for item in sorted(source.iterdir()) if item.is_dir()) if why] if source.is_dir() else []
    if bad:
        raise BadSkills(bad, word)
    errors = kbstd.check(root)["errors"]
    if errors:
        raise CompanyError(say("company.pack.kb_errors", count=errors))
    return word


def pack_check(root: Path) -> Dict[str, Any]:
    """The checks a package passes before it is made, with no folder chosen yet (1.7.38: the board checks first and asks where to put the file afterwards): nothing uncommitted, the skills,
    the form of the knowledge base. `{ok, word}`; the errors are those of `pack`."""
    folder = targets.company_folder(root)
    if folder is None:
        raise CompanyError(say("company.pack.none"))
    return {"ok": True, "word": check_for_pack(root, folder.parent)}


def commit_changes(root: Path) -> Dict[str, Any]:
    """Commit what is changed in the knowledge base, for the person who pressed Commit on the board (`git add -A`, one commit). `{committed, lines}`."""
    folder = targets.company_folder(root)
    if folder is None:
        raise CompanyError(say("company.pack.none"))
    kb = folder.parent
    if not (kb / ".git").exists():
        raise CompanyError(say("company.pack.no_git", path=str(kb)))
    state = git(kb, "status", "--porcelain")
    lines = changed_lines(state.stdout) if state.returncode == 0 else []
    if not lines:
        return {"committed": False, "lines": []}
    for arguments in (("add", "-A"), ("commit", "-q", "-m", "Update the knowledge base")):
        done = git(kb, *arguments)
        if done.returncode != 0:
            raise CompanyError(say("company.git_failed", error=(done.stderr or done.stdout).decode("utf-8", "replace").strip()[:300]))
    return {"committed": True, "lines": lines}


def next_version(out: Path, word: str) -> str:
    """The date and the minute (1.7.38): two packages of one day do not overwrite each other. Made in the same minute, the second gets `.2`."""
    today = time.strftime("%Y.%m.%d-%H%M")
    version, count = today, 1
    while (out / f"{word}-kb-{version}.zip").exists():
        count += 1
        version = f"{today}.{count}"
    return version


def pack(root: Path, raw_out: str) -> Dict[str, Any]:
    folder = targets.company_folder(root)
    if folder is None:
        raise CompanyError(say("company.pack.none"))
    kb = folder.parent
    out = Path(raw_out).expanduser()
    if not out.is_absolute() or not out.is_dir():
        raise CompanyError(say("company.pack.out", path=raw_out))
    if kb.resolve() == out.resolve() or kb.resolve() in out.resolve().parents:
        raise CompanyError(say("company.pack.out", path=raw_out))
    word = check_for_pack(root, kb)
    listed = git(kb, "ls-files", "-z")
    if listed.returncode != 0:
        raise CompanyError(say("company.git_failed", error=listed.stderr.decode("utf-8", "replace").strip()))
    names = sorted(name for name in listed.stdout.decode("utf-8").split("\0") if name and name != MANIFEST_PATH)
    linked = [name for name in names if (kb / name).is_symlink()]
    if linked:
        raise CompanyError(say("company.pack.links", names=", ".join(linked[:SHOWN])))
    version = next_version(out, word)
    target = out / f"{word}-kb-{version}.zip"
    manifest: Dict[str, Any] = {"schema_version": 1, "version": version, "made": time.strftime("%Y-%m-%d %H:%M"), "harness": harness_version(root), "skill_prefix": word, "files": {}}
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as package:
            for name in names:
                data = (kb / name).read_bytes()
                manifest["files"][name] = digest(data)
                package.writestr(zip_entry(name, zip_mode(kb, name, data)), data)
            package.writestr(zip_entry(MANIFEST_PATH, 0o644), json.dumps(manifest, indent=2, sort_keys=True))
    except OSError:
        target.unlink(missing_ok=True)
        raise
    return {"package": str(target), "version": version, "harness": manifest["harness"], "files": len(names), "next": say("company.pack.done")}


# --- update: a colleague's copy of the knowledge base from a zip ----------------------------------------------------------------------------------------------


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and "\\" not in name and ":" not in name and not path.is_absolute() and ".." not in path.parts and not NOT_CONTENT.intersection(path.parts)


def load(raw: str) -> Tuple[Path, Dict[str, Any]]:
    """The package and its manifest, every file checked against it: a bad zip stops here, before any file is touched."""
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise CompanyError(say("company.update.from", path=raw))
    try:
        with zipfile.ZipFile(path) as package:
            manifest = json.loads(package.read(MANIFEST_PATH).decode("utf-8"))
            files = manifest["files"]
            if set(package.namelist()) != set(files) | {MANIFEST_PATH} or not all(safe_name(name) for name in files):
                raise ValueError("the files do not match the manifest")
            for name, wanted in files.items():
                if digest(package.read(name)) != wanted:
                    raise ValueError(f"{name} is damaged")
            str(manifest["version"])
    except (OSError, KeyError, TypeError, AttributeError, ValueError, zipfile.BadZipFile) as error:
        raise CompanyError(say("company.update.bad_zip", path=str(path), error=error)) from None
    return path, manifest


def target_kb(root: Path) -> Path:
    """Where a package goes: the knowledge base with company content, else the first one there is."""
    folder = targets.company_folder(root)
    if folder is not None:
        return folder.parent
    return next((path for _name, path in targets.knowledge_bases(root) if path.is_dir()), root / targets.KB_DIR)


def compare(kb: Path, files: Dict[str, str]) -> Dict[str, List[str]]:
    """`new`, `changed`, `removed`: what the package does to the knowledge base. `local`: files someone changed here since the last package."""
    here = digests(kb) if kb.is_dir() else {}
    here.pop(MANIFEST_PATH, None)
    was = read_json(kb / MANIFEST_PATH).get("files") or {}
    empty = not was and set(here) <= PLACEHOLDER
    return {
        "new": sorted(name for name in files if name not in here),
        "changed": sorted(name for name in files if name in here and here[name] != files[name]),
        "removed": sorted(name for name in here if name not in files),
        "local": [] if empty else sorted(name for name, value in here.items() if value != files.get(name) and value != was.get(name)),
    }


def commit(kb: Path, version: str) -> bool:
    """The knowledge base is a repository a task writes back to: it stays clean, on its base branch."""
    if not (kb / ".git").exists():
        return False
    return git(kb, "add", "-A").returncode == 0 and git(kb, "commit", "-q", "-m", f"Company package {version}").returncode == 0


def apply_package(root: Path, kb: Path, path: Path, manifest: Dict[str, Any], change: Dict[str, List[str]]) -> Optional[Path]:
    backup = None
    if change["local"]:
        backup = runtime_dir(root) / BACKUP_DIR / time.strftime("%Y%m%d-%H%M%S")
        for name in change["local"]:
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(kb / name, backup / name)
    with zipfile.ZipFile(path) as package:
        for name in change["new"] + change["changed"]:
            (kb / name).parent.mkdir(parents=True, exist_ok=True)
            (kb / name).write_bytes(package.read(name))
        restore_modes(kb, package, sorted(manifest["files"]))  # before the commit below: the run bit is part of the version
        for name in change["removed"]:
            (kb / name).unlink()
        for folder in sorted((item for item in kb.rglob("*") if item.is_dir() and ".git" not in item.relative_to(kb).parts), key=lambda item: len(item.parts), reverse=True):
            if not any(folder.iterdir()):
                folder.rmdir()
        (kb / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
        (kb / MANIFEST_PATH).write_bytes(package.read(MANIFEST_PATH))  # last: a run that stopped halfway can simply be run again
    return backup


def update(root: Path, raw: str, apply: bool = False, interactive: Optional[bool] = None) -> Dict[str, Any]:
    if apply:
        try:
            approval.require_person("company update --apply", interactive, typed=False)
        except approval.Refused as error:
            raise CompanyError(str(error)) from error
    path, manifest = load(raw)
    kb = target_kb(root)
    if kb.resolve() in path.resolve().parents:
        raise CompanyError(say("company.update.from", path=raw))
    change = compare(kb, manifest["files"])
    result: Dict[str, Any] = {"package": str(path), "version": manifest["version"], "made": manifest.get("made", ""), "tested_on_harness": manifest.get("harness", ""), "this_harness": harness_version(root), "knowledge_base": str(kb),
                              "skill_prefix": manifest.get("skill_prefix", ""), "new": len(change["new"]), "changed": len(change["changed"]), "removed": len(change["removed"]), "changed_here": change["local"][:SHOWN], "changed_here_count": len(change["local"])}
    if not apply:
        result.update(next=say("company.update.dry"), _next_person=say("company.update.person"))
        return result
    backup = apply_package(root, kb, path, manifest, change)
    result.update(backup=str(backup) if backup else "", committed=commit(kb, str(manifest["version"])), synced=sync_after(root), next=say("company.update.done"))
    return result
