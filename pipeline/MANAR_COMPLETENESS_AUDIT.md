# Manar completeness audit

Audit date: 2026-07-18.

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
- The source backstop adds 207 rulings the LLM omitted.
- Released Manar rows: 13,252 across 114/114 surahs.
- Mechanically alignable explicit source rulings: 9,566 unique keys.
- Missing explicit rulings after rebuild: **0**.
- Local traceability heuristic: 13,150/13,252 rows grounded automatically
  (99.23%); 102 rows are queued for human review, not classified as errors.
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
