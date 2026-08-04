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
