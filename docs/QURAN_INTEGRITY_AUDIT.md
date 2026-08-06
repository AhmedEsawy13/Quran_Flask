# Quran text integrity audit

The audit is run offline from an ignored Tafsir MCP snapshot:

```bash
python3 pipeline/audit_quran_integrity.py --fetch-reference
python3 pipeline/audit_quran_integrity.py --audit
```

The completed snapshot currently contains all 6,236 ayahs. Its JSONL SHA-256
is `00c26910bf653e480b73514faab2fea814a73add4f681b5547d272f2e673a4c6`.
The snapshot is not a Flask runtime dependency.

The audit covers the raw Quran JSON/Tanzil sources, transliteration keys,
`quran_script.db`, `word_name.db`, waqf-symbol and classical waqf stores, and
all configured QPC, Bahrain, Shemrly, Azhar, and Mesaha layout namespaces.
Comparison normalization is limited to documented orthography/presentation
variants; raw source text is never rewritten.

Current result: `review_required`, not fully verified. The MCP response for
`11:14` reports `word_count=16` while its returned text splits into 17
space-separated tokens. The source queue also contains unresolved
orthography/tokenization cases, three orphan quran-script waqf rows, Bahrain
layout gaps, and unresolved Shemrly/Azhar endpoint/order issues.

The audit writes these ignored review artifacts:

- `artifacts/quran-integrity/mcp-ayah-reference.jsonl`
- `artifacts/quran-integrity/mcp-reference-manifest.json`
- `artifacts/quran-integrity/integrity-report.json`
- `artifacts/quran-integrity/quran-script-candidate-mapping.json`
- `artifacts/quran-integrity/quran_script_candidate.db`
- `artifacts/quran-integrity/layout-candidate-repairs.json`

The candidate database declares a separate `qpc-canonical-token-v2`
namespace and `replacement_approved=0`. No live Quran database or layout
database is replaced automatically.

## Word-meaning comparison

The MCP `analyze_word` meanings are harvested into a resumable, ignored
snapshot:

```bash
python3 pipeline/compare_word_meanings.py --fetch --source python
python3 pipeline/compare_word_meanings.py --compare
```

`--source python` uses the official `tafsir-mcp` package and its read-only
SQLite database. On the first run the package downloads its approximately
214 MB database once; the comparison then loads all word records in one local
query instead of making one HTTP request per word. Use `--source http` only
when the offline package is unavailable.

The review dashboard is available at `/quran-integrity-review`. It separates
verse-level token alignment, grouped-phrase rows, and directly comparable
single-word meaning text. Exact text equality is reported as a comparison
signal only; it is not treated as proof that one scholarly meaning is correct.

After approving the migration, replace the runtime `word_name.db` with the
canonical MCP word rows:

```bash
python3 pipeline/migrate_word_name_to_mcp.py --apply
```

The command keeps a legacy backup under `artifacts/quran-integrity/`, adds
source provenance to the runtime database, and does not make Flask depend on
the Python package at request time.
