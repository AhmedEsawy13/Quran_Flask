# Random check of the classical waqf books

You are checking rows of a database built from four classical Arabic books on
الوقف والابتداء against the books themselves. Be strict and literal: judge only
from the book text, not from your own view of where to stop.

Books (source files, Shamela markdown):
- muktafa = المكتفى في الوقف والابتدا، أبو عمرو الداني
- anbari  = إيضاح الوقف والابتداء، ابن الأنباري
- nahhas  = القطع والائتناف، النحاس
- manar   = منار الهدى في بيان الوقف والابتدا، الأشموني

## Each row (packet) has
- `surah`, `ayah`, `wpos`: where the ruling is seated. **wpos is 0-based**: the
  stop is AFTER word number `wpos` in `verse_numbered` (word 0 is the first word).
  `seated_word` is that word. `wpos` null means the row has no word seat.
- `quote`: the phrase the book quotes for this ruling (the stop is at its end).
- `grade`: normalized grade: تام / كاف / حسن / صالح / جائز / قبيح / لا (= no stop).
  `grade_raw`: the book's own wording (e.g. «أكفى منه», «رؤوس الآي»).
- `reported_from`: who the ruling belongs to when it is NOT the author's own
  (e.g. نافع, أبو حاتم, الأخفش, بعضهم). Empty = the author's own ruling.
- `note` / `illa`: reason or context taken from the book.
- `excerpts`: up to 4 passages of the book where the quote appears (with line
  numbers in `book_file`). They may be from the wrong surah; the book is ordered
  surah by surah, so find the passage for THIS surah/ayah. If no excerpt fits,
  search `book_file` yourself with Grep (the book's spelling is imlāʾī, mostly
  without vowels; try a distinctive word or two of the quote).

## Special row kinds (these are by design, judge them on their own terms)
- **Blanket rows**: `note` starts with «حكم عام». The author states a general rule
  («وكذلك رؤوس الآي بعد», «وكذلك الفواصل إلى قوله …») and the row applies it to one
  verse end. Correct if that general statement really exists, covers this verse,
  and no specific ruling in the book for this exact spot contradicts it.
- **منار «ومثله» rows**: منار says a later spot is «مثله»; the row copies the
  earlier ruling. Correct if the book links them that way.
- A book often gives several opinions on one spot. Each opinion is its own row,
  credited to whoever said it. Check only THIS row's opinion is really stated
  and credited correctly.

## For each row decide
1. **ruling**: does the book state this grade for this phrase at this spot?
2. **seat**: is the stop on the right word (end of the quoted phrase, right
   verse, right occurrence if the phrase repeats)? Off by a word = WRONG.
3. **attribution**: is `reported_from` right (empty when it is the author's own
   view; the named scholar when the author relays someone's view)?
4. **not a remark**: the text is an actual waqf ruling, not grammar, a variant
   reading, or an example.

## Output
Write a JSON array to the result file you were given. One object per row:
```
{"id": 123, "book": "nahhas", "verdict": "OK" | "WRONG" | "UNSURE",
 "problems": ["seat" | "grade" | "attribution" | "not_a_ruling" | "missing_context"],
 "expected": "what it should be, e.g. wpos 7 / grade كاف / reported_from أبو حاتم",
 "evidence": "the book line number and a SHORT quote (≤ 20 words) that decides it"}
```
Use UNSURE only when the book text is genuinely ambiguous or you cannot find
the passage after searching; say what you searched for. Do not modify any file
other than your result file. Finish with a one-paragraph summary: counts of
OK/WRONG/UNSURE and the WRONG ids with one line each.
