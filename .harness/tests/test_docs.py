"""README, docs/ and the short commands (B11, M4-11): the documents agree with the code.

Checks: every relative link has a target, no document points at `.local/`, every command a document shows exists (`--help`
runs), every policy field in the reference exists and every top-level field is documented, every hook event and contract is
listed, and the launcher scripts work.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from support import ENGINE, REPO
from test_targets import SYMLINKS

DOCUMENTS = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md")), REPO / ".workspace" / "README.md"]
REFERENCE = REPO / "docs" / "04-reference.md"
LINK = re.compile(r"\]\(([^)\s]+)\)")
LOCAL_FOLDER = re.compile(r"(?<![~\w])\.local/")
SUBCOMMANDS = {"level", "request", "target", "logs", "eval", "brief", "attempt", "handoff", "admin"}
CLI = ENGINE / "cli.py"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def spans(content: str) -> List[str]:
    """Code: every fenced block line and every inline `code` span."""
    found: List[str] = []
    fenced = False
    for line in content.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            found.append(line.strip())
        else:
            found.extend(re.findall(r"`([^`]+)`", line))
    return found


def command_words(span: str) -> List[str]:
    """The command (and sub-command) after `cli.py`, `<cli>` or `harness`, or []."""
    match = re.search(r"(?:\.harness[/\\]engine[/\\]cli\.py|<cli>|(?:^|[\s/\\])harness(?:\.cmd)?)\s+([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?", span)
    if not match:
        return []
    words = [match.group(1)]
    if match.group(2) and words[0] in SUBCOMMANDS:
        words.append(match.group(2))
    return words


def runs(words: List[str]) -> bool:
    done = subprocess.run([sys.executable, str(CLI), *words, "--help"], capture_output=True, text=True)
    return done.returncode == 0


def section(content: str, title: str) -> str:
    start = content.index(f"## {title}")
    nxt = re.search(r"^## ", content[start + 3:], re.M)
    return content[start: start + 3 + nxt.start()] if nxt else content[start:]


class LinkTests(unittest.TestCase):
    def test_every_relative_link_has_a_target(self) -> None:
        broken: List[str] = []
        for document in DOCUMENTS:
            for target in LINK.findall(text(document)):
                if re.match(r"^(?:[a-z]+:|#)", target):
                    continue
                path = target.split("#", 1)[0]
                if path and not (document.parent / path).exists():
                    broken.append(f"{document.relative_to(REPO)} -> {target}")
        self.assertEqual(broken, [])

    def test_documents_do_not_point_at_the_local_folder(self) -> None:
        for document in DOCUMENTS:
            with self.subTest(document.name):
                self.assertIsNone(LOCAL_FOLDER.search(text(document)))

    def test_the_readme_links_every_doc(self) -> None:
        readme = text(REPO / "README.md")
        for doc in (REPO / "docs").glob("*.md"):
            self.assertTrue(f"docs/{doc.name}" in readme, doc.name)

    def test_the_twelve_docs_exist(self) -> None:
        names = sorted(item.name for item in (REPO / "docs").glob("*.md"))
        self.assertEqual(len(names), 12, names)


class InitializeSkillTests(unittest.TestCase):
    """The CLI prints UTF-8 on a Windows pipe by itself. The skill only acts when that reads as garbage: it writes `native`."""

    def steps(self) -> Dict[str, str]:
        skill = text(REPO / ".github" / "skills" / "harness-rookie-get-me-ready" / "SKILL.md")
        body = skill[skill.index("## Step-by-Step Workflows"):skill.index("## Gotchas")]
        return {number: chunk for number, chunk in re.findall(r"^(\d)\. (.+?)(?=^\d\. |\Z)", body, re.M | re.S)}

    def test_step_9_does_nothing_when_the_sample_line_reads_fine_and_writes_native_when_it_is_garbage(self) -> None:
        check = self.steps()["9"]
        self.assertIn("the sample line of Chinese", check)
        self.assertIn("If you can read it, do nothing", check)
        self.assertIn("If it is garbage, write `.harness/policies/cli.override.json` yourself", check)
        self.assertIn("run `harness doctor` once more", check)

    def test_step_8_does_not_ask_the_user_about_the_encoding(self) -> None:
        step = self.steps()["8"]
        self.assertIn("Do not ask the user about Chinese text", step)
        self.assertNotIn("Two common ones", step)

    def test_the_json_the_skill_tells_the_agent_to_write_is_what_doctor_accepts(self) -> None:
        written = json.loads(re.search(r"`(\{\"output\": \{\"encoding\": \"native\"\}\})`", self.steps()["9"]).group(1))
        sys.path.insert(0, str(ENGINE))
        try:
            from core import output
        finally:
            sys.path.remove(str(ENGINE))
        self.assertEqual(written["output"]["encoding"], output.NATIVE)

    def test_the_overrides_that_are_about_this_machine_are_ignored_by_git(self) -> None:
        ignored = text(REPO / ".gitignore").splitlines()
        for name in ("target", "user", "cli"):
            self.assertIn(f".harness/policies/{name}.override.json", ignored, name)

    def test_step_1_on_windows_checks_the_path_that_stays_and_not_only_the_one_of_this_window(self) -> None:
        """Windows round, W13: VS Code kept a PATH the person had removed, and the skill said the command was set up."""
        step = self.steps()["1"]
        self.assertIn("(Get-Command harness).Source", step)
        self.assertIn('[Environment]::GetEnvironmentVariable("Path", "User")', step)


class RequirementConfirmedTests(unittest.TestCase):
    """Only the person fills in the "用户确认" line of REQ.md. Every file that speaks of it says the same."""

    def test_no_file_tells_the_agent_to_fill_it_in(self) -> None:
        self.assertIn("Only the user may change the confirmation line of `REQ.md`", text(REPO / "AGENTS.md"))
        walk = text(REPO / ".github" / "skills" / "harness-rookie-quick-start" / "references" / "walkthrough.md")
        self.assertIn("press **confirm requirement** on the page and type the code", walk)
        self.assertIn("the harness fills the confirmation line, and you never do", walk)

    def test_the_reviewer_does_not_fail_a_task_over_it(self) -> None:
        self.assertIn("An empty confirmation line in `REQ.md` is not a finding", text(REPO / ".github" / "agents" / "reviewer.agent.md"))
        self.assertIn("the review package tells the reviewer to treat the requirement as \"to be confirmed\"", text(REPO / "AGENTS.md"))


class ReadmeStructureTests(unittest.TestCase):
    def test_the_readme_introduces_gets_the_reader_started_and_points_at_the_docs(self) -> None:
        readme = text(REPO / "README.md")
        self.assertTrue(readme.startswith("# GitHub Copilot Agentic Harness on VS Code\n"))
        self.assertEqual(re.findall(r"^## (.+)$", readme, re.M), ["What you get", "What it is", "Get started", "What it does", "See it", "What you must plug in", "Docs", "Directory layout", "License"])
        start = section(readme, "Get started")
        for skill in ("harness-rookie-get-me-ready", "harness-rookie-quick-start", "harness-rookie-wondering"):
            self.assertIn(f"`/{skill}`", start, skill)
            self.assertTrue((REPO / ".github" / "skills" / skill / "SKILL.md").is_file(), skill)
        self.assertIn("What the harness does", section(readme, "What it does"))

    def test_the_readme_shows_the_version_of_the_registry(self) -> None:
        readme = text(REPO / "README.md")
        version = json.loads(text(REPO / ".harness" / "registry.json"))["version"]
        self.assertIn(f"badge/version-{version}-", readme)
        self.assertIn(f"Version {version} ·", readme)
        self.assertIn(f"## {version} (", text(REPO / "docs" / "07-release-notes.md"))

    def test_the_readme_has_the_directory_tree_with_both_parts(self) -> None:
        readme = text(REPO / "README.md")
        tree = readme[readme.index("## Directory layout"):]
        for needle in ("knowledge-base/", "knowledgebase.instructions.md", ".harness/", "engine/", ".workspace/", "repos_root", "Outside the harness"):
            self.assertIn(needle, tree, needle)

    def test_the_knowledge_base_instructions_must_be_connected_and_are_not_hidden(self) -> None:
        readme = text(REPO / "README.md")
        self.assertIn("(.github/instructions/knowledgebase.instructions.md)", readme)
        self.assertIn("must be plugged in", readme[readme.index("## What you must plug in"):])
        configure = text(REPO / "docs" / "03-configure.md")
        self.assertIn("must be plugged in", section(configure, "Knowledge base"))
        self.assertTrue((REPO / ".github" / "instructions" / "knowledgebase.instructions.md").is_file())


class PathIndexTests(unittest.TestCase):
    """The path index is the agent's map. It lives outside the README, so finding a file does not load the introduction."""

    INDEX = REPO / ".harness" / "INDEX.md"

    def paths(self) -> List[str]:
        found = []
        for line in text(self.INDEX).splitlines():
            if line.startswith("| `"):
                found.append(re.match(r"\| `([^`]+)`", line).group(1))
        return found

    def test_every_indexed_path_exists(self) -> None:
        paths = self.paths()
        self.assertGreater(len(paths), 15)
        self.assertEqual([path for path in paths if not (REPO / path).exists()], [])

    def test_every_shipped_skill_and_harness_folder_is_indexed(self) -> None:
        index = text(self.INDEX)
        for skill in sorted((REPO / ".github" / "skills").glob("harness-*")):
            self.assertIn(f"`.github/skills/{skill.name}/`", index, skill.name)
        for folder in ("engine", "policies", "contracts", "bin", "eval", "tests"):
            self.assertIn(f"`.harness/{folder}/`", index, folder)

    def test_agents_md_points_at_the_index_and_the_readme_holds_no_copy(self) -> None:
        self.assertIn("(.harness/INDEX.md)", text(REPO / "AGENTS.md"))
        readme = text(REPO / "README.md")
        self.assertIn("(.harness/INDEX.md)", readme)
        self.assertNotIn("## Path index", readme)


class CommandTests(unittest.TestCase):
    def test_every_command_a_document_shows_runs(self) -> None:
        wanted: Dict[Tuple[str, ...], str] = {}
        for document in DOCUMENTS:
            for span in spans(text(document)):
                words = command_words(span)
                if words:
                    wanted.setdefault(tuple(words), document.name)
        self.assertGreater(len(wanted), 5)
        missing = [f"{' '.join(words)} (in {name})" for words, name in sorted(wanted.items()) if not runs(list(words))]
        self.assertEqual(missing, [])

    def test_the_command_tables_of_the_reference_list_real_commands(self) -> None:
        listed: Set[Tuple[str, ...]] = set()
        for title in ("Commands",):
            for line in section(text(REFERENCE), title).splitlines():
                if line.startswith("|"):
                    first = line.split("|")[1]
                    for item in re.findall(r"`([^`]+)`", first):
                        listed.add(tuple(item.split()))
        self.assertGreater(len(listed), 20)
        for words in sorted(listed):
            with self.subTest(" ".join(words)):
                self.assertTrue(runs(list(words)))

    def test_every_top_level_command_is_listed_in_the_reference(self) -> None:
        done = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True)
        names = re.search(r"\{([^}]+)\}", done.stdout).group(1).split(",")
        reference = text(REFERENCE)
        missing = [name for name in names if not re.search(rf"`{re.escape(name)}[ `]", reference)]
        self.assertEqual(missing, [])


def dotted(data: dict, path: str) -> bool:
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


class PolicyFieldTests(unittest.TestCase):
    def rows(self) -> List[Tuple[str, str]]:
        found = []
        for line in section(text(REFERENCE), "Policy fields").splitlines():
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if len(cells) >= 2 and cells[0].endswith(".json"):
                found.append((cells[0], cells[1].strip("`")))
        return found

    def test_every_documented_field_exists(self) -> None:
        rows = self.rows()
        self.assertGreater(len(rows), 25)
        for name, path in rows:
            with self.subTest(f"{name} {path}"):
                data = json.loads(text(REPO / ".harness" / "policies" / name))
                self.assertTrue(dotted(data, path))

    def test_every_top_level_field_is_documented(self) -> None:
        documented: Dict[str, Set[str]] = {}
        for name, path in self.rows():
            documented.setdefault(name, set()).add(path.split(".")[0])
        for policy in sorted((REPO / ".harness" / "policies").glob("*.json")):
            if policy.name.endswith(".override.json"):
                continue
            keys = set(json.loads(text(policy))) - {"schema_version", "description"}
            with self.subTest(policy.name):
                self.assertEqual(sorted(keys - documented.get(policy.name, set())), [])


class ReferenceCoverageTests(unittest.TestCase):
    def test_every_hook_event_is_listed(self) -> None:
        events = json.loads(text(REPO / ".github" / "hooks" / "harness.json"))["hooks"]
        reference = section(text(REFERENCE), "Hook events")
        for event in events:
            self.assertIn(f"`{event}`", reference, event)

    def test_every_task_template_is_listed(self) -> None:
        reference = section(text(REFERENCE), "Templates (contracts)")
        templates = sorted(path.name for path in (REPO / ".harness" / "contracts" / "templates" / "task" / "en").glob("*.md"))
        self.assertEqual(templates, ["INTAKE.md", "LOG.md", "REQ.md", "TASK.md", "TODO.md"])
        for name in templates:
            self.assertIn(f"`{name}`", reference)

    def test_every_guardrail_the_features_doc_names_is_a_guardrail(self) -> None:
        policy = json.loads(text(REPO / ".harness" / "policies" / "gate.json"))
        features = text(REPO / "docs" / "02-features.md")
        for path in policy["guardrail_paths"]:
            shown = path[:-3] if path.endswith("/**") else path
            self.assertIn(shown, features, path)


def shell_command(launcher: Path) -> Optional[List[str]]:
    """The command that runs a shell launcher. macOS and Linux run the file itself. Windows cannot, so it runs under the
    bash that comes with Git for Windows (found next to git). None when that bash is not installed."""
    if os.name != "nt":
        return [str(launcher)]
    git = shutil.which("git")
    bash = Path(git).resolve().parents[1] / "bin" / "bash.exe" if git else None
    return [str(bash), str(launcher)] if bash and bash.exists() else None


class LauncherTests(unittest.TestCase):
    bin = REPO / ".harness" / "bin"

    def test_the_shell_launcher_runs_the_cli_from_any_folder(self) -> None:
        launcher = self.bin / "harness"
        command = shell_command(launcher)
        if command is None:
            self.skipTest("Windows: the shell launcher runs under Git Bash, which is not installed")
        if os.name != "nt":
            self.assertTrue(os.stat(launcher).st_mode & stat.S_IXUSR, "harness must be executable")  # Windows keeps no execute bit
        with tempfile.TemporaryDirectory() as folder:
            done = subprocess.run([*command, "target", "--help"], capture_output=True, text=True, cwd=folder)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("list", done.stdout)
            self.assertEqual(subprocess.run([*command, "no-such-command"], capture_output=True, text=True, cwd=folder).returncode, 2)

    @unittest.skipUnless(SYMLINKS, "this account cannot make symlinks (on Windows: turn on Developer Mode or run as admin)")
    def test_the_shell_launcher_works_through_a_link(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / "h"
            os.symlink(self.bin / "harness", link)
            command = shell_command(link)
            if command is None:
                self.skipTest("Windows: the shell launcher runs under Git Bash, which is not installed")
            done = subprocess.run([*command, "logs", "--help"], capture_output=True, text=True, cwd=folder)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("prune", done.stdout)

    def test_the_windows_launcher_calls_the_cli_and_keeps_its_exit_code(self) -> None:
        content = (self.bin / "harness.cmd").read_bytes().decode("utf-8")
        self.assertIn("\r\n", content, "harness.cmd needs CRLF line endings")
        self.assertNotRegex(content, r"(?<!\r)\n")
        self.assertIn(r"%~dp0..\engine\cli.py", content)
        self.assertIn("%*", content)
        self.assertIn("exit /b %errorlevel%", content)
        self.assertIn("python", content)

    @unittest.skipUnless(os.name == "nt", "harness.cmd runs on Windows only")
    def test_the_windows_launcher_runs_from_any_folder_also_one_with_a_space(self) -> None:
        launcher = str(self.bin / "harness.cmd")
        with tempfile.TemporaryDirectory() as folder:
            spaced = Path(folder) / "a b"
            spaced.mkdir()
            done = subprocess.run(["cmd", "/c", launcher, "target", "--help"], capture_output=True, text=True, cwd=spaced)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("list", done.stdout)
            self.assertEqual(subprocess.run(["cmd", "/c", launcher, "no-such-command"], capture_output=True, text=True, cwd=spaced).returncode, 2)

    def test_git_keeps_the_line_endings_the_launchers_need(self) -> None:
        attributes = text(REPO / ".gitattributes")
        self.assertRegex(attributes, r"harness\.cmd\s+text eol=crlf")
        self.assertRegex(attributes, r"\.harness/bin/harness\s+text eol=lf")

    def test_the_launchers_are_guardrails_and_registered(self) -> None:
        registry = json.loads(text(REPO / ".harness" / "registry.json"))
        files = registry["modules"]["gate"]["files"]
        self.assertIn(".harness/bin/harness", files)
        self.assertIn(".harness/bin/harness.cmd", files)
        policy = json.loads(text(REPO / ".harness" / "policies" / "gate.json"))
        self.assertIn(".harness/bin/**", policy["guardrail_paths"])


if __name__ == "__main__":
    unittest.main()
