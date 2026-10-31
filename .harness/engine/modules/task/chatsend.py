"""What the board says to the chat of a task, and what it keeps of it (1.6, B72). A page only shows the text: it is made here.

The text of a message to the agent is English and fixed. A person can add a line or two (notes), pick the reply language and, for an answer, write the text; nobody can change
the words of a template. Control marks (`[ZH]`) are added only when the person chose them; `[review]` is never in a message (the number of checks is set on the task page).

  go-req, go-plan, go-promote   the three approvals: the template with the code the person just typed (the board keeps it in memory; see `boardserve.Board.codes`)
  go-recover, go-review         a plain line, no code
  answer                        the person's own words, no template

Notes: the saved drafts of the task (`.task/drafts.json`, the person's file: never in a digest, never written back) and the note typed in the panel go last, one line each, after
`Notes from the person:`. A message that went is kept whole in `.task/sent.jsonl`, one JSON line each.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import tasks
from core.paths import utc_now
from core.state import atomic_write, state_lock

LANGS = ("en", "zh")
MAX_TEXT = 20000  # characters of one message
MAX_NOTE = 2000  # characters of one note or draft
MAX_DRAFTS = 50
SUMMARY_CHARS = 100
NOTES_HEAD = "Notes from the person:"
ZH_MARK = "[ZH]"
DRAFTS_NAME = "drafts.json"
SENT_NAME = "sent.jsonl"

TEMPLATES = {
    "go-req": "Requirement confirmed (REQ.md, code {code}). Go on.",
    "go-plan": "Plan approved (PLAN.md, code {code}). Go on with TODO.md.",
    "go-promote": "Write-back plan approved (code {code}). Go on with the promote, then stop and report.",
}
NO_CODE = {  # the approval was made where the board did not see the code (a terminal, or before the board started)
    "go-req": "Requirement confirmed (REQ.md). Go on.",
    "go-plan": "Plan approved (PLAN.md). Go on with TODO.md.",
    "go-promote": "Write-back plan approved. Go on with the promote, then stop and report.",
}
PLAIN = {"go-recover": "The repositories are put back. Try the write-back again.", "go-review": "The checks are decided. Go on."}
GO = tuple(TEMPLATES) + tuple(PLAIN)
CODE_OF_ACTION = {"confirm-req": "go-req", "approve-plan": "go-plan", "approve-promote": "go-promote"}  # the approval that leaves each mark


def template(why: str, code: str = "") -> str:
    """The fixed text for a `go-*` wait. Empty for a wait that has none."""
    if why in PLAIN:
        return PLAIN[why]
    if why in TEMPLATES:
        return TEMPLATES[why].format(code=code) if code else NO_CODE[why]
    return ""


def one_line(text: str, limit: int = MAX_NOTE) -> str:
    return " ".join(str(text or "").split())[:limit]


def lines_of(text: str) -> List[str]:
    """Each non-empty line of what a person typed, as one note."""
    return [line for line in (one_line(raw) for raw in str(text or "").splitlines()) if line]


def compose(head: str, lang: str, notes: List[str]) -> str:
    """The message: `[ZH]` first when Chinese was chosen, the head, then the notes (one line each)."""
    text = head.strip()
    if notes:
        text += "\n\n" + NOTES_HEAD + "\n" + "\n".join("- " + note for note in notes)
    return (ZH_MARK + " " + text) if lang == "zh" else text


def summary(text: str) -> str:
    """What the history shows of a message: one line."""
    flat = one_line(text, 10 ** 6)
    return flat if len(flat) <= SUMMARY_CHARS else flat[:SUMMARY_CHARS - 1].rstrip() + "…"


# --- the files of a task: drafts and what was sent ----------------------------------------------------------------

def drafts_file(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.STATE_DIR / DRAFTS_NAME


def sent_file(root: Path, task: str) -> Path:
    return tasks.task_dir(root, task) / tasks.STATE_DIR / SENT_NAME


def drafts(root: Path, task: str) -> List[Dict[str, str]]:
    """The saved drafts, oldest first: {id, at, text, use}. `use` false: kept, but left out of the next message. A file that cannot be read holds none."""
    try:
        found = json.loads(drafts_file(root, task).read_text(encoding="utf-8-sig")).get("items")
    except (OSError, ValueError, AttributeError):
        return []
    return [{"id": str(item["id"]), "at": str(item.get("at") or ""), "text": str(item["text"]), "use": item.get("use") is not False} for item in found or [] if isinstance(item, dict) and item.get("id") and str(item.get("text") or "").strip()]


def add_draft(root: Path, task: str, text: str) -> Dict[str, str]:
    """Append one draft (one line)."""
    line = one_line(text)
    if not line:
        raise ValueError("empty")
    path = drafts_file(root, task)
    with state_lock(path):
        items = drafts(root, task)
        if len(items) >= MAX_DRAFTS:
            raise ValueError("full")
        entry = {"id": secrets.token_hex(4), "at": utc_now(), "text": line}
        atomic_write(path, {"items": items + [entry]})
    return entry


def change_draft(root: Path, task: str, draft_id: str, text: Optional[str] = None, use: Optional[bool] = None, delete: bool = False) -> None:
    """Edit the text of one draft, switch it in or out of the next message, or delete it. ValueError("gone") for an id that is not there, ("empty") for a text with nothing in it."""
    line = None if text is None else one_line(text)
    if line is not None and not line:
        raise ValueError("empty")
    path = drafts_file(root, task)
    with state_lock(path):
        items = drafts(root, task)
        if not any(item["id"] == draft_id for item in items):
            raise ValueError("gone")
        out = []
        for item in items:
            if item["id"] == draft_id:
                if delete:
                    continue
                if line is not None:
                    item = dict(item, text=line)
                if use is not None:
                    item = dict(item, use=use)
            out.append(item)
        atomic_write(path, {"items": out})


def drop_drafts(root: Path, task: str, ids: List[str]) -> None:
    """Take the drafts that went into a message out of the file (the ones saved meanwhile stay)."""
    if not ids:
        return
    path = drafts_file(root, task)
    with state_lock(path):
        left = [item for item in drafts(root, task) if item["id"] not in ids]
        atomic_write(path, {"items": left})


def record(root: Path, task: str, entry: Dict[str, Any]) -> None:
    """One line of `.task/sent.jsonl`: the whole message and where it went."""
    path = sent_file(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    with state_lock(path):
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def prepare(root: Path, task: str, kind: str, why: str, code: str, lang: str, body: str, note: str, with_drafts: bool = True) -> Dict[str, Any]:
    """The message of a send, whole: `{text, notes (the lines added), draft_ids (the drafts merged)}`. Raises ValueError("kind"|"empty"|"long") for what cannot be sent."""
    lang = lang if lang in LANGS else "en"
    if kind == "go":
        head = template(why, code)
        if not head:
            raise ValueError("kind")
    elif kind == "answer":
        head = str(body or "").strip()
        if not head:
            raise ValueError("empty")
    else:
        raise ValueError("kind")
    saved = [item for item in drafts(root, task) if item["use"]] if with_drafts else []
    notes = [item["text"] for item in saved] + lines_of(note)
    text = compose(head, lang, notes)
    if len(text) > MAX_TEXT:
        raise ValueError("long")
    return {"text": text, "notes": notes, "draft_ids": [item["id"] for item in saved], "lang": lang}


def steer_text(body: str) -> Tuple[str, str]:
    """The text of a steer: what the person typed, as it is. (text, problem) where problem is "" or "empty" or "long"."""
    text = str(body or "").strip()
    if not text:
        return "", "empty"
    return (text, "long") if len(text) > MAX_TEXT else (text, "")


def model_of(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The model the person chose for this task (`chat.model`), in the shape of `message.model`: {id} or {id, config}. None: the chat keeps the one it had."""
    model = (data.get("chat") or {}).get("model") if isinstance(data.get("chat"), dict) else None
    if not isinstance(model, dict) or not model.get("id"):
        return None
    out: Dict[str, Any] = {"id": str(model["id"])}
    if isinstance(model.get("config"), dict) and model["config"]:
        out["config"] = dict(model["config"])
    return out
