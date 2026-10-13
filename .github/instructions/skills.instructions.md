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
