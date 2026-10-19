"""CLI commands of the observe module.

  stats                numbers from the session logs: prompts, refusals, review verdicts, hook time
  kb reads             which knowledge base files the tasks read, and which nobody read
  kb check [--domain]  is each domain in the standard form (core/kbstd.py)
  kb stale --domain D  which objects were learned from source files that changed since (--diff: what changed)
  kb stamp --path P    after a refresh: the sources count from the base branch now (only in a task's DEV/)
  kb survey / map      build the repository map (core/kbmap.py)
  kb near / split / gaps  questions on the map (core/kbgraph.py): every object and use, by script (core/kbmap.py)
  logs prune           delete session logs not written to for N days (a person decides; no hook deletes anything)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from core.paths import repo_root

from core import kbaudit, kbgraph, kblearn, kbmap, kbmigrate, kbstd

from . import kbstats, prune, stats


def cmd_stats(args: argparse.Namespace) -> Dict[str, Any]:
    return stats.collect(repo_root(), args.session_id, args.surface, args.days)


def cmd_prune(args: argparse.Namespace) -> Dict[str, Any]:
    return prune.prune(repo_root(), args.days, args.dry_run)


def cmd_migrate(args: Any) -> Dict[str, Any]:
    try:
        return kbmigrate.migrate(repo_root(), Path(args.source), Path(args.target))
    except kbmigrate.MigrateError as error:
        raise RuntimeError(str(error)) from None


def cmd_stamp(args: Any) -> Dict[str, Any]:
    try:
        return kbstd.stamp(repo_root(), Path(args.path), args.id)
    except kbstd.KbError as error:
        raise RuntimeError(str(error)) from None


def cmd_stale(args: Any) -> Dict[str, Any]:
    try:
        return kbstd.stale(repo_root(), args.domain, args.diff)
    except ValueError as error:
        raise RuntimeError(str(error)) from None


def mapped(work: Any) -> Any:
    def run(args: Any) -> Dict[str, Any]:
        try:
            return work(args)
        except kbmap.MapError as error:
            raise RuntimeError(str(error)) from None
    return run


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
    # The form of the knowledge base (standard v1). Kept here because `kb` is here; the code is core/kbstd.py.
    form = kb_commands.add_parser("check", help="is each domain in the standard form? domain.yaml, objects/index.jsonl, cards and anchors, no local paths. Exit code 1 on an error")
    form.add_argument("--domain", action="append", default=None, help="only this domain (may be given more than once)")
    form.add_argument("--path", default="", help="check this one domain folder instead (a migration in a task's DEV/)")
    form.set_defaults(handler=lambda a: kbstd.check_path(repo_root(), Path(a.path)) if a.path else kbstd.check(repo_root(), a.domain))
    move = kb_commands.add_parser("migrate", help="a domain of before the standard (domain.yaml with object lists + objects/indexes.json) into the standard form, into a task's DEV/; prints what it could not map")
    move.add_argument("--from", dest="source", required=True, help="the domain folder in the old form")
    move.add_argument("--to", dest="target", required=True, help="where the new form goes: inside .workspace/sandbox/tasks/<task>/DEV/; may be the same folder as --from")
    move.set_defaults(handler=cmd_migrate)
    old = kb_commands.add_parser("stale", help="which objects of a domain were learned from source files that changed since (git, on the base branch)")
    old.add_argument("--domain", required=True)
    old.add_argument("--diff", action="store_true", help="with what changed in each source since its card was written (cut after 120 lines)")
    old.set_defaults(handler=cmd_stale)
    mark = kb_commands.add_parser("stamp", help="after checking cards against the code: set the sha of their sources to the base branch now. Only in a task's DEV/")
    mark.add_argument("--path", required=True, help="the domain folder inside .workspace/sandbox/tasks/<task>/DEV/")
    mark.add_argument("--id", action="append", default=None, help="only this object (may be given more than once); default: all")
    mark.set_defaults(handler=cmd_stamp)
    # The repository map (layer one of learning a code base): core/kbmap.py, extractors in core/kbextract.py.
    build = kb_commands.add_parser("map", help="map the target repositories with the toolkit of the knowledge base (<knowledge base>/toolkit/): every object and every use. Only changed files are read again; the known facts of the toolkit are checked")
    build.add_argument("--repo", action="append", default=None, help="only this repository (may be given more than once); default: all but the knowledge base")
    build.add_argument("--fresh", action="store_true", help="read every file again")
    build.add_argument("--toolkit", default="", help="try a toolkit being built in a task (a folder inside .workspace/sandbox/tasks/) instead of the knowledge base's")
    build.set_defaults(handler=mapped(lambda a: kbmap.build(repo_root(), a.repo, a.fresh, Path(a.toolkit) if a.toolkit else None)))
    look = kb_commands.add_parser("survey", help="what each target repository holds, before there is a toolkit: kinds of files, folders, a few sample files of each kind")
    look.add_argument("--repo", action="append", default=None, help="only this repository (may be given more than once)")
    look.add_argument("--samples", type=int, default=3, help="sample files per kind (1 to 10)")
    look.set_defaults(handler=mapped(lambda a: kbmap.survey(repo_root(), a.repo, a.samples)))
    close = kb_commands.add_parser("near", help="what one object uses and what uses it, from the map")
    close.add_argument("object", help="an id (sp:Db.dbo.usp_x) or a name (usp_x)")
    close.add_argument("--depth", type=int, default=1, choices=range(1, 6), help="how many steps out (1 to 5)")
    side = close.add_mutually_exclusive_group()
    side.add_argument("--up", dest="direction", action="store_const", const="up", help="only what uses it")
    side.add_argument("--down", dest="direction", action="store_const", const="down", help="only what it uses")
    close.set_defaults(handler=mapped(lambda a: kbgraph.near(repo_root(), a.object, a.depth, a.direction or "both")), direction=None)
    cut = kb_commands.add_parser("split", help="a first cut of the domains from the map: entry points and what they reach; objects reached from many entry points are shared")
    cut.add_argument("--shared-min", type=int, default=None, help="reached from this many entry points makes an object shared (default: from the profile, 3)")
    cut.set_defaults(handler=mapped(lambda a: kbgraph.split(repo_root(), a.shared_min)))
    hole = kb_commands.add_parser("gaps", help="what runs or is used but has no code in the repositories: missing names, retired code in use, files deleted in git; with --inventory, also what production runs that no repository holds")
    hole.add_argument("--inventory", default="", help="a list of production objects a person exported (ids, one per line, or CSV with an id column)")
    hole.set_defaults(handler=mapped(lambda a: kbgraph.gaps(repo_root(), Path(a.inventory) if a.inventory else None)))
    check = kb_commands.add_parser("audit", help="how right the map is: a sample of objects of each type to read blind; with --answers, the readings against the map per type (recall, precision, every difference). Exit code 1 below the bar")
    check.add_argument("--per-type", type=int, default=kbaudit.PER_TYPE, help=f"objects per type in the sample (default {kbaudit.PER_TYPE})")
    check.add_argument("--type", action="append", default=None, help="only this type (may be given more than once); default: the types that use something")
    check.add_argument("--seed", type=int, default=1, help="another seed gives another sample")
    check.add_argument("--answers", default="", help="the readings: JSON lines {from, to, kind, line}; {from, none: true} for an object that uses nothing")
    check.add_argument("--min", type=float, default=kbaudit.MIN_SCORE, help=f"the bar for recall and precision of each type (default {kbaudit.MIN_SCORE})")
    check.set_defaults(handler=mapped(lambda a: kbaudit.score(repo_root(), Path(a.answers), a.min) if a.answers else kbaudit.sample(repo_root(), a.per_type, a.type, a.seed)))
    # Learning a domain from the map (M27): core/kblearn.py.
    plan = kb_commands.add_parser("order", help="what the entry points reach and the order to learn it in: bottom up, in batches of one type; what is shared, stopped at, missing or known only at run time")
    plan.add_argument("--entry", action="append", required=True, help="an entry point, id or name (may be given more than once)")
    plan.add_argument("--stop", action="append", default=None, help="do not learn this object or what is past it: a boundary (may be given more than once)")
    plan.add_argument("--batch", type=int, default=kblearn.BATCH, help=f"objects per batch (default {kblearn.BATCH})")
    plan.add_argument("--lines", type=int, default=kblearn.BUDGET, help=f"lines of code per batch at most (default {kblearn.BUDGET}); a longer object is a batch of its own")
    plan.add_argument("--shared-min", type=int, default=None, help="reached from this many entry points, one of them not given, makes an object shared (default: from the profile, 3)")
    plan.add_argument("--path", default="", help="a domain folder: objects already in its index are learned and left out")
    plan.set_defaults(handler=mapped(lambda a: kblearn.order(repo_root(), a.entry, a.stop, a.batch, a.shared_min, Path(a.path) if a.path else None, a.lines)))
    ways = kb_commands.add_parser("flows", help="the paths from each entry point through the map, for the Flows of architecture.md")
    ways.add_argument("--entry", action="append", required=True, help="an entry point, id or name (may be given more than once)")
    ways.add_argument("--depth", type=int, default=kblearn.FLOW_DEPTH, choices=range(1, 13), help=f"steps at most (default {kblearn.FLOW_DEPTH})")
    ways.add_argument("--stop", action="append", default=None, help="end paths at this object (may be given more than once)")
    ways.add_argument("--shared-min", type=int, default=None, help="as for kb order")
    ways.set_defaults(handler=mapped(lambda a: kblearn.flows(repo_root(), a.entry, a.depth, kblearn.FLOW_PATHS, a.stop, a.shared_min)))
    enrol = kb_commands.add_parser("index", help="after the cards of a batch are written: their lines in objects/index.jsonl, from the map, stamped with the base branch now. Only in a task's DEV/")
    enrol.add_argument("--path", required=True, help="the domain folder inside .workspace/sandbox/tasks/<task>/DEV/")
    enrol.add_argument("--id", action="append", required=True, help="an object whose card was written (may be given more than once)")
    enrol.add_argument("--level", default="verified", choices=["verified", "supported", "inferred", "unknown", "conflict"], help="the level of the new lines (default verified)")
    enrol.set_defaults(handler=mapped(lambda a: kblearn.index(repo_root(), Path(a.path), a.id, a.level)))
    tally = kb_commands.add_parser("cardcheck", help="the Reads / Writes / Calls / Called by of the cards and the Flows of architecture.md, against the map. Exit code 1 on an error")
    tally.add_argument("--path", required=True, help="the domain folder (in the knowledge base, or in a task's DEV/)")
    tally.set_defaults(handler=mapped(lambda a: kblearn.cardcheck(repo_root(), Path(a.path))))

    logs = subparsers.add_parser("logs", help="the session logs")
    commands = logs.add_subparsers(dest="logs_command", required=True)
    prune_parser = commands.add_parser("prune", help="delete session logs not written to for N days")
    prune_parser.add_argument("--days", type=int, required=True)
    prune_parser.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    prune_parser.set_defaults(handler=cmd_prune)
