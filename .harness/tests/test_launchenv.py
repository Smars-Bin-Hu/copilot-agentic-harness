"""This computer (1.7.11): the tool folders and the CA bundle VS Code is started with. No test reaches the network: the chain and the check are given."""

from __future__ import annotations

import base64
import os
import stat
import sys
from pathlib import Path
from typing import List, Tuple
from unittest import mock

from support import HarnessTestCase

from core import launchenv, connections


def cert(n: int) -> str:
    """A PEM block with a body made of `n` (not a real certificate: the bundle code only reads and dedupes the blocks)."""
    return launchenv.der_to_pem(bytes([n]) * 300)


class LaunchEnvCase(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tools = self.root / "tools" / "az" / "bin"
        self.tools.mkdir(parents=True)
        program = self.tools / ("az.cmd" if os.name == "nt" else "az")
        program.write_text("echo az\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
        certifi = self.root / "tools" / "az" / "Lib" / "site-packages" / "certifi"
        certifi.mkdir(parents=True)
        (certifi / "cacert.pem").write_text(cert(1) + cert(2), encoding="ascii")

    def chain(self, blocks: List[str], trust: str = "None"):
        def given(host: str, proxy: str) -> Tuple[List[str], str]:
            self.asked = (host, proxy)
            return blocks, trust
        return given


class ToolFolders(LaunchEnvCase):
    def test_a_folder_with_a_program_is_kept_and_goes_before_path(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools), "  ", str(self.tools)])
        self.assertEqual(launchenv.settings(self.root)["paths"], [str(self.tools)])
        found = launchenv.extra(self.root, {"PATH": os.pathsep.join(["/usr/bin", str(self.tools)])})
        self.assertEqual(found["PATH"].split(os.pathsep), [str(self.tools), "/usr/bin"], "first, and not twice")

    def test_a_wrong_folder_is_refused_and_nothing_is_kept(self) -> None:
        for bad in ("relative/bin", str(self.root / "nowhere"), str(self.root / "tools")):
            with self.assertRaises(ValueError, msg=bad):
                launchenv.save_paths(self.root, [bad])
        self.assertEqual(launchenv.settings(self.root)["paths"], [])

    def test_a_folder_gone_since_is_left_out_and_an_empty_list_clears(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools)])
        connections.write_env(self.root, {launchenv.PATH_KEY: os.pathsep.join([str(self.tools), str(self.root / "gone")])})
        self.assertEqual(launchenv.extra(self.root, {"PATH": "/usr/bin"})["PATH"].split(os.pathsep), [str(self.tools), "/usr/bin"])
        launchenv.save_paths(self.root, [])
        self.assertEqual(launchenv.extra(self.root, {"PATH": "/usr/bin"}), {})

    def test_the_identities_in_the_same_file_stay(self) -> None:
        connections.write_env(self.root, {"HARNESS_SERVER_DB_ACCOUNT": "me"})
        launchenv.save_paths(self.root, [str(self.tools)])
        self.assertEqual(connections.read_env(self.root)["HARNESS_SERVER_DB_ACCOUNT"], "me")


class Programs(LaunchEnvCase):
    """1.7.37: no more tool folders as a concept: a program that is not found gets "I installed it here"."""

    def test_the_folder_must_hold_the_program_that_asked_for_it(self) -> None:
        for bad, program in ((str(self.root / "nowhere"), "az"), (str(self.root / "tools"), "az"), (str(self.tools), "other"), ("relative", "az")):
            with self.assertRaises(ValueError, msg=bad):
                launchenv.add_folder(self.root, program, bad)
        self.assertEqual(launchenv.settings(self.root)["paths"], [])
        launchenv.add_folder(self.root, "az", ' "' + str(self.tools) + '" ')
        launchenv.add_folder(self.root, "az", str(self.tools))
        self.assertEqual(launchenv.settings(self.root)["paths"], [str(self.tools)], "once")

    def test_the_rows_say_who_needs_each_program_and_carry_the_companys_hint_for_a_missing_one(self) -> None:
        import json
        import tempfile
        from test_toolpacks import make

        recipe = {"tool_folders": [{"label": "Azure CLI", "hint": "C:\\tools\\az\\bin", "program": "tracker-nowhere"}, {"label": "Old", "hint": "an old entry without a program"}]}
        (self.root / launchenv.RECIPE).write_text(json.dumps(recipe), encoding="utf-8")
        with tempfile.TemporaryDirectory() as outside:
            from core import toolpacks

            toolpacks.add(self.root, str(make(Path(outside) / "tracker", needs={"programs": ["tracker-nowhere"], "trust": []})))
            shown = launchenv.state(self.root)
        rows = {row["program"]: row for row in shown["programs"]}
        self.assertEqual(list(rows)[0], "python")
        self.assertTrue(rows["python"]["found"])
        self.assertEqual((rows["tracker-nowhere"]["found"], rows["tracker-nowhere"]["hint"], rows["tracker-nowhere"]["needed_by"][0]["pack"]), (False, "C:\\tools\\az\\bin", "tracker"))
        self.assertEqual([item["label"] for item in shown["recipe"]["tool_folders"]], ["Azure CLI", "Old"], "an entry without a program still works")
        self.assertEqual(shown["recipe"]["tool_folders"][1].get("program"), None)

    def test_a_program_on_the_path_shows_no_hint_and_a_bad_program_name_in_the_recipe_is_named(self) -> None:
        self.assertTrue(any("program" in line for line in launchenv.recipe_errors({"tool_folders": [{"label": "x", "program": "a b!"}]})))
        self.assertEqual(launchenv.recipe_errors({"tool_folders": [{"label": "x", "program": "az"}]}), [])


class Bundle(LaunchEnvCase):
    def test_the_bundle_is_the_tools_roots_and_the_chain_but_the_site_once_each(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools)])
        made = launchenv.make(self.root, "dev.example.org", "http://127.0.0.1:9000/", get_chain=self.chain([cert(9), cert(5), cert(2)]), verify=lambda *_: (True, ""))
        self.assertEqual(self.asked, ("dev.example.org", "127.0.0.1:9000"))
        self.assertTrue(made["ok"])
        self.assertIn("certifi", made["roots"])
        text = (self.root / launchenv.BUNDLE).read_text(encoding="ascii")
        self.assertEqual(launchenv.pem_blocks(text), [cert(1), cert(2), cert(5)], "the site's own (the first of the chain) left out; the root the tool has already, once")
        self.assertEqual(launchenv.extra(self.root, {"PATH": ""})["REQUESTS_CA_BUNDLE"], str(self.root / launchenv.BUNDLE))
        kept = launchenv.state(self.root)["bundle"]
        self.assertEqual((kept["n"], kept["host"], kept["proxy"]), (3, "dev.example.org", "127.0.0.1:9000"))

    def test_a_bundle_whose_check_fails_is_not_kept_and_the_old_one_stays(self) -> None:
        launchenv.make(self.root, "a.example.org", "", get_chain=self.chain([cert(9), cert(5)]), verify=lambda *_: (True, ""))
        before = (self.root / launchenv.BUNDLE).read_text(encoding="ascii")
        made = launchenv.make(self.root, "a.example.org", "", get_chain=self.chain([cert(9)]), verify=lambda *_: (False, "unable to get local issuer certificate"), own_roots=lambda: [])
        self.assertFalse(made["ok"])
        self.assertIn("issuer", made["why"])
        self.assertEqual((self.root / launchenv.BUNDLE).read_text(encoding="ascii"), before)
        self.assertFalse((self.root / launchenv.BUNDLE).with_suffix(".tmp").exists())

    def test_the_systems_own_roots_are_added_only_when_the_chain_alone_fails(self) -> None:
        tried = []

        def verify(path: Path, host: str, proxy: str):
            blocks = launchenv.pem_blocks(path.read_text(encoding="ascii"))
            tried.append(len(blocks))
            return cert(8) in blocks, "" if cert(8) in blocks else "unable to get local issuer certificate"
        launchenv.save_paths(self.root, [str(self.tools)])  # the tool's roots: 1 and 2
        made = launchenv.make(self.root, "c.example.org", "", get_chain=self.chain([cert(9)]), verify=verify, own_roots=lambda: [cert(8), cert(1)])
        self.assertEqual((made["ok"], made["system"], len(tried), tried[1] - tried[0]), (True, 1, 2, 1), "8 added, 1 not twice")
        asked = []
        launchenv.make(self.root, "c.example.org", "", get_chain=self.chain([cert(9), cert(8)]), verify=verify, own_roots=lambda: asked.append(1) or [])
        self.assertEqual(asked, [], "not read when the chain is enough")
        self.assertEqual(launchenv.system_roots("win32"), [])

    def test_the_check_is_made_with_the_new_file_through_the_same_proxy(self) -> None:
        seen = {}

        def verify(path: Path, host: str, proxy: str):
            seen.update(blocks=launchenv.pem_blocks(path.read_text(encoding="ascii")), host=host, proxy=proxy)
            return True, ""
        launchenv.make(self.root, "b.example.org", "10.0.0.1:8080", get_chain=self.chain([cert(9), cert(7)]), verify=verify)
        self.assertIn(cert(7), seen["blocks"])
        self.assertEqual((seen["host"], seen["proxy"]), ("b.example.org", "10.0.0.1:8080"))

    def test_remove_drops_the_file_and_the_variables(self) -> None:
        launchenv.make(self.root, "", "", get_chain=self.chain([cert(9), cert(7)]), verify=lambda *_: (True, ""))
        self.assertEqual(launchenv.settings(self.root)["host"], launchenv.DEFAULT_HOST)
        launchenv.drop_bundle(self.root)
        self.assertFalse((self.root / launchenv.BUNDLE).exists())
        self.assertNotIn("REQUESTS_CA_BUNDLE", launchenv.extra(self.root, {"PATH": ""}))

    def test_a_host_that_is_not_an_address_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            launchenv.make(self.root, "a b; rm", "", get_chain=self.chain([cert(9)]), verify=lambda *_: (True, ""))

    def test_a_host_may_carry_its_port_and_the_chain_is_asked_for_that_port(self) -> None:
        """1.7.38: the recipe's `host` can be `host:port`; Make used to reach port 443 only."""
        self.assertEqual(launchenv.split_host("dev.example.org"), ("dev.example.org", 443))
        self.assertEqual(launchenv.split_host(" dev.example.org:18443 "), ("dev.example.org", 18443))
        for bad in ("a:0", "a:70000", "a:b", "a:1:2", ":8", "a b:9", ""):
            with self.assertRaises(ValueError, msg=bad):
                launchenv.split_host(bad)
        made = launchenv.make(self.root, "localhost:18443", "", get_chain=self.chain([cert(9), cert(5)]), verify=lambda *_: (True, ""))
        self.assertEqual((self.asked, made["host"], launchenv.settings(self.root)["host"]), (("localhost:18443", ""), "localhost:18443", "localhost:18443"))
        with self.assertRaises(ValueError):
            launchenv.make(self.root, "localhost:99999", "", get_chain=self.chain([cert(9)]), verify=lambda *_: (True, ""))
        argv: list = []

        class Done:
            stdout, stderr = "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(bytes([4]) * 60).decode("ascii") + "\n-----END CERTIFICATE-----\nVerify return code: 0 (ok)\n", ""

        def run(command: list, **_kw: object) -> Done:
            argv.extend(command)
            return Done()
        with mock.patch.object(launchenv.shutil, "which", return_value="/usr/bin/openssl"):
            launchenv.chain_openssl("localhost:18443", "", run)
        self.assertEqual((argv[argv.index("-servername") + 1], argv[argv.index("-connect") + 1]), ("localhost", "localhost:18443"))
        script: list = []
        with self.assertRaises(ValueError):  # the made-up answer holds no TRUST line; the script it was given is what is looked at
            launchenv.chain_windows("localhost:18443", "127.0.0.1:9000", lambda command, **_kw: script.append(command[-1]) or Done())
        self.assertIn("$h = 'localhost'; $port = 18443;", script[0])
        self.assertNotIn("__PORT__", script[0])
        self.assertEqual(launchenv.recipe_errors({"ca_bundle": {"host": "localhost:18443", "proxy": "127.0.0.1:9000"}}), [])
        self.assertTrue(launchenv.recipe_errors({"ca_bundle": {"host": "localhost:abc"}}))

    def test_no_chain_because_nothing_answered_names_the_proxy_not_an_errno(self) -> None:
        class Down:
            stdout, stderr = "", "connect:errno=61\n"

        with mock.patch.object(launchenv.shutil, "which", return_value="/usr/bin/openssl"):
            with self.assertRaises(ValueError) as proxy:
                launchenv.chain_openssl("h.example.org", "127.0.0.1:9009", lambda *a, **k: Down())
            with self.assertRaises(ValueError) as host:
                launchenv.chain_openssl("h.example.org", "", lambda *a, **k: Down())
        self.assertIn("127.0.0.1:9009", str(proxy.exception))
        self.assertNotIn("errno", str(proxy.exception))
        self.assertIn("h.example.org", str(host.exception))
        self.assertNotIn("9009", str(host.exception))

        class Odd:
            stdout, stderr = "", "something else broke\n"

        with mock.patch.object(launchenv.shutil, "which", return_value="/usr/bin/openssl"):
            with self.assertRaises(ValueError) as other:
                launchenv.chain_openssl("h.example.org", "", lambda *a, **k: Odd())
        self.assertIn("something else broke", str(other.exception), "a failure that is not a missing answer keeps its words")

    def test_proxy_addresses_and_pem_reading(self) -> None:
        self.assertEqual(launchenv.proxy_address("http://user@127.0.0.1:9000/"), "127.0.0.1:9000")
        self.assertEqual(launchenv.proxy_address("nonsense"), "")
        self.assertEqual(launchenv.detect_proxy({"https_proxy": "http://p.example.org:3128"}), "p.example.org:3128")
        self.assertEqual(launchenv.detect_proxy({}), "")
        windows = cert(3).replace("\n", "\r\n")  # PowerShell's base64 breaks lines at 76 with CRLF
        self.assertEqual(launchenv.pem_blocks("noise\r\n" + windows), [cert(3)])
        self.assertEqual(launchenv.merge([cert(1), cert(2)], [cert(2), cert(3)]), [cert(1), cert(2), cert(3)])

    def test_the_windows_chain_is_read_from_powershell_output(self) -> None:
        body = base64.b64encode(bytes([4]) * 300).decode("ascii")
        out = "TRUST None\r\n-----BEGIN CERTIFICATE-----\r\n" + body + "\r\n-----END CERTIFICATE-----\r\n"

        class Done:
            stdout, stderr = out, ""
        seen = []
        blocks, trust = launchenv.chain_windows("h.example.org", "127.0.0.1:9000", run=lambda argv, **k: seen.append(argv) or Done())
        self.assertEqual((blocks, trust), ([cert(4)], "None"))
        script = seen[0][-1]
        self.assertIn("$h = 'h.example.org'; $port = 443; $p = '127.0.0.1:9000'", script, "the values are in the script itself: -Command passes it no $args")
        self.assertEqual(seen[0][-2], "-Command")

        class Empty:
            stdout, stderr = "TRUST \r\n", "Exception calling AuthenticateAsClient"
        with self.assertRaises(ValueError):  # no chain is a failure with its reason, not "the system trusts it"
            launchenv.chain_windows("h.example.org", "", run=lambda *a, **k: Empty())

        class Refused:
            stdout, stderr = "PROXY HTTP/1.1 403 Forbidden\r\n", ""
        with self.assertRaises(ValueError):
            launchenv.chain_windows("h.example.org", "127.0.0.1:9000", run=lambda *a, **k: Refused())


class WhatVsCodeGot(LaunchEnvCase):
    """1.7.21 (T3#1): a VS Code that was already running is not given the settings; the hook sees what it really got, and the board does not say green."""

    def setUp(self) -> None:
        super().setUp()
        launchenv.save_paths(self.root, [str(self.tools)])
        bundle = self.root / launchenv.BUNDLE
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text(cert(1), encoding="ascii")
        connections.write_env(self.root, {launchenv.BUNDLE_KEY: launchenv.BUNDLE.as_posix()})

    def test_lacking_names_a_tool_folder_and_a_trust_variable_that_are_not_there(self) -> None:
        bundle = str(self.root / launchenv.BUNDLE)
        right = {"PATH": os.pathsep.join([str(self.tools), "/usr/bin"]), "REQUESTS_CA_BUNDLE": bundle}
        self.assertEqual(launchenv.lacking(self.root, right), [])
        self.assertEqual(launchenv.lacking(self.root, {"PATH": "/usr/bin", "REQUESTS_CA_BUNDLE": bundle}), [f"PATH {self.tools}"])
        self.assertEqual(launchenv.lacking(self.root, {**right, "REQUESTS_CA_BUNDLE": "/other.pem"}), ["REQUESTS_CA_BUNDLE"])
        self.assertEqual(launchenv.lacking(self.root, {"PATH": "/usr/bin"}), [f"PATH {self.tools}", "REQUESTS_CA_BUNDLE"])

    def test_nothing_to_give_nothing_lacking(self) -> None:
        other = self.root / "elsewhere"
        other.mkdir()
        from core import launchenv as again

        connections.write_env(self.root, {launchenv.BUNDLE_KEY: None, launchenv.PATH_KEY: None})
        self.assertEqual(again.lacking(other, {"PATH": "/usr/bin"}), [])

    def test_the_hook_keeps_what_it_found_and_the_view_goes_red_with_the_sentence(self) -> None:
        from core import reach

        systems = {"tk": {"reach": {"cli": "tk"}, "env": "none", "needs": {"probes": {"none": "tk me"}}}}
        reach._write(self.root, {"tk:none": {"state": "ok", "at": "2026-01-01T00:00:00+00:00", "why": "", "who": "me", "source": "probe"}})  # noqa: SLF001
        self.assertEqual(reach.view(self.root, systems)[0]["state"], "ok")
        found = launchenv.note_seen(self.root, {"PATH": "/usr/bin"})
        self.assertEqual((found["ok"], len(found["missing"])), (False, 2))
        line = reach.view(self.root, systems)[0]
        self.assertEqual((line["state"], line["why"]), ("denied", "vscode-env"))
        self.assertIn("完全退出 VS Code", line["launch"])
        launchenv.note_seen(self.root, {"PATH": str(self.tools), "REQUESTS_CA_BUNDLE": str(self.root / launchenv.BUNDLE)})
        self.assertEqual(reach.view(self.root, systems)[0]["state"], "ok", "a VS Code started right: the board's own word stands")
        launchenv.note_seen(self.root, {"PATH": "/usr/bin"})
        launchenv.mark_started(self.root)  # the board started VS Code with the settings
        self.assertEqual(reach.view(self.root, systems)[0]["state"], "ok")

    def test_running_is_asked_of_the_system(self) -> None:
        class Done:
            def __init__(self, code: int, out: str = "") -> None:
                self.returncode, self.stdout = code, out
        self.assertTrue(launchenv.vscode_running(run=lambda *a, **k: Done(0), platform="darwin"))
        self.assertFalse(launchenv.vscode_running(run=lambda *a, **k: Done(1), platform="darwin"))
        self.assertTrue(launchenv.vscode_running(run=lambda *a, **k: Done(0, "Code.exe  1234 Console"), platform="win32"))
        self.assertFalse(launchenv.vscode_running(run=lambda *a, **k: Done(0, "INFO: No tasks are running"), platform="win32"))
        def broken(*a, **k):
            raise OSError("no pgrep")
        self.assertFalse(launchenv.vscode_running(run=broken, platform="darwin"))

    def test_on_windows_only_a_code_exe_with_a_window_is_an_open_vs_code(self) -> None:
        """1.7.41: the `code` command and helpers left behind run as Code.exe with no window; tasklist counted them, and the board said "VS Code did not quit" while none was open."""
        class Done:
            returncode, stdout = 0, "Code.exe  1234 Console"
        asked = []
        def tasklist(*a, **k):
            asked.append(a)
            return Done()
        self.assertFalse(launchenv.vscode_running(run=tasklist, platform="win32", windows=lambda: False), "Code.exe processes, no window: not open")
        self.assertTrue(launchenv.vscode_running(run=tasklist, platform="win32", windows=lambda: True))
        self.assertEqual(asked, [], "no process is started when the windows can be read")
        self.assertTrue(launchenv.vscode_running(run=tasklist, platform="win32", windows=lambda: None), "windows not readable: tasklist, as before")
        self.assertIsNone(launchenv.code_windows() if sys.platform != "win32" else None, "away from Windows it cannot be told")


PS_LINE = ("/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper.app/Contents/MacOS/Code Helper --type=utility --utility-sub-type=node.mojom.NodeService --lang=en-US "
           "TERM_PROGRAM=vscode PATH=/Users/me/tools/az/bin:/usr/bin:/Applications/Visual Studio Code.app/Contents/Resources/app/bin REQUESTS_CA_BUNDLE=/Users/me/Dev Folder/copy/.harness/certs/ca-bundle.pem HOME=/Users/me")


class SettingsCarriedByVSCode(LaunchEnvCase):
    """1.7.38, Q2: the board tells before any chat whether the VS Code that runs was started with this copy's settings."""

    def settings_on(self) -> None:
        launchenv.save_paths(self.root, [str(self.tools)])

    def test_the_environment_in_a_ps_line_is_read_with_spaces_in_a_value_and_no_argument_taken_for_a_name(self) -> None:
        found = launchenv.parse_ps_environ(PS_LINE)
        self.assertEqual(found["PATH"], "/Users/me/tools/az/bin:/usr/bin:/Applications/Visual Studio Code.app/Contents/Resources/app/bin")
        self.assertEqual(found["REQUESTS_CA_BUNDLE"], "/Users/me/Dev Folder/copy/.harness/certs/ca-bundle.pem")
        self.assertEqual(found["TERM_PROGRAM"], "vscode")
        self.assertNotIn("--type", found)
        self.assertNotIn("type", found)
        self.assertEqual(launchenv.parse_ps_environ(""), {})

    def test_an_environment_is_read_by_ps_on_macos_by_proc_on_linux_and_never_on_windows(self) -> None:
        done = mock.Mock(returncode=0, stdout=PS_LINE)
        run = mock.Mock(return_value=done)
        self.assertEqual(launchenv.host_environ(4711, "darwin", run)["TERM_PROGRAM"], "vscode")
        self.assertEqual(run.call_args[0][0], ["ps", "eww", "-o", "command=", "-p", "4711"])
        self.assertEqual(launchenv.host_environ(4711, "linux", read=lambda path: b"A=1\0PATH=/a:/b\0")["PATH"], "/a:/b")
        self.assertIsNone(launchenv.host_environ(4711, "win32", run), "another process's memory is not read")
        self.assertIsNone(launchenv.host_environ("x", "darwin", run))
        self.assertIsNone(launchenv.host_environ(4711, "darwin", mock.Mock(return_value=mock.Mock(returncode=1, stdout=""))))
        self.assertIsNone(launchenv.host_environ(4711, "linux", read=mock.Mock(side_effect=PermissionError)))

    def test_how_long_a_process_ran_is_read_from_ps_elapsed_time(self) -> None:
        self.assertEqual(launchenv._elapsed_seconds("08:47"), 527.0)  # noqa: SLF001
        self.assertEqual(launchenv._elapsed_seconds("1:02:03"), 3723.0)  # noqa: SLF001
        self.assertEqual(launchenv._elapsed_seconds("2-00:00:10"), 172810.0)  # noqa: SLF001
        self.assertIsNone(launchenv._elapsed_seconds("nonsense"))  # noqa: SLF001
        run = mock.Mock(return_value=mock.Mock(returncode=0, stdout="  01:40\n"))
        self.assertEqual(launchenv.process_started(4711, "darwin", run, now=lambda: 1000.0), 900.0)

    def test_a_copy_with_no_settings_accepts_any_vscode(self) -> None:
        self.assertEqual(launchenv.needs(self.root), {"folders": [], "bundle": ""})
        found = launchenv.carried(self.root, 4711, environ=lambda _pid: {"PATH": "/usr/bin"})
        self.assertEqual((found["state"], found["missing"]), (launchenv.FREE, []))

    def test_the_environment_of_the_agent_host_is_judged_by_the_words_of_the_hook(self) -> None:
        self.settings_on()
        lost = launchenv.carried(self.root, 4711, environ=lambda _pid: {"PATH": "/usr/bin"})
        self.assertEqual((lost["state"], lost["by"], lost["missing"]), (launchenv.MISSING, "env", [f"PATH {self.tools}"]))
        good = launchenv.carried(self.root, 4711, environ=lambda _pid: {"PATH": os.pathsep.join([str(self.tools), "/usr/bin"])})
        self.assertEqual((good["state"], good["by"]), (launchenv.CARRIED, "env"))
        self.assertEqual(launchenv.carried(self.root, None)["state"], launchenv.UNSEEN)  # no VS Code known: nothing is judged

    def test_where_the_environment_cannot_be_read_the_start_of_the_board_and_the_birth_of_the_process_decide(self) -> None:
        """Windows: a VS Code created after the board started it has the settings; one created before it does not; a VS Code the board did not start proves nothing."""
        self.settings_on()
        none = lambda _pid: None  # noqa: E731
        born = lambda at: (lambda _pid: at)  # noqa: E731
        self.assertEqual(launchenv.carried(self.root, 4711, none, born(1000.0))["state"], launchenv.UNSEEN, "never started by the board, no chat yet")
        launchenv.mark_started(self.root)
        mark = launchenv._stamp(launchenv.seen(self.root)["at"])  # noqa: SLF001
        after = launchenv.carried(self.root, 4711, none, born(mark + 5))
        self.assertEqual((after["state"], after["by"]), (launchenv.CARRIED, "board"))
        within = launchenv.carried(self.root, 4711, none, born(mark - 1))  # created a moment before the mark: the board marks just before it asks VS Code to open
        self.assertEqual(within["state"], launchenv.CARRIED)
        before = launchenv.carried(self.root, 4711, none, born(mark - 3600))  # an older VS Code: the board's start did not make it
        self.assertEqual((before["state"], before["by"]), (launchenv.MISSING, "board"))
        self.assertEqual(launchenv.carried(self.root, 4711, none, none)["state"], launchenv.UNSEEN, "when it cannot be known when the process was created")

    def test_a_chat_of_this_vscode_is_believed_and_one_of_an_older_vscode_is_not(self) -> None:
        self.settings_on()
        none = lambda _pid: None  # noqa: E731
        found = launchenv.note_seen(self.root, {"PATH": "/usr/bin"})  # a hook: the chat's environment lacks the tool folder
        at = launchenv._stamp(found["at"])  # noqa: SLF001
        said = launchenv.carried(self.root, 4711, none, lambda _pid: at - 60)  # this VS Code started a minute before the chat
        self.assertEqual((said["state"], said["by"], said["missing"]), (launchenv.MISSING, "hook", [f"PATH {self.tools}"]))
        stale = launchenv.carried(self.root, 4711, none, lambda _pid: at + 60)  # this VS Code is newer than that report
        self.assertEqual(stale["state"], launchenv.UNSEEN)
        launchenv.note_seen(self.root, {"PATH": str(self.tools)})
        good = launchenv.carried(self.root, 4711, none, lambda _pid: at - 60)
        self.assertEqual((good["state"], good["by"]), (launchenv.CARRIED, "hook"))
