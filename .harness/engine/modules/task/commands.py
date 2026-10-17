"""CLI commands of the task module.

  task new|open|upgrade|list                 the life of a task (tasklife.py); list --text|--watch: the board in a terminal
  task board                                 the board as a page (taskboard.py)
  task queue                                 the promote queue: who holds a repository, who is in line (taskqueue.py)
  task status|fetch|delete|diff|set-branch|promote|close|report      the work on a task (task.py)
  task autorun on|off|status                 autorun, beta: down TODO.md without a person; on is a person at a terminal (autorun.py)
  task pause|resume                          a person puts a task aside and takes it back (tasklife.py)
  task approve-plan|approve-promote|recover  a person at a terminal
  task review start|status                   independent checks, `[review]=n` (taskreview.py); extend|waive: a person at a terminal
  task snapshot list|prune                   the copies made at the gates (tasksnap.py)
  target list|show                           the target repositories (policy target.json): where they are, what their base branch is
  target refs <name>...                      where names are used: every target repository and the knowledge base, in one search (refs.py)
  target init-kb                             make knowledge-base/ a git repository (kbsetup.py), so that a task can update it
"""

from __future__ import annotations

import argparse
from typing import Any, Dict

from core import approval, render, targets, tasks
from core.paths import repo_root

from . import autorun, boardserve, kbsetup, taskarchive, refs, task, task_report, taskboard, tasklife, taskqueue, taskreview, tasksnap


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


def cmd_new(args: argparse.Namespace) -> Dict[str, Any]:
    if args.domain:
        tasklife.known_domains(repo_root(), args.domain)  # a wrong name stops it before the task is made
    result = tasklife.new(repo_root(), args.name, args.kind, args.tier, args.session_id, args.surface)
    if args.domain:
        named = tasklife.set_domains(repo_root(), result["task"], args.domain)
        result.update(domains=named["domains"], domain_skills=named["skills"])
        result["next"] = f"{result.get('next', '')} {named['next']}".strip()
    return result


def list_text(result: Dict[str, Any]) -> str:
    """`task list` on a terminal: the table of `--text`."""
    return taskboard.table(result) if "tasks" in result else render.render(result)


def cmd_board(args: argparse.Namespace) -> Dict[str, Any]:
    person = approval.is_person()
    if args.serve or (person and not args.once and args.refresh is None and not args.no_serve):  # a person gets the server by default
        return boardserve.serve(repo_root(), args.all, args.port)
    refresh = taskboard.refresh_seconds(args.refresh, args.once, person)
    if refresh > 0:
        return taskboard.keep_fresh(repo_root(), args.all, refresh, (lambda board: taskboard.open_in_browser(repo_root(), board)) if args.open else None)
    result = taskboard.board(repo_root(), args.all)
    if args.open:
        result["opened"] = taskboard.open_in_browser(repo_root(), result["board"])
    return result


def cmd_report(args: argparse.Namespace) -> Dict[str, Any]:
    result = task_report.generate(repo_root(), args.task, args.detail)
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

    new = commands.add_parser("new", help="make a task under .workspace/sandbox/tasks/ with the files of its tier; this session picks it up")
    new.add_argument("name", help="the task name: the folder name, no slashes")
    new.add_argument("--kind", required=True, choices=list(tasks.KINDS), help="qa, rca, design (a design or a plan), dev, test, kb (a knowledge base update), other (a broad question or a case that fits none of these; the standard of done is agreed with the person and written in REQ.md)")
    new.add_argument("--tier", default="", choices=["", *tasks.TIERS], help="light: TASK.md only; medium: + REQ.md, REQ/, REF/, LOG.md; full: + TODO.md, DEV/, TEST/. Default: by kind")
    new.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    new.add_argument("--surface", default="vscode", choices=["vscode"])
    new.add_argument("--domain", action="append", default=None, help="a business domain of the task (may be given more than once); the same as `task set-domain` after it")
    new.set_defaults(handler=cmd_new)
    open_parser = commands.add_parser("open", help="this session picks up a task that exists; a closed task is opened again")
    open_parser.add_argument("name", help="the task name, or its folder")
    open_parser.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    open_parser.add_argument("--surface", default="vscode", choices=["vscode"])
    open_parser.set_defaults(handler=lambda a: tasklife.open_task(repo_root(), a.name, a.session_id, a.surface))
    domain = add("set-domain", "the business domains the task is about (folders under <knowledge base>/domains/); the agent is then told their skills", lambda a: tasklife.set_domains(repo_root(), a.task, a.domains))
    domain.add_argument("domains", nargs="+", help="domain names")
    upgrade = add("upgrade", "give the task a higher tier: missing files are added, existing ones are left alone", lambda a: tasklife.upgrade(repo_root(), a.task, a.tier))
    upgrade.add_argument("--tier", required=True, choices=list(tasks.TIERS))
    listing = commands.add_parser("list", help="every open task: kind, tier, what it waits for; --all adds the closed ones")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--text", action="store_true", help="a table for a person to read, not JSON")
    listing.add_argument("--watch", action="store_true", help="the table, drawn again every --interval seconds until Ctrl+C")
    listing.add_argument("--interval", type=float, default=5.0)
    listing.set_defaults(handler=cmd_list, render=list_text)
    line = commands.add_parser("queue", help="the promote queue: per target repository, whose files wait for a commit and which tasks are in line")
    line.set_defaults(handler=lambda a: taskqueue.queue(repo_root()))
    board = commands.add_parser("board", help="the board of every task: what it waits for, its time and usage. A person at a terminal gets it served with the task pages and buttons that act; --once writes .workspace/reports/board.html and returns")
    board.add_argument("--all", action="store_true", help="the closed tasks too")
    board.add_argument("--refresh", type=int, default=None, help=f"keep the board fresh: write it again every N seconds until Ctrl+C, and the pages load themselves again. For a person at a terminal this is on by itself, every {taskboard.DEFAULT_REFRESH} seconds; 0 is the same as --once")
    board.add_argument("--open", action="store_true", help="open the page in the browser (a person at a terminal)")
    how = board.add_mutually_exclusive_group()
    how.add_argument("--once", action="store_true", help="write the pages once and return: what an agent runs (the gate refuses `task board` without it from an agent). A script or a pipe gets this anyway")
    how.add_argument("--serve", action="store_true", help="serve the board on 127.0.0.1 with the task pages and buttons that act, until Ctrl+C. What a person at a terminal gets anyway; the browser it opens is paired with a code no one sees")
    how.add_argument("--no-serve", action="store_true", help="a person at a terminal: keep the page on disk fresh instead of serving it (no buttons that act, no task pages)")
    board.add_argument("--port", type=int, default=None, help="with --serve: the port (default: board.port in task.json)")
    board.set_defaults(handler=cmd_board)
    shelf = commands.add_parser("archive", help="move closed tasks out of .workspace/sandbox/tasks/ into a folder you choose, usually outside the repository; one way. Without --apply it only says what would move")
    shelf.add_argument("names", nargs="*", help="task names; none and no --all: list what can be archived")
    shelf.add_argument("--all", action="store_true", help="every closed task that can be archived")
    shelf.add_argument("--to", default="", help="the folder (an absolute path; made when missing). Left out: archive_to in user.override.json")
    shelf.add_argument("--apply", action="store_true", help="move them. Without it nothing moves")
    shelf.add_argument("--remember", action="store_true", help="with --apply: keep --to as archive_to in user.override.json (this computer only)")
    shelf.set_defaults(handler=lambda a: taskarchive.archive(repo_root(), a.names, a.all, a.to, a.apply, a.remember))
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
    extend.set_defaults(person_only=True)
    extend.add_argument("--checks", type=int, default=2, choices=range(1, 10), metavar="1-9")
    add_review("waive", "the person lets this version of the result be promoted without the passes (terminal only)", lambda a: taskreview.waive(repo_root(), a.task)).set_defaults(person_only=True)
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
    add("approve-plan", "the person approves PLAN.md (terminal only)", lambda a: task.approve_plan(repo_root(), a.task)).set_defaults(person_only=True)
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
    add("approve-promote", "the person approves the plan of the last task promote --dry-run (terminal only)", lambda a: task.approve_promote(repo_root(), a.task)).set_defaults(person_only=True)
    add("recover", "the person puts the repositories back after a task promote stopped halfway (terminal only)", lambda a: task.recover(repo_root(), a.task)).set_defaults(person_only=True)
    add("pause", "the person puts the task aside: the board stops saying it waits, the time aside is not counted as waiting (terminal only)", lambda a: tasklife.pause(repo_root(), a.task)).set_defaults(person_only=True)
    add("resume", "the person takes a task back that was put aside (terminal only); a prompt in the task's session does the same", lambda a: tasklife.resume(repo_root(), a.task)).set_defaults(person_only=True)
    auto = commands.add_parser("autorun", help="autorun (beta): the agent goes down TODO.md by itself and stops where a person is needed")
    auto_commands = auto.add_subparsers(dest="autorun_command", required=True)

    def add_auto(name: str, text: str, handler: Any) -> argparse.ArgumentParser:
        item = auto_commands.add_parser(name, help=text)
        item.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
        item.set_defaults(handler=handler)
        return item

    add_auto("on", "the person turns autorun on for the task (terminal only, a typed code)", lambda a: autorun.turn_on(repo_root(), a.task)).set_defaults(person_only=True)
    off = add_auto("off", "turn autorun off: the person at a terminal, or the agent with --reason when it cannot go on", lambda a: autorun.turn_off(repo_root(), a.task, a.reason))
    off.add_argument("--reason", default="")
    add_auto("status", "on or off, the steps done, how often it was pushed on, why it stopped", lambda a: autorun.status(repo_root(), a.task))
    close = add("close", "the session lets go of the task and the report is written; the folder stays where it is", lambda a: task.close(repo_root(), a.task, a.reason))
    close.add_argument("--reason", default="")
    report = add("report", "write .workspace/reports/tasks/<name>/report.md (what was done) and report.html (where the time and usage went)", cmd_report)
    report.add_argument("--open", action="store_true", help="open the HTML page in the browser (a person at a terminal)")
    report.add_argument("--detail", action="store_true", help="add the slowest prompts, the tools and the checks to `insight` (more to read)")


def register(subparsers: Any) -> None:
    register_task(subparsers)
    target = subparsers.add_parser("target", help="the target repositories")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    target_list = target_commands.add_parser("list", help="every target repository: path, base branch, its commit, clean or not")
    target_list.set_defaults(handler=cmd_target_list)
    target_show = target_commands.add_parser("show", help="one target repository")
    target_show.add_argument("--repo", required=True, help="the repository name (the folder name under repos_root)")
    target_show.set_defaults(handler=cmd_target_show)
    init_kb = target_commands.add_parser("init-kb", help="make knowledge-base/ a git repository (init, branch = base branch, first commit) so that a task can update it; one that is a git repository already is left as it is")
    init_kb.set_defaults(handler=lambda a: kbsetup.init(repo_root()))
    find = target_commands.add_parser("refs", help="where are these names used? One search over every target repository (the committed base branch) and the knowledge base, with their spellings; for the impact of a change")
    find.add_argument("terms", nargs="+", help="names: a table, a column, a procedure, a job, a config key. At least 3 characters; for a common column name give `table.column`")
    find.add_argument("--repo", default="", help="only this repository")
    find.add_argument("--no-kb", action="store_true", help="leave the knowledge base folder out")
    find.add_argument("--exact", action="store_true", help="count only whole-word hits, not a name inside a longer name")
    find.add_argument("--no-variants", action="store_true", help="search the names as typed, without the snake, kebab, joined and spaced spellings")
    find.add_argument("--max-files", type=int, default=30, help="files shown per repository (the rest are counted)")
    find.add_argument("--lines", type=int, default=2, help="sample lines shown per file")
    find.set_defaults(handler=lambda a: refs.refs(repo_root(), a.terms, a.repo, a.no_kb, not a.no_variants, a.exact, a.max_files, a.lines))
