"""`cli.py doctor`: check that registry, files, hook config, policies and tool kinds agree."""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from core import config, kbstd, messages, output, render, skillcheck, standards, targets, tasks, user
from core.logs import read_lines, session_files
from core.paths import cli_command, policies_dir, python_command
from core.registry import load_registry
from core.state import TRACKED_EVENTS


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)

HOOK_ENTRY = ".harness/engine/hook.py"
COMMAND_KEYS = ("command", "windows", "linux", "osx", "bash", "powershell")
KB_DIR = "knowledge-base"
BROAD_APPLY_TO = {"**", "**/*", "*", "**/**"}
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
SHOWN_BROKEN_LINKS = 5
TOOL_KINDS = {"read", "edit", "create", "terminal", "search", "subagent", "mcp", "web", "skill", "meta"}
INTERPRETER_SECONDS = 15
RECENT_LOG_FILES = 20  # the hook self-check reads only the newest session logs
STALE_HOOK_DAYS = 7
SLOW_GATE_SHARE = 0.5  # of the PreToolUse timeout: the SDK engine lets a call through when the hook times out
DEFAULT_HOOK_TIMEOUT = 30


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.lines: List[str] = []

    def ok(self, message: str) -> None:
        self.lines.append(f"[OK]    {message}")

    def warn(self, message: str) -> None:
        self.lines.append(f"[WARN]  {message}")

    def error(self, message: str) -> None:
        self.errors += 1
        self.lines.append(f"[ERROR] {message}")


def check_python(report: Report) -> None:
    version = sys.version_info
    text = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 9):
        report.ok(f"Python {text}")
    else:
        report.error(say("doctor.python.old", version=text))


def check_interpreter(report: Report) -> None:
    """The launcher and the hook start `python` (Windows) or `python3` (elsewhere). It has to run, not only be found.

    In a Copilot (SDK) session a hook that cannot start counts as a refusal: every tool call is denied (P2, 2026-10-10).
    """
    name = python_command()
    consequence = say("doctor.interpreter.consequence")
    found = shutil.which(name)
    if not found:
        report.error(say("doctor.interpreter.missing", name=name, consequence=consequence))
        return
    try:
        result = subprocess.run([found, "-c", "print(1)"], capture_output=True, text=True, timeout=INTERPRETER_SECONDS)
        problem = "" if result.returncode == 0 and result.stdout.strip() == "1" else say("doctor.interpreter.exit", code=result.returncode)
    except Exception as error:
        problem = f"{type(error).__name__}"
    if problem:
        report.error(say("doctor.interpreter.broken", name=name, found=found, problem=problem, consequence=consequence))
    else:
        report.ok(say("doctor.interpreter.ok", name=name))


def hook_timeout(root: Path) -> float:
    """The PreToolUse timeout of the hook config, in seconds. The default when the config cannot be read."""
    try:
        path = sorted((root / ".github" / "hooks").glob("*.json"))[0]
        entry = config.read_json(path)["hooks"]["PreToolUse"][0]
        return float(entry.get("timeoutSec") or entry.get("timeout") or DEFAULT_HOOK_TIMEOUT)
    except Exception:
        return float(DEFAULT_HOOK_TIMEOUT)


def recent_calls(root: Path) -> List[Dict[str, Any]]:
    """The rows of the newest session logs, oldest first."""
    files = sorted((path for _surface, path in session_files(root)), key=lambda path: path.stat().st_mtime)[-RECENT_LOG_FILES:]
    rows = [row for path in files for row in read_lines(path) if isinstance(row.get("at"), str)]
    return sorted(rows, key=lambda row: row["at"])


def days_since(at: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() / 86400
    except (TypeError, ValueError):
        return 0.0


def check_hook_activity(report: Report, root: Path, registry: Dict[str, Any]) -> None:
    """Is the hook really being called? The config can be right while the hook never runs (hooks switched off,
    an engine that ignores the file). The session logs are the only proof, so this needs the observe module."""
    entry = registry["modules"].get("observe")
    if entry is None or not entry["enabled"]:
        return
    try:
        rows = recent_calls(root)
    except Exception as error:
        report.warn(say("doctor.hook.logs_unreadable", error=error))
        return
    hint = say("doctor.hook.hint")
    if not rows:
        report.warn(say("doctor.hook.never", hint=hint))
        return
    last = rows[-1]
    age = days_since(last["at"])
    when = last["at"][:16].replace("T", " ") + " UTC"
    if age > STALE_HOOK_DAYS:
        report.warn(say("doctor.hook.stale", when=when, days=int(age), hint=hint))
    else:
        report.ok(say("doctor.hook.last", when=when))
    engines = [row.get("engine") for row in rows if row.get("event") == "PreToolUse" and row.get("engine") in ("cli", "legacy")]
    if engines and engines[-1] == "legacy":
        report.warn(say("doctor.hook.local"))
    elif engines:
        report.ok(say("doctor.hook.sdk"))
    gate = [float(row["ms"]) for row in rows if row.get("event") == "PreToolUse" and isinstance(row.get("ms"), (int, float))]
    if not gate:
        return
    timeout = hook_timeout(root)
    slowest = max(gate) / 1000
    middle = sorted(gate)[len(gate) // 2]
    text = say("doctor.gate.speed", count=len(gate), middle=f"{middle:.0f}", slowest=f"{max(gate):.0f}", timeout=f"{timeout:.0f}")
    if slowest >= timeout * SLOW_GATE_SHARE:
        report.warn(say("doctor.gate.slow", text=text))
    else:
        report.ok(text)


def launcher_files(root: Path) -> List[Path]:
    return [root / ".harness" / "bin" / name for name in ("harness", "harness.cmd")]


def same_launcher(found: Path, root: Path) -> bool:
    """A copy of this repository's launcher (a fixed folder in PATH holds one): the same name, the same bytes."""
    mine = root / ".harness" / "bin" / found.name
    try:
        return found.name in ("harness", "harness.cmd") and mine.is_file() and found.read_bytes() == mine.read_bytes()
    except OSError:
        return False


def check_short_command(report: Report, root: Path) -> None:
    """Every command an agent is told to run starts with `harness`: it has to be in PATH (a required setup step)."""
    found = shutil.which(cli_command())
    if not found:
        folder = root / ".harness" / "bin"
        report.error(say("doctor.short.missing", folder=folder, launcher=folder / "harness"))
        return
    try:
        resolved = Path(found).resolve()
        mine = any(resolved == path.resolve() for path in launcher_files(root))
    except OSError:
        resolved, mine = Path(found), False
    if mine:
        report.ok(say("doctor.short.ok", found=found))
    elif same_launcher(resolved, root):
        report.ok(say("doctor.short.copy", found=found))
    else:
        report.warn(say("doctor.short.other", resolved=resolved))


def check_files(report: Report, root: Path, owner: str, files: List[str]) -> None:
    missing = [name for name in files if not (root / name).exists()]
    for name in missing:
        report.error(say("doctor.files.missing", owner=owner, name=name))
    if not missing:
        report.ok(say("doctor.files.ok", owner=owner, count=len(files)))


def interpreter_problems(entry: Dict[str, Any]) -> List[str]:
    """The config carries two sets of keys: `command`/`windows`, and `bash`/`powershell` which a Copilot (SDK) session reads.

    An engine that finds no key for its system runs the wrong one, and a hook that fails to start counts as a deny:
    every tool call is refused. Windows has `python` and often no `python3`.
    """
    problems = []
    for key, interpreter in (("command", "python3"), ("bash", "python3"), ("windows", "python"), ("powershell", "python")):
        value = entry.get(key)
        if not isinstance(value, str):
            problems.append(say("doctor.hookcfg.key_missing", key=key, system="Windows" if interpreter == "python" else "macOS/Linux", engine="VS Code" if key in ("command", "windows") else say("doctor.hookcfg.engine.sdk")))
        elif value.split()[0] != interpreter:
            problems.append(say("doctor.hookcfg.key_wrong", key=key, interpreter=interpreter, found=value.split()[0]))
    return problems


def check_hook_config(report: Report, root: Path, registry: Dict[str, Any]) -> None:
    directory = root / ".github" / "hooks"
    configs = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not configs:
        report.error(say("doctor.hookcfg.none"))
        return
    if len(configs) > 1:
        names = ", ".join(path.name for path in configs)
        report.error(say("doctor.hookcfg.many", count=len(configs), names=names))
    configured: Set[str] = set()
    for path in configs:
        try:
            data = config.read_json(path)
            hooks = data["hooks"]
        except Exception as error:
            report.error(say("doctor.hookcfg.unparsable", name=path.name, error=error))
            continue
        for event, entries in hooks.items():
            configured.add(event)
            for entry in entries:
                commands = [entry[key] for key in COMMAND_KEYS if isinstance(entry.get(key), str)]
                if not commands or any(HOOK_ENTRY not in command for command in commands):
                    report.error(say("doctor.hookcfg.wrong_entry", name=path.name, event=event, entry=HOOK_ENTRY))
                for problem in interpreter_problems(entry):
                    report.error(say("doctor.hookcfg.problem", name=path.name, event=event, problem=problem))
    needed: Set[str] = set(TRACKED_EVENTS)
    for name, entry in registry["modules"].items():
        if entry["enabled"] and entry["status"] != "retired":
            needed.update(entry["events"])
    for event in sorted(needed - configured):
        report.error(say("doctor.hookcfg.event_missing", event=event))
    for event in sorted(configured - needed):
        report.warn(say("doctor.hookcfg.event_unused", event=event))
    if configured >= needed:
        report.ok(say("doctor.hookcfg.ok", count=len(configured & needed)))


def check_module(report: Report, root: Path, name: str, entry: Dict[str, Any]) -> None:
    if entry["status"] == "retired":
        return
    check_files(report, root, say("doctor.module.owner", name=name), entry["files"])
    try:
        module = importlib.import_module(f"modules.{name}")
        if not callable(getattr(module, "handle", None)):
            raise AttributeError(say("doctor.module.no_handle"))
    except Exception as error:
        (report.error if entry["enabled"] else report.warn)(say("doctor.module.unloadable", name=name, error=error))
        return
    report.ok(say("doctor.module.loadable", name=name))
    own_check = getattr(module, "doctor", None)
    if callable(own_check):
        found = own_check(root)
        for text in found:
            report.error(say("doctor.module.problem", name=name, text=text))
        if not found:
            report.ok(say("doctor.module.checked", name=name))
    policy_name = getattr(module, "POLICY_NAME", None)
    if policy_name:
        try:
            module.validate_policy(config.load_policy(root, policy_name))
            report.ok(say("doctor.policy.ok", name=policy_name))
        except Exception as error:
            report.error(say("doctor.policy.bad", name=policy_name, error=error))


def check_logs(report: Report, root: Path, registry: Dict[str, Any]) -> None:
    """Nothing deletes the session logs by itself. Say so when there are many, and name the command."""
    entry = registry["modules"].get("observe")
    if entry is None or not entry["enabled"]:
        return
    try:
        limit = config.load_policy(root, "observe")["warn_session_files"]
    except Exception:
        return  # the policy check of the module reports a broken file
    base = root / ".harness" / "runtime" / "logs"
    count = len(list(base.glob("*/*.jsonl"))) if base.is_dir() else 0
    if count > limit:
        report.warn(say("doctor.logs.many", count=count, limit=limit))
    if (base / "hook-calls.jsonl").exists():
        report.warn(say("doctor.logs.old_file"))


def check_output(report: Report, root: Path) -> bool:
    """How the CLI prints Chinese here. Returns True when the raw UTF-8 sample line should be printed too."""
    try:
        section = config.load_policy(root, output.POLICY_NAME)["output"]
        raw = section["encoding"]
        shape = section.get("format", output.AUTO)
    except Exception as error:
        report.error(say("doctor.output.unreadable", error=error))
        return False
    if raw not in output.CHOICES:
        report.error(say("doctor.output.bad_choice", raw=raw, choices=messages.joined(output.CHOICES)))
    if shape not in output.FORMATS:
        report.error(say("doctor.output.bad_format", raw=shape, choices=messages.joined(output.FORMATS)))
    facts = output.facts()
    pages = facts["code_pages"]
    where = say("doctor.output.terminal") if facts["terminal"] else say("doctor.output.pipe")
    shown = say("doctor.output.shown", stdout=facts["stdout_encoding"], where=where, preferred=facts["preferred"])
    if pages:
        shown += say("doctor.output.pages", console=pages["console_output"], ansi=pages["ansi"])
    shown += say("doctor.output.setting", setting=output.setting(root))
    if output.shows(output.SAMPLE, facts["stdout_encoding"]):
        replaced = output.REPLACED.get("stdout", "")
        report.ok(shown + (say("doctor.output.replaced", replaced=replaced) if replaced else ""))
        report.ok(say("doctor.output.sample.back" if replaced else "doctor.output.sample", sample=output.SAMPLE))
        return False
    report.warn(shown + say("doctor.output.cannot"))
    return True


def print_utf8_sample() -> None:
    """One line as raw UTF-8 bytes, whatever the stream encoding is: it shows what UTF-8 output would look like here.

    The advice is in that line too: a person who can read it is a person for whom UTF-8 works.
    """
    text = say("doctor.output.utf8_sample", sample=output.SAMPLE)
    try:
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:  # noqa: BLE001 - a sample line must not fail doctor
        pass


def check_language(report: Report, raw: Any) -> None:
    """Which language the engine speaks and where that comes from. A value it does not know falls back to the default."""
    if raw is not None and raw not in messages.LANGUAGES:
        report.error(say("doctor.language.bad", raw=raw, choices=messages.joined(messages.LANGUAGES), default=messages.DEFAULT_LANGUAGE))
    source = "env" if os.environ.get(messages.ENVIRONMENT, "").strip().lower() in messages.LANGUAGES else "policy" if raw in messages.LANGUAGES else "default"
    report.ok(say("doctor.language.ok", language=messages.language(), source=say(f"doctor.language.source.{source}")))


def check_user(report: Report, root: Path) -> None:
    try:
        policy = config.load_policy(root, user.POLICY_NAME)
    except Exception as error:
        report.error(say("doctor.user.unreadable", error=error))
        return
    raw = policy.get("name", "")
    check_language(report, policy.get("language"))
    if not isinstance(raw, str):
        report.error(say("doctor.user.name_type"))
        return
    found = user.who(root)
    if found["source"] == "none":
        report.warn(say("doctor.user.unknown"))
    else:
        report.ok(say("doctor.user.name", name=found["name"], source=found["source"]))


def check_overrides(report: Report, root: Path) -> None:
    """Each `<name>.override.json`: one layer, merges onto an existing policy, and says what it changed."""
    directory = policies_dir(root)
    found = sorted(directory.glob("*" + config.OVERRIDE_SUFFIX)) if directory.is_dir() else []
    if not found:
        report.ok(say("doctor.override.none"))
        return
    for path in found:
        name = path.name[: -len(config.OVERRIDE_SUFFIX)]
        if config.OVERRIDE_SUFFIX[:-5] in name or not (directory / f"{name}.json").exists():
            report.error(say("doctor.override.orphan", file=path.name, name=name))
            continue
        try:
            base = config.read_json(directory / f"{name}.json")
            override = config.read_json(path)
            config.deep_merge(base, override)
        except Exception as error:
            report.error(say("doctor.override.unmergeable", file=path.name, name=name, error=error))
            continue
        touched = config.changes(base, override)
        report.ok(say("doctor.override.summary", file=path.name, count=len(touched), name=name))
        for where, how, size in touched:
            if how == "replaced" and size:
                report.warn(say("doctor.override.replaced", file=path.name, where=where, size=size, key=where.split(".")[-1]))
            else:
                report.ok(say("doctor.override.item", where=where, how=say(f"doctor.override.how.{how}")))


def front_matter(text: str) -> Dict[str, str]:
    front = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not front:
        return {}
    pairs = (line.split(":", 1) for line in front.group(1).splitlines() if ":" in line)
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def body_of(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL).strip()


def kb_instruction_files(root: Path) -> List[Path]:
    """Instruction files that have text and are about the knowledge base: named after it, or naming its folder."""
    directory = root / ".github" / "instructions"
    found = []
    for path in sorted(directory.glob("*.instructions.md")) if directory.is_dir() else []:
        text = path.read_text(encoding="utf-8")
        if body_of(text) and ("knowledge" in path.name.lower() or KB_DIR in text.lower()):
            found.append(path)
    return found


def kb_instruction_loads(root: Path, path: Path) -> str:
    """Why Copilot would load the file on its own, or an empty string when nothing makes it."""
    apply_to = front_matter(path.read_text(encoding="utf-8")).get("applyTo", "")
    if any(part.strip() in BROAD_APPLY_TO for part in apply_to.split(",")):
        return say("doctor.kb.loads.apply_to", apply_to=apply_to)
    for name in ("AGENTS.md", ".github/copilot-instructions.md"):
        entry = root / name
        if entry.is_file() and path.name in entry.read_text(encoding="utf-8"):
            return say("doctor.kb.loads.link", name=name)
    return ""


def kb_broken_links(kb: Path) -> List[str]:
    readme = kb / "README.md"
    broken = []
    for target in MARKDOWN_LINK.findall(readme.read_text(encoding="utf-8")):
        target = target.split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("/"):
            continue
        if not (kb / target).exists():
            broken.append(target)
    return broken


def kb_git_ignored(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.is_file():
        return False
    names = {KB_DIR, f"/{KB_DIR}", f"{KB_DIR}/", f"/{KB_DIR}/", f"{KB_DIR}/*", f"/{KB_DIR}/*", f"{KB_DIR}/**", f"/{KB_DIR}/**"}
    return any(line.strip() in names for line in ignore.read_text(encoding="utf-8").splitlines())


def check_knowledge_base(report: Report, root: Path) -> None:
    """Can an agent reach the knowledge base? Looks at the folder, its README index and the instructions. Warns only."""
    kb = root / KB_DIR
    content = targets.knowledge_base_content(kb)
    if not content:
        report.ok(say("doctor.kb.empty", kb=KB_DIR))
        return
    report.ok(say("doctor.kb.content", kb=KB_DIR, count=len(content)))
    if not (kb / "README.md").is_file():
        report.warn(say("doctor.kb.no_readme", kb=KB_DIR))
    else:
        broken = kb_broken_links(kb)
        shown = ", ".join(broken[:SHOWN_BROKEN_LINKS]) + (say("doctor.kb.links.more", count=len(broken)) if len(broken) > SHOWN_BROKEN_LINKS else "")
        if broken:
            report.warn(say("doctor.kb.links.broken", kb=KB_DIR, shown=shown))
        else:
            report.ok(say("doctor.kb.links.ok", kb=KB_DIR))
    if (kb / ".git").exists():
        if not targets.kb_registered(root):
            report.warn(say("doctor.kb.unregistered", kb=KB_DIR))
    elif not targets.kb_registered(root):  # registered but not git: check_targets reports that as an error
        report.warn(say("doctor.kb.not_git", kb=KB_DIR))
    if kb_git_ignored(root):
        report.warn(say("doctor.kb.ignored", kb=KB_DIR))
    check_kb_form(report, root)
    files = kb_instruction_files(root)
    if not files:
        report.warn(say("doctor.kb.no_instructions"))
        return
    for path in files:
        reason = kb_instruction_loads(root, path)
        if reason:
            report.ok(say("doctor.kb.instructions.loaded", file=path.name, reason=reason))
        else:
            report.warn(say("doctor.kb.instructions.not_loaded", file=path.name))


def check_kb_form(report: Report, root: Path) -> None:
    """The domains in the standard form (`kb check`). Warns only: a knowledge base of before the standard still works."""
    try:
        result = kbstd.check(root)
    except Exception as error:  # noqa: BLE001 - doctor reports, it does not stop
        report.warn(say("doctor.kb.form.failed", error=error))
        return
    if not result["domains"]:
        return
    if result["errors"]:
        names = ", ".join(item["domain"] for item in result["problems"] if item["errors"])
        report.warn(say("doctor.kb.form.errors", count=result["errors"], domains=names))
    else:
        report.ok(say("doctor.kb.form.ok", count=result["domains"], warnings=result["warnings"]))


def check_skills(report: Report, root: Path) -> None:
    """Are the skills well formed? A skill with an error is listed; so is a skill of ours or of the company (it has a prefix) with only a warning.

    A third-party skill keeps its own name and form, so only its errors count. Warns only: a bad skill must not stop the harness.
    """
    results = skillcheck.check_all(root)
    bad = [item["skill"] for item in results if item["errors"] or (item["warnings"] and item["skill"].startswith(skillcheck.PREFIXES))]
    if bad:
        report.warn(say("skill.doctor.summary", count=len(bad), names=", ".join(bad)))
    elif results:
        report.ok(say("skill.doctor.ok", count=len(results)))


def check_standards(report: Report, root: Path) -> None:
    """Are the code standards plugged in, and does each rule have the fields the check needs? Warns only."""
    found = standards.rules(root)
    if not found:
        report.ok(say("doctor.standards.none", file=standards.STANDARDS_FILE))
        return
    report.ok(say("doctor.standards.ok", count=len(found), file=standards.STANDARDS_FILE))
    bad = [item for item in found if item["missing"]]
    if bad:
        fields = ", ".join(sorted({name for item in bad for name in item["missing"]}))
        report.warn(say("doctor.standards.incomplete", file=standards.STANDARDS_FILE, fields=fields, titles=", ".join(item["title"] for item in bad[:5])))


def check_targets(report: Report, root: Path) -> None:
    """The target repositories (target.json + target.override.json): found, git repositories, with their base branch."""
    try:
        found = targets.load(root)
    except Exception as error:
        report.error(say("doctor.target.policy_bad", error=error))
        return
    if not found.configured:
        report.ok(say("doctor.target.none"))
        return
    for problem in found.problems:
        report.error(say("doctor.target.problem", problem=problem))
    if not found.repos:
        if not found.problems:
            report.warn(say("doctor.target.no_repos"))
        return
    for name in found.names():
        repo = found.repos[name]
        try:
            info = targets.summary(repo, found.timeout)
        except targets.TargetError as error:
            report.error(say("doctor.target.error", name=name, error=error))
            continue
        if not info["has_base_ref"]:
            report.error(say("doctor.target.no_branch", name=name, base_ref=repo.base_ref))
            continue
        state = say("doctor.target.clean") if info["clean"] else say("doctor.target.dirty", files=info["uncommitted_files"])
        kind = say("doctor.target.kind.kb" if repo.knowledge_base else "doctor.target.kind.repo")
        report.ok(say("doctor.target.info", kind=kind, name=name, base_ref=repo.base_ref, commit=info["base_commit"], date=info["base_commit_date"][:10], branch=info["current_branch"], state=state))
        if repo.knowledge_base and info["current_branch"] != repo.base_ref:
            report.warn(say("doctor.target.kb_branch", name=name, base_ref=repo.base_ref))


def check_location(report: Report, root: Path) -> None:
    problems = targets.location_warnings(str(root))
    for text in problems:
        report.warn(text)
    if not problems:
        report.ok(say("doctor.location.ok"))


def check_tool_kinds(report: Report) -> None:
    path = Path(__file__).resolve().parent / "adapters" / "tool_kinds.json"
    try:
        data = config.read_json(path)
        bad = [
            f"{surface}:{tool}={kind}"
            for surface, body in data["surfaces"].items()
            for tool, kind in body["tools"].items()
            if kind not in TOOL_KINDS
        ]
    except Exception as error:
        report.error(say("doctor.tool_kinds.unparsable", error=error))
        return
    if bad:
        report.error(say("doctor.tool_kinds.unknown", bad=", ".join(bad)))
    else:
        report.ok(say("doctor.tool_kinds.ok"))


def agent_models(path: Path) -> Any:
    """The `model` line of an .agent.md front matter: a list of names, a single name, or None when there is none."""
    text = path.read_text(encoding="utf-8")
    front = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not front:
        return None
    for line in front.group(1).splitlines():
        if line.startswith("model:"):
            value = line.split(":", 1)[1].strip()
            if not value:
                return None
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return [value.strip("'\"")]
            return parsed if isinstance(parsed, list) else [str(parsed)]
    return None


def series_of(name: str, series: Dict[str, List[str]]) -> str:
    lowered = name.lower()
    for label, words in series.items():
        if any(word.lower() in lowered for word in words):
            return label
    return ""


def check_agents(report: Report, root: Path) -> None:
    """Each agent's model list stays in one series (unless it is in `any_series`); roles listed in `different_series` do not share one."""
    directory = root / ".github" / "agents"
    if not directory.is_dir() or not (root / ".harness" / "policies" / "agents.json").exists():
        return
    try:
        policy = config.load_policy(root, "agents")
    except Exception as error:
        report.error(say("doctor.agents.unreadable", error=error))
        return
    chosen: Dict[str, str] = {}
    for path in sorted(directory.glob("*.agent.md")):
        agent = path.name[: -len(".agent.md")]
        names = agent_models(path)
        if not names:
            continue
        labels = {series_of(name, policy["series"]) for name in names}
        if "" in labels:
            report.warn(say("doctor.agents.unknown_model", agent=agent, names=", ".join(n for n in names if not series_of(n, policy["series"]))))
            labels.discard("")
        if len(labels) > 1 and agent in policy.get("any_series", []):
            continue  # this agent may fall back across series; it takes no part in `different_series`
        if len(labels) > 1:
            report.error(say("doctor.agents.mixed", agent=agent, labels=", ".join(sorted(labels))))
        elif labels:
            chosen[agent] = next(iter(labels))
    for group in policy.get("different_series", []):
        present = [name for name in group if name in chosen]
        seen: Dict[str, str] = {}
        for name in present:
            if chosen[name] in seen:
                report.error(say("doctor.agents.same", first=seen[chosen[name]], second=name, series=chosen[name]))
            seen[chosen[name]] = name
    report.ok(say("doctor.agents.ok", count=len(chosen)))


def check_old_tasks(report: Report, root: Path) -> None:
    """Task folders of before 1.1.0 are not read any more. Say so, so nobody waits for a task that cannot be opened."""
    old = root / tasks.OLD_TASKS_DIR
    names = sorted(path.name for path in old.iterdir() if path.is_dir()) if old.is_dir() else []
    if names:
        shown = messages.joined(names[:5]) + (say("rules.task.open_more") if len(names) > 5 else "")
        report.warn(say("doctor.old_tasks", old=tasks.OLD_TASKS_DIR, count=len(names), shown=shown, tasks_dir=tasks.TASKS_DIR))


def shown(lines: List[str]) -> str:
    """On a terminal, a long line goes on under its text, not under `[OK]`. On a pipe, one line per check, as before."""
    try:
        if not sys.stdout.isatty():
            return "\n".join(lines)
        size = render.columns()
    except Exception:  # noqa: BLE001 - the report must always come out
        return "\n".join(lines)
    out: List[str] = []
    for line in lines:
        body = line[8:]
        indent = " " * (8 + len(body) - len(body.lstrip(" ")))
        out += render.wrap(line, size, indent)
    return "\n".join(out)


def run(root: Path) -> int:
    report = Report()
    check_python(report)
    check_interpreter(report)
    check_short_command(report, root)
    try:
        registry = load_registry(root)
    except Exception as error:
        report.error(say("doctor.registry.unreadable", error=error))
        print(shown(report.lines))
        return 1
    report.ok(say("doctor.registry.ok"))
    check_files(report, root, "engine", registry["engine"]["files"])
    check_tool_kinds(report)
    check_hook_config(report, root, registry)
    check_hook_activity(report, root, registry)
    check_agents(report, root)
    check_logs(report, root, registry)
    check_overrides(report, root)
    sample = check_output(report, root)
    check_user(report, root)
    check_targets(report, root)
    check_location(report, root)
    check_knowledge_base(report, root)
    check_skills(report, root)
    check_standards(report, root)
    check_old_tasks(report, root)
    for name, entry in registry["modules"].items():
        check_module(report, root, name, entry)
    print(shown(report.lines))
    if sample:
        print_utf8_sample()
    print(json.dumps({"errors": report.errors}))
    return 1 if report.errors else 0
