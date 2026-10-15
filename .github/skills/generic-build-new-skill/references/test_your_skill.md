# Test a skill

A skill that Copilot never loads helps nobody. Copilot picks a skill by its `name` and `description` alone, so test that first.

## 1. Check the form (no Copilot needed)

Run `harness skill check <skill folder name>`. It reports:

- **Errors**: the skill cannot be loaded or has a dead link. Fix all of them.
- **Warnings**: it loads but will be found or used badly (no "Use when", a description that is too long, no Gotchas, a file that no text points at). Fix them unless you have a reason.

`harness doctor` runs the same check on every skill, so a skill that breaks later shows up there too.

## 2. Does it trigger?

Write the prompts down before you test, in the words a user would really say, not in the words of the description:

| Kind | How many | Example of what to write |
| --- | --- | --- |
| Should trigger | 3 | Three ways to ask for the same thing: short, long, and one that does not use your keywords |
| Should not trigger | 2 | Neighbours: asks that sound close but belong to another skill |

For each prompt, open a **new chat** (an old chat may already hold the skill) and send it. Do not type the skill name. Then run `harness stats --session-id <id>` and look at `skills_loaded`: it lists the skills that were loaded in that session. This is a fact from the log, not what the agent says.

- Did not load when it should: the description lacks the words the user said. Add them to `description` (keep it short), and test again.
- Loaded when it should not: the description is too wide. Narrow the "Use when", or add a line about when not to use it.

## 3. Does it change what the agent does?

A skill that loads but changes nothing is dead weight. Run the same task twice, in two new chats: once with the skill and once without (move the folder away, or name a task the skill does not cover). Compare the result against what you wrote the skill for. If you cannot see a difference, cut the lines that make none: the agent already knew them.

## 4. Keep what you learn

Every time the agent does something wrong with the skill, add one line to `## Gotchas`: **bold** the rule, then the reason. A gotcha with a real example is worth ten general tips.
