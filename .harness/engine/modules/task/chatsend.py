"""What the board says to the chat of a task, and what it keeps of it (1.6, B72). A page only shows the text: it is made here.

The text of a message to the agent is English and fixed. A person can add a line or two (notes), pick the reply language and, for an answer, write the text; nobody can change
the words of a template. Control marks (`[ZH]`) are added only when the person chose them; `[review]` is never in a message (the number of checks is set on the task page).

  go-req, go-plan, go-promote   the three approvals
  go-recover, go-review         a plain line
  (no template holds the confirmation code: it is typed by a person at an approval and goes nowhere else)
  answer                        the person's own words, no template

Notes: the saved drafts of the task (`.task/drafts.json`, the person's file: never in a digest, never written back) and the note typed in the panel go last, one line each, after
`Notes from the person:`. A message that went is kept whole in `.task/sent.jsonl`, one JSON line each.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import messages, tasks
from core.paths import utc_now
from core.state import atomic_write, state_lock, state_path

LANGS = ("en", "zh")
MAX_TEXT = 20000  # characters of one message
MAX_FILES = 10  # files of one message
MAX_FILE = 10 * 1024 * 1024  # bytes of one file
MAX_FILES_TOTAL = 20 * 1024 * 1024  # bytes of all the files of one message
FILE_TYPE = re.compile(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+")
MAX_NOTE = 2000  # characters of one note or draft
MAX_DRAFTS = 50
SUMMARY_CHARS = 100
NOTES_HEAD = "Notes from the person:"
ZH_MARK = "[ZH]"
EN_MARK = "[EN]"
DRAFTS_NAME = "drafts.json"
SENT_NAME = "sent.jsonl"

TEMPLATES = {
    "go-req": "Requirement confirmed (REQ.md). Go on.",
    "go-plan": "Plan approved (PLAN.md). Go on with TODO.md.",
    "go-promote": "Promote (write-back repo) approved. Go on with the promote, then stop and report.",
}
PLAIN = {"go-recover": "The repositories are put back. Try the promote (write-back repo) again.", "go-review": "The checks are decided. Go on."}
COMPACT_TEXT = "/compact"  # the one control mark the board sends, and only when the person pressed the compact button (`Board.compact`); no template holds it
GO = tuple(TEMPLATES) + tuple(PLAIN)


def template(why: str) -> str:
    """The fixed text for a `go-*` wait. Empty for a wait that has none. It holds no confirmation code: the agent does not need it."""
    return PLAIN.get(why) or TEMPLATES.get(why) or ""


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


def reply_of(root: Path, task: str) -> str:
    """The language this task's chat replies in: what `[ZH]` or `[EN]` last said in its session, else the language setting."""
    data = tasks.read(root, task) or {}
    try:
        state = json.loads(state_path(root, str(data.get("surface") or "vscode"), str(data.get("session_id") or "")).read_text(encoding="utf-8"))
        reply = ((state.get("modules") or {}).get("task") or {}).get("reply")
    except (OSError, ValueError, AttributeError):
        reply = None
    return reply if reply in LANGS else messages.language()


def with_english(root: Path, task: str, chosen: str, text: str) -> str:
    """The person chose English for a chat that replies in Chinese: only `[EN]` turns it back. An empty `chosen` means they did not touch it: the chat stays as it is."""
    return f"{EN_MARK} {text}" if chosen == "en" and reply_of(root, task) == "zh" else text


def prepare(root: Path, task: str, kind: str, why: str, lang: str, body: str, note: str, with_drafts: bool = True) -> Dict[str, Any]:
    """The message of a send, whole: `{text, notes (the lines added), draft_ids (the drafts merged), reply}`. Raises ValueError("kind"|"empty"|"long") for what cannot be sent."""
    chosen, lang = lang, lang if lang in LANGS else "en"
    if kind == "go":
        head = template(why)
        if not head:
            raise ValueError("kind")
    elif kind == "answer":
        head = str(body or "").strip()
        if not head:
            raise ValueError("empty")
    elif kind == "command":  # "Ask agent" on a code block: the command and nothing else; the drafts wait for the next message
        command = str(body or "").strip()
        if not command:
            raise ValueError("empty")
        mark = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", command)), default=0))
        head = f"Run this command and report the output:\n\n{mark}\n{command}\n{mark}"
        with_drafts = False
    else:
        raise ValueError("kind")
    saved = [item for item in drafts(root, task) if item["use"]] if with_drafts else []
    notes = [item["text"] for item in saved] + lines_of(note)
    text = with_english(root, task, chosen, compose(head, lang, notes))
    if len(text) > MAX_TEXT:
        raise ValueError("long")
    return {"text": text, "notes": notes, "draft_ids": [item["id"] for item in saved], "lang": lang, "reply": reply_of(root, task)}


def steer_text(body: str, lang: str = "en") -> Tuple[str, str]:
    """The text of a steer: what the person typed, as it is, with `[ZH]` first when Chinese was chosen (the reply panel). (text, problem) where problem is "" or "empty" or "long"."""
    text = str(body or "").strip()
    if not text:
        return "", "empty"
    if lang == "zh":
        text = ZH_MARK + " " + text
    return (text, "long") if len(text) > MAX_TEXT else (text, "")


def attachments(items: Any) -> List[Dict[str, Any]]:
    """What the page attached to a message, as the host takes it. An `embeddedResource` of any type reaches the model: pictures, text and PDF were read back on a real chat (2026-11-01). The host
    keeps a copy and lists its own address in the chat, so the bytes stay out of the snapshots. ValueError: `file-count`, `file-big` or `file-bad`."""
    if items is None or items == []:
        return []
    if not isinstance(items, list) or len(items) > MAX_FILES:
        raise ValueError("file-count")
    out: List[Dict[str, Any]] = []
    total = 0
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str) or not str(item.get("name") or "").strip():
            raise ValueError("file-bad")
        try:
            size = len(base64.b64decode(item["data"], validate=True))
        except ValueError:
            raise ValueError("file-bad") from None
        total += size
        if size > MAX_FILE or total > MAX_FILES_TOTAL:
            raise ValueError("file-big")
        kind = str(item.get("type") or "")
        out.append({"type": "embeddedResource", "data": item["data"], "contentType": kind if FILE_TYPE.fullmatch(kind) else "application/octet-stream", "label": re.split(r"[\\/]", str(item["name"]).strip())[-1][:200]})
    return out


def listed(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What `.task/sent.jsonl` keeps of the files of a message: the name and the size, not the bytes."""
    return [{"name": item["label"], "type": item["contentType"], "bytes": len(item["data"]) * 3 // 4} for item in files]


def model_of(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The model the person chose for this task (`chat.model`), in the shape of `message.model`: {id} or {id, config}. None: the chat keeps the one it had."""
    model = (data.get("chat") or {}).get("model") if isinstance(data.get("chat"), dict) else None
    if not isinstance(model, dict) or not model.get("id"):
        return None
    out: Dict[str, Any] = {"id": str(model["id"])}
    if isinstance(model.get("config"), dict) and model["config"]:
        out["config"] = dict(model["config"])
    return out
