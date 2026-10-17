"""Sample toolkit: the extractors of a SQL Server code base (database projects, SQL Agent job scripts, SSIS packages).

A toolkit is the part of the repository map that depends on the stack. It lives in `<knowledge base>/toolkit/`;
`harness kb map` calls the functions `toolkit.json` names, one file at a time:

    def <function>(text: str, context: dict) -> list[dict]

`text` is the file, decoded (UTF-8 or UTF-16 with a BOM). `context` holds `path`, `stem`, `folder` (the folder the file
is in), `repo`, and one key per entry of `markers` in toolkit.json: here `db` (the nearest `.sqlproj` above the file)
and `project` (the nearest `.dtproj`). Each object returned:

    {"id": "sp:Db.dbo.usp_load", "type": "sp", "name": "Db.dbo.usp_load", "line": 3, "dynamic": False,
     "refs": [{"kind": "calls" | "runs" | "reads" | "writes", "name": "dbo.usp_step", "db": "Db", "line": 9, "as": "package"}]}

A ref holds the name as written; `harness kb map` resolves names over all files (toolkit.json `names`: `sql`).
The contract is `.harness/contracts/kb/map.md`. This file uses the standard library only and imports nothing of the harness.

  tsql   `.sql`: CREATE PROCEDURE / VIEW / FUNCTION / TABLE / TRIGGER and what each body runs, reads and writes.
         A SQL Agent job script (`sp_add_job`, as SSMS scripts it) is read as a job: its steps run procedures and packages
  ssis   `.dtsx`: the SQL of Execute SQL tasks, the tables of data flow sources and destinations, child packages

What is only known at run time (`EXEC(@sql)`, `sp_executesql`, a package from a variable) is marked `dynamic`.
Written from the public documentation of these formats: check it against your own files (facts.jsonl) and change it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from typing import Any, Dict, List, Optional, Tuple

DEFINED = {"PROC": "sp", "PROCEDURE": "sp", "VIEW": "view", "FUNCTION": "fn", "TABLE": "table", "TRIGGER": "trigger", "SYNONYM": "synonym"}
PART = r"(?:\[[^\]\n]+\]|\"[^\"\n]+\"|[A-Za-z_#@][\w$#@]*)"
NAME = rf"{PART}(?:\s*\.\s*(?:{PART})?){{0,3}}"
GO = re.compile(r"^[ \t]*GO[ \t]*(?:\d+[ \t]*)?$", re.IGNORECASE | re.MULTILINE)
DEFINITION = re.compile(rf"\A\s*(?:CREATE(?:\s+OR\s+ALTER)?|ALTER)\s+(PROC(?:EDURE)?|VIEW|FUNCTION|TABLE|TRIGGER|SYNONYM)\s+({NAME})", re.IGNORECASE)
CALL = re.compile(rf"\bEXEC(?:UTE)?\s+(?:@\w+\s*=\s*)?({NAME})", re.IGNORECASE)
DYNAMIC = re.compile(r"\bEXEC(?:UTE)?\s*\(|\bsp_executesql\b|\bEXEC(?:UTE)?\s+@\w+(?!\s*=)", re.IGNORECASE)
WRITES = (
    re.compile(rf"\bINTO\s+({NAME})", re.IGNORECASE),  # INSERT INTO, MERGE INTO, SELECT ... INTO
    re.compile(rf"\bINSERT\s+(?!INTO\b)({NAME})", re.IGNORECASE),
    re.compile(rf"\bUPDATE\s+(?:TOP\s*\([^)]*\)\s*)?({NAME})\s+SET\b", re.IGNORECASE),
    re.compile(rf"\bDELETE\s+(?:TOP\s*\([^)]*\)\s*)?(?:FROM\s+)?({NAME})", re.IGNORECASE),
    re.compile(rf"\bMERGE\s+(?:TOP\s*\([^)]*\)\s*)?(?!INTO\b)({NAME})", re.IGNORECASE),
    re.compile(rf"\bTRUNCATE\s+TABLE\s+({NAME})", re.IGNORECASE),
)
READS = re.compile(rf"(\bDELETE\s+(?:TOP\s*\([^)]*\)\s*)?)?\b(?:FROM|JOIN|APPLY|USING)\s+({NAME})(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?", re.IGNORECASE)
CTE = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s+AS\s*\(", re.IGNORECASE)
NOT_ALIAS = {
    "where", "on", "join", "inner", "left", "right", "full", "cross", "outer", "group", "order", "having", "union", "select",
    "set", "with", "when", "then", "else", "end", "option", "for", "into", "values", "output", "pivot", "unpivot", "apply", "as",
    "go", "begin", "if", "while", "return", "insert", "update", "delete", "merge", "exec", "execute", "declare", "using", "except", "intersect",
}
NOT_TARGET = {"select", "values", "top", "openquery", "openrowset", "openjson", "openxml", "string_split", "set"}

JOB = re.compile(r"\bsp_add_job\b(?!step|schedule|server)", re.IGNORECASE)
STEP = re.compile(r"\bsp_add_jobstep\b", re.IGNORECASE)
SCHEDULE = re.compile(r"\bsp_add_(?:job)?schedule\b|\bsp_attach_schedule\b", re.IGNORECASE)
ARGUMENT = r"@{name}\s*=\s*N?'((?:[^']|'')*)'"
PACKAGE = re.compile(r"([^\\/\"';]+)\.dtsx\b", re.IGNORECASE)


# --- text -----------------------------------------------------------------------------------------


def blank(text: str) -> str:
    """The SQL with comments and string literals turned into spaces, the line breaks kept: positions and line numbers
    stay right, and a name inside a string or a comment is not taken for a use."""
    out = list(text)
    index, size = 0, len(text)
    while index < size:
        two = text[index:index + 2]
        if two == "--":
            end = text.find("\n", index)
            end = size if end < 0 else end
        elif two == "/*":
            depth, end = 1, index + 2
            while end < size and depth:
                if text.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif text.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
        elif text[index] == "'":
            end = index + 1
            while end < size:
                if text[end] == "'":
                    if text[end + 1:end + 2] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            for spot in range(index + 1, max(index + 1, end - 1)):
                if out[spot] != "\n":
                    out[spot] = " "
            index = end
            continue
        elif text[index] == "[":
            end = text.find("]", index)
            index = size if end < 0 else end + 1
            continue
        else:
            index += 1
            continue
        for spot in range(index, end):
            if out[spot] != "\n":
                out[spot] = " "
        index = end
    return "".join(out)


def parts(raw: str) -> List[str]:
    """`[Db].dbo.[My Table]` -> ["Db", "dbo", "My Table"]. `Db..t` keeps the empty schema."""
    found, current, index = [], "", 0
    while index < len(raw):
        char = raw[index]
        if char in "[\"":
            close = "]" if char == "[" else "\""
            end = raw.find(close, index + 1)
            end = len(raw) if end < 0 else end
            current += raw[index + 1:end]
            index = end + 1
            continue
        if char == ".":
            found.append(current.strip())
            current = ""
        elif not char.isspace():
            current += char
        index += 1
    found.append(current.strip())
    return found


def sql_name(raw: str, db: str = "") -> str:
    """The name as `Db.schema.name` when the database is known, `schema.name` when not. A server part is dropped."""
    pieces = parts(raw)[-3:]
    if len(pieces) == 1:
        pieces = ["dbo"] + pieces
    if len(pieces) == 3 and not pieces[1]:
        pieces[1] = "dbo"
    if len(pieces) == 2 and db:
        pieces = [db] + pieces
    return ".".join(pieces)


def line_at(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def usable(raw: str) -> bool:
    first = raw.lstrip()[:1]
    return bool(first) and first not in "@#(" and raw.strip().lower() not in NOT_TARGET


# --- T-SQL ------------------------------------------------------------------------------------------


def sql_refs(text: str, db: str, offset_line: int = 0, skip: str = "") -> Tuple[List[Dict[str, Any]], bool]:
    """(the uses in a piece of SQL, does it run SQL only known at run time). `text` has comments and strings blanked."""
    ctes = {match.group(1).lower() for match in CTE.finditer(text)}
    aliases: Dict[str, str] = {}
    refs: List[Dict[str, Any]] = []
    seen = set()

    def add(kind: str, raw: str, position: int) -> None:
        if not usable(raw):
            return
        pieces = parts(raw)
        if len(pieces) == 1 and pieces[0].lower() in ctes:
            return
        if len(pieces) == 1 and pieces[0].lower() in aliases:
            raw = aliases[pieces[0].lower()]
        key = (kind, sql_name(raw, db).lower())
        if key in seen or key[1] == skip.lower():
            return
        seen.add(key)
        refs.append({"kind": kind, "name": " ".join(raw.split()), "db": db, "line": offset_line + line_at(text, position)})

    for match in READS.finditer(text):
        alias = match.group(3)
        if alias and alias.lower() not in NOT_ALIAS:
            aliases[alias.lower()] = match.group(2)
    for match in CALL.finditer(text):
        add("calls", match.group(1), match.start(1))
    for pattern in WRITES:
        for match in pattern.finditer(text):
            add("writes", match.group(1), match.start(1))
    for match in READS.finditer(text):
        if not match.group(1):
            add("reads", match.group(2), match.start(2))
    return refs, bool(DYNAMIC.search(text))


def tsql(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The objects a `.sql` file defines: one per batch (`GO`) that starts with CREATE or ALTER."""
    if JOB.search(text):
        return sqlagent(text, context)
    db = str(context.get("db") or "")
    clean = blank(text)
    found = []
    start = 0
    bounds = [match.start() for match in GO.finditer(clean)] + [len(clean)]
    for end in bounds:
        batch = clean[start:end]
        first_line = line_at(clean, start) - 1
        start = end + 2 if end < len(clean) else end
        match = DEFINITION.search(batch)
        if not match:
            continue
        raw = match.group(2)
        if not usable(raw):
            continue
        kind = DEFINED[match.group(1).upper()]
        name = sql_name(raw, db)
        body = batch[match.end():]
        refs, dynamic = ([], False) if kind == "table" else sql_refs(body, db, first_line + line_at(batch, match.end()) - 1, skip=name)
        if kind == "trigger":
            on = re.match(rf"\s*ON\s+({NAME})", body, re.IGNORECASE)
            if on:
                refs.insert(0, {"kind": "reads", "name": " ".join(on.group(1).split()), "db": db, "line": first_line + line_at(batch, match.end())})
        found.append({"id": f"{kind}:{name}", "type": kind, "name": name, "line": first_line + line_at(batch, match.start(2)), "dynamic": dynamic, "refs": refs})
    return found


def argument(text: str, name: str) -> str:
    match = re.search(ARGUMENT.format(name=name), text, re.IGNORECASE)
    return match.group(1).replace("''", "'") if match else ""


def package_ref(command: str) -> Optional[str]:
    """`/ISSERVER "\\"\\SSISDB\\Folder\\Project\\Load.dtsx\\""` -> `Project/Load`; `/FILE "...\\Load.dtsx"` -> `Load`."""
    match = PACKAGE.search(command)
    if not match:
        return None
    before = re.split(r"[\\/]+", command[:match.start()].replace("\\\"", "").replace("\"", ""))
    folders = [piece for piece in before if piece and not piece.startswith("/")]
    if "SSISDB" in [piece.upper() for piece in folders] and folders:
        return f"{folders[-1]}/{match.group(1)}"
    return match.group(1)


def sqlagent(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A SQL Agent job script (as SSMS scripts it): the job, and what each step runs."""
    jobs: List[Dict[str, Any]] = []
    marks = sorted([(match.start(), "job") for match in JOB.finditer(text)] + [(match.start(), "step") for match in STEP.finditer(text)])
    for number, (position, what) in enumerate(marks):
        end = marks[number + 1][0] if number + 1 < len(marks) else len(text)
        chunk = text[position:end]
        if what == "job":
            name = argument(chunk, "job_name")
            if name:
                jobs.append({"id": f"job:{name}", "type": "job", "name": name, "line": line_at(text, position), "dynamic": False, "refs": [], "scheduled": False})
            continue
        if not jobs:
            continue
        job = jobs[-1]
        subsystem = argument(chunk, "subsystem").upper()
        command = argument(chunk, "command")
        line = line_at(text, position)
        if subsystem == "TSQL":
            refs, dynamic = sql_refs(blank(command), argument(chunk, "database_name"))
            for ref in refs:
                ref["line"] = line
            job["refs"] += refs
            job["dynamic"] = job["dynamic"] or dynamic
        elif subsystem == "SSIS" or ".dtsx" in command.lower():
            package = package_ref(command)
            if package:
                job["refs"].append({"kind": "runs", "name": package, "db": "", "line": line, "as": "package"})
            else:
                job["dynamic"] = True
    for job in jobs:
        job["scheduled"] = bool(SCHEDULE.search(text))
    return jobs


# --- SSIS ---------------------------------------------------------------------------------------------


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attribute(element: ElementTree.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if local(key) == name:
            return value
    return ""


def ssis(text: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A package: one object, with the SQL its tasks run and the tables its data flows read and write."""
    project = context.get("project") or context.get("folder")
    name = f"{project}/{context['stem']}" if project else context["stem"]
    package = {"id": f"package:{name}", "type": "package", "name": name, "line": 1, "dynamic": False, "refs": []}
    try:
        tree = ElementTree.fromstring(re.sub(r"\A\s*<\?xml[^>]*\?>", "", text))
    except (ElementTree.ParseError, ValueError):
        package["dynamic"] = True
        return [package]
    seen = set()

    def add(kind: str, raw: str, as_type: str = "") -> None:
        key = (kind, raw.lower())
        if raw and key not in seen:
            seen.add(key)
            package["refs"].append({"kind": kind, "name": raw, "db": "", "line": 1, **({"as": as_type} if as_type else {})})

    for element in tree.iter():
        tag = local(element.tag)
        source = attribute(element, "SqlStatementSource")
        if source:
            if attribute(element, "SqlStatementSourceType").lower() == "variable":
                package["dynamic"] = True
            else:
                refs, dynamic = sql_refs(blank(source), "")
                for ref in refs:
                    add(ref["kind"], ref["name"])
                package["dynamic"] = package["dynamic"] or dynamic
        if tag == "component":
            kind = "writes" if "destination" in attribute(element, "componentClassID").lower() else "reads"
            for prop in element.iter():
                if local(prop.tag) != "property":
                    continue
                label, value = attribute(prop, "name"), (prop.text or "").strip()
                if label == "OpenRowset" and value:
                    add(kind, value)
                elif label == "SqlCommand" and value:
                    refs, dynamic = sql_refs(blank(value), "")
                    for ref in refs:
                        add(ref["kind"], ref["name"])
                    package["dynamic"] = package["dynamic"] or dynamic
                elif label == "OpenRowsetVariable" and value:
                    package["dynamic"] = True
        if tag == "PackageName" and (element.text or "").strip():
            child = (element.text or "").strip()
            add("runs", child[:-5] if child.lower().endswith(".dtsx") else child, "package")
    return [package]
