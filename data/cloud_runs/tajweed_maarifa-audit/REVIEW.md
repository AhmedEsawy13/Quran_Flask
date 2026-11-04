# مصحف التجويد (دار المعرفة) vs old Madinah 1405: eye review

Audit (all 604 pages, reference «المدينة القديم»): match 4001, wrong 39, missing 323, extra 19 (exact recall 91.7%).
Reviewed by eye, as the runbook asks: every `symbol_differs` (39) and `not_in_db` (19) item, and a random sample
of 50 of the 297 `cv_missed` items (seed 1), on crops of the 1024 px page cache. Verdict per item: `review-by-eye.json`.

| Class | differs + not_in_db (58) | missed sample (50) | What it means |
|---|---|---|---|
| **real** | 3 | 0 | the print differs from old Madinah (below) |
| reader | 22 | 27 | sign printed as old Madinah has it; the model misread or missed it |
| position | 7 | 0 | sign printed as old Madinah has it on the neighbouring word; the audit attached it to the wrong key |
| false | 22 | 0 | no waqf sign: the reader fired on a colour tajweed mark (madd strokes, green/red letters), a vowel, or a juz/surah header |
| unsure | 4 | 23 | the crop cannot tell |

The `cv_missed` sample has no real difference: every one that could be judged has the sign printed.

## Real differences

| verse:word | page | word | التجويد prints | old Madinah | note |
|---|---|---|---|---|---|
| 2:144:9 | 22 | تَرْضَىٰهَا | صلى | ج | every other print in the DB has ج |
| 13:8:11 | 250 | تَزْدَادُ | ج | صلى | new Madinah and al-Azhar have ج |
| 58:22:42 | 545 | عَنْهُ («ورضوا عنه») | قلى | ج | every other print in the DB has ج |

This print follows old Madinah 1405 closely (not 1427 or the new Madinah: only 7 of the 58 flagged signs match either),
so «المدينة القديم» stays its reference. Most flags come from the colour tajweed marks the model was not trained on.
