"""The icon of Start Harness (1.6.83): what each system is asked to do, when it is not asked, and that a failure stops nothing. The same robot in the pages (1.6.85)."""

from __future__ import annotations

import base64
import re
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".harness" / "engine"))

from core import starticon  # noqa: E402
from modules.task import taskhtml  # noqa: E402


class Calls:
    """Stands in for subprocess.run: keeps each call and says what `xattr` printed."""

    def __init__(self, attributes: str = "") -> None:
        self.calls = []
        self.attributes = attributes

    def __call__(self, command, **options):
        self.calls.append((command, options))
        return SimpleNamespace(stdout=self.attributes, returncode=0)

    def names(self):
        return [call[0][0] for call in self.calls]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "my harness"
        (self.root / ".harness" / "bin").mkdir(parents=True)

    def make(self, *names: str) -> None:
        for name in names:
            (self.root / name).write_text("x", encoding="utf-8")


class MacTests(Base):
    def test_a_file_with_no_icon_gets_one(self) -> None:
        self.make(starticon.MAC_START, starticon.MAC_ICON)
        calls = Calls("com.apple.quarantine\n")
        self.assertTrue(starticon.mac(self.root, calls))
        self.assertEqual(calls.names(), ["xattr", "osascript"])
        command = calls.calls[1][0]
        self.assertEqual(command[-2:], [str(self.root / starticon.MAC_ICON), str(self.root / starticon.MAC_START)])

    def test_a_file_with_an_icon_is_left_alone(self) -> None:
        self.make(starticon.MAC_START, starticon.MAC_ICON)
        calls = Calls("com.apple.FinderInfo\ncom.apple.ResourceFork\n")
        self.assertFalse(starticon.mac(self.root, calls))
        self.assertEqual(calls.names(), ["xattr"])

    def test_a_missing_file_asks_nothing(self) -> None:
        self.make(starticon.MAC_START)
        calls = Calls()
        self.assertFalse(starticon.mac(self.root, calls))
        self.assertEqual(calls.calls, [])


class WindowsTests(Base):
    def test_no_shortcut_yet(self) -> None:
        self.make(starticon.WINDOWS_START, starticon.WINDOWS_ICON)
        calls = Calls()
        self.assertTrue(starticon.windows(self.root, calls))
        command, options = calls.calls[0]
        self.assertEqual(command[0], "powershell")
        self.assertEqual(options["env"]["HARNESS_LINK"], str(self.root / starticon.WINDOWS_LINK))
        self.assertEqual(options["env"]["HARNESS_ICON"], str(self.root / starticon.WINDOWS_ICON))
        self.assertNotIn(str(self.root), " ".join(command), "a path on the command line could break it")

    def test_a_good_shortcut_is_left_alone(self) -> None:
        self.make(starticon.WINDOWS_START, starticon.WINDOWS_ICON)
        (self.root / starticon.WINDOWS_LINK).write_bytes(b"L\0\0\0" + str(self.root).encode("utf-16-le") + b"\0\0")
        calls = Calls()
        self.assertFalse(starticon.windows(self.root, calls))
        self.assertEqual(calls.calls, [])

    def test_a_shortcut_of_a_moved_folder_is_made_again(self) -> None:
        self.make(starticon.WINDOWS_START, starticon.WINDOWS_ICON)
        (self.root / starticon.WINDOWS_LINK).write_bytes(b"L\0\0\0" + "C:\\old".encode("utf-16-le"))
        calls = Calls()
        self.assertTrue(starticon.windows(self.root, calls))

    def test_a_missing_file_asks_nothing(self) -> None:
        self.make(starticon.WINDOWS_ICON)
        calls = Calls()
        self.assertFalse(starticon.windows(self.root, calls))
        self.assertEqual(calls.calls, [])


class FailureTests(Base):
    def test_a_failure_stops_nothing(self) -> None:
        for name, system in (("mac", "darwin"), ("windows", "win32")):
            with mock.patch.object(starticon, name, side_effect=OSError("no")), mock.patch.object(starticon.sys, "platform", system):
                starticon.put(self.root)

    def test_another_system_does_nothing(self) -> None:
        with mock.patch.object(starticon, "mac") as mac, mock.patch.object(starticon, "windows") as windows, mock.patch.object(starticon.sys, "platform", "linux"):
            starticon.put(self.root)
        mac.assert_not_called()
        windows.assert_not_called()


class ShippedTests(unittest.TestCase):
    def test_the_windows_icon_holds_the_sizes_a_window_asks_for(self) -> None:
        data = (REPO / starticon.WINDOWS_ICON).read_bytes()
        kind, count = struct.unpack("<xxHH", data[:6])
        self.assertEqual(kind, 1)
        sizes = {data[6 + 16 * n] or 256 for n in range(count)}
        self.assertLessEqual({16, 32, 48, 256}, sizes)

    def test_the_mac_icon_is_an_icon(self) -> None:
        data = (REPO / starticon.MAC_ICON).read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack(">I", data[4:8])[0], len(data))

    def test_the_shortcut_stays_out_of_git(self) -> None:
        self.assertIn(f"/{starticon.WINDOWS_LINK}", (REPO / ".gitignore").read_text(encoding="utf-8").splitlines())


class PageTests(unittest.TestCase):
    def test_every_page_holds_the_icon_in_itself(self) -> None:
        for skeleton in ("board.html", "desk.html", "setup.html", "task.html"):
            page = taskhtml.build(skeleton, [], "title", {})
            found = re.search(r'<link rel="icon" type="image/png" href="data:image/png;base64,([^"]+)">', page)
            self.assertIsNotNone(found, skeleton)
            self.assertEqual(base64.b64decode(found.group(1))[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn(":root{--logo:url(data:image/png;base64,", page)

    def test_a_saved_page_may_show_it(self) -> None:
        self.assertIn("img-src data:", taskhtml.SNAPSHOT_CSP)

    def test_the_header_shows_the_robot(self) -> None:
        ui = (taskhtml.WEB / "ui.css").read_text(encoding="utf-8")
        self.assertIn("background:var(--logo) center/contain no-repeat", ui)
        self.assertNotIn("--mark", ui)

    def test_it_stays_small_because_every_page_carries_it_twice(self) -> None:
        self.assertLess((taskhtml.WEB / "icon.png").stat().st_size, 16 * 1024)


if __name__ == "__main__":
    unittest.main()
