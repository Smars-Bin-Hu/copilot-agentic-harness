"""The shell of the task page (1.6.16, B87): the facts the server adds for the info line and the context card (thinking effort, window, the real parts of the context), the time of each stage,
and what the page files must keep (one header made once and changed in place, tabs in five groups, one shared widget for the stage strip and its card, a message for each text)."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
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

    def test_the_window_is_the_one_the_host_lists_for_the_model(self) -> None:
        self.assertEqual(chatctx.capacity("a", {"a": 200000}), 200000)
        self.assertIsNone(chatctx.capacity("b", {"a": 200000}))
        self.assertIsNone(chatctx.capacity("", {"": 0}))


def attributed(entries: list, **more: object) -> dict:
    return {"turns": [{"id": "t", "usage": {"model": "m", "inputTokens": 1, "outputTokens": 1, "_meta": {"contextAttribution": {"totalTokens": 1, "entries": entries}}, **more}}]}


class PartsTests(unittest.TestCase):
    def test_system_and_tool_definitions_come_from_the_attribution_of_the_newest_call(self) -> None:
        found = chatctx.parts(attributed([{"kind": "system", "tokens": 14953}, {"kind": "toolDefinition", "tokens": 20000}, {"kind": "toolDefinition", "tokens": 3975}]), None)
        self.assertEqual((found["system"], found["tools"]), (14953, 23975))
        self.assertNotIn("conversation", found)  # there is no number for it: it is left out, not worked out
        self.assertEqual(found["recorded"], [])

    def test_a_child_of_an_entry_is_in_its_parent_and_a_kind_without_a_number_is_not_drawn(self) -> None:
        found = chatctx.parts(attributed([{"kind": "system", "tokens": 100, "id": "s"}, {"kind": "system", "tokens": 60, "parentId": "s"}, {"kind": "skill", "tokens": 500}, {"kind": "mcpServer", "tokens": 70},
                                          {"kind": "toolDefinition", "tokens": 0}]), None)
        self.assertEqual(found, {"system": 100, "recorded": [], "at": ""})  # skills and MCP servers are not parts of this card, and a zero is no number

    def test_the_record_fills_what_the_call_has_not_and_the_call_wins(self) -> None:
        record = {"system": 111, "tools": 222, "conversation": 333, "at": "2026-10-31T22:35:32.135Z"}
        found = chatctx.parts(attributed([{"kind": "system", "tokens": 14953}]), record)
        self.assertEqual((found["system"], found["tools"], found["conversation"]), (14953, 222, 333))
        self.assertEqual(found["recorded"], ["tools", "conversation"])
        self.assertEqual(found["at"], record["at"])
        only = chatctx.parts({}, record)
        self.assertEqual((only["system"], only["recorded"]), (111, ["system", "tools", "conversation"]))

    def test_no_number_anywhere_is_none(self) -> None:
        self.assertIsNone(chatctx.parts({}, None))
        self.assertIsNone(chatctx.parts(attributed([]), {}))
        self.assertIsNone(chatctx.parts(attributed([{"kind": "system", "tokens": "x"}]), None))


def event(kind: str, stamp: str, **data: object) -> str:
    return json.dumps({"type": kind, "timestamp": stamp, "data": data})


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        copilot_events._PARTS.clear()
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "events.jsonl"

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_each_part_keeps_its_newest_number_and_a_zero_is_not_a_number(self) -> None:
        self.path.write_text("\n".join([
            event("session.shutdown", "2026-10-30T10:00:00.000Z", systemTokens=13000, conversationTokens=30000, toolDefinitionsTokens=24000, currentModel="m"),
            event("session.compaction_start", "2026-10-31T10:00:00.000Z", systemTokens=14956, conversationTokens=1488, toolDefinitionsTokens=0, currentTokens=16448),  # the local estimate has no tool definitions
            event("assistant.message", "2026-10-31T10:01:00.000Z", systemTokens=1),
        ]) + "\n", encoding="utf-8")
        found = copilot_events.context_parts(self.path)
        self.assertEqual({key: found[key] for key in ("system", "tools", "conversation")}, {"system": 14956, "tools": 24000, "conversation": 1488})
        self.assertEqual(found["at"], "2026-10-31T10:00:00.000Z")

    def test_a_file_with_nothing_to_say_and_a_missing_file_give_none(self) -> None:
        self.assertIsNone(copilot_events.context_parts(self.path))
        self.path.write_text(event("session.shutdown", "2026-10-30T10:00:00.000Z", systemTokens=0) + "\nnot json\n", encoding="utf-8")
        self.assertIsNone(copilot_events.context_parts(self.path))

    def test_the_file_is_read_again_only_when_its_size_changed(self) -> None:
        self.path.write_text(event("session.shutdown", "2026-10-30T10:00:00.000Z", systemTokens=5) + "\n", encoding="utf-8")
        with mock.patch.object(copilot_events.json, "loads", wraps=json.loads) as reads:
            first = copilot_events.context_parts(self.path)
            for _ in range(5):  # the page asks every 10 seconds
                self.assertEqual(copilot_events.context_parts(self.path), first)
            self.assertEqual(reads.call_count, 1)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event("session.shutdown", "2026-10-31T10:00:00.000Z", systemTokens=9) + "\n")
            self.assertEqual(copilot_events.context_parts(self.path)["system"], 9)
            self.assertEqual(reads.call_count, 3)


class LinkTests(unittest.TestCase):
    def link(self, state: dict) -> vslink.VsLink:
        with tempfile.TemporaryDirectory() as folder:
            link = vslink.VsLink(Path(folder), enabled=False)
        link.ready = True
        link.bound = {"t": {"session": "s", "chat": "c", "how": "hook"}}
        link.sessions = {"s": {"title": "A chat", "status": "idle"}}
        link.chats = {"c": {"state": state}}
        link.windows = {"m": 200000}
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

    def test_the_parts_of_a_chat_come_from_its_state_and_the_record_of_its_session(self) -> None:
        link = self.link(attributed([{"kind": "system", "tokens": 7}]))
        with mock.patch.object(copilot_events, "events_path", return_value=Path("x")), mock.patch.object(copilot_events, "context_parts", return_value={"conversation": 9, "at": "a"}):
            found = link.context_parts("t", "sess")
        self.assertEqual((found["system"], found["conversation"], found["recorded"]), (7, 9, ["conversation"]))
        self.assertIsNone(link.context_parts("nobody", "sess"))  # a task with no chat has none
        broken = mock.patch.object(copilot_events, "events_path", side_effect=OSError("no"))
        with broken:
            self.assertEqual(link.context_parts("t", "sess")["system"], 7)  # Copilot's file is not ours: it can fail without hurting the page


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
        self.assertIn('node.dataset.short ? "desk.paired.short"', source("serve.js"))

    def test_the_status_part_has_the_card_and_still_one_timer(self) -> None:
        status = source("status.js")
        self.assertEqual(status.count("setInterval("), 1)
        self.assertNotIn("innerHTML", status + source("desk.js"))
        for name in ("function card(", "function stageCard(", "function checks(", "function refresh()"):
            self.assertIn(name, status)
        self.assertIn("return {row: build, stages, ribbon, stageList, stageCard, checks, card, refresh,", status)
        self.assertIn('fail: "fail"', status)  # a failed check is red with a cross, not the amber of a flag
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
