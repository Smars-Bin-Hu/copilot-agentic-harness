"""Making a task from the board (1.6, B73): what the dialog sends is checked here, and the first message is made here. A page only shows the dialog.

The board makes a new chat in VS Code (`vslink`, `createSession`) and sends it one message. The chat opens the task itself, with the skill `harness-my-task` (a new task) or
`harness-task-fork` (a task forked from one that exists). The chat is made with `isolation: folder` (no worktree) and the mode `interactive`: neither can be chosen.
The words of the first message are English and fixed; the person's text goes in as it is, last. `[ZH]` is added only when the person chose Chinese.

Everything the page sends is checked again here: the name as `task new` takes it, the kind, the fork source (a task that exists), the text, the model (one the host lists now) and its
thinking level, the reply language, the tool permission. A value that is not allowed is refused with the reason; nothing is made.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core import ahp, messages, tasks
from core.paths import utc_now

from . import chatsend, task as task_ops, tasklife
from .common import CommandError

MAX_TEXT = 5000  # characters of what the person asks for
PERMISSIONS = {"allow-all": "autoApprove", "default": "default", "assisted": "assisted"}  # the page's word -> `config.autoApprove` of the host
DEFAULT_PERMISSION = "allow-all"
KEEP_PENDING = 3600.0  # seconds a made chat waits for its task to appear before the board lets go of it


def refusal(why: str, /, **values: Any) -> CommandError:
    return CommandError(messages.text("create.refused." + why, **values))


def text_field(data: Dict[str, Any], key: str) -> str:
    """A field of the request as text. A field that is not text (a list, a number, an object) is refused: the page never sends one."""
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise refusal("field", field=key)
    return value.strip()


def known_names(root: Any) -> List[str]:
    """The names of every task folder (open or closed), as they are on disk."""
    return [task_ops.name_of(item) for item in tasks.folders(root)]


def validate(root: Any, data: Dict[str, Any], models: List[Dict[str, Any]], waiting: Iterable[str] = ()) -> Dict[str, Any]:
    """The plan of a create from the request of the page, or a CommandError that says what is wrong. `models`: what the host lists now (`ahp.models_of`); `waiting`: the names of chats made
    by this board whose task does not exist yet. The mode, the isolation and the other settings of the chat are not read from the request."""
    name = tasklife.clean_name(text_field(data, "name"))  # the rules of `task new`, with its messages
    existing = {item.lower() for item in known_names(root)} | {item.lower() for item in waiting}
    if name.lower() in existing:
        raise refusal("exists", name=name)
    kind = text_field(data, "kind")
    if kind not in tasks.KINDS:
        raise refusal("kind", kinds=", ".join(tasks.KINDS))
    source = text_field(data, "source")
    if source and source not in known_names(root):
        raise refusal("source", source=source)
    text = text_field(data, "text")
    if not text:
        raise refusal("text.empty")
    if len(text) > MAX_TEXT:
        raise refusal("text.long", limit=MAX_TEXT)
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise refusal("text.bad")
    lang = text_field(data, "lang") or "en"
    if lang not in chatsend.LANGS:
        raise refusal("lang")
    permission = text_field(data, "permission") or DEFAULT_PERMISSION
    if permission not in PERMISSIONS:
        raise refusal("permission")
    model = model_of(data, models)
    return {"name": name, "kind": kind, "source": source, "text": text, "lang": lang, "permission": permission, "approve": PERMISSIONS[permission], "model": model}


def model_of(data: Dict[str, Any], models: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The model and thinking level in the shape of `message.model`, or None (the chat keeps VS Code's own choice). Only a model the host lists now, only a level it has."""
    wanted, level = text_field(data, "model"), text_field(data, "thinking")
    if not wanted:
        if level:
            raise refusal("thinking")
        return None
    listed = {item["id"]: item for item in models}
    if wanted not in listed:
        raise refusal("model")
    levels = (listed[wanted].get("thinking") or {}).get("levels") or []
    if level and level not in levels:
        raise refusal("thinking")
    return {"id": wanted, **({"config": {"thinkingLevel": level}} if level else {})}


def first_message(plan: Dict[str, Any]) -> str:
    """The first message to the new chat: a fixed English head (which skill, the name and the kind, the source of a fork), then what the person asked for, as typed."""
    if plan["source"]:
        head = ("This task is made from the board. Use the skill harness-task-fork to start it from the task below (harness task fork). "
                "The name, the kind and the source are given: do not ask for them.\n"
                f"- New task name: {plan['name']}\n- Kind: {plan['kind']}\n- Fork from: {plan['source']}")
    else:
        head = ("This task is made from the board. Use the skill harness-my-task to open it now (harness task new). "
                "The name and the kind are given: do not ask for them.\n"
                f"- Task name: {plan['name']}\n- Kind: {plan['kind']}")
    return chatsend.compose(head + "\n\nWhat to do:\n" + plan["text"], plan["lang"], [])


def pending(plan: Dict[str, Any], text: str, session: str, chat: str, title: str = "") -> Dict[str, Any]:
    """What the board remembers of a chat it made until the task exists: to bind them (`chatlink.adopt`) and to keep the model for the next messages."""
    return {"name": plan["name"], "kind": plan["kind"], "source": plan["source"], "lang": plan["lang"], "permission": plan["permission"], "model": plan["model"], "text": text,
            "session": session, "chat": chat, "title": title, "made_at": utc_now(), "clock": 0.0}
