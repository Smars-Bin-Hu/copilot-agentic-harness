# Rules for an extractor

The function signature and the fields it returns are in [map.md](../../../../.harness/contracts/kb/map.md). These are the traps.

- **Standard library only, and no import of the harness.** The toolkit must run on any computer the harness runs on, and survive harness upgrades. Python 3.9.
- **One file in, its objects out.** Do not open other files, call git, or keep state between calls: the map calls an extractor only for files that changed, in any order.
- **Return names as written** (`dbo.usp_x`, `OwnerRepository`). The harness resolves them over all repositories; an extractor that guesses the full name ties itself to one database or package.
- **Blank comments and string literals before matching** (keep the line breaks, so line numbers stay right). A name in a comment is not a use. Dynamic code is the exception: read the string only to mark the object `dynamic`.
- **Mark what you cannot follow as `dynamic`** instead of guessing a target.
- **Raise on a file you do not understand** rather than return half of it. The map lists the file under `failed` with your error, and goes on.
- **Line numbers**: `line` of the object is where its name is defined; `line` of a use is where it is written.
- **No business names in the code.** If a rule needs a list of the company's object names, it belongs in a fact or a question for the user, not in the extractor.
- **Keep it short.** An extractor longer than a few hundred lines usually reads the language instead of the few forms the design named.
