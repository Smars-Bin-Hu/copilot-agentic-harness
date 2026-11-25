"""New task, second round (1.6.18, B88b): the knowledge base choice of the dialog, the first-task block of an empty board, the preview without placeholders typed by hand,
the language names of the settings panel without Chinese in a page file, and Cmd+K from inside a box. The pages are checked as files (no browser here); the server side is in test_chatnew."""

from __future__ import annotations

import json
import re
import unittest

import support  # noqa: F401 - puts the engine on the path

from core import messages, tasks
from modules.task import taskhtml

WEB = taskhtml.WEB
HAN = re.compile(r"[一-鿿]")


def source(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class DialogTests(unittest.TestCase):
    def test_a_notice_does_not_stop_the_page_under_it(self) -> None:
        serve = source("serve.js")
        self.assertIn("function dialog(children, informs)", serve)
        self.assertIn("busy = stack.some((item) => !quiet.has(item))", serve)
        self.assertIn("inform: () =>", serve)
        self.assertIn('h("div", {class: "row"}, close)], true);', source("dock.js"))  # Started in VS Code only tells
        self.assertIn("view.inform();", source("chat.js"))  # the New task box once sent

    def test_the_new_task_notice_shows_the_task_when_the_board_brings_it(self) -> None:
        chat, board = source("chat.js"), source("board.js")
        self.assertIn("function seen(rows)", chat)
        self.assertIn("create, seen,", chat)
        self.assertIn('"/task/" + encodeURIComponent(name)', chat)
        self.assertIn("CHAT.seen(data.rows)", board)  # the board's own read, no new poll
        for lang in ("en", "zh"):
            table = json.loads((WEB.parents[2] / "core" / f"messages.{lang}.json").read_text(encoding="utf-8"))
            self.assertIn("board.new.here", table)
            self.assertIn("board.new.open", table)

    def test_the_dialog_asks_for_the_domains_and_sends_them_with_every_step(self) -> None:
        chat = source("chat.js")
        create = chat.split("function create(preset)")[1].split("// \"Allow . deny\"")[0]
        self.assertIn("domains: Array.from(state.domains)", create)  # preview and act take the same body: the server checks it again
        self.assertIn("state.domainList = Array.isArray(found.domains) ? found.domains : [];", create)
        self.assertIn("board.new.kb.none", create)  # none is a choice of its own
        self.assertIn("board.new.kb.empty", create)  # no domain: it says so
        draw = create.split("function drawKb()")[1].split("const sync = ")[0]
        self.assertIn("if (!list.length)", draw)
        self.assertNotIn("go.disabled", draw)  # nothing about the knowledge base blocks the dialog
        self.assertIn("title: full || label", draw)  # a long name is cut by CSS and shown whole on hover

    def test_the_preview_is_the_servers_text_and_is_not_a_field(self) -> None:
        create = source("chat.js").split("function create(preset)")[1].split("// \"Allow . deny\"")[0]
        self.assertIn('const preview = h("pre", {class: "send-preview"}', create)  # a <pre>: read only
        self.assertIn("preview.textContent = found.text + (found.then ? ", create)  # the second message a skill gets (1.8.2) is the server's too
        self.assertIn("state.ready = !found.blocked && !found.problem;", create)
        self.assertNotRegex(create, r"preview\.(contentEditable|setAttribute\(\"contenteditable)")
        self.assertNotIn("first_message", create)  # no second template in the page
        self.assertNotIn("Task name:", create)

    def test_the_buttons_stay_in_view_and_the_chips_are_cut(self) -> None:
        css = source("page.css")
        self.assertRegex(css, r"\.dialog \.new-actions\{position:sticky;bottom:-18px")
        self.assertIn(".new-kb .kb-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}", css)
        self.assertIn("max-height:98px;overflow:auto", css)  # many domains scroll inside their box
        create = source("chat.js").split("function create(preset)")[1]
        self.assertLess(create.index("h(\"div\", {class: \"new-actions\"}, problem, said, h(\"div\", {class: \"row send-actions\"}"), create.index("const body = (step)"))

    def test_every_literal_key_of_the_new_pieces_is_in_both_languages(self) -> None:
        en, zh = messages.table("en"), messages.table("zh")
        keys = set()
        for name in ("chat.js", "board.js", "shell.js"):
            keys |= set(re.findall(r't\("((?:board\.new\.kb|board\.empty|board\.new\.first|desk\.send\.lang\.name)[a-z.]*)"', source(name)))
        self.assertGreaterEqual(len(keys), 8)
        for key in sorted(keys):
            self.assertIn(key, en, key)
            self.assertIn(key, zh, key)
        self.assertIn("create.refused.domain", en)
        self.assertEqual(en["desk.send.lang.name.en"], zh["desk.send.lang.name.en"])
        self.assertEqual(en["desk.send.lang.name.zh"], zh["desk.send.lang.name.zh"])


class EmptyBoardTests(unittest.TestCase):
    def test_no_task_gets_the_big_button_in_the_list_and_the_lobby_and_a_file_on_disk_gets_the_way_to_serve(self) -> None:
        board, lobby = source("board.js"), source("lobby.js")
        first = board.split("function bigNewTask()")[1].split("// The pill that says")[0]
        self.assertIn('SERVE.runs("create")', first)
        self.assertIn("class: \"act hot live first-go new-task\"", first)  # the button shows even when VS Code is not linked: the dialog says why
        self.assertNotIn("vscode.ready", first)
        self.assertIn('t("board.empty.disk", {command: cli + " task board"})', first)  # a file on disk: no button
        self.assertIn("tableBox.replaceChildren(firstTask())", board)
        self.assertIn("first: firstTask", board)
        self.assertIn("rows.length ? newTask() : null", board)  # with tasks the header button stays; with none only the big one
        self.assertIn('typeof options.first === "function"', lobby)
        self.assertIn("!rows.length", lobby)

    def test_the_empty_block_has_the_one_new_task_button_and_no_sample_or_lesson(self) -> None:  # 1.8.32
        board = source("board.js")
        block = board.split("function firstTask()")[1].split("// The pill that says")[0]
        self.assertIn("bigNewTask()", block)
        self.assertNotIn("board.empty.sample", board)
        self.assertNotIn("board.empty.lesson", board)
        self.assertNotIn("board.empty.own", board)
        self.assertNotIn("lessonLink", board)
        self.assertNotIn("first-link", block)
        self.assertNotIn("first-row", block)
        self.assertNotIn("CHAT.create(true)", block)
        self.assertIn('t("board.new")', board.split("function bigNewTask()")[1].split("function firstTask()")[0])  # the header's label
        for lang in ("en", "zh"):
            keys = json.loads((WEB.parents[2] / "core" / f"messages.{lang}.json").read_text(encoding="utf-8"))
            for gone in ("board.empty.sample", "board.empty.lesson", "board.empty.own"):
                self.assertNotIn(gone, keys)

    def test_the_lobby_with_only_closed_tasks_keeps_its_quiet_sentence(self) -> None:
        lobby = source("lobby.js")
        self.assertIn('t(go ? "board.lobby.quiet" : "board.lobby.quiet.disk")', lobby)  # with the big button; a page on disk has none
        self.assertIn("go: bigNewTask", source("board.js"))
        self.assertIn('data-kind', lobby)

    def test_the_block_wraps_long_text(self) -> None:
        css = source("page.css")
        self.assertIn(".first-task{display:flex;flex-direction:column;align-items:center", css)
        self.assertIn("overflow-wrap:anywhere", css.split(".first-task h2")[1])


class KeyAndLanguageTests(unittest.TestCase):
    def test_cmd_k_opens_the_palette_from_inside_a_box(self) -> None:
        shell = source("shell.js")
        key = shell.split('document.addEventListener("keydown"')[1].split("if (open()) {")[0]
        self.assertIn("(event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey", key)
        self.assertNotIn("INPUT", key)
        self.assertNotIn("isContentEditable", key)

    def test_the_plain_r_key_stays_off_in_a_box(self) -> None:
        reply = source("reply.js")
        self.assertIn("if (typing(event.target) || SERVE.open()", reply)  # a notice does not stop the refresh (busy), but the key still waits for it (1.6.112)
        self.assertIn("open: () => stack.length > 0", source("serve.js"))

    def test_open_task_keeps_the_name_it_was_made_for(self) -> None:
        """Open task read `waiting.name` at the click, after `seen` had let `waiting` go: the click threw and did nothing (1.6.112, browser test)."""
        seen = source("chat.js").split("function seen(rows)")[1].split("function create(")[0]
        self.assertIn("const name = waiting.name;", seen)
        self.assertNotIn("encodeURIComponent(waiting.name)", seen)

    def test_the_say_something_panel_sits_over_the_dock_and_under_a_dialog(self) -> None:
        """At 390 px the dock's buttons covered Send of the panel (1.6.112, browser test)."""
        layer = lambda css, rule: int(re.search(re.escape(rule) + r"\{[^}]*?z-index:(\d+)", css).group(1))  # noqa: E731
        live, dock, page = source("live.css"), source("dock.css"), source("page.css")
        self.assertGreater(layer(live, ".rp"), layer(dock, ".dock-panel"))
        self.assertLess(layer(live, ".rp"), layer(page, ".shade"))

    def test_no_page_file_holds_chinese_and_the_zh_names_come_from_the_table(self) -> None:
        for path in sorted(WEB.iterdir()):
            if path.is_file() and path.suffix != ".png":
                self.assertFalse(HAN.search(path.read_text(encoding="utf-8")), path.name)
        self.assertIn('t(code === "zh" ? "desk.send.lang.name.zh"', source("wizard.js"))  # 1.8.32: the language is picked in Settings, You (the wizard's page), no longer in the sliders panel

    def test_the_words_that_were_english_in_the_chinese_table_are_chinese_now(self) -> None:
        zh = messages.table("zh")
        for key in ("desk.tab.live", "desk.live.title", "desk.info.effort", "desk.ctx.part.system"):
            self.assertRegex(zh[key], HAN, key)
        self.assertIn("{level}", zh["desk.info.effort"])


class FormStateTests(unittest.TestCase):
    """F3 and F4 of the slow-computer findings: the New task form follows its fields, an old answer never wins, and the selects are never empty or reset."""

    def create(self) -> str:
        return source("chat.js").split("function create(preset)")[1].split("// \"Allow . deny\"")[0]

    def test_f3_an_older_preview_answer_never_overwrites_a_newer_one(self) -> None:
        create = self.create()
        refresh = create.split("function refresh()")[1].split("const close = ")[0]
        self.assertIn("const mine = ++state.seq;", refresh)
        self.assertEqual(refresh.count("if (mine !== state.seq) return;"), 2)  # the answer and the error
        self.assertIn("state.seq++", create.split("const close = ")[1].split("\n")[0])  # a closed dialog takes no answer
        self.assertIn('preview.classList.add("is-pending")', refresh)
        self.assertIn(".send-preview.is-pending", source("space.css"))

    def test_f3_create_follows_the_fields_not_the_last_server_answer(self) -> None:
        create = self.create()
        line = [row for row in create.splitlines() if row.lstrip().startswith("const sync = ")][0]
        for part in ("state.busy", "files.reading()", "!state.options", "!local()", "state.pending"):
            self.assertIn(part, line)
        local = [row for row in create.splitlines() if row.lstrip().startswith("const local = ")][0]
        for part in ("name.value.trim()", "kind.value", "text.value.trim()", "state.skill"):
            self.assertIn(part, local)
        self.assertIn("sync();", create.split("function refresh()")[1].split("state.timer = setTimeout")[0])  # on every keystroke, before the round trip
        click = create.split('go.addEventListener("click"')[1].split('ask("/api/create", {step: "options"})')[0]
        self.assertIn("said.replaceChildren(...SERVE.reasons(shown(error)))", click)  # a refusal of the server is told, never silent
        self.assertIn('...body("act")', click)  # the server still checks everything on Create

    def test_f4_the_kind_list_is_the_engines_and_the_options_answer_leaves_it_alone(self) -> None:
        chat = source("chat.js")
        found = re.search(r"const KINDS = \[([^\]]*)\];", chat)
        self.assertIsNotNone(found)
        self.assertEqual(re.findall(r'"([a-z]+)"', found.group(1)), list(tasks.KINDS))  # same ids, same order
        create = self.create()
        self.assertIn("...KINDS.map(", create.split("const source = ")[0])
        self.assertNotIn("kind.replaceChildren", create)
        self.assertNotIn("found.kinds", create)

    def test_f4_a_late_option_list_fills_without_touching_what_the_person_picked(self) -> None:
        create = self.create()
        fill = create.split("function fill(found)")[1].split("function again()")[0]
        self.assertIn("state.touched.model", fill)
        self.assertIn("had.source", fill)
        self.assertIn("if (first) {", fill)  # chips, domains and the preset are made once
        self.assertIn("state.tries < 20", fill)
        self.assertIn("setTimeout(again, 2000)", fill)
        self.assertIn("remembered()", fill)  # the remembered model is applied when the list holds it
        self.assertIn("clearTimeout(state.retry)", create.split("const close = ")[1].split("\n")[0])
        self.assertIn("board.serve.working", create)  # one "loading" entry in source and model until the answer
        self.assertIn("state.touched.model = true", create)


if __name__ == "__main__":
    unittest.main()
