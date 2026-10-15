# What the search cannot see

Write down the ones that apply to this change. Each is a reason to ask someone, not a reason to skip the check.

| Blind spot | Why | What to do |
| --- | --- | --- |
| Readers outside the registered repositories | Reports, dashboards, other teams' jobs, hand-run queries | Ask the user who else reads it; write the answer in `IMPACT.md` |
| Names built at run time | Dynamic SQL, string concatenation, f-strings, config templates | Search the fixed part; read the code that builds the name |
| Positional use | `SELECT *`, `INSERT` without columns, `SELECT` by position, file layouts read by column number | Search the table name; read those statements |
| Other names for the same thing | Abbreviations, old names, aliases, a view that renames a column | Search the old and short names the knowledge base gives |
| Scheduler and deploy settings | A job list outside the repositories | Ask the user, or search the repository that holds it if it is registered |
| Uncommitted or other-branch work | The search reads the committed base branch | Ask the user whether someone is changing the same thing |
| Data, not code | Rows that hold the name (a config table, a lookup) | Ask; this needs a query, which this skill does not run |
| Files the search skips | Binary files, files over the size limit of a plain knowledge base folder | List them if the change could matter there |
