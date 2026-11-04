# Sheikh Maktoum vs old Madinah 1405: eye review of the 520 differences

Every row of `compare-diffs.json` was checked against the full-resolution scan (word box and the reader's
sign marked on a crop; the 37 rows on pages whose word boxes were wrong were checked on the whole page;
possible real differences were re-checked zoomed in). Verdict per row: `review-by-eye.json`.

| Verdict | Rows | What it means |
|---|---|---|
| `position` | 212 | The sign is printed as old Madinah has it, but credited to the neighbouring word. 175: Maktoum prints the sign over the gap, often above the next word's first letter, and the split gives it to that word. 37: on 7 pages (32, 46, 59, 158, 175, 347, 446) the print breaks lines differently from the layout and every label on those lines is off. |
| `false_fire` | 138 | No sign there: the reader fired on a verse ring (most), a shadda, damma, tanween, the small س of يبصط, or an ornament. |
| `reader_missed` | 128 | The sign is printed as old Madinah has it; the reader did not find it (mostly صلى and ج; also 5 small lazim م that look like a damma at scan resolution). |
| `reader_misread` | 38 | The sign is printed as old Madinah has it; the reader named it wrongly (قلى as ج, معانقة dots as ج/م, م as ج, the sakta س as ج). |
| `unsure` | 1 | 9:42:19. |
| **`real`** | **3** | The print differs from old Madinah (below). |

## Real differences (print vs «المدينة القديم»), confirmed by the user

| verse:word | page | Maktoum prints | old Madinah |
|---|---|---|---|
| 3:7:31 الله («إلا الله») | 50 | م | قلى |
| 18:5:12 أفواههم | 294 | nothing | ج |
| 31:12:6 لله («أن اشكر لله») | 412 | ج | nothing |

Maktoum's lazim م is printed very small and looks like a damma at the scan's resolution: a first eye pass
took five of them (2:212, 5:64, 7:148, 11:20, 54:6) for missing signs. They are printed; a mark over a final
alif (قالوا، سبيلا، آمنوا) cannot be a damma.

Bottom line: 516 of 520 are the tools' errors; 3 are real; 1 unsure. The two split fixes (attach a sign to the
word whose end it sits over; choose the page's line breaks jointly, as already done for Wathiq) would remove
the 212 `position` rows.
