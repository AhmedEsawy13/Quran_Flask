# أثَر — Athar

Athar is a web app for reading, reciting, memorizing and **studying the Holy
Quran**, with particular depth in **علم الوقف والابتداء** — the classical science
of pause and resumption. It is a Flask backend organised as feature **modules**
over a shared `core`, plus a Next.js public frontend (`frontend/`) that is
progressively taking over the user-facing pages.

- Flask origin (data plane + legacy pages): <https://waqfquran-d0b6fce4874e.herokuapp.com>
- Next.js frontend: <https://athar-web-teal.vercel.app>

## The product

Four public doors, one research lab, and a set of internal tools.

| Door | Route | What it does |
|---|---|---|
| **المصحف** — Reading | `/read` | Printed-mushaf reader: word-by-word audio, five tafsirs, tajweed colouring, i'rāb, asbāb al-nuzūl, المتشابهات, themes, bookmarks |
| **تثبيت** — Memorize | `/memorize` | Circular Segmented Repetition player on per-reciter word timestamps, with optional live ASR listening |
| **مُكْث** — Pause guide | `/waqf` | Multi-reciter validated waqf stops per verse, the four classical waqf books («لماذا يُوقف هنا؟»), contemporary توجيه |
| **تدريب** — Waqf practice | `/waqf-practice` | Tap where you would pause; graded against the mushaf marks and classical rulings, with ASR/tajweed checking |
| مختبر الوقف — Waqf lab | `/waqf-lab` | Quran-wide research: word/pattern search, reciter solos and clusters, mushaf agreement/disagreement, waqf at ayah ends |
| `/`, `/credits` | | Landing page and source attribution |

Everything above exists twice on purpose during the migration: as a Flask-rendered
page (`templates/`) and as a Next.js page (`frontend/app/`). Flask stays the
**data plane** — every API, font, audio redirect and the ASR/editor tools; Next.js
never re-implements Quran logic. What has moved and what has not:
[`frontend/README.md`](frontend/README.md) and [`.cursor/rules/next-migration.mdc`](.cursor/rules/next-migration.mdc).

### The waqf science, in brief

- **Multi-reciter guide** — pause positions validated against several reciters'
  actual recitation, repeats filtered, solo (منفرد) stops flagged.
- **Four classical books** — المكتفى (الداني), منار الهدى (الأشموني), القطع والائتناف
  (النحاس), إيضاح الوقف (ابن الأنباري): parsed from OpenITI/Shamela, aligned to the
  exact recited word, each with its grade (تام/كاف/حسن/جائز/…), its علّة, and
  attribution when a book relays another scholar. Guarded by audits that run in CI.
- **Nine mushaf editions' marks** — المدينة (الجديد/القديم), الأزهر, الشمرلي, ورش,
  الهندي, قطر, الكويت, البحرين — comparable side by side.
- **Recitation checking** — an in-browser Zipformer phoneme model (onnxruntime-web)
  follows the learner, detects stops and flags tajweed slips.

### Reader features

Word-by-word highlighting and click-to-hear; غريب الكلمات meanings; five Arabic
tafsirs served from local data (no live API calls); several reciters with range
selection and looping; dark and sepia themes; multiple Arabic fonts (Uthmanic
Hafs/Warsh, Digital Khatt, IndoPak, per-page Shemrly and QPC fonts); bookmarks in
`localStorage` (no login); English voice commands and ←/→ verse navigation.

## Architecture

```text
app.py            create_app() factory + FEATURES-driven blueprint registry
core/             shared, Flask-light foundation (always loaded)
modules/          one file per feature area; importing a module attaches its routes
pipeline/         offline data builds and audits (never run at request time)
scripts/          operational tooling: smoke tests, browser matrix, reciter sync
tests/            pytest suite (+ tests/js for the DTW ASR helper)
data/ reciters/   the shipped datasets (SQLite + JSON), read-only at runtime
templates/ static/  Flask-rendered pages, JS/CSS, per-page mushaf fonts
frontend/         Next.js 16 public UI (Vercel)
models/           ONNX waqf-glyph detectors used by the CV tooling
docs/             operational and design docs — start at docs/README.md
```

### `core/`

| File | Role |
|---|---|
| `config.py`, `loader.py` | Paths, reciter/layout constants, JSON loading with CDN fallback |
| `datasets.py`, `text.py` | Quran text datasets; search normalisation and waqf-mark extraction |
| `verse_words.py` | A verse as recited words, and mapping printed-mushaf token indices to them |
| `db.py`, `lru.py` | Per-request SQLite access (read-only mode available), bounded LRU cache |
| `http.py`, `http_cache.py`, `errors.py` | Security headers/CSP, cache policy, gzip, typed errors → JSON |
| `blueprints.py` | The five blueprint objects |
| `mushaf_waqf.py`, `memorization.py`, `classical_review.py`, `classical_illa.py`, `tawjih.py` | Waqf marks, reciter catalog + breathing-guide builder, classical/توجيه data layers |
| `supabase_editor.py`, `layout_persistence.py`, `edition_capabilities.py` | Cloud editor + layout persistence and the per-edition capability registry |

### `modules/` → blueprints

| Blueprint | Modules |
|---|---|
| `core` | `quran_api` (text, search, audio, health), `layouts` (mushaf page payloads), `seo` (`robots.txt`, `sitemap.xml`, `llms.txt`), credits |
| `reading` | `reading` |
| `memorize` | `memorize` |
| `breathing` | `breathing` (مُكْث + تدريب), `waqf_research` (the `/api/waqf-research/*` family) |
| `editor` *(off in production)* | `editor`, `editor_auth`, `layout_studio` (+ `layout_engine`, `layout_editions`, `azhar_layout` aliases), `waqf_mark_review`, `classical_review`, `tawjih_review`, `cv_waqf_ui`, `activity`, `font_lab`, `quran_integrity_review` |

### Choosing what a process serves

One entrypoint (`gunicorn app:app`); environment variables pick the modules:

| Variable | Effect |
|---|---|
| `FEATURES` | Comma-separated blueprints, e.g. `FEATURES=reading` or `memorize,breathing`. Default `reading,memorize,breathing`; `core` is always on |
| `ENABLE_EDITOR` | Truthy (`1/true/yes/on`) mounts the write-capable `editor` blueprint and every internal tool. **Unset in production** |
| `EDITOR_DEPLOYMENT` | Required as well when `DYNO` is set (Heroku), so a stale `ENABLE_EDITOR` on a public dyno stays fail-closed |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `EDITOR_SESSION_SECRET` | Cloud editor (invite-gated drafts; admin publish). `EDITOR_SESSION_SECRET` ≥ 32 chars, required when Supabase is set |
| `PUBLIC_BASE_URL` | Canonical origin for sitemap/canonical/OG URLs |

`python3 app.py` (local) turns the editor on by default. Full production
configuration: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md); editor policy:
[`docs/EDITOR_AUTHORIZATION.md`](docs/EDITOR_AUTHORIZATION.md),
[`docs/SUPABASE_EDITOR.md`](docs/SUPABASE_EDITOR.md).

## Data

Everything is pre-built and committed; no database server. Highlights of `data/`:

| Path | Contents |
|---|---|
| `quran_script.db`, `quran_text/`, `word_name.db` | Quran script and word positions, multi-edition text, word meanings |
| `qpc-v1/v4-15-lines.db`, `digital-khatt-15-lines.db`, `mushaf-*-layout.db`, `glyph_mappings.db`, `mushaf_layout_inferred.db` | Page layouts for each printed edition |
| `mushaf_waqf.db`, `waqf_symbols.db`, `waqf_glyphs.json` | Waqf marks per mushaf and their glyphs |
| `classical_waqf.db` | The four classical books aligned to word positions |
| `tafseer_local.db`, `asbab_local.db`, `tajweed_local.db`, `tajweed_notes_local.db`, `verse_topics.db` | Tafsir, asbāb, tajweed, Bahouth topics |
| `research_cache/` | Baked مُكْث research payloads (rebuilt by `pipeline/precompute_research.py`) |
| `reciters/<slug>/` | Per-reciter word/verse/letter timing |

Every dataset has a builder in [`pipeline/`](pipeline/README.md), which also
records which scripts are one-time provenance. The 52 MB of QUL reciter
timestamps are **not** in git; `scripts/import_qul_reciters.py --restore` fetches
the release pinned in `reciters/.qul_sync_state.json` (Heroku does this in
`bin/post_compile`; a weekly workflow proposes upgrades).

Runtime never migrates or rebuilds data. After changing Quran sources or
schemas, run `python3 pipeline/prepare_runtime_databases.py`.

## Getting started

Requirements: Python 3.12 (see `.python-version`), Node ≥ 20.19 for the frontend.

```bash
git clone https://github.com/AhmedEsawy13/Quran_Flask.git && cd Quran_Flask
python3.12 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 scripts/import_qul_reciters.py --restore     # reciter timestamps (not in git)
python3 app.py                                        # http://localhost:5001, editor enabled
```

Serve only the public modules, as production does:

```bash
ENABLE_EDITOR= FEATURES=reading,memorize,breathing python3 app.py
```

Optional extras live in `requirements/`: `dev.txt` (tests, Playwright, LLM
extraction clients), `cv.txt` / `cv-train.txt` (OpenCV waqf detection),
`font-audit.txt`.

**Recitation checking (ASR) needs a model that is not in git.** The 73 MB
`quran_phoneme_zipformer.int8.onnx` and its source JSONs live in `static/asr/`
locally (only the small `zipformer_meta.json` / `zipformer_phonemes.json` are
tracked). Without the model the live-listening features in تثبيت and تدريب cannot
start; everything else works.

Frontend:

```bash
cd frontend && cp .env.example .env.local && npm install && npm run dev   # http://localhost:3000
```

## Testing and CI

```bash
python3 -m pip install -r requirements/dev.txt
python3 -m pytest                       # full suite
python3 -m pytest tests/test_classical_waqf_quality.py -v
python3 pipeline/audit_release_readiness.py
python3 scripts/smoke_test.py --local --include-editor
cd frontend && npm run verify && npm run test:smoke
```

The suite covers app boot under every feature combination, the API route
contracts (`docs/api-route-contracts.json` — regenerate with
`python3 pipeline/generate_route_contracts.py` after an intentional change), the
classical-book pipeline (text quality, attribution, word alignment), the research
endpoints, the editor and layout tools, and read-only-at-import guarantees.

The تثبيت typography audit uses real Chromium measurements
(`python3 -m playwright install chromium`, then
`python3 scripts/audit_mushaf_fonts.py --mode risk|full`; reports go to
`artifacts/mushaf-font-audit/`).

GitHub Actions (`.github/workflows/`): core CI, frontend CI, browser smoke matrix,
classical-data and font audits on relevant PRs, a daily production smoke test, and
scheduled syncs (QUL reciters, QVP page engine, published waqf marks) that open PRs.
Details: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## API

Representative public endpoints; the complete, generated inventory (methods, auth,
cache class, response keys) is [`docs/api-route-contracts.json`](docs/api-route-contracts.json).

| Area | Endpoints |
|---|---|
| Text | `/api/surahs` · `/api/surahs/<s>/ayahs[/<a>]` · `/api/quran-text?source=` · `/api/search?q=` · `/api/word-search?q=` · `/api/transliteration` |
| Mushaf pages | `/api/{shamarly,azhar,qpc-v1,qpc-v2,digital-khatt}/page/<n>` and `…/page-by-ayah/<s>/<a>` · `/api/mushaf-versions` |
| Reader aids | `/api/tafseer/<s>/<a>` · `/api/tajweed/<s>/<a>` · `/api/tajweed-notes/…` · `/api/eerab/…` · `/api/asbab/…` · `/api/mutashabihat/…` |
| Audio | `/api/audio-proxy?url=` (allow-listed CDNs) · `/api/yt-audio?url=` (approved catalogue only) |
| Memorize | `/api/memorization-reciters` · `/api/memorization/<s>` · `…/<s>/breathing` · `/api/memorization/context[-map]` |
| Waqf | `/api/waqf/<s>/<a>` · `/api/classical-waqf/<s>/<a>` · `/api/tawjih/<s>/<a>` · `/api/waqf-map/<s>` |
| Waqf research | `/api/waqf-research/{stats,solos,patterns,clustering,ibtidaa,saktat,mandatory,marks,mushaf-agreement,mushaf-similarity,mushaf-diff,ayah-ends}` |
| Practice | `/api/waqf-practice/{passage/<s>/<from>/<to>,phonemes/…,grade,tajweed}` |
| Monitoring | `/api/health` — `200` healthy / `503` degraded; never cached |

Unexpected errors return a generic JSON body; details (tracebacks, paths, SQL)
stay in server logs.

## Security posture

- Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff` on every response
  (`core/http.py`); editor and error responses are `no-store`.
- The audio proxy only redirects HTTPS URLs on an allow-list of audio CDNs (Drive
  audio only for pre-approved URLs); `/api/yt-audio` accepts only catalogued videos.
- Every write path lives on the `editor` blueprint, which is not mounted on a
  public deployment; with Supabase configured it additionally requires an invite
  session signed by `EDITOR_SESSION_SECRET`.
- Secrets live in environment variables / a gitignored `.env`; nothing is baked
  into the repo or the frontend bundle.

## Contributing and licence

Fork, branch, open a pull request; CI must pass. Keep Quran wording, tafsir and
waqf rulings sourced from the local datasets or the Tafsir/Bahouth MCPs — never
invented. New classical books follow
[`docs/CLASSICAL_BOOK_ONBOARDING.md`](docs/CLASSICAL_BOOK_ONBOARDING.md). Source
attributions are shown on `/credits`.

No `LICENSE` file is included yet, so all rights are reserved by default. Several
bundled datasets and fonts come from third parties (QUL, Tanzil, OpenITI,
Digital Khatt, …) with their own terms — settle the licence before advertising the
repo as open source.

Contact: [Ahmed Esawy](https://github.com/AhmedEsawy13).
