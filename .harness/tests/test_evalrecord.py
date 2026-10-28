"""The eval record (M44-1): what is kept about a closed task, and the proof that no text gets in. All inputs are made up (evalsynth)."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import unittest
from typing import Any, Dict, List

import evalsynth
import support  # noqa: F401  (puts the engine on the path)
from evalsynth import CANARY, NAME, SALT

from core import evalrecord


def build(**over: Any) -> Dict[str, Any]:
    """A record from the synthetic task; any of state, insight, facts, identity can be replaced (an empty one stays empty)."""
    given = {
        "state": evalsynth.task_state(), "insight": evalsynth.insight(), "facts": evalsynth.facts(), "identity": evalsynth.identity(), **over,
    }
    return evalrecord.build_task_record(given["state"], given["insight"], given["facts"], given["identity"], now="2026-03-02T13:00:05Z")


def line(record: Dict[str, Any], **over: Any) -> str:
    return evalrecord.dumps({**record, **over})


def answer(rid: str, at: str, **over: Any) -> Dict[str, Any]:
    return {"t": "answer", "v": 1, "at": at, "rid": rid, "round": 1, "state": "answered", "effort_min": 90, "correction": "some", "friction": "none", **over}


class BuildTest(unittest.TestCase):
    def test_every_field_equals_the_hand_worked_value(self) -> None:
        record = build()
        expected = {
            "t": "task", "v": 1, "at": "2026-03-02T13:00:05Z", "round": 1, "user": "U9", "harness_version": "1.6.0", "surface": "vscode",
            "source": "copilot-events", "models": ["gpt-5"], "backfilled": False, "kind": "dev", "tier": "full", "size": "M", "size_source": "open",
            "domains_n": 1, "todo_steps": 6, "files_changed": 3, "lines_added": 120, "lines_removed": 40, "targets_n": 1,
            "lead_s": 13800.0, "lead_active_s": 12000.0, "wall_s": 12300.0, "active_s": 900.0, "model_s": 500.0, "tool_s": 300.0, "approval_s": 50.0,
            "subagent_s": 50.0, "waiting_s": 9000.0, "paused_s": 600.0, "prompts": 2,
            "by_stage": {"requirement": {"active_s": 300.0, "prompts": 1}, "developing": {"active_s": 600.0, "prompts": 1}, "env": {"active_s": 0.0, "prompts": 0}},
            "aiu": 12.5, "premium_requests": 18.0, "input_tokens": 3000, "output_tokens": 300, "subagent_tokens": 4000, "tool_calls": 8, "failed_tool_calls": 2, "context_max": 90000,
            "review": {"n": 2, "rounds": 4, "valid": 2, "fails": 1, "invalid": 1, "refunded": 1, "dismissed": 1, "waived": False, "extended": 1, "passes_at_close": 2},
            "plan_approvals": 1, "req_confirms": 1, "req_changed": 0, "task_rounds": 1, "forked_from": None,
            "approvals": {"req": 1, "plan": 1, "promote": 1}, "approvals_by_person": True, "denied": 2, "denied_by": {"gate": 2}, "asked": 1, "stop_blocks": 0, "push_denied": 0,
            "autorun": {"used": False, "stop_reason": None}, "handoffs": 0, "estimate_min": 240, "answers": {"state": "pending"}, "followup": {"state": "pending"},
        }
        rid = record.pop("rid")
        self.assertEqual(record, expected)
        self.assertEqual(evalrecord.errors({**record, "rid": rid}), [])

    def test_canary_words_planted_everywhere_text_lives_do_not_come_out(self) -> None:
        state = evalsynth.task_state(forked_from=f"{CANARY}-FORK", name=f"{CANARY}-NAME-1")
        facts = evalsynth.facts(denied_by={"gate": 2, f"{CANARY}-/etc/passwd": 5, "Bad Key": 1}, forked_from=f"{CANARY}-FORK", extra_field=f"{CANARY}-EXTRA")
        insight = evalsynth.insight(models_note=f"{CANARY}-MODEL")
        insight["prompts"][0]["models"] = ["gpt-5", f"{CANARY} model with spaces"]
        text = evalrecord.dumps(build(state=state, facts=facts, insight=insight))
        self.assertNotIn(CANARY, text)
        self.assertNotIn("passwd", text)
        self.assertNotIn(NAME, text)
        self.assertIn('"denied_by":{"gate":2}', text)

    def test_the_forked_from_name_is_kept_only_as_a_salted_hash(self) -> None:
        record = build(facts=evalsynth.facts(forked_from="example-parent"))
        self.assertRegex(record["forked_from"], r"^[0-9a-f]{12}$")
        self.assertNotEqual(record["forked_from"], hashlib.sha256(b"example-parent").hexdigest()[:12])
        self.assertNotEqual(record["forked_from"], build(identity=evalsynth.identity(salt="f" * 32), facts=evalsynth.facts(forked_from="example-parent"))["forked_from"])

    def test_old_and_degraded_inputs_give_nulls_not_errors(self) -> None:
        record = build(insight=evalsynth.insight(source="hook-log", with_usage=False), facts={})
        self.assertEqual(record["source"], "hook-log")
        for key in ("aiu", "premium_requests", "input_tokens", "output_tokens", "model_s", "tool_s", "approval_s", "subagent_s", "subagent_tokens"):
            self.assertIsNone(record[key], key)
        self.assertIsNone(record["todo_steps"])
        self.assertEqual(record["denied_by"], {})
        self.assertEqual(record["lead_s"], 13800.0)
        bare = build(insight={}, facts={}, state=evalsynth.task_state(size=None))
        self.assertEqual((bare["source"], bare["prompts"], bare["by_stage"], bare["size"], bare["size_source"], bare["lead_active_s"], bare["wall_s"]), ("none", 0, {}, None, None, None, None))

    def test_a_task_without_a_close_event_has_no_lead_time(self) -> None:
        state = evalsynth.task_state()
        state["events"] = [item for item in state["events"] if item["what"] != "close"]
        self.assertIsNone(build(state=state)["lead_s"])

    def test_the_review_counts_only_the_rounds_of_this_task_round(self) -> None:
        state = evalsynth.task_state(round=2, round_started_at="2026-03-02T11:00:00+00:00")
        state["review"]["rounds"][0]["task_round"] = 2
        record = build(state=state)
        self.assertEqual((record["review"]["rounds"], record["task_rounds"]), (1, 2))
        self.assertEqual(record["plan_approvals"], 0)  # the events of round 1 are not round 2's

    def test_autorun_reason_is_one_of_the_known_words(self) -> None:
        for why, kept in (("steps", "steps"), (f"{CANARY} free words", "other")):
            state = evalsynth.task_state(autorun={"state": "off", "started_at": "2026-03-02T10:00:00+00:00", "stopped": {"why": why, "detail": f"{CANARY}-DETAIL"}})
            record = build(state=state)
            self.assertEqual(record["autorun"], {"used": True, "stop_reason": kept})
            self.assertNotIn(CANARY, evalrecord.dumps(record))

    def test_a_test_task_keeps_counts_of_its_runs(self) -> None:
        record = build(facts=evalsynth.facts(test={"envs": 2, "pass": 1, "fail": 1, "runs": 3, "defects_open": 1, "defects_fixed": 2}))
        self.assertEqual(record["test"], {"envs": 2, "pass": 1, "fail": 1, "runs": 3, "defects_open": 1, "defects_fixed": 2})
        self.assertNotIn("test", build())

    def test_a_missing_salt_or_user_is_an_error_not_a_weak_record(self) -> None:
        with self.assertRaises(ValueError):
            build(identity=evalsynth.identity(salt=""))
        with self.assertRaises(ValueError):
            build(identity=evalsynth.identity(user="Alice"))
        with self.assertRaises(ValueError):
            build(state=evalsynth.task_state(kind=f"{CANARY}-kind"))


class SanitizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.record = build()

    def test_an_unknown_field_is_dropped_and_counted(self) -> None:
        clean, info = evalrecord.sanitize({**self.record, "extra_field": f"{CANARY}-EXTRA", "review": {**self.record["review"], "note": "x"}})
        self.assertEqual(clean, self.record)
        self.assertEqual((info["dropped"], info["reason"]), (2, ""))

    def test_a_sentence_where_a_word_belongs_refuses_the_whole_line(self) -> None:
        for bad in ({"answers": {"state": "answered", "friction": "see ticket XYZ"}}, {"kind": "see ticket XYZ"}, {"source": f"{CANARY}-path"}, {"user": "Alice"}, {"rid": "ticket-12345"}):
            clean, info = evalrecord.sanitize({**self.record, **bad})
            self.assertIsNone(clean, bad)
            self.assertTrue(info["reason"], bad)
        clean, info = evalrecord.sanitize(answer(self.record["rid"], "2026-03-02T14:00:00Z", friction="see ticket XYZ"))
        self.assertIsNone(clean)
        self.assertIn("see ticket XYZ", info["reason"])

    def test_numbers_out_of_range_are_refused(self) -> None:
        for bad in ({"lead_s": -1}, {"lead_s": 400 * 86400}, {"aiu": -0.5}, {"aiu": 10 ** 7}, {"round": 0 - 1}, {"round": 100}, {"prompts": 1.5}, {"lead_s": "12"}, {"lead_s": True}, {"estimate_min": 10081}):
            self.assertIsNone(evalrecord.sanitize({**self.record, **bad})[0], bad)
        for bad in ('{"t":"task","lead_s":NaN}', '{"t":"task","lead_s":Infinity}', '{"t":"task","lead_s":1e999}'):
            self.assertIsNone(evalrecord.sanitize(bad)[0], bad)
        self.assertIsNone(evalrecord.sanitize({**self.record, "by_stage": {"x" * 5: {"active_s": 1.0, "prompts": 1}}})[0])
        self.assertIsNone(evalrecord.sanitize({**self.record, "denied_by": {"Not A Module": 1}})[0])
        self.assertIsNone(evalrecord.sanitize({**self.record, "denied_by": {"gate": 10 ** 9}})[0])
        self.assertIsNone(evalrecord.sanitize({**self.record, "denied_by": {f"m{n}": 1 for n in range(13)}})[0])

    def test_a_trailing_newline_does_not_pass_a_pattern(self) -> None:
        self.assertIsNone(evalrecord.sanitize({**self.record, "user": "U9\n"})[0])
        self.assertIsNone(evalrecord.sanitize({**self.record, "rid": "a1b2c3d4e5f6\n"})[0])

    def test_lines_that_are_not_records(self) -> None:
        for bad in ("", "not json", "[1,2]", '{"t":"mystery","v":1}', '{"t":"task"}', '{"t":"task","v":2}', json.dumps({"t": "task", "v": 1, "pad": "x" * evalrecord.MAX_LINE})):
            self.assertIsNone(evalrecord.sanitize(bad)[0], bad[:30])

    def test_the_one_free_text_is_one_short_line(self) -> None:
        good = {"t": "feedback", "v": 1, "at": "2026-03-02T14:00:00Z", "user": "U9", "text": "Saved me a lot of time on the first draft."}
        self.assertEqual(evalrecord.sanitize(good)[0], good)
        for bad in ("", "x" * (evalrecord.FEEDBACK_CHARS + 1), "two\nlines", "tab\there"):
            self.assertIsNone(evalrecord.sanitize({**good, "text": bad})[0], repr(bad))

    def test_support_minutes_are_a_small_whole_number(self) -> None:
        good = {"t": "support", "v": 1, "at": "2026-03-02T14:00:00Z", "user": "U1", "date": "2026-03-02", "minutes": 30}
        self.assertEqual(evalrecord.sanitize(good)[0], good)
        for bad in ({"minutes": 0}, {"minutes": 1441}, {"minutes": 2.5}, {"date": "March 2"}):
            self.assertIsNone(evalrecord.sanitize({**good, **bad})[0], bad)

    def test_a_line_that_is_json_text_is_read_too(self) -> None:
        self.assertEqual(evalrecord.sanitize(line(self.record))[0], self.record)
        self.assertEqual(evalrecord.sanitize(line(self.record).encode("utf-8"))[0], self.record)


class RidTest(unittest.TestCase):
    CREATED = evalsynth.CREATED

    def test_it_is_a_keyed_hash_of_the_folder_name_and_the_start_time(self) -> None:
        expected = hmac.new(SALT.encode(), f"task\n{NAME}\n{self.CREATED}".encode(), hashlib.sha256).hexdigest()[:12]
        self.assertEqual(evalrecord.rid(SALT, NAME, self.CREATED), expected)

    def test_same_input_same_id_and_a_new_salt_a_new_id(self) -> None:
        first = evalrecord.rid(SALT, NAME, self.CREATED)
        self.assertEqual(first, evalrecord.rid(SALT, NAME, self.CREATED))
        self.assertNotEqual(first, evalrecord.rid("f" * 32, NAME, self.CREATED))
        self.assertNotEqual(first, evalrecord.rid(SALT, NAME, "2026-03-03T09:00:00+00:00"))

    def test_it_cannot_be_found_by_hashing_a_guessed_name(self) -> None:
        found = evalrecord.rid(SALT, "TICKET-100", self.CREATED)
        for guess in ("TICKET-100", f"TICKET-100{self.CREATED}", f"TICKET-100\n{self.CREATED}", f"task\nTICKET-100\n{self.CREATED}"):
            self.assertNotEqual(found, hashlib.sha256(guess.encode()).hexdigest()[:12])
            self.assertNotEqual(found, hashlib.md5(guess.encode()).hexdigest()[:12])
        self.assertRegex(found, r"^[0-9a-f]{12}$")

    def test_names_one_character_apart_have_nothing_in_common(self) -> None:
        a, b = evalrecord.rid(SALT, "TICKET-100", self.CREATED), evalrecord.rid(SALT, "TICKET-101", self.CREATED)
        self.assertNotEqual(a, b)
        self.assertLess(sum(x == y for x, y in zip(a, b)), 6)  # about 12/16 would match by chance; a prefix match would show here

    def test_no_salt_no_id(self) -> None:
        for weak in ("", "short", None):
            with self.assertRaises(ValueError):
                evalrecord.rid(weak, NAME, self.CREATED)  # type: ignore[arg-type]

    def test_new_salts_are_long_and_different(self) -> None:
        one, two = evalrecord.new_salt(), evalrecord.new_salt()
        self.assertNotEqual(one, two)
        self.assertGreaterEqual(len(one), 32)


class FoldTest(unittest.TestCase):
    def setUp(self) -> None:
        self.task = build()
        self.rid = self.task["rid"]

    def lines(self) -> List[str]:
        return [
            line(self.task),
            line(answer(self.rid, "2026-03-02T14:00:00Z", effort_min=60)),
            line(answer(self.rid, "2026-03-02T15:00:00Z", effort_min=90)),
            line({"t": "followup", "v": 1, "at": "2026-03-30T09:00:00Z", "rid": self.rid, "round": 1, "state": "answered", "defect": "none"}),
            line({"t": "feedback", "v": 1, "at": "2026-03-02T14:00:00Z", "user": "U9", "text": "first thought"}),
            line({"t": "feedback", "v": 1, "at": "2026-03-09T14:00:00Z", "user": "U9", "text": "second thought"}),
            line({"t": "support", "v": 1, "at": "2026-03-02T14:00:00Z", "user": "U1", "date": "2026-03-02", "minutes": 30}),
            "not a record",
        ]

    def test_the_latest_line_per_key_wins_and_answers_join_their_task(self) -> None:
        folded = evalrecord.fold(self.lines())
        self.assertEqual(len(folded["tasks"]), 1)
        record = folded["tasks"][0]
        self.assertEqual(record["answers"], {"state": "answered", "effort_min": 90, "correction": "some", "friction": "none", "answered_at": "2026-03-02T15:00:00Z"})
        self.assertEqual(record["followup"], {"state": "answered", "defect": "none", "at": "2026-03-30T09:00:00Z"})
        self.assertEqual([item["text"] for item in folded["feedback"]], ["second thought"])
        self.assertEqual([item["minutes"] for item in folded["support"]], [30])
        self.assertEqual(folded["stats"], {"lines": 8, "refused": 1, "dropped_fields": 0, "orphans": 0})

    def test_the_order_of_the_lines_never_changes_the_result(self) -> None:
        reference = json.dumps(evalrecord.fold(self.lines()), sort_keys=True)
        rng = random.Random(7)
        for _ in range(20):
            shuffled = self.lines()
            rng.shuffle(shuffled)
            self.assertEqual(json.dumps(evalrecord.fold(shuffled), sort_keys=True), reference)

    def test_an_answer_that_comes_before_its_task_still_joins_it(self) -> None:
        lines = self.lines()
        folded = evalrecord.fold([lines[2], lines[1], lines[0]])
        self.assertEqual(folded["tasks"][0]["answers"]["effort_min"], 90)

    def test_an_answer_with_no_task_is_counted_not_invented(self) -> None:
        folded = evalrecord.fold([line(answer("0" * 12, "2026-03-02T14:00:00Z"))])
        self.assertEqual((folded["tasks"], folded["stats"]["orphans"]), ([], 1))

    def test_the_same_task_in_another_round_is_another_task(self) -> None:
        second = {**self.task, "round": 2, "task_rounds": 2}
        folded = evalrecord.fold([line(self.task), line(second)])
        self.assertEqual([item["round"] for item in folded["tasks"]], [1, 2])

    def test_a_task_line_written_again_later_replaces_the_earlier_one(self) -> None:
        later = {**self.task, "at": "2026-03-03T00:00:00Z", "prompts": 99}
        for order in ([self.task, later], [later, self.task]):
            self.assertEqual(evalrecord.fold(line(item) for item in order)["tasks"][0]["prompts"], 99)

    def test_unknown_fields_in_a_log_are_counted_when_folded(self) -> None:
        folded = evalrecord.fold([line(self.task, sneaky="x")])
        self.assertEqual((len(folded["tasks"]), folded["stats"]["dropped_fields"]), (1, 1))


class CompletenessTest(unittest.TestCase):
    def folded(self, **over: Any) -> Dict[str, Any]:
        record = build()
        lines = [line(record), line(answer(record["rid"], "2026-03-02T14:00:00Z"))]
        task = evalrecord.fold(lines)["tasks"][0]
        task.update(over)
        return task

    def test_a_record_with_everything_is_complete_and_friction_is_not_needed(self) -> None:
        task = self.folded()
        task["answers"]["friction"] = None
        self.assertEqual(evalrecord.completeness(task), {"complete": True, "missing": []})

    def test_each_gap_is_named(self) -> None:
        cases = {
            "size": {"size": None, "size_source": None},
            "size_late": {"size_source": "late"},
            "effort": {"answers": {"state": "answered", "effort_min": None, "correction": "none", "friction": None, "answered_at": "x"}},
            "correction": {"answers": {"state": "answered", "effort_min": 5, "correction": None, "friction": None, "answered_at": "x"}},
            "source_none": {"source": "none"},
        }
        for missing, over in cases.items():
            self.assertEqual(evalrecord.completeness(self.folded(**over)), {"complete": False, "missing": [missing]}, missing)

    def test_pending_and_skipped_answers_are_incomplete(self) -> None:
        for state in ("pending", "skipped"):
            result = evalrecord.completeness(self.folded(answers={"state": state}))
            self.assertEqual(result["missing"], ["effort", "correction"], state)

    def test_a_backfilled_task_has_no_size_so_it_is_never_complete(self) -> None:
        self.assertFalse(evalrecord.completeness(self.folded(size=None, size_source=None, backfilled=True))["complete"])


class SerializeTest(unittest.TestCase):
    def test_the_same_record_gives_the_same_bytes_whatever_the_key_order(self) -> None:
        record = build()
        shuffled = dict(reversed(list(record.items())))
        self.assertEqual(evalrecord.dumps(record), evalrecord.dumps(shuffled))
        text = evalrecord.dumps(record)
        self.assertNotIn(" ", text.replace('"Saved me', ""))  # no padding: the bytes are what a digest is taken over
        self.assertNotIn("\n", text)
        self.assertEqual(text, evalrecord.dumps(json.loads(text)))

    def test_non_ascii_is_escaped_so_the_bytes_do_not_depend_on_the_platform(self) -> None:
        text = evalrecord.dumps({"t": "feedback", "text": "快 and fast"})
        self.assertTrue(text.isascii())
        self.assertEqual(json.loads(text)["text"], "快 and fast")

    def test_nan_cannot_be_written(self) -> None:
        with self.assertRaises(ValueError):
            evalrecord.dumps({"x": float("nan")})

    def test_utc_text_is_a_fixed_shape(self) -> None:
        self.assertEqual(evalrecord.utc_text(0), "1970-01-01T00:00:00Z")
        self.assertRegex(evalrecord.utc_text(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
