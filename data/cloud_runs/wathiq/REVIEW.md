# Wathiq Billah vs old Madinah 1405: eye review

Run with the fixed split (page line breaks chosen jointly by alignment cost, `wathiq_split.py`) and reader (strict + loose
blue mask, scan streaks dropped, `wathiq_waqf.py`). 602/604 pages (1-2: decorated frame, not split).

| | first run | this run |
|---|---|---|
| same | 4274 | **4338** |
| other_symbol | 24 | 9 |
| missed | 62 | 8 |
| print_only | 54 | 8 |
| sakta_red (the sakta is printed red; the blue-sign reader skips it) | — | 5 |
| print_only_noise | 60 | 18 |
| **differences to review** | 140 | **25** |

Every one of the 25 was checked against the page image (`review-by-eye.json`):

| Verdict | Rows | |
|---|---|---|
| `model_misread` | 9 | print has old Madinah's sign; mostly the small م read as ج (2:253, 3:181, 4:118, 7:148, 36:76) |
| `model_missed` | 4 | print has the sign, faint (53:23, 55:54) or merged with a streak (6:28, 49:14) |
| `split_shift` | 6 (3 pairs) | 6:138, 17:51 (×2): the line break still moved a label by one word |
| `model_false_fire` | 5 | scan streaks on pages 370/372 |
| **`real`** | **1** | **16:74 الأمثال (p275)**: Wathiq prints no sign; old Madinah has ج (confirmed on a paper copy) |

Bottom line: Wathiq matches old Madinah 1405 everywhere except 16:74.
