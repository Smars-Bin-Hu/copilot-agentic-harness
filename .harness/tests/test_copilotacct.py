"""`core/copilotacct.py` (1.8.38): the Copilot account read with gh for Settings > Copilot. What is kept, every shape that is no answer, the cache, `ahp.models_off`, and `/api/copilot-account`."""

from __future__ import annotations

import json
import subprocess
import time
import unittest
from typing import Any, Dict, List
from unittest import mock

import support  # noqa: F401 - HARNESS_GH=off: no test touches the real gh

from core import ahp, copilotacct, ghauth
from test_boardserve import ServeCase


def answer(**change: Any) -> Dict[str, Any]:
    """gh's answer as seen on a personal account (2026-11-24), with made-up ids."""
    found: Dict[str, Any] = {
        "id": 123, "login": "someone", "analytics_tracking_id": "abc", "access_type_sku": "monthly_subscriber_quota", "assigned_date": "2026-09-10T22:13:58-04:00",
        "copilot_plan": "individual", "chat_enabled": True, "cli_enabled": True, "is_mcp_enabled": True, "cloud_sessions_enabled": True, "is_staff": False,
        "endpoints": {"api": "https://api.example", "telemetry": "https://t.example"}, "organization_list": [], "enterprise_list": [], "organization_login_list": [],
        "quota_reset_date": "2026-12-01", "quota_reset_date_utc": "2026-12-01T00:00:00.000Z",
        "quota_snapshots": {
            "chat": {"unlimited": True, "entitlement": 0, "remaining": 0},
            "premium_interactions": {"overage_count": 0, "overage_permitted": False, "percent_remaining": 53.4, "quota_remaining": 802.1, "unlimited": False, "timestamp_utc": "2026-11-24T14:38:38.394Z",
                                     "credits_used": 697, "remaining": 802, "entitlement": 1500},
        },
    }
    found.update(change)
    return found


def premium(**change: Any) -> Dict[str, Any]:
    snapshot = dict(answer()["quota_snapshots"]["premium_interactions"])
    snapshot.update(change)
    return answer(quota_snapshots={"premium_interactions": snapshot})


class ReadTests(unittest.TestCase):
    def test_keeps_only_the_named_fields(self) -> None:
        found = copilotacct.read(json.dumps(answer()))
        self.assertEqual(found["credits"], {"unlimited": False, "total": 1500.0, "used": 697.0, "left": 802.1, "over": 0.0, "over_ok": False})
        self.assertEqual((found["plan"], found["resets"], found["since"][:10]), ("individual", "2026-12-01T00:00:00.000Z", "2026-09-10"))
        self.assertEqual(found["switches"], {"cli_enabled": True, "is_mcp_enabled": True, "chat_enabled": True, "cloud_sessions_enabled": True})
        text = json.dumps(found)
        for gone in ("someone", "abc", "api.example", "123", "is_staff"):
            self.assertNotIn(gone, text)

    def test_unlimited_and_over_the_limit(self) -> None:
        self.assertEqual(copilotacct.read(json.dumps(premium(unlimited=True)))["credits"], {"unlimited": True})
        over = copilotacct.read(json.dumps(premium(entitlement=300, quota_remaining=0, credits_used=342, overage_count=42, overage_permitted=True)))["credits"]
        self.assertEqual((over["over"], over["over_ok"], over["left"]), (42.0, True, 0.0))

    def test_used_is_worked_out_when_missing(self) -> None:
        snapshot = dict(answer()["quota_snapshots"]["premium_interactions"])
        snapshot.pop("credits_used")
        self.assertEqual(copilotacct.read(json.dumps(answer(quota_snapshots={"premium_interactions": snapshot})))["credits"]["used"], 1500 - 802.1)

    def test_credits_that_cannot_be_read_are_none_and_the_rest_stays(self) -> None:
        for bad in ({"entitlement": None}, {"entitlement": 0}, {"entitlement": "1500"}, {"entitlement": True}, {"quota_remaining": None, "remaining": None}, {"entitlement": float("nan")}):
            found = copilotacct.read(json.dumps(premium(**bad)))
            self.assertIsNone(found["credits"], bad)
            self.assertEqual(found["plan"], "individual")

    def test_organizations_are_names_only(self) -> None:
        found = copilotacct.read(json.dumps(answer(organization_login_list=["org-a", "org-a", 5, "org-b"], enterprise_list=[{"id": 9, "name": "ent"}, {"login": "x" * 500}])))
        self.assertEqual(found["orgs"], ["org-a", "org-b"])
        self.assertEqual(found["enterprises"], ["ent", "x" * copilotacct.NAME_KEEP])
        self.assertEqual(copilotacct.read(json.dumps(answer(organization_list=[{"login": "from-list"}])))["orgs"], ["from-list"])

    def test_switches_of_another_type_are_left_out(self) -> None:
        self.assertEqual(copilotacct.read(json.dumps(answer(is_mcp_enabled="no", chat_enabled=None)))["switches"], {"cli_enabled": True, "cloud_sessions_enabled": True})

    def test_what_is_no_answer(self) -> None:
        for text in ("", "not json", "[]", "null", '"text"', json.dumps({"message": "Not Found", "status": "404"}), b"\xff\xfe", 5, None):
            self.assertIsNone(copilotacct.read(text), text)
        self.assertIsNone(copilotacct.read(b" " * (copilotacct.MAX_BYTES + 1)))
        self.assertIsNone(copilotacct.read(json.dumps(answer(padding="x" * copilotacct.MAX_BYTES))))


class FetchTests(unittest.TestCase):
    def run_with(self, result: Any) -> Any:
        def run(gh: str, arguments: List[str], timeout: float, extra: Any) -> Any:
            self.asked = (gh, arguments, timeout)
            if isinstance(result, Exception):
                raise result
            return result
        return copilotacct.fetch(None, None, find=lambda folders: "/bin/gh", run=run)

    def test_a_good_answer(self) -> None:
        found = self.run_with(subprocess.CompletedProcess([], 0, json.dumps(answer()).encode(), b""))
        self.assertEqual(found["credits"]["total"], 1500.0)
        self.assertEqual(self.asked, ("/bin/gh", ["api", "/copilot_internal/user"], copilotacct.TIMEOUT))

    def test_every_failure_is_none(self) -> None:
        self.assertIsNone(self.run_with(subprocess.CompletedProcess([], 1, json.dumps(answer()).encode(), b"HTTP 401")))
        self.assertIsNone(self.run_with(ghauth.GhError("slow", "gh gave no answer")))
        self.assertIsNone(self.run_with(ghauth.GhError("cannot-run", "blocked")))
        self.assertIsNone(copilotacct.fetch(None, None, find=lambda folders: None))

    def test_no_gh_in_the_tests(self) -> None:
        self.assertIsNone(copilotacct.fetch())  # HARNESS_GH=off


class KeeperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 1000.0
        self.calls = 0
        self.answer: Any = {"plan": "individual"}
        self.jobs: List[Any] = []

    def fetch(self) -> Any:
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def keeper(self) -> copilotacct.Keeper:
        return copilotacct.Keeper(self.fetch, clock=lambda: self.now, wall=lambda: 5000.0, start=self.jobs.append)

    def run_jobs(self) -> None:
        while self.jobs:
            self.jobs.pop(0)()

    def test_first_read_then_kept_then_asked_again(self) -> None:
        keep = self.keeper()
        self.assertEqual(keep.latest(), {"state": "reading"})
        self.assertEqual(keep.latest(), {"state": "reading"})  # one read at a time
        self.assertEqual(len(self.jobs), 1)
        self.run_jobs()
        self.assertEqual(keep.latest(), {"state": "ok", "account": {"plan": "individual"}, "read_at": 5000.0, "reading": False})
        self.now += copilotacct.KEEP - 1
        keep.latest()
        self.assertEqual(self.jobs, [])
        self.now += 2
        self.assertEqual(keep.latest()["reading"], True)  # the old answer is shown while gh is asked again
        self.run_jobs()
        self.assertEqual(self.calls, 2)

    def test_fresh_asks_now(self) -> None:
        keep = self.keeper()
        keep.latest()
        self.run_jobs()
        keep.latest(fresh=True)
        self.run_jobs()
        self.assertEqual(self.calls, 2)

    def test_a_failure_drops_the_old_answer_and_is_tried_again_sooner(self) -> None:
        keep = self.keeper()
        keep.latest()
        self.run_jobs()
        self.answer = None
        keep.latest(fresh=True)
        self.run_jobs()
        self.assertEqual(keep.latest(), {"state": "none"})
        self.now += copilotacct.RETRY
        self.answer = RuntimeError("broken")
        self.assertEqual(keep.latest(), {"state": "reading"})
        self.run_jobs()
        self.assertEqual(keep.latest(), {"state": "none"})

    def test_forget_drops_a_read_that_was_under_way(self) -> None:
        keep = self.keeper()
        keep.latest()
        keep.forget()
        self.run_jobs()  # the answer about the account before comes back late
        self.assertEqual(keep.latest(), {"state": "reading"})
        self.run_jobs()
        self.assertEqual(keep.latest()["state"], "ok")


class ModelsOffTests(unittest.TestCase):
    def test_off_is_what_the_policy_keeps_out(self) -> None:
        state = {"agents": [
            {"provider": ahp.LOCAL_PROVIDER, "models": [
                {"id": "a", "name": "Model A", "policyState": "enabled", "_meta": {"priceCategory": "low"}},
                {"id": "b", "name": "Model B", "policyState": "disabled", "_meta": {"priceCategory": "high"}},
                {"id": "c", "policyState": "unconfigured"},
                {"id": ahp.FUSION_ID, "name": "Copilot Fusion"},
                {"id": "d", "name": "No state"}, "not a model", {"name": "no id", "policyState": "disabled"}]},
            {"provider": "claude", "models": [{"id": "e", "policyState": "disabled"}]}]}
        self.assertEqual(ahp.models_off(state), [{"id": "b", "name": "Model B", "price": "high"}, {"id": "c", "name": "c", "price": ""}])
        self.assertEqual([item["id"] for item in ahp.models_of(state)], ["a", ahp.FUSION_ID])


class ApiTests(ServeCase):
    def test_paired_only_and_the_shape(self) -> None:
        self.assertEqual(self.request("POST", "/api/copilot-account", {}, cookie="")[0], 403)
        cookie = self.pair()
        with mock.patch.object(copilotacct, "fetch", return_value=copilotacct.read(json.dumps(answer()))) as fetched:
            status, data, _ = self.request("POST", "/api/copilot-account", {}, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(data["state"], ("reading", "ok"))
            self.assertEqual(data["models"], {"on": [], "off": []})  # no link in the tests
            for _ in range(100):
                status, data, _ = self.request("POST", "/api/copilot-account", {}, cookie=cookie)
                if data["state"] == "ok":
                    break
                time.sleep(0.05)
            self.assertEqual(data["account"]["credits"]["total"], 1500.0)
            self.request("POST", "/api/copilot-account", {"fresh": "yes"}, cookie=cookie)  # only `true` asks gh again
            self.assertEqual(fetched.call_count, 1)


if __name__ == "__main__":
    unittest.main()
