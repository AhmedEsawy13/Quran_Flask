# Manar completeness audit

Audit date: 2026-08-04.

## Sources compared

- `classical_sources/manar_shamela_sections.json`: the authoritative source
  used for the LLM extraction, converted from Shamela book 6496.
- `classical_sources/manar_ashmuni_shamela6496.md`: an independent OpenITI
  digitization used as a cross-check.
- The public-domain 1322 AH printed edition scan on
  [Arabic Wikisource](https://ar.wikisource.org/wiki/ملف:منار_الهدى_في_الوقف_والابتدا.pdf),
  visually checked around سورة مريم and damaged verse references.

## Result

- Source/cache coverage: 114/114 surahs; every chunk is cached.
- Raw LLM records: 13,045; deterministic validation accepts 13,045/13,045.
- The dual source backstop adds 234 rulings the LLM omitted.
- Released Manar rows: 13,272 across 114/114 surahs.
- Mechanically alignable explicit source rulings:
  - Shamela JSON: 9,566
  - OpenITI cross-check: 9,587
  - Union checked by the release gate: 9,593 unique keys
- Missing explicit rulings after rebuild: **0**.
- The OpenITI cross-check exposed 27 explicit keys absent from the converted
  Shamela export, concentrated in six surahs; those are now recovered by the
  deterministic backstop.
- Local traceability heuristic: 13,187/13,272 rows grounded automatically
  (99.36%); 85 rows are queued for human review, not classified as errors.
- سورة مريم: 123 explicit aligned keys in Shamela JSON and 123 in OpenITI;
  the sets are identical. The earlier “three missing pages” statement confused
  missing Shamela row IDs with demonstrated missing printed content.

## Reproduce

```bash
python3 pipeline/build_classical_llm.py --book manar --status
python3 pipeline/build_classical_llm.py --book manar
python3 pipeline/audit_manar_completeness.py --strict
python3 pipeline/audit_traceability.py --db data/classical_waqf.db --source manar
```

The audit deliberately makes a bounded claim: every explicit source ruling
that can be deterministically aligned is present. Discursive prose and
alternative opinions remain guarded by cache validation and regression tests;
they cannot be proven exhaustive by a regex alone.

## «ومثله / وكذا» inheritance audit (2026-09-26)

`pipeline/audit_manar_mithl.py` re-resolves every chained item mechanically
(1,878 items): inherited grade, collective grades («كلها حسان»، «وقوف
كافية»), alternates voiced before the chain, ordinals («الثاني»،
«الأخيرة»، «في الموضعين»), searching from the head's word up to the next
marked verse. Exact spelling beats a prefixed one, and when a word repeats
the mushaf's pause-marked occurrence wins unless a later chain item names it.

Findings in the LLM release, all applied to `data/classical_waqf.db`:

- 256 inherited rulings were absent (e.g. 28:88 «إلا وجهه» تام، 36:48
  «صادقين» تام، 4:92 «مؤمنة» في الموضعين، 55:71 «تكذبان» ليس بوقف) and
  16 more where only an alternate/relayed grade had been stored (39:20
  «الأنهار»: الأشموني كاف، not only أبو حاتم's تام).
- Repeated-word misplacement ("last occurrence wins"): 45 curated moves
  (13:16 «قل الله» تام sat on «قل الله خالق»; 7:195 the لا belongs to the
  first three «بها», the last is كاف) plus 114 mechanical ones — 81 of them
  exact duplicates on a mid-phrase word such as «إِنَّ ٱللَّهَ» right after the
  real stop, now removed. 82 remaining suspects are in
  `review/manar_misplaced_review.jsonl` for a human reader.
- 39:50 «يكسبون» regraded كاف (the «تام فيهما» is about «كسبوا»).

Result: 1,828/1,878 chain items match the DB; 39 do not align to the Hafs
text (qirāʾa spellings such as «يقض»، «جدار», or typos in the edition), 6 are
reviewed parser misreads. The completeness gate still reports 0 missing
explicit rulings; its exact-seat drift rose to 17 because rows were moved
off the last-occurrence aligner's mid-phrase seats (48:28 {كله} ≠ «بالله»).

### Follow-up (same day): every item resolved

- The 82 repeated-word suspects were each decided against the book's own
  `{quote} [n]` line: 69 moved/merged onto the quoted word, 10 confirmed
  correct where they sit, 2 withdrawn (conf=0) because no line of the book
  supports them (3:73 كاف on «وَٱللَّهُ وَٰسِعٌ», 48:10 جائز on «عَٰهَدَ عَلَيۡهُ ٱللَّهَ»).
- The 39 unplaced chain items: 31 pinned by hand (qirāʾa spellings «يقض
  الحق»، «بظنين»، «جدار»; the edition's typos «سراجا»→«سرابا»،
  «فتفكرون»→«فتكفرون»), 12 excluded as remarks rather than rulings
  («و «ثم» لترتيب الأخبار»، «وكذا «إن» نصب …»، rasm cross-references).
- Final: 1,866/1,866 chain items match; 0 suspects in the review queue.

## المكتفى (same audit round)

- `audit_muktafa_ordinals.py`: 19 rulings recovered that the builder dropped
  when an ordinal sits between quote and grade, 5 «الثاني» items moved off
  the first occurrence, 2:81 regraded تام.
- `audit_muktafa_blanket.py`: الداني's 243 blanket statements («ورؤوس الآي بعد
  كافية»، «إلى قوله {X}»، «إلى آخر السورة»، «وكذلك عامة فواصلها»، «ورأس الآية
  أتم») expanded to the 2,329 verse-ends in their scope that carried no
  المكتفى ruling. An explicit ruling always wins. Rows carry
  `grade_raw='رؤوس الآي'` and the statement as note («حكم عام: «…»»); the
  traceability gate checks the statement against the book. Open «بعد» runs
  to the next blanket statement or the surah's end; «قبل/بين ذلك» covers the
  «ومثله» chain it closes. Not expanded: «آخر كل قصة» / «أواخر القصص»
  (story boundaries are not stated).

## Release status (2026-09-26, final pass)

Both released books now serve every row (conf=0 count: 0) and pass every
gate: catalog alignment, 100% source traceability, 100% Qur'an alignment,
0 missing explicit rulings, chain/ordinal/blanket audits idempotent.

- منار (13,402 rows): the 85 heuristic traceability suspects were read
  against the book — 74 confirmed, 4 regraded (83:2 حسن، 52:8 حسن، 2:16
  صالح، 70:3 حسن), 3 re-attributed (قيل / الأخفش / شيخ الإسلام), 3
  deleted (2:6 «أم لم تنذرهم» which the author rejects; 20:95 and 37:165
  with no ruling in the book). Recorded in
  `review/manar_traceability_verified.json`; the review page shows only
  unread suspects. 36 held-back rows with misspelled quotes were repaired
  (mushaf spelling, 3 moved to the right word, 4 duplicates dropped).
- المكتفى (6,756 rows): its 23 held-back rows were read against their own
  surah sections and served (2 moved: 3:20 «أأسلمتم», 24:37 «والأبصار»;
  22:13 attributed to الدينوري). 20 keep the book's spelling and are listed
  in `review/hand_pinned_seats.json`, which the alignment gates accept.
  4:123 regraded تام («وهو عندي تام»).
- 30 redundant duplicate rulings merged (same word, grade and attribution,
  note empty or contained in the other); 11 duplicates with different
  conditions stay.

What "trust" means here: every served row is tied to a located sentence of
the book and to a verified word of the Hafs text, and every row the
heuristics flagged has been read by hand. It is not a second scholar's
independent review of الأشموني's and الداني's discursive prose.

## Measured accuracy (random sample, 2026-09-26)

100 served rulings drawn at random (seed 20260926): 50 منار, 30 المكتفى
explicit, 20 المكتفى verse-end rules. Each was read against the book's own
sentence and the Hafs verse.

| | word + grade right | attribution right |
|---|---:|---:|
| منار (50) | 49 | 48 |
| المكتفى explicit (30) | 30 | 29 |
| المكتفى verse-end rules (20) | 20 | 20 |
| **all (100)** | **99** | **97** |

Every error type the sample found was then swept across both whole books
and fixed (audit_manar_mithl.py / audit_muktafa_ordinals.py /
audit_muktafa_blanket.py): 33 منار explicit rulings on the wrong occurrence
of a repeated word (16:104 type) plus 5 missing first occurrences; 92 منار
rows mislabelled as another scholar's view although the grade is
الأشموني's own («كاف، وقال أبو عمرو: تام»); 26 المكتفى relayed opinions
(«وقال نافع {بل أحياء} تام») labelled; a verse-end rule that ignored its
«إلى قوله» bound (7 rows in الزمر). The completeness gate now seats explicit
rulings the same way (exact spelling, then the pause-marked occurrence); 8
residual seat differences are documented in the test.

Rows: منار 13,407, المكتفى 6,749. 95% Wilson interval on the pre-sweep sample:
word+grade 94.6–99.8%, attribution 91.5–99.0%. The swept error classes no
longer occur, so the current rate is at or above these.

### ابن الأنباري (إيضاح الوقف والابتداء), 2026-09-26

`pipeline/audit_anbari.py --apply` (run after `build_classical_waqf.py --only
anbari`; it settles by the second pass) fixed the surah-section mapping (short
titles like «ن» had matched «نوح»), re-seated rows by the book's own verse
numbers, resolved «ومثله/وكذلك» chains and ordinals, deleted negated chain
items («غير تام»), labelled relays (السجستاني، الأخفش), and added graded
entries and book-end rows.

The book's «يحسن / لا يحسن الوقف على (X)» sentences are nearly all tied to a
reading or an i'rab («فمن قرأ …»، «فعلى هذا المذهب …»، «إن جعلت …»), often
not Hafs's. Each was read by hand: where the split is between readings, the
side Hafs reads (checked against the Hafs vowels: وضعَتْ، وأنَّ، أنَّهم، أنَّا،
متاعَ، سواءً، خالدَين …) is served and marked «[على قراءة حفص]» (HAFS_SIDE,
HAFS_ADD); plain or «من الوجهين جميعا» rulings are served (BEFORE_CONFIRMED).
The 68 that hinge only on i'rab alternatives or a non-Hafs reading stay
held. Two grade-after rows that were not the Hafs ruling are dropped (DROP).

After that pass 2,288 of 2,414 rows were served; after the Hafs resolution
2,308 are served and 106 held. Accuracy check (seed 20261001): 100
rulings (70 ordinary, 6 relayed, 24 grade-before). Ordinary and relayed were
76/76 right on word, grade and attribution (95% Wilson lower bound ≈ 95%). The
grade-before class was wrong for Hafs or wrongly seated in 8 of 24, which is
why that class is now held. The 23 rule-inserted graded entries and the 4
served grade-before rulings were each read by hand.

### النحاس (القطع والائتناف), 2026-09-27

The old harvester read one pattern and credited nearly every ruling to
النحاس. `pipeline/nahhas_parse.py` now parses the book's own vocabulary:
grade after a quote («قطع كاف»، «تم»، «فإنه تمام»، «فهذا الكافي من الوقف»)
or before it («والتمام {X}»، «والكافي بعده عنده {X}»), «وكذا» chains,
negations («ليس بقطع كاف»), and «ثم القطع على رؤوس الآيات كاف إلى {X}»
ranges. Attribution: «قال فلان» covers only the quote it introduces (a bare
«قال» continues it), «{X} كاف عند أبي حاتم»، «وعن نافع {X} تم»، «ومذهب فلان أن
التمام»، «وعند غيره تام» (a second row); «قال جل وعز» and tafsir authorities
are not waqf verdicts; «أبو جعفر» is النحاس. Each quote is seated where the
whole quote matches the Hafs text, nearest forward from the previous seat.
Surah sections were fixed (الطول، حم عسق، الشريعة، سأل، انفطرت; the second
«سورة القلم» is العلق). `pipeline/audit_nahhas.py` adds الفاتحة, «ذوات قل»,
«والتمام آخر السورة» rows and a few curated fixes.

Rows 1,767 → 5,426 (5,118 served, 308 held). Three random samples of 100:
88/100, then 97/100 after fixing what the first found, then 97/100 on an
untouched sample (seed 20261004); word placement 100/100 on the last two.
The remaining misses are attribution edge cases and one corrupted passage.
