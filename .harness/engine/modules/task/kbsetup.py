"""`target init-kb`: make `knowledge-base/` a git repository, so that a task can update it.

The setup skill runs it after the knowledge base is copied in. A knowledge base that came with its own `.git` is left as it is.
Each step looks at the state first, so a run that stopped (no git identity, say) is finished by running it again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from core import config, targets

from .common import CommandError, say

COMMIT_MESSAGE = "Initial knowledge base"


def base_ref(root: Path) -> str:
    """The branch the knowledge base is committed on: its own `base_ref` when registered, else the one of target.json."""
    policy = config.load_policy(root, targets.POLICY_NAME)
    kb = (root / targets.KB_DIR).resolve()
    for name, folder in targets.knowledge_bases(root):
        entry = (policy.get("repos") or {}).get(name)
        if name != targets.KB_DIR and isinstance(entry, dict) and entry.get("base_ref") and folder.resolve() == kb:
            return str(entry["base_ref"])
    return str(policy.get("base_ref") or "main")


def step(folder: Path, *arguments: str) -> str:
    code, said = targets.run_step(folder, list(arguments))
    if code != 0:
        raise CommandError(say("kb.init.failed", arguments=" ".join(arguments), message=said))
    return said


def init(root: Path) -> Dict[str, Any]:
    folder = root / targets.KB_DIR
    if not targets.knowledge_base_content(folder):
        raise CommandError(say("kb.init.empty", kb=targets.KB_DIR))
    branch = base_ref(root)
    created = not (folder / ".git").exists()
    if created:
        step(folder, "init", "-q")
        step(folder, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    code, _said = targets.run_step(folder, ["rev-parse", "--verify", "--quiet", "HEAD"])
    committed = code != 0
    if committed:
        step(folder, "add", "-A")
        code, said = targets.run_step(folder, ["commit", "-q", "-m", COMMIT_MESSAGE])
        if code != 0:
            raise CommandError(say("kb.init.commit", message=said))
    registered = targets.kb_registered(root)
    return {
        "knowledge_base": targets.KB_DIR,
        "git_created": created,
        "committed": committed,
        "branch": branch,
        "registered": registered,
        "next": say("kb.init.next.check" if registered else "kb.init.next.register", kb=targets.KB_DIR),
    }
