---
name: harness-vscode-updates
description: 'Read the newest VS Code release notes (code.visualstudio.com/updates) and judge, against the design of this harness, what to retire, change or add. Writes the advice to .local/vscode-updates/ for later. Use only when the user types /harness-vscode-updates. Keywords: VS Code release notes, updates, platform changes, Copilot changes, retire a module, upgrade the harness.'
argument-hint: 'Nothing (from the last version checked to the newest), or a version such as 1.142'
disable-model-invocation: true
type: workflow
specificTo: generic
---

# VS Code updates: what they mean for the harness

The harness is built on the extension points of VS Code and Copilot. Every module carries a `retire_when`: the platform feature that would make it unneeded. This skill reads the release notes since the last check and turns them into advice: retire, change, add, watch. It changes no harness file. The advice goes to `.local/vscode-updates/`, which git ignores.

## When to Use This Skill

**Use it only when the user types `/harness-vscode-updates`.** It reads several web pages and long text, which costs time and tokens. Run it about once a month, or after the user upgraded VS Code.

- No argument: every version after the last one checked, up to the newest.
- A version (`1.142`): that one only, even when it was checked before.

## Prerequisites

- The web fetch tool works, and code.visualstudio.com can be reached. If not, see Troubleshooting.
- The session holds no task. With a task, the gate lets you write the task folder only, and `.local/` is outside it. When the rules at the top of the prompt name a task this session holds, ask the user to start a new chat.
- No task is opened for this skill: it is upkeep of the harness, not a task of the team, and its output is not delivered anywhere.

## Step-by-Step Workflows

1. **Find where the last check stopped.** Read `.local/vscode-updates/INDEX.md`. Its table lists every version checked. When the file does not exist, this is the first run: create it from [index.md](./templates/index.md) after step 6, and check the newest version only, unless the user asks for more.
2. **Find the versions to read.** Fetch `https://code.visualstudio.com/updates/`. It redirects to the newest stable version; the title says it (`Visual Studio Code 1.142`). The page of one version is `https://code.visualstudio.com/updates/v1_<minor>`. Read every version after the last one checked, **6 at most in one run**; tell the user when more are left.
3. **Read only what can touch the harness.** In each page, read the sections listed in [what-to-look-for.md](./references/what-to-look-for.md) (Agents, Chat, Enterprise, Deprecated features and settings, and a few more). Skip editor, language and theme news. For each item that matters, keep: its title, the link to its anchor (`...v1_142#_agents`), and whether it is stable, Preview or experimental.
4. **Read the harness as it is now.** Do not judge from memory. Read:
   - `.harness/registry.json`: the modules and their `retire_when`.
   - `docs/05-design.md`: the design, and what the harness chose not to do and why.
   - `.github/hooks/harness.json` and `.harness/engine/adapters/tool_kinds.json`: the hook events and the tool names the harness relies on.
   - `.harness/policies/gate.json`: what the gate stops.
   - The last two reports in `.local/vscode-updates/`, so the advice does not repeat or contradict them without saying so.
   Read more only when an item points at it (a skill, an agent, `AGENTS.md`).
5. **Judge each item.** Give it one verdict, by the rules in [what-to-look-for.md](./references/what-to-look-for.md):
   - **Retire**: the platform now does what a module or a part of one does. Name the `retire_when` it meets, or why it meets part of it.
   - **Change**: it changes something the harness relies on (a hook event, a tool name, a setting, how approvals or subagents behave), or lets a part be done more simply.
   - **Add**: a new extension point or feature the harness could use for its users.
   - **Watch**: Preview or experimental, or not clear yet. Say what would turn it into one of the above.
   - Leave out items with no effect. List their titles in one line only.
   For every Retire, Change or Add write: the evidence (a quote of a few words and the link), the files it touches, the effort (small, medium, large), the risk, and **how to verify it in Copilot first**. Advice that has not been tried in Copilot is a guess: say so.
6. **Write the report.** One file per run: `.local/vscode-updates/<date>-v1_<from>-v1_<to>.md` (one version: `<date>-v1_<minor>.md`), from [report.md](./templates/report.md). Write it in the language the hook names. Then add one row per version to `INDEX.md`.
7. **Tell the user** in a few lines: the versions read, the count of each verdict, the two or three items worth acting on first, and the path of the report. Do not start any change: the user decides, and a change to the harness is made in admin mode (`harness-admin`).

## Gotchas

- **Do not change the harness in this skill.** It writes only `.local/vscode-updates/`. Even an obvious fix waits for the user.
- **Do not build on Preview or experimental features.** The harness rule is that they can change or vanish. Mark them Watch, whatever they promise.
- **The company may run an older VS Code.** Note the version each item came with. An item is only usable at the company once its VS Code is at least that version, and an enterprise policy can still switch it off.
- **Hooks in SDK sessions differ from what the release notes show.** The notes often describe the local agent. The harness supports Copilot (SDK) sessions only. A change to hooks, tool names or payloads counts only after a recorded payload proves it: the fixtures are in `.harness/eval/fixtures/hooks/copilot-sdk/`.
- **A headline is not a fact.** Release notes say what is new, not its limits. Before you advise Retire, follow the link to the docs page of the feature and check it covers what the `retire_when` asks for. Partly covered means Change or Watch, not Retire.
- **"Asks for approval" is not a boundary.** A platform feature that only asks (a confirmation dialog, an auto-approve list) does not replace a gate deny: Allow all and Autopilot skip it. Say so when an item is about approvals or permissions.
- **The fetch tool may cut a long page short.** When a section you need is missing, fetch the page again with the section anchor, or ask the user for the text.
- **The notes of one month may mention Insiders-only items.** Count only what the stable release ships.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The web fetch is refused or times out | Ask the user to open the page in a browser, save it (or copy the text) into `.local/vscode-updates/inbox/v1_<minor>.md`, and run the skill again. Read from there |
| A write to `.local/` is refused | The session holds a task. Ask the user to start a new chat and type `/harness-vscode-updates` there |
| `INDEX.md` lists a version newer than the newest page | The page redirect may lag. Trust the version in the page title, and say so in the report |
| Many versions are unchecked | Read the newest 6, write the report, and tell the user to run the skill again for the rest |
| An item seems to break the harness right away (a hook event renamed, a tool gone) | Put it first in the report, marked Change with high risk, and tell the user to run `harness doctor` and one hook check in Copilot before anything else |
