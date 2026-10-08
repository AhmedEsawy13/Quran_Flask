# Third round: full check, weighted toward منار

Read `INSTRUCTIONS.md` (packet format, blanket rows, output shape) and
`INSTRUCTIONS_ATTRIBUTION.md` (attribution and reading rules) in this folder
first. This round checks EVERYTHING for each row: ruling (grade), seat,
attribution, reading/i'rab condition, and that it is a real ruling. Judge only
from the book text.

## منار الهدى (الأشموني) — how the book is written
- Each entry is `{quote} [n] grade…`, where `[n]` is the AYAH NUMBER of the
  stop (use it: the seat must be in that ayah). The stop is the END of the
  quote. `{X (n)}` with a number inside the braces is a verse end.
- «ومثله «A»، و «B»» / «وكذا «A»»: A and B get the SAME grade as the head
  entry (unless the book states another grade for them). These rows have
  `follows` set or a note like «مثل «head» (grade)». Check the item is really
  named in the chain, that it is the right occurrence (the next one after the
  head in reading order, unless the book says الأول/الثاني/في الموضعين), and
  that the grade is the head's.
- «X الأول / الثاني»، «في الموضعين»: ordinal occurrences in the verse/passage.
- Reading or i'rab splits: منار keeps BOTH sides as separate rows, each with
  its condition in the note («جائز على قراءة عكرمة …» + «ليس بوقف لمن جرها»).
  A row is WRONG only if its condition is missing/attached to the wrong row,
  or the Hafs side is absent where the book states it. Hafs = the text in
  `verse_numbered`.
- `stratum` tells you why the row was sampled: `chain`, `conditional`,
  `repeated_word` (the stop word occurs more than once in the verse — check
  the occurrence carefully), or `plain`.

## Minor issues (still verdict OK)
If the grade/seat/attribution are right but the `note` holds text that belongs
to a different ruling, keep verdict OK and add `"minor": "note_from_other_ruling"`.

## Output
JSON array to your result file, one object per row:
```
{"id": 1, "book": "manar", "stratum": "chain", "verdict": "OK" | "WRONG" | "UNSURE",
 "problems": ["grade" | "seat" | "attribution" | "missing_condition" | "non_hafs_reading" |
              "not_a_ruling" | "missing_hafs_side"],
 "minor": "note_from_other_ruling" (optional),
 "expected": "what it should be",
 "evidence": "book line number + SHORT quote (≤ 20 words)"}
```
Use your own uniquely named temp files if you write scripts. Do not modify any
other file. End with a short summary: counts, and one line per WRONG id.
