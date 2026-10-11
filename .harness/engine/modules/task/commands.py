"""CLI commands of the task module.

  task new|open|upgrade|list                 the life of a task (tasklife.py); list --text|--watch: the board in a terminal
  task board                                 the board as a page (taskboard.py)
  task status|fetch|delete|diff|set-branch|promote|close|report      the work on a task (task.py)
  task approve-plan|approve-promote|recover  a person at a terminal
  task review start|status                   independent checks, `[review]=n` (taskreview.py); extend|waive: a person at a terminal
  task snapshot list|prune                   the copies made at the gates (tasksnap.py)
  target list|show                           the target repositories (policy target.json): where they are, what their base branch is
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core import messages, targets, tasks
from core.paths import cli_command, repo_root

from . import task, task_report, taskboard, tasklife, taskreview, tasksnap
from .common import CommandError


def gone(_args: argparse.Namespace) -> Dict[str, Any]:
    raise CommandError(messages.text("task.start.gone", command=cli_command()))


def cmd_target_list(args: argparse.Namespace) -> Dict[str, Any]:
    found = targets.load(repo_root())
    return {
        "configured": found.configured,
        "repos": [targets.summary(found.repos[name], found.timeout) for name in found.names()],
        "problems": found.problems,
    }


def cmd_target_show(args: argparse.Namespace) -> Dict[str, Any]:
    found = targets.load(repo_root())
    return targets.summary(found.get(args.repo), found.timeout)


def cmd_list(args: argparse.Namespace) -> Dict[str, Any]:
    if args.watch:
        return taskboard.watch(repo_root(), args.all, args.interval)
    result = tasklife.list_tasks(repo_root(), args.all)
    return {"_text": taskboard.table(result)} if args.text else result


def cmd_board(args: argparse.Namespace) -> Dict[str, Any]:
    result = taskboard.board(repo_root(), args.all, max(0, args.refresh))
    if args.open:
        result["opened"] = taskboard.open_in_browser(repo_root(), result["board"])
    return result


def cmd_report(args: argparse.Namespace) -> Dict[str, Any]:
    result = task_report.generate(repo_root(), args.task)
    if args.open and result.get("analysis"):
        result["opened"] = taskboard.open_in_browser(repo_root(), result["analysis"])
    return result


def register_task(subparsers: Any) -> None:
    parser = subparsers.add_parser("task", help="tasks: a folder per task, a plan and a promote the person approves, independent checks")
    commands = parser.add_subparsers(dest="task_command", required=True)

    def add(name: str, text: str, handler: Any, required: bool = False) -> argparse.ArgumentParser:
        item = commands.add_parser(name, help=text)
        item.add_argument("--task", required=required, default="", help="the task folder (or just its name); left out, the one open task")
        item.set_defaults(handler=handler)
        return item

    start = commands.add_parser("start", help="removed in 1.1.0: use `task new` or `task open`")
    for old in ("--task", "--session-id", "--surface", "--branch"):  # what the old command took, so the answer is the pointer and not a usage error
        start.add_argument(old, default="")
    start.add_argument("rest", nargs="*")
    start.set_defaults(handler=gone)
    new = commands.add_parser("new", help="make a task under .workspace/sandbox/tasks/ with the files of its tier; this session picks it up")
    new.add_argument("name", help="the task name: the folder name, no slashes")
    new.add_argument("--kind", required=True, choices=list(tasks.KINDS), help="qa, rca, design (a design or a plan), dev, test, kb (a knowledge base update), other (a broad question or a case that fits none of these; the standard of done is agreed with the person and written in REQ.md)")
    new.add_argument("--tier", default="", choices=["", *tasks.TIERS], help="light: TASK.md only; medium: + REQ.md, REQ/, REF/, LOG.md; full: + TODO.md, DEV/, TEST/. Default: by kind")
    new.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    new.add_argument("--surface", default="vscode", choices=["vscode"])
    new.set_defaults(handler=lambda a: tasklife.new(repo_root(), a.name, a.kind, a.tier, a.session_id, a.surface))
    open_parser = commands.add_parser("open", help="this session picks up a task that exists; a closed task is opened again")
    open_parser.add_argument("name", help="the task name, or its folder")
    open_parser.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    open_parser.add_argument("--surface", default="vscode", choices=["vscode"])
    open_parser.set_defaults(handler=lambda a: tasklife.open_task(repo_root(), a.name, a.session_id, a.surface))
    upgrade = add("upgrade", "give the task a higher tier: missing files are added, existing ones are left alone", lambda a: tasklife.upgrade(repo_root(), a.task, a.tier))
    upgrade.add_argument("--tier", required=True, choices=list(tasks.TIERS))
    listing = commands.add_parser("list", help="every open task: kind, tier, what it waits for; --all adds the closed ones")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--text", action="store_true", help="a table for a person to read, not JSON")
    listing.add_argument("--watch", action="store_true", help="the table, drawn again every --interval seconds until Ctrl+C")
    listing.add_argument("--interval", type=float, default=5.0)
    listing.set_defaults(handler=cmd_list)
    board = commands.add_parser("board", help="write .workspace/reports/board.html: every task, what it waits for, its time and usage")
    board.add_argument("--all", action="store_true", help="the closed tasks too")
    board.add_argument("--refresh", type=int, default=0, help="the page loads itself again every N seconds (run the command again to renew the numbers)")
    board.add_argument("--open", action="store_true", help="open the page in the browser (a person at a terminal)")
    board.set_defaults(handler=cmd_board)
    review = commands.add_parser("review", help="independent checks of a task ([review]=n): start a check, see the count; extend and waive are the person's")
    review_commands = review.add_subparsers(dest="review_command", required=True)

    def add_review(name: str, text: str, handler: Any) -> argparse.ArgumentParser:
        item = review_commands.add_parser(name, help=text)
        item.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
        item.set_defaults(handler=handler)
        return item

    add_review("start", "snapshot the result, write REVIEW/round-NNN/package.md and open the check; then call the reviewer", lambda a: taskreview.start(repo_root(), a.task))
    add_review("status", "n, the passes that count now, the checks used and what comes next", lambda a: taskreview.status(repo_root(), a.task))
    extend = add_review("extend", "the person allows more checks after the limit (terminal only)", lambda a: taskreview.extend(repo_root(), a.task, a.checks))
    extend.add_argument("--checks", type=int, default=2, choices=range(1, 10), metavar="1-9")
    add_review("waive", "the person lets this version of the result be promoted without the passes (terminal only)", lambda a: taskreview.waive(repo_root(), a.task))
    snapshot = commands.add_parser("snapshot", help="the copies of a task's result made at its gates (plan approval, each check, promote dry-run)")
    snapshot_commands = snapshot.add_subparsers(dest="snapshot_command", required=True)
    snapshot_list = snapshot_commands.add_parser("list", help="every snapshot of the task: gate, time, files")
    snapshot_list.add_argument("--task", default="")
    snapshot_list.set_defaults(handler=lambda a: {"snapshots": tasksnap.snapshots(repo_root(), task.resolve(repo_root(), a.task))})
    snapshot_prune = snapshot_commands.add_parser("prune", help="remove snapshots older than --days (default: the policy); the newest always stays")
    snapshot_prune.add_argument("--task", default="")
    snapshot_prune.add_argument("--days", type=float, default=None)
    snapshot_prune.add_argument("--dry-run", action="store_true")
    snapshot_prune.set_defaults(handler=lambda a: {"removed": tasksnap.prune(repo_root(), task.resolve(repo_root(), a.task), a.days if a.days is not None else tasksnap.settings(repo_root())["keep_days"], dry_run=a.dry_run), "dry_run": a.dry_run})
    add("status", "where the task stands and what comes next", lambda a: task.status(repo_root(), a.task))
    add("approve-plan", "the person approves PLAN.md (terminal only)", lambda a: task.approve_plan(repo_root(), a.task))
    fetch = add("fetch", "copy files of a target repository's base branch into DEV/<repo>/<path>", lambda a: task.fetch(repo_root(), a.task, a.paths, a.overwrite))
    fetch.add_argument("paths", nargs="+", help="<repo>/<path>: a file or a folder")
    fetch.add_argument("--overwrite", action="store_true", help="take the base version again over a file already changed in DEV/")
    delete = add("delete", "a fetched file is to be deleted in the repository", lambda a: task.delete(repo_root(), a.task, a.paths))
    delete.add_argument("paths", nargs="+", help="<repo>/<path>")
    add("diff", "what DEV/ changes against the fetched versions; writes CHANGES.diff", lambda a: task.diff(repo_root(), a.task))
    branch = add("set-branch", "set the feature branch name", lambda a: task.set_branch(repo_root(), a.task, a.branch))
    branch.add_argument("--branch", required=True)
    promote_parser = add("promote", "write DEV/ onto a new branch of each target repository", lambda a: task.run_promote(repo_root(), a.task, a.dry_run))
    promote_parser.add_argument("--dry-run", action="store_true")
    add("approve-promote", "the person approves the plan of the last task promote --dry-run (terminal only)", lambda a: task.approve_promote(repo_root(), a.task))
    add("recover", "the person puts the repositories back after a task promote stopped halfway (terminal only)", lambda a: task.recover(repo_root(), a.task))
    close = add("close", "the session lets go of the task and the report is written; the folder stays where it is", lambda a: task.close(repo_root(), a.task, a.reason))
    close.add_argument("--reason", default="")
    report = add("report", "write .workspace/reports/task-<name>.md (what was done) and task-<name>.html (where the time and usage went)", cmd_report)
    report.add_argument("--open", action="store_true", help="open the HTML page in the browser (a person at a terminal)")


def register(subparsers: Any) -> None:
    register_task(subparsers)
    target = subparsers.add_parser("target", help="the target repositories")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    target_list = target_commands.add_parser("list", help="every target repository: path, base branch, its commit, clean or not")
    target_list.set_defaults(handler=cmd_target_list)
    target_show = target_commands.add_parser("show", help="one target repository")
    target_show.add_argument("--repo", required=True, help="the repository name (the folder name under repos_root)")
    target_show.set_defaults(handler=cmd_target_show)
