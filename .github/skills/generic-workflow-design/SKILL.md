---
name: generic-workflow-design
description: 'Design an agentic workflow from a repeated manual development routine, without building it: learn from the user''s description, 2-3 finished examples and the knowledge base, sort each step into deterministic, semantic, human or verification, and write WORKFLOW-DESIGN.md for the user to approve. Use when the user describes a standard routine to be repeated ("every time we add a pipeline we do these steps"), or asks to turn a process into a skill or standardise a workflow. Keywords: workflow, SOP, standard process, ETL steps, repeatable, orchestration.'
type: workflow
specificTo: generic
---

# Design a workflow from a repeated routine

People repeat the same development routine for every new pipeline, table or report. If an agent learns it once, each next case follows the same standard. This skill does the first half: it designs the workflow and stops. It builds nothing; `generic-workflow-build` does that after the user approves the design.

**Who starts it: offer.** When the user describes a routine that will repeat, ask in one line whether to design a workflow from it (it reads the examples and the knowledge base, and writes one document). Go on only after a yes, or when the user asked for it.

## When to Use This Skill

- The user describes the steps a person takes for a repeated kind of work, and wants the agent to do it the same way next time.
- The user asks to turn a process into a skill, or to standardise how something is developed.

## Prerequisites

- A task is open (`harness-my-task`), kind `design`. The design is a file at its root; no approval is needed to write it.
- The routine as the user tells it, in `REQ/` or in the conversation. Ask for a runbook, an old ticket or notes if there are any.
- **2 or 3 finished examples** of the routine (names of things already built in the target repositories). Without them the design is a guess: say so, and mark every step "unverified".

## Step-by-Step Workflows

1. **Collect.** Write down the routine in the user's words. Ask for the examples, for the kinds of case the routine will meet, and for what goes wrong. Write unclear points into `REQ.md` as questions.
2. **List the objects of each example.** Run `harness target refs <example name>` for each example: it lists every file that holds the name. Together with the user's words, that is the set of objects one case touches.
3. **Align the examples.** Put the lists side by side with the example names replaced by a placeholder. Paths that match for every example are the skeleton. Strings that change with the example name are parameters. Content that differs beyond the name is where judgment lives. Method and traps: [classify-steps.md](./references/classify-steps.md).
4. **Read the knowledge base** for the naming, layering and registration rules and the acceptance standard. Note the page for each rule you use.
5. **Sort every step** into D (deterministic), S (semantic), H (human) or V (verification), with the evidence for it (the user's sentence, the knowledge base page, the example file). Anything the examples have and the user did not mention (a registry entry, a release list) goes on the questions list: is it part of the routine?
6. **Write `WORKFLOW-DESIGN.md`** from [workflow-design.md](./templates/workflow-design.md): goal and limits, parameters, the steps table, the skill layout (unit skills and one orchestration skill), the flexible parts, the open questions, the test plan, the install plan.
7. **Stop.** Give the user the link and the open questions. The confirmation line at the end of the file is filled in by the user only; you do not fill it in, and you do not start `generic-workflow-build`.

## Gotchas

- **A step is D only when the examples prove it**: the same parameters give the same result in at least two of them. When unsure between D and S, choose S. Judgment can be turned into code later; code that was wrong about a judgment is harder to find.
- **Do not design from the description alone.** What people say they do and what the examples hold differ; the difference is the most useful finding. Put it in the open questions.
- **Names, values, customers and secrets from the examples do not go into the design.** Use placeholders and describe the shape.
- **A path in `refused_paths` or a guardrail path is an H step.** Write "the user changes it by hand" and do not plan to write it.
- **Keep the approvals of the harness in the flow**: the plan approval before `DEV/`, the promote approval, and the independent check when the user asked for one. A workflow does not skip them.
- **Split a workflow that has more than about twelve steps or two different outputs.** One design per kind of result.
- **Leave room.** Write defaults and conditions ("skip when ... "), not a fixed script. Record the variants the examples showed, and what to do when a case fits none: say so, fall back to the model and the knowledge base, or ask.
- **Do not build anything**: no skill folders, no scripts. The design is the only file you write.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| The user has no example | Say the design is a guess, mark all steps unverified, and ask for one example before building |
| The examples differ a lot | They may be two routines. Ask the user; design one workflow per routine |
| `target refs` finds the name in hundreds of files | The name is too common, or the examples are old. Use a more exact name or `--exact`; ask which files matter |
| The user wants the skills now | Finish the design and get the confirmation first; the build skill refuses to start without it |
