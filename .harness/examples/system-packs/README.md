# System packs

A system pack is what a company puts in its knowledge base, under `company/tools/`, so that an agent may reach an outside system (a database, a cloud, a ticket board) through the gate. The harness ships none: the folders here are samples with made-up names. Copy one into `<knowledge base>/company/tools/`, change the names, then `harness company sync`.

```text
<knowledge base>/company/tools/
  systems.json        {"systems": {...}}: the outside systems, in the form of `systems` in tools.json. Copied to .harness/policies/tools.company.json
  launch/             scripts a person runs to start VS Code the way a system needs (an identity, a sign-in). Copied to .harness/launch/
  README.md           for the people of the team: not copied
```

These paths are fixed: `company sync`, `company pack` and `company update` count on them. A skill that teaches the agent how to use the system goes in `company/skills/`, as any company skill.

| Sample | What it shows |
| --- | --- |
| `sqlserver-sqlcmd/` | A SQL Server reached with `sqlcmd` and the identity of the process (Windows authentication): the environment from the server name, read and write verbs, a probe, and a launch script that starts VS Code under another identity with `runas /netonly` |
