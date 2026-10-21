# 11. Independent checks: `[review]=n`

## In one sentence

Nothing is checked by default. When you write `[review]=n` in a prompt, the work of the task has to **pass n independent checks in a row** before it can be written back. The checker (the reviewer) has not seen the author's reasoning, and the code counts the passes: the agent's own word is not trusted.

## Chunks

### 11.1 Why it is needed

Someone who checks their own work has the same blind spots. A target repository cannot be run, so checking can only be reading. So the trust comes from three things: the checker has not seen the author's reasoning; it is a new one every time; and the knowledge base states the rules.

### 11.2 How to use it

1. You write `[review]=n` in a prompt of the task (once is enough; `[review]=0` switches it off). The agent cannot write it itself.
2. When the work is written, the agent runs `task review start`: a snapshot is saved, and the review package is written.
3. The agent calls the reviewer (only now is it let through; without checks on, the call is refused).
4. The reviewer answers: the first line is `VERDICT: PASS` or `FAIL`, every finding has "file:line", and it only points out findings, never how to fix them.
5. The hook saves the answer as written, as `REVIEW/round-NNN/verdict.md`; the agent cannot change it.
6. FAIL: the agent fixes the findings itself and checks again, with a new reviewer every time. From the 2nd check on, only what affects correctness is reported.
7. Only with n passes in a row can `task promote --dry-run` run.

### 11.3 How it is counted (the main point)

`passes` = counting back from the latest check, the PASSes in a row whose **checked version is exactly the work as it is now**.

- "Exactly" rests on sha256: the result files, `REQ.md` and `PLAN.md` make up the fingerprint together.
- Not counted in: `TASK.md`, `TODO.md`, `LOG.md`, `.task`, `REQ/`, `REF/`, `REVIEW`, `SNAPSHOT`, the `.diff` files, and what promote writes into `DEV/` itself (`*.patch`, `_deleted/`), and what a tool makes (`.DS_Store`, `Thumbs.db`). Updating the progress, or a write-back, does not undo a pass.
- **After a write-back, or when the task is closed**, the page shows the checks as they stood (the passes in a row on the last version checked), not compared again with files that change afterwards (a draft written after the close, say). The gate that lets a write-back through always counts on the files as they are.
- Once the work, the requirement or the plan changes, the earlier passes no longer count.

### 11.4 The limit on checks

At most `n + 2` checks (`review.extra_checks` in `task.json`), plus the extra ones you give. n is 5 at most. When they are used up without enough passes, the agent stops and tells you where the last findings are. You choose in the terminal:

- `harness task review extend --checks 2`: 2 more checks;
- `harness task review waive`: no more checks; **this version** is let through (if the work changes again, the waiver ends).

Why there is a limit: a reviewer may keep finding fault.

### 11.5 The output of `harness task review status`

| Item | Meaning |
| --- | --- |
| `n` | How many passes in a row are needed |
| `passes` | The number of PASSes in a row for the work as it is now |
| `checks_used` / `checks_limit` | Checks done / the limit |
| `last_verdict` | The verdict of the latest check |
| `pending_round` | The round that is open and not answered yet |
| `waived` | Whether the current version was let through |
| `next` | The next step. The agent decides by this sentence whether to go on, stop or move ahead |

### 11.6 What if checks are on and nothing is checked

The Stop hook checks: when checks are on and nothing was checked, or files changed after a check, it blocks once and makes the agent catch up.

### 11.7 The honest limits

- It was measured that two reviewers give different verdicts on the same work. n=1 is enough day to day; use 2 for an important change.
- The reviewer cannot run the code of a target repository; it can only read.
- Whether a check really happened is confirmed by the `verdict.md` the hook wrote to disk, not by the agent's word.

## Hands on

- Read [reviewer.agent.md](../../../agents/reviewer.agent.md).
- Open `REVIEW/round-001/verdict.md` and `package.md` of some task.
- Run `harness task review status`.

## Where to look

- `.harness/engine/modules/task/taskreview.py` (`passes`, `limit`, `summary`), `tasksnap.py` (the fingerprint)
- The part of [02-features.md](../../../../docs/02-features.md) about independent checks

## Common questions

- **"Can the agent make the reviewer always pass it?"** The CLI writes the review package and the hook saves the verdict; the agent can change neither. It can only change the work.
- **"Why passes in a row, and not one pass?"** One PASS may be luck. n=2 needs two independent reviewers to agree.
