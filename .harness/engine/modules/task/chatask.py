"""What waits for a person in a chat of VS Code, and how the board answers it (1.6, B75; result and sign-in in 1.8.x B5). Any other `inputNeeded` is not shown and gets no button.

  toolConfirmation    Copilot asks whether a tool may run (a terminal command): status `pending-confirmation`. Answer: `chat/toolCallConfirmed` for that `toolCallId`.
                      Or whether the result of a tool that ran may go to the model: status `pending-result-confirmation`, view `stage: result`. Answer: `chat/toolCallResultConfirmed`.
  toolAuthentication  a tool of an MCP server waits for the person to sign in to that server (status `auth-required`). Shown only: the board does not sign in for the person (an OAuth
                      flow of its own would hold a token of a server it does not own); the person can stop the turn.
  chatInput           the agent asked a question (the ask tool). Answer: `chat/inputAnswerChanged` for each question, then `chat/inputCompleted`.

The item comes from the session state of the host (`inputNeeded[]`, kept by `vslink`). A page only shows it and says which item the person answered (`id`, the call or request id, and the
`digest` of what was shown): the thread reads the item again before it acts, and refuses when the item is gone or is not what the page showed. Python makes every action; a page never does.
What is shown of a command is redacted (`core/redact.py`) and cut. A question of a kind the board does not know gets a text box (`kind: other`): the words go as a text answer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from core import redact

CONFIRM, CHAT_INPUT, AUTH = "toolConfirmation", "chatInput", "toolAuthentication"
SUB = "sub|"  # the start of the id of an item that waits in a subagent's chat
PENDING = "pending-confirmation"
RESULT = "pending-result-confirmation"  # the tool ran; its result waits for the person before the model reads it
SIGN_IN = "auth-required"
KINDS = ("single-select", "multi-select", "text", "boolean", "number", "integer")
MAX_COMMAND = 400  # characters of a command shown on the page and kept in the history
MAX_LINE = 200  # a question, an option, a line of history
MAX_TEXT = 8000  # characters of what the agent says with its questions, whole on the page with its line breaks (1.6.102: it was cut to one line of 200)
MAX_ANSWER = 2000  # characters of a typed answer
MAX_SOURCE = 20000  # how much of a tool input is read before it is redacted
MAX_RESULT = 4000  # characters of a result shown for the person to check: the end of it, as a command's output is read
MAX_RESULT_LINES = 40
MAX_RAW = 2000  # characters of a question of a kind the board does not know, as JSON, for the Details of its card
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
    """One question as the page draws it, or None when it has no id (no answer can name it). A kind the board does not know, or a list with no option, is `other`: a text box, and the question as
    it came (`raw`, redacted and cut) for the Details of the card."""
    if not isinstance(question, dict) or question.get("id") in (None, ""):
        return None
    options = options_of(question)
    kind = question.get("kind")
    if kind not in KINDS or (kind in ("single-select", "multi-select") and not options):
        try:
            raw = json.dumps(question, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            raw = ""
        return {"id": str(question["id"]), "title": one_line(question.get("title") or question.get("message") or question.get("question") or question["id"], MAX_LINE),
                "message": clip(question.get("message") or "", MAX_TEXT), "kind": "other", "was": one_line(kind if isinstance(kind, str) else "", 60), "required": bool(question.get("required")), "options": [], "free": False, "raw": clip(raw, MAX_RAW)}
    return {"id": str(question["id"]), "title": one_line(question.get("title") or question.get("message") or question["id"], MAX_LINE), "message": clip(question.get("message") or "", MAX_TEXT),
            "kind": kind, "required": bool(question.get("required")), "options": options,
            "free": question["kind"] in ("single-select", "multi-select") and question.get("allowFreeformInput") is not False}  # VS Code's own rule: a list takes typed words unless it says it does not


RUNNING = ("running", "streaming", "pending-confirmation", RESULT, SIGN_IN)  # the states of a tool call that has not ended


def sub_calls(state: Any) -> List[Dict[str, str]]:
    """The subagent calls that run now in a chat state (1.8): a `task` tool call whose `_meta` names the chat of its subagent (`subagentChatUri`). `{chat, agent, call}`, oldest first."""
    active = state.get("activeTurn") if isinstance(state, dict) else None
    found = []
    for part in (active.get("responseParts") if isinstance(active, dict) else None) or []:
        call = part.get("toolCall") if isinstance(part, dict) else None
        meta = (call.get("_meta") if isinstance(call, dict) else None) or (part.get("_meta") if isinstance(part, dict) else None)
        if isinstance(call, dict) and isinstance(meta, dict) and meta.get("subagentChatUri") and call.get("status") in RUNNING:
            found.append({"chat": str(meta["subagentChatUri"]), "agent": one_line(meta.get("subagentAgentName") or "", 60), "call": str(call.get("toolCallId") or "")})
    return found


def sub_item(chat: str, agent: str, state: Any) -> Optional[Dict[str, Any]]:
    """The oldest tool call of a subagent's chat that waits for a person (to run, to send its result, or a sign-in), as an `inputNeeded` item that `shown` and `confirm_action` take (1.8). The id starts
    with `sub|`: it names the chat, so the thread knows to read that chat again and to send the answer to it. None: nothing waits there."""
    active = state.get("activeTurn") if isinstance(state, dict) else None
    if not isinstance(active, dict) or not active.get("id"):
        return None
    for part in active.get("responseParts") or []:
        call = part.get("toolCall") if isinstance(part, dict) else None
        if isinstance(call, dict) and call.get("status") in (PENDING, RESULT, SIGN_IN) and call.get("toolCallId"):
            return {"id": f"{SUB}{chat}|{call['toolCallId']}", "chat": chat, "kind": AUTH if call["status"] == SIGN_IN else CONFIRM, "turnId": active["id"], "toolCall": call, "agent": agent}
    return None


def result_of(call: Dict[str, Any]) -> Tuple[str, bool]:
    """What a tool call gave, for the person to check before the model reads it: the output of a command or the texts of the result, else the error; the last `MAX_RESULT_LINES` lines and
    `MAX_RESULT` characters, redacted. `(text, cut)`."""
    texts: List[str] = []
    for item in call.get("content") or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if item.get("type") == "terminal" and isinstance(result.get("preview"), str):
            texts.append(result["preview"])
        elif item.get("type") == "text" and isinstance(item.get("text"), str):
            texts.append(item["text"])
    if not texts and isinstance(call.get("error"), dict):
        texts.append(str(call["error"].get("message") or ""))
    whole = redact.text("\n".join(texts)[-MAX_SOURCE:]).rstrip()
    lines = whole.split("\n")
    text = "\n".join(lines[-MAX_RESULT_LINES:])
    cut = len(lines) > MAX_RESULT_LINES or len(text) > MAX_RESULT
    return (text[-MAX_RESULT:] if len(text) > MAX_RESULT else text), cut


def auth_view(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A tool call that waits for a sign-in, as the page shows it: the tool, the server (its name or its address), why (`required`, `expired`, `insufficientScope`), the scopes and what the server
    says. Never the OAuth client (`ahp.auth_kept` does not keep it)."""
    call = item.get("toolCall")
    if not isinstance(call, dict) or call.get("status") != SIGN_IN or not call.get("toolCallId") or not item.get("turnId"):
        return None
    auth = call.get("auth") if isinstance(call.get("auth"), dict) else {}
    resource = auth.get("resource") if isinstance(auth.get("resource"), dict) else {}
    contributor = call.get("contributor") if isinstance(call.get("contributor"), dict) else {}
    server = resource.get("resource_name") or contributor.get("name") or contributor.get("customizationId") or resource.get("resource") or ""
    scopes = [one_line(scope, 80) for scope in (auth.get("requiredScopes") or [])[:20] if isinstance(scope, str)]
    return {"kind": "auth", **({"agent": one_line(item["agent"], 60)} if item.get("agent") else {}), "id": str(item["id"]), "tool_call_id": str(call["toolCallId"]),
            "tool": one_line(call.get("displayName") or call.get("toolName") or "", 60), "server": one_line(server, 120), "url": one_line(resource.get("resource") or "", 300),
            "reason": str(auth.get("reason") or "required") if auth.get("reason") in ("required", "expired", "insufficientScope") else "required", "scopes": scopes,
            "about": clip(auth.get("description") or "", MAX_LINE * 2), "cut": bool(auth.get("cut")), "digest": digest_of(item["id"], item["turnId"], call["toolCallId"], SIGN_IN)}


def shown(item: Any) -> Optional[Dict[str, Any]]:
    """An `inputNeeded` item as the page shows it, or None when it is not one of the two kinds (or is not whole). `digest` names what was shown: a changed item has another."""
    if not isinstance(item, dict) or not item.get("id") or not item.get("chat"):
        return None
    if item.get("kind") == AUTH:
        return auth_view(item)
    if item.get("kind") == CONFIRM:
        call = item.get("toolCall")
        if not isinstance(call, dict) or call.get("status") not in (PENDING, RESULT) or not call.get("toolCallId") or not item.get("turnId"):
            return None
        whole = command_of(call)
        view = {"kind": "confirm", **({"agent": one_line(item["agent"], 60)} if item.get("agent") else {}), "id": str(item["id"]), "tool_call_id": str(call["toolCallId"]), "tool": one_line(call.get("toolName") or "", 60), "title": one_line(call.get("confirmationTitle") or "", MAX_LINE),
                "intention": one_line(call.get("intention") or "", MAX_LINE), "command": clip(whole, MAX_COMMAND), "digest": digest_of(item["id"], item["turnId"], call["toolCallId"], call.get("toolName"), whole, call["status"])}
        if call["status"] == RESULT:
            text, cut = result_of(call)
            view.update({"stage": "result", "result": text, "result_cut": cut, "failed": call.get("success") is False})
        return view
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
        # `message`: one line for a card or a row; `text`: all of it, with its line breaks, for the dialog where the person answers
        return {"kind": "question", "id": str(item["id"]), "request_id": str(request["id"]), "message": message or (first["title"] if first else ""), "text": clip(request.get("message") or "", MAX_TEXT), "supported": supported,
                "questions": [view for view in views if view] if supported else [], "digest": digest_of(item["id"], request["id"], raw)}
    return None


def confirm_action(item: Dict[str, Any], approved: bool) -> Dict[str, Any]:
    """The action for a decision on a tool call. Allow is a plain yes (never `allow-session`: it would change the permissions of the session). Deny carries the reason and the host's own deny option.
    A call whose result waits (`pending-result-confirmation`): yes sends the result to the model, no keeps it from it (`chat/toolCallResultConfirmed`)."""
    call = item["toolCall"]
    if call.get("status") == RESULT:
        return {"type": "chat/toolCallResultConfirmed", "turnId": item["turnId"], "toolCallId": call["toolCallId"], "approved": bool(approved)}
    action: Dict[str, Any] = {"type": "chat/toolCallConfirmed", "turnId": item["turnId"], "toolCallId": call["toolCallId"], "approved": bool(approved)}
    if not approved:
        deny = next((str(option["id"]) for option in call.get("options") or [] if isinstance(option, dict) and option.get("kind") == "deny" and option.get("id")), "skip")
        action.update({"reason": "denied", "reasonMessage": DENY_TEXT, "selectedOptionId": deny})
    return action


def one_answer(view: Dict[str, Any], value: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the value in the shape of the host, a line for the history) for one question, or (None, "") when it is left empty. Raises AnswerError."""
    kind, title = view["kind"], view["title"]
    ids = [option["id"] for option in view["options"]]
    typed = ""
    if isinstance(value, dict) and view.get("free"):  # {value: what was picked, free: what was typed}
        typed, value = str(value.get("free") or "").strip(), value.get("value")
        if len(typed) > MAX_ANSWER:
            raise AnswerError("long", title)
    if typed and kind == "single-select":
        return {"kind": "text", "value": typed}, typed  # as VS Code sends it: the words stand for the choice
    if not typed and (value is None or value == "" or value == []):
        return None, ""
    if kind == "single-select":
        if not isinstance(value, str) or value not in ids:
            raise AnswerError("bad", title)
        return {"kind": "selected", "value": value}, next(option["label"] for option in view["options"] if option["id"] == value)
    if kind == "multi-select":
        value = [] if value is None and typed else value
        if not isinstance(value, list) or not all(isinstance(one, str) and one in ids for one in value):
            raise AnswerError("bad", title)
        chosen = [one for one in ids if one in value]
        labels = [option["label"] for option in view["options"] if option["id"] in chosen]
        return {"kind": "selected-many", "value": chosen, **({"freeformValues": [typed]} if typed else {})}, ", ".join(labels + ([typed] if typed else []))
    if kind in ("text", "other"):  # `other`: a kind the board does not know; the words go as a text answer
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


def skip_actions(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """1.8.4: the actions that skip a question item whole: `inputAnswerChanged` with `skipped` for every question the agent asked (also the kinds the board cannot show), then `inputCompleted` accept."""
    request = item["request"]
    rid = str(request["id"])
    questions = [question for question in request.get("questions") or [] if isinstance(question, dict) and question.get("id")]
    answers: Dict[str, Any] = {str(question["id"]): {"state": "skipped"} for question in questions}
    actions: List[Dict[str, Any]] = [{"type": "chat/inputAnswerChanged", "requestId": rid, "questionId": key, "answer": dict(answer)} for key, answer in answers.items()]
    actions.append({"type": "chat/inputCompleted", "requestId": rid, "response": "accept", "answers": answers})
    return actions


def find(items: Any, ident: str) -> Optional[Dict[str, Any]]:
    return next((item for item in items or [] if isinstance(item, dict) and item.get("id") == ident), None)


def first_for(items: Any, chat: Any) -> Tuple[Optional[Dict[str, Any]], int]:
    """The oldest item of this chat that is one of the kinds the board shows, and how many there are. The page shows one at a time: the one answered first."""
    chats = {chat} if isinstance(chat, str) else set(chat)  # the chat of the task and, while their calls run, the chats of its subagents
    mine = [view for view in (shown(item) for item in items or [] if isinstance(item, dict) and item.get("chat") in chats) if view]
    return (mine[0] if mine else None), len(mine)
