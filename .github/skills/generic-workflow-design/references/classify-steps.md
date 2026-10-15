# Sorting steps, and aligning examples

## The four kinds

Ask the questions in order. The first yes decides.

| Kind | Question | Goes to |
| --- | --- | --- |
| H human | Does the step need authority: an approval, a production run, a permission, a protected path? | Stays with the user. Write who and when |
| D deterministic | With the same parameters, do at least two examples give the same result, byte for byte apart from the names? | A script with a test |
| V verification | Is it a check of a result? Can a command do the check (counts, fields, names exist, no duplicates)? | A script if it can; otherwise a check list for the model and the independent check |
| S semantic | Does it need to understand the requirement or the business? | The model, with a check list, pointers to knowledge base pages, and the common mistakes |

A step can be split: a config file is D for its shape and S for the source, the fields and the schedule.

## Aligning the examples

1. Take the file list of each example from `harness target refs <example name>`. Ignore hits that are only a mention (a comment, a README line) unless the user says they matter.
2. Replace the example name in every path with `{name}`, and the parts that change with a domain or layer with `{domain}` and `{layer}`. If the paths of all examples now match, that is the skeleton of the objects.
3. For each file in the skeleton, read it in two examples. Text that is the same apart from the name and the parameters is a template. Text that differs is judgment (S) or a variant.
4. Look for registration: lines in a shared file (a registry, a manifest, a scheduler list) that name each example. These are easy to forget; they belong in the design as their own steps.
5. Parameters are what you would have to be told to produce the next case: the name, the domain, the layer, the source, the target. Mark which can be derived from the requirement or the knowledge base and which must be asked.
6. Write the variants: where one example does something the others do not, and why (ask when unknown).

## What the examples cannot tell

- Why a step exists. Ask the user for the reason of any step that looks optional.
- The order the person works in. Use the order of dependencies (a file that names another must come after it), and ask.
- What the person checks by eye. Ask what they look at when they say it is done.
