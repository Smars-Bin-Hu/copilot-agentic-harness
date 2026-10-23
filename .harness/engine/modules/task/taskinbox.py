"""`INBOX/` (1.5.42): what the person gives the task on its page, saved by the board server, read by the agent.

The person runs something in an environment and has the output, the commands and screenshots. The task page takes them in (text and pictures pasted into
a form) and the server writes them under `INBOX/<ENV>/<time>/`: `given.txt` (the output), `ran.txt` (the commands, when given) and `image-N.<type>`.
`INBOX/` is a person's folder like `REQ/` and `REF/`: the agent's file tools cannot write there, so what is in it is what the person gave. The agent
reads the newest folder of the environment and records it with `task test record` or `task run record` (which copy the pictures into the task).

The server picks every name. The environment is a short name; a picture is taken by what its first bytes say it is, not by its name or the type the
browser claims; sizes and counts are limited; nothing is written outside the task folder.
"""

from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from core import messages, tasks
from core.paths import utc_now

from . import task as task_ops
from .common import CommandError

INBOX = "INBOX"
ENV_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,11}$")
MAX_TEXT_BYTES = 400_000
MAX_RAN_BYTES = 100_000
MAX_IMAGES = 10
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF87a", ".gif"), (b"GIF89a", ".gif"))


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def image_type(data: bytes) -> str:
    """The file type a picture really is, from its first bytes; "" when it is none the page shows (svg is not one: it can carry a script)."""
    for head, suffix in MAGIC:
        if data.startswith(head):
            return suffix
    return ".webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else ""


def save(root: Path, raw_task: str, env: str, text: str, ran: str, images: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write what the person gave for an environment. `images`: `{"data": <base64>}` each. Returns the folder (from the task folder) and what to tell the agent."""
    env = str(env or "").strip()
    if not ENV_NAME.match(env):
        raise CommandError(say("inbox.env"))
    text, ran = str(text or ""), str(ran or "")
    if not text.strip() and not images:
        raise CommandError(say("inbox.empty"))
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES or len(ran.encode("utf-8")) > MAX_RAN_BYTES:
        raise CommandError(say("inbox.text_big", kb=MAX_TEXT_BYTES // 1000, ran_kb=MAX_RAN_BYTES // 1000))
    if len(images) > MAX_IMAGES:
        raise CommandError(say("inbox.images_many", limit=MAX_IMAGES))
    pictures = []
    for number, item in enumerate(images, 1):
        try:
            data = base64.b64decode(str(item.get("data", "") if isinstance(item, dict) else ""), validate=True)
        except ValueError:  # binascii.Error is one
            raise CommandError(say("inbox.image_bad", n=number)) from None
        if len(data) > MAX_IMAGE_BYTES:
            raise CommandError(say("inbox.image_big", n=number, mb=MAX_IMAGE_BYTES // (1024 * 1024)))
        suffix = image_type(data)
        if not suffix:
            raise CommandError(say("inbox.image_type", n=number))
        pictures.append((f"image-{number}{suffix}", data))
    task = task_ops.resolve(root, raw_task)
    data_now = tasks.read(root, task)
    task_ops.require_open(data_now)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    relative = f"{INBOX}/{env.upper()}/{stamp}"
    folder = tasks.task_dir(root, task) / relative
    suffix = 1
    while folder.exists():  # two in one second: the second gets its own folder
        suffix += 1
        folder = tasks.task_dir(root, task) / f"{relative}-{suffix}"
    folder.mkdir(parents=True)
    if text.strip():
        (folder / "given.txt").write_text(text.replace("\r\n", "\n"), encoding="utf-8")
    if ran.strip():
        (folder / "ran.txt").write_text(ran.replace("\r\n", "\n"), encoding="utf-8")
    for name, data in pictures:
        (folder / name).write_bytes(data)
    where = folder.relative_to(tasks.task_dir(root, task)).as_posix()
    with task_ops.locked(root, task) as fresh:
        task_ops.note(fresh, "inbox", f"{env.upper()}: {where}")
    files = sorted(path.name for path in folder.iterdir())
    return {"task": task, "env": env.upper(), "folder": where, "files": files, "saved_at": utc_now(),
            "message": say("inbox.message", env=env.upper(), folder=where)}
