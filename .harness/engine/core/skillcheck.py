"""Is a skill well formed? The checks a person would do by hand before putting a skill into `.github/skills/`.

Used by `harness skill check` and by `doctor`. It reads files only. An error is a skill that Copilot cannot load or that has a
dead link; a warning is a skill that loads but will be found or used badly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import config, messages

SKILLS_DIR = ".github/skills"
PREFIXES = ("harness-", "generic-", "domain-")
COMPANY_FORM = re.compile(r"^[a-z0-9]+$")
RESERVED = ("harness", "generic", "domain")
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DOMAIN_NAME = re.compile(r"^domain-[a-z0-9]+-[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_DESCRIPTION, MAX_DESCRIPTION, WIDE_DESCRIPTION = 10, 1024, 600
MAX_BODY, BIG_BODY = 500, 200
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+_\-]{12,}")
WHEN = re.compile(r"(?i)\bwhen\b|\bif the user\b|\bwhenever\b")
RESOURCE_DIRS = ("references", "templates", "scripts", "assets")


def company_prefix(root: Path) -> str:
    """The first word of the company's own skills (`skill_prefix` of the policy `user`), or "" when it is not set or not valid (`doctor` says which)."""
    return usable(config.policy_or_empty(root, "user").get("skill_prefix", ""))


def usable(value: Any) -> str:
    return value if isinstance(value, str) and COMPANY_FORM.match(value) and value not in RESERVED else ""


def prefix_problem(root: Path) -> str:
    """Why `skill_prefix` is not used, or "" when it is empty or fine."""
    value = config.policy_or_empty(root, "user").get("skill_prefix", "")
    if value in ("", None):
        return ""
    if not isinstance(value, str) or not COMPANY_FORM.match(value):
        return say("skill.prefix.form", value=value)
    if value in RESERVED:
        return say("skill.prefix.reserved", value=value)
    return ""


def prefixes(root: Path) -> Tuple[str, ...]:
    """The prefixes a skill of ours or of the company has: the three of the harness, and the company's when it is set."""
    company = company_prefix(root)
    return PREFIXES + ((company + "-",) if company else ())


def frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """(the keys of the frontmatter, the body). A small reading of YAML: `key: value`, quoted values, and `>` or `|` blocks."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}, text
    fields: Dict[str, str] = {}
    index = 1
    while index < end:
        match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", lines[index])
        index += 1
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            while index < end and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                block.append(lines[index].strip())
                index += 1
            value = (" " if value.startswith(">") else "\n").join(part for part in block if part)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].replace("''", "'") if value[0] == "'" else value[1:-1]
        fields[key] = value
    return fields, "\n".join(lines[end + 1:])


def links_of(body: str) -> List[str]:
    """The relative links of a body: not those in code, not web addresses, not anchors inside the same file. Without the `#anchor`."""
    plain = INLINE_CODE.sub("", FENCE.sub("", body))
    found = []
    for target in LINK.findall(plain):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        found.append(target.split("#", 1)[0])
    return [item for item in found if item]


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def check(folder: Path, company: str = "") -> Dict[str, Any]:
    """{"skill", "errors", "warnings"} for one skill folder. `company`: the company's prefix, when it has one."""
    owned = PREFIXES + ((company + "-",) if company else ())
    errors: List[str] = []
    warnings: List[str] = []
    result = {"skill": folder.name, "errors": errors, "warnings": warnings}
    file = folder / "SKILL.md"
    if not file.is_file():
        errors.append(say("skill.no_file"))
        return result
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        errors.append(say("skill.unreadable", error=error))
        return result
    fields, body = frontmatter(text)
    if not fields:
        errors.append(say("skill.no_frontmatter"))
        return result
    name = fields.get("name", "")
    if not name:
        errors.append(say("skill.name.missing"))
    else:
        if name != folder.name:
            errors.append(say("skill.name.folder", name=name, folder=folder.name))
        if not NAME.match(name) or len(name) > 64:
            errors.append(say("skill.name.form"))
        if name.startswith("domain-") and not DOMAIN_NAME.match(name):
            errors.append(say("skill.name.domain"))
        elif not name.startswith(owned):
            warnings.append(say("skill.name.prefix", prefixes=", ".join(owned)))
    description = fields.get("description", "")
    if not description:
        errors.append(say("skill.desc.missing"))
    else:
        if len(description) < MIN_DESCRIPTION:
            errors.append(say("skill.desc.short", count=len(description), minimum=MIN_DESCRIPTION))
        if len(description) > MAX_DESCRIPTION:
            errors.append(say("skill.desc.long", count=len(description), maximum=MAX_DESCRIPTION))
        elif len(description) > WIDE_DESCRIPTION:
            warnings.append(say("skill.desc.wide", count=len(description), limit=WIDE_DESCRIPTION))
        if not WHEN.search(description):
            warnings.append(say("skill.desc.when"))
    if name.startswith(owned):
        if fields.get("type") not in ("unit", "workflow"):
            warnings.append(say("skill.type"))
        if not fields.get("specificTo"):
            warnings.append(say("skill.specific.missing"))
        elif DOMAIN_NAME.match(name) and fields["specificTo"] != name.split("-")[1]:
            warnings.append(say("skill.specific.domain", actual=fields["specificTo"], expected=name.split("-")[1]))
    lines = len(body.splitlines())
    if lines > MAX_BODY:
        errors.append(say("skill.body.long", count=lines, maximum=MAX_BODY))
    elif lines > BIG_BODY:
        warnings.append(say("skill.body.big", count=lines, limit=BIG_BODY))
    for link in links_of(body):
        target = (folder / link).resolve()
        if not target.exists():
            errors.append(say("skill.link", link=link))
    if not re.search(r"(?mi)^#{2,3}\s+gotchas\b", body):
        warnings.append(say("skill.gotchas"))
    if ".claude/" in text:
        warnings.append(say("skill.claude"))
    secret = SECRET.search(text)
    if secret:
        warnings.append(say("skill.secret", what=secret.group(1)))
    warnings += orphans(folder, text)
    return result


def orphans(folder: Path, skill_text: str) -> List[str]:
    """Files in references/, templates/, scripts/ or assets/ that no text of the skill names. Copilot opens a file only when a link points at it."""
    texts = [skill_text]
    for item in folder.rglob("*.md"):
        if item.name != "SKILL.md" or item.parent != folder:
            try:
                texts.append(item.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    joined = "\n".join(texts)
    found = []
    for name in RESOURCE_DIRS:
        for item in sorted((folder / name).rglob("*")) if (folder / name).is_dir() else []:
            if item.is_file() and item.name != ".gitkeep" and "__pycache__" not in item.parts:  # Python's own cache of a script
                relative = item.relative_to(folder).as_posix()
                if relative not in joined and item.name not in joined:
                    found.append(say("skill.orphan", path=relative))
    return found


def check_all(root: Path, only: List[str] | None = None) -> List[Dict[str, Any]]:
    """Every skill folder under `.github/skills/`, or the named ones (a folder name or a path)."""
    base = root / SKILLS_DIR
    if only:
        folders = []
        for item in only:
            path = Path(item)
            folders.append(path if path.is_dir() or path.is_absolute() else base / item)
    else:
        from . import domainskills  # it reads frontmatter with this module

        folders = [item for item in sorted(base.iterdir()) if item.is_dir()] if base.is_dir() else []
        folders += domainskills.folders(root)  # the skills of the domains, in the knowledge base
    company = company_prefix(root)
    return [check(folder, company) for folder in folders]
