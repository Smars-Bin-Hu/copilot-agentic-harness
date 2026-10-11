"""`kb reads`: which knowledge base files the tasks read, and which nobody read (M8-8).

From the `kb` field of the session logs (core/kbreads.py). A file nobody reads may be of no use, or the index does not
lead to it. A file a failed task never opened is a gap. Folders that were searched are listed apart: a search over a
folder does not say which of its files were read.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import targets
from core.kbreads import reads_by_task, task_name
from core.paths import utc_now

NEVER_READ_SHOWN = 100
SKIPPED_NAMES = (".git", ".DS_Store", ".gitkeep")


def files_of(folder: Path) -> List[str]:
    found: List[str] = []
    for current, folders, files in os.walk(str(folder)):
        folders[:] = sorted(name for name in folders if name not in SKIPPED_NAMES)
        for name in sorted(files):
            if name not in SKIPPED_NAMES:
                found.append((Path(current) / name).relative_to(folder).as_posix())
    return found


def collect(root: Path, days: Optional[int] = None, task: str = "") -> Dict[str, Any]:
    found = reads_by_task(root, days)
    wanted = task_name(task) if task else ""
    rows = [
        {"file": path, "reads": entry["reads"], "tasks": sorted(entry["tasks"]), "sessions": len(entry["sessions"])}
        for path, entry in found.items() if not wanted or wanted in entry["tasks"]
    ]
    rows.sort(key=lambda row: (-row["reads"], row["file"]))
    files = [row for row in rows if not row["file"].endswith("/")]
    bases = []
    for name, folder in targets.knowledge_bases(root):
        if not folder.is_dir():
            continue
        every = files_of(folder)
        seen = {row["file"] for row in files}
        never = [path for path in every if f"{name}/{path}" not in seen]
        bases.append({
            "name": name, "path": str(folder), "files": len(every), "read": len(every) - len(never),
            "never_read": never[:NEVER_READ_SHOWN], "never_read_count": len(never),
        })
    return {
        "knowledge_bases": bases, "files": files, "folders_searched": [row for row in rows if row["file"].endswith("/")],
        "task": wanted, "days": days, "as_of": utc_now(),
        "note": "只记工具点名的文件：read、search 工具的路径，和终端命令里写出来的路径。搜索一个文件夹只记文件夹，不知道读了其中哪些文件。",
    }
