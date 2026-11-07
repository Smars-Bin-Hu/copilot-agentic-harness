"""This computer (1.7.11): the tool folders and the CA bundle VS Code is started with. No test reaches the network: the chain and the check are given."""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path
from typing import List, Tuple

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
        self.assertIn("$h = 'h.example.org'; $p = '127.0.0.1:9000'", script, "the values are in the script itself: -Command passes it no $args")
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
