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
