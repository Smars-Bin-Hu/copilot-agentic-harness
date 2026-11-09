#!/usr/bin/env python3
"""Command line entry for agents and people: <python> .harness/engine/cli.py <command> (python on Windows, python3 elsewhere).

  doctor                       check that the harness files and config are consistent
  user                         the name of the person using this copy (for a change note that needs an author), and the prefix of the company's skills
  task ...                     tasks: new, open, upgrade, list, fetch, diff, promote, review, snapshot, close (task module)
  target list|show|refs|init-kb  the target repositories; refs: where names are used; init-kb: make the knowledge base a git repository (task module)
  reinstall --from <old copy> [--apply]  carry the tasks, runtime, overrides and knowledge base of an older copy over to this one; --apply: a person only
  company sync|pack|update     the company's content in the knowledge base: copy it where Copilot finds it, make a package of it, put a package in place (--apply: a person only)
  skill check [name|path ...]  is a skill well formed? (all skills when none is named, the domain skills too)
  skill list [--domain D]      the skills of business domains, kept in the knowledge base
  approve-command              a person approves a git command the gate refused (gate module)
  admin on|off|status          a person switches admin mode on for one session: it may then change guardrail files (gate module)
  stats, logs prune            numbers from the session logs; delete old logs (observe module)
  eval list|show|check         fixed scenarios, judged from a finished run (evalcheck module)
  --version [--short]          the harness release, date and authors (from .harness/registry.json); --short prints one line

A result is text on a terminal and JSON on a pipe (`output.format` in the cli policy). `--json`, anywhere on the line,
always prints JSON. The commands only a person may run always print text.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import approval, company, toolpacks, domainskills, messages, output, pinpython, reinstall, render, skillcheck, user  # noqa: E402
from core.paths import repo_root  # noqa: E402
from core.registry import harness_version, version_banner  # noqa: E402
import doctor  # noqa: E402
from modules.evalcheck import commands as eval_commands  # noqa: E402
from modules.gate import commands as gate_commands  # noqa: E402
from modules.observe import commands as observe_commands  # noqa: E402
from modules.task import commands as task_commands  # noqa: E402


SHORT_FLAG = "--short"
JSON_FLAG = "--json"
ARGV = None  # the arguments main() was called with, when it was not the command line


class ShowVersion(argparse.Action):
    """`--version` reads the registry only when it is asked for: a broken registry must not break the other commands (doctor reports it)."""

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, help="show the harness version and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        try:
            if SHORT_FLAG in (ARGV if ARGV is not None else sys.argv[1:]):
                print(f"harness {harness_version(repo_root())}")  # one line, for scripts
            else:
                print(version_banner(repo_root(), sys.stdout))
        except Exception as error:
            print(messages.text("cli.version.unreadable", error=error), file=sys.stderr)
            parser.exit(1)
        parser.exit(0)


def check_skills(only):
    results = skillcheck.check_all(repo_root(), only)
    errors = sum(len(item["errors"]) for item in results)
    return {
        "checked": len(results),
        "errors": errors,
        "warnings": sum(len(item["warnings"]) for item in results),
        "skills": [item for item in results if item["errors"] or item["warnings"]],
        "next": messages.text("skill.next.errors" if errors else "skill.next.ok"),
        "exit_code": 1 if errors else 0,
    }


def list_domain_skills(only):
    found = domainskills.skills(repo_root(), only)
    return {"domains": sorted(domainskills.domains(repo_root()), key=str.lower), "skills": found, "next": messages.text("domain.list.next" if found else "domain.list.none")}


def check_after_reinstall(names):
    """After the copy: doctor (short command, user, targets, knowledge base) and the state of every task that came over."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = doctor.run(repo_root())
    lines = [line for line in buffer.getvalue().splitlines() if line.startswith(("[ERROR]", "[WARN]"))]
    found = reinstall.check_tasks(repo_root(), names)
    found.update(doctor_errors=sum(line.startswith("[ERROR]") for line in lines), doctor_exit_code=code, doctor_problems=lines)
    return found


def _toolpack_add(source: str, replace: bool) -> dict:
    approval.require_person("toolpack add", typed=False)
    return toolpacks.add(repo_root(), source, replace=replace)


def _toolpack_remove(name: str) -> dict:
    approval.require_person("toolpack remove", typed=False)
    return toolpacks.remove(repo_root(), name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Harness CLI")
    parser.add_argument("--version", action=ShowVersion)
    parser.add_argument(SHORT_FLAG, action="store_true", help="with --version: only `harness <version>`, one line")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="check harness files and config")
    check.add_argument("--accept", action="store_true", help="accept the guardrail files (engine, policies, hooks, bin, packs) as they are now: the list the hook checks them against is made again. A person at a terminal only")
    check.set_defaults(handler=None)
    name = commands.add_parser("user", help="the name of the person using this copy (user.override.json, else git config user.name), and skill_prefix: the word the company's own skills start with")
    name.set_defaults(handler=lambda _args: user.who(repo_root()))
    skill = commands.add_parser("skill", help="the skills in .github/skills/")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    skill_check = skill_commands.add_parser("check", help="is a skill well formed? name, description, size, links, files nobody points at. Exit code 1 when there is an error")
    skill_check.add_argument("skills", nargs="*", help="a skill folder name under .github/skills/, or a path; none means every skill")
    skill_check.set_defaults(handler=lambda a: check_skills(a.skills))
    skill_list = skill_commands.add_parser("list", help="the skills of business domains, kept in the knowledge base (<knowledge base>/domains/<domain>/skills/): name, when to use it, path")
    skill_list.add_argument("--domain", action="append", default=None, help="only this domain (may be given more than once)")
    skill_list.set_defaults(handler=lambda a: list_domain_skills(a.domain))
    again = commands.add_parser("reinstall", help="carry the tasks, reports, goals, runtime, *.override.json and knowledge base of an older copy of the harness over to this one. Without --apply it only says what would be copied")
    again.add_argument("--from", dest="source", required=True, help="the old copy: an absolute path")
    again.add_argument("--apply", action="store_true", help="copy. A person at a terminal only. Never overwrites: what is here already is skipped and listed")
    again.set_defaults(handler=lambda a: reinstall.run(repo_root(), a.source, a.apply, check=check_after_reinstall))
    group = commands.add_parser("company", help="the company's content in <knowledge base>/company/: standards, skills, instructions")
    group_commands = group.add_subparsers(dest="company_command", required=True)
    compare = group_commands.add_parser("diff", help="compare <knowledge base>/company/ with its copies in .github/: what a sync would add, change or remove")
    compare.set_defaults(handler=lambda _args: company.diff(repo_root()))
    sync = group_commands.add_parser("sync", help="copy the company's skills and instructions to .github/, where Copilot finds them. A skill of the company's word that left company/ moves to .harness/runtime/company-backup/. Touches no other file")
    sync.set_defaults(handler=lambda _args: company.sync(repo_root(), remove=True))
    pack = group_commands.add_parser("pack", help="the owner: make a zip of what git has in the knowledge base, after checking it. The working tree must be clean")
    pack.add_argument("--out", required=True, help="the folder for the zip: an absolute path outside the knowledge base")
    pack.set_defaults(handler=lambda a: company.pack(repo_root(), a.out))
    update = group_commands.add_parser("update", help="put a package in the knowledge base. Without --apply it only says what would change")
    update.add_argument("--from", dest="source", required=True, help="the zip: an absolute path")
    update.add_argument("--apply", action="store_true", help="do it. A person at a terminal only. Files changed here are copied to .harness/runtime/company-backup/ first; then `company sync` runs")
    update.set_defaults(handler=lambda a: company.update(repo_root(), a.source, a.apply))
    link = commands.add_parser("toolpack", help="tool packs: what lets the agent work with one outside tool (its types, rules, skills, program). The factory packs are in .harness/toolpacks/; the knowledge base turns them on (company/tools/packs.json, `use`)")
    link_commands = link.add_subparsers(dest="toolpack_command", required=True)
    link_add = link_commands.add_parser("add", help="try a pack from a folder on this computer: its path is recorded and the pack is read where it lies (a person at a terminal only: its rules are the gate's rules)")
    link_add.add_argument("source", help="the folder that holds toolpack.json: an absolute path")
    link_add.add_argument("--replace", action="store_true", help="take this folder in place of the one added before under the same name")
    link_add.set_defaults(handler=lambda a: _toolpack_add(a.source, a.replace), person_only=True)
    link_list = link_commands.add_parser("list", help="the packs this computer knows: where each lies (harness, company, a folder), whether it is on, and whether it has what it needs: its files, its programs, a CA bundle")
    link_list.set_defaults(handler=lambda _a: toolpacks.check(repo_root()))
    link_check = link_commands.add_parser("check", help="check a tool pack: one known here by its name (all when none is given), or a folder before you add it. Exit code 1 when one is not ready")
    link_check.add_argument("name", nargs="?", default="", help="a name, or the path of a folder")
    link_check.set_defaults(handler=lambda a: toolpacks.check_folder(repo_root(), Path(a.name).expanduser()) if a.name and Path(a.name).expanduser().is_dir() else toolpacks.check(repo_root(), a.name))
    link_new = link_commands.add_parser("new", help="the skeleton of a tool pack to fill in (.harness/contracts/toolpack/README.md): in the company pack's tools/packs/ when there is one")
    link_new.add_argument("name", help="one word of small letters and digits")
    link_new.add_argument("--out", default="", help="the folder to make it in, instead")
    link_new.set_defaults(handler=lambda a: toolpacks.new(repo_root(), a.name, a.out))
    link_remove = link_commands.add_parser("remove", help="forget a folder added with `toolpack add` and take back the skills it put (to .harness/runtime/toolpack-backup/). A factory pack is turned off by taking it out of `use` in the knowledge base (a person at a terminal only)")
    link_remove.add_argument("name", help="the pack's name, or the folder")
    link_remove.set_defaults(handler=lambda a: _toolpack_remove(a.name), person_only=True)
    task_commands.register(commands)
    gate_commands.register(commands)
    observe_commands.register(commands)
    eval_commands.register(commands)
    return parser


def safe_streams() -> None:
    """A character the terminal encoding cannot show (a Chinese text on a Windows pipe) must not kill the command.

    On a pipe it is printed as UTF-8 (`output.encoding: auto` in the cli policy), on a terminal as \\uXXXX.
    `native` keeps the encoding of the pipe too, for a reader that does not decode UTF-8.
    """
    for name, stream in (("stdout", sys.stdout), ("stderr", sys.stderr)):
        try:
            encoding = output.encoding_for(stream)
            before = stream.encoding
            if encoding:
                stream.reconfigure(encoding=encoding, errors="backslashreplace")
                if output.setting() == output.AUTO:
                    output.REPLACED[name] = before
            else:
                stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, LookupError):
            pass


def main(argv=None) -> int:
    global ARGV
    ARGV = argv
    if argv is None:  # the `harness` command itself (not a test calling main): run on the Python the policy names, if one is
        pinpython.restart_if_pinned(repo_root())
    safe_streams()
    words = list(sys.argv[1:] if argv is None else argv)
    forced_json = JSON_FLAG in words
    args = build_parser().parse_args([word for word in words if word != JSON_FLAG])
    if args.command == "doctor":
        return doctor.run(repo_root(), accept=bool(getattr(args, "accept", False)))
    try:
        result = args.handler(args)
        code = result.pop("exit_code", 0) if isinstance(result, dict) else 0
        if isinstance(result, dict) and "_text" in result:  # a command for a person's eyes (`task list --text`)
            if result["_text"]:
                print(result["_text"])
            return code
        compact = isinstance(result, dict) and result.pop("_compact", False)  # a result an agent reads in bulk: no indentation
        person_next = result.pop("_next_person", None) if isinstance(result, dict) else None  # a command an agent and a person both run: what to tell each
        if output.as_text(sys.stdout, forced_json, getattr(args, "person_only", False)):
            if person_next:
                result["next"] = person_next
            shown = getattr(args, "render", None)  # a command's own text (the task list as a table), else the generic one
            print(shown(result) if shown else render.render(result))
            return code
        print(json.dumps(result, indent=None if compact else 2, separators=(",", ":") if compact else None, sort_keys=True, ensure_ascii=False))
        return code
    except Exception as error:
        said = f"harness: {error}"
        try:
            if sys.stderr.isatty():  # a person reads it: lines that fit, with commands kept whole
                said = "\n".join(render.wrap(said, render.columns(), "  "))
        except Exception:  # noqa: BLE001 - the error itself must always come out
            pass
        print(said, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
