---
description: 'Guidelines for creating high-quality Agent Skills for GitHub Copilot'
applyTo: '.github/skills/**/SKILL.md'
---

# Progressive Loading Architecture

| Level | What Loads | When |
| --- | --- | --- |
| 1. Discovery | `name` and `description` only | Always (lightweight metadata) |
| 2. Instructions | Full `SKILL.md` body | When request matches description |
| 3. Resources | Scripts, examples, docs | Only when Copilot needs them |


# Skill name prefixes

The folder name of a skill and its `name` field must be the same, and use one of the three prefixes below. Only third-party skills have no prefix: they keep their own names.

- `harness-<name>`: a skill of the harness itself. Maintained upstream. Two kinds:
  - The semantic side of a module: the name matches `.harness/engine/modules/<module>/`, with underscores in the module name written as hyphens.
  - A flow for using the harness itself: it matches no module, and the name says what it does (`harness-get-me-ready`).
- `generic-<skill-name>`: a general skill for any domain. Maintained upstream.
- `domain-<domain name>-<skill-name>`: a skill for one business domain. Maintained by the team; upstream makes none.


# Who starts a skill

Every skill says in its first lines who starts it. Pick one of three, by what the skill costs and what it touches:

- **auto**: the agent starts it when the situation fits. For a skill that is cheap and reads, or writes only a draft in the task folder, and that the user would want every time. Make the `description` match the situation (`Use when ...`, in the words a user says).
- **offer**: the agent may start it, but first asks the user in one or two lines (what it will do, roughly what it costs) and goes on only after a yes. A skill that is asked for by name is not asked about again. For a skill that takes real time or tokens, or spreads work. Say so in the first step of the skill.
- **user-only**: `disable-model-invocation: true`. The agent cannot start it, but when the situation fits it tells the user that the command exists (`you can type /name`). For a skill that spends money, hands over rights, or runs unattended.

A skill never goes beyond the task it serves: it writes in the task folder only, and it does not change a target repository or the knowledge base, or switch on what only the user may switch on. Where a skill ends and a step needs the user (an approval, a copy into place), it says so and stops.

# Unit type vs workflow orchestration type

- Unit type: the skill does one well-defined unit of work, with a fixed input and output. It is usually one step of a workflow, or a tool that is used often.

- Workflow orchestration type: the skill arranges the steps of a complex task flow.

- Directory Structure Example
# Skill Files Structure
```
.agents/skills/my-skill/
├── SKILL.md              # Required: Main instructions
├── LICENSE.txt           # Recommended: License terms (Apache 2.0 typical)
├── scripts/              # Optional: Executable automation
│   ├── helper.py         # Python script
│   └── helper.ps1        # PowerShell script
├── references/           # Optional: Documentation loaded into context
│   ├── api_reference.md
│   ├── workflow-setup.md     # Detailed workflow (>5 steps)
│   └── workflow-deployment.md
├── assets/               # Optional: Static files used AS-IS in output
│   ├── baseline.png      # Reference image for comparison
│   └── report-template.html
└── templates/            # Optional: Starter code the AI agent modifies
    ├── scaffold.py       # Code scaffold the AI agent customizes
    └── config.template   # Config template the AI agent fills in
```
