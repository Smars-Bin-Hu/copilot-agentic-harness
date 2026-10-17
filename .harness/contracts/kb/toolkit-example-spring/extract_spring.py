"""Toolkit extractors for a Spring Boot service (Java): classes by role, HTTP endpoints, JPA tables, Thymeleaf views.

  java      one object per top-level type, typed by its role (controller, service, repository, entity, component,
            class), and one `endpoint:<METHOD> <path>` per request mapping of a controller
  template  a Thymeleaf template is `view:<path under templates/ without .html>`, the name a controller returns

Standard library only. Written from spring-petclinic; the forms it knows are listed in DESIGN.md.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

TYPE = re.compile(r"^(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+|sealed\s+)*(class|interface|enum|record)\s+([A-Z]\w*)([^{]*)\{", re.MULTILINE)
ROLE = (("@RestController", "controller"), ("@Controller", "controller"), ("@Service", "service"), ("@Entity", "entity"), ("@Configuration", "component"), ("@Component", "component"))
REPOSITORY = re.compile(r"extends\s+(?:Jpa|Crud|PagingAndSorting|ListCrud|)Repository\s*<\s*([A-Z]\w*)")
EXTENDS = re.compile(r"\bextends\s+([A-Z]\w*)")
TABLE = re.compile(r"@Table\s*\(\s*name\s*=\s*\"([^\"]+)\"")
FIELD = re.compile(r"^\s*(?:private|protected|public)?\s*(?:final\s+)?(?:static\s+)?([A-Z]\w*)(?:\s*<([^;=()]*)>)?\s+[a-z]\w*\s*[;=]", re.MULTILINE)
PARAMS = re.compile(r"\b(?:public|protected)?\s*([A-Z]\w*)\s*\(([^)]*)\)\s*\{")
CLASS_MAPPING = re.compile(r"@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"")
MAPPING = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\s*(?:\(([^)]*)\))?")
PATHS = re.compile(r"\"([^\"]*)\"")
VIEW = re.compile(r"(?:return|new\s+ModelAndView\s*\()\s*\"([^\"]+)\"")
CONSTANT = re.compile(r"static\s+final\s+String\s+([A-Z_][A-Z0-9_]*)\s*=\s*\"([^\"]*)\"")
RETURN_CONSTANT = re.compile(r"(?:return|new\s+ModelAndView\s*\()\s*([A-Z_][A-Z0-9_]*)\s*[;)]")
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
JAVA_TYPES = {"String", "Integer", "Long", "Boolean", "Double", "Float", "Object", "List", "Set", "Map", "Optional", "Collection", "LocalDate", "LocalDateTime", "Page", "Pageable", "Model", "BindingResult", "RedirectAttributes", "WebDataBinder", "ModelAndView"}


def blank_comments(text: str) -> str:
    return COMMENT.sub(lambda match: re.sub(r"[^\n]", " ", match.group(0)), text)


def line_at(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def used_types(text: str) -> List[str]:
    found = []
    for match in FIELD.finditer(text):
        found.append(match.group(1))
        found += re.findall(r"[A-Z]\w*", match.group(2) or "")
    for match in PARAMS.finditer(text):
        found += re.findall(r"\b([A-Z]\w*)\s+[a-z]\w*", match.group(2))
    return [name for name in dict.fromkeys(found) if name not in JAVA_TYPES]


def java(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    clean = blank_comments(text)
    match = TYPE.search(clean)
    if not match:
        return []
    name, head = match.group(2), clean[:match.start()]
    role = next((role for mark, role in ROLE if mark in head), "class")
    repository = REPOSITORY.search(match.group(3))
    if repository:
        role = "repository"
    refs: List[Dict[str, Any]] = []
    if repository:
        refs.append({"kind": "reads", "name": repository.group(1), "as": "entity", "line": line_at(clean, match.start(3))})
    parent = EXTENDS.search(match.group(3))
    if parent and not repository:
        refs.append({"kind": "extends", "name": parent.group(1), "line": line_at(clean, match.start(3))})
    table = TABLE.search(head)
    if table:
        refs.append({"kind": "maps", "name": table.group(1), "as": "table", "line": line_at(clean, table.start(1))})
    body = clean[match.end():]
    offset = line_at(clean, match.end()) - 1
    for used in used_types(body):
        if used != name:
            refs.append({"kind": "uses", "name": used, "line": offset + 1})
    found = [{"id": f"{role}:{name}", "type": role, "name": name, "line": line_at(clean, match.start(2)), "dynamic": False, "refs": refs}]
    if role == "controller":
        found += endpoints(clean, head, body, offset, name)
    return found


def endpoints(clean: str, head: str, body: str, offset: int, controller: str) -> List[Dict[str, Any]]:
    prefix_match = CLASS_MAPPING.search(head)
    prefix = prefix_match.group(1).rstrip("/") if prefix_match else ""
    marks = list(MAPPING.finditer(body))
    found = []
    for number, mark in enumerate(marks):
        method = mark.group(1).upper()
        paths = PATHS.findall(mark.group(2) or "") or [""]
        until = marks[number + 1].start() if number + 1 < len(marks) else len(body)
        method_body = body[mark.end():until]
        constants = dict(CONSTANT.findall(body))
        named = VIEW.findall(method_body) + [constants[name] for name in RETURN_CONSTANT.findall(method_body) if name in constants]
        views = [view for view in named if not view.startswith(("redirect:", "forward:"))]
        for path in paths:
            name = f"{method} {prefix}{path}" or f"{method} /"
            refs = [{"kind": "handled_by", "name": controller, "as": "controller", "line": offset + line_at(body, mark.start())}]
            refs += [{"kind": "renders", "name": view, "as": "view", "line": offset + line_at(body, mark.start())} for view in dict.fromkeys(views)]
            found.append({"id": f"endpoint:{name}", "type": "endpoint", "name": name, "line": offset + line_at(body, mark.start()), "dynamic": False, "refs": refs})
    return found


def template(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = context["path"]
    name = path.split("/templates/", 1)[-1]
    name = name[:-5] if name.endswith(".html") else name
    return [{"id": f"view:{name}", "type": "view", "name": name, "line": 1, "dynamic": False, "refs": []}]
