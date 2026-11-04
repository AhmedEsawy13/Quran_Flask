# مصحف آل البيت vs «المدينة ١٤٢٧»: eye review

**Why 1427.** The first audit against old Madinah 1405 (`../aalalbayt-audit/`) found 125 real differences; 112 of them are
the sign of the Madinah 1427 print, and where 1427 and the new Madinah disagree the print shows 1427's sign 91 times and the
new one twice. The colophon (scans 611-626 on tafsir.app) says the signs are the Jordanian Ministry of Awqaf review
committee's (chair: Samih Ahmad Athamneh; worked 1424-1429 AH; printing approved 3 June 2008, decision 2008/6/1; printed
1429 AH / 2008; calligrapher Shukri Hussein al-Khalidi). Line breaks follow 1405, so the layout stays QPC v1.

Audit against 1427 (all 604 pages): match 3851, wrong 45, missing 397, extra 30
(exact recall 89.7%; against 1405 it was 85.7%). Reviewed by eye as the runbook asks: every
`symbol_differs` and `not_in_db` item (75) and a random sample of 50 `cv_missed` (seed 1). Each crop was labelled
with the nearby words that carry a 1427 sign, so a sign attached to the wrong word shows up as `position`.

| Class | differs + not_in_db (75) | missed sample (50) |
|---|---|---|
| **real** | 13 | 0 |
| reader | 19 | 30 |
| position | 10 | 7 |
| false | 31 | 0 |
| unsure | 2 | 13 |

`position` includes the last pages (572-598), where the word boxes sit on the wrong line.

## Real differences from «المدينة ١٤٢٧»

| verse:word | page | word | آل البيت | 1405 | 1427 | new Madinah | الأزهر |
|---|---|---|---|---|---|---|---|
| 4:9:10 | 78 | عَلَيْهِمْ | صلى | — | — | — | ج |
| 5:22:12 | 111 | مِنْهَا | صلى | — | — | — | ج |
| 9:19:15 | 189 | ٱللَّهِۚ | قلى | ج | ج | ج | ج |
| 9:60:16 | 196 | ٱلسَّبِيلِۖ | قلى | صلى | صلى | صلى | ج |
| 12:24:3 | 238 | بِهِۦۖ | ج | صلى | صلى | صلى | ج |
| 24:26:4 | 352 | لِلْخَبِيثَٰتِۖ | ج | صلى | صلى | صلى | ج |
| 26:154:5 | 373 | مِّثْلُنَا | ج | — | — | — | ج |
| 28:31:3 | 389 | عَصَاكَۚ | صلى | صلى | ج | ج | ج |
| 38:22:14 | 454 | بَعْضࣲ | ج | — | — | — | ج |
| 38:22:19 | 454 | تُشْطِطْ | ج | — | — | — | ج |
| 38:56:2 | 456 | يَصْلَوْنَهَا | ج | — | — | — | ج |
| 57:15:9 | 539 | كَفَرُوا۟ۚ | صلى | ج | ج | ج | ج |
| 59:18:10 | 548 | لِغَدࣲۖ | ج | صلى | صلى | صلى | ج |

Nine of the thirteen are a ج that al-Azhar also has: the committee's own choices where it departs from Madinah.
