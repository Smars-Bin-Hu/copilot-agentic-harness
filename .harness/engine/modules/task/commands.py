"""CLI commands of the task module.

  task new|open|upgrade|list                 the life of a task (tasklife.py); list --text|--watch: the board in a terminal
  task board                                 the board as a page (taskboard.py)
  task queue                                 the promote queue: who holds a repository, who is in line (taskqueue.py)
  task status|fetch|delete|diff|set-branch|promote|close|report      the work on a task (task.py)
  task autorun on|off|status                 autorun, beta: down TODO.md without a person; on is a person at a terminal (autorun.py)
  task pause|resume                          a person puts a task aside and takes it back (tasklife.py)
  task handoff tests|run --env E | clear     the agent hands the tests of an environment, or a run before the write-back, to the person; the board says it waits (tasklife.py)
  task approve-plan|confirm-req|approve-promote|recover  a person at a terminal
  task review start|status                   independent checks, `[review]=n` (taskreview.py); extend|waive|dismiss: a person at a terminal
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

from . import autorun, boardserve, common, intake, kbsetup, taskarchive, refs, task, runrecord, task_report, taskboard, taskfork, tasklife, taskqueue, taskreview, tasksnap, testdefects, testrecord


def read_text_argument(path: str) -> str:
    import sys
    from pathlib import Path

    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).expanduser().read_text(encoding="utf-8-sig")
    except OSError as error:
        raise common.CommandError(str(error)) from None


def intake_convert(args: argparse.Namespace) -> Dict[str, Any]:
    from pathlib import Path

    results = []
    for raw in args.files:
        path = Path(raw).expanduser()
        try:
            data = path.read_bytes()
        except OSError as error:
            raise common.CommandError(f"{raw}: {error.strerror or error}") from None
        results.append(intake.add_file(repo_root(), args.task, path.name, data, args.include_hidden))
    return results[0] if len(results) == 1 else {"converted": results, "next": results[-1]["next"]}


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
        tasklife.known_domains(repo_root(), args.domain, new_ok=args.kind == "kb")  # a wrong name stops it before the task is made
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
        return boardserve.serve(repo_root(), True, args.port)
    refresh = taskboard.refresh_seconds(args.refresh, args.once, person)
    if refresh > 0:
        return taskboard.keep_fresh(repo_root(), True, refresh, (lambda board: taskboard.open_in_browser(repo_root(), board)) if args.open else None)
    result = taskboard.board(repo_root(), True)
    if args.open:
        result["opened"] = taskboard.open_in_browser(repo_root(), result["board"])
    return result


def guarded(command: str, call: Any) -> Any:
    """What the person decides or changes with a command: a person at a terminal is stopped while the agent is in the middle of a turn (it may be
    answering a doubt about the result; the person decides after it has stopped). `--force` goes on."""
    def run(args: argparse.Namespace) -> Dict[str, Any]:
        if approval.is_person() and not getattr(args, "force", False):
            root = repo_root()
            data = tasks.read(root, task.resolve(root, args.task))
            if data is not None:
                tasklife.require_idle(root, data, command)
        return call(args)

    return run


def with_force(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--force", action="store_true", help="even while the agent is in the middle of a turn")
    return parser


def close_task(args: argparse.Namespace) -> Dict[str, Any]:
    """`task close`: the agent closes a task it finished (that is its own turn); a person at a terminal is stopped while the agent is at work."""
    if approval.is_person() and not args.force:
        root = repo_root()
        folder = task.resolve(root, args.task)
        data = tasks.read(root, folder)
        if data is not None:
            tasklife.require_idle(root, data, "task close")
    return task.close(repo_root(), args.task, args.reason, getattr(args, "todo_open", ""))


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
    forked = commands.add_parser("fork", help="make a new task from a task that is done: its conclusions and materials are copied into REF/from-<old>/ (never its state, its checks or DEV/); this session picks up the new task")
    forked.add_argument("name", help="the new task's name")
    forked.add_argument("--from", dest="source", required=True, help="the task to start from (its name or folder); it is not changed")
    forked.add_argument("--kind", required=True, choices=list(tasks.KINDS))
    forked.add_argument("--tier", default="", choices=["", *tasks.TIERS], help="default: by kind")
    forked.add_argument("--session-id", required=True, help="the session id written at the top of the prompt rules")
    forked.add_argument("--surface", default="vscode", choices=["vscode"])
    forked.set_defaults(handler=lambda a: taskfork.fork(repo_root(), a.name, a.source, a.kind, a.tier, a.session_id, a.surface))
    off = commands.add_parser("offwork", help="the person leaves for the day: every open task that is not at work is paused at once (terminal or board only)")
    off.set_defaults(handler=lambda a: tasklife.offwork(repo_root()), person_only=True)
    on = commands.add_parser("onwork", help="back at work: the tasks offwork paused are taken back; one paused by hand stays paused")
    on.set_defaults(handler=lambda a: tasklife.onwork(repo_root()), person_only=True)
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
    board = commands.add_parser("board", help="the board of every task, the newest closed ones too: what it waits for, its time and usage. A person at a terminal gets it served with the task pages and buttons that act; --once writes .workspace/reports/board.html and returns")
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
    extend = add_review("extend", "the person allows more checks after the limit (terminal only)", guarded("task review extend", lambda a: taskreview.extend(repo_root(), a.task, a.checks)))
    extend.set_defaults(person_only=True)
    with_force(extend)
    extend.add_argument("--checks", type=int, default=2, choices=range(1, 10), metavar="1-9")
    waive = add_review("waive", "the person lets this version of the result be promoted without the passes (terminal only)", guarded("task review waive", lambda a: taskreview.waive(repo_root(), a.task)))
    waive.set_defaults(person_only=True)
    with_force(waive)
    dismiss = add_review("dismiss", "the person says a check judged wrong: it no longer counts, as a check used or as a FAIL (terminal only)", guarded("task review dismiss", lambda a: taskreview.dismiss(repo_root(), a.task, a.round)))
    dismiss.set_defaults(person_only=True)
    with_force(dismiss)
    dismiss.add_argument("--round", type=int, default=0, help="the number of the check (round-NNN); left out, the newest that did not pass")
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
    approve = with_force(add("approve-plan", "the person approves PLAN.md (terminal only; refused while the agent is at work)", guarded("task approve-plan", lambda a: task.approve_plan(repo_root(), a.task, with_req=a.with_req))))
    approve.set_defaults(person_only=True)
    approve.add_argument("--with-req", action="store_true", help="REQ.md is not confirmed yet: confirm it and approve the plan with one code")
    with_force(add("confirm-req", "the person confirms REQ.md says what they meant (terminal only); the harness fills the confirmation line", guarded("task confirm-req", lambda a: task.confirm_req(repo_root(), a.task)))).set_defaults(person_only=True)
    fetch = add("fetch", "copy files of a target repository's base branch into DEV/<repo>/<path>", lambda a: task.fetch(repo_root(), a.task, a.paths, a.overwrite, a.rebase))
    fetch.add_argument("paths", nargs="+", help="<repo>/<path>: a file or a folder")
    fetch.add_argument("--overwrite", action="store_true", help="take the base version again over a file already changed in DEV/")
    fetch.add_argument("--rebase", action="store_true", help="the file changed on main since it was fetched: take main as it is now (your changes in DEV/ to it are dropped; make them again)")
    delete = add("delete", "a fetched file is to be deleted in the repository", lambda a: task.delete(repo_root(), a.task, a.paths))
    delete.add_argument("paths", nargs="+", help="<repo>/<path>")
    add("diff", "what DEV/ changes against the fetched versions; writes CHANGES.diff", lambda a: task.diff(repo_root(), a.task))
    branch = add("set-branch", "set the feature branch name", lambda a: task.set_branch(repo_root(), a.task, a.branch))
    branch.add_argument("--branch", required=True)
    promote_parser = add("promote", "write DEV/ onto a new branch of each target repository", lambda a: task.run_promote(repo_root(), a.task, a.dry_run))
    promote_parser.add_argument("--dry-run", action="store_true")
    with_force(add("approve-promote", "the person approves the plan of the last task promote --dry-run (terminal only; refused while the agent is at work)", guarded("task approve-promote", lambda a: task.approve_promote(repo_root(), a.task)))).set_defaults(person_only=True)
    with_force(add("recover", "the person puts the repositories back after a task promote stopped halfway (terminal only; refused while the agent is at work)", guarded("task recover", lambda a: task.recover(repo_root(), a.task)))).set_defaults(person_only=True)
    pause = add("pause", "the person puts the task aside: the board stops saying it waits, the time aside is not counted as waiting (terminal only; refused while the agent is at work)", lambda a: tasklife.pause(repo_root(), a.task, force=a.force))
    pause.set_defaults(person_only=True)
    pause.add_argument("--force", action="store_true", help="even while the agent is in the middle of a turn")
    add("resume", "the person takes a task back that was put aside (terminal only); a prompt in the task's session does the same", lambda a: tasklife.resume(repo_root(), a.task)).set_defaults(person_only=True)
    defects = commands.add_parser("defects", help="the defects of a test task (TEST/defects.md): their status follows the results")
    defects_commands = defects.add_subparsers(dest="defects_command", required=True)
    defects_sync = defects_commands.add_parser("sync", help="mark `[open]` defects `[fixed]` where the verdict of their environment is PASS; the only way a defect is marked fixed")
    defects_sync.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    defects_sync.set_defaults(handler=lambda a: testdefects.sync(repo_root(), task.resolve(repo_root(), a.task)))
    test = commands.add_parser("test", help="a test task: record the results of an environment (the script writes the file, the verdict and the status files)")
    test_commands = test.add_subparsers(dest="test_command", required=True)
    record = test_commands.add_parser("record", help="add a run to TEST/results-<environment>.md from what the user gave back and one row for each criterion; the verdict is worked out from the rows")
    record.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    record.add_argument("--env", required=True, help="the environment, as the test guide names it")
    record.add_argument("--given-file", default="", help="a file with the user's results as they gave them (it is copied in whole); may be left out when the user gave only pictures (--evidence)")
    record.add_argument("--row", action="append", default=[], help="`criterion::evidence::PASS|FAIL|NEEDS MORE`, one for each criterion of the environment; PASS needs its evidence")
    record.add_argument("--run-by", default="", help="who ran it and when, as the user said")
    record.add_argument("--follow-up", default="", help="one line: what comes next")
    record.add_argument("--ran-file", default="", help="a file with the commands the user ran, as they ran them (shown in the run as what was run)")
    record.add_argument("--evidence", action="append", default=[], help="a picture the user gave (a screenshot): `PATH` or `PATH::what it shows`; copied into TEST/evidence/<ENV>/ and shown in the run. Repeat for each picture")
    record.set_defaults(handler=lambda a: testrecord.record(repo_root(), a.task, a.env, a.given_file, a.row, a.run_by, a.follow_up, a.ran_file, a.evidence))
    run = commands.add_parser("run", help="a development task: record the result of a run the user did in an environment before the write-back (the script writes RUNS/<ENV>/results.md)")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    run_record = run_commands.add_parser("record", help="add a run to RUNS/<environment>/results.md from what the user gave back (output, commands, screenshots); takes the handoff of that environment away")
    run_record.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    run_record.add_argument("--env", required=True, help="the environment, for example DEV")
    run_record.add_argument("--given-file", default="", help="a file with the user's output as they gave it (it is copied in whole); may be left out when the user gave only pictures")
    run_record.add_argument("--ran-file", default="", help="a file with the commands the user ran, as they ran them")
    run_record.add_argument("--evidence", action="append", default=[], help="a picture the user gave: `PATH` or `PATH::what it shows`; copied into RUNS/<ENV>/evidence/. Repeat for each picture")
    run_record.add_argument("--run-by", default="", help="who ran it and when, as the user said")
    run_record.add_argument("--follow-up", default="", help="one line: what comes next")
    run_record.set_defaults(handler=lambda a: runrecord.record(repo_root(), a.task, a.env, a.given_file, a.run_by, a.ran_file, a.evidence, a.follow_up))
    intake_parser = commands.add_parser("intake", help="the documents a business gave (docx, xlsx, ...) as files the agent can read, in REQ/ of a task; no AI is used")
    intake_commands = intake_parser.add_subparsers(dest="intake_command", required=True)
    convert_parser = intake_commands.add_parser("convert", help="put files in REQ/: the original is kept in REQ/originals/, its text (Markdown, CSV) is written in REQ/, with a report of what was left out")
    convert_parser.add_argument("files", nargs="+", help="the files to convert: .docx, .xlsx, (.xls, .pdf when their package is installed), text and picture files")
    convert_parser.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    convert_parser.add_argument("--include-hidden", action="store_true", help="also convert hidden sheets, rows and columns of a workbook")
    convert_parser.set_defaults(handler=lambda a: intake_convert(a))
    paste_parser = intake_commands.add_parser("paste", help="save a table or a text you copied (cells copied out of Excel are tab-separated) as a file of REQ/")
    paste_parser.add_argument("--name", required=True, help="the name of the file, without its type")
    paste_parser.add_argument("--kind", default="csv", choices=intake.PASTE_KINDS, help="csv or md for a table, txt for a text")
    paste_parser.add_argument("--file", default="-", help="the file that holds the pasted text; - (the default) reads it from standard input")
    paste_parser.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    paste_parser.set_defaults(handler=lambda a: intake.paste(repo_root(), a.task, a.name, read_text_argument(a.file), a.kind))
    init_parser = intake_commands.add_parser("init", help="make REQ/INTAKE.md from the template: the goal, the scope, what not to do, how to know it is done, where to look")
    init_parser.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    init_parser.set_defaults(handler=lambda a: intake.init(repo_root(), a.task))
    setup_parser = intake_commands.add_parser("setup", help="which optional readers are installed, and the command to install the others (from the policy tools)")
    setup_parser.set_defaults(handler=lambda a: intake.setup(repo_root()))
    hand = commands.add_parser("handoff", help="the agent hands work to the person that only they can do outside the harness (tests in an environment); the board says it waits for it")
    hand_commands = hand.add_subparsers(dest="handoff_command", required=True)
    hand_tests = hand_commands.add_parser("tests", help="the person is to run the tests of TEST-GUIDE.md in an environment and bring the results back")
    hand_tests.add_argument("--env", required=True, help="the environment, for example DEV")
    hand_tests.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    hand_tests.set_defaults(handler=lambda a: tasklife.handoff(repo_root(), a.task, "tests", a.env))
    hand_run = hand_commands.add_parser("run", help="before the write-back, the person is to run something in an environment (a job, a query) and bring the output back; no check can start until then")
    hand_run.add_argument("--env", required=True, help="the environment, for example DEV")
    hand_run.add_argument("--what", required=True, help="one line: what the person is to run and send back")
    hand_run.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    hand_run.set_defaults(handler=lambda a: tasklife.handoff(repo_root(), a.task, "run", a.env, a.what))
    hand_clear = hand_commands.add_parser("clear", help="the results are back: take the mark away, then work on them")
    hand_clear.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
    hand_clear.set_defaults(handler=lambda a: tasklife.handoff_clear(repo_root(), a.task))
    auto = commands.add_parser("autorun", help="autorun (beta): the agent goes down TODO.md by itself and stops where a person is needed")
    auto_commands = auto.add_subparsers(dest="autorun_command", required=True)

    def add_auto(name: str, text: str, handler: Any) -> argparse.ArgumentParser:
        item = auto_commands.add_parser(name, help=text)
        item.add_argument("--task", default="", help="the task folder (or just its name); left out, the one open task")
        item.set_defaults(handler=handler)
        return item

    auto_on = add_auto("on", "the person turns autorun on for the task (terminal only, a typed code; refused while the agent is at work)", lambda a: autorun.turn_on(repo_root(), a.task, force=a.force))
    auto_on.set_defaults(person_only=True)
    auto_on.add_argument("--force", action="store_true", help="even while the agent is in the middle of a turn")
    off = add_auto("off", "turn autorun off: the person at a terminal, or the agent with --reason when it cannot go on", lambda a: autorun.turn_off(repo_root(), a.task, a.reason))
    off.add_argument("--reason", default="")
    add_auto("status", "on or off, the steps done, how often it was pushed on, why it stopped", lambda a: autorun.status(repo_root(), a.task))
    close = add("close", "the session lets go of the task and the report is written; the folder stays where it is (refused while steps of TODO.md are not ticked, unless --todo-open says why; a person at a terminal is refused while the agent is at work)", lambda a: close_task(a))
    close.add_argument("--reason", default="")
    close.add_argument("--todo-open", default="", help="why steps of TODO.md stay unticked (tick the ones that are done first)")
    close.add_argument("--force", action="store_true", help="even while the agent is in the middle of a turn (a person at a terminal)")
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
