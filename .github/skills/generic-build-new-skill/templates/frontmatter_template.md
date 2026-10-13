### Frontmatter (Required)

```yaml
---
name: generic-webdev-testapp
description: 'Toolkit for testing local web applications using Playwright. Use when asked to verify frontend functionality, debug UI behavior, capture browser screenshots, check for visual regressions, or view browser console logs. Supports Chrome, Firefox, and WebKit browsers.'
license: Complete terms in LICENSE.txt
type: unit
specificTo: generic
---
```

| Field | Required | Constraints |
| --- | --- | --- |
| `name` | Yes | Lowercase, hyphens for spaces, max 64 characters (e.g., `generic-webapp-testing`) |
| `description` | Yes | 10–1024 characters, clear capabilities AND use cases, wrapped in single quotes |
| `license` | No | Reference to LICENSE.txt (e.g., `Complete terms in LICENSE.txt`) or SPDX identifier |
| `type` | Yes | `unit`: the skill does one well-defined unit of work with a fixed input and output, usually one step of a workflow or a tool that is used often. `workflow`: the skill arranges the steps of a complex task flow |
| `specificTo` | Yes | `generic` for a skill usable in any domain, or `<domain-name>` for a skill for one business domain |

### Description Best Practices

**CRITICAL**: The `description` field is the PRIMARY mechanism for automatic skill discovery. Copilot reads ONLY the `name` and `description` to decide whether to load a skill. If your description is vague, the skill will never be activated.

**What to include in description:**

1. **WHAT** the skill does (capabilities)
2. **WHEN** to use it (specific triggers, scenarios, file types, or user requests)
3. **Keywords** that users might mention in their prompts

**Good description:**

```yaml
description: 'Toolkit for testing local web applications using Playwright. Use when asked to verify frontend functionality, debug UI behavior, capture browser screenshots, check for visual regressions, or view browser console logs. Supports Chrome, Firefox, and WebKit browsers.'
```