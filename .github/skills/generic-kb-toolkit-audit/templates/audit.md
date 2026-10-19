# Map audit

Date: <YYYY-MM-DD> · Map at: <repo>@<short commit>, ... · Toolkit: <name> (signature <signature from `toolkits` of kb audit>) · Sample: `kb audit --per-type <n> --seed <s>` · Bar: <0.95>

Result: **pass** | **fail**

## Score per type

| Type | Objects | Uses read | Uses in the map | Both | Recall | Precision | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- |

## The map's misses (in the code, not in the map)

| Object | Use | Path:line | Why the toolkit misses it |
| --- | --- | --- | --- |

## The map's false uses (in the map, not in the code)

| Object | Use | Path | Why the toolkit sees it |
| --- | --- | --- | --- |

## Patterns

- <one line per form the toolkit gets wrong, with how common it looks in the code>

## Names the map could not place (`unresolved` of `kb map`, most used)

- <name: used by n; what it is>

## Readings corrected after checking the line

- <object, use: what was misread. Or "none">

## Not counted

- Dynamic code: <ids>
