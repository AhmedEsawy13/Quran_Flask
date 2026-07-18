# أثَر — Quran Flask

Quran_Flask (product name **أثَر**, "mع القرآن") is a modular web application for
reading, reciting, memorizing, and studying the Holy Quran, with a particular
depth in **علم الوقف والابتداء** — the classical science of pause and resumption
points. It is built with Flask and organized into independent feature
**modules** (blueprints) over a shared `core`, so each module can be enabled
per deployment and served on its own domain.

## Modules · الوحدات

| Page (nav) | Module | Blueprint | What it does |
|---|---|---|---|
| **المصحف** | Reading | `reading` | Main mushaf page: word-by-word audio, tafseer, tajweed, i'rāb, themes, bookmarks |
| **تثبيت** | Memorization | `memorize` | Circular Segmented Repetition player for memorizing a surah, with live ASR listening |
| **مُكْث** | Pause Guide | `breathing` | Multi-reciter waqf stops + all four classical waqf books («لماذا يُوقف هنا؟») + research tools |
| **تدريب** | Waqf Practice | `breathing` | Tap-to-stop practice graded against mushaf marks and classical rulings, with ASR/tajweed checking |
| *(local only)* | Mushaf Editor | `editor` | Click-to-edit waqf tool (Qatar/Kuwait/المدينة layouts). Admin-only — the **only writer** |

All modules sit on a shared **`core`** package (Quranic text, search, and
mushaf page-rendering) that is always enabled. `مُكْث` and `تدريب` are two pages
served by the same `breathing` blueprint — see [Architecture](#architecture)
for how modules are turned on/off per deployment.

## Features

### 📜 **علم الوقف والابتداء — Waqf & Pause Science** (`مُكْث` + `تدريب`)
This is the app's deepest feature area, well beyond a simple "where do I
pause" guide:
- **Multi-reciter breathing guide**: validated pause positions cross-checked
  against several Qāris' actual recitation, with repeats filtered and solo
  (منفرد) stops flagged separately.
- **Classical waqf books**: four books — المكتفى (الداني), منار الهدى
  (الأشموني), القطع والائتناف (النحاس), وإيضاح الوقف (ابن الأنباري) —
  harvested from OpenITI, aligned to the exact recited word, and shown per
  stop as a «لماذا يُوقف هنا؟» card with each imam's grade (تام/كاف/حسن/جائز/…),
  the علّة (reasoning), and attribution when one book relays another
  scholar's opinion rather than stating its own.
  See [Deep dives](#deep-dives) for more on how this data is built and kept
  correct.
- **الابتداء بما قبله** and **المتشابهات**: research tabs for resumption-point
  analysis and finding verses similar in wording across the Quran.
  - **السكتات**: reference list of the mandatory Hafs pause points.
- **تدريب الوقف (waqf practice)**: the learner taps where they'd pause in a
  passage; their choices are graded against the mushaf's own marks and the
  classical books' rulings, with a caution tier for genuinely disputed
  (خلاف) stops rather than marking them flatly wrong.
- **Recitation checking (تسميع)**: in-browser ASR (a ported zipformer
  phoneme model) listens to the learner read and flags tajweed errors,
  reusing the same silence/pause detection built for the breathing guide.

### 🎨 **Theme & Display**
- **Dark / Sepia modes**: comfortable reading in low light or for extended sessions
- **Multiple Arabic Fonts**: UthmanicHafs (Hafs & Warsh), Digital Khatt, IndoPak Nastaleeq, and Mushaf (Shemrly page) fonts
- **Responsive Design**: optimized for mobile and desktop
- **Theme Persistence**: saved and restored on next visit

### 📖 **Quranic Text Features**
- **Word-by-word Highlighting**: real-time highlighting during audio recitation
- **Word Meanings (غريب الكلمات)**: display meanings of difficult Arabic words
- **Clickable Words**: click any word to hear its individual pronunciation
- **Transliteration**: phonetic pronunciation of Arabic text
- **Tafseer Integration**: 5 Arabic commentary sources (Al Qurtubi, Al Saddi, Al-Baghawi, Al-Muyassar, Al-Mukhtasar), served from local data — no live API calls

### 🎵 **Advanced Audio Features**
- **Multiple Reciters**: Abdul Basit Abdus Samad (Mujawwad/Murattal), Mohamed al-Minshawi (Mujawwad/Murattal), Mahmoud Khalil al-Husary (Mujawwad/Muallim), Ibrahim Al-Akhdar, Ayman Rushdi Suwaid, Mahmoud Ali Al-Banna, Mustafa Ismaeel, and more
- **Audio Synchronization**: precise word-by-word audio timing
- **Range Selection & Looping**: play or repeat multiple consecutive verses
- **Audio Preloading**: next ayah preloaded for seamless navigation

### 🎧 **رُسوخ — Memorization Mode**
- **Circular Segmented Repetition**: a structured repeat-and-expand drill
  pattern for memorizing a surah segment by segment
- **Live listening**: optional real-time ASR follows along and flags
  silences/stalls during a memorization pass

### 🔖 **Bookmark System**
- Save, manage, and jump to bookmarked verses — no login required, stored in `localStorage`

### 🎤 **Interactive Features**
- **Voice Commands**: control the app using speech recognition (English)
- **Keyboard Navigation**: arrow-key verse navigation
- **Modal Dialogs & Toasts**: range selection and notification UI

### 🔧 **Technical Features**
- **RESTful API** across every module
- **Caching**: `@lru_cache`, precomputed research caches on disk, and Cache-Control headers
- **Security Headers**: CSP and related HTTP headers
- **SQLite**, hardened for concurrent access (WAL mode + busy timeout) on Heroku's ephemeral filesystem

## Architecture

The app is a single codebase split into a shared `core` package and
per-feature `modules/`, assembled by an application factory in
[`app.py`](app.py) — which is now just the factory itself (243 lines):
static-asset hashing, the CSP/caching `after_request` hook, error handlers,
and env-driven blueprint registration. Every blueprint's routes live in
`modules/`:

```
core/
├── config.py        # DB paths, reciter config, layout constants, waqf/search regexes
├── blueprints.py     # Blueprint objects: core_bp, reading_bp, memorize_bp, breathing_bp, editor_bp
├── db.py             # Shared per-request word_name.db connection (get_db / teardown)
├── datasets.py        # Raw + normalised Quran text datasets (JSON, CDN fallback)
├── loader.py          # JSON loading + CDN-or-local fetch helpers
├── lru.py             # Bounded LRU cache used across modules
├── mushaf_waqf.py      # Waqf DB access layer (mushaf_waqf.db / mushaf-qatar-layout.db)
├── memorization.py     # Reciter catalog, audio-URL resolution, breathing-guide builder
│                       #   (shared by modules/memorize.py AND modules/breathing.py)
└── text.py            # Search normalisation + waqf-mark extraction

modules/
├── quran_api.py        # core_bp: surah/ayah text, audio (proxy/YouTube/reciters), search
├── layouts.py         # Mushaf page builders + reading-page routes
├── editor.py          # /mushaf-editor blueprint — the ONLY write path
├── breathing.py        # مُكْث: pause guide, classical waqf books, waqf-practice grader
├── waqf_research.py    # مُكْث research tabs: the /api/waqf-research/* analytics family
├── reading.py          # المصحف: tafseer, tajweed, i'rab, waqf symbols, المتشابهات
└── memorize.py         # تثبيت: the Circular Segmented Repetition player + routes

app.py                 # create_app() factory + env-driven blueprint registration only
```

### Selecting modules per deployment

Every process runs the same entrypoint (`gunicorn app:app`); which modules it
serves is controlled by environment variables:

| Env var | Effect |
|---|---|
| `FEATURES` | Comma-separated module list to enable, e.g. `FEATURES=reading` or `FEATURES=memorize,breathing`. Defaults to `reading,memorize,breathing`. `core` is **always** included. |
| `ENABLE_EDITOR` | A truthy value (`1`, `true`, `yes`, or `on`) mounts the write-capable `editor` module. **Off by default** — keep it to localhost so production stays read-only. |

This lets you put each module on its own domain while sharing one repo and one
set of databases:

| Domain / app | Env | Serves |
|---|---|---|
| `mushaf.example.com` | `FEATURES=reading` | المصحف + core |
| `repeat.example.com` | `FEATURES=memorize` | تثبيت + core |
| `waqf.example.com` | `FEATURES=breathing` | مُكْث + تدريب + core |
| your laptop | `ENABLE_EDITOR=1` | everything, incl. محرّر المصحف |

> **Note on the editor:** it is the only module that *writes* (to
> `data/mushaf_waqf.db` / `data/mushaf-qatar-layout.db`). Because production
> filesystems are ephemeral, the editor is intended to run **locally** — you
> edit, commit the updated `.db`, and redeploy so the read-only modules serve
> the new data.

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AhmedEsawy13/Quran_Flask.git
   cd Quran_Flask
   ```

2. **Install dependencies** (add `-r requirements-dev.txt` instead if you're also running tests):
   ```bash
   python3 -m pip install -r requirements.txt
   ```

3. **Restore the reciter timestamp data** (not tracked in git — 52 MB
   refreshed weekly upstream; downloads the release pinned in
   `reciters/.qul_sync_state.json`):
   ```bash
   python3 scripts/import_qul_reciters.py --restore
   ```
   On **Heroku** this happens automatically on every build via
   `bin/post_compile`.

4. **Run the Flask application:**
   ```bash
   python3 app.py            # serves on http://localhost:5001
   ```
   To work on the editor module locally, enable it explicitly:
   ```bash
   ENABLE_EDITOR=1 python3 app.py
   ```
   To serve only a subset of modules (as in production), set `FEATURES`:
   ```bash
   FEATURES=reading python3 app.py
   ```

5. Open `http://localhost:5001` in your browser.

### Requirements
- Python 3.10+
- SQLite3 (included with Python)
- Modern web browser with HTML5 support (WebAssembly + Web Audio for the ASR features)
- Internet connection for external CDN resources

## Testing

```bash
python3 -m pip install -r requirements-dev.txt
pytest              # full suite
pytest -q tests/test_classical_waqf_quality.py -v   # a single file
```

The تثبيت font audit uses real Chromium layout measurements. Install its
browser once, then run either the pull-request corpus or all 604 pages:

```bash
python3 -m playwright install chromium
python3 scripts/audit_mushaf_fonts.py --mode risk
python3 scripts/audit_mushaf_fonts.py --mode full
```

Both modes test Old Madinah and Digital Khatt at desktop, mobile, and
two-page-spread sizes. Reports are written under
`artifacts/mushaf-font-audit/`; the command exits non-zero for compression,
word-spacing, edge-alignment, expansion, or facing-page-size violations.

`tests/` covers: app boot / feature-flag combinations, the classical waqf
pipeline (text quality, attribution, and word-position alignment — three
separate concerns, three files), مُتشابهات, and the waqf research endpoints.
See [pipeline/build_classical_waqf.py](pipeline/build_classical_waqf.py) for
the data these tests pin down, and the module docstring at the top of each
`tests/test_classical_waqf_*.py` file for the specific bugs each guards
against.

## API Endpoints

Representative endpoints — see `app.py` (routes not yet split out) and
`modules/*.py` for the full list.

### Surahs & Text
- `GET /api/surahs` · `GET /api/surahs/<surah>/ayahs` · `GET /api/surahs/<surah>/ayahs/<ayah>`
- `GET /api/quran-text?source=<font_source>` — Quranic text in a given font/edition
- `GET /api/search?q=<query>` · `GET /api/word-search?q=<query>`

### Audio
- `GET /api/reciters/<reciter>/ayahs/<ayah>/audio`
- `GET /api/audio-proxy?url=<audio_url>`

### Tafseer
- `GET /api/tafseer/<surah>/<ayah>` — all 5 Arabic tafsirs, served from local data

### Waqf & Pause Science (`مُكْث` / `تدريب`)
- `GET /api/waqf/<surah>/<ayah>` — mushaf waqf marks for a verse
- `GET /api/classical-waqf/<surah>/<ayah>` — the four classical books' rulings, aligned per word
- `GET /api/recitation-guide/<surah>/<ayah>` · `GET /api/reciter-compare/<surah>/<ayah>` — multi-reciter pause validation
- `GET /api/waqf-research/{solos,patterns,clustering,ibtidaa,saktat,mushaf-agreement,mushaf-similarity,...}` — the مُكْث research tabs
- `GET /api/waqf-practice/passage/<surah>/<from_ayah>/<to_ayah>` · `POST /api/waqf-practice/grade` — تدريب الوقف practice + grading
- `POST /api/waqf-practice/tajweed` — ASR-based recitation/tajweed check

### Monitoring
- `GET /api/health`

## Deep dives

Some subsystems have enough nuance that they're documented in more depth than
fits here:
- **The classical waqf pipeline** ([pipeline/build_classical_waqf.py](pipeline/build_classical_waqf.py)):
  harvesting four differently-structured classical texts from OpenITI markdown,
  aligning each citation to the exact recited word (including disambiguating
  a word that repeats within the same verse), detecting when a book relays
  another scholar's opinion rather than stating its own, and the text-quality
  guards that keep quotes/notes from being silently truncated. The module
  docstrings in `tests/test_classical_waqf_*.py` are the best entry point.
- **The Shemrly (شمرلي) mushaf renderer**: three SQLite databases plus
  per-page font subsets work together to reproduce the classical Madinah
  mushaf's exact line breaks and glyphs — see `core/mushaf_waqf.py` and
  `modules/layouts.py`.
- **In-browser ASR**: a ported zipformer phoneme model (`static/js/mushaf_zipformer.js`)
  provides tajweed-aware recitation checking for `تدريب`; an older,
  simpler FastConformer-based listener (`static/js/mushaf_asr.js`, lazy-loaded)
  still powers live silence/stall detection during `تثبيت` memorization drills.

## Technology Stack

### Backend
- **Flask 3.0.3** — Python web framework, deployed via `gunicorn`
- **SQLite3** — every dataset (Quranic script, waqf marks, classical books, tafseer, reciter timing) ships as a pre-built `.db` or `.json`, no external database server
- **quran-transcript** — phoneme-level transcript/tajweed utilities backing the ASR features

### Frontend
- **Vanilla JavaScript** — no framework dependency
- **WebAssembly (onnxruntime-web)** — in-browser ASR model inference
- **Font Awesome 6**, **Tippy.js**, **Web Speech API**

## Usage

### Basic Navigation
1. **Select Reciter** from the dropdown
2. **Choose Surah** and **Pick Ayah**
3. **Play Audio** with the transport controls

### Advanced Features
- **Theme Toggle**: moon (🌙) icon for dark mode, leaf (🍃) icon for sepia mode
- **Font Selection**: change Arabic font from the font dropdown
- **Word Meanings**: click "عرض غريب الكلمات" to show/hide word meanings
- **Voice Commands**: click "امر صوتي" and speak commands in English
- **Range Selection / Loop**: "تحديد نطاق" / "تكرار الاية"
- **Bookmarks**: "علامة مرجعية" to save, "المرجعيات" to view saved bookmarks
- **مُكْث**: pick a verse to see multi-reciter pause validation and the classical books' rulings, with research tabs (المتشابهات، الابتداء، السكتات، …)
- **تدريب**: tap where you'd pause in a passage, get graded, optionally read aloud for ASR/tajweed feedback

### Keyboard Shortcuts
- **←** / **→** — previous / next verse

### Voice Commands (English)
- "chapter [number] verse [number]" / "chapter [number]" / "verse [number]"

## Deployment

The app deploys on **Heroku** via the [`Procfile`](Procfile)
(`gunicorn app:app`). Because each module is selected by environment variables,
the same repo can be deployed to several Heroku apps — one per domain/module —
each scaled independently:

```bash
heroku config:set FEATURES=reading   -a quran-reading
heroku config:set FEATURES=memorize  -a quran-memorize
git push https://git.heroku.com/quran-reading.git main
```

`bin/post_compile` runs on every build to restore the reciter timestamp data
(see [Installation](#installation)) — if it fails, the build still succeeds
and simply serves without that reciter's timing.

> **Read-only at runtime:** the read modules (`reading`, `memorize`,
> `breathing`, `core`) only read databases shipped in the slug, so they scale
> horizontally across dynos cleanly. The writing `editor` module is excluded
> from production (`ENABLE_EDITOR` unset) and run locally instead.

## Project Structure

```
Quran_Flask/
├── app.py                    # create_app() factory + remaining reading/memorize/breathing routes
├── core/                     # Shared package (always enabled) — see Architecture
├── modules/                  # Extracted per-feature blueprints (layouts, editor)
├── pipeline/                 # Data-pipeline / DB-build scripts (one per source dataset)
│   └── classical_sources/    # Vendored OpenITI classical waqf book texts
├── scripts/                  # Maintenance scripts (e.g. QUL reciter sync)
├── tests/                    # pytest suite — see Testing
├── data/                     # Pre-built datasets (SQLite + JSON), see below
├── reciters/                 # Per-reciter word/verse/letter timing data
├── static/                   # JS, CSS, fonts, ASR model assets
├── templates/                # One HTML template per page/module
│   ├── index.html            #   المصحف (reading)
│   ├── mushaf_memorize.html  #   تثبيت (memorize)
│   ├── waqf_guide.html       #   مُكْث (breathing guide + classical waqf books)
│   ├── waqf_practice.html    #   تدريب (waqf practice + ASR)
│   └── mushaf_editor.html    #   محرّر المصحف (editor, local-only)
├── Procfile / runtime.txt / bin/post_compile   # Heroku deployment
└── requirements.txt / requirements-dev.txt
```

### Data sources (`data/`)
- `quran_text/` — Quranic text in multiple fonts/editions (JSON)
- `quran_script.db` — Quranic script + word positions
- `word_name.db` — word-meaning database
- `mushaf_waqf.db` / `mushaf-qatar-layout.db` — waqf marks per mushaf layout (written by the editor)
- `classical_waqf.db` — the four classical waqf books, aligned per word (built by `pipeline/build_classical_waqf.py`)
- `qpc-v4-15-lines.db` / `qpc-v1-15-lines.db` / `mushaf-qatar-layout.db` / `digital-khatt-15-lines.db` — page-layout databases
- `glyph_mappings.db` / `mushaf_layout_inferred.db` — Shemrly page rendering
- `tajweed_local.db` — tajweed coloring rules
- `tafseer_local.db` — 5 Arabic tafsirs, built by `pipeline/build_tafseer_local.py` from QUL (qul.tarteel.ai) exports
- `word_timestamps/`, `research_cache/` — additional per-feature datasets
- `reciters/<reciter>/*.json.gz` — per-reciter word/verse/letter timing (restored at build time, not tracked)

New classical books follow the deterministic, no-LLM ingestion and review
process documented in [`pipeline/CLASSICAL_BOOK_ONBOARDING.md`](pipeline/CLASSICAL_BOOK_ONBOARDING.md).
With `ENABLE_EDITOR=1`, `/classical-review` opens the local scholarly reviewer
for المكتفى and منار الهدى; decisions are stored separately in
`data/classical_review.db`.

## License

No LICENSE file is currently included in this repository — all rights are
reserved by default until one is added.

## Contributing

Contributions are welcome! Please fork the repository and create a pull request with your changes.

## Contact

For any inquiries or support, please contact [Ahmed Esawy](https://github.com/AhmedEsawy13).
