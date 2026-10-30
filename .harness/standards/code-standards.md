# Code standards

This file ships empty. Better, write your company's code standards in `<knowledge base>/company/standards/code-standards.md`: that file is used first, and this copy of the harness stays clean. Or write them here. The skill `generic-code-standards` reads it, checks the code of a task against it, and fixes what does not comply. The agent asks you before it runs the check.

Only rules written as below are used. Anything in an HTML comment is ignored.

## How to write a rule

One rule, one `###` heading. Keep each rule short and checkable: a rule that says "write clean code" cannot be checked.

```markdown
### R1 Table names are lower snake case
- **Applies to**: `*.sql`
- **Rule**: Table and column names use lower_snake_case. No spaces, no quotes, no camelCase.
- **Check**: `sqlfluff lint {file} --rules CP02`   (or `read` when a person must read the code)
- **Fix**: auto   (or `manual`: a change that needs a decision)
- **Severity**: must   (or `should`)
- **Good**: `select order_id from sales.order_delay`
- **Bad**: `select OrderID from [Sales].[OrderDelay]`
```

- **Applies to**: file patterns the rule is for.
- **Check**: a command that prints the problems (`{file}` stands for the file), or `read`. The command runs as written on the files of the task, nothing else.
- **Fix**: `auto` when the change is mechanical and safe; `manual` when it needs a decision. The agent fixes `auto` rules and the clear `manual` ones; it asks about the rest.
- **Severity**: `must` is fixed; `should` is reported.

Group rules under a `##` heading per language or area (SQL, Python, shell, configuration). Put long reasons and examples in other files in this folder and link them; the agent reads a linked file only when it needs it.

## Rules

<!-- Write your rules below this line. -->
