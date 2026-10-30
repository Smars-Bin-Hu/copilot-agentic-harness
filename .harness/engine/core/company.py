"""The company's own content: `<knowledge base>/company/`, kept apart from the harness so that a copy of the harness stays clean.

  company/company.json      { "skill_prefix": "<word>" }
  company/standards/        code-standards.md, read where it is (`standards.py`)
  company/skills/           `<prefix>-<name>/`, copied to `.github/skills/`: Copilot finds a skill there only
  company/instructions/     knowledgebase.instructions.md, copied to `.github/instructions/`, for the same reason
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

from . import approval, gitread, kbstd, messages, skillcheck, targets
from .paths import runtime_dir
from .registry import harness_version

CONFIG_FILE = "company.json"
MANIFEST_FILE = "manifest.json"
MANIFEST_PATH = f"{targets.COMPANY_DIR}/{MANIFEST_FILE}"
SKILLS_DIR = ".github/skills"
INSTRUCTIONS_DIR = ".github/instructions"
INSTRUCTION_FILES = ("knowledgebase.instructions.md",)  # one name only: a copy must never replace a file the harness ships for itself
NOT_CONTENT = {".git", ".DS_Store", "Thumbs.db"}
PLACEHOLDER = {"README.md", ".gitkeep"}  # what an empty knowledge base ships with
BACKUP_DIR = "company-backup"
SHOWN = 20
GIT_SECONDS = 60


class CompanyError(Exception):
    pass


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    if wanted and have and wanted != have:
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
    named = {item.name for item in skills}
    here = root / SKILLS_DIR
    only_here = sorted(item.name for item in here.glob(f"{have}-*") if item.is_dir() and item.name not in named) if have else []
    return {"pairs": pairs, "refused": refused, "only_here": only_here}


def same(source: Path, target: Path) -> bool:
    if source.is_dir():
        return target.is_dir() and digests(source) == digests(target)
    return target.is_file() and source.read_bytes() == target.read_bytes()


def sync(root: Path) -> Dict[str, Any]:
    folder = targets.company_folder(root)
    if folder is None:
        return {"found": False, "next": say("company.sync.none")}
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
    return {"found": True, "company": str(folder), "copied": done, "already_same": len(plan["pairs"]) - len(done), "refused": plan["refused"], "only_here": plan["only_here"],
            "next": say("company.sync.problems" if plan["refused"] else "company.sync.done"), "exit_code": 1 if plan["refused"] else 0}


def sync_after(root: Path) -> Optional[Dict[str, Any]]:
    """`sync` at the end of another command: a problem goes in that command's answer, it does not undo what was done."""
    try:
        found = sync(root)
    except (CompanyError, OSError) as error:
        return {"error": str(error)}
    found.pop("exit_code", None)
    return found if found["found"] else None


def drift(root: Path) -> Optional[Dict[str, Any]]:
    """For `doctor`: the copies that differ from the company content; None when there is no company content."""
    folder = targets.company_folder(root)
    if folder is None:
        return None
    try:
        plan = copies(root, folder)
    except CompanyError as error:
        return {"problem": str(error), "stale": [], "refused": []}
    return {"problem": "", "stale": [name for name, source, target in plan["pairs"] if not same(source, target)],
            "refused": [item["skill"] for item in plan["refused"]], "version": str(read_json(folder / MANIFEST_FILE).get("version") or "")}


# --- pack: the owner's zip ----------------------------------------------------------------------------------------------------------------------------------


def check_for_pack(root: Path, kb: Path) -> str:
    """The word of the company's skills, once what would go in the package passes the same checks a colleague's copy will run."""
    if not (kb / ".git").exists():
        raise CompanyError(say("company.pack.no_git", path=str(kb)))
    state = git(kb, "status", "--porcelain")
    if state.returncode != 0:
        raise CompanyError(say("company.git_failed", error=state.stderr.decode("utf-8", "replace").strip()))
    if state.stdout.strip():
        raise CompanyError(say("company.pack.dirty", path=str(kb)))
    word = skillcheck.usable(read_json(kb / targets.COMPANY_DIR / CONFIG_FILE).get("skill_prefix", ""))
    if not word:
        raise CompanyError(say("company.pack.no_word", path=f"{targets.COMPANY_DIR}/{CONFIG_FILE}"))
    source = kb / targets.COMPANY_DIR / "skills"
    bad = [item.name for item in sorted(source.iterdir()) if item.is_dir() and (not item.name.startswith(word + "-") or skillcheck.check(item, word)["errors"])] if source.is_dir() else []
    if bad:
        raise CompanyError(say("company.pack.bad_skills", names=", ".join(bad), word=word))
    errors = kbstd.check(root)["errors"]
    if errors:
        raise CompanyError(say("company.pack.kb_errors", count=errors))
    return word


def next_version(out: Path, word: str) -> str:
    today = time.strftime("%Y.%m.%d")
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
                package.writestr(name, data)
            package.writestr(MANIFEST_PATH, json.dumps(manifest, indent=2, sort_keys=True))
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
