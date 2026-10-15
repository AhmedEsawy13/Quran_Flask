# Adding classical waqf books without an LLM

## Policy

New books are imported with deterministic source adapters only. A parser may
read explicit typography and grammar (`{quote} [ayah] grade`, headings, lists,
and mechanically inherited chains), but it must not infer a ruling from prose.
Anything ambiguous is written to a review queue for a qualified human; it is
never guessed into the released database.

The existing Manar release is a historical exception: its cache was produced
with an LLM, then aligned and validated locally, and now has a deterministic
explicit-ruling completeness backstop. New books do not use that path.

## Pipeline

```text
fixed public-domain edition
        ↓ checksum
book-specific parser (no network, no model)
        ↓ JSONL candidates + source locator
shared strict importer
        ├── exact/prefix Qur'an alignment → accepted rows + provenance
        └── invalid/ambiguous/repeated phrase → review queue
        ↓
independent-edition comparison + coverage audit
        ↓
scholar approval of review queue
        ↓
catalog floors + tests + CI gate
```

The shared importer is `import_classical_book.py`. It enforces the closed
grade lexicon, ayah bounds, exact word alignment, explicit disambiguation of
repeated phrases, transactional replacement of one book, source SHA-256, and
per-row provenance. It performs no API or network calls.

## Per-book rollout

### 1. Freeze the edition

- Prefer a public-domain machine-readable edition plus an independent scan or
  second digitization.
- Vendor the source under `classical_sources/`.
- Add the title, author, source file, SHA-256, parser version, and initial
  coverage floors to `classical_books.json`.
- Never update a source silently. A changed checksum requires a catalog update,
  parser rerun, and reviewed diff.

### 2. Survey its syntax

Before writing the parser, count and sample every structural form the edition
uses:

- grade after quote: `{X} تام`;
- grade before quote: `التمام {X}`;
- explicit ayah markers;
- ordered lists (`فالتامة أربعة ...`);
- inheritance (`ومثله`, `وكذا`);
- reported opinions (`وقال فلان:`);
- page markers, footnotes, poetry, and editorial additions.

Each accepted pattern needs positive and negative fixtures. A bare grade word
near a quote is not enough when the same construction appears in ordinary
grammar or in a negation.

### 3. Emit candidates, not database rows

The adapter writes one JSON object per ruling:

```json
{"surah":2,"ayah":255,"quote":"السماوات والأرض","grade":"كاف","grade_raw":"كاف","note":"...","reported_from":null,"locator":"PageV01P123:paragraph-4","expected_wpos":43}
```

`locator` must identify the source page/paragraph or stable source record.
`expected_wpos` is required when the quoted phrase occurs more than once in
the ayah. Reasons and attribution must be copied from source evidence, not
rewritten or inferred.

### 4. Run the strict importer

```bash
python3 pipeline/import_classical_book.py \
  --source-key new_book \
  --title-ar 'عنوان الكتاب' \
  --author-ar 'اسم المؤلف' \
  --parser new_book_v1 \
  --source-file pipeline/classical_sources/new_book.md \
  --candidates /tmp/new_book_candidates.jsonl \
  --review-out pipeline/review/new_book.jsonl
```

This is dry-run by default. Inspect rejection counts and the review queue. Add
`--write` only after the candidates and review decisions are approved. A write
replaces that source alone in one transaction and refuses an empty import.

### 5. Prove completeness at the right level

Use three separate claims; do not collapse them into one:

1. **Structural completeness:** every mechanically recognizable explicit
   ruling in the source is represented or deliberately rejected with a reason.
2. **Alignment completeness:** every released row maps to a real word in the
   stated ayah and repeated phrases are disambiguated.
3. **Scholarly completeness:** a qualified reader checked discursive prose,
   reported opinions, alternative grades, and every review item.

Only the third claim supports saying the whole book has been exhaustively
interpreted. Regex coverage alone does not.

### 6. Cross-check and release

- Compare explicit ruling keys against the independent edition.
- Pin representative passages, negations, inherited chains, repeated words,
  and alternative opinions in tests.
- Set catalog floors slightly below the reviewed result so accidental losses
  fail CI while legitimate deduplication remains possible.
- Run:

```bash
python3 pipeline/audit_classical_catalog.py
python3 -m pytest -q tests/test_classical_import.py tests/test_classical_waqf_*.py
```

The GitHub workflow `classical-data-audit.yml` also runs the Manar strict
completeness audit and prevents its 102-item traceability review queue from
growing unnoticed.

## Recommended order for the current books

1. **المكتفى** — best next candidate: strong sequential structure; review the
   remaining genuinely unpinnable conf=0 rows in `/classical-review` and backfill
   stable page/paragraph locators. Run with `ENABLE_EDITOR=1`; the page stores
   approve/reject decisions separately and will not activate the book until
   every uncertain row has a decision and the reviewer selects «اعتماد وإضافة
   الكتاب».
2. **إيضاح الوقف والابتداء** — active since 2026-09-26 after audit_anbari.py
   (section mapping fixed, chains/negations/relays resolved, grade-before
   rulings added, reading splits resolved to Hafs); 106 rows stay held, 68 of
   them grade-before rulings that hinge on i'rab or a non-Hafs reading.
3. **القطع والائتناف** — active since 2026-09-27. pipeline/nahhas_parse.py
   reads its chains, blanket verse-end rules and whose verdict each ruling is
   (about a quarter are أبو حاتم، الأخفش، نافع … and carry `reported_from`);
   308 rows stay held.
4. **منار الهدى** — keep the released guarded dataset, review the exported 102
   heuristic suspects in the منار tab of `/classical-review`, then replace
   historical LLM-only discursive records incrementally with source-located
   deterministic or human-entered records. Rejecting a reviewed row suppresses
   it from the live API without deleting the underlying source record.

Current deterministic catalog audit baseline:

| Book | Rows | Surahs | Confident | Existing low-confidence review |
|---|---:|---:|---:|---:|
| المكتفى | 6,752 | 112 | 6,752 | 0 (incl. blanket verse-end rows) |
| منار الهدى | 13,405 | 114 | 13,405 | 0 |
| القطع والائتناف | 5,444 | 113 | 5,194 | 250 held (157 quotes not found in their surah, reading-dependent or far-jump seats) |
| إيضاح الوقف والابتداء | 2,434 | 112 | 2,336 | 98 held (68 i'rab/non-Hafs grade-before rulings, unplaceable single words, curated HOLD) |

Inheritance and ordinal audits (2026-09-26) — rerun after any rebuild:

```bash
python3 pipeline/audit_manar_mithl.py          # منار «ومثله/وكذا» chains + repeated-word seats
python3 pipeline/audit_muktafa_ordinals.py     # المكتفى «الأول/الثاني/في الموضعين» rulings
python3 pipeline/audit_muktafa_blanket.py      # المكتفى «ورؤوس الآي بعد كافية» statements
python3 pipeline/build_classical_waqf.py --only anbari && \
python3 pipeline/audit_anbari.py --apply       # إيضاح: seats, chains, relays, grade-before rulings (run twice)
python3 pipeline/build_classical_waqf.py --only nahhas && \
python3 pipeline/audit_nahhas.py --apply       # القطع: الفاتحة، ذوات قل، آخر السورة، curated fixes (loops until stable)
python3 pipeline/derive_illa.py                # العلّة + «ومثله» heads for all four books
python3 pipeline/audit_reading_side.py --apply # last: mark rows for a reading other than Hafs's
```

`derive_illa.py` stores each ruling's العلّة (`illa`) and, for a «ومثله / وكذا»
item, the ruling it follows (`follows`). The note is the book text around the
quote; `core/classical_illa.py` keeps only the reason (no chain wording, no
next item's ruling, no isnad), and the app shows the book text under «نص الكتاب».

Run them in that order (the blanket step fills only verse-ends no other
المكتفى row rules on).

Both are dry-run by default; `--apply` writes their curated, idempotent fixes.

These counts are regression baselines, not claims that the discursive books
have been exhaustively interpreted.

## Cross-check against quranpedia.app (2026-09-28)

quranpedia.app/uloom publishes the same five waqf books (ours plus السجاوندي's
علل الوقوف) cut per ayah, quotes vowelled. Its «ayah» is the page a passage
falls on, not each ruling's seat (it files «{ونقدس لك}» under 2:29), so it is
a cross-check, never a source of seats. Matched by ayah and last word it agrees
with 98% of منار and ~93% of المكتفى; every disagreement was read against the
Quran text and book order. What it found, now fixed and guarded by tests:

- multi-word quotes seated by their last word alone on a neighbouring verse
  (69:2 «وما أدراك ما الحاقة», 11:98 «ويوم القيامة», 43:32 «رحمت ربك» on the
  verse-end) — `test_multi_word_quotes_end_where_they_are_seated`;
- ابن الأنباري: «{الذين يؤمنون بالغيب} [3]» verse numbers after {…}, «…»-quoted
  stops, and «حسن الوقف على (X)» / «حسن أن يقف على» (grades the NEXT quote);
- النحاس: «يا أيها» is one mushaf word (token variants), elided quotes «{X ... Y}»
  stop on Y, «فوقف حسن / فقطع كاف», open tā' (كلمت/كلمة) in its seating only;
- the aligner's `norm` reads وٰ as ا (الصلوة/الزكوة/الحيوة = الصلاة/الزكاة/الحياة).


## Corpus sweeps (2026-10-07)

Run over all four books after the quranpedia pass, each disagreement read in the book:

- **Same-word stop vs «ليس بوقف»**: two rulings stacked on one occurrence of a
  word the verse repeats (2:13 «السفهاء»: كاف «لحرف التنبيه» is the first,
  the لا «للاستدراك» the second). 30 منار rows moved by curated
  `audit_manar_mithl.MOVES`; that dict now outranks the generic repeat-word
  mover and `explicit_seat_moves`, which only guess (pause mark / last
  occurrence). Guarded by `test_repeated_words_do_not_stack_a_stop_and_a_no_stop`.
- **Book order** (seq vs neighbours): المكتفى quotes that are the book's slips
  («تعلمون» for 7:43 «تعملون», «بيضاء» for 28:71 «بضياء») and a mid-verse
  «يؤمنون» that is 39:52's (hand-pinned).
- **Remarks read as stops**: «و «ثم» لترتيب الأخبار» (4:153), «و «كتب» أجرى مجرى
  القسم» (58:21) — `NOT_RULINGS` is keyed by the chain HEAD's verse — and a
  braced «{عند} غيره» in النحاس (`audit_nahhas.QUOTE_FIX`).
- 60-row random read (15 per book): 58/60 right; the two misses fixed above
  (58:21) and in `audit_nahhas.CURATED_BY` (42:45 «عند بعضهم»).

## Raising the per-book confidence (2026-10-07, second pass)

- **ابن الأنباري held rows** (98 → 78): every held row read in the book.
  `audit_anbari.SERVE` serves the plain rulings the audit could not seat
  (no [n]: «والوقف على «المصلحين» حسن»), his own verdicts against others
  («فلا يحسن الوقف على (العنكبوت)» — the first one, via `BEFORE_SEAT`) and the
  Hafs side of reading splits («أئن» بالكسر: «وقف: (طائركم معكم)»; 24:36
  «يسبِّح» → «الآصال» لا يحسن in `HAFS_ADD`). The 78 left are i'rab-conditional
  or non-Hafs grade-before rulings, a paraphrase, a grammarian's example and
  reviewed HOLDs.
- **النحاس attribution**: a 100-row read (60 attributed, 40 unattributed with a
  name nearby) found the name placed after the grade («تمام على ما روى عن
  نافع»، «تمام عند أبي عبيده») or between quote and grade («{X} عند نافع تم»)
  unread; the parser now reads all three (+29 attributions, each checked).
- **منار repeated words**: every ruling on a word its verse repeats checked
  against book order (the verse's previous and next rulings); 11 moved, one
  `explicit_seat_moves` side effect pinned with `SEAT_KEEP`; guarded by
  `test_manar_rulings_on_a_repeated_word_follow_book_order`.
- Fresh 60-row read after the fixes: 57/60; the three misses (2:282
  «إحداهما» the first, 2:51 الأخفش, and a ruling covered above) fixed.

## Recall and chain attribution (2026-10-07, third pass)

- **Recall check**: every «{X} GRADE» / «(X) GRADE» the four books state was
  matched to a row. Gaps fixed: المكتفى «تمام القصة / تمام الكلام» and «… وليس
  كذلك، هما كافيان» (`audit_muktafa_ordinals.MANUAL`, `RELAYED_BY` — a relayed
  ruling and الداني's correction both stand); النحاس grades on the line after
  «}» (`after` now strips newlines, +11); ابن الأنباري «وقف حسن:» (colon after
  the grade). منار had no real gaps (its section file overlaps at the last
  surahs; the DB rows are in the right surahs).
- **النحاس chains**: «وكذا {B}» continues the LAST view stated on the quote
  before it — «وهو كاف عند أبي حاتم»، «وقال غيره هو كاف»، «وغيره يقول هو الوقف
  الصالح»، «ولكنه قطع صالح» — not the first. «قال X» introduces a quote only if
  what stands between is waqf vocabulary or ends in a grade that introduces it
  («وقال غيره: هو قطع كاف، والتمام {X}»); «قال نافع: تم {X}» and «وقال نصير:
  أكره …» end X's scope. 40-row chain read: ~32/40 → ~38/40.
- `audit_nahhas --apply` repeats at most five passes and refuses to spin;
  MOVES skip rows already at their target.
- Final 100-row read (25 per book): 99/100, the miss (23:11) fixed.

## Random check by independent reviewers (2026-10-08)

240 rows (60 per book, `pipeline/review/random_check/make_packets.py`) were
split into 8 batches and read against the book by separate reviewers following
`pipeline/review/random_check/INSTRUCTIONS.md`. 224 OK, 12 WRONG, 4 UNSURE;
each flag was then re-read by hand:

- **المكتفى blanket scope**: «ومثله {X}. وكذلك الفواصل إلى …» anchored on an
  earlier verse when X ends two verses of the surah (33:3/33:48 «وكيلا»):
  `ANCHOR_FIX`. The audit now recomputes the whole expansion and removes rows
  that fall out of scope (it used to only add). Open «بعد» statements still
  run to the next statement or the surah end (the 14:42 and 25:15 flags are
  kept by design); «وكذلك رؤوس الآي بعد ((مسلمون)) تام» reads «… بعد [كافية].
  ((مسلمون)) تام».
- **منار**: 43:80 أبو حاتم's كاف sits on «بلى» (the «وقيل» on «نجواهم» has no
  grade); 3:45 «والآخرة» is only جائز; 17:104 «لفيفا» is the author's own
  (السجاوندي gives the reason). `REPORTED_FIX` can now clear a name (None).
- **ابن الأنباري**: 25:22 «[22 ي» is garbled — the own حسن on «محجورا» is
  added (`BOOK_ADD`) and the تام relayed «عن الحسن» (`RELAYED_BY`); 2:210
  «لا يحسن» on «الملائكة» is معاذ's non-Hafs reading (`DROP_ANY`).
- **النحاس**: 11:3 أبو حاتم, 4:162 «على مذهب سيبويه» (`CURATED_BY`). The
  sample's one unseated row led to all 97 held unseated rows: fuzzy-matched
  inside their book-order window, 55 confident, each read — 53 seated
  (`SEAT_HELD`), 2 rejected (not rulings on the quoted phrase). 44 stay held.
- Guarded by `tests/test_classical_random_check.py`.

### Second round: attribution and reading conditions (2026-10-08)

160 rows aimed at the weak spots (`make_attribution_packets.py`, brief
`INSTRUCTIONS_ATTRIBUTION.md`): per book 20 credited rows + 20 own-voice rows
whose note names another scholar or a reading. 149 OK, 10 WRONG, 2 UNSURE;
re-read by hand, 8 real plus 3 found while verifying:

- **منار**: 11:18 «{على ربهم} الثاني، قال محمد بن جرير: تم الكلام» was stored
  as لا (the «لا يوقف» is on «الظالمين», now its own row) and «الأول» sat on
  the second «ربهم»; 30:25 a duplicate on «الأرض» credited to نافع; 2:7 a
  «لا» on «سمعهم» credited to الفراء (the author's inference under نصب
  «غشاوة»); 13:33 the Hafs side is «مكرهم» ليس بوقف («وصُدّوا» الكوفيون), the
  كاف is the other reading's. `NOTE_FIX` replaces a note that carried another
  ruling's clause. منار keeps both sides of a reading split as rows whose notes
  name the reading (12:105 جائز «على قراءة عكرمة» + Hafs لا) — the explicit-ruling
  test requires the book's own head grade to stay.
- **المكتفى**: 29:58 «تام عند ابن الأنباري. وليس كذلك» (`RELAYED_BY`).
- **النحاس**: 2:259 نافع (and the missing «وكذا قال {أعلم أن الله …}»), 35:35
  الأخفش, 38:45 بعضهم; 38:45 «واذكر عبدنا إبراهيم» is ابن عباس's reading
  (`DROP_NON_HAFS`). «قال X {A} تمام الكلام {B} قطع تام» stays own-voice at B.

### Third round: wide check weighted toward منار (2026-10-08)

250 new rows (`make_wide_packets.py`, brief `INSTRUCTIONS_WIDE.md`): 150 منار
in four strata (plain, «ومثله» chain, reading-conditional, repeated word) +
~33 per other book; 10 reviewers. 232 OK, 16 WRONG, 2 UNSURE; re-read by hand.

- **منار ordinal heads**: three flags were «{X} [n] الأول/الأولى» on the last
  occurrence. A sweep of every ordinal head (phrase-matched against the verse)
  found 10, all moved (`MOVES`), plus the book's «والثاني ليس بوقف / أحسن منه»
  rows that were missing (`EXTRA`). Guarded by
  `test_manar_ordinal_heads_sit_on_the_named_occurrence`.
- **منار**: 2:89 «ومثله في عدم الوقف «كفروا»» is the first «كفروا»; 5:116 and
  2:69 rows on the wrong item dropped; 9:55 and 43:32 أبو حاتم; 56:10 the
  «ومثله» كاف added; scholar names normalized to the nominative («أبي حاتم» →
  «أبو حاتم», 31 rows).
- **المكتفى**: الشعراء's refrain «{إن في ذلك لآية} كاف. {مؤمنين} تام. {العزيز
  الرحيم} أتم منه. وكذلك جميع ما في السورة من ذلك» applied to its seven repeats
  (21 rows), replacing the general «ورؤوس الآي بعد كافية». A sweep of every
  other «حيث وقع / جميع ما في السورة» statement added 26 more: 2:1 «الم», 10:1
  «الر», 27:61–64 «أإله مع الله», 54's six «فهل من مدكر», 77's ten «ويل يومئذ
  للمكذبين»; the verse before each «ويل» («وكذلك ما قبل …») is a blanket row
  (`audit_muktafa_blanket.MANUAL_VERSES`) so its citation traces to the book.
- **النحاس**: 5:95 الأخفش, 58:8 يعقوب.
- Not changed (read and kept): 70:44 «ذلة» لا is the conditioned يعقوب-reading
  side beside the Hafs تام; 20:62 كاف on the «إنّ هذان» reading is the book's
  only ruling there, conditioned; «قال X {A} … {B} قطع …» stays own-voice at B.
- Many reviewers noted `note`s that also carry a neighbouring ruling's text —
  cosmetic (grades, seats and attributions right), not yet cleaned.

### Fourth round: book → database passages (2026-10-11)

24 random continuous passages (`make_passages.py`, brief
`INSTRUCTIONS_PASSAGES.md`, helper `show_rows.py`): the reviewer lists every
ruling the passage states and reconciles both ways. Precision held (few wrong
rows); recall was the gap (≈ منار 89%, المكتفى 88%, ابن الأنباري 76%, النحاس 72% of
stated rulings had a row — mostly relayed «وقيل» views and the other side of a
conditional ruling, which live in the notes). Fixed book-wide:

- **المكتفى blankets** took the grade of the NEXT ruling («إلى قوله {يصنعون}
  {فاتخذوه عدوا} كاف»): the span now stops at the next quote (42 verse ends
  كاف → تام); the audit also regrades rows still in scope (`plan` → add/drop/
  regrade).
- **النحاس parser**: «{X} مثله» (13), «{X} الأولى والثانية جميعا تمام»,
  «تم الكلام متصل» (= ثم, not a grade), «رؤوس الآيات X إلى آخر السورة» (5
  ranges); a range now starts from where the main pass seated its quote (book
  spellings «والأفئدة»، «لا يستوون» used to drop the range) and leaves verse
  ends the book rules itself; `VERSE_ENDS` for «والتمام رأس الآية (وكذا الآيات
  التي بعدها)»; +80 rows.
- **منار prose no-stops** «ولا وقف من قوله … فلا يوقف على «A»، ولا على «B»»:
  `prose_nostops()` seats each item on its single occurrence near the entry
  (prefix-tolerant uniqueness), note = the book's sentence, speaker from «قال X:»
  / «قاله X»; +125 rows; guarded by `test_manar_prose_nostops_all_have_a_row`.
- **Hafs sides** where only the other reading's row existed: منار 7:54, 47:31;
  المكتفى 40:20, 91:14 (`HAFS_SIDE`).
- Single rows: النحاس 32:5 الأخفش تام, 32:9 أبو عبد الله, 5:45 يعقوب, 2:143 seated,
  5:47 served; المكتفى 19:97 «لدا» moved, 4:123 أصحاب التمام; منار 9:71 قيل, 47:27
  own.
- **Open**: relayed «وقيل: X» views and the negative side of conditionals that
  sit only in a note (shown to the reader, but not separate rows); ابن الأنباري's
  «غير تام» (a negation, not a grade); النحاس ungraded «ثم الوقف {X}» stops and
  «كل أمر ونهي ها هنا إلى …» spans.

### Follow-up: recall patterns (2026-10-11)

- **ابن الأنباري**: comparatives before the quote («تام، وأتم منه: (X)»,
  «وأحسن منه: (X)») and «(X) هذا وقف تام» are read (+16); prose relays
  «قال الفراء: … تمام الكلام على (X)», «وقال المفسرون: الكلام يتم على (X)»
  curated (`BOOK_ADD` + `RELAYED_BY`, relay applied after the adds so one pass
  is complete). Most remaining gaps are by design: «غير تام» (108 — a negation,
  not a grade) and «فعلى هذا المذهب / لم يتم الكلام على» reading- or
  i'rab-conditional rulings (held).
- **النحاس**: «والتمام عند X {A} وعند غيره {B}» — B is the others' تمام (21
  places, none parsed before).

### Second passage check (2026-10-11)

24 fresh passages (`make_passages.py 2`, surahs not drawn before); every
missing ruling now carries a `kind` (plain / in_note / conditional_side /
ghayr_tamm / ungraded). Plain-ruling recall: منار 98%, المكتفى 97%, النحاس 77%,
ابن الأنباري 60%. Fixed:

- **ابن الأنباري**: «ومثله: (A) [3] (B) [4] (C)» — list items joined only by
  «] (» / «، (» now chain when the list opens with «ومثله / وكذلك» (`grade_at`,
  +104); المجادلة's quotes in {…} read as (…) in `anbari_sections` (+11);
  graded inserts take the seq after every earlier seat (a later verse's chain
  head was being found after its items).
- **النحاس**: «(X) قطع كاف» — graded quotes the copy put in parentheses become
  {X} in `nahhas_sections` (23); «هذا كله عن X» runs (13:16 الأخفش, 6:30–35
  نافع via `EXTRA_AT`); 81:21, 35:10 أبو حاتم.
- **المكتفى**: «سيقولون لله» في الثلاثة, 8:42 «وهو التمام», 21:20 أحمد بن موسى.
- What remains of the gap is mostly by design: «وقيل» views and the other
  side of conditionals kept in notes (المكتفى 26, منار 1 in this sample).

### Third passage check: النحاس and ابن الأنباري (2026-10-11)

16 fresh passages (`make_passages.py 3 nahhas:8,anbari:8`). Plain-ruling
recall: ابن الأنباري 93% (was 60% before the list/brace fixes), النحاس 69%.
النحاس fixes: «رؤوس الايات» without madda in ranges (4); ungraded «وكذا رؤوس /
آخر الآيات إلى {X}» takes the previous grade (11); «والتمام على ما روى عن X
{Y}» grade-before credited to X (46), kept as a second view when the quote also
has its own grade after it. +80 rows. Most of النحاس's remaining gap is by
design: «ليس بتمام / ليس بقطع كاف» (a negation, not a grade) and prose relays
the parser cannot scope.

### Fourth passage check: منار، المكتفى، ابن الأنباري (2026-10-11)

24 fresh passages (`make_passages.py 4 manar:8,muktafa:8,anbari:8`). Plain
recall before fixes: منار 97.6%, المكتفى 91.4%, ابن الأنباري 86.5%. Fixed:

- **ابن الأنباري**: «ومثله» lists that run over «]. » and line breaks (+192).
- **المكتفى**: an open «بعد» range ran only to the next statement of any kind —
  a single «ورأس الآية أكفى منه» cut it off; now only range statements do
  (+87 verse ends); «والتمام آخر السورة» (110, 114); «مثله {X}» without «و» and
  «{X} مثل {Y}» (6:25, 45:10, 98:4, 111:2); 111:4 «وامرأته» (Hafs نصب «حمالة»).
- **منار**: prose no-stops «على قوله: «X»» and those before the first «[n]»
  (+8); 31:14 أبو حاتم ×3 and العماني; 5:64 بعضهم; 8:65 «لا يفقهون» حسن; 33:13
  duplicate dropped.

### Fifth passage check (2026-10-11)

24 fresh passages (`make_passages.py 5 manar:8,muktafa:8,anbari:8`). Plain
recall: المكتفى 94.8%, ابن الأنباري 90.7%, منار 84.4% (one range statement in 53
and a few items in 89 made most of منار's gap). Fixed:

- **ابن الأنباري**: a chain item cannot be a quote followed at once by «قال /
  كان / غير تام / ليس / لا يحسن / لم يتم / فيه وجهان» — those open a discussion
  or negate (37:126, 11:40, 8:51 …, −12 rows). A closing grade after a
  «، (»-joined group is NOT shared (4:11 «… وقوف حسنة غير تامة»).
- **المكتفى**: الرحمن's refrain («كل شيء في هذه السورة من {فبأي آلاء ربكما
  تكذبان} تام ما لم يتعلق», 30 verses, blanket so explicit rulings win); 70:21 لا
  («إلا المصلين» استثناء — pinned, the لا sits before the quote); «المر» row
  seated on 10:12 dropped; 43:81 الحسن وقتادة, 55:62 ابن الأنباري.
- **منار**: 53:41–50 «ولا يوقف على شيء من أواخر الآيات … في ثلاثة عشر موضعا»;
  89:7 «{بعاد إرم} وقف عند نافع» on «إرم»; 89:14 الأخفش.

### Sixth passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 6 manar:8,muktafa:8,anbari:8`), reviewed by
an OpenAI model through `random_check/run_openai.py` (key in `.env`; the model
gets `show_rows` and a book search as tools, via `/v1/responses` because chat
completions refuses tools with reasoning on). Its ruling counts are inflated
(blanket verse ends counted one by one), so recall was not computed from them;
every issue was checked against the book. Its «ungraded» claims on bare
«(X) [n].» lines under «ومثله» contradict the list rule and were rejected, as
were «بعضهم» blanket views (kept in notes like «وقيل»). Fixed:

- **المكتفى**: «والفواصل بين ذلك كافية» after a surah-wide refrain («جميع ما في
  السورة»، «حيث وقع في السورة»، «أواخر القصص فيها») spans first to last
  occurrence, not just up to the anchor — 26:9–191, 37:60–148, 38:29–48,
  54:8–51; 74:3–7 «كل آية بعدها كافية» (+134 blanket rows). 9:30 (an editor's
  bracketed restoration), 74:31 «[ومثله]», 74:53 «{كلا} أيضا تام», 89:14 «جواب
  القسم … وهو تام»; 56:27 moved to the second «اليمين».
- **ابن الأنباري**: scan slips «[43 ي» → «[43]» (13 in the book) and «[116]. وقف
  تام» (the full stop hid the grade, so the list's حسن won); «قرأ» after a quote
  opens a reading discussion, not a list item (68:14); 82:5/82:12 «… وهو وقف
  التمام. ومثله», 16:125 «[مثله]».
- **منار**: 52:29 «كاف؛ … قال الخليل:» is the author's grade (الخليل gives the
  reason only).

### Seventh passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 7 manar:8,muktafa:8,anbari:8`). About a
third of the model's findings held up against the book. Fixed:

- **المكتفى**: «[ومثله] {X}» items (7:74, 7:176); a bare quote between two
  «ومثله» items (7:92); «{X} … تام. وهو عندي كاف» (15:13, and 26:201 «وفي
  الشعراء»); 60:1 «وكذلك هو عندي» (حسن beside نافع's تام); 60:4 «والتمام {X}»;
  60:1 «أولياء» credited to نصير بن يوسف ومحمد بن عيسى; seats: 7:96 → 7:39
  «تكسبون» (by book order), 15:25 to the verse end (the book reverses «حكيم
  عليم»; pinned), 60:10 → 60:11 «مثل ما أنفقوا» (`ID_MOVES`).
- **ابن الأنباري**: «(X) [n] مثله» takes the previous graded quote's grade (3
  in the book); the discussion guard no longer cuts a direct «ومثله: (X)» item
  (11:44) and also stops at «قد» (74:53 «قد استقصينا أمرها»).
- **منار**: 15:72 «والوقف على «لعمرك» قبيح»; 44:5 «مرسلين» حسن is the
  author's (سعيد بن جبير's reading is the «لا» side).

### Eighth passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 8 manar:8,muktafa:8,anbari:8`); most model
findings were by-design kinds or wrong (several cited evidence from another
surah). Fixed:

- **المكتفى**: 37:4–5 «جواب القسم: {X} وهو وقف كاف. {Y} التمام»; 68:5–9 «وقال
  المازني … وقال غيره {بأيكم المفتون} التمام. ومثله …» credited (the chain
  continues غيره); `RELAYED_ADD` inserts relayed views that had no row at all
  (38:25 يعقوب والدينوري «فغفرنا له», 68:6 غيره) — RELAYED_BY only relabels.
- **ابن الأنباري**: «[ومثله]:» (the editor's bracket) opens a chain (65:1).
- **منار**: 34:13 ابن كثير is cited for the ياء, not the ruling; 57:4 stray
  جائز beside «أحسن مما قبله» deleted.

### Reviewer calibration and the wrong-word check (2026-10-11)

12 known errors were planted in a DB copy (`CLASSICAL_WAQF_DB`, read by
`show_rows.py`) under round-7/8 passages, twice. gpt-6-luna caught 8/12 and
8/11: wrong grades, invented rows and wrong credits every time; deleted and
held rows about two in three; rows moved off their word never. 10-verse dumps
and two merged passes gave no clear gain (`--passes` defaults to 1).

`pipeline/review/seat_check.py` (and `tests/test_classical_seats.py`) covers
the gap mechanically: a row's quote must end on its seated word, compared by
consonant skeleton (waṣla/dagger alif, hamza seats, prefixes, one-edit typos),
and no other word of the verse may fit the quote's closing run better. It
caught all three planted moves and six real ones — المكتفى 4:78 «قل كل من عند
الله», 6:158 «بعض آيات ربك», 9:37 «فيحلوا ما حرم الله», 20:69 «كيد ساحر»; منار
2:14 duplicate on «إنا». Book slips are pinned (7:18, 9:51, 16:33, 101:10).

### Ninth passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 9 manar:8,muktafa:8,anbari:8`). Fixed:

- **ابن الأنباري** (text clean-up in `anbari_sections`): «ب 6]» → «[6]» (4),
  «[حسني» → «حسن», «[151]. حسن» (the grade after a full stop, not only «وقف
  …»), «[1، 2] وقف حسن» / «[78، 79] وقف التمام» → the last verse's marker (9);
  «مثله:» without «و» opens a chain; «وأحسن منهن:» comparative.
- **المكتفى**: 24:28 «{هو أزكى لكم} شبيه بالتام ورأس الآية أتم», 24:45 «وآخر
  الآية أتم منهما»; relayed views with no row: 18:22 الزجاج, 18:44 الدينوري (on
  «هنالك»), 48:29 مجاهد; 18:63 credited to بعض أهل التأويل.
- **منار**: 104:3–4 «{أخلده (3) كلا} [3، 4] تام» stops on «كلا» (the wrong-word
  check caught the first attempt, a move that left the quote «أخلده» on «كلا»).

Left as is: 5:76–87 (an open «وكذلك رؤوس الآي بعد» after a تام overlaps «ورؤوس
الآي قبل ذلك كافية»; the book does not say where one ends), 36:52 (a range «إلى
قوله {من مرقدنا}» that ends mid-verse), 89:16-style «وكذلك» after «وقيل».

### Tenth passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 10 manar:8,muktafa:8,anbari:8`). Most real
gaps were المكتفى general statements with no rows at all:

- 81:1–13 «جواب {إذا} {علمت نفس ما أحضرت} ولا تمام دونه، وهو تام. ورؤوس الآي
  بين ذلك كافية» (+ 81:14 تام); 72 «والوقف على رأس كل آية كاف. ويتم على …»
  inside «قال بعض العلماء: …» — credited (`STATEMENT_BY` for the blanket rows,
  RELAYED_ADD for 72:5, 7, 15); 69 «سائر هاءات الاستراحة في هذه السورة» (كتابيه،
  حسابيه، ماليه) and «ورؤوس الآي بين ذلك كافية» (69:30–50); 112:4, 113:5
  «والتمام في آخرها» (`test_asr_and_falaq_have_no_db_rows` now expects 113:5).
- «والآية أتم» / «ورأس الآية أتم» over a blanket كاف (3:122, 25:16, 25:20,
  28:35, 60:3): these verse ends have no quote in the book, so the row carries
  the mushaf word with grade_raw «رأس الآية» and is traced by its note (like
  «آخر السورة»), in the quality test and `core.classical_review`.
- 77:7, 81:21 نافع, 81:27 / 28:25 «لا».
- **منار**: 82:7 «وجوز بعضهم الوقف على: «فسواك» لمن خفف «فعدلك»» (Hafs reads
  it light) on «فسواك»; 112:3 «كذا وسمه بعضهم بالكافي» credited.

### Coverage sweep (2026-10-11)

1,637 of 6,236 verse ends had no المكتفى row. The 29 surahs over half uncovered
were searched for general phrasing (`رؤوس الآي`, `الفواصل`, `رأس كل آية`, `بين
ذلك`, `لا وقف … إلى`): most short late surahs simply have few rulings (the gap is
the book's). One systemic fix: «قبل ذلك» / «قبل وبعد» ranges now start after the
previous statement or at the surah start, as the docstring always said; «بين ذلك»
keeps starting at the «ومثله» head (70:35 «{فأوعى} … ومثله {مكرمون} والفواصل بين
ذلك» is between those two). +64 rows: 50:1–28, 19:1–20, 9:1–10, 5:1–30,
16:78–88, 18:60–62, 59:1–8. Left as is: 76 «وبين ذلك وقوف كافية» and 79 «وبين
ذلك وقوف كافية حسنة» (stops, not verse ends).

### Eleventh passage check (2026-10-11, gpt-6-luna)

24 fresh passages (`make_passages.py 11 manar:8,muktafa:8,anbari:8`); the
quietest round so far (about ten real items). Fixed: المكتفى 25:21 «كاف عند
أبي حاتم وابن الأنباري وابن عبد الرزاق وهو عندي تام» (credit + own تام), 12:52
«تمام الكلام», 27:43 «ورأس الآية أتم»; منار 102:5 «علم اليقين … أكفى مما قبله»,
12:15 «يحسن الوقف على «الجب»»; ابن الأنباري 26:208 «وهذا عندنا وقف حسن» (after
a line break). The blanket anchor now asks for one verse, not one row: a second
row on the anchor quote (25:21) had pushed «والفواصل تامة» back a verse. The
runner retries `http.client` errors (a cut-off response stopped the run).

### Twelfth passage check (2026-10-12, gpt-6-luna)

Every ابن الأنباري surah had been drawn once (المكتفى: 11 left), so
`make_passages.py` now falls back to an unread stretch of an already-drawn
surah; earlier passages are located by 60-character probes, since cleaned scan
slips changed the section text. Fixed:

- **المكتفى**: 53 «والوقف {وما ينطق عن الهوى} وهو كاف. ومثله {يوحى} …» (7 rows;
  «والوقف {X} وهو كاف» opens no chain for the parser); «جواب القسم {X} فلا وقف
  دونه» → «لا» on the oath verses before the answer (51:1–4, 52:1–6, 53:1;
  grade_raw «رأس الآية»); 50:42 «وهو كاف», 83:28 «المقربون» الثاني, 59:15
  الأخفش, 44:53 الحسن; 20:77 «لا تخف دركا» dropped (the jussive reading).
  «X. كذلك» stays on X — `test_period_quotes_pin_before_the_period` records that
  convention.
- **منار**: 56:18–20 «ولا على «أباريق» ولا على «من معين» … ولا على «يتخيرون»»;
  20:55–57 «كلها وقوف تقرب من التام» → كاف (MISMATCH_OK).
- **ابن الأنباري**: 5:68 «فلا تأس على القوم الكافرين. تام.» (no parentheses in
  the copy); 8:3–4 «ويحسن الوقف على قوله أيضا: (…) ويتم على قوله: (…)».

### Thirteenth passage check and accuracy (2026-10-12, gpt-6-luna)

21 passages (ابن الأنباري had only 5 unread stretches left). Accuracy before
this round's fixes, explicit rulings only (by-design kinds excluded): rulings
held = DB rows whose quote occurs in the passage; misses = issues confirmed
against the book.

| book | held | confirmed misses | completeness | ÷ ⅔ catch rate | wrong rows |
|---|---|---|---|---|---|
| منار | 220 | 2 | 99.1% | ≈ 98.7% | 0 |
| المكتفى | 335 | 4 | 98.8% | ≈ 98.2% | 0 (2 blanket verse ends graded كاف for «أتم») |
| ابن الأنباري | 179 | 11 | 94.2% | ≈ 91.6% | 1 credit |

Most ابن الأنباري misses were one bug: the chain look-back was 16 characters,
shorter than «وكذلك الوقف على قوله: »; now 30, and «كذلك» without «و» counts
(2:200–231, 7:101). Also «(توبة من الله). حسن», 2:205 / 2:215 quotes without
parentheses, 2:28 «غير تام وهو حسن», 4:46 «لكان خيرا وأقوم» (the book drops
«لهم»), 4:83 «وقال قوم» credit. المكتفى: 22:27 صالح, 3:34, 33:33, 22:41, 11:109.
منار: 93:1–2 «ولا وقف من أولها إلى: {قلى (3)}».

### Fourteenth passage check and accuracy (2026-10-12, gpt-6-luna)

22 passages (ابن الأنباري: 6 unread stretches of 2–4). Accuracy before this
round's fixes, measured as in round 13:

| book | held | confirmed misses | completeness | wrong rows |
|---|---|---|---|---|
| منار | 100 | 4 | 96.2% | 0 |
| المكتفى | 375 | 3 | 99.2% | 1 credit |
| ابن الأنباري | 240 | 5 | 98.0% (94.2% before the round-13 chain fix) | 0 |

Rounds 13–14 together: منار 98.2% (320/326), المكتفى 99.0% (710/717). Not
counted above: two ابن الأنباري general statements with no rows (2:51–56, 2:280).

Fixed: ابن الأنباري «(A) وعلى (B) GRADE» — A shares B's grade (2:4, 2:58, 3:86,
2:260); verse ends it rules without quoting (2:51–56 «رأس كل آية إلى قوله: (…)
[57] حسن», 2:280 «آخر الآية التي قبلها») as grade_raw «رأس الآية», which the
seat audit and `renote` now skip; 2:251, 2:258. المكتفى: 2:26 credited to
الدينوري والنحاس, 7:172 relayed, 7:30, 3:156, 4:157, 4:155–160. منار: 77:5,
111:1, 55:22, 55:26. Left: 91 (a conditional pair), 3:175 / 4:148 (whether a
mid-verse statement covers its own verse end).

### Own-voice conflict check (2026-10-12)

One word graded twice by the same book in its own voice reads, in the app, as
«وجهٌ آخر عنده» — the author contradicting himself. Checked every such seat:

- **منار**: 37 rows were the book's relayed view stored as the author's —
  «{حذر الموت} [19] حسن، وقيل: كاف» (also «… وقيل: كاف، وقيل: تام», «ومثله …
  وقيل: حسن», «وكاف عند أبي حاتم»). Credited via REPORTED_FIX;
  `pipeline/review/qila_check.py` / `tests/test_classical_qila.py` keep the
  «G1، وقيل: G2» form at zero. Misplaced duplicates: 5:27's second «لأقتلنك»
  is 5:28 «لأقتلك» (pinned — `test_stop_phrase_words_occur_in_the_verse` now
  honours pins), 42:15 «بينكم» the first occurrence, 5:31 duplicate removed.
  The remaining ~60 conflicts are reading/i'rab splits (one side carries the
  condition), which منار keeps by design.
- **ابن الأنباري**: a quote followed by «الوقف على …» opens a discussion, not a
  list item (3:169, 27:43 had inherited a grade beside the real one).
- **المكتفى**: 16:8 «وزينة» تام is ابن الأنباري's.

Open: 296 served rows (منار 251, المكتفى 45) are tied to a reading («لمن قرأ
…»). Both sides are kept with the condition in the note; which side is
Hafs's is not marked.

### Rulings for another reading than Hafs's (2026-10-12)

منار and المكتفى keep both sides of a reading split, each with its condition in
the note («كاف لمن قرأ "نفصل" بالنون»). 297 served rows were tied to a reading;
each was classified by comparing the note with the Hafs text (gpt-6-luna, then
every verdict read by hand — 25 corrected, e.g. 3:114 «بالتحتية فيهما», 73:8
«ربُّ» بالرفع and 11:110 «من شدد النون والميم» are Hafs's). 166 hold only
under another reading (منار 145, المكتفى 21): `pipeline/review/reading_side.json`
→ `pipeline/audit_reading_side.py` sets `classical.reading = 'other'`, the API
returns `reading`, and the app labels them «على غير قراءة حفص» (Next.js
imam-rulings and the legacy guide); the «اتفق / اختلف الأئمة» summary ignores
them. `tests/test_classical_reading.py`.

### Fifteenth passage check (2026-10-12, gpt-6-luna)

15 passages (المكتفى and ابن الأنباري are nearly out of unread text). Accuracy
before this round's fixes: منار 99.4% (159 held, 1 miss, 1 credit), المكتفى
98.0% (244, 5 misses, 2 credits), ابن الأنباري 96.5% (82, 3 misses). Fixed:
المكتفى 4:8 «وآخر الآية أكفى», 4:24 «تمام القصة», 4:30 «[يسيرا] تام», 5:25
«وأخي» كاف, 7:190 «كاف عند أصحاب الوقف، وهو عندي تام» (credit + own), 5:20 نافع;
منار 105:4 «وهكذا إلى آخر السورة», 13:1 «وقيل: هي قسم … لا يوقف عليها» credited;
ابن الأنباري 2:24 «(لم) في (تفعلوا) قبيح … (تفعلوا) الأول والثاني قبيح»
(KEEP_SEAT keeps both occurrences). Left: 2:87–96 «ثم الوقف على رؤوس الآيات إلى
قوله …» (no grade).

### ابن الأنباري coverage sweep (2026-10-12)

Every graded quote in the book was checked for a row in its surah. The standard
«(X) [n] GRADE» form had 3 gaps: 7:195 is the existing «فلا تنظرون», 25:60 a
reading other than Hafs's, and 70:15 «لظى» real (below). Other forms («يحسن الوقف على …», «الوقف على (X) … GRADE», quotes
without parentheses): 64 hits, nearly all «غير تام», conditional parses or
other readings. Added: 2:5 «ربهم» حسن (no parentheses), 38:84 «(الحق) الثاني»
قبيح (KEEP_SEAT), 70:15 «لظى» حسن (Hafs «نَزَّاعَةٗ»: HAFS_ADD). Held rows with
no condition (15): served 2:5 «أولئك» قبيح and 37:138 «وبالليل» تام (SERVE,
pinned), 29:66 «يتمتعوا» حسن (the لام كي parse is Hafs's: HAFS_SIDE); the rest
are held on purpose (HOLD, other-surah citations, an example sentence, «غير تام»).

### المكتفى / منار coverage sweep (2026-10-12)

The ابن الأنباري sweep, extended to the other two books and kept as a check:
`pipeline/review/coverage_check.py` lists every quote followed by a grade word
with no row ending on the same word (skeleton match; منار at the verse its
«[n]» names), and `tests/test_classical_coverage.py` fails on any gap not in
`pipeline/review/coverage_exceptions.json` (book slips whose row sits at the
right seat, other-reading sides — each with its reason) or on a stale exception.

Found: المكتفى «جواب القسم {X} وهو GRADE» — «وهو» before the grade had left the
oath answers and their «ومثله» chains without rows (82:5, 8, 12, 16; 86:4;
90:4; 92:4; 93:3–4; 95:4, 6) — and «تام على القراءتين / في كلا الوجهين» (14:2,
28:68, 29:66); منار 44:2 «{حم (1) والكتاب المبين (2)} حسن؛ إن … وليس بوقف إن …»
(both sides) and relayed «كلا» views 70:15 (الأخفش والفراء وأبو حاتم), 70:39
(نافع), 74:16 (الأكثر).

### النحاس: first pass (2026-10-12, gpt-6-luna + sweep)

12 passages (round 16) plus a full-book sweep. Before the fixes, about 87% of
the explicit rulings in the passages had rows (217 held, ~31 confirmed misses),
and most verse-end ranges were missing. Fixed:

- **Plain «"…"» quote marks** (المؤمنون، النور): the copy quotes with straight
  quotes there and drops some, so they were never read (23:55–100 had 3 rows).
  `_nahhas_requote` turns each stretch between two marks into a quote only if
  it is short Arabic with no commentary words — pairing marks in order shifted
  every later quote. 23: 3 → 82 rows, 24: 21 → 68.
- **Verse-end ranges** «ثم القطع على رؤوس الآيات GRADE إلى {X}»: the expansion
  needed X seated by the main pass, so a range whose X has no grade of its own
  (8:63) or an orthographic variant («فأنظر»، «الرحمن»، «السموات») was dropped;
  X and the quote before it are now found by a level-2 match. Also «القطع على
  الآيات … إلى» (no «رؤوس») and «وكذا رؤوس الآيات بعده إلى». Range rows 388 → 658.
- «ثطع» for «قطع» (38:34); 11:81 «بالنصب والرفع فإنه كاف»; relayed 11:87 يعقوب,
  11:107–108 أبو حاتم (الأول والثاني), 38:41 محمد بن عيسى; 23:11 duplicate on the
  verse end dropped (DROP_AT). The wrong-word check now covers النحاس (3 slips pinned).

Not rows (by design): «ليس بكاف / ليس بتمام» negations, «ومن الوقف {X}» stops
with no grade, other readings and conditional parses.

### النحاس: second pass (2026-10-12)

Round 17 (12 fresh passages), measured after the first pass: ≈ 95.5% of the
explicit rulings had rows (262 held, 8 confirmed misses + ~4 likely relayed),
2 wrong credits — up from ≈ 87% in round 16. Fixed: ranges with a qualifier
(«كاف على أن تبتديء الخبر إلى»), «والتمام على أواخر الايات إلى» (grade first),
«كيلا» / «لكيلا» split as in the mushaf (seating variant; ابن الأنباري unchanged),
doubled braces «{{…}}»; أبو حاتم's «وقف جيد / الوقف الجيد» read as حسن (the book
pairs them: «وقف جيد حسن»); hand additions (EXTRA_AT, now with an optional raw
«رأس الآية» for unquoted verse ends): 88:17–20 أبو حاتم, 73:1–3 نافع, 54:46,
54:50 أبو حاتم, 54:51, 59:23; credits 73:4 and 89:7 to نافع.

### النحاس: third pass (2026-10-12)

Round 18 (12 fresh passages). Before its fixes: 212 explicit rulings held;
confirmed 21 misses in النور 43–58, where the copy lost its quote marks
altogether («قال أحمد بن موسى: يكاد سنا برقه يذهب بالأبصار، تمام» — read by
hand, EXTRA_AT), ~15 other misses (mostly relayed: 46:17–18 غيره, 40:50 أبو
حاتم/غيره, 33:22 الأخفش, 51:20 يعقوب, 53:32 نافع, 66:1 محمد بن عيسى; own:
33:26–27, 39:22, 39:24 «(…)»), and 12 relayed views stored as the author's
(«قال الأخفش … والتمام {X}», «والتمام عنده {X}», «وقيل {X} كاف»). Outside النور
that is ≈ 93% complete. The traceability test now treats «، ؛ ؟» as word
separators on both sides (quotes without marks end before a comma), and «قيل»
is a known credit for النحاس.

### النحاس: credit sweep (2026-10-12)

Round 18 showed relayed views stored in the author's voice, so every own-voice
conf=1 النحاس row was checked for a speaker cue in its sentence before the quote
(«قال/عند/وعن/زعم/وخالفه X», «عنده», «وقال غيره», 211 rows). The 56 with no grade
of the author's right after the quote were each read in the book: 37 credited
(CURATED_BY — e.g. «وخالفهما أبو حاتم وجعل التمام {وهم يطمعون}», «زعم الأخفش أن
التمام {ألم نشرح لك صدرك}», «وقيل: ليس بتمام … ولكنه كاف»; 79:14 is a view
النحاس calls «خطأ»), 2 regraded («والكافي عنده بعده {X}» was stored تام — 30:44,
43:80), 2 dropped (cross-references «لأن بعده {وعد الله}» 39:20, «{وعمروها أكثر
مما عمروها}» 30:9), and 2 added (40:9 «وهما عند أبي حاتم كافيات»). Left in the
author's voice by design: «X كاف عند أبي حاتم والتمام {Y}» with no «عنده», views
النحاس adopts («والقول ما قال أبو حاتم»، «وهو الصواب»), and conditionals («ومن
قال … فالتمام عنده {Y}»، «ومن قرأ …») whose note carries the condition.

### النحاس: round 19 (2026-10-12)

12 fresh passages, after the credit sweep. gpt-6-luna matched ≈ 211 rulings and
raised 83 issues; about 50 were by-design non-rows (negations, ungraded stops,
conditional sides, non-Hafs readings) or misreadings («تم التمام بعده»). The
confirmed ones: ≈ 25 misses (unbraced quotes in الأنبياء 33/46/47/52, inverted
braces at نوح 12, verse-end rulings «والتمام رأس الاية» at الفتح 17/19/26 and
الشورى 16, two unexpanded ranges — يونس 41–49 «إلى رأس الخمسين» and القلم 45–52
«إلى آخر السورة» — 3 held rows served, 7 relayed views), 10 credits (8 relayed
views still in the author's voice, e.g. 45:21 نافع, 42:24 أبو عمرو بن العلاء),
1 wrong grade (90:11 كاف → تام), and 2 stale rows. Observed completeness ≈ 89%
(lower than round 18 — the unbraced and inverted-brace stretches). New: OWN_BY
credits only the own-voice copy when a credited row shares its quote; one own
grade per word holds (50:25 keeps the first of three parses, the note the second).

### النحاس: whole-book brace scan (2026-10-12)

Round 19's misses clustered where the copy lost its quote marks, so the whole
book was scanned: Quran text (≥ 2 contiguous words of the surah) right after a
ruling cue («وكذا / والتمام / والكافي بعده / الوقف الكافي …») but outside braces,
and every unbalanced «{ }». Fixes at the source (build_classical_waqf
`_NAHHAS_BRACE_FIXES`, line-break tolerant): 17 dropped/swapped marks
(«ولكن يناله التقوى منكم}», «} يا أيها النبي … العدة {هذا», «{ذلك} بأنهم …}»
which had seated 47:9 on its first word, 47:1's section start), mixed
brackets «{X)» / «(X}» (29:7, 29:39, 33:47, 34:15 …), and «والتمام عند {X}»
which the parser read as a scholar's name (10:40, 13:30). Unbraced rulings read
by hand (EXTRA_AT): النور 38–42 (the lapse before 43–58), 7:40–41, 40:57, and
relayed views quoted without marks (2:28 أبو حاتم, 2:217 أبو حاتم, 17:20 أبو
حاتم, 23:67 العباس بن الفضل, 24:40 أحمد بن جعفر). Net +35 rows, 1 wrong seat
fixed. A test pins brace balance (only 43:88's garbled «وقيله» passage remains).
The rebuild also restored an own-voice «والتمام {فإذا هم بالساهرة}» (79:14) that
an earlier merge had folded into the relayed row. Left as is: the copy's typo
«آكنوا» (47:3), since quotes must stay traceable to the book's own spelling.

### النحاس: round 20 (2026-10-13)

12 fresh passages after the brace scan. gpt-6-luna matched ≈ 307 rulings and
raised 80 issues besides ungraded / conditional ones; ≈ 30 were by-design
non-rows («ليس بكاف»، «وقف بيان»، محمد بن عيسى's «أجاز الوقوف» — النحاس has no
جائز grade, as with 30:9's «وأجاز نصير»), a fabricated quote (60:1 «وعند غيرهما
وأن تؤمنوا»), or extra co-credits (first name kept). Confirmed: ≈ 30 misses —
11 rows held or unseated though plain (SERVE_HELD / SEAT_HELD: «..» elision at
65:5, «لكيلا» at 22:5, rulings held for a nearby reading note whose Hafs side
they are), يوسف ranges 47–50 and 56–65, unbraced 30:18, 20:77, relayed views
(80:32 الأخفش, 12:37 الأخفش, 14:28 نافع, 14:45 يعقوب, 60:1–2, 34:41–42 غيره, 20:123
and 20:127 غيره) — 10 credits (e.g. 22:9 أبو إسحاق, 20:123 أحمد بن جعفر, 7:37's
حسن back to the author), 1 wrong grade (12:52 «لا» → يعقوب's كاف: the «ليس
بوقف» there is ابن جريج's parse of 12:51), 1 wrong seat (34:48 يعقوب stops
before the بدل; quote trimmed via QUOTE_FIX), 1 reason quoted as a ruling (60:4).
Observed completeness ≈ 91% (round 19: 89%). A fresh rebuild reproduces the
incremental result exactly.

### النحاس: held-row sweep and «{X} G عند Y» credits (2026-10-13)

The parser holds (conf=0) every النحاس ruling with «قراءة / قرأ» within ~120
characters before it or ~90 after, so the note about a neighbouring stop, or a
ruling stated for Hafs's own reading, kept plain rulings out of the app. All 199
held rows were read against Hafs's reading: 95 seated rows are now served
(SERVE_AT, keyed by seat — e.g. «واتخذوا» بالكسر 2:125، «والخامسةَ» 24:9،
«ثلاثُ عورات» 24:58، «سنفرغ» بالنون 55:29، «يغلي» بالياء), 28 unseated ones placed
(SEAT_HELD: slips «عافلين»، «قاقرءوا»، «إ ذا»، an elided «… غفورا رحيما»), one
reseated (40:84 → 40:85). About 77 stay held: rulings for a reading Hafs does not
have («يفصّل» 10:5، «سارعوا» بلا واو 3:130، «مودةُ بينِكم» 29:25، «عالمُ الغيب» 34:3،
«الريحُ» 34:12 …), citations of other surahs, and garbled quotes. Served rows
6,066 → 6,187.

A second scan found own-voice rows whose grade the book gives to a scholar right
after the quote — «{X} فإنه تمام عند أبي حاتم»، «{X} قطع كاف عن ابن شاذان»، «{X} تمام
على ما روى عن نافع» — 12, credited by seat (CREDIT_AT, own-voice rows only). Two
book slips are pinned or allowed: 67:15 «وإليه المصير» for «النشور» and 23:94
«من القوم» for «في القوم».

### النحاس: round 21 (2026-10-13)

12 fresh passages after the held-row and credit sweeps. gpt-6-luna matched ≈ 238
rulings and raised 88 issues; about half were by-design non-rows (negations,
«أجاز الوقف», co-credits, a commentator's paraphrase such as قتادة / ابن عباس)
or misreadings (37:105's كاف and أبو حاتم's تام are both right). Confirmed ≈ 24
misses, most in الصافات: «وكذا الآيات إلى {X}» ranges (37:90–92, 98–102,
143–144), «فكان كافيا وكذا» (37:79–80), 37:93 أحمد بن جعفر / غيره, 37:138; also
17:46–49 («تمام إلى {أو حديدا}»), 74:3–7 (أبو حاتم's «وكل آية بعدها كافية»),
75:2, 75:19, 77:12, 16:19 (غيره on Hafs's «يدعون»), 16:28, 3:113, 3:133, and
28:16–17 / 28:21–22 («والتمام عند غيره.» — a stray period before the quote). 5
credits (47:31–33's «ومن فتح الواو فالتمام عنده» is the Hafs side, not يعقوب's;
28:28 قيل; 74:10 غيره), 1 negation stored as كاف (28:25), 1 wrong seat (77:15's
own row is 77:19; MOVE_OWN moves only the own-voice copy). Not stored: «الوقف على
رؤوس الآيات مفهوم إلى …» (37:114–124, 126–136) — النحاس's «مفهوم» has no grade in
the scheme yet. Observed completeness ≈ 91%.

### النحاس: its own kinds — «جيد» and «بيان» (2026-10-13)

النحاس counts eight kinds of stop: التام، التمام، الكافي، الحسن، الصالح، الجيد،
البيان، القبيح. «جيد» (أبو حاتم's «وقف جيد / الوقف الجيد», 16 rows) had been read
as حسن since round 18; it is now its own grade, and «وقف البيان» (40:28, 60:1 —
both أبو حاتم) is stored as «بيان» instead of being skipped. «كاف جيد» stays كاف
(the first word grades). «مفهوم» («الوقف على رؤوس الآيات مفهوم إلى …», الصافات)
is not one of the eight, so those verse ends stay unstored. «التام / التمام» are
one grade (تام): the book uses «تمام» as its usual noun for it. The grade tables
(frontend/lib/waqf.ts, imam-rulings, stop-explorer, waqf_guide.js,
core/classical_review) carry the two new names.

### النحاس: «قبيح» (2026-10-13)

All eight «قبيح / أقبح / يقبح» in the book were read. One is a ruling: «وذكر الفراء
أنه يقبح الوقف على {فلما رأوا بأسنا قالوا آمنا بالله وحده وكفرنا بما كنا به
مشركين}» (40:84, now قبيح credited to الفراء — the first قبيح row for النحاس; the
app treats it as a negative ruling). The rest are vocabulary («سنة قبيحة»،
«ليست قبيحة»), grammar («قبيح في المنصوب»، «غلط قبيح»), or النحاس's general case
against stopping on every «كلا». Reading them turned up a missed parenthesized
ruling beside one: «والقطع على (ما) لعمري حسن» (2:26 «مثلا ما»), added.

### النحاس: whole-book range and coverage checks (2026-10-14)

Rounds 19–21 kept finding unfilled verse-end ranges, so every graded range
statement in the book («ثم القطع على رؤوس الآيات G إلى {X}», «وكذا رؤوس الآيات
إلى …» chains) was placed — its start by the quote before it, its end by X's row or
the verse text — and its verse ends checked. 13 ranges had gaps (51 verse ends):
4:106–112 (with «والقطع الحسن (بما أراك الله)» and نافع's 4:113), 12:12–17 (+يعقوب's
12:18), 14:6–8, 21:109–111, 23:112–118, 26:70–71, 27:82–85, 28:10–11, 43:82–86,
60:10–13, and verse-end rulings at 23:11 and 23:61 (أبو حاتم). Ungraded ranges
(«ثم الوقف على رؤوس الآيات إلى …») stay unstored by design.

coverage_check.py now covers النحاس (its standing test runs on all three books):
«{X} (قطع|وقف) G» and the grade-first «والتمام / والكافي (بعده|عند فلان|على ما روى
عن فلان) {X}», a quote counting as covered when a row in its surah ends on the same
last two words. It found 19 misses, mostly a comma or period between grade and
quote («والتمام، {X}», «على ما روى عن نافع. {X}»), fused two-verse quotes, and
«هذا وقف جيد»; 7 by-design cases are listed with reasons in
coverage_exceptions.json. Served النحاس rows 6,228 → 6,296.

### النحاس: round 22 and the «وكذا» chain scan (2026-10-14)

Round 22 (12 unread stretches of already-drawn surahs; gpt-6-luna matched ≈ 227
rulings, raised 61 issues, ~20 of them negations) confirmed ≈ 29 misses: the
الصافات 61–72 range and its «والكافي {A} {B} وكذا {C}» chains (37:32–50), unbraced
«والتمام بأجماع: {X} وكذا {Y}» (25:59–62), 11:12–18, 13:22/28, 38:2/22, 43:76,
57:7/13, 36:58 (أبو حاتم's تمام النحاس calls a slip); 6:145 credited to أبو حاتم;
17:12 «فصلناه تفصيلا» regraded كاف → تام. Observed ≈ 89% — these stretches were the
parts earlier rounds had not read.

Its pattern — a bare quote between a graded quote and «وكذا», and the «وكذا» items
after it, left ungraded — was then scanned book-wide (147 hits; most are «وكذا»
after a negation, i.e. negations themselves, or cross-references in the «كلا»
essay). 44 graded chain rows added, e.g. 2:85 «وكذا عنده {…}» (أبو حاتم), 23:38–40
«فإنه يكفي الوقوف عليه وكذا {…}», الشورى 14–15 / 26–28, 31:22–24 غيره, 26:4–5
«والتمام خاضعين وكذا {…}», 51:38–45 «وإن وقفت على رؤوس الآيات كان قطعا صالحا».
Served النحاس rows 6,296 → 6,366.

### النحاس: round 23 (2026-10-14)

12 more unread stretches. gpt-6-luna matched ≈ 346 rulings (its counts run high:
it counts each verse end of a range) and raised 52 issues besides negations;
most were ungraded ranges («تم الوقوف على رؤوس الآيات إلى …», by design), first-
name co-credits, or commentators (اليزيدي، الحسن). Confirmed ≈ 14 misses: الكهف
52–56 (كاف) and 58–62 (حسن) ranges, 18:63 «عجبا», 18:64 الأخفش, 7:124 «والتمام تم
{…}», 22:31 الأخفش, 22:40 بعضهم / أحمد بن جعفر, 10:88 يعقوب, 10:92, 20:23 أبو حاتم,
4:118 and 27:10 نافع, and the held 2:235 (the copy writes «غفور رحيم» for «حليم»,
pinned); 2 credits (9:3 بعضهم, 18:90 أحمد بن موسى). Observed ≈ 95%, up from
89–91% — the first round after the range, coverage and chain scans.

### ابن الأنباري: coverage check and round 24 (2026-10-14)

coverage_check.py now covers ابن الأنباري too — «(X) [n] (وهو الوقف|وقف)? G» — so
its standing test runs on all four books. One miss: 77:7 «جواب القسم (إنما توعدون
لواقع) [7] وهو الوقف التام»; two «حسن أن يقف» verb phrases are listed exceptions.

Round 24 measured the book again (10 unread stretches; make_passages now
falls back to shorter stretches when a short book runs out of 2,600-character
ones). gpt-6-luna matched ≈ 194 rulings and raised 36 issues; most were «غير تام»
negations and its usual misreading of bare «(X) [n].» list lines (they take the
list's grade). Confirmed: 6 misses (2:6 conditional تام, 2:10, 5:4 ×2 list items,
6:12 conditional تام, 7:174), 1 held row served (6:109 «يشعركم» — Hafs «أنها»), 1
credit (2:28 «فأحياكم» تام is السجستاني's, refuted). Observed ≈ 96–97%.

### منار and المكتفى: round 25 confirmation (2026-10-14)

6 unread منار and 6 unread المكتفى stretches, to confirm the shared-code changes
since their last measurement. منار: Luna matched ≈ 103 rulings; nothing needed
a change (its flags were «وقيل» views kept in notes by design, an «ويجوز الوقف على كل
منها» set against «ولا وقف من … إلى …», a conditional «حسن الوقف على» that describes
the كاف row, and rows whose ruling lies outside its passage). المكتفى: ≈ 158
matched; confirmed 3 verse ends the book names over a blanket كاف («والتمام عندي آخر
الآية» 6:3، «وكذلك [الذي] عند رأس الجزء» 2:141، «ورأس الآية أتم. وكذلك {…}» 12:92–93),
the Hafs side of 3:79 (نصب «ولا يأمركم»: «لم يقف على ((تدرسون))», which replaces the
blanket تام), 6:14 «فاطر السموات والأرض» reseated from 6:12, and أبو جعفر النحاس's
relayed «(كمثل آدم) تمام الكلام» (3:59). Left as the parser read it: «{من الشاهدين} أكفى
منه. وكذلك رؤوس الآي بعد ((مسلمون)) تام» (3:81–90) — it can be read either way.
Observed: منار ≈ 99–100%, المكتفى ≈ 96%.

### المكتفى: named verse ends (2026-10-14)

Round 25's misses shared a cause: الداني names a verse end («ورأس الآية أتم»، «وآخر الآية
أكفى منه»، «والتمام آخر الآية»، «عند رأس الجزء») and the only row there came from a general
«رؤوس الآي» rule. A book-wide scan placed each such statement on its verse (by the quote
before it) and compared grades: 34 hits, 28 already carrying the stated grade through the
general rule (أتم = تام, أكفى = كاف), 1 «وقيل» view, 1 range. Fixed: 2:181 and 4:1 «وآخر
الآية أكفى» had no row; 3:75 «ورأس الآية أكفى منه» was تام and 10:92 «ورأس الآية أتم منه»
was كاف (explicit rows now replace the general ones). tests/test_muktafa_named_verse_ends.py
keeps it so: 39 of the 40 such statements are placed and checked.

### المكتفى: first quranpedia cross-check fixes (2026-10-14)

A partial re-run of the quranpedia.app cross-check (293 المكتفى pages, then paused)
agreed on 234 of 240 graded quotes. Two real fixes: 13:11 «ومثله {فلا مرد له} وهو أتم
منه» is تام (it was the «ومثله»'s كاف), and القتبي's relayed «{كذلك} التمام» at 10:103
was missing. The rest were quranpedia filing a quote on a neighbouring page. The
fetch and compare scripts and the page cache are in the gitignored artifacts/quranpedia/.

### Placement checks across the four books (2026-10-14)

Random rounds catch misplaced rows least (the planted-error test: 0 of 4), so two
placement checks were run over every confident row:

- **Unique two-word endings.** A quote whose last two words occur once in the surah
  must sit there. 8 rows were elsewhere: 6 are the book's spelling against the
  mushaf («تعلمون» for «تعملون», «من بعده», a dropped «اتقوا») or seats already read
  against the book; 1 is a matcher limit («(قالوا سلاما)» = «فقالوا سلاما»); 1 was
  wrong — المكتفى «ومثله {سوأة أخيه}» on 5:30's «قتل أخيه», now 5:31. Kept as
  tests/test_classical_seats.py::test_unique_two_word_endings_sit_on_their_spot.
- **The same quote in two books, a few verses apart.** 20 pairs; most are phrases a
  verse repeats («بإذن الله»، «إلا ما شاء ربك»), where each book rules its own
  occurrence. By the book's own order two المكتفى rows were on the earlier
  occurrence: «ومثله {ويقدر له} ومثله {ليقولن الله} ومثله {قل الحمد لله}» is 29:63,
  not 29:61, and «{وأصلح بالهم} تام. {الحق من ربهم} كاف» is 47:3, not 47:2.

### المكتفى and النحاس: round 26 measurement (2026-10-14)

6 unread stretches of each. المكتفى: ≈ 237 matched; besides «وقيل» views (notes by
design), 5 fixes — 24:9 «{من الكاذبين} تام. مثله {من الصادقين}» had no row; 2:262
«والتمام آخر الآية وكذلك {يحزنون}» was كاف (now تام); 2:259 «آية للناس» is إبراهيم بن
عبد الرزاق's; relayed أبو حاتم «الم» كاف and نافع «لا ريب فيه» تام added. Observed
≈ 98%. النحاس: ≈ 128 matched; 9 misses, almost all relayed views with a scholar's
name: «قال أبو حاتم (ولو افتدى به) كاف» and «ومن الوقوف الكافي (حتى تنفقوا مما تحبون)»
(3:91–92), «وقال الأخفش: وعلى أمم ممن معك: تمام» (11:48), «وقول الأخفش إن تمام الكلام
إلا قليلا ملعونين» (33:61), 21:88 أبو حاتم, 21:93 الأخفش, 9:90 نافع, 3:97 قيل; plus
the 3:81–85 range «ثم التمام على رأس كل آية إلى انتهاء أربع آيات». Observed ≈ 93%.

### النحاس: relayed views in parentheses (2026-10-14)

Round 26's النحاس misses were mostly another scholar's ruling with the quote in
parentheses or bare («قال أبو حاتم (X) كاف», «وقال الأخفش: X: تمام»). A book-wide scan
(speaker + quote, then any «(X) G» or «…: X: G» with no row) found 11, 10 real:
أحمد بن موسى «(وأملي لهم) تمام» 7:183, «(ولا يرغبوا بأنفسهم عن نفسه) تمام» 9:120,
«أول خلق نعيدة، تمام» 21:104; أبو عبيدة «(لا يبصرون) تام» 2:17; «وقيل: (ثم توليتم إلا
قليلا منكم) التمام» 2:83; النحاس's own «(وما يشعرون) تمام» 2:9, «(وكلا نمد) كاف» 17:20,
«(لا ريب) التمام» 2:2; الأخفش «(وكهلا) حسن» 3:46; and 3:7 «وما يعلم تأويله إلا الله»,
which had no النحاس row although he reports at length that نافع، يعقوب، الكسائي،
الأخفش، الفراء and أبو حاتم stop there (stored تام, credited نافع, the list in the
note; the other view's «القطع … (والراسخون في العلم)» is ungraded). coverage_check now
reads «(X) G» for النحاس too; يعقوب's «(لا تلبسوا الحق بالباطل) تام كاف», quoted in an
argument with two grades at once, is a listed exception.

### النحاس and ابن الأنباري: round 27 measurement (2026-10-14)

Sixteen passages (8 per book), checked by gpt-6-luna, with every flag checked against the book.
ابن الأنباري had only short stretches left unread, and `make_passages.py` halved 2600 → 1300 → 650,
so it skipped the 800 floor and drew nothing. It now tries 800 last.

- **ابن الأنباري: 2 real misses in 63 rulings (≈ 97%).**
  - 3:16 «(النار) تلم إذا نصبت … على المدح», where the copy has «تلم» for تام.
  - 8:75 «والتمام آخر السورة».
  - Both added in `BOOK_ADD`. The other flags were conditional or other-reading sides,
    or rows that were already right.
- **النحاس: 26 real errors in 260 rulings (≈ 90%).**
  - Relayed views after a braced quote, about 20 of them:
    - «{X} عن نافع قال: تم» (4:62, 9:114, 9:115, 24:21, 4:151)
    - «قال الأخفش {X} هاهنا تم الكلام» (6:43)
    - «{X} فإن الأخفش ذكر أنه تمام» (7:95)
    - «قال أبو حاتم: ومن الكافي {…} {ومثله} {X}» (24:11 ×2)
    - «وهو كاف على قول الكسائي» (24:20)
    - «وقال غيره … كاف» (4:58, 4:151)
    - «وعند غيره {X}» (24:21)
    - 28:68: نافع's long list, and علي بن سليمان's «ويختار»
  - Credits fixed with `CURATED_BY`:
    - 4:58 الأخفش
    - 28:68 «ما كان لهم الخيرة» أبو حاتم
    - 34:3 الأخفش (held row)
    - 9:114 «تبرأ منه»: back to the author's own. «وكذا قال أحمد بن جعفر» closes نافع's ruling before it.
  - The author's own rulings:
    - 4:148 «إلا من ظلم» كاف
    - 7:86 «وانظروا كيف كان عاقبة المفسدين» قطع صالح
    - 24:16 «{وكذلك} {سبحانك هذا بهتان عظيم}»
    - 28:78 «علم عندي» كاف, and «وبعده {وأكثر جمعا}»
- **Not real:** the النحاس flags on «وبعده {X}» rows (6:51, 28:79/81/82) are wrong. «وبعده» carries the
  grade before it.

### النحاس: relayed views beside braced quotes (2026-10-14)

Round 27's main class of error was a scholar's view stated right next to a braced quote. A book-wide scan
for it is now a standing test: `pipeline/review/nahhas_relayed_check.py` with its exceptions, run by
`tests/test_nahhas_relayed.py`. The scan reports any quote where a scholar and a grade sit next to
it and no row in the surah is credited to him. It started with 94 candidates.

**Parser (`nahhas_parse.py`)**
- New patterns:
  - «{X} عن نافع قال: تم», «{X} عند نافع: تم», «{X} عن نافع: تام»
  - «قال الأخفش {X} هاهنا تم الكلام»
  - «قال أبو حاتم {X} التمام،»
  - «{X} قال نافع: تم» / «{X} قال أحمد بن جعفر: تم» (`_SAID_AFTER_BARE`). The text before the grade must be
    exactly a name (strict match). A loose match read «وقال يعقوب هو وقف كاف» and «قال أبو إسحاق (فما لكم) تم»
    as names, which changed 7 rows until it was made strict.
- «قال X: {Q} تمام وهو قول Y» and «وعن نافع {Q} تم وهو قول Y» now credit X / نافع (first-name convention).
  `_AT` had given the row to Y. An explicit «وهو كاف عند Y» still goes to Y.

**Curation (`audit_nahhas.py`)**
- `CURATED_BY`:
  - «قال الأخفش {X} التمام فيه {Y}»: the تمام is at Y, so the Y row is الأخفش's (nine places, as at 4:58).
  - 11:60, 13:17, 18:64, 29:3, 87:7. At 87:7 the كاف is the author's, and محمد بن عيسى's تمام is
    an extra row.
- `EXTRA_AT`, views the parser rule can't reach:
  - 2:61 «وبصلها», which is unbraced
  - 7:2, 13:17, 22:72, 24:35, 29:22, 31:10, 35:18, 48:1
- `DROP_AT`, three rows the new rule wrongly attached to the previous quote's grade:
  - 2:264 «وبعده {X}» after نافع's rejected تم
  - 2:270 «أن بعده {X}», which is an argument
  - 4:127 «معطوف على {X} وكذا»

**Result**
- 72 new النحاس rows: about 60 from نافع, الأخفش, أبو حاتم, أحمد بن جعفر and others, plus 3 of the
  author's own via «وكذا» chains.
- 24 rows re-credited. Everything added was checked against the book.
- 29 exceptions remain, each with a reason: «التمام فيه» on the X side, a name that belongs to the
  quote before, other readings, and own grades where the named scholar is someone who agrees.

### النحاس and ابن الأنباري: round 28 measurement (2026-10-14)

Thirteen passages: 10 النحاس and 3 ابن الأنباري. ابن الأنباري is nearly fully read, so few unread stretches
are left in it. gpt-6-luna checked them, and every flag was checked against the book.

**النحاس: 13 real errors in 281 rulings (≈ 95%, up from ≈ 90% in round 27).**
- Credits:
  - 4:38: «وللأخفش فيه قول حسن … {X} وهذا التمام عنده»
  - 42:45: «وأكثر أصحاب التمام يقولون التمام {X}», now غيره
  - 6:12: «في قول أبي حاتم وهو أحد قولي الفراء»
  - 6:3: «قال العباس بن الفضل … قال: وقال أبي {X} وقف كاف», now credited to العباس بن الفضل
- Missing rows:
  - 4:162: الأخفش «هو تمام»
  - 2:30: «فالوقف الكافي على هذا (ونقدس لك)»
  - 6:109: «والتمام على قول الجماعة (لا يؤمنون)»
  - 19:21: أبو حاتم «هو علي هين»
  - 19:34: «والكافي بإجماع {الذي فيه يمترون}»
  - 21:82 and 21:83: «{X} كان». The copy has «كان» for «كاف»; the sentence before reads «كان كافيا … لم يكف».
- Rows dropped:
  - 23:1: «يجوز أن يكون التمام {قد أفلح المؤمنون}» comes after «البين … ليس بتمام ولا بكاف».
  - 4:171: «والتمام {إنما المسيح عيسى بن مريم رسول الله} ليس بتمام». An earlier coverage pass had added
    this row. Both are now coverage exceptions.

**ابن الأنباري: 1 real error in 21 rulings.**
- 3:4: «وقال السجستاني: هو تام، وهو خطأ منه» added (BOOK_ADD and RELAYED_BY).
- `audit()` now skips BOOK_ADD rows, as `--apply` already did. Before, the hand-added تام beside the book's
  حسن showed up as a pending regrade.

The rest were by design: conditional and other-reading sides, «يجوز» permissions, notes asking for
conditions, ungraded mentions, and «وبعده» chains.

### النحاس and ابن الأنباري: round 29, full coverage (2026-10-15)

Random rounds had read only part of each book. Measured strictly, with no margin around earlier passages,
53% of النحاس (312k chars) and 34k chars of ابن الأنباري had never been in a passage.
`pipeline/review/random_check/make_cover.py ROUND anbari,nahhas` tiles every gap, however short, into
passages. Each gap is widened by 150 chars on both sides, so a ruling cut at a boundary is read whole by
one of the two passages, and the passages are packed ≤ 4 / ~5000 chars per call. That came to
363 passages in 116 gpt-6-luna calls. `make_cover.py --verify anbari,nahhas` now reports
**0 uncovered characters in both books**.

Every flag was triaged and the rest checked against the book. Set aside:
- by design: conditional and other-reading sides, «يجوز» permissions, negations, ungraded mentions,
  notes asking for conditions
- «missing» flags whose row already exists in the surah
- «unsupported» flags that only reflect the reviewer seeing one passage

Each new row's note is the book's own words, checked verbatim, and its quote is the book's spelling.

**النحاس: about 280 corrections over ~4,860 rulings checked (≈ 94%).**
- 218 new served rows, including 37 verse ends from graded «رؤوس الآيات … إلى {X}» ranges.
- 57 re-credited. Scholars' chains had been read as the author's own: «قال يعقوب وأبو حاتم: {A} {B} كاف
  وكذا {C} …», «قال أبو حاتم … وقال: والتمام {X}», «وعن نافع {X} قطع حسن وكذا {Y}», and
  «قال الأخفش {…} فالتمام فيه {X}». Most are seat-keyed through `CREDIT_AT`, because quotes such as
  «إن الله على كل شيء قدير» recur in a surah.
- Parser slip: in «{X}، قال الأخفش: التمام {Z}» the bare definite grade belongs to Z, not X (2:87).
  «هذا التمام» still refers back to X.
- Grades: 2:41 «إلا أنه حسن» and 40:74 «والتمام كذلك {يضل الله الكافرين}».
- Dropped:
  - 25:75 «وليس {تحية وسلاما} تمام»
  - 33:6, re-seated to «معروفا»
  - 27:82, which is تام on Hafs's «أن الناس», not the blanket كاف
- `surah_end_rulings` respects a credited surah end («والتمام عند غيره آخر السورة»).

**ابن الأنباري: 27 corrections over ~790 rulings (≈ 96.6%).**
- New rows:
  - the second «إياك» and «الصراط» قبيح
  - «بمنزلة الوقف على (الأنهار)»
  - bare «ومثله» lists in النور
  - three surah ends
  - السجستاني's rejected «هو تام» at 2:177, 3:14 and 10:2
- 1:7 «عليهم» re-seated to the first «عليهم».

### النحاس: round 30, second full pass (2026-10-15)

`make_cover.py 30 nahhas --all` re-tiled the whole book (331 passages, 152 calls), ignoring earlier
rounds. gpt-6-luna counted ~8,900 rulings. 103 flags repeated ones already judged in round 29. Of the rest,
~150 survived checking against the book:
- **New rows.** «قال الأخفش: ولو وقف على (قلوبهم) كان أيضا تماما», أبو حاتم's
  «{ولو أعجبتكم} {ولو أعجبكم} كافيان», «وكذا {يا بني أقم الصلاة} … وكذا {وأمر بالمعروف}», and نافع's and
  يعقوب's relayed «تم» in passages round 29 had read once.
- **Verse ends.** The 10:72–80 حسن range, where the range's end quote is in parentheses, not braces.
- **Credits (`CREDIT_AT`).** «قال يعقوب يعني الأزرق المقرئ {…} … وكذا …» (10:24–25), أبو حاتم's chain in
  الملك (67:11–19), «قالا {X} تمام» (24:35), «وخالفهم كلهم الأخفش فقال: التمام {X}» (2:68), and others.
- **Grades.** 3:20 «وكذا {فقد اهتدوا} وكذا {فإنما عليك البلاغ}» is كاف. 46:26–28 «والتمام كذا {…} وكذا {…}»
  is تام.
- **Dropped.** 7:123 «ليس في هذا تمام … وكذا {فسوف تعلمون}».
- **Fixed two of my own round-29 seats.** 3:20 «فقل أسلمتم» is «ءأسلمتم» (wpos 13). 3:47 «كن» is wpos 21.

### ابن الأنباري: round 31, second full pass (2026-10-15)

`make_cover.py 31 anbari --all` gave 166 passages in 67 calls. Midway the OpenAI account ran out of
credits, so 124 passages came back «HTTP 429: no credits». Those batches were deleted and rerun once
credits were added. gpt-6-luna counted ~3,600 rulings. Most of the 88 «wrong grade» flags were bare
«ومثله» list items, which inherit by design, and the held rows are مذهب / other-reading sides.

31 rows added, each traced verbatim:
- السجستاني's rejected «هو تام» at 2:106, 3:45, 3:196, 4:12, 15:3 and 65:10, and his «فالوقف الكافي
  (من ذهب)» on the نصب of «اللؤلؤ», which is Hafs (22:23).
- Bare «وكذلك / ومثله» items in 4:92, 4:130, 5:16, 9:114, 18:23, 24:32–33 and 35:43.
- 31:17 «أقم الصلاة، بالمعروف، عن المنكر، ما أصابك» حسن.
- «فتم الكلام على …» 12:52, «جواب القسم وهو وقف حسن» 37:4, and «وأحسن من هذا كله» 95:7.
- 72:23 «فعلى هذا المذهب …». The reading cited is «روى أبو عمر عن عاصم», i.e. حفص.

### المكتفى: round 32, first full pass (2026-10-15)

`make_cover.py` now tiles المكتفى too, using `make_passages`' section split. `make_cover.py 32 muktafa --all`
gave 183 passages in 67 calls. gpt-6-luna counted ~7,500 rulings. Most flags were المكتفى's
«{X} كاف. وقيل: تام» (kept in the note by design) and conditional or other-reading sides.

Fixes, each traced verbatim (`audit_muktafa_ordinals.py`):
- **`RELAYED_ADD` (32 rows).** Named views after the author's grade: «وقال نافع / الأخفش / أبو حاتم / يعقوب
  / القتبي / الدينوري …: تام», and «ومثله» items inside such a ruling (16:7, 16:18).
- **`MANUAL` (32 rows).** The author's own rulings the parser missed: «والتمام: {لساحر مبين}», «{أو نتخذه ولدا}
  لأنه انقضاء كلام امرأة فرعون», «جواب القسم … [وهو تام]». Also 24 verse ends graded تام by «ورؤوس الآي تامة»
  (3:136), «وكذلك رؤوس الآي بعد» after a تمام (3:141–145), «ورؤوس الآي إلى العشر تامة» (3:175),
  «وآخر كل قصة تمام» (11:49, 11:68), «ورؤوس الآي تامة إلى قوله ((مريب))» (11:56–61), «وكذلك آخر كل
  قصة فيها» (51) and «وكذلك الفواصل إلى آخر السورة» (66:6–12). These replace the blanket كاف.
- **`REGRADE`.**
  - «ومثله» after a تام: 13:25 and 42:18–23.
  - «{يعلمون} الأول كاف. والثاني تام» (2:102).
  - «وهو أتم منه» (23:27).
  - «ومثله» after a كاف: 2:105 and 9:118.
  - 10:100 «وحسن على قراءة من قرأ بالياء» (Hafs «ويجعل»).
- **`RELAYED_BY`.** 17:20 يعقوب and 25:22 الحسن.
- **`DROP_IDS`.** 28:5 «والفواصل تامة ما خلا قوله {الوارثين}».

Left out:
- the copy's slips 7:18 «مذعورا» and 43:60 «يخلقون», which the seat and alignment tests reject
- 19:81 «عزا كلا»: the quote must end on its seated word
- 28:71 «بيضاء»: the copy's slip for that verse's «بضياء»; an earlier test pins it there

### منار: round 33, partial full pass (2026-10-15)

`make_cover.py` now tiles منار too, from `manar_shamela_sections.json`. Earlier random rounds had read
only 16% of منار (1.18M of 1.41M chars never reviewed). `make_cover.py 33 manar --all` gave 797
passages in 376 calls. The run was stopped on purpose after 89 batches (~24% of the book), and those
results were triaged. Token use, now logged by `run_openai.py`: ~40k input / 6k output tokens per batch.

Most real flags were relayed views stated right after the author's grade: «{X} [n] حسن، وقال نافع /
الأخفش / أبو عمرو / أبو حاتم / يحيى بن نصير النحوي: تام». They go in the new `RELAYED_EXTRA`
(audit_manar_mithl.py). It inserts each row with its own credit; `REPORTED` is seat-keyed and would
also credit the author's own row at that seat. 21 relayed rows were added. Also:
- 13:38 «تم الكلام» regraded to تام.
- Credits:
  - 7:137 «فلا يوقف على يستضعفون» and 10:24 «فلا يوقف على فاختلط» are the author's own.
  - 16:6 «وكذا تسرحون» is أبو عمرو's.
- نافع's 10:37 «تام» re-seated on «لا ريب فيه» (it sat on «العالمين»).
