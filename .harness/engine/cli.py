#!/usr/bin/env python3
"""Command line entry for agents and people: <python> .harness/engine/cli.py <command> (python on Windows, python3 elsewhere).

  doctor                       check that the harness files and config are consistent
  user                         the name of the person using this copy (for a change note that needs an author)
  task ...                     tasks: new, open, upgrade, list, fetch, diff, promote, review, snapshot, close (task module)
  target list|show|refs|init-kb  the target repositories; refs: where names are used; init-kb: make the knowledge base a git repository (task module)
  skill check [name|path ...]  is a skill well formed? (all skills when none is named)
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
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import messages, output, render, skillcheck, user  # noqa: E402
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
                print(version_banner(repo_root()))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Harness CLI")
    parser.add_argument("--version", action=ShowVersion)
    parser.add_argument(SHORT_FLAG, action="store_true", help="with --version: only `harness <version>`, one line")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="check harness files and config")
    check.set_defaults(handler=None)
    name = commands.add_parser("user", help="the name of the person using this copy (user.override.json, else git config user.name)")
    name.set_defaults(handler=lambda _args: user.who(repo_root()))
    skill = commands.add_parser("skill", help="the skills in .github/skills/")
    skill_commands = skill.add_subparsers(dest="skill_command", required=True)
    skill_check = skill_commands.add_parser("check", help="is a skill well formed? name, description, size, links, files nobody points at. Exit code 1 when there is an error")
    skill_check.add_argument("skills", nargs="*", help="a skill folder name under .github/skills/, or a path; none means every skill")
    skill_check.set_defaults(handler=lambda a: check_skills(a.skills))
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
    safe_streams()
    words = list(sys.argv[1:] if argv is None else argv)
    forced_json = JSON_FLAG in words
    args = build_parser().parse_args([word for word in words if word != JSON_FLAG])
    if args.command == "doctor":
        return doctor.run(repo_root())
    try:
        result = args.handler(args)
        code = result.pop("exit_code", 0) if isinstance(result, dict) else 0
        if isinstance(result, dict) and "_text" in result:  # a command for a person's eyes (`task list --text`)
            if result["_text"]:
                print(result["_text"])
            return code
        compact = isinstance(result, dict) and result.pop("_compact", False)  # a result an agent reads in bulk: no indentation
        if output.as_text(sys.stdout, forced_json, getattr(args, "person_only", False)):
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
