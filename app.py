from flask import Flask, jsonify, render_template, request, g, Response, redirect
import json
import sqlite3
import os
import logging
import re
import threading
from collections import defaultdict, OrderedDict
from functools import lru_cache


class _BoundedLRU(OrderedDict):
    """Thread-safe bounded LRU.

    Python dict ops are atomic under the GIL for single-key access, but the
    move_to_end + popitem dance below is not — so we guard with a lock to
    keep multiple Flask worker threads from corrupting the order map. All
    locked methods call OrderedDict super().* directly to avoid re-entering
    the lock from one method into another.
    """
    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def get(self, key, default=None):  # type: ignore[override]
        with self._lock:
            if OrderedDict.__contains__(self, key):
                self.move_to_end(key)
                return OrderedDict.__getitem__(self, key)
            return default

    def __contains__(self, key):  # type: ignore[override]
        with self._lock:
            return OrderedDict.__contains__(self, key)

    def __getitem__(self, key):  # type: ignore[override]
        with self._lock:
            value = OrderedDict.__getitem__(self, key)
            self.move_to_end(key)
            return value

    def __setitem__(self, key, value):  # type: ignore[override]
        with self._lock:
            if OrderedDict.__contains__(self, key):
                self.move_to_end(key)
            OrderedDict.__setitem__(self, key, value)
            while len(self) > self._maxsize:
                self.popitem(last=False)
from flask import make_response
import gzip
from io import BytesIO
import requests as http_requests

# orjson is ~5-8x faster than stdlib json for large files (Rust-based).
# Fall back gracefully to stdlib if not installed.
try:
    import orjson as _orjson
    def _json_load(fh):
        """Read file handle and parse with orjson (accepts bytes or str)."""
        return _orjson.loads(fh.read())
except ImportError:
    _orjson = None  # type: ignore
    def _json_load(fh):  # type: ignore
        return json.load(fh)
import concurrent.futures

app = Flask(__name__, static_folder='static')

# (Flask-Compress is not installed/initialised here — the previous
# COMPRESS_* config keys had no effect and were removed. JSON gzip is
# handled inline in after_request below.)

# Configure logging
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# Compression and security improvements
@app.after_request
def after_request(response):
    """Add security headers and compression to all responses"""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdnjs.cloudflare.com https://vercel.live https://va.vercel-scripts.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com; "
        "connect-src 'self' https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com;"
    )
    
    # Cache control for API responses.
    if request.path.startswith('/api/'):
        # Waqf overlays can be adjusted at runtime and are sensitive to
        # matching logic updates. Avoid stale browser cache for these requests.
        if request.args.get('mushaf_version'):
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        else:
            response.headers['Cache-Control'] = 'public, max-age=3600'
    
    # GZIP compression for JSON responses - check early to avoid unnecessary processing.
    # Skip if the response is already encoded (e.g. by a downstream middleware) so we
    # don't double-encode (gzip(gzip(...)) — broken clients).
    if (response.status_code == 200 and
        not response.direct_passthrough and
        not response.headers.get('Content-Encoding') and
        response.content_type and 'application/json' in response.content_type and
        'gzip' in request.headers.get('Accept-Encoding', '').lower()):

        response_data = response.get_data()
        # Only compress if response is large enough
        if len(response_data) > 500:
            gzip_buffer = BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=gzip_buffer, compresslevel=6) as gzip_file:
                gzip_file.write(response_data)
            
            compressed = gzip_buffer.getvalue()
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed))
            response.headers['Vary'] = 'Accept-Encoding'
    
    return response

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'QUL_data', 'word_name.db')
WAQF_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'QUL_data', 'waqf_symbols.db')
MUSHAF_WAQF_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'QUL_data', 'mushaf_waqf.db')
# Per-reciter guide config: positions.db path + default waqf column from mushaf_waqf DB.
# Add a new entry here whenever a reciter has segmentation data.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECITER_GUIDE_CONFIG = {
    'Mahmoud Khalil al-Husary (Mujawwad)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'mahmoud_khalil_al_husari_0_2_positions.db'),
        'waqf_col': 'المدينة',
    },
    'Mahmoud Khalil al-Husary (Muallim)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'positions.db'),
        'waqf_col': 'المدينة',
    },
    'Mahmoud Khalil al-Husary (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'mahmoud_khalil_al_husari_0_1_positions.db'),
        'waqf_col': 'المدينة',
    },
    'Ibrahim Al-Akhdar': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'ibrahim-al-akhdar', 'positions.db'),
        'waqf_col': 'المدينة',
    },
    'Ayman Rushdi Suwaid': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'ayman-suwaid', 'positions.db'),
        'waqf_col': 'المدينة',
    },
    'Mahmoud Ali Al-Banna': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mahmoud-ali-al-banna', 'positions.db'),
        'waqf_col': 'المدينة',
    },
    'Mustafa Ismaeel': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mustafa-ismaeel', 'positions.db'),
        'waqf_col': 'المدينة',
    },
    'AbdulBaset AbdulSamad (Mujawwad)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'abdul-basit-abdus-samad', 'mujawwad_positions.db'),
        'waqf_col': 'المدينة',
    },
    'AbdulBaset AbdulSamad (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'abdul-basit-abdus-samad', 'murattal_positions.db'),
        'waqf_col': 'المدينة',
    },
    'Mohamed al-Minshawi (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mohammed-siddiq-al-minshawi', 'positions.db'),
        'waqf_col': 'المدينة',
    },
}
# Keep for backwards compat with any legacy code that may reference it
HUSARY_POSITIONS_DB = RECITER_GUIDE_CONFIG['Mahmoud Khalil al-Husary (Muallim)']['db']
DIGITAL_KHATT_LAYOUT_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'digital-khatt-15-lines.db')

MAX_AYAH_NUMBER = 286  # Al-Baqarah, the longest surah
SHEMRLY_CODEPOINT_BASE = 0xFB50  # Shemrly fonts index glyphs from U+FB51 (base + 1)

# True waqf stop symbols only (ayah/sajda/rubu markers are handled separately).
WAQF_SYMBOL_CHARS = set([
    'ۖ', 'ۗ', 'ۘ', 'ۙ', 'ۚ', 'ۛ', 'ۜ'
])
INDOPAK_EXTRA_WAQF_SYMBOL_CHARS = set([
    '۟', '۠', 'ۡ', 'ۢ', 'ۤ', 'ۥ', 'ۦ', '۪', '۫', '۬', 'ۭ',
    'ؕ', 'ؔ', 'ؗ'
])
# Markers like Sajda, Rubu, and verse-end that are NOT waqf.
# (U+06EC was previously listed here too, but it is also in
# INDOPAK_EXTRA_WAQF_SYMBOL_CHARS — the JS legend treats it as a Hindi waqf, so
# the duplicate caused U+06EC to be silently dropped from waqf extraction.)
NON_WAQF_SPECIFIC_CHARS = set([
    '۩', '۞', '۝'
])
ARABIC_INDIC_DIGIT_PATTERN = re.compile(r'^[٠-٩]+$')
ARABIC_DIACRITICS_STRIP_PATTERN = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED]')

# Broader pattern used for search normalisation: strip diacritics, tatweel,
# ayah-end markers, and Quranic annotation marks so user queries like "الله"
# match the fully-vocalised text "ٱللَّهِ" in the Quranic JSON sources.
_SEARCH_STRIP_PATTERN = re.compile(
    r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640\u06DD\u08F0-\u08FF\ufbb2-\ufbc1\u00A0]'
)
_SEARCH_LETTER_FOLD = {
    'ٱ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ئ': 'ي',
    'ؤ': 'و', 'ة': 'ه', 'ي': 'ي', 'ك': 'ك',
}


def _normalize_for_search(text):
    """Fold vocalisation and common Arabic letter variants so exact-match
    search behaves the way a reader typing on a keyboard expects."""
    if not text:
        return ''
    cleaned = _SEARCH_STRIP_PATTERN.sub('', text)
    # Fold common letter variants (hamza forms, alif maqsura, taa marbuta).
    return ''.join(_SEARCH_LETTER_FOLD.get(ch, ch) for ch in cleaned)

# jsDelivr CDN base for large JSON assets (GitHub repo as origin)
_CDN_BASE = 'https://cdn.jsdelivr.net/gh/AhmedEsawy13/Quran_Flask@main/QUL_data'

# In-process cache for CDN-fetched JSON blobs
_cdn_cache: dict = {}

# True when running on Vercel / AWS Lambda — local data files are always bundled
# so we skip the outbound CDN fetch to eliminate the cold-start latency.
_IS_SERVERLESS = bool(
    os.environ.get('VERCEL') or
    os.environ.get('VERCEL_ENV') or
    os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
)

def _load_json_cdn_or_local(cdn_path: str, local_path: str):
    """Load JSON from local file (preferred) or CDN fallback.

    On serverless deployments (Vercel / Lambda) the data files are always
    bundled alongside the function, so we read locally and skip the CDN
    fetch entirely — it would only add latency on cold start.
    On local dev without the data files we fall back to CDN.
    """
    if cdn_path in _cdn_cache:
        return _cdn_cache[cdn_path]
    # Always prefer local file when present (zero network cost).
    abs_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_path)
    if os.path.exists(abs_local):
        try:
            # Open in binary mode so orjson can read raw bytes (faster);
            # stdlib json.load also accepts binary file handles in Python 3.
            with open(abs_local, 'rb') as f:
                data = _json_load(f)
            _cdn_cache[cdn_path] = data
            return data
        except Exception as e:
            app.logger.warning(f'Local load failed for {local_path}: {e}')
    if _IS_SERVERLESS:
        app.logger.error(f'Local file missing on serverless deployment: {local_path}')
        return {}
    # Local dev fallback: try CDN when local file is absent.
    url = f'{_CDN_BASE}/{cdn_path}'
    try:
        resp = http_requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _cdn_cache[cdn_path] = data
        app.logger.info(f'Loaded {cdn_path} from CDN')
        return data
    except Exception as e:
        app.logger.error(f'CDN fetch also failed for {cdn_path}: {e}')
        return {}


# Load Quranic text data — CDN first, local fallback
# Local files now live under QUL_data/quran_text/
digital_khatt_data = _load_json_cdn_or_local(
    'Digital_Khatt_Aya_Space.json', 'QUL_data/quran_text/Digital_Khatt_Aya_Space.json'
)
qpc_hafs_data = _load_json_cdn_or_local(
    'QPC Hafs.json', 'QUL_data/quran_text/QPC Hafs.json'
)
indopak_nastaleeq_data = _load_json_cdn_or_local(
    'Indopak Nastaleeq_Waqf.json', 'QUL_data/quran_text/Indopak Nastaleeq_Waqf.json'
)
indopak_nastaleeq_2_data = _load_json_cdn_or_local(
    'indopak-nastaleeq 2.json', 'QUL_data/quran_text/indopak-nastaleeq 2.json'
)
transliteration_data = _load_json_cdn_or_local(
    'Transliteration.json', 'QUL_data/quran_text/Transliteration.json'
)
surahs_data = _load_json_cdn_or_local('surahs.json', 'QUL_data/quran_text/surahs.json')
if not isinstance(surahs_data, list):
    surahs_data = []

# Tafseer API configuration (quran.com v4)
# IDs confirmed from https://api.quran.com/api/v4/resources/tafsirs
TAFSEER_API_IDS = {
    'تفسير السعدي':   91,
    'تفسير القرطبي':  90,
    'تفسير البغوي':   94,
    'التفسير الميسر': 16,
}
TAFSEER_API_BASE = 'https://api.quran.com/api/v4/tafsirs/{id}/by_ayah/{verse_key}'

# quranenc.com API — used for tafseers not on quran.com
# identifier → Arabic name mapping
TAFSEER_QURANENC_IDS = {
    'المختصر في التفسير': 'arabic_mokhtasar',
}
TAFSEER_QURANENC_BASE = 'https://quranenc.com/api/v1/translation/aya/{identifier}/{surah}/{ayah}'

# In-process cache: (tafseer_name, verse_key) → {text: "..."}
# Bounded so long-running processes don't accumulate every tafseer ever fetched.
_tafseer_cache: _BoundedLRU = _BoundedLRU(maxsize=4096)

# SurahApp API (grammatical analysis / إعراب)
SURAHAPP_API_BASE = 'https://dev.surahapp.com/api/v1/aya/{slug}/{sura}/{aya}'
# In-process cache (bounded — eerab payloads are small but plentiful).
_eerab_cache: _BoundedLRU = _BoundedLRU(maxsize=2048)


# Load audio data — CDN first, local fallback
# Local files now live under QUL_data/word_timestamps/
reciters = {
    "AbdulBaset AbdulSamad (Mujawwad)": ("AbdulBaset AbdulSamad Recitation.json",
                                         "QUL_data/word_timestamps/AbdulBaset AbdulSamad Recitation.json"),
    "AbdulBaset AbdulSamad (Murattal)": ("ayah-recitation-abdul-basit-abdul-samad-murattal-hafs-950.json",
                                         "QUL_data/word_timestamps/ayah-recitation-abdul-basit-abdul-samad-murattal-hafs-950.json"),
    "Mohamed al-Minshawi (Mujawwad)": ("Mohamed Siddiq al-Minshawi Recitation.json",
                              "QUL_data/word_timestamps/Mohamed Siddiq al-Minshawi Recitation.json"),
    "Mohamed al-Minshawi (Murattal)": ("ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json",
                              "QUL_data/word_timestamps/ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json"),
    "Mahmoud Khalil al-Husary (Mujawwad)": ("ayah-recitation-mahmoud-khalil-al-husary-mujawwad-hafs-956.json",
                                           "QUL_data/word_timestamps/ayah-recitation-mahmoud-khalil-al-husary-mujawwad-hafs-956.json"),
    "Mahmoud Khalil al-Husary (Murattal)": ("ayah-recitation-mahmoud-khalil-al-husary-murattal-hafs-957.json",
                                            "QUL_data/word_timestamps/ayah-recitation-mahmoud-khalil-al-husary-murattal-hafs-957.json"),
    "Mahmoud Khalil al-Husary (Muallim)": ("mahmoud-khalil-al-husary-muallm-hafs.json",
                                           "QUL_data/word_timestamps/mahmoud-khalil-al-husary-muallm-hafs.json"),
    "Ibrahim Al-Akhdar":        ("ibrahim-al-akhdar.json",
                                  "QUL_data/word_timestamps/ibrahim-al-akhdar.json"),
    "Ayman Rushdi Suwaid":       ("ayman-rushdi-suwaid.json",
                                  "QUL_data/word_timestamps/ayman-rushdi-suwaid.json"),
    "Mahmoud Ali Al-Banna":      ("mahmoud-ali-al-banna.json",
                                  "QUL_data/word_timestamps/mahmoud-ali-al-banna.json"),
    "Mustafa Ismaeel":           ("mustafa-ismaeel.json",
                                  "QUL_data/word_timestamps/mustafa-ismaeel.json"),
}

# Reciter audio data and mappings are loaded lazily on first use.
# This defers ~150 ms of JSON parsing out of the cold-start path.
audio_data: dict = {}
_reciters_initialized = False
_reciters_lock = threading.Lock()


def _ensure_reciters_initialized():
    """Idempotent: load reciter JSON files and build mappings on first call."""
    global _reciters_initialized
    if _reciters_initialized:
        return
    with _reciters_lock:
        if _reciters_initialized:  # double-checked locking
            return
        for reciter, (cdn_name, local_path) in reciters.items():
            data = _load_json_cdn_or_local(cdn_name, local_path)
            audio_data[reciter] = data if data else []
        for reciter, data in audio_data.items():
            try:
                reciter_mappings[reciter] = create_audio_mapping(digital_khatt_data, data)
                reciter_audio_by_global_id[reciter] = {
                    info['id']: info
                    for info in reciter_mappings[reciter].values()
                    if 'id' in info
                }
            except Exception as e:
                app.logger.error(f'Error creating mapping for reciter {reciter}: {e}')
                reciter_mappings[reciter] = {}
                reciter_audio_by_global_id[reciter] = {}
        _reciters_initialized = True


def _parse_segment(seg):
    """Normalise a raw segment to {start_word_index, end_word_index, start_time, end_time}.

    Accepts two layouts:
      4-element [start_word_0based, end_word_0based, start_ms, end_ms]  (qurancdn format)
      3-element [word_1based, start_ms, end_ms]                         (tarteel format)
    Returns None for anything else.
    """
    if not isinstance(seg, (list, tuple)):
        return None
    if len(seg) == 4:
        return {
            'start_word_index': seg[0],
            'end_word_index':   seg[1],
            'start_time':       seg[2],
            'end_time':         seg[3],
        }
    if len(seg) == 3:
        w = max(0, int(seg[0]) - 1)   # convert 1-based → 0-based
        return {
            'start_word_index': w,
            'end_word_index':   w,
            'start_time':       seg[1],
            'end_time':         seg[2],
        }
    return None


# Matches diacritics/harakat and quranic marks (NOT the superscript alef ٰ U+0670,
# which we keep for يا-vocative detection via _YA_NIDA_RE below).
_HARAKAT_RE = re.compile(r'[\u064B-\u065F\u0654\u0655\u06D6-\u06DC\u06DF-\u06E4]')

# Detects a يا-vocative compound word in the Uthmanic text: starts with ي + optional
# harakat + superscript alef (ٰ U+0670).  Examples: يَٰٓأَيُّهَا, يَٰٓادَمُ,
# يَٰبَنِيٓ, يَٰقَوۡمِ, يَٰنِسَآءُ — all forms where يا is written with a superscript
# alef rather than a full ا.
_YA_NIDA_RE = re.compile(r'^\u064A[\u064B-\u065F]*\u0670')


def _fix_ya_nida_segments(segments, verse_text):
    """Fix word-index alignment when the timing source split يَا-vocative
    compounds into two consecutive tokens (يَا + following word) while the
    Uthmanic/DK text stores each compound as a single merged token.

    Handles all يا-vocative forms wherever they appear in the verse — at the
    start or mid-verse — including:
        يَٰٓأَيُّهَا  (يا + أيها)
        يَٰٓادَمُ     (يا + آدم)
        يَٰبَنِيٓ     (يا + بني)
        يَٰقَوۡمِ     (يا + قوم)
        يَٰنِسَآءُ   (يا + نساء)
        … and any other word beginning with ي + superscript-alef (ٰ).

    Algorithm:
      1. Count DK content words (all tokens except the trailing ayah-number).
      2. If len(segments) <= content_word_count there is nothing to fix.
      3. Identify every يا-vocative word position in the DK word list.
      4. Walk DK positions in order; at each يا position consume TWO timing
         segments (merge them into one) instead of one, until the surplus is
         fully absorbed.  All segment word indices are re-assigned from the
         DK position counter so downstream code always sees a 0-based,
         gap-free index matching the displayed word list.
    """
    if not segments or not verse_text:
        return segments

    verse_words = verse_text.split()
    # DK text ends with the ayah-number glyph as the last space-separated token;
    # the timing data never covers that glyph, so content words = total – 1.
    content_word_count = len(verse_words) - 1
    extra = len(segments) - content_word_count
    if extra <= 0:
        return segments  # no surplus — nothing to fix

    # Find 0-based indices of all يا-vocative words in the DK content word list.
    ya_positions = {
        i for i, word in enumerate(verse_words[:-1])
        if _YA_NIDA_RE.match(word)
    }
    if not ya_positions:
        return segments  # no يا-vocative tokens found — can't identify splits

    # Walk DK word positions and timing segments together.
    # At each يا position we consume two timing slots and merge them into one
    # (absorbing one unit of surplus).  Stop merging once the surplus is gone.
    new_segments = []
    seg_idx = 0
    merges_left = min(extra, len(ya_positions))

    for dk_idx in range(content_word_count):
        if seg_idx >= len(segments):
            break

        if dk_idx in ya_positions and merges_left > 0 and seg_idx + 1 < len(segments):
            s0, s1 = segments[seg_idx], segments[seg_idx + 1]
            new_segments.append({
                'start_word_index': dk_idx,
                'end_word_index':   dk_idx,
                'start_time':       s0['start_time'],
                'end_time':         max(s0['end_time'], s1['end_time']),
            })
            seg_idx += 2
            merges_left -= 1
        else:
            new_segments.append({
                **segments[seg_idx],
                'start_word_index': dk_idx,
                'end_word_index':   dk_idx,
            })
            seg_idx += 1

    return new_segments


def create_audio_mapping(quran_text_data, audio_data):
    """Build a verse_key → audio segment map from either list-based or dict-based audio source."""
    if not quran_text_data or not audio_data:
        app.logger.warning("Empty quran_text_data or audio_data provided")
        return {}

    id_to_verse_key = {
        data['id']: verse_key
        for verse_key, data in quran_text_data.items()
        if isinstance(data, dict) and 'id' in data
    }

    # If the dict keys already look like verse keys ('1:1', '2:168' …) use them
    # directly instead of going through the global-id lookup, which breaks when
    # ayah_number stores a within-surah ordinal rather than a global id.
    use_dict_keys = (
        isinstance(audio_data, dict) and
        bool(audio_data) and
        bool(re.match(r'^\d+:\d+$', str(next(iter(audio_data)))))
    )

    if use_dict_keys:
        pairs = audio_data.items()
    elif isinstance(audio_data, list):
        pairs = ((None, item) for item in audio_data)
    else:
        pairs = ((None, item) for item in audio_data.values())

    verse_key_to_segment_map = {}

    for item_key, audio_info in pairs:
        if not isinstance(audio_info, dict):
            app.logger.warning(f"Unexpected non-dict entry in audio data: {audio_info}")
            continue

        audio_url = audio_info.get('audio_url')
        if not audio_url:
            app.logger.warning(f"Missing audio_url in audio info: {audio_info}")
            continue

        # Resolve verse key
        if item_key is not None:
            verse_key = item_key
        else:
            ayah_number = audio_info.get('ayah_number')
            verse_key = id_to_verse_key.get(ayah_number)
            if not verse_key:
                app.logger.warning(f"Ayah number {ayah_number} not found in Quranic text data")
                continue

        raw_segments = audio_info.get('segments') or []
        segments = [s for seg in raw_segments if (s := _parse_segment(seg)) is not None]

        # For per-word Tarteel segments (3-element format), fill timing gaps between
        # consecutive words so highlighting stays continuous instead of going dark
        # during natural pauses between words.
        if len(segments) > 1 and all(s['start_word_index'] == s['end_word_index'] for s in segments):
            segs_sorted = sorted(segments, key=lambda s: s['start_time'])
            for i in range(len(segs_sorted) - 1):
                next_start = segs_sorted[i + 1]['start_time']
                if segs_sorted[i]['end_time'] < next_start - 10:
                    segs_sorted[i] = {**segs_sorted[i], 'end_time': next_start - 10}
            segments = segs_sorted

        verse_info = quran_text_data.get(verse_key, {})
        verse_text = verse_info.get('text', '') if isinstance(verse_info, dict) else ''
        segments = _fix_ya_nida_segments(segments, verse_text)
        verse_key_to_segment_map[verse_key] = {
            'id':           verse_info.get('id', audio_info.get('ayah_number')),
            'surah_number': int(verse_key.split(':')[0]),
            'ayah_number':  int(verse_key.split(':')[1]),
            'audio_url':    audio_url,
            'segments':     segments,
        }

    return verse_key_to_segment_map

# These dicts are populated lazily by _ensure_reciters_initialized().
reciter_mappings: dict = {}
reciter_audio_by_global_id: dict = {}


def is_waqf_like_char(char, source_name):
    if char in NON_WAQF_SPECIFIC_CHARS:
        return False
        
    if char in WAQF_SYMBOL_CHARS:
        return True

    if source_name == 'indopak_nastaleeq':
        # IndoPak source stores extra waqf/marker glyphs in this range.
        if char in INDOPAK_EXTRA_WAQF_SYMBOL_CHARS:
            return True
        # Specific patterns for IndoPak waqf symbols that might be composite or standalone
        # 0xE000-0xF8FF: Private Use Area often used for ligatures and markers in IndoPak fonts
        if 0xE000 <= ord(char) <= 0xF8FF:
            return True
        # Check for standard small markers often used in IndoPak
        if char in ['ؐ', 'ؑ', 'ؒ', 'ؓ', 'ؔ', 'ؕ', 'ؖ', 'ؗ', 'ؘ', 'ؙ', 'ؚ', 'ٛ', 'ٜ', 'ٝ', '٘', 'ٙ']:
            return True

    return False


def build_aligned_text(raw_text, source_name):
    """
    Keep original tokens except standalone waqf marker tokens in the middle of a verse.
    For IndoPak, this preserves end marker tokens while removing noisy in-verse marker-only tokens.
    """
    tokens = [token for token in (raw_text or '').split(' ') if token]
    if source_name != 'indopak_nastaleeq':
        return ' '.join(tokens)

    aligned_tokens = []
    last_index = len(tokens) - 1

    for idx, token in enumerate(tokens):
        stripped = ''.join(
            char for char in token if not is_waqf_like_char(char, source_name)
        ).strip()

        if stripped:
            aligned_tokens.append(token)
        elif idx == last_index:
            # Keep ayah-end marker token because segment indices often include it.
            aligned_tokens.append(token)

    return ' '.join(aligned_tokens)


def normalize_text_and_extract_waqf(raw_text, source_name):
    """
    Split verse text into alignment-safe tokens and extract waqf symbols.
    Returns cleaned words and per-token waqf symbol metadata.
    """
    tokens = [token for token in (raw_text or '').split(' ') if token]
    cleaned_words = []
    waqf_entries = []

    changed = False

    for original_index, token in enumerate(tokens):
        cleaned_chars = []
        symbols = []

        for char in token:
            if is_waqf_like_char(char, source_name):
                symbols.append(char)
            else:
                cleaned_chars.append(char)

        cleaned_token = ''.join(cleaned_chars).strip()
        digits_only = bool(cleaned_token) and ARABIC_INDIC_DIGIT_PATTERN.match(cleaned_token)
        current_word_index = None

        if cleaned_token and not digits_only:
            current_word_index = len(cleaned_words) + 1
        elif cleaned_words:
            current_word_index = len(cleaned_words)

        if symbols:
            changed = True
            waqf_entries.append({
                'token_index': original_index,
                'word_index': current_word_index,
                'symbols': ''.join(symbols),
                'original_token': token,
                'clean_token': cleaned_token
            })

        # Ayah-number tokens (e.g., ۝٤) should never be included in word alignment.
        if digits_only:
            changed = True
            continue

        if cleaned_token:
            if cleaned_token != token:
                changed = True
            cleaned_words.append(cleaned_token)

    return cleaned_words, waqf_entries, changed


def normalize_quran_dataset(source_name, source_data):
    """Extract waqf records and attach cleaned text without mutating original verse text."""
    if not isinstance(source_data, dict):
        return source_data, [], {'source': source_name, 'normalized': 0, 'mismatches': 0}

    normalized = {}
    waqf_rows = []
    normalized_count = 0
    for verse_key, verse_data in source_data.items():
        if not isinstance(verse_data, dict):
            normalized[verse_key] = verse_data
            continue

        verse_copy = dict(verse_data)
        original_text = verse_copy.get('text', '')
        cleaned_words, waqf_entries, changed = normalize_text_and_extract_waqf(original_text, source_name)
        aligned_text = build_aligned_text(original_text, source_name)

        if changed:
            normalized_text = ' '.join(cleaned_words)
            normalized_count += 1
            verse_copy['clean_text'] = normalized_text

        if source_name == 'indopak_nastaleeq' and aligned_text != original_text:
            verse_copy['raw_text'] = original_text
            verse_copy['text'] = aligned_text

        normalized[verse_key] = verse_copy

        if waqf_entries:
            try:
                surah_number, ayah_number = verse_key.split(':')
                surah_number = int(surah_number)
                ayah_number = int(ayah_number)
            except (ValueError, TypeError):
                continue

            for entry in waqf_entries:
                waqf_rows.append({
                    'source': source_name,
                    'verse_key': verse_key,
                    'surah_number': surah_number,
                    'ayah_number': ayah_number,
                    'token_index': entry['token_index'],
                    'word_index': entry.get('word_index'),
                    'symbols': entry['symbols'],
                    'original_token': entry['original_token'],
                    'clean_token': entry['clean_token']
                })

    stats = {
        'source': source_name,
        'normalized': normalized_count
    }
    return normalized, waqf_rows, stats


def initialize_waqf_database(waqf_rows):
    """Persist extracted waqf symbols in a dedicated SQLite database.

    Skips the full rebuild when the existing row count already matches, so
    repeated cold starts on serverless don't pay the write cost every time.
    """
    try:
        conn = sqlite3.connect(WAQF_DATABASE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waqf_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                verse_key TEXT NOT NULL,
                surah_number INTEGER NOT NULL,
                ayah_number INTEGER NOT NULL,
                token_index INTEGER NOT NULL,
                word_index INTEGER,
                symbols TEXT NOT NULL,
                original_token TEXT,
                clean_token TEXT
            )
        ''')
        existing_columns = {row[1] for row in cursor.execute('PRAGMA table_info(waqf_symbols)').fetchall()}
        if 'word_index' not in existing_columns:
            cursor.execute('ALTER TABLE waqf_symbols ADD COLUMN word_index INTEGER')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waqf_lookup ON waqf_symbols(source, surah_number, ayah_number)')
        conn.commit()

        # Skip expensive rebuild if data is already current.
        cursor.execute('SELECT COUNT(*) FROM waqf_symbols')
        if cursor.fetchone()[0] == len(waqf_rows):
            conn.close()
            return

        # Rebuild inside a single transaction for crash safety.
        cursor.execute('BEGIN')
        cursor.execute('DELETE FROM waqf_symbols')
        if waqf_rows:
            cursor.executemany(
                '''
                INSERT INTO waqf_symbols (
                    source, verse_key, surah_number, ayah_number, token_index,
                    word_index, symbols, original_token, clean_token
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [(
                    row['source'], row['verse_key'], row['surah_number'], row['ayah_number'],
                    row['token_index'], row.get('word_index'), row['symbols'], row['original_token'], row['clean_token']
                ) for row in waqf_rows]
            )
        cursor.execute('COMMIT')
        conn.close()
    except sqlite3.Error as e:
        app.logger.error(f"Failed to initialize waqf database: {e}")


@lru_cache(maxsize=1)
def _get_mushaf_table_columns():
    """Discover waqf table columns once for safe dynamic SQL decisions."""
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        return tuple()
    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(waqf)")
        cols = cursor.fetchall()
        conn.close()
        return tuple(col[1] for col in cols)
    except Exception as e:
        app.logger.error(f"Error loading mushaf table columns: {e}")
        return tuple()


@lru_cache(maxsize=1)
def _get_mushaf_version_whitelist():
    """Discover allowed Mushaf version column names once.

    Returned set is used to reject any user-supplied column name, preventing
    SQL identifier injection when column names are interpolated into queries
    (SQLite does not allow parameterising column identifiers).
    """
    cols = _get_mushaf_table_columns()
    if not cols:
        return frozenset()
    # Columns 0-3: Sura, SuraName, Ayah, Word. Versions start at column 4.
    helper_columns = {
        'token_index', 'word_index', 'word_position', 'word_key', 'word_no',
        'رقم_الكلمة', 'ترتيب_الكلمة',
    }
    return frozenset(col for col in cols[4:] if col not in helper_columns)


@lru_cache(maxsize=1)
def _get_mushaf_position_column():
    """Optional disambiguation column for absolute word position/token key.

    If DB is later enriched with any of these columns, matching can be exact
    even when words repeat in the same ayah.
    """
    cols = set(_get_mushaf_table_columns())
    for candidate in (
        'word_index', 'token_index', 'word_position', 'word_key', 'word_no',
        'رقم_الكلمة', 'ترتيب_الكلمة'
    ):
        if candidate in cols:
            return candidate
    return None


def _is_valid_mushaf_version(mushaf_version):
    return bool(mushaf_version) and mushaf_version in _get_mushaf_version_whitelist()


@app.route('/api/mushaf-versions', methods=['GET'])
def get_mushaf_versions():
    """Returns available Mushaf versions from the waqf database."""
    return jsonify(sorted(_get_mushaf_version_whitelist()))


@lru_cache(maxsize=2048)
def _get_positions_segments(surah_number, ayah_number, reciter=None):
    """Return (segments, has_db) for a single ayah from the reciter's positions.db.

    Each segment: {start_word, end_word, text, is_repeat}
    has_db=False means no positions.db exists for this reciter (guide unavailable).
    has_db=True with empty segments means the ayah has no segmentation data.
    """
    cfg = RECITER_GUIDE_CONFIG.get(reciter or '', {})
    db_path = cfg.get('db')
    # No fallback to another reciter's DB — missing config means guide is unavailable.
    if not db_path or not os.path.exists(db_path):
        return [], False
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT start_word, end_word, uthmani_text
            FROM positions
            WHERE start_sura = ? AND start_aya = ?
              AND end_sura   = ? AND end_aya   = ?
              AND has_quran  = 1
            ORDER BY CAST(segment_index AS REAL)
        """, (surah_number, ayah_number, surah_number, ayah_number))
        rows = cur.fetchall()
        conn.close()

        segments = []
        high_water = 0  # furthest end_word reached so far
        for start_w, end_w, text in rows:
            start_w = int(start_w)
            end_w   = int(end_w)
            # A segment is a repeat only when it does NOT advance past the furthest
            # word already covered.  If end_w > high_water the reciter has moved to a
            # new stopping point even if start_w backed up into covered territory.
            is_repeat = end_w <= high_water
            segments.append({
                'start_word': start_w,
                'end_word':   end_w,
                'text':       text or '',
                'is_repeat':  is_repeat,
            })
            if end_w > high_water:
                high_water = end_w
        return segments, True
    except Exception as e:
        app.logger.error(f'Error reading positions.db for reciter {reciter!r}: {e}')
        return [], True

def _get_waqf_at_boundary(surah_number, ayah_number, end_word, versions):
    """Return waqf entries [{symbols, version}] for all versions at a segment boundary.

    The positions.db end_word equals the waqf DB word_index for the last word of
    that segment.  We try end_word first, then end_word-1 as a 1-off fallback.
    """
    result = []
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        return result
    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for ver in versions:
            if not _is_valid_mushaf_version(ver):
                continue
            qcol = '"' + ver.replace('"', '""') + '"'
            for wi in (end_word, end_word - 1):
                cur.execute(f"""
                    SELECT {qcol} as symbol FROM waqf
                    WHERE "السورة" = ? AND "الآية" = ? AND word_index = ?
                    AND {qcol} IS NOT NULL AND {qcol} != ''
                """, (surah_number, ayah_number, wi))
                row = cur.fetchone()
                if row:
                    result.append({'symbols': row['symbol'], 'version': ver})
                    break
        conn.close()
    except Exception as e:
        app.logger.error(f'Error fetching waqf at boundary: {e}')
    return result


@app.route('/api/recitation-guide/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_recitation_guide(surah_number, ayah_number):
    """Return segmented recitation guide for a reciter, powered by their positions.db.

    Query params:
      reciter — the reciter key (e.g. 'Mahmoud Khalil al-Husary (Muallim)')

    Returns:
      {reciter, has_positions_db, segments: [{start_word, end_word, text, waqf: [{symbols}]}]}
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    cfg = RECITER_GUIDE_CONFIG.get(reciter, {})
    # الحصري column was dropped from mushaf_waqf.db (commit 703521b); fall back
    # to المدينة so unconfigured reciters still get a guide overlay.
    waqf_col = cfg.get('waqf_col', 'المدينة')
    valid_versions = [waqf_col] if _is_valid_mushaf_version(waqf_col) else []

    pos_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)

    if not has_db:
        return jsonify({'reciter': reciter, 'has_positions_db': False, 'segments': []})

    result_segments = []
    for seg in pos_segs:
        waqf_entries = _get_waqf_at_boundary(
            surah_number, ayah_number, seg['end_word'], valid_versions
        ) if valid_versions else []
        # Strip version label — the guide is per-reciter, not per-mushaf
        for e in waqf_entries:
            e.pop('version', None)
        result_segments.append({
            'start_word': seg['start_word'],
            'end_word':   seg['end_word'],
            'text':       seg['text'],
            'is_repeat':  seg['is_repeat'],
            'waqf':       waqf_entries,
        })
    return jsonify({'reciter': reciter, 'has_positions_db': True, 'segments': result_segments})


@app.route('/api/pause-match/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_pause_match(surah_number, ayah_number):
    """Return how well a reciter's pause positions match each mushaf's waqf marks.

    Query params:
      reciter — the reciter key

    Returns:
      {
        has_data: bool,
        pause_count: int,
        matches: { version: {matched, total, score} }
      }
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    pos_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)

    if not has_db or not pos_segs:
        return jsonify({'has_data': False, 'pause_count': 0, 'matches': {}})

    versions = sorted(_get_mushaf_version_whitelist())

    # ── Filter out repeated segments ─────────────────────────────────────────
    # Repeated segments (reciter backs up and re-reads) are not real pauses.
    pause_segs = [seg for seg in pos_segs if not seg.get('is_repeat')]

    if not pause_segs:
        return jsonify({'has_data': False, 'pause_count': 0, 'matches': {}})

    # ── Identify the verse-end stop ──────────────────────────────────────────
    # The last non-repeat segment always ends at رأس الآية.
    verse_end_word = pause_segs[-1]['end_word']

    # Symbols that explicitly PROHIBIT stopping (verse-end precision check only).
    # U+06D9 (ۙ) = IndoPak glyph for "لا" = لا يجوز الوقف.
    def _is_prohibited_stop(symbols_str):
        # Exact-match only — substring 'in' would falsely flag arbitrary
        # composite waqf strings that happen to contain the letters ل-ا.
        sym = (symbols_str or '').strip()
        return sym == 'لا' or sym == '\u06D9'

    # Symbols that should NOT count as coverage targets — only hard prohibitions.
    # ص (صلى) is treated like ج (جائز): stopping is permissible, so it IS a target.
    def _is_not_coverage_mark(symbols_str):
        sym = (symbols_str or '').strip()
        if not sym:
            return True
        return _is_prohibited_stop(sym)

    pause_count = len(pause_segs)

    # Build set of pause end_words for coverage computation
    pause_end_words = {seg['end_word'] for seg in pause_segs}

    matches = {}
    for ver in versions:
        # ── Precision: how many of the reciter's stops match mushaf marks ────
        matched = 0
        for seg in pause_segs:
            is_verse_end = (seg['end_word'] == verse_end_word)
            waqf_entries = _get_waqf_at_boundary(
                surah_number, ayah_number, seg['end_word'], [ver]
            )
            if is_verse_end:
                # رأس الآية is always valid unless mushaf explicitly prohibits it.
                sym = waqf_entries[0]['symbols'] if waqf_entries else ''
                if not _is_prohibited_stop(sym):
                    matched += 1
            else:
                # ص (صلى) is treated like ج (جائز) — any permissible mark counts.
                valid_entries = [
                    e for e in waqf_entries
                    if not _is_prohibited_stop(e.get('symbols', ''))
                ]
                if valid_entries:
                    matched += 1

        # ── Coverage: how many of the mushaf's marks the reciter stopped at ──
        # Exclude only hard prohibition marks (لا / ۙ).
        # ص (صلى) is treated like ج — it IS a mark the reciter is expected to cover.
        mushaf_rows = _fetch_single_mushaf_waqf(surah_number, ayah_number, ver)
        mark_positions = {
            r['word_index'] for r in mushaf_rows
            if r.get('word_index') and not _is_not_coverage_mark(r.get('symbols', ''))
        }
        # A mark at word_index wi is covered when a pause falls at end_word=wi or wi+1
        # (matching the ±1 fallback logic in _get_waqf_at_boundary)
        marks_covered = sum(
            1 for wi in mark_positions
            if wi in pause_end_words or (wi + 1) in pause_end_words
        )
        mushaf_marks = len(mark_positions)
        coverage_score = round(marks_covered / mushaf_marks * 100) if mushaf_marks > 0 else 100

        matches[ver] = {
            'matched': matched,
            'total': pause_count,
            'score': round(matched / pause_count * 100) if pause_count > 0 else 0,
            'mushaf_marks': mushaf_marks,
            'marks_covered': marks_covered,
            'coverage_score': coverage_score,
        }

    return jsonify({'has_data': True, 'pause_count': pause_count, 'matches': matches})


@app.route('/api/reciter-compare/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_reciter_compare(surah_number, ayah_number):
    """Compare pause positions of one reciter against every other reciter with positions data.

    Returns for each other reciter:
      a_to_b: fraction of subject's mid-pauses that land within ±1 of other's pauses
      b_to_a: fraction of other's mid-pauses that land within ±1 of subject's pauses
    Verse-end stop is excluded (every reciter stops there — trivially 100%).
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    subject_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)
    if not has_db or not subject_segs:
        return jsonify({'has_data': False, 'comparisons': {}})

    subject_pauses = [s for s in subject_segs if not s.get('is_repeat')]
    if not subject_pauses:
        return jsonify({'has_data': False, 'comparisons': {}})

    verse_end_word = subject_pauses[-1]['end_word']
    # Mid-pause segments only (exclude رأس الآية — every reciter stops there)
    subject_mid_segs = [s for s in subject_pauses if s['end_word'] != verse_end_word]

    def _overlap(a_set, b_set):
        """Fraction of positions in a_set that have a ±1 match in b_set."""
        if not a_set:
            return 1.0, len(a_set), len(a_set)
        matched = sum(1 for w in a_set if w in b_set or (w - 1) in b_set or (w + 1) in b_set)
        return matched / len(a_set), matched, len(a_set)

    comparisons = {}
    for other_reciter, cfg in RECITER_GUIDE_CONFIG.items():
        if other_reciter == reciter:
            continue
        other_segs, other_has_db = _get_positions_segments(surah_number, ayah_number, other_reciter)
        if not other_has_db or not other_segs:
            continue
        other_pauses = [s for s in other_segs if not s.get('is_repeat')]
        if not other_pauses:
            continue
        other_verse_end = other_pauses[-1]['end_word']

        # Work with full segment objects so diff can show segment text
        a_segs = [s for s in subject_pauses if s['end_word'] != verse_end_word]
        b_segs = [s for s in other_pauses  if s['end_word'] != other_verse_end]
        a_set  = {s['end_word'] for s in a_segs}
        b_set  = {s['end_word'] for s in b_segs}

        a_frac, a_matched, a_total = _overlap(a_set, b_set)
        b_frac, b_matched, b_total = _overlap(b_set, a_set)

        # Unmatched segments for the diff view — carry full uthmani_text from positions.db
        only_in_a = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in a_segs
            if not (s['end_word'] in b_set or (s['end_word'] - 1) in b_set or (s['end_word'] + 1) in b_set)
        ]
        only_in_b = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in b_segs
            if not (s['end_word'] in a_set or (s['end_word'] - 1) in a_set or (s['end_word'] + 1) in a_set)
        ]

        comparisons[other_reciter] = {
            'a_to_b_score':   round(a_frac * 100),
            'a_to_b_matched': a_matched,
            'a_to_b_total':   a_total,
            'b_to_a_score':   round(b_frac * 100),
            'b_to_a_matched': b_matched,
            'b_to_a_total':   b_total,
            # Combined similarity: harmonic mean (same logic as F1)
            'similarity': round(
                2 * a_frac * b_frac / (a_frac + b_frac) * 100
                if (a_frac + b_frac) > 0 else 0
            ),
            'diff': {'only_in_a': only_in_a, 'only_in_b': only_in_b},
        }

    return jsonify({
        'has_data': bool(comparisons),
        'subject_mid_count': len(subject_mid_segs),
        'comparisons': comparisons,
    })


def get_mushaf_waqf_symbols(surah_number, ayah_number, mushaf_version):
    """Fetch waqf symbols from Excel-source DB for one or more Mushaf versions.

    mushaf_version may be a string (single version) or a list of strings.
    Each returned entry gains a 'version' field identifying its source.
    """
    if isinstance(mushaf_version, (list, tuple)):
        versions = [v for v in mushaf_version if _is_valid_mushaf_version(v)]
    else:
        versions = [mushaf_version] if _is_valid_mushaf_version(mushaf_version) else []

    if not versions or not os.path.exists(MUSHAF_WAQF_DATABASE):
        return []

    all_rows = []
    for ver in versions:
        rows = _fetch_single_mushaf_waqf(surah_number, ayah_number, ver)
        for r in rows:
            r['version'] = ver
        all_rows.extend(rows)
    return all_rows


# In-process cache for mushaf waqf DB lookups.
# Callers mutate the returned dicts (adding a 'version' key) so we always
# return a list of fresh dict copies, keeping the cached originals clean.
# Bounded — ~6236 ayahs × ~10 versions = ~62K possible keys.
_mushaf_waqf_cache: _BoundedLRU = _BoundedLRU(maxsize=8192)


def _fetch_single_mushaf_waqf(surah_number, ayah_number, mushaf_version):
    """Internal: fetch for exactly one validated version, with in-process caching."""
    if not _is_valid_mushaf_version(mushaf_version):
        return []

    cache_key = (surah_number, ayah_number, mushaf_version)
    cached = _mushaf_waqf_cache.get(cache_key)
    if cached is not None:
        return [dict(r) for r in cached]

    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Column name is validated against a whitelist above, so interpolation
        # is safe here (SQLite doesn't support parameterised identifiers).
        quoted_col = '"' + mushaf_version.replace('"', '""') + '"'
        cols = set(_get_mushaf_table_columns())

        token_expr = 'NULL as token_index'
        if 'token_index' in cols:
            token_expr = 'CAST("token_index" AS INTEGER) as token_index'
        else:
            pos_col = _get_mushaf_position_column()
            if pos_col and pos_col != 'word_index':
                quoted_pos_col = '"' + pos_col.replace('"', '""') + '"'
                token_expr = f'CAST({quoted_pos_col} AS INTEGER) as token_index'

        word_expr = 'NULL as word_index'
        if 'word_index' in cols:
            word_expr = 'CAST("word_index" AS INTEGER) as word_index'
        else:
            pos_col = _get_mushaf_position_column()
            if pos_col == 'word_index':
                word_expr = 'CAST("word_index" AS INTEGER) as word_index'

        query = f'''
            SELECT "الكلمة" as word, {quoted_col} as symbol, {token_expr}, {word_expr}
            FROM waqf
            WHERE "السورة" = ? AND "الآية" = ?
            AND {quoted_col} IS NOT NULL AND {quoted_col} != ''
            ORDER BY rowid ASC
        '''

        cursor.execute(query, (surah_number, ayah_number))
        rows = cursor.fetchall()
        conn.close()

        result = [
            {
                'clean_token': row['word'],
                'symbols': row['symbol'],
                # DB stores 1-based word position; convert to 0-based for the JS
                # word array so map.set(token_index, ...) aligns with words[i].
                'token_index': (row['token_index'] - 1) if row['token_index'] is not None else None,
                'word_index': row['word_index']
            }
            for row in rows
        ]
        _mushaf_waqf_cache[cache_key] = result
        return [dict(r) for r in result]
    except Exception as e:
        app.logger.error(f"Error reading mushaf waqf: {e}")
        return []

def get_waqf_symbols(surah_number, ayah_number, source):
    """Fetch waqf symbols for an ayah from the dedicated waqf database."""
    mushaf_version = request.args.getlist('mushaf_version') or request.args.get('mushaf_version')
    
    # If a specific mushaf version is requested, we use the Excel-sourced data.
    if mushaf_version:
        mushaf_data = get_mushaf_waqf_symbols(surah_number, ayah_number, mushaf_version)
        # For IndoPak source, also merge the embedded الهندي waqf symbols — but
        # ONLY if 'الهندي' itself isn't already among the selected mushaf_version
        # values, otherwise we'd duplicate every symbol.
        _mv_list = mushaf_version if isinstance(mushaf_version, list) else [mushaf_version]
        _hindi_already = 'الهندي' in _mv_list
        indopak_extras = []
        if (source in ('indopak_nastaleeq', 'indopak_nastaleeq_2')
                and not _hindi_already
                and os.path.exists(WAQF_DATABASE)):
            try:
                conn = sqlite3.connect(WAQF_DATABASE)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                waqf_src = 'indopak_nastaleeq'
                cursor.execute(
                    '''
                    SELECT token_index, word_index, symbols, original_token, clean_token
                    FROM waqf_symbols
                    WHERE source = ? AND surah_number = ? AND ayah_number = ?
                    ORDER BY token_index ASC
                    ''',
                    (waqf_src, surah_number, ayah_number)
                )
                indopak_extras = [
                    {
                        'token_index': r['token_index'],
                        'word_index': r['word_index'],
                        'symbols': r['symbols'],
                        'original_token': r['original_token'],
                        'clean_token': r['clean_token'],
                        'version': 'الهندي',
                    }
                    for r in cursor.fetchall()
                ]
                conn.close()
            except sqlite3.Error:
                pass

        if mushaf_data:
            verse_key = f"{surah_number}:{ayah_number}"
            verse_text = ''
            source_data = get_quran_text_data_by_source(source)
            if isinstance(source_data, dict):
                verse_text = (source_data.get(verse_key, {}) or {}).get('text', '') or ''

            words = [
                {'text': token, 'text_original': token}
                for token in verse_text.split()
                if token
            ]

            if not words:
                return mushaf_data + indopak_extras

            aligned = []
            search_start = 0
            current_word_pos = 0
            for row in mushaf_data:
                matched_index = _find_mushaf_row_match_index(words, row, search_start)
                if matched_index is None:
                    aligned.append(row)
                    continue

                search_start = matched_index + 1
                token_text = words[matched_index].get('text_original') or words[matched_index].get('text') or ''
                current_word_pos = sum(
                    1 for i in range(0, matched_index + 1)
                    if _normalize_mushaf_word_token(words[i].get('text_original') or words[i].get('text') or '')
                )
                aligned.append({
                    'token_index': matched_index,
                    'word_index': current_word_pos if current_word_pos > 0 else row.get('word_index'),
                    'symbols': row.get('symbols', ''),
                    'version': row.get('version', ''),
                    'original_token': token_text,
                    'clean_token': token_text
                })

            return aligned + indopak_extras

        if indopak_extras:
            return indopak_extras

    # For IndoPak sources, also include the embedded waqf symbols labeled as الهندي.
    if source not in ('indopak_nastaleeq', 'indopak_nastaleeq_2'):
        return []

    if not os.path.exists(WAQF_DATABASE):
        # If mushaf_version data was fetched above, still return it
        return []

    try:
        conn = sqlite3.connect(WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Both indopak variants share the same waqf data in the DB
        waqf_source = 'indopak_nastaleeq' if source == 'indopak_nastaleeq_2' else source
        cursor.execute(
            '''
            SELECT token_index, word_index, symbols, original_token, clean_token
            FROM waqf_symbols
            WHERE source = ? AND surah_number = ? AND ayah_number = ?
            ORDER BY token_index ASC
            ''',
            (waqf_source, surah_number, ayah_number)
        )
        rows = cursor.fetchall()
        conn.close()

        # Label IndoPak embedded waqf symbols with the الهندي mushaf version so
        # they render with the IndoPak font and the correct mushaf colour class.
        return [
            {
                'token_index': row['token_index'],
                'word_index': row['word_index'],
                'symbols': row['symbols'],
                'original_token': row['original_token'],
                'clean_token': row['clean_token'],
                'version': 'الهندي',
            }
            for row in rows
        ]
    except sqlite3.Error as e:
        app.logger.error(f"Failed to read waqf symbols: {e}")
        return []


digital_khatt_data_normalized, waqf_rows_digital, digital_stats = normalize_quran_dataset(
    'digital_khatt', digital_khatt_data
)
qpc_hafs_data_normalized, waqf_rows_qpc, qpc_stats = normalize_quran_dataset(
    'qpc_hafs', qpc_hafs_data
)
indopak_nastaleeq_data_normalized, waqf_rows_indopak, indopak_stats = normalize_quran_dataset(
    'indopak_nastaleeq', indopak_nastaleeq_data
)
indopak_nastaleeq_2_data_normalized, _, _ = normalize_quran_dataset(
    'indopak_nastaleeq', indopak_nastaleeq_2_data
)


# QUL waqf code → inline Arabic combining mark, used to bake an Azhar-marked
# variant of QPC Hafs for the Amiri Quran font.
_AZHAR_CODE_TO_MARK = {
    'م':   'ۘ',  # ۘ لازم
    'قلى': 'ۗ',  # ۗ قلى
    'ر':   'ۗ',  # ۗ راجح (rendered like قلى)
    'ج':   'ۚ',  # ۚ جائز
    'ص':   'ۖ',  # ۖ صلى
    'لا':  'ۙ',  # ۙ لا وقف
    'ع':   'ۛ',  # ۛ معانقة
    'س':   'ۜ',  # ۜ سكتة
}


def _encode_azhar_symbol(sym):
    if not sym:
        return ''
    s = sym.strip()
    if s in _AZHAR_CODE_TO_MARK:
        return _AZHAR_CODE_TO_MARK[s]
    # Already encoded as inline marks — pass through.
    if all(ch in WAQF_SYMBOL_CHARS for ch in s):
        return s
    return ''


# Trailing ayah-number suffix (NBSP + Arabic-Indic digits) that QPC Hafs glues
# to the last word. We insert waqf marks BEFORE this suffix so they sit on the
# word, not after the number.
_AYAH_END_SUFFIX_PATTERN = re.compile(r'[ \s][٠-٩۰-۹]+$')


def _insert_mark_before_ayah_end(token, mark):
    match = _AYAH_END_SUFFIX_PATTERN.search(token)
    if match:
        return token[:match.start()] + mark + token[match.start():]
    return token + mark


# Trailing run of Arabic-Indic digits at the very end of a verse — the ayah
# number. Used to prefix it with U+06DD so the Amiri Quran font draws it
# enclosed in the verse-end rosette.
_AYAH_NUMBER_TAIL_PATTERN = re.compile(r'(?<!۝)([٠-٩۰-۹]+)$')


def _wrap_ayah_number_with_end_marker(text):
    match = _AYAH_NUMBER_TAIL_PATTERN.search(text)
    if not match:
        return text
    return text[:match.start()] + '۝' + text[match.start():]


def _build_amiri_quran_data(base_data):
    """Bake الأزهر waqf marks into the QPC Hafs text so the Amiri Quran font
    shows them inline in 'original only' mode, matching how other mushaf fonts
    carry their tradition's marks in the text itself."""
    if not isinstance(base_data, dict):
        return base_data
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        # Without the source DB we can't transform — fall back to qpc_hafs as-is.
        return {k: dict(v) if isinstance(v, dict) else v for k, v in base_data.items()}

    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            'SELECT "السورة" AS surah, "الآية" AS ayah, '
            '"token_index" AS tidx, "الأزهر" AS sym '
            'FROM waqf '
            'WHERE "الأزهر" IS NOT NULL AND "الأزهر" != "" '
            'ORDER BY "السورة", "الآية", "token_index"'
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.Error as exc:
        app.logger.warning(f'Could not read Azhar waqf for Amiri Quran build: {exc}')
        return {k: dict(v) if isinstance(v, dict) else v for k, v in base_data.items()}

    marks_by_verse = {}
    for r in rows:
        try:
            verse_key = f"{int(r['surah'])}:{int(r['ayah'])}"
            tidx = int(r['tidx'])
        except (TypeError, ValueError):
            continue
        mark = _encode_azhar_symbol(r['sym'])
        if not mark:
            continue
        marks_by_verse.setdefault(verse_key, []).append((tidx, mark))

    out = {}
    for verse_key, verse_data in base_data.items():
        if not isinstance(verse_data, dict):
            out[verse_key] = verse_data
            continue
        verse_copy = dict(verse_data)
        text = verse_copy.get('text', '') or ''
        # Strip the existing inline waqf marks so Azhar's are the only ones shown.
        stripped = ''.join(ch for ch in text if ch not in WAQF_SYMBOL_CHARS)
        # Split on every whitespace run (NBSP included) while preserving the
        # separators, so verses that start with ۞ joined to the next word by
        # NBSP still tokenise the way the mushaf_waqf DB expects.
        parts = re.split(r'(\s+)', stripped)
        token_part_indices = [i for i, p in enumerate(parts) if p and not p.isspace()]
        for tidx, mark in marks_by_verse.get(verse_key, []):
            i = tidx - 1
            if 0 <= i < len(token_part_indices):
                pi = token_part_indices[i]
                parts[pi] = _insert_mark_before_ayah_end(parts[pi], mark)
        verse_copy['text'] = _wrap_ayah_number_with_end_marker(''.join(parts))
        out[verse_key] = verse_copy
    return out


amiri_quran_data = _build_amiri_quran_data(qpc_hafs_data)
amiri_quran_data_normalized, _, amiri_stats = normalize_quran_dataset(
    'amiri_quran', amiri_quran_data
)

initialize_waqf_database(waqf_rows_digital + waqf_rows_qpc + waqf_rows_indopak)
app.logger.info(
    f"Waqf normalization summary: {digital_stats}, {qpc_stats}, {indopak_stats}, {amiri_stats}"
)

# Ensure word_name.db has an index on (surah_number, ayah_number) for fast per-ayah
# lookups. Creates the index if missing; safe to call on every startup.
try:
    _wn_conn = sqlite3.connect(DATABASE)
    _wn_conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_verses_surah_ayah ON verses(surah_number, ayah_number)'
    )
    _wn_conn.commit()
    _wn_conn.close()
except sqlite3.Error as _wn_err:
    app.logger.warning(f'Could not create word_name index: {_wn_err}')


# Database helper functions
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        # Check if database file exists
        if not os.path.exists(DATABASE):
            app.logger.error(f"Database file not found: {DATABASE}")
            return None
            
        try:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row  # To access columns by name
        except sqlite3.Error as e:
            app.logger.error(f"Database connection error: {e}")
            return None
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def get_word_meanings(surah_number, ayah_number):
    db = get_db()
    if db is None:
        app.logger.warning("Database not available for word meanings")
        return {}
    
    try:
        cursor = db.cursor()
        query = '''
            SELECT word, meaning
            FROM verses
            WHERE surah_number = ? AND ayah_number = ?
        '''
        cursor.execute(query, (surah_number, ayah_number))
        rows = cursor.fetchall()
        word_meanings = {}
        for row in rows:
            word_meanings[row['word']] = row['meaning']
        return word_meanings
    except sqlite3.Error as e:
        app.logger.error(f"Database query error: {e}")
        return {}


def get_word_meanings_ordered(surah_number, ayah_number):
    """Return word meanings as an ordered list for stable verse-order rendering on frontend."""
    db = get_db()
    if db is None:
        app.logger.warning("Database not available for ordered word meanings")
        return []

    try:
        cursor = db.cursor()
        query = '''
            SELECT word, meaning
            FROM verses
            WHERE surah_number = ? AND ayah_number = ?
            ORDER BY id ASC
        '''
        cursor.execute(query, (surah_number, ayah_number))
        rows = cursor.fetchall()
        return [
            {
                'word': row['word'],
                'meaning': row['meaning']
            }
            for row in rows
        ]
    except sqlite3.Error as e:
        app.logger.error(f"Database ordered query error: {e}")
        return []

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    health_status = {
        "status": "healthy",
        "service": "Quran Flask API",
        "checks": {
            "database": os.path.exists(DATABASE),
            "waqf_database": os.path.exists(WAQF_DATABASE),
            "digital_khatt_loaded": bool(digital_khatt_data),
            "qpc_hafs_loaded": bool(qpc_hafs_data),
            "indopak_loaded": bool(indopak_nastaleeq_data),
            "indopak_2_loaded": bool(indopak_nastaleeq_2_data),
            "transliteration_loaded": bool(transliteration_data),
            "audio_data_loaded": bool(audio_data)
        }
    }
    
    # Check if any critical component is missing
    if not all([
        digital_khatt_data,
        qpc_hafs_data,
        indopak_nastaleeq_data,
        transliteration_data
    ]):
        health_status["status"] = "degraded"
        return jsonify(health_status), 503
    
    return jsonify(health_status), 200

@app.route('/api/surahs', methods=['GET'])
def get_surahs():
    """Get list of surahs with their names (local data, no external API dependency)"""
    if surahs_data:
        return jsonify(surahs_data)
    
    # Fallback to extracting surah numbers from text data
    quran_text_data = get_quran_text_data()
    surahs = {int(vk.split(':')[0]) for vk in quran_text_data.keys()}
    return jsonify(sorted(surahs))

@app.route('/api/surahs/<int:surah_number>/ayahs', methods=['GET'])
def get_ayahs(surah_number):
    # Validate surah number range (1-114)
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number. Must be between 1 and 114."}), 400
        
    quran_text_data = get_quran_text_data()
    prefix = f"{surah_number}:"
    seen = set()
    for verse_key in quran_text_data.keys():
        if verse_key.startswith(prefix):
            seen.add(int(verse_key.split(':')[1]))
    return jsonify(sorted(seen))

@app.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>', methods=['GET'])
def get_ayah_text(surah_number, ayah_number):
    # Validate surah number range (1-114)
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number. Must be between 1 and 114."}), 400
    
    # Validate ayah number (basic range check)
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:  # Max ayah in any surah
        return jsonify({"error": "Invalid ayah number."}), 400

    source = normalize_source(request.args.get('source', 'qpc_hafs'))
        
    quran_text_data = get_quran_text_data()

    # Removed surah name mapping
    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in quran_text_data:
        ayah_data = dict(quran_text_data[verse_key])
        ayah_data.setdefault('id', ayah_number)
        # Expose verse identity explicitly so the frontend's "is this the
        # cached ayah?" check in updateDisplayedText() can hit.
        ayah_data['surah_number'] = surah_number
        ayah_data['ayah_number'] = ayah_number
        ayah_data['verse_key'] = verse_key
        ayah_data['transliteration'] = transliteration_data.get(verse_key, {})
        
        # Tafseer is fetched on-demand via /api/tafseer/<surah>/<ayah>
        # Add reciters' audio information (loads reciter files on first call)
        _ensure_reciters_initialized()
        ayah_data['reciters'] = {}
        for reciter, mapping in reciter_mappings.items():
            if verse_key in mapping:
                ayah_data['reciters'][reciter] = mapping[verse_key]
        
        # Fetch word meanings from the SQLite database (single query)
        ordered_meanings = get_word_meanings_ordered(surah_number, ayah_number)
        ayah_data['word_meanings_ordered'] = ordered_meanings
        ayah_data['word_meanings'] = {r['word']: r['meaning'] for r in ordered_meanings}
        ayah_data['waqf_symbols'] = get_waqf_symbols(surah_number, ayah_number, source)
        
        return jsonify(ayah_data)
    return jsonify({"error": "Ayah not found"}), 404


@app.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>/waqf', methods=['GET'])
def get_ayah_waqf_symbols(surah_number, ayah_number):
    """Expose waqf metadata independent from word-level data for frontend/UI consumers."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number. Must be between 1 and 114."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    source = normalize_source(request.args.get('source', 'qpc_hafs'))
    data = get_waqf_symbols(surah_number, ayah_number, source)
    return jsonify({
        'surah_number': surah_number,
        'ayah_number': ayah_number,
        'source': source,
        'waqf_symbols': data
    })

@app.route('/api/tafseer/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_tafseer(surah_number, ayah_number):
    """Fetch tafseer for a single ayah in parallel, with in-process caching."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"

    def _fetch_qurancom(name, tafseer_id):
        ck = (name, verse_key)
        if ck in _tafseer_cache:
            return name, _tafseer_cache[ck]
        url = TAFSEER_API_BASE.format(id=tafseer_id, verse_key=verse_key)
        try:
            resp = http_requests.get(url, timeout=10)
            resp.raise_for_status()
            text = resp.json().get('tafsir', {}).get('text', '')
            entry = {'text': text}
            _tafseer_cache[ck] = entry
            return name, entry
        except Exception as e:
            app.logger.error(f"Tafseer API error for {name} {verse_key}: {e}")
            return name, {'text': ''}

    def _fetch_quranenc(name, identifier):
        ck = (name, verse_key)
        if ck in _tafseer_cache:
            return name, _tafseer_cache[ck]
        url = TAFSEER_QURANENC_BASE.format(
            identifier=identifier, surah=surah_number, ayah=ayah_number
        )
        try:
            resp = http_requests.get(url, timeout=10)
            resp.raise_for_status()
            text = resp.json().get('result', {}).get('translation', '')
            entry = {'text': text}
            _tafseer_cache[ck] = entry
            return name, entry
        except Exception as e:
            app.logger.error(f"Tafseer (quranenc) API error for {name} {verse_key}: {e}")
            return name, {'text': ''}

    # Fast path: everything already cached, no threads needed.
    all_names = list(TAFSEER_API_IDS) + list(TAFSEER_QURANENC_IDS)
    if all((n, verse_key) in _tafseer_cache for n in all_names):
        return jsonify({n: _tafseer_cache[(n, verse_key)] for n in all_names})

    tasks = (
        [(n, tid, 'qurancom') for n, tid in TAFSEER_API_IDS.items()] +
        [(n, ident, 'quranenc') for n, ident in TAFSEER_QURANENC_IDS.items()]
    )
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks) or 1) as ex:
        futures = [
            ex.submit(_fetch_qurancom, n, src) if t == 'qurancom'
            else ex.submit(_fetch_quranenc, n, src)
            for n, src, t in tasks
        ]
        for future in concurrent.futures.as_completed(futures):
            name, entry = future.result()
            result[name] = entry

    return jsonify(result)


# Tajweed-annotated text cache: verse_key → {"html": "..."}
_tajweed_cache: _BoundedLRU = _BoundedLRU(maxsize=4096)

# verse_number param is silently ignored by this endpoint — it always returns
# all verses of the chapter, so we fetch once per surah and cache everything.
TAJWEED_API_BASE = 'https://api.quran.com/api/v4/quran/verses/uthmani_tajweed?chapter_number={surah}'

@app.route('/api/tajweed/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_tajweed(surah_number, ayah_number):
    """Return tajweed-annotated HTML for one ayah from quran.com v4."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in _tajweed_cache:
        resp = jsonify(_tajweed_cache[verse_key])
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    # Fetch all verses of the surah in one call and cache them all
    url = TAJWEED_API_BASE.format(surah=surah_number)
    try:
        r = http_requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        verses = data.get('verses', [])
        if not verses:
            return jsonify({"error": "Verse not found"}), 404
        # Cache every verse returned so sibling requests are instant
        for v in verses:
            vk = v.get('verse_key', '')
            if vk:
                _tajweed_cache[vk] = {"html": v.get('text_uthmani_tajweed', '')}
        if verse_key not in _tajweed_cache:
            return jsonify({"error": "Verse not found"}), 404
        resp = jsonify(_tajweed_cache[verse_key])
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    except Exception as e:
        app.logger.error(f"Tajweed API error for {verse_key}: {e}")
        return jsonify({"error": "Failed to fetch tajweed data"}), 502


@app.route('/api/eerab/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_eerab(surah_number, ayah_number):
    """Fetch grammatical analysis (إعراب) for a single ayah from SurahApp API."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    cache_key = (surah_number, ayah_number)
    if cache_key in _eerab_cache:
        return jsonify(_eerab_cache[cache_key])

    url = SURAHAPP_API_BASE.format(slug='eerab-aya', sura=surah_number, aya=ayah_number)
    try:
        resp = http_requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if 'error' in data:
            return jsonify({"content": ""}), 404
        result = {"content": data.get('content', '')}
        _eerab_cache[cache_key] = result
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"SurahApp eerab API error for {surah_number}:{ayah_number}: {e}")
        return jsonify({"content": ""}), 500


@app.route('/api/reciters/<reciter>/ayahs/<int:ayah_number>/audio', methods=['GET'])
def get_audio_segments(reciter, ayah_number):
    if ayah_number < 1:
        return jsonify({"error": "Invalid ayah number."}), 400

    _ensure_reciters_initialized()
    by_id = reciter_audio_by_global_id.get(reciter)
    if by_id is None:
        return jsonify({"error": "Reciter not found"}), 404

    audio_info = by_id.get(ayah_number)
    if audio_info:
        return jsonify(audio_info)
    return jsonify({"error": "Audio not found"}), 404

@app.route('/api/quran-text', methods=['GET'])
def get_quran_text():
    quran_text_data = get_quran_text_data()
    return jsonify(quran_text_data)

@app.route('/api/transliteration', methods=['GET'])
def get_transliteration():
    return jsonify(transliteration_data)

@app.route('/')
def index():
    return render_template('index.html', enable_vercel_analytics=_IS_SERVERLESS)


def normalize_source(source):
    valid_sources = [
        'digital_khatt', 'digital_khatt_2', 'old_madina',
        'indopak_nastaleeq', 'indopak_nastaleeq_2', 'qpc_hafs', 'shamarly',
        'amiri_quran'
    ]
    if source not in valid_sources:
        return 'qpc_hafs'
    if source in ('digital_khatt_2', 'old_madina'):
        return 'digital_khatt'
    return source


def get_quran_text_data_by_source(source):
    if source == 'digital_khatt':
        return digital_khatt_data_normalized
    if source == 'indopak_nastaleeq':
        return indopak_nastaleeq_data_normalized
    if source == 'indopak_nastaleeq_2':
        return indopak_nastaleeq_2_data_normalized
    if source == 'shamarly':
        return qpc_hafs_data_normalized
    if source == 'amiri_quran':
        return amiri_quran_data_normalized
    return qpc_hafs_data_normalized

def get_quran_text_data():
    source = normalize_source(request.args.get('source', 'qpc_hafs'))
    return get_quran_text_data_by_source(source)

@app.route('/api/audio-proxy')
def audio_proxy():
    """Validate and redirect to audio files to avoid firewall issues in sandbox environments"""
    from urllib.parse import urlparse
    
    audio_url = request.args.get('url')
    if not audio_url:
        return jsonify({"error": "Missing audio URL"}), 400
    
    # Parse and validate the URL
    try:
        parsed_url = urlparse(audio_url)
        
        # Only allow HTTPS protocol
        if parsed_url.scheme != 'https':
            return jsonify({"error": "Only HTTPS URLs are allowed"}), 400
        
        # Only allow specific trusted domains and default HTTPS port.
        allowed_domains = {'audio.qurancdn.com', 'audio-cdn.tarteel.ai', 'everyayah.com'}
        if parsed_url.hostname not in allowed_domains:
            return jsonify({"error": "Only trusted audio domains are allowed"}), 400
        if parsed_url.port not in (None, 443):
            return jsonify({"error": "Only default HTTPS port is allowed"}), 400
        if parsed_url.username or parsed_url.password:
            return jsonify({"error": "Credentials in URL are not allowed"}), 400
            
    except Exception as e:
        app.logger.error(f"URL validation error: {e}")
        return jsonify({"error": "Invalid URL format"}), 400
    
    # Redirect to the validated audio URL instead of proxying
    # This allows the client browser to fetch directly from trusted audio CDNs
    # which is allowed by the CSP media-src directive and avoids firewall issues
    # Using 307 (Temporary Redirect) to preserve request method
    return redirect(audio_url, code=307)


@app.route('/api/search', methods=['GET'])
def search_verses():
    """Search for verses containing specific text or words"""
    query = request.args.get('q', '').strip()
    source = request.args.get('source', 'qpc_hafs')
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({"error": "Search query parameter 'q' is required"}), 400
    
    if len(query) > 500:
        return jsonify({"error": "Search query too long. Maximum 500 characters allowed."}), 400
    
    if limit < 1 or limit > 100:
        limit = 50
    
    source = normalize_source(source)
    search_data = get_quran_text_data_by_source(source)

    # Normalise both the query and each verse so typed queries without
    # vocalisation still match the fully-vocalised text.
    normalized_query = _normalize_for_search(query)
    if not normalized_query:
        return jsonify({
            'query': query,
            'total_results': 0,
            'results': [],
            'source': source
        })

    results = []
    for verse_key, verse_data in search_data.items():
        if len(results) >= limit:
            break

        text = verse_data.get('text', '')
        if normalized_query in _normalize_for_search(text):
            surah_num, ayah_num = verse_key.split(':')
            results.append({
                'verse_key': verse_key,
                'surah_number': int(surah_num),
                'ayah_number': int(ayah_num),
                'text': text,
                'highlight': True
            })

    return jsonify({
        'query': query,
        'total_results': len(results),
        'results': results,
        'source': source
    })

@app.route('/api/word-search', methods=['GET'])
def search_word_meanings():
    """Search for word meanings in the database"""
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({"error": "Search query parameter 'q' is required"}), 400
    
    if len(query) > 500:
        return jsonify({"error": "Search query too long. Maximum 500 characters allowed."}), 400
    
    if limit < 1 or limit > 100:
        limit = 50
    
    db = get_db()
    if db is None:
        return jsonify({"error": "Database not available"}), 503
    
    try:
        cursor = db.cursor()
        # Search in both word and meaning columns
        search_query = '''
            SELECT DISTINCT surah_number, ayah_number, word, meaning
            FROM verses
            WHERE word LIKE ? OR meaning LIKE ?
            LIMIT ?
        '''
        search_pattern = f'%{query}%'
        cursor.execute(search_query, (search_pattern, search_pattern, limit))
        rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append({
                'surah_number': row['surah_number'],
                'ayah_number': row['ayah_number'],
                'word': row['word'],
                'meaning': row['meaning']
            })
        
        return jsonify({
            'query': query,
            'total_results': len(results),
            'results': results
        })
    except sqlite3.Error as e:
        app.logger.error(f"Database search error: {e}")
        return jsonify({"error": "Search failed"}), 500

@app.route('/api/shamarly/ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_shamarly_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]

        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM words WHERE surah = ? AND ayah = ? ORDER BY word_index ASC", (surah_number, ayah_number))
        words = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()

        # Fetch pages and verse-line rows in one connection to avoid re-opening.
        if words:
            first_word_id = words[0]['word_index']
            last_word_id = words[-1]['word_index']
            layout_cursor.execute("""
                SELECT DISTINCT page_number FROM pages 
                WHERE (first_word_id <= ? AND last_word_id >= ?) OR (first_word_id <= ? AND last_word_id >= ?)
                OR (first_word_id >= ? AND last_word_id <= ?)
            """, (last_word_id, first_word_id, first_word_id, last_word_id, first_word_id, last_word_id))
            pages = sorted([int(row['page_number']) for row in layout_cursor.fetchall()])
            layout_cursor.execute(
                '''
                SELECT page_number, line_number, first_word_id, last_word_id
                FROM pages
                WHERE line_type = 'ayah'
                  AND (
                        (first_word_id <= ? AND last_word_id >= ?)
                     OR (first_word_id <= ? AND last_word_id >= ?)
                     OR (first_word_id >= ? AND last_word_id <= ?)
                  )
                ORDER BY page_number ASC, line_number ASC
                ''',
                (last_word_id, first_word_id, first_word_id, last_word_id, first_word_id, last_word_id)
            )
            _prefetched_line_rows = [dict(row) for row in layout_cursor.fetchall()]
        else:
            pages = []
            _prefetched_line_rows = []

        layout_conn.close()
        
        glyph_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'glyph_mappings.db'))
        glyph_conn.row_factory = sqlite3.Row
        glyph_cursor = glyph_conn.cursor()
        font_name = None
        if pages:
            # Shemrly font naming follows actual Mushaf page numbering.
            effective_page = max(1, int(pages[0]))
            font_name = f"Shemrly-Page{effective_page:03d}"

        shemrly_pages_with_fonts = []
        for page in pages:
            candidate_font = f"Shemrly-Page{int(page):03d}"
            if _get_shamarly_font_supported_codepoints(candidate_font) is not None:
                shemrly_pages_with_fonts.append(int(page))

        # Keep original Arabic words for waqf matching before replacing with glyph chars.
        original_words = [dict(word) for word in words]
        raw_arabic_text = ' '.join(
            (item.get('text_original') or item.get('text') or '').strip()
            for item in original_words
            if (item.get('text_original') or item.get('text') or '').strip()
        )

        for word in words:
            glyph_char = None

            if shemrly_pages_with_fonts:
                for page in shemrly_pages_with_fonts:
                    glyph_char = _get_shamarly_glyph_char_for_word(page, int(word['word_index']))
                    if glyph_char:
                        break

            # Legacy compatibility fallback only if no Shemrly page font is available.
            if not glyph_char and not shemrly_pages_with_fonts:
                glyph_cursor.execute(
                    """
                    SELECT codepoint, codepoint_hex, arabic_word
                    FROM glyph_mappings
                    WHERE surah_number = ? AND ayah_number = ? AND word_position = ?
                    ORDER BY id ASC
                    """,
                    (surah_number, ayah_number, word['word_index'])
                )
                candidates = glyph_cursor.fetchall()
                mapping = None
                best_score = -1
                for candidate in candidates:
                    score = _glyph_row_score(candidate['arabic_word'])
                    if score > best_score:
                        mapping = candidate
                        best_score = score
                if mapping:
                    glyph_char = chr(mapping['codepoint'])

            if glyph_char:
                word['glyph_char'] = glyph_char
                word['text'] = glyph_char
        glyph_conn.close()

        waqf_symbols = []
        if mushaf_version:
            mushaf_waqf_rows = get_mushaf_waqf_symbols(surah_number, ayah_number, mushaf_version)

            # Group rows by mushaf version so each version aligns to the verse
            # words independently (a shared advancing pointer would skip a later
            # version's early tokens). Preserve 'version' so the frontend can
            # show/hide and colour marks per selected mushaf, like other fonts.
            rows_by_version = {}
            for row in mushaf_waqf_rows:
                rows_by_version.setdefault(row.get('version', ''), []).append(row)

            for version, version_rows in rows_by_version.items():
                search_start = 0
                for row in version_rows:
                    matched_index = _find_mushaf_row_match_index(original_words, row, search_start)
                    if matched_index is None:
                        continue
                    search_start = matched_index + 1
                    arabic_clean_token = original_words[matched_index].get('text_original') or original_words[matched_index].get('text') or ''
                    word_position_in_ayah = sum(
                        1 for i in range(0, matched_index + 1)
                        if _normalize_mushaf_word_token(_get_word_match_text(original_words[i]))
                    )
                    waqf_symbols.append({
                        'token_index': matched_index,
                        'word_index': word_position_in_ayah if word_position_in_ayah > 0 else None,
                        'symbols': row.get('symbols', ''),
                        'version': version,
                        'clean_token': arabic_clean_token,
                        'original_token': arabic_clean_token
                    })

        verse_lines = []
        if words:
            first_word_id = int(words[0]['word_index'])
            last_word_id = int(words[-1]['word_index'])

            for line in _prefetched_line_rows:
                line_first = int(line['first_word_id'])
                line_last = int(line['last_word_id'])
                line_words = []
                for token_index, word in enumerate(words):
                    word_pos = int(word['word_index'])
                    if line_first <= word_pos <= line_last:
                        line_words.append({
                            'token_index': token_index,
                            'word_index': word_pos,
                            'text': word.get('text') or ''
                        })

                if line_words:
                    verse_lines.append({
                        'page_number': int(line['page_number']),
                        'line_number': int(line['line_number']),
                        'words': line_words
                    })

        return jsonify({
            'surah': surah_number,
            'ayah': ayah_number,
            'words': words,
            'raw_text': raw_arabic_text,
            'verse_lines': verse_lines,
            'pages': pages,
            'font_name': font_name,
            'waqf_symbols': waqf_symbols,
            'mushaf_version': (mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or ''))
        })
    except Exception as e:
        app.logger.error(f"Error fetching shamarly data: {e}")
        return jsonify({"error": str(e)}), 500


def _normalize_mushaf_word_token(value):
    text = (value or '').strip()
    if not text:
        return ''
    text = ARABIC_DIACRITICS_STRIP_PATTERN.sub('', text)
    return ''.join(ch for ch in text if not ch.isspace())


def _compact_mushaf_word_token(value):
    text = (value or '').strip()
    if not text:
        return ''
    return ''.join(ch for ch in text if not ch.isspace())


def _get_row_match_text(row):
    return row.get('clean_token') or row.get('word') or row.get('original_token') or ''


def _get_word_match_text(word):
    return word.get('text_original') or word.get('text') or ''


def _word_index_hint_to_list_index(words, row):
    """Map DB word_index (1-based within ayah words) to a list index.

    word_index is interpreted as the ordinal position among content words in the
    verse, excluding marker-only tokens (e.g. Rubu/Sajda standalone markers).
    """
    raw = row.get('word_index')
    if raw is None:
        return None
    try:
        hinted_word_pos = int(raw)
    except (TypeError, ValueError):
        return None

    if hinted_word_pos <= 0:
        return None

    current_word_pos = 0
    for idx, word in enumerate(words):
        token = _get_word_match_text(word)
        # Treat non-empty normalized token as a real word; marker-only tokens
        # normalize to empty and are skipped from within-ayah word indexing.
        if _normalize_mushaf_word_token(token):
            current_word_pos += 1
            if current_word_pos == hinted_word_pos:
                return idx

    return None


def _find_mushaf_row_match_index(words, row, search_start=0):
    """Find best token index for a mushaf waqf row.

    Priority:
    1) Optional DB word_index hint (within-ayah content-word position).
    2) Exact token matching (only whitespace removed).
    3) Normalized fallback (diacritics/waqf removed) for script variance.
    """
    if not words:
        return None

    target_text = _get_row_match_text(row)
    target_raw = _compact_mushaf_word_token(target_text)
    target_norm = _normalize_mushaf_word_token(target_text)

    if not target_raw and not target_norm:
        return None

    hinted_by_word_index = _word_index_hint_to_list_index(words, row)
    if hinted_by_word_index is not None and 0 <= hinted_by_word_index < len(words):
        hinted_text = _get_word_match_text(words[hinted_by_word_index])
        hinted_raw = _compact_mushaf_word_token(hinted_text)
        hinted_norm = _normalize_mushaf_word_token(hinted_text)

        if (target_raw and hinted_raw == target_raw) or (target_norm and hinted_norm == target_norm):
            return hinted_by_word_index

    ranges = [range(search_start, len(words)), range(0, search_start)]

    if target_raw:
        for rng in ranges:
            for idx in rng:
                candidate = _compact_mushaf_word_token(_get_word_match_text(words[idx]))
                if candidate == target_raw:
                    return idx

    if target_norm:
        for rng in ranges:
            for idx in rng:
                candidate = _normalize_mushaf_word_token(_get_word_match_text(words[idx]))
                if candidate == target_norm:
                    return idx

    return None


def _glyph_row_score(arabic_word):
    """Prefer full-word glyph rows over standalone marker rows for duplicate word positions."""
    token = ''.join(ch for ch in (arabic_word or '') if not ch.isspace())
    if not token:
        return 0

    if len(token) == 1:
        char = token[0]
        if is_waqf_like_char(char, 'indopak_nastaleeq'):
            return 0
        if ARABIC_INDIC_DIGIT_PATTERN.match(char):
            return 1
        return 1

    return 2


@lru_cache(maxsize=1024)
def _get_shamarly_page_ayah_word_bounds(page_number):
    """Return (first_ayah_word_id, last_ayah_word_id) for a page."""
    try:
        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        layout_cursor.execute(
            '''
            SELECT MIN(first_word_id) AS first_word_id, MAX(last_word_id) AS last_word_id
            FROM pages
            WHERE page_number = ?
              AND line_type = 'ayah'
              AND first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ''',
            (int(page_number),)
        )
        row = layout_cursor.fetchone()
        layout_conn.close()
        if not row or row['first_word_id'] is None or row['last_word_id'] is None:
            return (None, None)
        return (int(row['first_word_id']), int(row['last_word_id']))
    except Exception:
        return (None, None)


@lru_cache(maxsize=1024)
def _get_shamarly_font_supported_codepoints(font_name):
    """Return supported unicode codepoints for a Shemrly font file.

    Returns:
        set[int] when loaded successfully,
        None when the font file does not exist or cannot be parsed.
    """
    font_path = os.path.join(os.path.dirname(__file__), 'static', f'{font_name}.ttf')
    if not os.path.exists(font_path):
        return None

    try:
        from fontTools.ttLib import TTFont
        font = TTFont(font_path)
        codepoints = set()
        for table in font['cmap'].tables:
            codepoints.update(table.cmap.keys())
        return codepoints
    except Exception:
        return None


@lru_cache(maxsize=1024)
def _get_shamarly_page_word_codepoint_map(page_number):
    """Return {word_position: codepoint} map for a Shemrly page using glyph DB rows.

    This preserves page-specific skips/markers in codepoint ordering that cannot be
    reconstructed by a simple contiguous local-index formula.
    """
    first_word_id, last_word_id = _get_shamarly_page_ayah_word_bounds(page_number)
    if first_word_id is None or last_word_id is None:
        return {}

    font_name = f"Shemrly-Page{int(page_number):03d}"
    supported_codepoints = _get_shamarly_font_supported_codepoints(font_name)

    try:
        glyph_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'glyph_mappings.db'))
        glyph_conn.row_factory = sqlite3.Row
        glyph_cursor = glyph_conn.cursor()
        glyph_cursor.execute(
            '''
            SELECT word_position, codepoint, arabic_word
            FROM glyph_mappings
            WHERE word_position BETWEEN ? AND ?
              AND font_name LIKE 'Elgharib-A%'
            ORDER BY word_position ASC, id ASC
            ''',
            (int(first_word_id), int(last_word_id))
        )
        rows = glyph_cursor.fetchall()
        glyph_conn.close()
    except Exception:
        return {}

    codepoint_map = {}
    score_map = {}
    for row in rows:
        codepoint = int(row['codepoint'])
        if supported_codepoints is not None and codepoint not in supported_codepoints:
            continue

        word_pos = int(row['word_position'])
        score = _glyph_row_score(row['arabic_word'])
        if score > score_map.get(word_pos, -1):
            codepoint_map[word_pos] = codepoint
            score_map[word_pos] = score

    return codepoint_map


def _get_shamarly_glyph_char_for_word(page_number, word_position):
    """Map global word position to Shemrly page-local glyph codepoint."""
    first_word_id, last_word_id = _get_shamarly_page_ayah_word_bounds(page_number)
    if first_word_id is None or last_word_id is None:
        return None

    if word_position < first_word_id or word_position > last_word_id:
        return None

    local_index = int(word_position) - first_word_id + 1
    if local_index <= 0:
        return None

    codepoint = SHEMRLY_CODEPOINT_BASE + local_index
    font_name = f"Shemrly-Page{int(page_number):03d}"
    supported_codepoints = _get_shamarly_font_supported_codepoints(font_name)

    # Prefer native page-local indexing when the target codepoint exists in the page font.
    if supported_codepoints is None or codepoint in supported_codepoints:
        return chr(codepoint)

    # Some pages have intentional gaps in local sequence (e.g. marker-only slots); use DB fallback.
    db_codepoint_map = _get_shamarly_page_word_codepoint_map(page_number)
    if int(word_position) in db_codepoint_map:
        return chr(db_codepoint_map[int(word_position)])

    return None


def _get_preferred_legacy_glyph_font_for_range(min_word_id, max_word_id):
    """Pick the dominant legacy Elgharib font for a word range.

    Some ranges span multiple legacy font buckets; using a single dominant bucket
    avoids mixing incompatible glyph codepoint sets in one rendered page.
    """
    if min_word_id is None or max_word_id is None:
        return None

    try:
        glyph_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'glyph_mappings.db'))
        glyph_conn.row_factory = sqlite3.Row
        glyph_cursor = glyph_conn.cursor()
        glyph_cursor.execute(
            '''
            SELECT font_name, COUNT(*) AS cnt
            FROM glyph_mappings
            WHERE word_position BETWEEN ? AND ?
              AND font_name LIKE 'Elgharib-A%'
            GROUP BY font_name
            ORDER BY cnt DESC, font_name ASC
            LIMIT 1
            ''',
            (min_word_id, max_word_id)
        )
        row = glyph_cursor.fetchone()
        glyph_conn.close()
        return row['font_name'] if row else None
    except Exception:
        return None


def _build_page_waqf_map(page_word_rows, mushaf_version):
    versions = mushaf_version if isinstance(mushaf_version, list) else ([mushaf_version] if mushaf_version else [])
    versions = [v for v in versions if v]
    if not versions or not page_word_rows:
        return {}

    grouped = defaultdict(list)
    for row in page_word_rows:
        grouped[(row['surah'], row['ayah'])].append(row)

    # Returns {word_index: [{symbols, version}, ...]} — keep per-version entries so
    # the frontend can render each with the correct font/colour (Warsh vs Hafs etc.)
    waqf_map = {}
    for (surah_number, ayah_number), words in grouped.items():
        mushaf_rows = get_mushaf_waqf_symbols(surah_number, ayah_number, versions)
        if not mushaf_rows:
            continue

        search_start = 0
        for row in mushaf_rows:
            matched_index = _find_mushaf_row_match_index(words, row, search_start)
            if matched_index is None:
                continue

            search_start = matched_index + 1
            word_index = words[matched_index]['word_index']
            symbol = (row.get('symbols') or '').strip()
            if not symbol:
                continue

            entry = {'symbols': symbol, 'version': row.get('version', '')}
            if word_index in waqf_map:
                # Avoid exact duplicates (same symbol + version)
                if entry not in waqf_map[word_index]:
                    waqf_map[word_index].append(entry)
            else:
                waqf_map[word_index] = [entry]

    return waqf_map


def _build_shamarly_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    # Track every sqlite3 connection opened in this function so an exception
    # mid-flight (rather than a clean return) still closes them. sqlite3
    # .close() is idempotent — the existing explicit closes below are kept.
    _open_conns = []
    def _track(c):
        _open_conns.append(c)
        return c
    try:
        return _build_shamarly_page_payload_impl(
            page_number, focus_surah, focus_ayah, mushaf_version, _track
        )
    finally:
        for c in _open_conns:
            try:
                c.close()
            except Exception:
                pass


def _build_shamarly_page_payload_impl(page_number, focus_surah, focus_ayah, mushaf_version, _track):
    layout_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'mushaf_layout_inferred.db')))
    layout_conn.row_factory = sqlite3.Row
    layout_cursor = layout_conn.cursor()

    layout_cursor.execute(
        '''
        SELECT page_number, line_number, line_type, is_centered, first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number ASC
        ''',
        (page_number,)
    )
    lines = [dict(row) for row in layout_cursor.fetchall()]
    layout_conn.close()

    if not lines:
        return None

    effective_page = max(1, int(page_number))
    font_name = f"Shemrly-Page{effective_page:03d}"

    word_ranges = [
        (line.get('first_word_id'), line.get('last_word_id'))
        for line in lines
        if line.get('first_word_id') is not None and line.get('last_word_id') is not None
    ]
    min_word_id = min((rng[0] for rng in word_ranges), default=None)
    max_word_id = max((rng[1] for rng in word_ranges), default=None)
    preferred_legacy_font = _get_preferred_legacy_glyph_font_for_range(min_word_id, max_word_id)
    shemrly_font_available = _get_shamarly_font_supported_codepoints(font_name) is not None

    glyph_by_word_pos = {}
    glyph_score_by_word_pos = {}
    if min_word_id is not None and max_word_id is not None:
        if shemrly_font_available:
            for word_pos in range(int(min_word_id), int(max_word_id) + 1):
                glyph_char = _get_shamarly_glyph_char_for_word(effective_page, word_pos)
                if glyph_char:
                    glyph_by_word_pos[word_pos] = glyph_char
        else:
            glyph_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'glyph_mappings.db')))
            glyph_conn.row_factory = sqlite3.Row
            glyph_cursor = glyph_conn.cursor()
            if preferred_legacy_font:
                glyph_cursor.execute(
                    '''
                    SELECT word_position, codepoint, arabic_word
                    FROM glyph_mappings
                    WHERE word_position BETWEEN ? AND ?
                      AND font_name = ?
                    ORDER BY word_position ASC, id ASC
                    ''',
                    (min_word_id, max_word_id, preferred_legacy_font)
                )
            else:
                glyph_cursor.execute(
                    '''
                    SELECT word_position, codepoint, arabic_word
                    FROM glyph_mappings
                    WHERE word_position BETWEEN ? AND ?
                    ORDER BY word_position ASC, id ASC
                    ''',
                    (min_word_id, max_word_id)
                )
            for row in glyph_cursor.fetchall():
                word_pos = row['word_position']
                score = _glyph_row_score(row['arabic_word'])
                if score > glyph_score_by_word_pos.get(word_pos, -1):
                    glyph_by_word_pos[word_pos] = chr(row['codepoint'])
                    glyph_score_by_word_pos[word_pos] = score
            glyph_conn.close()

    focus_word_range = None
    if focus_surah is not None and focus_ayah is not None:
        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db')))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT MIN(word_index) AS first_word_id, MAX(word_index) AS last_word_id
            FROM words
            WHERE surah = ? AND ayah = ?
            ''',
            (focus_surah, focus_ayah)
        )
        row = words_cursor.fetchone()
        words_conn.close()
        if row and row['first_word_id'] is not None and row['last_word_id'] is not None:
            focus_word_range = (row['first_word_id'], row['last_word_id'])

    page_word_rows = []
    page_word_by_index = {}
    if min_word_id is not None and max_word_id is not None:
        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db')))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT word_index, surah, ayah, text, text_original
            FROM words
            WHERE word_index BETWEEN ? AND ?
            ORDER BY word_index ASC
            ''',
            (min_word_id, max_word_id)
        )
        for row in words_cursor.fetchall():
            item = {
                'word_index': int(row['word_index']),
                'surah': int(row['surah']),
                'ayah': int(row['ayah']),
                'text': row['text'],
                'text_original': row['text_original']
            }
            page_word_rows.append(item)
            page_word_by_index[item['word_index']] = item
        words_conn.close()

    waqf_by_word_index = _build_page_waqf_map(page_word_rows, mushaf_version)

    anchor_surah_number = None
    anchor_ayah_number = None
    if page_word_rows:
        first = min(page_word_rows, key=lambda item: item['word_index'])
        anchor_surah_number = first['surah']
        anchor_ayah_number = first['ayah']

    output_lines = []
    for line in lines:
        first_word_id = line.get('first_word_id')
        last_word_id = line.get('last_word_id')
        glyph_text = None
        contains_focus_ayah = False
        line_words = []

        if first_word_id is not None and last_word_id is not None:
            chars = []
            for word_pos in range(first_word_id, last_word_id + 1):
                glyph_char = glyph_by_word_pos.get(word_pos, '')
                fallback_word = page_word_by_index.get(word_pos, {}).get('text') or ''
                rendered_word = glyph_char or fallback_word
                if not rendered_word:
                    continue
                chars.append(rendered_word)
                line_words.append({
                    'word_index': word_pos,
                    'text': rendered_word,
                    'waqf_symbols': waqf_by_word_index.get(word_pos, '')
                })

            if chars:
                glyph_text = ' '.join(chars)

            if focus_word_range:
                focus_first, focus_last = focus_word_range
                contains_focus_ayah = not (last_word_id < focus_first or first_word_id > focus_last)

        output_lines.append({
            'line_number': line['line_number'],
            'line_type': line['line_type'],
            'is_centered': bool(line['is_centered']),
            'surah_number': line['surah_number'],
            'first_word_id': first_word_id,
            'last_word_id': last_word_id,
            'raw_text': line['line_text'],
            'glyph_text': glyph_text,
            'contains_focus_ayah': contains_focus_ayah,
            'words': line_words
        })

    return {
        'page_number': int(page_number),
        'font_name': font_name,
        'glyph_legacy_font': preferred_legacy_font,
        'glyph_mapping_mode': 'shemrly-page-local' if shemrly_font_available else 'legacy-word-position',
        'lines': output_lines,
        'focus_surah': focus_surah,
        'focus_ayah': focus_ayah,
        'anchor_surah_number': anchor_surah_number,
        'anchor_ayah_number': anchor_ayah_number,
        'mushaf_version': (mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or ''))
    }


@app.route('/api/shamarly/page/<int:page_number>', methods=['GET'])
def get_shamarly_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_shamarly_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching Shamarly page {page_number}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/shamarly/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_shamarly_page_by_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        words_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db'))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT MIN(word_index) AS first_word_id, MAX(word_index) AS last_word_id
            FROM words
            WHERE surah = ? AND ayah = ?
            ''',
            (surah_number, ayah_number)
        )
        word_range = words_cursor.fetchone()
        words_conn.close()

        if not word_range or word_range['first_word_id'] is None:
            return jsonify({'error': 'Ayah not found in script DB'}), 404

        first_word_id = word_range['first_word_id']
        last_word_id = word_range['last_word_id']

        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        layout_cursor.execute(
            '''
            SELECT page_number
            FROM pages
            WHERE (first_word_id <= ? AND last_word_id >= ?)
               OR (first_word_id <= ? AND last_word_id >= ?)
               OR (first_word_id >= ? AND last_word_id <= ?)
            ORDER BY page_number ASC, line_number ASC
            LIMIT 1
            ''',
            (last_word_id, first_word_id, first_word_id, last_word_id, first_word_id, last_word_id)
        )
        row = layout_cursor.fetchone()
        layout_conn.close()

        if not row:
            return jsonify({'error': 'Page not found for ayah'}), 404

        page_number = row['page_number']
        payload = _build_shamarly_page_payload(
            page_number,
            focus_surah=surah_number,
            focus_ayah=ayah_number,
            mushaf_version=mushaf_version
        )
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching Shamarly page by ayah {surah_number}:{ayah_number}: {e}")
        return jsonify({"error": str(e)}), 500


def _get_surah_name_ar(surah_number):
    try:
        target = int(surah_number)
    except (TypeError, ValueError):
        return None

    for entry in surahs_data:
        if isinstance(entry, dict) and entry.get('number') == target:
            return entry.get('name')
    return None


@lru_cache(maxsize=1)
def _get_quran_script_layout_offset():
    try:
        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db'))
        cursor = conn.cursor()
        cursor.execute('SELECT MIN(word_index) FROM words')
        min_word_index = cursor.fetchone()[0]
        conn.close()
        if min_word_index is None:
            return 0
        # Layout DB uses 1-based first word while quran_script starts from 3 in this dataset.
        return int(min_word_index) - 1
    except Exception:
        return 0


def _build_digital_khatt_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    if not os.path.exists(DIGITAL_KHATT_LAYOUT_DATABASE):
        return None

    # See _build_shamarly_page_payload for the _track / try/finally rationale.
    _open_conns = []
    def _track(c):
        _open_conns.append(c)
        return c
    try:
        return _build_digital_khatt_page_payload_impl(
            page_number, focus_surah, focus_ayah, mushaf_version, _track
        )
    finally:
        for c in _open_conns:
            try:
                c.close()
            except Exception:
                pass


def _build_digital_khatt_page_payload_impl(page_number, focus_surah, focus_ayah, mushaf_version, _track):
    layout_conn = _track(sqlite3.connect(DIGITAL_KHATT_LAYOUT_DATABASE))
    layout_conn.row_factory = sqlite3.Row
    layout_cursor = layout_conn.cursor()
    layout_cursor.execute(
        '''
        SELECT page_number, line_number, line_type, is_centered, first_word_id, last_word_id, surah_number, total_advance, x_offset
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number ASC
        ''',
        (page_number,)
    )
    lines = [dict(row) for row in layout_cursor.fetchall()]

    layout_cursor.execute('SELECT font_name, number_of_pages, lines_per_page, name FROM info LIMIT 1')
    info_row = layout_cursor.fetchone()
    layout_conn.close()

    if not lines:
        return None

    layout_offset = _get_quran_script_layout_offset()

    focus_layout_word_range = None
    if focus_surah is not None and focus_ayah is not None:
        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db')))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT MIN(word_index) AS first_word_id, MAX(word_index) AS last_word_id
            FROM words
            WHERE surah = ? AND ayah = ?
            ''',
            (focus_surah, focus_ayah)
        )
        focus_row = words_cursor.fetchone()
        words_conn.close()
        if focus_row and focus_row['first_word_id'] is not None and focus_row['last_word_id'] is not None:
            focus_layout_word_range = (
                int(focus_row['first_word_id']) - layout_offset,
                int(focus_row['last_word_id']) - layout_offset
            )

    def to_int_or_none(value):
        try:
            if value is None or str(value).strip() == '':
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    ranged_lines = []
    for line in lines:
        first_word = to_int_or_none(line.get('first_word_id'))
        last_word = to_int_or_none(line.get('last_word_id'))
        if first_word is None or last_word is None:
            continue
        ranged_lines.append((first_word, last_word))

    min_layout_word = min((pair[0] for pair in ranged_lines), default=None)
    max_layout_word = max((pair[1] for pair in ranged_lines), default=None)

    script_word_map = {}
    page_word_rows = []
    page_word_by_index = {}
    if min_layout_word is not None and max_layout_word is not None:
        script_min = min_layout_word + layout_offset
        script_max = max_layout_word + layout_offset

        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db')))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT word_index, surah, ayah, text, text_original
            FROM words
            WHERE word_index BETWEEN ? AND ?
            ORDER BY word_index ASC
            ''',
            (script_min, script_max)
        )
        for row in words_cursor.fetchall():
            script_index = int(row['word_index'])
            script_word_map[script_index] = row['text_original'] or row['text']
            item = {
                'word_index': script_index,
                'surah': int(row['surah']),
                'ayah': int(row['ayah']),
                'text': row['text'],
                'text_original': row['text_original']
            }
            page_word_rows.append(item)
            page_word_by_index[item['word_index']] = item
        words_conn.close()

    waqf_by_word_index = _build_page_waqf_map(page_word_rows, mushaf_version)

    anchor_surah_number = None
    anchor_ayah_number = None
    if page_word_rows:
        first = min(page_word_rows, key=lambda item: item['word_index'])
        anchor_surah_number = first['surah']
        anchor_ayah_number = first['ayah']

    bismillah = 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ'
    output_lines = []
    for line in lines:
        first_word_id = to_int_or_none(line.get('first_word_id'))
        last_word_id = to_int_or_none(line.get('last_word_id'))
        line_type = line.get('line_type')
        line_surah = line.get('surah_number')

        display_text = ''
        line_words = []
        if first_word_id is not None and last_word_id is not None:
            script_range = range(first_word_id + layout_offset, last_word_id + layout_offset + 1)
            words = []
            for word_index in script_range:
                word_text = script_word_map.get(word_index, '')
                if not word_text:
                    continue
                words.append(word_text)
                line_words.append({
                    'word_index': word_index,
                    'text': word_text,
                    'waqf_symbols': waqf_by_word_index.get(word_index, '')
                })
            display_text = ' '.join(words)
        elif line_type == 'surah_name':
            surah_name = _get_surah_name_ar(line_surah)
            display_text = f"سورة {surah_name}" if surah_name else ''
        elif line_type == 'basmallah':
            display_text = bismillah

        contains_focus_ayah = False
        if focus_layout_word_range and first_word_id is not None and last_word_id is not None:
            focus_first, focus_last = focus_layout_word_range
            contains_focus_ayah = not (last_word_id < focus_first or first_word_id > focus_last)

        output_lines.append({
            'line_number': int(line['line_number']),
            'line_type': line_type,
            'is_centered': bool(line.get('is_centered')),
            'surah_number': line_surah,
            'first_word_id': first_word_id,
            'last_word_id': last_word_id,
            'display_text': display_text,
            'contains_focus_ayah': contains_focus_ayah,
            'words': line_words,
            'total_advance': line.get('total_advance'),
            'x_offset': line.get('x_offset', 0)
        })

    # Page content width: median total_advance of justified lines on this page,
    # used by the frontend to compute per-line scale factors for justification.
    page_content_width = None
    justified_advances = [
        l.get('total_advance') for l in output_lines
        if l.get('total_advance') and not l.get('x_offset')
    ]
    if justified_advances:
        justified_advances.sort()
        mid = len(justified_advances) // 2
        page_content_width = justified_advances[mid]

    return {
        'source': 'digital_khatt',
        'page_number': int(page_number),
        'font_name': (info_row['font_name'] if info_row and 'font_name' in info_row.keys() else 'Digital Khatt'),
        'layout_name': (info_row['name'] if info_row and 'name' in info_row.keys() else 'Digital Khatt layout'),
        'lines_per_page': (int(info_row['lines_per_page']) if info_row and info_row['lines_per_page'] else None),
        'page_content_width': page_content_width,
        'focus_surah': focus_surah,
        'focus_ayah': focus_ayah,
        'lines': output_lines,
        'anchor_surah_number': anchor_surah_number,
        'anchor_ayah_number': anchor_ayah_number,
        'mushaf_version': (mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or ''))
    }


@app.route('/api/digital-khatt/page/<int:page_number>', methods=['GET'])
def get_digital_khatt_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_digital_khatt_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching Digital Khatt page {page_number}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/digital-khatt/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_digital_khatt_page_by_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        if not os.path.exists(DIGITAL_KHATT_LAYOUT_DATABASE):
            return jsonify({'error': 'Digital Khatt layout DB not found'}), 404

        layout_offset = _get_quran_script_layout_offset()

        words_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'QUL_data', 'quran_script.db'))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT MIN(word_index) AS first_word_id, MAX(word_index) AS last_word_id
            FROM words
            WHERE surah = ? AND ayah = ?
            ''',
            (surah_number, ayah_number)
        )
        word_range = words_cursor.fetchone()
        words_conn.close()

        if not word_range or word_range['first_word_id'] is None:
            return jsonify({'error': 'Ayah not found in script DB'}), 404

        layout_first = int(word_range['first_word_id']) - layout_offset
        layout_last = int(word_range['last_word_id']) - layout_offset

        layout_conn = sqlite3.connect(DIGITAL_KHATT_LAYOUT_DATABASE)
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        layout_cursor.execute(
            '''
            SELECT page_number
            FROM pages
            WHERE (first_word_id <= ? AND last_word_id >= ?)
               OR (first_word_id <= ? AND last_word_id >= ?)
               OR (first_word_id >= ? AND last_word_id <= ?)
            ORDER BY page_number ASC, line_number ASC
            LIMIT 1
            ''',
            (layout_last, layout_first, layout_first, layout_last, layout_first, layout_last)
        )
        row = layout_cursor.fetchone()
        layout_conn.close()

        if not row:
            return jsonify({'error': 'Page not found for ayah'}), 404

        payload = _build_digital_khatt_page_payload(
            row['page_number'],
            focus_surah=surah_number,
            focus_ayah=ayah_number,
            mushaf_version=mushaf_version
        )
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching Digital Khatt page by ayah {surah_number}:{ayah_number}: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
