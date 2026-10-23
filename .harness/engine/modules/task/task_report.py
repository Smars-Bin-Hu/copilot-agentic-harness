"""`task report`: one Markdown page about a task, from task.json, PLAN.md, DEV/ and the hook log of its session.

It lists facts and judges nothing. It is written to .workspace/reports/tasks/<name>/report.md when the
task is closed, and again whenever `task report` runs. Earlier rounds of the same task stay on the page.
Next to it goes report.html: where the task's time and usage went (taskinsight.py, taskhtml.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core import kbreads, messages, tasks
from core.paths import cli_command

from . import common, task as task_ops

PLAN_LINES = 120
KB_FILES_SHOWN = 30


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, command=cli_command(), **values)


def event_text(what: str) -> str:
    """The name of a task event in words. An event that has no text keeps its own name."""
    found = say(f"event.{what}")
    return what if found == f"event.{what}" else found


def promote_text(state: str) -> str:
    found = say(f"mdreport.promote.{state}")
    return state if found == f"mdreport.promote.{state}" else found


def report_path(root: Path, task: str) -> Path:
    return common.task_report_file(root, task_ops.name_of(task), common.REPORT_MD)


def render(root: Path, task: str, data: Dict[str, Any]) -> str:
    promote = data["promote"]
    plan = data.get("plan") or {}
    approved_now = tasks.plan_approved(root, task, data)
    lines = [
        say("mdreport.title", name=data["name"]),
        "",
        say("mdreport.folder", task=task),
        say("mdreport.status", status=data["status"], round=data["round"]),
        say("mdreport.created", at=data["created_at"]),
        say("mdreport.updated", at=data["updated_at"]),
        say("mdreport.session", session_id=data.get("session_id", ""), surface=data.get("surface", "")),
        say("mdreport.plan.approved" if approved_now else "mdreport.plan.changed", at=plan["approved_at"]) if plan.get("approved_at") else say("mdreport.plan.none"),
    ]
    review = data.get("review") or {}
    lines.append(say("mdreport.review.on", n=review["n"]) if review.get("n") else say("mdreport.review.off"))
    if data.get("branch"):
        lines.append(say("mdreport.branch", branch=data["branch"]))
    lines += [say("mdreport.target", name=name, base_ref=item["base_ref"], commit=item["base_commit"][:12]) for name, item in data.get("targets", {}).items()]
    lines += ["", say("mdreport.result.title"), "", say("mdreport.result.promote", text=promote_text(promote["state"]))]
    if promote.get("approved_at"):
        lines.append(say("mdreport.result.approved", at=promote["approved_at"]))
    for name, item in (promote.get("repos") or {}).items():
        if isinstance(item, dict) and item.get("commit"):
            lines.append(say("mdreport.result.kb", name=name, commit=item["commit"][:12]))
    for item in promote.get("files", []):
        lines.append(f"- {item['action']} {item['path']}")
    if promote.get("patch"):
        lines.append(say("mdreport.result.patch", patch=promote["patch"]))
    items, _text = task_ops.changes(root, task, data)
    changed = [item for item in items if item["action"] != "unchanged"]
    lines += ["", say("mdreport.changes.title"), ""]
    if changed:
        lines += [say("mdreport.changes.header"), "| --- | --- | --- | --- |"]
        lines += [f"| {item['path']} | {item['action']} | {item['added']} | {item['removed']} |" for item in changed]
    else:
        lines.append(say("mdreport.changes.none"))
    fetched = sorted(data.get("target_files", {}))
    if fetched:
        lines += ["", say("mdreport.fetched", count=len(fetched), files=messages.joined(fetched[:30]) + (say("mdreport.fetched.more") if len(fetched) > 30 else ""))]
    checks = [item for item in review.get("rounds") or [] if item.get("task_round") == data["round"]]
    lines += ["", say("mdreport.checks.title"), ""]
    if checks:
        no_verdict = say("mdreport.checks.no_verdict")
        lines += [say("mdreport.checks.header"), "| --- | --- | --- | --- | --- |"]
        refunded, dismissed = say("mdreport.checks.refunded"), say("mdreport.checks.dismissed")  # a check that does not count says so in its row
        lines += [
            f"| round-{item['number']:03d} | {str(item.get('started_at', ''))[:19]} | {item.get('verdict') or no_verdict}{refunded if item.get('refunded') else dismissed if item.get('dismissed') else ''} | {str(item.get('digest', ''))[:12]} | {task}/REVIEW/round-{item['number']:03d}/verdict.md |"
            for item in checks
        ]
        waived = review.get("waived") or {}
        if waived.get("task_round") == data["round"]:
            lines.append(say("mdreport.checks.waived", at=waived.get("at", ""), digest=str(waived.get("digest", ""))[:12]))
    else:
        lines.append(say("mdreport.checks.none"))
    try:
        read = kbreads.of_task(root, task)
    except Exception:  # noqa: BLE001 - a list in a report
        read = []
    if read:
        lines += ["", say("mdreport.kb.title"), "", say("mdreport.kb.header"), "| --- | --- |"]
        lines += [f"| {item['file']} | {item['reads']} |" for item in read[:KB_FILES_SHOWN]]
        if len(read) > KB_FILES_SHOWN:
            lines.append(say("mdreport.kb.more", count=len(read) - KB_FILES_SHOWN, name=data["name"]))
    lines += ["", say("mdreport.plan.title"), ""]
    try:
        plan_lines = tasks.plan_file(root, task).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        plan_lines = []
    if plan_lines:
        lines += ["> " + line for line in plan_lines[:PLAN_LINES]]
        if len(plan_lines) > PLAN_LINES:
            lines.append(say("mdreport.plan.more", count=len(plan_lines) - PLAN_LINES, plan=f"{task}/{tasks.PLAN_NAME}"))
    else:
        lines.append(say("mdreport.plan.no_file"))
    lines += ["", say("mdreport.events.title"), "", say("mdreport.events.header"), "| --- | --- | --- | --- |"]
    for event in data.get("events", []):
        lines.append(f"| {event['at'][:19]} | {event.get('round', '')} | {event_text(event['what'])} | {common.cell(event.get('detail', '')) or '-'} |")
    for old in data.get("rounds", []):
        lines += ["", say("mdreport.old.title", round=old["round"]), ""]
        lines.append(say("mdreport.old.plan", at=(old.get("plan") or {}).get("approved_at") or say("mdreport.old.plan.none")))
        lines.append(say("mdreport.old.promote", text=promote_text(old["promote"]["state"]), branch=old.get("branch", "")))
        lines += [f"- {item['action']} {item['path']}" for item in old["promote"].get("files", [])]
        lines.append(say("mdreport.old.dev", dev=old.get("dev", "")))
        if old.get("plan_file"):
            lines.append(say("mdreport.old.plan_file", plan=old["plan_file"]))
    lines += common.log_section(root, {"session_id": data.get("session_id", ""), "surface": data.get("surface", "vscode"), "created_at": data.get("round_started_at", data["created_at"])})
    return "\n".join(lines) + "\n"


def generate(root: Path, raw_task: str = "", detail: bool = False) -> Dict[str, Any]:
    if raw_task.strip():
        task = task_ops.resolve(root, raw_task)
    else:
        known = tasks.folders(root)
        started = [(tasks.read(root, name) or {}).get("updated_at", "") for name in known]
        ranked = sorted((stamp, name) for stamp, name in zip(started, known) if stamp)
        if not ranked:
            raise task_ops.CommandError(say("mdreport.no_task"))
        task = ranked[-1][1]
    data = task_ops.read(root, task)
    path = report_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(root, task, data)
    path.write_text(text, encoding="utf-8")
    result: Dict[str, Any] = {"task": task, "report": path.relative_to(root).as_posix(), "status": data["status"], "lines": text.count("\n")}
    try:  # where the time and usage went: a page for the person, the same numbers for the agent that explains them
        from . import taskboard, taskinsight

        info, now = taskboard.insight(root, task)
        result["analysis"] = taskboard.write_task_page(root, task, info, 0, now).relative_to(root).as_posix()
        result["insight"] = taskinsight.for_agent(info, detail)
        result["_compact"] = True  # an agent reads this: no indentation
    except Exception as error:  # noqa: BLE001 - the Markdown report is written; the page must not undo that
        result["analysis_error"] = f"{type(error).__name__}: {error}"
    return result
