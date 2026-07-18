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
   167 low-confidence rows in the local `/classical-review` page and backfill
   stable page/paragraph locators. Run with `ENABLE_EDITOR=1`; the page stores
   approve/reject decisions separately and will not activate the book until
   every uncertain row has a decision and the reviewer selects «اعتماد وإضافة
   الكتاب».
2. **إيضاح الوقف والابتداء** — explicit ayah anchors, but many parenthesized
   grammatical examples; review the 228 low-confidence rows with strict
   negative fixtures.
3. **القطع والائتناف** — most discursive; expand only structurally unambiguous
   grade-before/grade-after forms, then scholar-review its 158 queued rows.
4. **منار الهدى** — keep the released guarded dataset, review the exported 102
   heuristic suspects in the منار tab of `/classical-review`, then replace
   historical LLM-only discursive records incrementally with source-located
   deterministic or human-entered records. Rejecting a reviewed row suppresses
   it from the live API without deleting the underlying source record.

Current deterministic catalog audit baseline:

| Book | Rows | Surahs | Confident | Existing low-confidence review |
|---|---:|---:|---:|---:|
| المكتفى | 4,408 | 111 | 4,241 | 167 |
| منار الهدى | 13,252 | 114 | 13,252 | 102 heuristic suspects |
| القطع والائتناف | 1,767 | 91 | 1,609 | 158 |
| إيضاح الوقف والابتداء | 2,178 | 94 | 1,950 | 228 |

These counts are regression baselines, not claims that the discursive books
have been exhaustively interpreted.
