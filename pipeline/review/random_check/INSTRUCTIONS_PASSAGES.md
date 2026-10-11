# Fourth round: book → database (completeness and consistency)

Earlier rounds started from a database row and asked "does the book say
this?". This round starts from the BOOK: you get continuous passages and must
reconcile everything they state with the database. First read
`INSTRUCTIONS.md` (grades, blanket rows, wpos is 0-based) and
`INSTRUCTIONS_ATTRIBUTION.md` (who said it, reading conditions); for منار
also `INSTRUCTIONS_WIDE.md` (its `{quote} [n]` format, «ومثله» chains,
ordinals, both sides of reading splits).

Each packet: `book`, `surah`, `text` (a slice of that surah's section; it may
start or end mid-sentence — ignore a ruling cut off at either edge).

## Steps for each passage
1. **List every waqf ruling the passage states**: quote, grade (normalised:
   تام / كاف / حسن / صالح / جائز / قبيح / لا), who says it (empty = the
   author), any reading/i'rab condition. Include «ومثله / وكذا» items (they
   take the head's grade), ordinal items (الأول/الثاني), «ليس بوقف / لا يوقف»
   (grade لا), general statements («ورؤوس الآي بعد كافية»، «حيث وقع»), and
   relayed views the author rejects (they still get a row, credited).
   Skip: grammar or reading remarks with no waqf ruling, hadith chains,
   tafsir glosses.
2. **Find the verses** the passage covers (منار gives `[n]` ayah numbers; for
   the others use the quotes) and dump the DB rows:
   `python3 pipeline/review/random_check/show_rows.py BOOK SURAH FIRST LAST`
   (prints each verse's numbered words and every row, held rows marked).
3. **Reconcile**:
   - each ruling → its row (right word, grade, scholar, condition in note);
   - each DB row in the covered span → a ruling in the passage (or a blanket
     statement, or a chain). A row with no support in the passage is
     `unsupported` (only judge rows strictly inside the span the passage
     fully covers).

## Output
Write a JSON object to your result file:
```
{"passages": [
  {"book": "manar", "surah": 7, "ayahs": [12, 19],
   "rulings_in_text": 23, "matched": 21,
   "issues": [
     {"type": "missing" | "unsupported" | "wrong_grade" | "wrong_seat" |
              "wrong_attribution" | "missing_condition" | "held_but_plain",
      "ayah": 14, "quote": "…", "row_id": 123 (if any),
      "expected": "…", "evidence": "SHORT quote from the passage (≤ 20 words)"}
   ]}
]}
```
`held_but_plain` = a held [held] row whose ruling the passage states plainly
(it should be served). Be precise: report only what the passage decides.
Use your own uniquely named temp files if you script anything. Do not modify
any file other than your result file. End with a short summary per passage.
