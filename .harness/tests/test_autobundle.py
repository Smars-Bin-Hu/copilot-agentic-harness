"""1.8.33: the certificate bundle is made by the board itself: the recipe is brought, the bundle is made in the background, once; the wizard says so and Review and the gear say when it was not made."""
from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import support  # noqa: F401 - the paths
from core import connections, launchenv, messages, wizard
from modules.task import bundlejob, ready, setupjob, taskhtml
from taskcase import TaskCase

WEB = Path(taskhtml.__file__).resolve().parent / "web"
SCRIPT = (WEB / "wizard.js").read_text(encoding="utf-8")
SHEET = (WEB / "wizard.css").read_text(encoding="utf-8")
CORE = Path(taskhtml.__file__).resolve().parents[2] / "core"
TEXTS = {code: json.loads((CORE / f"messages.{code}.json").read_text(encoding="utf-8")) for code in ("en", "zh")}
RECIPE = {"ca_bundle": {"host": "example.com", "proxy": "proxy.example.com:9000"}}


def made_file(root: Path) -> Dict[str, Any]:
    target = root / launchenv.BUNDLE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    connections.write_env(root, {launchenv.BUNDLE_KEY: launchenv.BUNDLE.as_posix()})
    return {"ok": True, "why": ""}


class AutoBundleTests(TaskCase):
    def recipe(self) -> None:
        (self.root / launchenv.RECIPE).write_text(json.dumps(RECIPE), encoding="utf-8")


    def wait(self, auto: bundlejob.Auto) -> None:
        if auto.thread:
            auto.thread.join(5)

    def test_it_starts_once_when_there_is_a_recipe_and_no_bundle_and_calls_after(self) -> None:
        self.recipe()
        called = []
        auto = bundlejob.Auto(self.root, after=lambda: called.append(1))
        with mock.patch.object(launchenv, "make", side_effect=lambda root, host, proxy: made_file(root)) as make:
            self.assertTrue(auto.kick())
            self.wait(auto)
            self.assertFalse(auto.kick())  # the bundle is there now
        self.assertEqual(make.call_args[0][1:], ("example.com", "proxy.example.com:9000"))
        view = auto.view()
        self.assertEqual((view["state"], called), ("made", [1]))
        self.assertTrue(view["made"])

    def test_it_does_not_start_with_a_bundle_or_without_a_recipe(self) -> None:
        auto = bundlejob.Auto(self.root)
        with mock.patch.object(launchenv, "make") as make:
            self.assertFalse(auto.kick())  # no recipe
            self.recipe()
            made_file(self.root)
            self.assertFalse(auto.kick())  # a bundle is there
        make.assert_not_called()
        self.assertEqual(auto.view()["state"], "made")

    def test_a_failure_is_kept_and_not_tried_again_unless_a_new_import_asks(self) -> None:
        self.recipe()
        auto = bundlejob.Auto(self.root)
        with mock.patch.object(launchenv, "make", return_value={"ok": False, "why": "no root"}) as make:
            self.assertTrue(auto.kick())
            self.wait(auto)
            for _ in range(3):
                self.assertFalse(auto.kick())
            self.assertEqual(make.call_count, 1)
            self.assertEqual((auto.view()["state"], auto.view()["why"]), ("failed", "no root"))
            self.assertTrue(auto.kick(True))  # a new knowledge base came in
            self.wait(auto)
        self.assertEqual(make.call_count, 2)

    def test_an_error_of_make_is_a_failure_with_a_short_reason(self) -> None:
        self.recipe()
        auto = bundlejob.Auto(self.root)
        with mock.patch.object(launchenv, "make", side_effect=OSError("x" * 900)):
            auto.kick()
            self.wait(auto)
        self.assertEqual(auto.view()["state"], "failed")
        self.assertLessEqual(len(auto.view()["why"]), bundlejob.WHY)

    def test_it_is_not_made_twice_at_once(self) -> None:
        self.recipe()
        gate = threading.Event()
        auto = bundlejob.Auto(self.root)
        with mock.patch.object(launchenv, "make", side_effect=lambda *a: (gate.wait(5), made_file(self.root))[1]) as make:
            self.assertTrue(auto.kick())
            self.assertEqual(auto.view()["state"], "making")
            self.assertFalse(auto.kick(True))
            gate.set()
            self.wait(auto)
        self.assertEqual(make.call_count, 1)

    def test_the_end_of_a_knowledge_base_import_makes_it(self) -> None:
        job = setupjob.Job()
        seen = []
        job.on_done = lambda: seen.append(1)
        with mock.patch.object(setupjob, "steps", return_value=[("kb", lambda: "ok")]):
            job.work(self.root, {}, ("kb",))
        self.assertEqual(seen, [1])
        with mock.patch.object(setupjob, "steps", return_value=[("kb", lambda: (_ for _ in ()).throw(ValueError("no")))]):
            job.work(self.root, {}, ("kb",))
        self.assertEqual(seen, [1])  # a failed import does not

    def test_the_gear_has_a_note_while_the_bundle_is_missing_and_not_while_it_is_made_or_under_way(self) -> None:
        self.recipe()
        board = ready.Ready(self.root, link=None, checker=mock.Mock())
        notes = lambda: [note["key"] for note in board.optional()["notes"]]  # noqa: E731
        self.assertIn("cert", notes())
        note = next(n for n in board.optional()["notes"] if n["key"] == "cert")
        self.assertEqual((note["text"], note["effect"]), (messages.text("ready.note.cert"), messages.text("ready.effect.cert")))
        board.bundle.state = "making"
        self.assertNotIn("cert", notes())
        board.bundle.state = "failed"
        self.assertIn("cert", notes())
        made_file(self.root)
        self.assertNotIn("cert", notes())

    def test_review_has_a_row_when_the_recipe_asks_and_it_is_not_made(self) -> None:
        self.recipe()
        programs = {"rows": [], "all_found": True}
        rows = lambda state: {row["id"]: row for row in wizard.summary(self.root, programs, {}, {"state": state})["rows"]}  # noqa: E731
        row = rows("failed")["bundle"]
        self.assertEqual((row["done"], row["label"], row["effect"]), (False, messages.text("setup.w.label.bundle"), messages.text("setup.w.bundle.effect")))
        self.assertFalse(row["required"])
        self.assertNotIn("bundle", rows("making"))
        made_file(self.root)
        self.assertTrue(rows("made")["bundle"]["done"])

    def test_the_review_step_bundle_asks_for_another_try_and_a_failure_shows_its_reason(self) -> None:
        from modules.task import boardserve

        self.recipe()
        board = boardserve.Board(self.root, False, 0, [])
        with mock.patch.object(launchenv, "make", return_value={"ok": False, "why": "no root"}) as make:
            board.bundle_job.kick()
            board.bundle_job.thread.join(5)
            board.setup({"step": "bundle"})
            board.bundle_job.thread.join(5)
            self.assertEqual(make.call_count, 2)  # a failure of this run does not stop a press on Try again
            found = board.setup({"step": "bundle"})
            self.assertIn(found["state"], ("making", "failed"))
            board.bundle_job.thread.join(5)
        rows = {row["id"]: row for row in board.setup({"step": "summary"})["rows"]}
        self.assertIn("no root", rows["bundle"]["effect"])

    def test_no_recipe_no_row(self) -> None:
        self.assertNotIn("bundle", [row["id"] for row in wizard.summary(self.root, {"rows": []}, {}, {"state": "failed"})["rows"]])


class WizardPageTests(unittest.TestCase):
    def test_the_line_the_tick_and_the_review_row_are_in_the_page_script(self) -> None:
        for needle in ("wz-cert", "paintCert", "wizard.cert.making", "wizard.cert.made", 'row.id === "bundle"', "MOTION.appear(shell.cert", "bundle=fail", 'q("bundle"'):
            self.assertIn(needle, SCRIPT, needle)
        self.assertIn('toSettings("network")', SCRIPT)  # where Settings exists
        self.assertIn('"wizard.v.retry"', SCRIPT)  # on the wizard page the button is "Try again", never a way out to "/"
        self.assertNotIn('"harness.reopen", "settings:" + section', SCRIPT)
        self.assertIn('api.setup("bundle")', SCRIPT)
        self.assertIn("function fitLines", SCRIPT)
        self.assertIn(".wz-lines", SHEET)
        self.assertIn(".wz-cert", SHEET)

    def test_the_texts_exist_in_both_languages(self) -> None:
        for key in ("wizard.cert.making", "wizard.cert.made", "wizard.cert.tip", "wizard.v.cert", "wizard.v.cert.e", "wizard.v.retry", "setup.w.label.bundle", "setup.w.bundle.effect", "ready.note.cert", "ready.effect.cert"):
            for code in ("en", "zh"):
                self.assertTrue(TEXTS[code].get(key), (code, key))
        self.assertEqual(TEXTS["en"]["wizard.cert.making"], "Making the certificate bundle for the company network")

    def test_the_moves_are_short(self) -> None:
        self.assertNotRegex(SCRIPT[SCRIPT.index("function paintCert"):SCRIPT.index("function pollReady")], r"ms: ?(3\d\d|[4-9]\d\d|\d{4})")


if __name__ == "__main__":
    unittest.main()
