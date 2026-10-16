# How the English should read

The house style is the `Writing` part of `AGENTS.md`: short sentences, common words, nothing that carries no information. What a translation gets wrong beyond that:

- **Translate meaning, not words.** A Chinese sentence often packs three facts with commas; write three short sentences. Do not keep 的/了 rhythm ("the loading of the data of the table").
- **Do not add.** No explanations, no softening, no "Note that". A line that was terse stays terse. Do not drop anything either: every fact, number, condition and exception comes across.
- **Names stay as they are**: table, column, job, package, procedure, file and path names, SQL, code, commands, config keys, error messages quoted from a system. If a Chinese name is itself an identifier (a Chinese column name), keep it and add the English in brackets once: `客户编号` (customer number).
- **Code blocks**: translate Chinese comments only; every other character stays.
- **Headings stay parallel**: if the Chinese headings are all nouns, the English ones are all nouns.
- **One term, one translation**: the glossary decides. A term not in the glossary that comes up more than once: stop and add it to the glossary draft first.
- **Uncertain meaning**: keep the Chinese in brackets after your English and list the line in the task's `LOG.md` for the user. Never guess a business meaning.
- **YAML and JSON**: translate values that are prose; never keys, IDs, enums or paths.
