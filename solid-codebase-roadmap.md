# Solid codebase roadmap

Status: active  
Last audited: 2026-08-08  
Rule: preserve routes, response shapes, database schemas, legacy aliases, and
reviewer data while moving in small tested slices.

## Current baseline

The application is a Quran reading, memorization, waqf-research, printed-mushaf
layout, and scholarly-review system. It has four kinds of state that must not be
mixed accidentally:

1. immutable Quran/runtime artifacts in `data/`;
2. local editor working databases;
3. Supabase draft/published reviewer state;
4. offline pipeline artifacts, manifests, and CV models.

The codebase is working and its existing automated suite passes. Recent work
also improved Quran-data integrity audits, atomic waqf publishing, layout word
index handling, audio delivery, thematic memorization context, and print review.
The remaining risk is concentration of responsibilities rather than a need for
a rewrite.

### Audit corrections to the original proposal

- Shared browser foundations (`athar-api.js`, `athar-ui.js`, mushaf/page chrome)
  already exist and are adopted by the main pages. Phase C should extend these,
  not create competing abstractions.
- Atomic publishing already exists for editor marks. The remaining work is to
  make its edition capability contract singular and to reuse its pattern for
  every release writer.
- Layout Studio and the CV pipeline now label word-ID namespaces explicitly in
  important paths. Typed word references remain useful, but this is a gradual
  hardening task rather than an emergency rewrite.
- Several pipelines already write temporary artifacts and manifests. Phase D
  should standardize the good implementations instead of replacing them.

## Target boundaries

```text
Flask route -> application service -> domain policy/value -> repository port
                                                    -> SQLite adapter
                                                    -> Supabase adapter

offline source -> extract -> validate -> stage -> audit -> atomic artifact
```

Routes parse and authorize. Services coordinate use cases. Domain code carries
explicit Quran identities and policies without importing Flask. Adapters own SQL,
HTTP, filesystem, and external-provider details.

## Phase A — contracts and runtime safety

Goal: make structural work safe before moving code.

### A1. Characterize public behavior — in progress

- [x] broad route and malformed-input tests;
- [x] editor feature/deployment gating tests;
- [x] static, dynamic, editor, and error cache tests;
- [x] clean-process import test protecting runtime database mtimes and hashes;
- [ ] route-contract inventory containing method, auth, cache class, status, and
  stable JSON keys for every `/api/` route;
- [ ] browser smoke matrix for reader, تثبيت, waqf guide, editor, Layout Studio,
  mark review, and CV labeling on desktop and mobile widths.

### A2. Make startup read-only — first slice complete

- [x] remove `CREATE INDEX` from `app.py` import;
- [x] remove derived `waqf_symbols.db` initialization from dataset import;
- [x] provide explicit `pipeline/prepare_runtime_databases.py` preparation;
- [x] add deliberate read-only mode to `core.db.connect` and use it for the
  request-scoped word database and thematic-context database;
- [ ] migrate remaining read-only SQLite callers in small module-level slices;
- [ ] add schema/producer/source-checksum metadata to derived artifacts;
- [ ] expose artifact readiness without rebuilding missing data at runtime.

### A3. Close security and persistence contract gaps — complete

- [x] make Bahrain publishability agree in Python and both Supabase SQL files;
- [x] apply the SQL migration to each deployed Supabase environment and assert
  its schema version in readiness checks;
- [x] require a non-default editor session secret whenever cloud auth is active;
- [x] define one authorization matrix for review reads, CV writes, layout writes,
  classical review, activity, and publishing;
- [x] make editor/authenticated/draft responses `no-store` by default and only
  allow public caching through an immutable-route allowlist;
- [x] validate cloud editions from capabilities, not local SQLite columns.

### A4. Stabilize failures

- [x] introduce typed validation, not-found, conflict, dependency, upstream, and
  persistence errors;
- [x] translate them centrally while retaining the current `error` response key
  and status codes;
- [x] keep SQL, paths, stack traces, subprocess output, and upstream bodies in
  server logs only;
- [x] reject malformed successful Supabase payloads at the adapter boundary.

Exit gate: full tests, clean import, editor-on/off smoke tests, Supabase readiness,
and no undocumented public contract change.

## Phase B — Quran domain and edition boundaries

Goal: stop raw integers and edition strings from carrying hidden meaning.

### B1. Explicit Quran identities

Introduce immutable values with conversion tests:

- `VerseKey(surah, ayah)`;
- `WordRef(verse, position, index_space)`;
- `IndexSpace`: token-zero-based, content-word-one-based, QPC global,
  Quran-script stable, and edition-layout global.

Start at persistence/CV/layout boundaries. Keep JSON integers unchanged and do
not bulk-convert rendering code.

### B2. One edition registry

Create one capability registry for reading, memorization, waqf, Layout Studio,
CV, local/cloud editing, and publishing. Capabilities include layout source,
word space, waqf source, font, reference scan, page range, cloud storage, auth,
and publishability. Existing constants remain compatibility projections until
all callers migrate.

### B3. Narrow persistence ports

- `WaqfStore`: read marks, save draft, read published, publish revision;
- `LayoutStore`: page/index/profile reads and atomic page/profile writes;
- `ReviewStore`: decisions, notes, progress, and audit;
- `AudioProvider`: Drive, YouTube, CDN, and local resolution.

Give SQLite and Supabase adapters the same contract tests. Retain
`core/supabase_editor.py` as a compatibility facade during extraction.

### B4. Application services

Extract one vertical use case at a time, in this order:

1. publish reviewed waqf edition;
2. save/load Layout Studio page and profile;
3. mark-review decision and progress;
4. audio source resolution;
5. CV label-to-word attachment.

Exit gate: route modules perform only parsing, authorization, service calls, and
serialization for the migrated use cases.

## Phase C — browser reliability

Goal: reduce race conditions, unsafe HTML, and oversized controllers.

- Add one shared latest-request/abort helper and migrate asynchronous panels.
- Add safe storage parsing/versioning while keeping current localStorage keys.
- Establish a trusted-rich-text boundary; otherwise render API data with DOM
  nodes or escaped text.
- Migrate raw API-driven `innerHTML` in waqf research, CV review, editor audit,
  memorization selectors, and integrity review first.
- Add one accessible dialog/sheet controller with focus trap, Escape, and focus
  restoration.
- Extract pure state/data/render functions from `waqf_guide.js`,
  `mushaf_memorize.js`, `mushaf_editor.js`, and `script.js` behind current page
  globals and template IDs.

Exit gate: no stale response can replace newer state in migrated panels, and no
untrusted API field reaches HTML without an explicit sanitizer/escape boundary.

## Phase D — reproducible data releases

Goal: make every shipped database explainable and replaceable atomically.

- Define a canonical artifact registry shared by runtime and pipelines.
- Require builders to accept an output root for isolated tests.
- Standardize manifests: schema and producer versions, git SHA, source identity,
  source/input hashes, dependency versions, row/coverage metrics, and output hash.
- Standardize `extract -> validate -> stage -> audit -> atomic replace`.
- Keep one release writer per dataset; legacy/destructive commands require an
  explicit replacement flag and backup.
- Add release preflight for Quran databases, layouts, waqf data, reciters,
  thematic topics, reference scans, and CV models.

Exit gate: identical inputs produce identical content hashes, and readers can
only observe the old complete artifact or the new complete artifact.

## Recommended implementation queue

Each item should be one reviewable pull request unless tests force a smaller
split.

1. Add the route-contract inventory and generate a failing test when a route
   silently changes method/auth/cache/response keys.
2. Introduce `VerseKey`, `WordRef`, and `IndexSpace`; migrate CV attachment and
   published-waqf sync first because index confusion is highest impact there.
3. Build the unified edition registry, initially exporting today's constants.
4. Extract the atomic waqf-publish service and repository contracts.
5. Standardize the Bahouth topics and CV manifests using the existing Quran
   integrity/word-meaning manifests as the reference implementation.
6. Migrate frontend request cancellation and unsafe HTML one page at a time.

## Verification on every slice

```bash
git diff --check
python3 -m compileall -q app.py core modules pipeline tests
python3 -m pytest -q
```

For UI or deployment changes also run editor-on/editor-off smoke tests, the
Supabase readiness check, and focused browser tests. Never mix reviewer data,
layout edits, generated database replacement, and architectural refactoring in
the same commit.
