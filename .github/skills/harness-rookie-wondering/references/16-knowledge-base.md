# 16. The knowledge base from code: scripts for structure, the model for meaning

## In one sentence

A knowledge base is worth reading only when it costs less than the code and is right; so what has one right answer (which objects, who uses what, in what order, whether a card's relations hold) is done by script, and the model only reads code and writes what it means, under checks.

## Chunks

### 16.1 Why not let the model read everything

A model that walks a code base by itself decides what to read next from what it just read. It misses objects, follows the wrong name, and cannot say how much it missed. Asking it twice gives two answers. A script that parses every file gives the same map every time, for no tokens, and can say what it could not read.

### 16.2 The toolkit and the map

What a procedure, a job or a class looks like in a file depends on the team's stack, so the harness ships no parser for it, only two samples. The team builds a toolkit (`toolkit.json` and small extractors) inside its knowledge base; `kb map` runs it over the base branch of each repository and caches every object and every use. Only changed files are read again.

### 16.3 How right is the map

Three checks run on every map: the uses a person knew (`facts.jsonl`), the files read or not, and the names that fit nothing. They show that the toolkit can find a use, not how many it misses. `kb audit` measures that: a sample of each type is read blind, and the script scores recall and precision per type. A reading is not truth either, so each difference is checked at its line. Code built at run time is out of reach of any map; it is marked `dynamic` and asked for.

### 16.4 Learning in batches

`kb order` walks the map from the entry points a person chose, cuts off what other domains share, and orders the rest bottom up: what an object uses is learned before it, so its card can point at the cards below instead of the code. A batch is one type, at most 20 objects and about 1500 lines. The whole domain is one task: its plan lists every batch and is approved once, its `TODO.md` has one step per batch, and the domain is written back once at the end. Chats come and go ("continue learn-<domain>"); the task keeps the state. A long object is a batch of its own and read in parts.

### 16.5 Checks on what the model writes

The model writes each card. Two of its parts are checked by script: the relations line must equal the map's uses (`kb cardcheck`), and every rule cites its lines, which must fall inside the object's code. The flows of `architecture.md` come from paths on the map (`kb flows`) and are checked the same way. What is left unchecked is whether a rule is understood right: that is the person's review, or the reviewer.

### 16.6 Where it stands, from the files

`kb status` works out from the files which step is done: the toolkit, the map and its facts, the audit (of this toolkit), the domains, and in each domain the plan, what is left to learn and the flows (in the open learn task while a domain is learned). A wizard (`/harness-rookie-new-knowledgebase`), a stop of a task (the offer once per session) and a person back after a week all read the same answer, so nothing depends on what an agent remembers.

### 16.7 A base, with its versions and its gaps

Every card holds the git sha of its source and the commit it was read at, so `kb stale` knows which cards the code has moved past. What the code cannot tell goes into `requests.md` (for a person to give) and `environment.md` (one fact a row, with the sha of the code that day). The knowledge base does not look complete; it says where it is not.

## Hands on

- Read `docs/08-knowledge-base.md`, section "The road, step by step".
- Run `harness kb --help` and find the commands of each step.
- Open `.harness/examples/kb-toolkits/spring/toolkit.json` and `facts.jsonl`: a whole toolkit is this small.
- When a map exists: `harness kb split`, then `harness kb order --entry <an entry point>`.

## Where to look

- `.harness/engine/core/kbmap.py` (building the map), `kbgraph.py` (questions on it), `kblearn.py` (order, flows, index, cardcheck), `kbaudit.py`, `kbstd.py` (the form, stale, stamp)
- `.harness/contracts/kb/README.md` (the standard), `map.md` (the toolkit contract)
- The skills `generic-kb-*`

## Common questions

- **"Can the map be 100% right?"** No. It can be measured (`kb audit`), and what it cannot see is listed, not guessed.
- **"Why not one big prompt that learns the domain?"** One context gets worse towards its end: so one batch at a time, and a new chat every two or three batches. What is reviewed is held by scripts (`kb cardcheck` on every card, `kb check`), and the person approves the plan and the one write-back.
- **"Does the model still matter?"** Yes: every word of meaning in a card is the model's. The scripts only make sure it reads the right things, in the right order, and does not make up structure.
