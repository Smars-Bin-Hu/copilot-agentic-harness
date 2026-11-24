"""`core/ghauth.py` (1.8.x): finding gh, its sign-in state, its token, and the web sign-in run with no terminal, with a fake gh."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import support  # noqa: F401 - HARNESS_GH=off: no test touches the real gh

from core import ghauth

TOKEN = "gho_" + "Q" * 36

FAKE = textwrap.dedent('''
    import json, os, sys, time
    args = sys.argv[1:]
    mode = os.environ.get("FAKE_GH", "signed-in")
    if args[:1] == ["--version"]:
        if mode == "broken":
            sys.exit(2)
        print("gh version 2.105.0 (2026-11-01)")
    elif args[:2] == ["auth", "status"]:
        if "--json" in args and mode == "old":
            print("unknown flag: --json", file=sys.stderr); sys.exit(1)
        if mode == "old":
            print("github.com\\n  Logged in to github.com account alex (keyring)"); sys.exit(0)
        if mode == "signed-out":
            print(json.dumps({"hosts": {}})); sys.exit(1)
        print(json.dumps({"hosts": {"github.com": [{"state": "success", "active": True, "host": "github.com", "login": "alex", "tokenSource": "keyring"}]}}))
    elif args[:2] == ["auth", "token"]:
        if mode == "signed-out":
            print("no oauth token found for github.com", file=sys.stderr); sys.exit(1)
        print("%s")
    elif args[:2] == ["auth", "logout"]:
        with open(os.environ["FAKE_ARGS"], "w") as out:
            out.write(" ".join(args))
        if mode == "logout-fails":
            print("cannot remove a token from GH_TOKEN", file=sys.stderr); sys.exit(1)
    elif args[:2] == ["auth", "login"]:
        with open(os.environ["FAKE_ARGS"], "w") as out:
            out.write(" ".join(args))
        print("")
        print("! One-time code (5F59-4EB2) copied to clipboard", flush=True)
        print("Open this URL to continue in your web browser: https://github.com/login/device", flush=True)
        if mode == "login-fails":
            print("error: token %s was refused", flush=True); sys.exit(1)
        while not os.path.exists(os.environ["FAKE_GO"]):
            time.sleep(0.05)
        print("Logged in as alex", flush=True)
''' % (TOKEN, TOKEN))


@unittest.skipIf(os.name == "nt", "the fake gh is a script with a #! line")
class FakeGhTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ghauth-"))
        self.gh = self.tmp / "gh"
        self.gh.write_text("#!" + sys.executable + "\n" + FAKE, encoding="utf-8")
        self.gh.chmod(self.gh.stat().st_mode | stat.S_IEXEC)
        self.go = self.tmp / "go"
        self.args = self.tmp / "args"
        self.extra = {"FAKE_GH": "signed-in", "FAKE_GO": str(self.go), "FAKE_ARGS": str(self.args)}
        self.logins = []

    def tearDown(self) -> None:
        for login in self.logins:
            login.cancel()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def mode(self, name: str) -> dict:
        return dict(self.extra, FAKE_GH=name)

    def test_version_status_token(self) -> None:
        self.assertEqual(ghauth.version(str(self.gh), self.extra), "2.105.0")
        self.assertEqual(ghauth.status(str(self.gh), self.extra), {"signed_in": True, "login": "alex", "why": ""})
        self.assertEqual(ghauth.token(str(self.gh), self.extra), TOKEN)

    def test_signed_out(self) -> None:
        self.assertFalse(ghauth.status(str(self.gh), self.mode("signed-out"))["signed_in"])
        with self.assertRaises(ghauth.GhError) as caught:
            ghauth.token(str(self.gh), self.mode("signed-out"))
        self.assertEqual(caught.exception.why, "not-signed-in")

    def test_an_older_gh_without_json(self) -> None:
        self.assertEqual(ghauth.status(str(self.gh), self.mode("old")), {"signed_in": True, "login": "alex", "why": ""})

    def test_a_gh_that_does_not_run(self) -> None:
        with self.assertRaises(ghauth.GhError) as caught:
            ghauth.version(str(self.gh), self.mode("broken"))
        self.assertEqual(caught.exception.why, "cannot-run")
        with self.assertRaises(ghauth.GhError) as caught:
            ghauth.version(str(self.tmp / "missing"))
        self.assertEqual(caught.exception.why, "cannot-run")

    def test_check_never_holds_the_token(self) -> None:
        found = ghauth.check(extra=self.extra, find=lambda folders: str(self.gh))
        self.assertEqual((found["signed_in"], found["login"], found["version"], found["why"]), (True, "alex", "2.105.0", ""))
        self.assertNotIn(TOKEN, json.dumps(found))
        self.assertEqual(ghauth.check(extra=self.mode("signed-out"), find=lambda folders: str(self.gh))["why"], "not-signed-in")

    def test_check_without_gh_links_the_download_page(self) -> None:
        found = ghauth.check(find=lambda folders: None)
        self.assertEqual(found["why"], "no-gh")
        self.assertEqual(found["download"], ghauth.DOWNLOAD_PAGE)

    def test_logout_names_the_account_and_asks_nothing(self) -> None:
        self.assertEqual(ghauth.logout(str(self.gh), self.extra), {"done": True, "login": "alex"})
        self.assertEqual(self.args.read_text(), "auth logout --hostname github.com --user alex")

    def test_logout_when_not_signed_in_or_refused(self) -> None:
        with self.assertRaises(ghauth.GhError) as caught:
            ghauth.logout(str(self.gh), self.mode("signed-out"))
        self.assertEqual(caught.exception.why, "not-signed-in")
        self.assertFalse(self.args.exists())
        with self.assertRaises(ghauth.GhError) as caught:
            ghauth.logout(str(self.gh), self.mode("logout-fails"))
        self.assertIn("GH_TOKEN", str(caught.exception))

    def wait(self, login: ghauth.Login, state: str, limit: float = 10.0) -> dict:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            found = login.status()
            if found["state"] == state:
                return found
            time.sleep(0.05)
        self.fail(f"login stayed {login.status()['state']}, wanted {state}")

    def test_login_shows_the_code_then_ends_done(self) -> None:
        login = ghauth.Login(str(self.gh), self.extra).start()
        self.logins.append(login)
        found = self.wait(login, "waiting")
        self.assertEqual((found["code"], found["url"]), ("5F59-4EB2", "https://github.com/login/device"))
        self.assertGreater(found["left"], 0)
        self.go.write_text("go", encoding="utf-8")
        self.wait(login, "done")
        arguments = self.args.read_text(encoding="utf-8")
        self.assertIn("--web", arguments)
        self.assertIn("--hostname github.com", arguments)

    def test_login_cancel(self) -> None:
        login = ghauth.Login(str(self.gh), self.extra).start()
        self.logins.append(login)
        self.wait(login, "waiting")
        login.cancel()
        self.assertEqual(login.status()["state"], "cancelled")
        time.sleep(0.3)
        self.assertEqual(login.status()["state"], "cancelled")  # the end of gh after the cancel does not turn it into `failed`

    def test_login_code_runs_out(self) -> None:
        login = ghauth.Login(str(self.gh), self.extra, life=0.5).start()
        self.logins.append(login)
        self.wait(login, "expired")

    def test_login_that_fails_says_why_without_a_token(self) -> None:
        login = ghauth.Login(str(self.gh), self.mode("login-fails")).start()
        self.logins.append(login)
        found = self.wait(login, "failed")
        self.assertIn("exit 1", found["why"])
        self.assertNotIn(TOKEN, json.dumps(found))
        self.assertNotIn(TOKEN, "\n".join(login.lines))

    def test_login_with_a_gh_that_cannot_start(self) -> None:
        login = ghauth.Login(str(self.tmp / "missing")).start()
        self.assertEqual(login.status()["state"], "failed")


class FindTest(unittest.TestCase):
    def test_order(self) -> None:
        there = {"/set/gh", "/tools/gh", "/opt/homebrew/bin/gh"}
        exists = there.__contains__
        self.assertEqual(ghauth.find_gh(["/tools"], {"HARNESS_GH": "/set/gh"}, "darwin", exists, lambda name: "/path/gh"), "/set/gh")
        self.assertEqual(ghauth.find_gh(["/tools"], {"HARNESS_GH": "/set"}, "darwin", exists, lambda name: "/path/gh"), "/set/gh")
        self.assertEqual(ghauth.find_gh(["/tools"], {}, "darwin", exists, lambda name: "/path/gh"), "/tools/gh")
        self.assertEqual(ghauth.find_gh([], {}, "darwin", exists, lambda name: "/path/gh"), "/path/gh")
        self.assertEqual(ghauth.find_gh([], {}, "darwin", exists, lambda name: None), "/opt/homebrew/bin/gh")
        self.assertIsNone(ghauth.find_gh([], {}, "linux", lambda place: False, lambda name: None))

    def test_off(self) -> None:
        self.assertIsNone(ghauth.find_gh(["/tools"], {"HARNESS_GH": "off"}, "darwin", lambda place: True, lambda name: "/path/gh"))

    def test_windows_places(self) -> None:
        places = ghauth.standard_places({"ProgramFiles": "C:\\Program Files", "LOCALAPPDATA": "C:\\Users\\a\\AppData\\Local"}, "win32")
        self.assertEqual(places[0], "C:\\Program Files\\GitHub CLI\\gh.exe")
        self.assertEqual(ghauth.program_name("win32"), "gh.exe")


class ReadTest(unittest.TestCase):
    def test_read_status(self) -> None:
        self.assertEqual(ghauth.read_status("not json")["why"], "unreadable")
        self.assertEqual(ghauth.read_status(json.dumps({"hosts": {}}))["why"], "not-signed-in")
        failed = {"hosts": {"github.com": [{"state": "error", "active": True, "login": "alex"}]}}
        self.assertEqual(ghauth.read_status(json.dumps(failed)), {"signed_in": False, "login": "alex", "why": "error"})

    def test_scrub(self) -> None:
        self.assertEqual(ghauth.scrub("x " + TOKEN + " y github_pat_" + "a" * 30), "x *** y ***")


if __name__ == "__main__":
    unittest.main()
