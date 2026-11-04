# Wathiq Billah vs old Madinah 1405: eye review of the 140 differences

Every row in `compare-diffs.json` was checked against the page image (word box drawn on the line, plus
the lines above and below where the sign could sit at a line end). The verdict for each row is in
`review-by-eye.json` (`verdict`, `note`).

| Verdict | Rows | What it means |
|---|---|---|
| `split_shift` | 86 (43 pairs) | Same sign in the same place as old Madinah. The split cut one word into two boxes (e.g. تحزن → «تحز» + «ن»), so every label after it on the line slid by one; the sign lands on the neighbouring key and shows up as one `missed` + one `print_only`. |
| `model_misread` | 23 | The print has the old Madinah sign; the reader named it wrongly. Mostly قلى read as ج (12), also small م (ۘ) read as ج, صلى read as م, قلى read as ص/ع. Two are faded ج. |
| `model_missed` | 18 | The sign is in the print; the reader missed it. Includes all 4 Hafs saktas (18:1, 69:28, 75:27, 83:14): the print has them, the reader has no sakta class. |
| `model_false_fire` | 11 | No sign in the print at that word (7 on p372/p370, 3 at the start of an ayah, 1 at 17:105 next to a real قلى). |
| `same` | 1 | 36:52 مرقدنا: قلى above the word, sakta given as a margin note. |
| **`real`** | **1** | **16:74 الأمثال (p275)**: Wathiq prints no sign; old Madinah has ج (confirmed by the user on a paper copy). |

Bottom line: 139 of 140 are the tools' errors, not the print's; one is real: 16:74 الأمثال, no sign in Wathiq
where old Madinah has ج (confirmed on a paper copy). Note that the blue sign ink is faded on some pages (22:18, 53:23, 55:54), which is where the
reader struggles most.
