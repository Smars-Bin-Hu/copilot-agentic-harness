"""A direct message from the super agent view to one task's chat (1.8.4, step 8): `POST /api/super/send`. It does not go through the super agent and spends none of its Credits.

  send   `send(board, data)`: `{task, text, model?, thinking?, context?, new_chat?, busy?, lang?, files?, checks?}` -> `{ok: true, how, task, chat, checks? | checks_pending?}` or `{ok: false, why}`.
         1.8.16: a CLOSED task is reopened: a new chat whose first message (`board.reopen.words`) has the agent open the task again, then the person's words; `how: "reopened"`. `checks` (0 up to `review.max_n`, else `why: "checks"`, key `send.refused.checks`) is set
         after the message went, through `taskreview.set_by_person` (the code of the board's `review set`); on a closed task it waits as `pending_checks` (`taskreview.set_pending`) until the board sees it open (`Board.apply_checks`): `checks_pending: n`, else `checks: n`.
         `how`: `sent` (idle chat), `queued` (busy chat, `busy` queue: the default), `steered` (busy chat, `busy` steer: into the running turn), `said` (the chat waits for the answer to its own
         question: the words skip it), `new-chat` (a new chat that goes on with the task). `why` is a key part of `send.refused.*` (`text.empty`, `text.long`, `not-idle`, `confirm-waits`, `off`,
         `not-ready`, `unsure`, `changed`, `timeout`, `model`, `thinking`, `context`, `file-bad`, `file-big`, `file-count`, `host` (+ `error`: the name of the error)), or `unknown`, `paused` (keys
         `super.route.why.*`), or `request` (key `serve.refused.request`).
  One decision, in this order, from the link's cache (the thread looks again before it acts): paused, refuse; a command confirmation waits, refuse; a new chat is wanted or the task has no chat,
  make one (refuse `not-idle` while the old chat works or waits); the chat waits on its own question, `say`; it works, `queue` or `steer`; it is idle, `send`.
  The model, thinking and context are the person's choice; left out (no `model` key), the model of the task. The person's words are kept whole (10000 characters) and recorded in `.task/sent.jsonl` with `by: "super"`.
"""

from __future__ import annotations

from typing import Any, Dict

from core import messages, tasks

from . import chatnew, chatsend, skillsend, task as task_ops, taskreview, tasklife, vslink
from .common import CommandError

MAX_TEXT = 10000  # characters of what the person types
SKILL = "harness-my-task"  # the skill "Go on in a new chat" starts
BUSY = ("queue", "steer")


def refusal(why: str, **more: Any) -> Dict[str, Any]:
    return {"ok": False, "why": why, **more}


def model_why(error: CommandError) -> str:
    """Which of `model`, `thinking`, `context` `chatnew.model_of` refused (it speaks in the words of `create.refused.*`)."""
    return next((why for why in ("thinking", "context", "model") if str(error) == messages.text(f"create.refused.{why}")), "model")


def first_message(root: Any, name: str, lang: str, text: str, reopen: bool = False) -> str:
    """The first message of a new chat: the skill, the fixed "go on with the task" words (in the language chosen; `[ZH]` after them so the slash stays first), then the person's text as typed.
    `reopen` (a closed task): the words tell the agent to open the task again first (`board.reopen.words`)."""
    key = "board.reopen.words" if reopen else "board.go.words"
    words = messages.table(lang).get(key) or messages.table("en")[key]
    head = f"/{SKILL} " + words.format(task=name) + (" " + chatsend.ZH_MARK if lang == "zh" else "")
    return head + "\n\n" + text


def confirm_waits(link: Any, task: str) -> bool:
    """From the cache: the oldest thing the chat waits for is a command to allow. What cannot be read counts as no: the thread looks again and refuses a `say` while any confirmation waits."""
    try:
        view = link.ask_of(task)
    except Exception:  # noqa: BLE001
        return False
    return bool(view) and view.get("kind") == "confirm"


def send(board: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    root, link = board.root, board.link
    try:
        task = task_ops.resolve(root, str(data.get("task", "")))  # a task that was archived away is no folder here: unknown
        found = tasks.read(root, task) or {}
    except (CommandError, ValueError, OSError):
        return refusal("unknown")
    reopen = found.get("status") == "closed"
    if found.get("status") not in ("open", "closed"):
        return refusal("unknown")
    if tasklife.paused_since(found):
        return refusal("paused")
    raw = data.get("text")
    typed = raw.strip() if isinstance(raw, str) else ""
    if not typed:
        return refusal("text.empty")
    if len(typed) > MAX_TEXT:
        return refusal("text.long")
    checks = data.get("checks")
    if checks is not None and not taskreview.checks_ok(root, checks):
        return refusal("checks")
    busy = str(data.get("busy") or "queue")
    lang = str(data.get("lang") or "")
    if busy not in BUSY or lang not in ("", *chatsend.LANGS):
        return refusal("request")
    try:
        files = chatsend.attachments(data.get("files", data.get("attachments")))
    except ValueError as error:
        return refusal(str(error))
    try:
        if "model" in data:
            model = chatnew.model_of(data, link.model_list())
        else:
            model = chatsend.model_of(found)
    except CommandError as error:
        return refusal(model_why(error))
    try:
        made = chatsend.prepare(root, task, "answer", "", lang, typed, "", with_drafts=False)  # `[ZH]` or `[EN]` as the reply panel does; no saved draft goes in
    except ValueError as error:
        return refusal("text." + str(error))
    text = made["text"]
    name = str(found.get("name") or task_ops.name_of(task))
    why = link.check(task, "send")
    if why in ("off", "not-ready", "unsure"):
        return refusal(why)
    bound = why != "unbound"
    if bound and confirm_waits(link, task):
        return refusal("confirm-waits")
    new = bool(data.get("new_chat")) or not bound or reopen  # a closed task has its old chat, if any, behind it: the reopen goes in a new chat
    if new:
        if bound and (link.check(task, "steer") == "" or link.check(task, "say") == ""):  # the old chat works, or waits for an answer
            return refusal("not-idle")
        job = "new-chat"
    elif link.check(task, "say") == "":
        job = "say"
    elif link.check(task, "steer") == "":
        job = "steer" if busy == "steer" else "queue"
    elif why == "":
        job = "send"
    else:
        return refusal(why)  # an error or an unknown state of the chat: it takes no message now
    try:
        if job == "new-chat":
            done = link.create(dict(skillsend.plan(lang or "en", name), model=model), first_message(root, name, lang or "en", text, reopen), files)
            skillsend.record(root, SKILL, "chat", done)
            # no `open_window()` (unlike "Go on in a new chat"): the person stays in the super view. `create` needs only the ready link, which means VS Code is up.
        else:
            done = link.dispatch(job, task, text, model, files)
    except vslink.Refused as error:
        return refusal(error.why)
    except Exception as error:  # noqa: BLE001 - the host said no: the name of the error only, never its text
        try:
            link.host_said(error)
        except Exception:  # noqa: BLE001
            pass
        return refusal("host", error=type(error).__name__)
    extra: Dict[str, Any] = {"by": "super", "lang": made["lang"], "model": model or {}, "files": chatsend.listed(files)}
    if reopen:
        extra["reopen"] = True
    if job == "say":
        extra["skipped"] = done.get("skipped") or []
        try:
            tasklife.set_waiting(root, task, None)  # the person answered the question
        except Exception:  # noqa: BLE001
            pass
    kept = board.sent(task, found, job, first_message(root, name, lang or "en", text, reopen) if job == "new-chat" else text, done, extra)
    answer: Dict[str, Any] = {"ok": True, "how": "reopened" if reopen else {"send": "sent", "queue": "queued", "steer": "steered", "say": "said", "new-chat": "new-chat"}[job], "task": name, "chat": kept["chat"], "recorded": kept["recorded"]}
    if checks is not None:
        answer.update(set_checks(root, task, checks, reopen))
    return answer


def set_checks(root: Any, task: str, number: int, reopen: bool) -> Dict[str, Any]:
    """After the message went: the person's independent checks, through the code of the board's `review set` (`taskreview.set_by_person`). The click of the paired browser is the person's word; the super agent can only propose.
    A closed task cannot take it (`review set` needs an open task): the number is kept (`pending_checks`) and the board sets it when it first sees the task open. `{checks: n}`, `{checks_pending: n}`, or `{}` when it could not be kept."""
    try:
        if reopen and not taskreview.set_pending(root, task, number):
            return {"checks_pending": number}
        if reopen:
            return {"checks": number} if taskreview.apply_pending(root, task) else {"checks_pending": number}  # the agent opened the task already
        taskreview.set_by_person(root, task, number, interactive=True)
        return {"checks": number}
    except Exception:  # noqa: BLE001 - the message went: a number that cannot be kept is no refusal of it
        return {}
