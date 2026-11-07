"""Which of three groups a skill belongs to, by its name alone (1.7.32). The Company tab and the skill list of the board both use this rule.

  harness-*, generic-*      come with the harness
  <prefix>-<pack>-<name>    the SOP of a tool pack, as the company named it (the pack is an active tool pack)
  <pack>-<name>             the same, with no company prefix
  <prefix>-<name>           the company's own SOP

`active_packs` is the one place that reads which tool packs are active. Everything of the board that shows packs goes through it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

HARNESS_WORDS = ("harness", "generic")


def active_packs(root: Path) -> Dict[str, Dict[str, Any]]:
    """`{name: {folder, manifest}}` of the tool packs the agent can use now. Today: the packs installed in `.harness/toolpacks/`.
    Re-point this one function when packs are read from somewhere else."""
    from . import toolpacks  # it reads the policies, which read this module's rule

    return toolpacks.installed(root)


def group(name: str, prefix: str, packs: Any) -> Tuple[str, str]:
    """`(group, pack)`: group is `harness`, `pack` or `company`; pack is the pack's name, or ''."""
    first = name.split("-")[0]
    if first in HARNESS_WORDS:
        return "harness", ""
    rest = name[len(prefix) + 1:] if prefix and name.startswith(prefix + "-") else name
    for pack in sorted(packs, key=len, reverse=True):
        if rest.startswith(pack + "-"):
            return "pack", pack
    return "company", ""
