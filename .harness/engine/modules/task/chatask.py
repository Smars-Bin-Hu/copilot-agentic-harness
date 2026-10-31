"""What waits for a person in a chat of VS Code, and how the board answers it (1.6, B75). Two kinds only; any other `inputNeeded` is not shown and gets no button.

  toolConfirmation   Copilot asks whether a tool may run (a terminal command). Answer: `chat/toolCallConfirmed` for that `toolCallId`.
  chatInput          the agent asked a question (the ask tool). Answer: `chat/inputAnswerChanged` for each question, then `chat/inputCompleted`.

The item comes from the session state of the host (`inputNeeded[]`, kept by `vslink`). A page only shows it and says which item the person answered (`id`, the call or request id, and the
`digest` of what was shown): the thread reads the item again before it acts, and refuses when the item is gone or is not what the page showed. Python makes every action; a page never does.
What is shown of a command is redacted (`core/redact.py`) and cut. A question kind the board cannot answer from a form makes the whole question "answer it in VS Code": no button.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from core import redact

CONFIRM, CHAT_INPUT = "toolConfirmation", "chatInput"
PENDING = "pending-confirmation"
KINDS = ("single-select", "multi-select", "text", "boolean", "number", "integer")
MAX_COMMAND = 400  # characters of a command shown on the page and kept in the history
MAX_LINE = 200  # a question, an option, a line of history
MAX_ANSWER = 2000  # characters of a typed answer
MAX_SOURCE = 20000  # how much of a tool input is read before it is redacted
MAX_QUESTIONS = 20
MAX_OPTIONS = 50
DENY_TEXT = "Denied by the person on the board."


class AnswerError(ValueError):
    """An answer that cannot be sent: `code` is a key of `ask.refused.answer.*`, `title` the question it is about."""

    def __init__(self, code: str, title: str = "") -> None:
        super().__init__(code)
        self.code, self.title = code, title


def clip(text: Any, limit: int) -> str:
    """Redacted and cut: the only way a command or an answer reaches a page or the history."""
    flat = redact.text(str(text or "")[:MAX_SOURCE]).strip()
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def one_line(text: Any, limit: int) -> str:
    return clip(" ".join(str(text or "").split()), limit)


def command_of(call: Dict[str, Any]) -> str:
    """The command a tool wants to run (`toolInput` is a JSON string; a terminal tool has `command`). Whole, not yet redacted or cut."""
    raw = call.get("toolInput")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return raw
    if isinstance(raw, dict):
        for key in ("command", "cmd", "script"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                return raw[key]
        return json.dumps(raw, ensure_ascii=False)
    return str(raw or call.get("intention") or "")


def digest_of(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def options_of(question: Dict[str, Any]) -> List[Dict[str, str]]:
    return [{"id": str(item["id"]), "label": one_line(item.get("label") or item["id"], MAX_LINE)} for item in (question.get("options") or [])[:MAX_OPTIONS] if isinstance(item, dict) and item.get("id") not in (None, "")]


def question_view(question: Any) -> Optional[Dict[str, Any]]:
    """One question as the page draws it, or None when the board cannot take an answer to it from a form."""
    if not isinstance(question, dict) or not question.get("id") or question.get("kind") not in KINDS:
        return None
    options = options_of(question)
    if question["kind"] in ("single-select", "multi-select") and not options:
        return None
    return {"id": str(question["id"]), "title": one_line(question.get("title") or question.get("message") or question["id"], MAX_LINE), "message": one_line(question.get("message") or "", MAX_LINE),
            "kind": question["kind"], "required": bool(question.get("required")), "options": options}


def shown(item: Any) -> Optional[Dict[str, Any]]:
    """An `inputNeeded` item as the page shows it, or None when it is not one of the two kinds (or is not whole). `digest` names what was shown: a changed item has another."""
    if not isinstance(item, dict) or not item.get("id") or not item.get("chat"):
        return None
    if item.get("kind") == CONFIRM:
        call = item.get("toolCall")
        if not isinstance(call, dict) or call.get("status") != PENDING or not call.get("toolCallId") or not item.get("turnId"):
            return None
        whole = command_of(call)
        return {"kind": "confirm", "id": str(item["id"]), "tool_call_id": str(call["toolCallId"]), "tool": one_line(call.get("toolName") or "", 60), "title": one_line(call.get("confirmationTitle") or "", MAX_LINE),
                "intention": one_line(call.get("intention") or "", MAX_LINE), "command": clip(whole, MAX_COMMAND), "digest": digest_of(item["id"], item["turnId"], call["toolCallId"], call.get("toolName"), whole)}
    if item.get("kind") == CHAT_INPUT:
        request = item.get("request")
        if not isinstance(request, dict) or not request.get("id"):
            return None
        raw = request.get("questions")
        raw = raw if isinstance(raw, list) else []
        views = [question_view(question) for question in raw[:MAX_QUESTIONS]]
        supported = bool(raw) and len(raw) <= MAX_QUESTIONS and all(views)
        message = one_line(request.get("message") or "", MAX_LINE)
        first = next((view for view in views if view), None)
        return {"kind": "question", "id": str(item["id"]), "request_id": str(request["id"]), "message": message or (first["title"] if first else ""), "supported": supported,
                "questions": [view for view in views if view] if supported else [], "digest": digest_of(item["id"], request["id"], raw)}
    return None


def confirm_action(item: Dict[str, Any], approved: bool) -> Dict[str, Any]:
    """The action for a decision on a tool call. Allow is a plain yes (never `allow-session`: it would change the permissions of the session). Deny carries the reason and the host's own deny option."""
    call = item["toolCall"]
    action: Dict[str, Any] = {"type": "chat/toolCallConfirmed", "turnId": item["turnId"], "toolCallId": call["toolCallId"], "approved": bool(approved)}
    if not approved:
        deny = next((str(option["id"]) for option in call.get("options") or [] if isinstance(option, dict) and option.get("kind") == "deny" and option.get("id")), "skip")
        action.update({"reason": "denied", "reasonMessage": DENY_TEXT, "selectedOptionId": deny})
    return action


def one_answer(view: Dict[str, Any], value: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the value in the shape of the host, a line for the history) for one question, or (None, "") when it is left empty. Raises AnswerError."""
    kind, title = view["kind"], view["title"]
    ids = [option["id"] for option in view["options"]]
    if value is None or value == "" or value == []:
        return None, ""
    if kind == "single-select":
        if not isinstance(value, str) or value not in ids:
            raise AnswerError("bad", title)
        return {"kind": "selected", "value": value}, next(option["label"] for option in view["options"] if option["id"] == value)
    if kind == "multi-select":
        if not isinstance(value, list) or not all(isinstance(one, str) and one in ids for one in value):
            raise AnswerError("bad", title)
        chosen = [one for one in ids if one in value]
        return {"kind": "selected-many", "value": chosen}, ", ".join(option["label"] for option in view["options"] if option["id"] in chosen)
    if kind == "text":
        if not isinstance(value, str):
            raise AnswerError("bad", title)
        if len(value) > MAX_ANSWER:
            raise AnswerError("long", title)
        return ({"kind": "text", "value": value.strip()}, value.strip()) if value.strip() else (None, "")
    if kind == "boolean":
        if not isinstance(value, bool):
            raise AnswerError("bad", title)
        return {"kind": "boolean", "value": value}, "yes" if value else "no"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == "integer" and int(value) != value):
        raise AnswerError("bad", title)
    number = int(value) if kind == "integer" or int(value) == value else value
    return {"kind": "number", "value": number}, str(number)


def answer_actions(item: Dict[str, Any], given: Any) -> Tuple[List[Dict[str, Any]], str]:
    """The actions that answer a question item, in the order the host wants (`inputAnswerChanged` for each question, then `inputCompleted`), and one line for the history.
    `given`: {question id: value}. A required question left empty, a value that is not an option, an unknown question: AnswerError. The item must be one `shown` can answer."""
    view = shown(item)
    if view is None or view["kind"] != "question" or not view["supported"]:
        raise AnswerError("unsupported")
    if not isinstance(given, dict) or not set(map(str, given)) <= {question["id"] for question in view["questions"]}:
        raise AnswerError("unknown")
    request = str(item["request"]["id"])
    answers: Dict[str, Any] = {}
    lines: List[str] = []
    for question in view["questions"]:
        found, text = one_answer(question, given.get(question["id"]))
        if found is None:
            if question["required"]:
                raise AnswerError("required", question["title"])
            answers[question["id"]] = {"state": "skipped"}
            continue
        answers[question["id"]] = {"state": "submitted", "value": found}
        lines.append(question["title"] + ": " + one_line(text, MAX_LINE))
    actions: List[Dict[str, Any]] = [{"type": "chat/inputAnswerChanged", "requestId": request, "questionId": key, "answer": answer} for key, answer in answers.items()]
    actions.append({"type": "chat/inputCompleted", "requestId": request, "response": "accept", "answers": answers})
    return actions, clip("; ".join(lines), MAX_LINE)


def find(items: Any, ident: str) -> Optional[Dict[str, Any]]:
    return next((item for item in items or [] if isinstance(item, dict) and item.get("id") == ident), None)


def first_for(items: Any, chat: str) -> Tuple[Optional[Dict[str, Any]], int]:
    """The oldest item of this chat that is one of the two kinds, and how many there are. The page shows one at a time: the one answered first."""
    mine = [view for view in (shown(item) for item in items or [] if isinstance(item, dict) and item.get("chat") == chat) if view]
    return (mine[0] if mine else None), len(mine)
