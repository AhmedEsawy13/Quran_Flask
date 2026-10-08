# Second round: who said it, and under which reading

You are checking rows of a database built from four classical Arabic books on
الوقف والابتداء. This round looks at two things only, strictly from the book
text: **attribution** and **reading/i'rab conditions**. Read
`INSTRUCTIONS.md` (same folder) first for the packet format (wpos is 0-based;
`seated_word` is the stop word; `excerpts` may be from the wrong surah, so find
the passage for THIS surah/ayah, searching `book_file` with Grep if needed).

Books: muktafa = الداني، anbari = ابن الأنباري، nahhas = النحاس، manar = الأشموني.

## 1. Attribution (`reported_from`)
Empty means the book's author states the ruling in his own voice. A name means
the author relays that scholar's view. Decide whose view THIS row's grade is:
- «قال X: {Q} تام», «{Q} تام عند X», «عن X تم», «على قول X / على مذهب X»,
  «وهو قول X» → X. «وقيل» / «وقال غيره» / «وقال بعضهم» → `قيل` / `غيره` /
  `بعضهم`.
- A relayed view stays credited to its scholar even when the author then
  rejects it («وهذا غلط»); the author's own counter-ruling is a separate row.
- A speaker's scope ends where the author resumes («قال أبو جعفر: …», a new
  «{X} قطع كاف» in the author's voice). «وكذا {B}» continues the view stated
  just before it (the LAST view on the previous quote, e.g. «… كاف عند أبي
  حاتم وكذا {B}» → B is أبو حاتم's كاف).
- If the author states the same grade himself after relaying it, own-voice is
  right.
- If two names share one view («عند محمد بن عيسى وأبي حاتم») either name is
  acceptable; say so in `evidence`.

## 2. Reading / i'rab conditions
- If the book ties the ruling to a reading or parsing («لمن قرأ …», «على
  قراءة …», «إن جعلت …», «فعلى هذا المذهب …»), check that **the condition is
  in the row's `note`** (or `illa`). Missing → problem `missing_condition`.
- If the reading is NOT Hafs (e.g. a different vowel/word than the mushaf text
  in `verse_numbered`, or a reading the book names as another reader's that
  differs from Hafs), the row should not exist as a Hafs ruling → problem
  `non_hafs_reading`. If you are not sure whether Hafs reads that way, say
  UNSURE and give the reading.
- Do not flag ordinary reasons («لأن ما بعده …») as conditions.

Also report any grade or seat error you notice, but do not hunt for them.

## Output
Write a JSON array to your result file, one object per row:
```
{"id": 123, "book": "nahhas", "verdict": "OK" | "WRONG" | "UNSURE",
 "problems": ["attribution" | "missing_condition" | "non_hafs_reading" | "grade" | "seat"],
 "expected": "e.g. reported_from أبو حاتم / note should carry «لمن قرأ بالرفع»",
 "evidence": "book line number + a SHORT quote (≤ 20 words) that decides it"}
```
Do not modify any file other than your result file. Finish with a short
summary: OK/WRONG/UNSURE counts and one line per WRONG id.
