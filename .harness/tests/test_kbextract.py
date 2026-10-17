"""Running a toolkit's extractors (core/kbextract.py): decoding a file, loading an extractor, running it safely."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the engine on sys.path)
from core import kbextract


class DecodeTests(unittest.TestCase):
    def test_the_encodings_scripts_come_in(self) -> None:
        self.assertEqual(kbextract.decode("é".encode("utf-8")), "é")
        self.assertEqual(kbextract.decode(b"\xef\xbb\xbf" + "é".encode("utf-8")), "é")  # UTF-8 with a BOM
        self.assertEqual(kbextract.decode(b"\xff\xfe" + "é".encode("utf-16-le")), "é")  # SSMS on Windows
        self.assertEqual(kbextract.decode("é".encode("cp1252")), "é")  # not UTF-8: the Windows code page


class LoadAndRunTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name)

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_missing_file_a_missing_function_and_a_broken_file_say_what_is_wrong(self) -> None:
        with self.assertRaises(kbextract.ToolkitError):
            kbextract.load(self.folder / "nope.py", "extract")
        with self.assertRaisesRegex(kbextract.ToolkitError, "no function"):
            kbextract.load(self.write("a.py", "def other(text, context):\n    return []\n"), "extract")
        with self.assertRaisesRegex(kbextract.ToolkitError, "SyntaxError"):
            kbextract.load(self.write("b.py", "def extract(:\n"), "extract")

    def test_two_toolkits_with_the_same_file_name_do_not_mix(self) -> None:
        first = self.folder / "one"
        second = self.folder / "two"
        first.mkdir()
        second.mkdir()
        (first / "x.py").write_text("def extract(text, context):\n    return [{'id': 'a:1', 'type': 'a'}]\n", encoding="utf-8")
        (second / "x.py").write_text("def extract(text, context):\n    return [{'id': 'b:1', 'type': 'b'}]\n", encoding="utf-8")
        self.assertEqual(kbextract.load(first / "x.py", "extract")("", {})[0]["id"], "a:1")
        self.assertEqual(kbextract.load(second / "x.py", "extract")("", {})[0]["id"], "b:1")

    def test_run_keeps_what_is_well_formed_and_reports_what_failed(self) -> None:
        objects, error = kbextract.run(lambda text, context: [{"id": "sp:x", "type": "sp", "refs": [{"kind": "calls"}, {"kind": "calls", "name": "y"}]}, {"type": "no id"}, "junk"], b"", {})
        self.assertIsNone(error)
        self.assertEqual([(item["id"], item["name"], item["refs"]) for item in objects], [("sp:x", "x", [{"kind": "calls", "name": "y"}])])
        self.assertEqual(kbextract.run(lambda text, context: "not a list", b"", {}), ([], "did not return a list"))


if __name__ == "__main__":
    unittest.main()
