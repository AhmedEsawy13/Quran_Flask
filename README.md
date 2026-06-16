# Quran Flask — مصحف تفاعلي

Quran_Flask is a modular web application for reading, reciting, memorizing, and
studying the Holy Quran. It is built with Flask and organized into four
independent feature **modules** (Flask blueprints) over a shared `core`, so each
module can be enabled per deployment and served on its own domain.

## Modules · الوحدات

| Module | الاسم العربي | Blueprint | What it does |
|---|---|---|---|
| **Reading** | **المصحف** — القراءة والتلاوة | `reading` | Main mushaf page: word-by-word audio, tafseer, tajweed, i'rāb, themes, bookmarks |
| **Memorization** | **رُسوخ** — التكرار المُقطّع للحفظ | `memorize` | Circular Segmented Repetition player for memorizing a surah |
| **Pause Guide** | **دليل التنفّس** — مواضع الوقف | `breathing` | Reciter-validated waqf (stop) positions across multiple Qāris |
| **Mushaf Editor** | **محرّر المصحف** — ضبط الوقف | `editor` | Click-to-edit waqf tool (Qatar/Kuwait layouts). Admin-only, runs locally — the **only writer** |

All four sit on a shared **`core`** module (Quranic text, search, and mushaf
page-rendering) that is always enabled. See [Architecture](#architecture) for how
modules are turned on/off per deployment.

## Features

### 🎨 **Theme & Display**
- **Dark Mode**: Toggle between light and dark themes for comfortable reading
- **Sepia Mode**: Eye-friendly sepia theme for extended reading sessions
- **Multiple Arabic Fonts**: Choose from UthmanicHafs (Hafs & Warsh), Digital Khatt, IndoPak Nastaleeq, and Mushaf (Shemrly page) fonts
- **Responsive Design**: Optimized for both mobile and desktop users
- **Theme Persistence**: Your preferred theme is saved and restored on next visit

### 📖 **Quranic Text Features**
- **Word-by-word Highlighting**: Real-time highlighting of words during audio recitation
- **Word Meanings (غريب الكلمات)**: Display meanings of difficult Arabic words
- **Clickable Words**: Click on any word to hear its individual pronunciation
- **Transliteration**: Show phonetic pronunciation of Arabic text
- **Tafseer Integration**: Access to multiple commentary sources (Al Qurtubi, Al Saddi, Al-Baghawi)

### 🎵 **Advanced Audio Features**
- **Multiple Reciters**: Choose from 10 recitation styles by Abdul Basit Abdus Samad (Mujawwad/Murattal), Mohamed al-Minshawi (Mujawwad/Murattal), Mahmoud Khalil al-Husary (Mujawwad/Muallim), Ibrahim Al-Akhdar, Ayman Rushdi Suwaid, Mahmoud Ali Al-Banna, and Mustafa Ismaeel
- **Audio Synchronization**: Precise word-by-word audio timing
- **Range Selection**: Play multiple consecutive verses
- **Loop Functionality**: Repeat verses for memorization
- **Audio Controls**: Play, pause, next/previous verse navigation
- **Audio Preloading**: Next ayah audio is preloaded for seamless navigation

### 🔖 **Bookmark System**
- **Save Bookmarks**: Bookmark your favorite verses for quick access
- **Manage Bookmarks**: View and delete bookmarks from a modal dialog
- **Quick Navigation**: Click any bookmark to jump directly to that verse

### 🎤 **Interactive Features**
- **Voice Commands**: Control the app using speech recognition (English)
- **Navigation Controls**: Easy verse-by-verse navigation with keyboard shortcuts (Arrow keys)
- **Modal Dialogs**: User-friendly range selection interface
- **Toast Notifications**: Modern notification system for user feedback

### 💾 **User Preferences**
- **Auto-save Position**: Your last viewed verse is remembered
- **Preference Persistence**: Theme, font, and reciter choices are saved locally
- **No Login Required**: All preferences stored in browser localStorage

### 🔧 **Technical Features**
- **RESTful API**: Well-structured API endpoints for data access
- **Caching System**: Optimized performance with intelligent caching
- **Security Headers**: Enhanced security with proper HTTP headers and CSP
- **Error Handling**: Robust error handling and logging
- **SQLite Database**: Local database for word meanings and metadata
- **Local Surah Data**: All 114 surah names stored locally (no external API dependency)

## Performance Optimizations

The application is optimized for deployment on Vercel with:
- **Lazy Loading**: Tafseer files (35MB) loaded on-demand for faster cold starts
- **Response Compression**: GZIP compression reduces API response sizes by ~70%
- **Caching**: Server-side caching with `@lru_cache` and Cache-Control headers
- **Efficient Data Loading**: Only essential data loaded at startup
- **CDN Caching**: Static files cached for 1 year, API responses for 1 hour
- **Audio Preloading**: Next verse audio preloaded for low-latency playback

## Architecture

The app is a single codebase split into a shared core and four feature
blueprints, assembled by an application factory in [`app.py`](app.py):

```
core/
├── config.py    # DB paths, reciter config, layout constants, waqf/search regexes
├── db.py        # shared per-request word_name.db connection (get_db / teardown)
└── __init__.py
app.py           # feature blueprints (core / reading / memorize / breathing / editor)
                 # + create_app() factory + env-driven registration
```

### Selecting modules per deployment

Every process runs the same entrypoint (`gunicorn app:app`); which modules it
serves is controlled by environment variables:

| Env var | Effect |
|---|---|
| `FEATURES` | Comma-separated module list to enable, e.g. `FEATURES=reading` or `FEATURES=memorize,breathing`. Defaults to `reading,memorize,breathing`. `core` is **always** included. |
| `ENABLE_EDITOR` | When set, mounts the write-capable `editor` module. **Off by default** — keep it to localhost so production stays read-only. |

This lets you put each module on its own domain while sharing one repo and one
set of databases:

| Domain / app | Env | Serves |
|---|---|---|
| `mushaf.example.com` | `FEATURES=reading` | المصحف + core |
| `repeat.example.com` | `FEATURES=memorize` | رُسوخ + core |
| `waqf.example.com` | `FEATURES=breathing` | دليل التنفّس + core |
| your laptop | `ENABLE_EDITOR=1` | everything, incl. محرّر المصحف |

> **Note on the editor:** it is the only module that *writes* (to
> `data/mushaf_waqf.db` / `data/mushaf-qatar-layout.db`). Because production
> filesystems are ephemeral, the editor is intended to run **locally** — you
> edit, commit the updated `.db`, and redeploy so the read-only modules serve
> the new data.

## Installation

To run this project locally, follow these steps:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AhmedEsawy13/Quran_Flask.git
   ```

2. **Navigate to the project directory:**
   ```bash
   cd Quran_Flask
   ```

3. **Install the required dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Flask application:**
   ```bash
   python app.py            # serves on http://localhost:5001
   ```
   To work on the editor module locally, enable it explicitly:
   ```bash
   ENABLE_EDITOR=1 python app.py
   ```
   To serve only a subset of modules (as in production), set `FEATURES`:
   ```bash
   FEATURES=reading python app.py
   ```

5. **Access the application:**
   Open your browser and go to `http://localhost:5001`

### Requirements
- Python 3.7+
- Flask 3.0.3
- SQLite3 (included with Python)
- Modern web browser with HTML5 support
- Internet connection for external CDN resources

## API Endpoints

The application provides RESTful API endpoints for accessing Quranic data:

### Surahs
- `GET /api/surahs` - Get all surahs (chapters)
- `GET /api/surahs/<surah_number>/ayahs` - Get all ayahs in a surah
- `GET /api/surahs/<surah_number>/ayahs/<ayah_number>` - Get specific ayah with metadata

### Audio & Text
- `GET /api/reciters/<reciter>/ayahs/<ayah_number>/audio` - Get audio data for specific ayah
- `GET /api/quran-text?source=<font_source>` - Get Quranic text in specified font
- `GET /api/audio-proxy?url=<audio_url>` - Proxy for audio streaming

### Search & Discovery
- `GET /api/search?q=<query>&limit=<limit>&source=<source>` - Search verses by text
- `GET /api/word-search?q=<query>&limit=<limit>` - Search word meanings

### Tafseer (Commentary)
- `GET /api/tafseer` - List available tafseers
- `GET /api/tafseer/<tafseer_name>` - Get specific tafseer data

### Monitoring
- `GET /api/health` - Health check endpoint for monitoring service status

### Data Sources
The application uses multiple data sources (all under `data/`, except per-reciter timing under `reciters/`):
- **data/quran_text/** - Quranic text in multiple fonts (Digital Khatt, QPC Hafs, IndoPak Nastaleeq, Transliteration, etc.)
- **data/word_name.db** - SQLite database for word meanings
- **data/quran_script.db** - Quranic script database
- **data/mushaf_waqf.db** - Waqf (stop mark) data for Mushaf layout (written by the editor module)
- **data/qpc-v4-15-lines.db** / **data/qpc-v1-15-lines.db** - Page-layout databases
- **data/glyph_mappings.db** / **data/mushaf_layout_inferred.db** - Shemrly page rendering
- **reciters/<reciter>/positions.db** - Per-reciter word-level audio timing data
- External APIs for audio recitations and translations

## Technology Stack

### Backend
- **Flask 3.0.3** - Python web framework
- **SQLite3** - Local database for word meanings
- **JSON Data Files** - Quranic text storage in multiple fonts

### Frontend  
- **Vanilla JavaScript** - No framework dependencies for better performance
- **HTML5 & CSS3** - Modern web standards
- **Font Awesome 6** - Icons and UI elements
- **Tippy.js** - Tooltips and popovers
- **Web Speech API** - Voice command functionality

### Features & APIs
- **Speech Recognition API** - Voice commands
- **Audio API** - Advanced audio controls and synchronization
- **Fetch API** - Modern HTTP requests
- **LocalStorage** - Client-side caching and preferences

## Usage

### Basic Navigation
1. **Select Reciter**: Choose from available reciters using the dropdown
2. **Choose Surah**: Select a chapter from the Surah dropdown
3. **Pick Ayah**: Select a specific verse from the Ayah dropdown
4. **Play Audio**: Use the play/pause button or audio controls

### Advanced Features
- **Theme Toggle**: Use the moon (🌙) icon for dark mode or leaf (🍃) icon for sepia mode
- **Font Selection**: Change Arabic font from the font dropdown
- **Word Meanings**: Click "عرض غريب الكلمات" to show/hide word meanings
- **Voice Commands**: Click "امر صوتي" and speak commands in English
- **Range Selection**: Click "تحديد نطاق" to play multiple consecutive verses
- **Loop Mode**: Enable "تكرار الاية" to repeat the current verse
- **Bookmarks**: Click "علامة مرجعية" to save a verse, or "المرجعيات" to view saved bookmarks

### Keyboard Shortcuts
- **←** (Left Arrow) - Go to previous verse
- **→** (Right Arrow) - Go to next verse

### Voice Commands (English)
- "chapter [number] verse [number]" - Jump to specific verse
- "chapter [number]" - Jump to specific surah
- "verse [number]" - Jump to specific verse in current surah

## Deployment

The app deploys on **Heroku** via the [`Procfile`](Procfile)
(`gunicorn app:app`). Because each module is selected by environment variables,
the same repo can be deployed to several Heroku apps — one per domain/module —
each scaled independently:

```bash
# one app per module, same repo, shared databases in the slug
heroku config:set FEATURES=reading   -a quran-reading
heroku config:set FEATURES=memorize  -a quran-memorize
git push https://git.heroku.com/quran-reading.git main
```

### Deployment Configuration
- **Platform**: Heroku
- **Runtime**: Python 3.x (`runtime.txt`)
- **Entrypoint**: `gunicorn app:app` (`Procfile`)
- **Module selection**: `FEATURES` / `ENABLE_EDITOR` env vars (see [Architecture](#architecture))

> **Read-only at runtime:** the read modules (`reading`, `memorize`,
> `breathing`, `core`) only read databases shipped in the slug, so they scale
> horizontally across dynos cleanly. The writing `editor` module is excluded
> from production (`ENABLE_EDITOR` unset) and run locally instead.

## Project Structure

```
Quran_Flask/
├── app.py                          # Feature blueprints + create_app() factory
├── core/                           # Shared module (always enabled)
│   ├── config.py                   # DB paths, reciter config, layout constants, regexes
│   └── db.py                       # Shared per-request DB connection helpers
├── Procfile                        # Heroku entrypoint (gunicorn app:app)
├── requirements.txt                # Python dependencies
├── runtime.txt                     # Python runtime version
├── vercel.json                     # (legacy) serverless deployment config
├── README.md                       # Project documentation
├── data/                           # Quranic data files
│   ├── quran_text/                 # Quranic text in multiple fonts (JSON)
│   ├── quran_script.db             # Quranic script database
│   ├── word_name.db                # Word meanings database
│   ├── waqf_symbols.db             # Waqf symbol data
│   ├── mushaf_waqf.db              # Waqf (stop mark) data  ·  written by editor
│   ├── mushaf-qatar-layout.db      # Qatar 15-line layout    ·  written by editor
│   ├── qpc-v4-15-lines.db          # QPC v4 ("New Madinah") page layout
│   ├── qpc-v1-15-lines.db          # QPC v1 page layout
│   ├── glyph_mappings.db           # Shemrly glyph mappings
│   ├── mushaf_layout_inferred.db   # Inferred Shemrly page layout
│   └── tajweed_local.db            # Local tajweed coloring data
├── reciters/                       # Per-reciter word-timing/position databases
│   ├── husary/
│   ├── abdul-basit-abdus-samad/
│   ├── ayman-suwaid/
│   ├── ibrahim-al-akhdar/
│   ├── mahmoud-ali-al-banna/
│   ├── mohammed-siddiq-al-minshawi/
│   └── mustafa-ismaeel/            # …and additional reciter sources
├── scripts/                        # Utility and maintenance scripts
├── pipeline/                       # Data pipeline scripts
├── static/                         # Static assets (JS, CSS, fonts)
└── templates/                      # HTML templates (one per page module)
    ├── index.html                  # Reading      (المصحف)
    ├── mushaf_memorize.html        # Memorization (رُسوخ)
    ├── waqf_guide.html             # Pause Guide  (دليل التنفّس)
    └── mushaf_editor.html          # Mushaf Editor (محرّر المصحف)
```

## License

This project is licensed under the terms of the [LICENSE].

## Contributing

Contributions are welcome! Please fork the repository and create a pull request with your changes.

## Contact

For any inquiries or support, please contact [Ahmed Esawy](https://github.com/AhmedEsawy13).
