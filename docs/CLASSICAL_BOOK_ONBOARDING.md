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
