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

from core import ahp, clip, company, config, kbstd, messages, output, render, skillcheck, standards, targets, tasks, unseen, user
from core.logs import read_lines, session_files
from core.paths import cli_command, policies_dir, python_command
from core.registry import load_registry
from core.events import CONFIG_KEYS
from core.state import TRACKED_EVENTS


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)

HOOK_ENTRY = ".harness/engine/hook.py"
COMMAND_KEYS = ("command", "windows", "linux", "osx", "bash", "powershell")
KB_DIR = "knowledge-base"
BROAD_APPLY_TO = {"**", "**/*", "*", "**/**"}
MARKDOWN_LINK = re.compile(r"\]\(([^)\s]+)\)")
SHOWN_BROKEN_LINKS = 5
UNSEEN_SHOWN = 10
TOOL_KINDS = {"read", "edit", "create", "terminal", "search", "subagent", "mcp", "web", "skill", "meta"}
INTERPRETER_SECONDS = 15
RECENT_LOG_FILES = 20  # the hook self-check reads only the newest session logs
STALE_HOOK_DAYS = 7
SLOW_GATE_SHARE = 0.5  # of the PreToolUse timeout: the SDK engine lets a call through when the hook times out
DEFAULT_HOOK_TIMEOUT = 30


TOPICS = "HARNESS_DOCTOR_TOPICS"  # the board's own run (1.7.38): a warning about the company's content (knowledge base, standards, repositories) says so, `[WARN:company]`; one about its copies `[WARN:copies]`; a person's run prints `[WARN]` as always


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.lines: List[str] = []
        self.topic = ""  # the part of the run that is going on: `company` while the checks of the repositories, the knowledge base, its copies and the standards run

    def ok(self, message: str) -> None:
        self.lines.append(f"[OK]    {message}")

    def warn(self, message: str) -> None:
        mark = f"[WARN:{self.topic}] " if self.topic and os.environ.get(TOPICS) else "[WARN]  "
        self.lines.append(f"{mark}{message}")

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
            configured.add(next((name for name, key in CONFIG_KEYS.items() if key == event), event))
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


def check_unseen(report: Report, root: Path) -> None:
    """Tools and shapes the gate met and could not place. Newest last; the list is short because each is kept once."""
    found = unseen.read(root)
    if not found:
        return
    for surface in sorted({item.get("surface", "") for item in found}):
        rows = [item for item in found if item.get("surface", "") == surface]
        items = "; ".join(f"{item.get('tool')} ({item.get('kind')}: {item.get('shape')})" for item in rows[-UNSEEN_SHOWN:])
        report.warn(say("doctor.unseen.tools", count=len(rows), surface=surface, items=items))


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
    """Each `<name>.company.json` (the company pack) and `<name>.override.json` (the person's): a layer that merges onto an existing policy, and what it changed."""
    directory = policies_dir(root)
    found = sorted(path for suffix in config.LAYERS for path in directory.glob("*" + suffix)) if directory.is_dir() else []
    if not found:
        report.ok(say("doctor.override.none"))
        return
    for path in found:
        suffix = next(item for item in config.LAYERS if path.name.endswith(item))
        name = path.name[: -len(suffix)]
        if any(layer[:-5] in name for layer in config.LAYERS) or not (directory / f"{name}.json").exists():
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
    others = set(company.ledger_files(root))  # the company's other instruction files (1.7.38) are about other things; only the guide to the knowledge base is judged here
    for path in sorted(directory.glob("*.instructions.md")) if directory.is_dir() else []:
        if path.name in others:
            continue
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
    problem = skillcheck.prefix_problem(root) or skillcheck.prefix_conflict(root)
    if problem:
        report.warn(problem)
    results = skillcheck.check_all(root)
    owned = skillcheck.prefixes(root)
    bad = [item["skill"] for item in results if item["errors"] or (item["warnings"] and item["skill"].startswith(owned))]
    if bad:
        report.warn(say("skill.doctor.summary", count=len(bad), names=", ".join(bad)))
    elif results:
        report.ok(say("skill.doctor.ok", count=len(results)))


def check_task_names(report: Report, root: Path) -> None:
    """A task folder whose name a terminal would take for commands. It still opens; only the agent's commands need quotes."""
    from modules.task import tasklife

    risky = [path.name for path in sorted((root / tasks.TASKS_DIR).glob("*")) if path.is_dir() and (set(path.name) & tasklife.SHELL_BAD)] if (root / tasks.TASKS_DIR).is_dir() else []
    if risky:
        report.warn(say("doctor.task_names", names=", ".join(risky[:5]) + (" ..." if len(risky) > 5 else "")))


def check_vscode(report: Report) -> None:
    """Can the board reach VS Code (1.6)? A warning at most: the board works without it. One `code` process and one connection, as `doctor` is run by hand and seldom."""
    if ahp.switched_off():
        report.ok(say("doctor.vscode.off"))
        return
    code = ahp.find_code()
    if not code:
        report.warn(say("doctor.vscode.nocli"))
        return
    secret = ""
    try:
        found = ahp.read_endpoints(code)
        if not found:
            report.warn(say("doctor.vscode.none"))
            return
        secret = found[0].token()
        ahp.connect(found[0]).close()
    except (ahp.AhpError, OSError) as error:
        report.warn(say("doctor.vscode.failed", error=ahp.scrub(error, secret)))
        return
    report.ok(say("doctor.vscode.ok", count=len(found)))


def check_optional_packages(report: Report, root: Path) -> None:
    """Are the optional readers (`xlrd` for .xls, `pypdf` for PDF) installed, into the Python the harness runs on? Warns only: nothing needs them until an old Excel or a PDF file comes in."""
    try:
        from modules.task import intake

        state = intake.setup(root)
    except Exception as error:  # noqa: BLE001 - a check that fails itself must not hurt doctor
        report.warn(say("doctor.packages.unreadable", error=error))
        return
    if not state["optional"]:
        return
    for text in state["warnings"]:
        report.warn(text)
    if state["all_installed"]:
        report.ok(say("doctor.packages.ok", names=", ".join(item["package"] for item in state["optional"])))
        return
    follow = say("doctor.packages.run", install=state["install_all"]) if state["install_all"] else say("doctor.packages.no_command")
    report.warn(say("doctor.packages.missing", names=", ".join(state["missing"]), next=follow))


def check_company(report: Report, root: Path) -> None:
    """Do the copies in `.github/` match the company content of the knowledge base? Warns only, and says nothing when there is none."""
    try:
        found = company.drift(root)
    except Exception as error:  # noqa: BLE001 - doctor reports, it does not stop
        report.warn(say("doctor.company.failed", error=error))
        return
    if found is None:
        return
    if found["problem"]:
        report.warn(found["problem"])
    elif found["stale"] or found["refused"]:
        report.warn(say("doctor.company.stale", names=", ".join(found["stale"] + found["refused"])))
    else:
        report.ok(say("doctor.company.ok", version=found["version"] or "-"))


def check_toolpacks(report: Report, root: Path) -> None:
    """Tool packs (1.7.30): a leftover of the old layout, a name in `use` no factory pack has, a connection field that is not filled in, a skill that uses a command its pack does not list."""
    try:
        from core import connections, launchenv, toolpacks

        if (root / ".harness" / "examples" / "toolpacks").exists():
            report.warn(say("doctor.toolpacks.old_examples"))
        gone = toolpacks.unknown_use(root)
        if gone:
            report.warn(say("doctor.toolpacks.unknown", names=", ".join(gone)))
        for line in toolpacks.clash_lines(root):  # `company sync` stops as a whole while this stands (1.7.38)
            report.error(line)
        company = targets.company_folder(root)
        recipe_file = company / "tools" / "computer.json" if company else None
        if recipe_file is not None and recipe_file.is_file():
            try:
                faults = launchenv.recipe_errors(json.loads(recipe_file.read_text(encoding="utf-8-sig")))
            except ValueError as error:
                faults = [str(error)]
            if faults:
                report.warn(say("doctor.toolpacks.recipe", faults="; ".join(faults)))
        for one in toolpacks.faults(root):  # 1.7.38 (G-1): a faulty file makes the gate hold every call of the pack's programs; it is an error, not a quiet gap
            for fault in one["faults"]:
                report.error(say("doctor.toolpacks.broken", pack=one["pack"], file=fault["file"], problem=str(fault["problem"]).rstrip(".") + ".", programs=", ".join(one["programs"]) or "-"))
        held = connections.broken_systems(root)  # 1.7.38 (C13 F2): a connection list that cannot be read holds every program of the connection types: an error, not a quiet gap
        for fault in connections.faults(root):
            report.error(say("doctor.connections.broken", file=fault["file"], problem=str(fault["problem"]).rstrip(".") + ".", programs=", ".join(sorted({one for system in held.values() for one in system["reach"]["cli"]})) or "-"))
        names = sorted(toolpacks.active(root))
        if names:
            report.ok(say("doctor.toolpacks.on", names=", ".join(names)))
        for name, aliases in toolpacks.guard_only(root).items():  # a pack that is off still guards the connections that use its types (1.7.38)
            report.ok(say("doctor.toolpacks.guard", name=name, aliases=", ".join(aliases)))
        for line in toolpacks.recent_updates(root):
            report.ok(line)
        for name, rows in toolpacks.needs_report(root).items():  # a program a pack on needs is not found (1.7.37)
            lost = list(dict.fromkeys(row["program"] for row in rows if not row["found"]))
            if lost:
                report.warn(say("doctor.toolpacks.program", name=name, programs=", ".join(lost)))
        for item in connections.unset_fields(root):
            report.warn(say("doctor.toolpacks.unset", alias=item["alias"], type=item["type"], fields=", ".join(item["fields"])))
        for item in toolpacks.command_problems(root):
            report.warn(say("doctor.toolpacks.command", **item))
    except Exception as error:  # noqa: BLE001 - a check that fails itself must not hurt doctor
        report.warn(say("doctor.company.failed", error=error))


def check_vscode_settings(report: Report, root: Path) -> None:
    """(1.7.38, C13 TA-Q2) A VS Code that runs without the settings of this copy (the tool folders, the CA bundle): a warning that says what is missing and where to mend it. The board makes the same check itself
    (its VS Code line), so the board's own run of doctor leaves it out. A VS Code that cannot be judged says nothing."""
    if os.environ.get(TOPICS):
        return
    try:
        from core import launchenv

        found = launchenv.windows_without_settings(root)
        if found:
            from modules.task import ready

            lost = list(dict.fromkeys(item for one in found for item in one["missing"]))
            report.warn(say("doctor.vscode.settings", missing=ready.missing_words(lost) or "-"))
    except Exception as error:  # noqa: BLE001 - a check that fails itself must not hurt doctor
        report.warn(say("doctor.company.failed", error=error))


def reach_words(code: str, said: str = "") -> str:
    """The word a probe leaves (`no-answer`, `identity`, `exit-<n>`) as a person reads it; anything else is kept as it is. `said`: what the probe printed when nothing answered."""
    if code == "no-answer":
        return say("doctor.systems.why.no_answer") + (say("doctor.systems.why.said", said=said) if said else "")
    if code in ("identity", "other-identity"):
        return say("doctor.systems.why.identity")
    if code.startswith("exit-"):
        return say("doctor.systems.why.exit", code=code[5:])
    return code


def system_reach(root: Path, systems: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Is each outside system reachable from here? A connection is probed as the board and VS Code do it (1.7.38): with the tool folders and the CA bundle VS Code gets and the identity kept here, so a connection
    that passed its Test is not reported as not reachable (exit code 127 or 1) just because a terminal has neither. What has no kept identity, and a system written by hand, is probed in this terminal as before."""
    from core import connections, reach as seen
    from core import systems as outside
    from modules.gate import external

    listed = set(connections.listed(root))
    try:
        done = connections.probe_lines(root) if listed else {}  # it reports and keeps nothing: the board runs doctor in a child with another PATH, and its answer must not replace the board's own (C12 N2)
    except Exception:  # noqa: BLE001 - a probe that cannot run leaves the terminal's way
        done = {}
    by_connection: Dict[str, Dict[str, Any]] = {}
    for name, system in systems.items():
        keys = [f"{name}:{env}" for env in outside.probes(system)]
        if name in listed and keys and all(key in done for key in keys):
            bad = [key for key in keys if done[key]["state"] != seen.OK]
            code = str(done[bad[0]].get("why") or done[bad[0]]["state"]) if bad else ""
            said = str(done[bad[0]].get("said") or "") if bad else ""
            by_connection[name] = {"reachable": not bad, "why": clip.words(say("doctor.systems.why.connection", why=reach_words(code, said)), 260) if bad else "",
                                   "launch": say("doctor.systems.launch.noanswer") if code == "no-answer" else (system.get("needs") or {}).get("launch") or ""}  # a new identity does not help when nothing answered
    rest = {name: system for name, system in systems.items() if name not in by_connection}
    answers = {**external.reach(rest, lambda command: external.run_probe(command, root)), **by_connection}
    try:
        loose = set(connections.unsigned(root))  # a connection with no sign-in kept here: told in one line, not one for each (1.7.38)
    except Exception:  # noqa: BLE001 - a list that cannot be read leaves the lines one by one
        loose = set()
    return {name: dict(answers[name], unsigned=name in loose and not answers[name]["reachable"]) for name in systems if name in answers}


def check_systems(report: Report, root: Path) -> None:
    """The outside systems a company listed (M43-2): is the list well formed, and is each system that has a probe reachable from here (1.7.1)? Nothing listed is fine: the harness ships none."""
    try:
        from modules.gate import external

        systems = config.load_policy(root, "tools").get("systems") or {}
        errors = external.validate(systems)
        found = external.warnings(systems) if not errors else []
        reached = system_reach(root, systems) if not errors else {}
    except Exception as error:  # noqa: BLE001 - a check that fails itself must not hurt doctor
        report.warn(say("doctor.systems.unreadable", error=error))
        return
    if errors:
        for text in errors[:5]:
            report.error(say("doctor.systems.bad", error=text))
        return
    if not systems:
        report.ok(say("doctor.systems.none"))
        return
    report.ok(say("doctor.systems.ok", count=len(systems), names=", ".join(systems)))
    for text in found:
        report.warn(say("doctor.systems.warn", text=text))
    loose = [name for name, line in reached.items() if line.get("unsigned")]
    for name, line in reached.items():
        if line["reachable"]:
            report.ok(say("doctor.systems.reached", name=name))
        elif name not in loose:
            report.warn(say("doctor.systems.unreached", name=name, why=line["why"], launch=line["launch"] or say("doctor.systems.no_launch")))
    if loose:  # no sign-in is kept for them: the cause is the same for all, and so is the way out
        report.warn(say("doctor.systems.unsigned.one" if len(loose) == 1 else "doctor.systems.unsigned", n=len(loose), names=", ".join(loose)))


def check_standards(report: Report, root: Path) -> None:
    """Are the code standards plugged in, and does each rule have the fields the check needs? Warns only."""
    found = standards.rules(root)
    if not found:
        report.ok(say("doctor.standards.none", file=standards.shown(root)))
        return
    report.ok(say("doctor.standards.ok", count=len(found), file=standards.shown(root)))
    bad = [item for item in found if item["missing"]]
    if bad:
        fields = ", ".join(sorted({name for item in bad for name in item["missing"]}))
        report.warn(say("doctor.standards.incomplete", file=standards.shown(root), fields=fields, titles=", ".join(item["title"] for item in bad[:5])))


def check_targets(report: Report, root: Path) -> None:
    """The target repositories (target.json + target.override.json): found, git repositories, with their base branch."""
    try:
        found = targets.load(root)
    except Exception as error:
        file, problem = targets.diagnose(root, error)  # 1.7.38 (C13 F2b): which file, and what is wrong
        report.error(say("doctor.target.policy_bad", file=file, error=problem))
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
    check_unseen(report, root)
    check_overrides(report, root)
    sample = check_output(report, root)
    check_user(report, root)
    report.topic = "company"
    check_targets(report, root)
    report.topic = ""
    check_location(report, root)
    report.topic = "company"
    check_knowledge_base(report, root)
    report.topic = ""
    check_skills(report, root)  # skills, packs and systems: the items of readyitems.py say more, so they are not counted twice
    report.topic = "copies"  # the board counts the copies itself (readyitems.sync_item), with a button; its count of doctor's notes leaves this line out
    check_company(report, root)
    report.topic = ""
    check_toolpacks(report, root)
    check_vscode_settings(report, root)
    report.topic = "company"
    check_standards(report, root)
    report.topic = ""
    check_task_names(report, root)
    check_optional_packages(report, root)
    check_vscode(report)
    check_systems(report, root)
    for name, entry in registry["modules"].items():
        check_module(report, root, name, entry)
    print(shown(report.lines))
    if sample:
        print_utf8_sample()
    print(json.dumps({"errors": report.errors}))
    return 1 if report.errors else 0
