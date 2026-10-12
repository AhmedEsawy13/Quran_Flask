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
python3 pipeline/derive_illa.py                # last: العلّة + «ومثله» heads for all four books
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
