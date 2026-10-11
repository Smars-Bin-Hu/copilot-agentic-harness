"""CLI commands of the observe module.

  stats                numbers from the session logs: prompts, refusals, review verdicts, hook time
  kb reads             which knowledge base files the tasks read, and which nobody read
  logs prune           delete session logs not written to for N days (a person decides; no hook deletes anything)
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core.paths import repo_root

from . import kbstats, prune, stats


def cmd_stats(args: argparse.Namespace) -> Dict[str, Any]:
    return stats.collect(repo_root(), args.session_id, args.surface, args.days)


def cmd_prune(args: argparse.Namespace) -> Dict[str, Any]:
    return prune.prune(repo_root(), args.days, args.dry_run)


def register(subparsers: Any) -> None:
    stats_parser = subparsers.add_parser("stats", help="counts and times from the session logs")
    stats_parser.add_argument("--session-id", default="", help="only this session")
    stats_parser.add_argument("--surface", default="", choices=["", "vscode"])
    stats_parser.add_argument("--days", type=int, default=None, help="only the calls of the last N days")
    stats_parser.set_defaults(handler=cmd_stats)

    kb = subparsers.add_parser("kb", help="the knowledge base")
    kb_commands = kb.add_subparsers(dest="kb_command", required=True)
    reads = kb_commands.add_parser("reads", help="which knowledge base files were read, by which tasks, and which nobody read")
    reads.add_argument("--days", type=int, default=None, help="only the calls of the last N days")
    reads.add_argument("--task", default="", help="only what this task read")
    reads.set_defaults(handler=lambda a: kbstats.collect(repo_root(), a.days, a.task))

    logs = subparsers.add_parser("logs", help="the session logs")
    commands = logs.add_subparsers(dest="logs_command", required=True)
    prune_parser = commands.add_parser("prune", help="delete session logs not written to for N days")
    prune_parser.add_argument("--days", type=int, required=True)
    prune_parser.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    prune_parser.set_defaults(handler=cmd_prune)
