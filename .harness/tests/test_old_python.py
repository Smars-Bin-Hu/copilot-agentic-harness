"""The harness runs on Python 3.9 or later (docs/01). Python 3.12 lets an f-string hold what older versions refuse as a syntax error, so a file written and tested on 3.12 can fail to load at all on a work
computer (1.7.38: `core/company.py` had `'\\u3002'` inside an f-string expression, and the harness did not start). This test reads every Python file the repository ships and refuses those forms:
a backslash, a comment or a line break inside an f-string expression, and a quote of the f-string's own kind reused inside it. On Python before 3.12 the file is parsed by that Python itself."""

from __future__ import annotations

import ast
import io
import sys
import tokenize
import unittest
from pathlib import Path
from typing import List

import support  # noqa: F401 - the engine on sys.path
from support import REPO

SKIP = (".local", ".git", "node_modules", "__pycache__")


def shipped() -> List[Path]:
    files = [path for path in REPO.rglob("*.py") if not any(part in SKIP for part in path.relative_to(REPO).parts)]
    for folder in (REPO / ".harness" / "toolpacks").glob("*/bin"):
        files += [path for path in folder.iterdir() if path.is_file() and path.read_bytes()[:2] == b"#!" and b"python" in path.read_bytes().split(b"\n", 1)[0]]
    return files


def newer_forms(text: str) -> List[str]:
    """What in this text only Python 3.12 or later reads inside an f-string. Needs the 3.12 tokenizer (FSTRING_START...)."""
    found: List[str] = []
    stack: List[str] = []  # the quote of each f-string that is open
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        kind = tokenize.tok_name[token.type]
        if kind == "FSTRING_START":
            quote = token.string.lstrip("rRfFbBuU")
            if stack and quote[0] == stack[-1][0] and len(stack[-1]) == 1:
                found.append(f"line {token.start[0]}: an f-string inside an f-string with the same quote")
            stack.append(quote)
            continue
        if kind == "FSTRING_END":
            stack.pop()
            continue
        if not stack or kind == "FSTRING_MIDDLE":
            continue
        if kind == "STRING":
            if "\\" in token.string:
                found.append(f"line {token.start[0]}: a backslash inside an f-string expression")
            body = token.string.lstrip("rRbBuU")
            if body[:1] == stack[-1][0] and len(stack[-1]) == 1:
                found.append(f"line {token.start[0]}: the f-string's own quote inside its expression")
        elif kind == "COMMENT":
            found.append(f"line {token.start[0]}: a comment inside an f-string expression")
        elif kind in ("NL", "NEWLINE") and len(stack[-1]) == 1:
            found.append(f"line {token.start[0]}: a line break inside an f-string expression")
    return found


class OldPythonTests(unittest.TestCase):
    def test_every_shipped_python_file_loads_on_python_3_9(self) -> None:
        wrong = []
        for path in shipped():
            text = path.read_text(encoding="utf-8")
            if sys.version_info >= (3, 12):
                wrong += [f"{path.relative_to(REPO)} {item}" for item in newer_forms(text)]
            else:
                try:
                    ast.parse(text, str(path))
                except SyntaxError as error:
                    wrong.append(f"{path.relative_to(REPO)} line {error.lineno}: {error.msg}")
        self.assertEqual(wrong, [])

    @unittest.skipIf(sys.version_info < (3, 12), "the tokens of an f-string exist from Python 3.12")
    def test_the_check_finds_the_forms_it_names(self) -> None:
        self.assertTrue(newer_forms("x = f\"{y.rstrip('. \\u3002')}\"\n"))
        self.assertTrue(newer_forms("x = f'{y['a']}'\n"))
        self.assertTrue(newer_forms("x = f'''{y  # c\n}'''\n"))
        self.assertEqual(newer_forms("x = f\"{y['a']} \\n\" + f'{z}'\n"), [])


if __name__ == "__main__":
    unittest.main()
