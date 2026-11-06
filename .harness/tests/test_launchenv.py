"""This computer (1.7.11): the tool folders and the CA bundle VS Code is started with. No test reaches the network: the chain and the check are given."""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path
from typing import List, Tuple

from support import HarnessTestCase

from core import launchenv, servers


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
        servers.write_env(self.root, {launchenv.PATH_KEY: os.pathsep.join([str(self.tools), str(self.root / "gone")])})
        self.assertEqual(launchenv.extra(self.root, {"PATH": "/usr/bin"})["PATH"].split(os.pathsep), [str(self.tools), "/usr/bin"])
        launchenv.save_paths(self.root, [])
        self.assertEqual(launchenv.extra(self.root, {"PATH": "/usr/bin"}), {})

    def test_the_identities_in_the_same_file_stay(self) -> None:
        servers.write_env(self.root, {"HARNESS_SERVER_DB_ACCOUNT": "me"})
        launchenv.save_paths(self.root, [str(self.tools)])
        self.assertEqual(servers.read_env(self.root)["HARNESS_SERVER_DB_ACCOUNT"], "me")


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
        blocks, trust = launchenv.chain_windows("h.example.org", "127.0.0.1:9000", run=lambda *a, **k: Done())
        self.assertEqual((blocks, trust), ([cert(4)], "None"))

        class Refused:
            stdout, stderr = "PROXY HTTP/1.1 403 Forbidden\r\n", ""
        with self.assertRaises(ValueError):
            launchenv.chain_windows("h.example.org", "127.0.0.1:9000", run=lambda *a, **k: Refused())
