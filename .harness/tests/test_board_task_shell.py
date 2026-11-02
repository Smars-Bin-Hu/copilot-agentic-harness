"""The shell of the task page (1.6.16, B87): the facts the server adds for the info line and the context card (thinking effort, window, the real parts of the context), the time of each stage,
and what the page files must keep (one header made once and changed in place, tabs in five groups, one shared widget for the stage strip and its card, a message for each text)."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import support  # noqa: F401 - puts the engine on the path

from core import copilot_events, messages
from modules.task import chatctx, taskhtml, taskstages, vslink

WEB = taskhtml.WEB


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def turn(model: str = "", level: str = "", usage: dict | None = None) -> dict:
    message = {"text": "go"}
    if model or level:
        message["model"] = {k: v for k, v in (("id", model), ("config", {"thinkingLevel": level} if level else None)) if v}
    return {"id": "t", "message": message, "usage": usage}


class FusionTests(unittest.TestCase):
    def test_the_newest_message_that_named_a_model_says_it(self) -> None:
        fusion = {"turns": [{"id": "t", "message": {"text": "go", "model": {"id": "auto", "config": {"tier": "balance"}}}}]}
        self.assertEqual(chatctx.fusion(fusion), "balance")
        self.assertEqual(chatctx.fusion({"turns": fusion["turns"] + [turn()]}), "balance")  # a message with no model keeps the last one
        self.assertIsNone(chatctx.fusion({"turns": fusion["turns"] + [turn("m")]}))
        self.assertEqual(chatctx.fusion({"turns": [turn("auto")]}), "")  # Fusion at no named tier
        self.assertIsNone(chatctx.fusion({"turns": []}))


class EffortTests(unittest.TestCase):
    def test_the_level_is_what_the_newest_message_that_carried_one_said(self) -> None:
        self.assertEqual(chatctx.effort({"turns": [turn("m", "low"), turn("m", "high")]}, "m"), "high")
        self.assertEqual(chatctx.effort({"turns": [turn("m", "low")], "activeTurn": turn("m", "max")}, "m"), "max")  # the turn that runs is the newest

    def test_a_message_with_no_model_is_skipped_and_one_that_names_a_model_without_a_level_ends_the_search(self) -> None:
        self.assertEqual(chatctx.effort({"turns": [turn("m", "low"), turn()]}, "m"), "low")  # typed in VS Code with no model: the level of the board's message stands
        self.assertIsNone(chatctx.effort({"turns": [turn("m", "low"), turn("m")]}, "m"))  # a later message named the model with no level: its own default, not known

    def test_a_level_given_for_another_model_is_not_the_one_that_ran(self) -> None:
        self.assertIsNone(chatctx.effort({"turns": [turn("other", "high")]}, "m"))
        self.assertEqual(chatctx.effort({"turns": [turn("m", "high")]}, ""), "high")  # no model known: nothing to compare

    def test_nothing_known_is_none_never_a_made_up_value(self) -> None:
        for chat in ({}, {"turns": []}, {"turns": [turn()]}, {"turns": [{"id": "t"}]}, {"turns": [turn("m", "  ")]}, {"turns": "x"}):
            with self.subTest(chat):
                self.assertIsNone(chatctx.effort(chat, "m"))

    def test_a_level_read_back_from_copilots_record_counts_too(self) -> None:
        self.assertEqual(chatctx.effort({"turns": [{"id": "t", "message": {"model": {"id": "m", "config": {"reasoningEffort": "medium"}}}}]}, "m"), "medium")


class LinkTests(unittest.TestCase):
    def link(self, state: dict) -> vslink.VsLink:
        with tempfile.TemporaryDirectory() as folder:
            link = vslink.VsLink(Path(folder), enabled=False)
        link.ready = True
        link.bound = {"t": {"session": "s", "chat": "c", "how": "hook"}}
        link.sessions = {"s": {"title": "A chat", "status": "idle"}}
        link.chats = {"c": {"state": state}}
        link.limits = {"m": {"window": 200000}}
        return link

    def test_a_row_carries_the_effort_the_window_and_the_meter(self) -> None:
        state = {"turns": [dict(turn("m", "high"), usage={"model": "m", "inputTokens": 50000, "outputTokens": 1000})]}
        out = self.link(state).chat_of("t")
        self.assertEqual((out["model"], out["effort"], out["window"], out["context"]["percent"]), ("m", "high", 200000, 25.5))

    def test_unknown_stays_none(self) -> None:
        out = self.link({"turns": [turn(usage={"model": "other", "inputTokens": 1, "outputTokens": 1})]}).chat_of("t")
        self.assertIsNone(out["effort"])
        self.assertIsNone(out["window"])
        self.assertIsNone(out["context"])

    def test_the_card_of_a_chat_comes_from_its_state(self) -> None:
        link = self.link({"turns": [dict(turn("m"), usage={"model": "m", "inputTokens": 50000, "outputTokens": 1000, "_meta": {"contextAttribution": {"totalTokens": 10, "entries": [{"kind": "system", "id": "systemPrompt", "tokens": 10}]}, "copilotUsage": {"sessionTotalNanoAiu": 2e9}}})]})
        found = link.context_card("t")
        self.assertEqual((found["parts"][0]["key"], found["parts"][0]["percent"], found["cost"]), ("system", 25.5, 2.0))
        self.assertEqual(link.context_card("nobody"), {"parts": None, "cost": None})  # a task with no chat has none


class TimingTests(unittest.TestCase):
    def data(self, **more: object) -> dict:
        events = [{"at": at, "round": 1, "what": what, "detail": ""} for at, what in (
            ("2026-10-31T10:01:00+00:00", "confirm-req"), ("2026-10-31T10:07:00+00:00", "approve-plan"), ("2026-10-31T11:30:00+00:00", "approve-promote"))]
        return dict({"round": 1, "created_at": "2026-10-31T10:00:00+00:00", "events": events}, **more)

    def steps(self, *states: str) -> dict:
        ids = ["requirement", "plan", "developing", "writeback", "done"]
        return {"steps": [{"id": ids[index], "state": state, "flag": ""} for index, state in enumerate(states)]}

    def test_a_done_step_has_its_length_and_the_one_that_is_now_has_where_it_began(self) -> None:
        found = self.steps("done", "done", "done", "now", "todo")
        taskstages.with_timing(found, self.data())
        self.assertEqual([step.get("s") for step in found["steps"]], [60.0, 360.0, 4980.0, None, None])
        self.assertTrue(found["steps"][3]["since"].startswith("2026-10-31T11:30:00"))
        self.assertNotIn("since", found["steps"][0])

    def test_time_aside_is_not_part_of_a_step(self) -> None:
        pause = [{"at": "2026-10-31T10:04:00+00:00", "round": 1, "what": "pause", "detail": ""}, {"at": "2026-10-31T10:04:50+00:00", "round": 1, "what": "unpause", "detail": ""}]
        plain = self.data()
        data = self.data(events=sorted(plain["events"] + pause, key=lambda event: event["at"]))
        found = self.steps("done", "done", "done", "now", "todo")
        taskstages.with_timing(found, data)
        self.assertEqual([step.get("s") for step in found["steps"]], [60.0, 310.0, 4980.0, None, None])

    def test_a_step_of_a_task_put_aside_stands_still(self) -> None:
        """Seen on the page: the stage card kept counting and said 18 s more than the card of waits, which was the time of an Off work."""
        plain = self.data()
        began = plain["events"][-1]["at"]
        later = (datetime.fromisoformat(began) + timedelta(minutes=2)).isoformat()
        data = self.data(events=plain["events"] + [{"at": later, "round": 1, "what": "pause", "detail": ""}])
        found = self.steps("done", "done", "done", "now", "todo")
        taskstages.with_timing(found, data)
        self.assertNotIn("since", found["steps"][3])
        self.assertEqual(found["steps"][3]["s"], 120.0)

    def test_a_step_with_an_end_missing_has_no_time_and_nothing_is_guessed(self) -> None:
        found = self.steps("done", "done", "now", "todo", "todo")
        taskstages.with_timing(found, self.data(events=[]))  # the history was cut
        for step in found["steps"]:
            self.assertNotIn("s", step)
            self.assertNotIn("since", step)

    def test_a_later_round_counts_from_its_own_start(self) -> None:
        data = self.data(round=2, events=[{"at": "2026-10-31T12:00:00+00:00", "round": 2, "what": "new-round", "detail": ""}, {"at": "2026-10-31T12:05:00+00:00", "round": 2, "what": "approve-plan", "detail": ""}])
        found = self.steps("done", "now", "todo", "todo", "todo")
        taskstages.with_timing(found, data)
        self.assertEqual(found["steps"][0].get("s"), 300.0)  # no confirm-req in this round: the plan's approval ends the step

    def test_the_board_rows_do_not_pay_for_it(self) -> None:
        self.assertIn("timing: bool = False", Path(taskstages.__file__).read_text(encoding="utf-8"))
        self.assertIn("timing=True", (Path(taskstages.__file__).parent / "taskdesk.py").read_text(encoding="utf-8"))


class PageFileTests(unittest.TestCase):
    def pages(self):
        served = taskhtml.desk_page({"name": "a", "task": "t"}, {"actions": [], "refresh": 10})
        saved = taskhtml.desk_page({"name": "a", "task": "t"}, None)
        return served, saved

    def test_the_shared_widget_is_before_the_page_and_the_shell_style_after_the_rest(self) -> None:
        for page in self.pages():
            self.assertLess(page.index("const Status = (function"), page.index("const GROUPS = ["))
            self.assertLess(page.index(".st-row{display:flex"), page.index(".tk-head{position:sticky"))
            self.assertLess(page.index("/* The controls fixed to the browser window"), page.index(".tk-head{position:sticky"))
        served, saved = self.pages()
        self.assertIn("const CHAT = (function", served)
        self.assertNotIn("const CHAT = (function", saved)  # a saved copy has nothing that talks to a server

    def test_the_tabs_are_in_five_groups_and_each_of_the_16_is_in_one(self) -> None:
        desk = source("desk.js")
        block = desk[desk.index("const GROUPS = ["):desk.index("const tabs = ")]
        groups = re.findall(r'\{id: "(\w+)", tabs: \[([^\]]*)\]\}', block)
        self.assertEqual([name for name, _tabs in groups], ["live", "overview", "deliver", "records", "files"])
        listed = [tab for _name, tabs in groups for tab in re.findall(r'"(\w+)"', tabs)]
        self.assertEqual(len(listed), 16)
        self.assertEqual(len(set(listed)), 16)
        self.assertEqual(dict((name, re.findall(r'"(\w+)"', tabs)) for name, tabs in groups)["overview"], ["overview", "req", "intake", "design", "rca", "plan", "todo"])
        self.assertEqual(dict((name, re.findall(r'"(\w+)"', tabs)) for name, tabs in groups)["deliver"], ["changes", "test", "review"])
        for tab in listed:
            for table in (messages.table("en"), messages.table("zh")):
                self.assertIn("desk.tab." + tab, table)
        self.assertIn("if (tab === \"live\") return served()", desk)
        self.assertIn("lastTab[group.id]", desk)  # a group goes back to the tab it was left on
        self.assertIn("JUMPS", desk)

    def test_the_header_is_made_once_and_changed_in_place(self) -> None:
        desk = source("desk.js")
        self.assertEqual(desk.count("function shell() {"), 1)
        self.assertIn("if (ui.root) return;", desk)
        self.assertNotIn("app.replaceChildren(...[...header()", desk)
        self.assertIn("Status.refresh();", desk)  # an open card is filled again only if its data changed
        for name in ("stage", "checks", "ctx", "state"):
            self.assertIn("ui." + name + ".set(", desk)

    def test_the_old_chat_bars_and_ribbon_are_gone_but_every_button_has_a_place(self) -> None:
        desk = source("desk.js")
        for gone in ("function chatBars()", "function lane(", "function ribbon()", "function contextMeter("):
            self.assertNotIn(gone, desk)
        for kept in ("function settingsRow()", "function draftsBox()", "function resultForm()", "function roundSwitch()", "copyTitleButton(", "askCompact", "SERVE.vsButton(", "SHELL.vsPill(", "/snapshot/", "desk.report",
                     "TALK.includes(item.action)", "OPTIONAL.includes(entry.action)", "SERVE.banner(true)"):
            self.assertIn(kept, desk)

    def test_the_strong_cards_name_a_tab_each_and_the_confirm_card_has_no_word_about_a_code(self) -> None:
        desk = source("desk.js")
        self.assertIn('{"approve-plan": "plan", "confirm-req": "req", "approve-promote": "changes"}', desk)
        for key in ("plan", "req", "changes", "live"):
            for language in ("en", "zh"):
                self.assertIn("desk.jump." + key, messages.table(language))
        self.assertNotIn("code", messages.table("en")["desk.paired.short"].lower())
        self.assertIn('markShort ? "desk.paired.short"', source("serve.js"))

    def test_the_status_part_has_the_card_and_still_one_timer(self) -> None:
        status = source("status.js")
        self.assertEqual(status.count("setInterval("), 1)
        self.assertNotIn("innerHTML", status + source("desk.js"))
        for name in ("function card(", "function stageCard(", "function checks(", "function refresh()"):
            self.assertIn(name, status)
        self.assertIn("return {row: build, stages, ribbon, stageList, stageCard, checks, card, refresh,", status)
        self.assertIn('fail: "fail"', status)  # a failed check is red with a cross, not the amber of a flag
        self.assertIn('if (again) lines.push(h("div", {class: "sub"}, t("stage.again")));', status)  # a plan asked for a second time says why
        self.assertIn('step.id === "plan" && step.state === "now") && desk.history.some((event) => event.what === "approve-plan")', source("desk.js"))
        css = source("status.css") + source("desk.css")
        for rule in (".st-d.k-fail", ".st-checks", ".st-card", ".st-ribbon .st-l.is-flow::after"):
            self.assertIn(rule, css)

    def test_the_motion_of_the_strip_is_off_under_lite_and_reduced_motion(self) -> None:
        self.assertIn("html.lite *", source("shell.css"))
        self.assertRegex(source("status.css"), r"prefers-reduced-motion:reduce\)\{[^}]*\.st-ribbon \.st-l::after")
        self.assertIn("prefers-reduced-motion:reduce", source("ui.css"))

    def test_the_palette_lists_every_tab_with_its_group(self) -> None:
        shell, desk = source("shell.js"), source("desk.js")
        self.assertIn('(tab.group ? " \\u00b7 " + tab.group : "")', shell)
        self.assertIn("tabs: tabs.filter(visible)", desk)
        self.assertIn("run: () => goTab(tab)", desk)

    def test_a_text_is_in_both_languages_for_every_literal_key_of_the_files_changed(self) -> None:
        table = {language: messages.table(language) for language in ("en", "zh")}
        for name in ("desk.js", "status.js", "shell.js"):
            for key in sorted(set(re.findall(r'\bt\("((?:desk|board|stage|task|unit)\.[a-z0-9_.-]+)"[,)]', source(name)))):
                for language in ("en", "zh"):
                    self.assertIn(key, table[language], f"{name}: {key} ({language})")

    def test_a_saved_copy_does_not_count_a_running_time_on(self) -> None:
        self.assertIn("if (saved && found)", source("desk.js"))

    def test_the_old_ribbon_style_stays_for_the_report_page_and_nothing_new_hides_behind_the_gear(self) -> None:
        self.assertIn(".rb-ribbon{", source("page.css"))
        self.assertIn("main.wide", source("shell.css"))


if __name__ == "__main__":
    unittest.main()
