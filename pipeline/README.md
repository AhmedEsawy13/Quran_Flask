# pipeline/ — building, auditing and migrating the shipped data

Everything the running app reads (`data/`, `reciters/`) is **built here, offline**,
and committed. Nothing in this directory runs at request time. Scripts are run
from the repo root (`python3 pipeline/<name>.py`) and are flat on purpose: CI
workflows, docs and habits all reference these paths.

The web app is never imported by a data build. Scripts that need a verse's word
list use `core.verse_words`; dataset access goes through `core.datasets`,
`core.config` and `core.text`.

Legend — **CI**: runs in GitHub Actions · **rebuild**: how a shipped artifact is
regenerated · **one-time**: already applied to the shipped data, kept as
provenance (safe to ignore unless you are rebuilding from scratch).

## Release gates and audits (read-only)

| Script | Purpose |
|---|---|
| `audit_release_readiness.py` | **CI.** Fails when a versioned DB or canonical layout stream is damaged |
| `audit_quran_integrity.py` | Exhaustive Quran text / word-key / layout integrity audit (feeds `/quran-integrity-review`) |
| `compare_word_meanings.py` | Compare `word_name.db` with the Tafsir MCP word analysis |
| `check_supabase_readiness.py` | **CI (daily).** Supabase connectivity, capabilities, schema version |
| `generate_route_contracts.py` | Regenerates `docs/api-route-contracts.json` (guarded by `tests/test_route_contracts.py`) |
| `audit_classical_catalog.py`, `audit_manar_completeness.py`, `audit_muktafa_accuracy.py`, `audit_traceability.py` | **CI.** Deterministic gates for the classical-book dataset |
| `audit_manar_mithl.py`, `audit_manar_pin_mismatch.py`, `audit_muktafa_blanket.py`, `audit_muktafa_ordinals.py`, `audit_anbari.py`, `audit_nahhas.py` | Per-book inheritance / seating audits; re-run after every rebuild of `classical_waqf.db` |
| `audit_tajweed_notes.py` | Tajweed colouring vs Tafsir-MCP prose notes |

## Classical waqf books → `data/classical_waqf.db`

The four active books are المكتفى (الداني), منار الهدى (الأشموني), القطع والائتناف
(النحاس) and إيضاح الوقف (ابن الأنباري). Policy and onboarding:
[`docs/CLASSICAL_BOOK_ONBOARDING.md`](../docs/CLASSICAL_BOOK_ONBOARDING.md).

| Script | Purpose |
|---|---|
| `build_classical_waqf.py` | **rebuild.** Aligns every book's citations to exact QPC word positions |
| `nahhas_parse.py` | Parser for النحاس, used by the build |
| `import_classical_book.py` | Deterministic (no-LLM) validation + import of a *new* book |
| `derive_illa.py` | Stores each ruling's العلّة and, for «ومثله/وكذا», the ruling it follows |
| `classical_cleanup.py` | Deduplicates extraction output |
| `convert_manar_shamela.py` | **one-time.** Shamela `.mdb` → markdown for منار |
| `build_classical_llm.py`, `verify_reported_from.py` | Optional LLM re-extraction pilot ([`docs/CLASSICAL_LLM_PILOT.md`](../docs/CLASSICAL_LLM_PILOT.md)); `classical_llm_cache/` holds its per-surah outputs |
| `build_tawjih.py` | Aligns the contemporary توجيه to QPC word positions |
| `classical_books.json`, `classical_sources/`, `review/` | Book catalogue, vendored OpenITI/Shamela texts, review queues |

## Mushaf waqf marks → `data/mushaf_waqf.db`

| Script | Purpose |
|---|---|
| `sync_published_waqf.py` | **CI (daily PR).** Pulls admin-published قطر/الكويت/البحرين marks from Supabase into the local DB |
| `migrate_waqf_to_supabase.py` | Seeds Supabase `editor_marks` from the local DB |
| `build_madinah_qadeem.py`, `build_indopak_waqf.py`, `build_husary_mushaf.py` | Build individual mushaf columns |
| `add_bahrain_waqf_column.py`, `add_qatar_kuwait_waqf_columns.py`, `seed_kuwait_surah_end_rukuu.py`, `migrate_mushaf_waqf_token_index.py`, `repair_mushaf_waqf_db.py` | **one-time** schema additions and repairs |
| `prepare_runtime_databases.py` | Builds derived indexes and `waqf_symbols.db`; run after changing Quran sources or schemas |

## Mushaf layouts (page geometry)

| Script | Purpose |
|---|---|
| `import_mesaha_layout.py`, `mesaha_printed_seating.py` | المساحة الأميرية ١٣٤٢هـ ([`docs/MESAHA_LAYOUT.md`](../docs/MESAHA_LAYOUT.md)) |
| `seed_azhar_layout_db.py`, `seed_bahrain_layout_db.py`, `seed_bahrain_layout_supabase.py` | Seed Layout Studio projects |
| `fetch_bahrain_ref_pdf.py` | Downloads the printed البحرين PDF used as an editor reference |
| `add_line_widths.py` | Adds per-line widths to `digital-khatt-15-lines.db` |
| `import_shamarly_page_glyph_overrides.py` | Shemrly per-page glyph overrides |
| `align_azhar_*.py`, `repair_shamarly_*.py` | **one-time** reviewer-confirmed page fixes |
| `cv_waqf/` | OpenCV detection of printed waqf marks (`python3 -m pipeline.cv_waqf`; extras in `requirements/cv.txt`) |

## Text, translation and reciter datasets

| Script | Output |
|---|---|
| `build_tafseer_local.py` | `data/tafseer_local.db` (5 tafsirs, from QUL exports) |
| `build_asbab_local.py` | `data/asbab_local.db` |
| `build_tajweed_local.py`, `build_tajweed_notes_local.py` | `data/tajweed_local.db`, `data/tajweed_notes_local.db` |
| `harvest_bahouth_topics.py` | `data/verse_topics.db` |
| `migrate_word_name_to_mcp.py` | `data/word_name.db` |
| `precompute_research.py` | **rebuild.** `data/research_cache/*.json` (re-run after reciter or waqf changes) |
| `fetch_waqf_positions.py`, `analyze_waqf_patterns.py`, `fetch_hf_timestamps.py`, `build_buraaq_index.py`, `build_tadabur_alignments.py` | Earlier reciter-research fetchers, kept as provenance |
| `tafsir_mcp_client.py` | Minimal client for the Tafsir MCP, used by the harvesters |

## Editor accounts (Supabase)

`create_editor_invite.py`, `set_editor_password.py`, and the `supabase_*.sql` files
(schema, atomic publish, audit actions, password auth, layout schema, readiness).
Setup: [`docs/SUPABASE_EDITOR.md`](../docs/SUPABASE_EDITOR.md).

## Conventions for new scripts

- Resolve paths from `core.config` (`_BASE_DIR`, DB constants), never from `__file__` arithmetic.
- Import helpers from `core.*`; do **not** `import app`.
- Read-only by default; anything destructive takes an explicit flag and writes a backup first.
- Add a one-line module docstring — it is what this index is built from.
