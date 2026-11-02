"""What the knowledge base window fills in after `kb status` (1.6.86): the stale cards, the form errors, the last read of a domain, the gaps."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".harness" / "engine"))

from core import kbdetail, kbmap, kbreads, kbstatus  # noqa: E402
from modules.task import kbview, taskhtml  # noqa: E402

STALE = {
    "orders": {"changed": [{"id": "job:a"}, {"id": "job:b"}], "gone": [{"id": "job:c"}], "unstamped": []},
    "billing": {"changed": [], "gone": []},
    "broken": {"error": "no such repository"},
}


class DetailTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_the_numbers_add_up_and_an_unknown_domain_is_not_zero(self) -> None:
        with mock.patch.object(kbdetail, "stale_of", return_value=STALE), mock.patch.object(kbdetail, "form_errors", return_value=2), mock.patch.object(kbreads, "last_by_domain", return_value={"orders": "2026-11-01T10:00:00Z"}):
            found = kbdetail.detail(self.root)
        self.assertEqual((found["stale"], found["form_errors"]), (3, 2))
        self.assertEqual(found["domains"]["orders"], {"stale": 3, "read": "2026-11-01T10:00:00Z"})
        self.assertEqual(found["domains"]["billing"], {"stale": 0, "read": ""})
        self.assertIsNone(found["domains"]["broken"]["stale"])

    def test_one_broken_domain_loses_no_other(self) -> None:
        def stale(_root, name):
            if name == "bad":
                raise ValueError("bad " * 200)
            return {"changed": [{"id": "x"}], "gone": []}
        with mock.patch.object(kbdetail.domainskills, "domains", return_value={"good": Path("g"), "bad": Path("b")}), mock.patch.object(kbdetail.kbstd, "stale", side_effect=stale):
            found = kbdetail.stale_of(self.root)
        self.assertEqual(len(found["good"]["changed"]), 1)
        self.assertLessEqual(len(found["bad"]["error"]), 300)

    def test_health_lists_only_what_asks_for_something_and_cuts_a_long_list(self) -> None:
        many = {"long": {"changed": [{"id": f"job:{n}"} for n in range(300)], "gone": []}, "clean": {"changed": [], "gone": []}}
        with mock.patch.object(kbdetail, "stale_of", return_value=many), mock.patch.object(kbdetail.kbstd, "check", return_value={"errors": 0, "domains": 2}), mock.patch.object(kbdetail, "gaps", return_value={}):
            found = kbdetail.health(self.root)
        self.assertEqual([row["domain"] for row in found["stale"]], ["long"])
        self.assertEqual((found["stale"][0]["total"], len(found["stale"][0]["changed"])), (300, kbdetail.MAX_LIST))

    def test_no_map_yet_is_no_gaps(self) -> None:
        with mock.patch.object(kbdetail.kbgraph, "gaps", side_effect=kbmap.MapError("no map")):
            self.assertEqual(kbdetail.gaps(self.root), {})

    def test_the_last_read_is_the_newest_of_every_session(self) -> None:
        rows = {"a": [{"at": "2026-11-01", "kb": ["kb/domains/Orders/card.md"]}, {"at": "2026-10-01", "kb": ["kb/domains/orders/x.md", "kb/README.md", "kb/domains/"]}], "b": [{"at": "2026-11-02", "kb": ["kb/domains/orders/y.md"]}, {"at": "2026-11-03"}]}
        with mock.patch.object(kbreads, "session_files", return_value=[("s", "a"), ("s", "b")]), mock.patch.object(kbreads, "read_lines", side_effect=lambda name: rows[name]):
            self.assertEqual(kbreads.last_by_domain(self.root), {"orders": "2026-11-02"})

    def test_status_counts_the_cards_of_a_domain(self) -> None:
        folder = self.root / "orders"
        (folder / "objects").mkdir(parents=True)
        (folder / "objects" / "index.jsonl").write_text(json.dumps({"id": "a"}) + "\n\n" + json.dumps({"id": "b"}) + "\n", encoding="utf-8")
        self.assertEqual(kbstatus.domain_state(self.root, folder, False)["cards"], 2)

    def test_the_view_works_on_its_own_thread_name(self) -> None:
        view = kbview.View(self.root)
        with mock.patch.object(kbdetail, "detail", return_value={"stale": 1}):
            self.assertEqual(view.work("detail")(), {"stale": 1})


class PageTests(unittest.TestCase):
    def test_a_person_never_reads_the_words_written_for_the_agent(self) -> None:
        dock = (taskhtml.WEB / "dock.js").read_text(encoding="utf-8")
        self.assertNotIn("found.next", dock.split("function near(")[0].split("function nextCard(")[1])

    def test_the_badge_has_a_place_and_goes_when_it_is_empty(self) -> None:
        self.assertIn(".dock-count[hidden]{display:none}", (taskhtml.WEB / "dock.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
