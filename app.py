from flask import Flask, jsonify, render_template, request, g, Response, redirect
import json
import sqlite3
import os
import logging
import re
import threading
from collections import defaultdict, OrderedDict, Counter
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
        # cdn.jsdelivr.net + blob: → onnxruntime-web (recitation ASR); wasm needs 'unsafe-eval'/'wasm-unsafe-eval'.
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://vercel.live https://va.vercel-scripts.com; "
        "worker-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # *.mp3quran.net → the memorize/reciter audio (server7/8/10/13/…); jsdelivr CDN allowed for ort wasm fetch.
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com https://*.mp3quran.net https://download.tvquran.com https://download.quranicaudio.com; "
        # huggingface.co (+ LFS redirect hosts) → ASR model fallback when /static can't serve the 132MB file.
        "connect-src 'self' https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co https://*.hf.co https://cdn-lfs.huggingface.co https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com;"
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

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'word_name.db')
WAQF_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'waqf_symbols.db')
MUSHAF_WAQF_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'mushaf_waqf.db')
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
# "New Madinah" source now uses the QPC v4 (1441/tajweed) 15-line layout — same
# 1..83668 word numbering as the older digital-khatt layout but with the proper
# QPC v4 line breaks. (Schema has no total_advance/x_offset columns.)
DIGITAL_KHATT_LAYOUT_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'qpc-v4-15-lines.db')
QPC_V1_LAYOUT_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'qpc-v1-15-lines.db')
# Local tajweed-coloring data, built offline by pipeline/build_tajweed_local.py
# from cpfair/quran-tajweed (CC-BY 4.0). Replaces the quran.com network call.
TAJWEED_DATABASE = os.path.join(_BASE_DIR, 'data', 'tajweed_local.db')

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
# Local files now live under data/quran_text/
digital_khatt_data = _load_json_cdn_or_local(
    'Digital_Khatt_Aya_Space.json', 'data/quran_text/Digital_Khatt_Aya_Space.json'
)
qpc_hafs_data = _load_json_cdn_or_local(
    'QPC Hafs.json', 'data/quran_text/QPC Hafs.json'
)
indopak_nastaleeq_data = _load_json_cdn_or_local(
    'Indopak Nastaleeq_Waqf.json', 'data/quran_text/Indopak Nastaleeq_Waqf.json'
)
indopak_nastaleeq_2_data = _load_json_cdn_or_local(
    'indopak-nastaleeq 2.json', 'data/quran_text/indopak-nastaleeq 2.json'
)
transliteration_data = _load_json_cdn_or_local(
    'Transliteration.json', 'data/quran_text/Transliteration.json'
)
surahs_data = _load_json_cdn_or_local('surahs.json', 'data/quran_text/surahs.json')
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
# Local files now live under data/word_timestamps/
reciters = {
    "AbdulBaset AbdulSamad (Mujawwad)": ("AbdulBaset AbdulSamad Recitation.json",
                                         "data/word_timestamps/AbdulBaset AbdulSamad Recitation.json"),
    "AbdulBaset AbdulSamad (Murattal)": ("ayah-recitation-abdul-basit-abdul-samad-murattal-hafs-950.json",
                                         "data/word_timestamps/ayah-recitation-abdul-basit-abdul-samad-murattal-hafs-950.json"),
    "Mohamed al-Minshawi (Mujawwad)": ("Mohamed Siddiq al-Minshawi Recitation.json",
                              "data/word_timestamps/Mohamed Siddiq al-Minshawi Recitation.json"),
    "Mohamed al-Minshawi (Murattal)": ("ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json",
                              "data/word_timestamps/ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json"),
    "Mahmoud Khalil al-Husary (Mujawwad)": ("ayah-recitation-mahmoud-khalil-al-husary-mujawwad-hafs-956.json",
                                           "data/word_timestamps/ayah-recitation-mahmoud-khalil-al-husary-mujawwad-hafs-956.json"),
    "Mahmoud Khalil al-Husary (Murattal)": ("ayah-recitation-mahmoud-khalil-al-husary-murattal-hafs-957.json",
                                            "data/word_timestamps/ayah-recitation-mahmoud-khalil-al-husary-murattal-hafs-957.json"),
    "Mahmoud Khalil al-Husary (Muallim)": ("mahmoud-khalil-al-husary-muallm-hafs.json",
                                           "data/word_timestamps/mahmoud-khalil-al-husary-muallm-hafs.json"),
    "Ibrahim Al-Akhdar":        ("ibrahim-al-akhdar.json",
                                  "data/word_timestamps/ibrahim-al-akhdar.json"),
    "Ayman Rushdi Suwaid":       ("ayman-rushdi-suwaid.json",
                                  "data/word_timestamps/ayman-rushdi-suwaid.json"),
    "Mahmoud Ali Al-Banna":      ("mahmoud-ali-al-banna.json",
                                  "data/word_timestamps/mahmoud-ali-al-banna.json"),
    "Mustafa Ismaeel":           ("mustafa-ismaeel.json",
                                  "data/word_timestamps/mustafa-ismaeel.json"),
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

    # ── Discretionary stops only ─────────────────────────────────────────────
    # Exclude the verse-end stop (رأس الآية): every reciter stops there and it is
    # trivially valid in every mushaf, so counting it inflates "صحة وقفاته". This
    # also handles the back-up-and-repeat case (e.g. Suwaid at 12:27, who stops at
    # فكذبت then re-reads from it to the verse end) — the resumed run terminates at
    # رأس الآية and must not be counted as a second discretionary waqf.
    # (reciter-compare already drops the verse-end for the same reason.)
    mid_pause_segs = [seg for seg in pause_segs if seg['end_word'] != verse_end_word]
    pause_count = len(mid_pause_segs)

    # Coverage still credits every real stop (including the verse-end) so a mark on
    # the final word can be matched.
    pause_end_words = {seg['end_word'] for seg in pause_segs}

    matches = {}
    for ver in versions:
        # ── Precision: how many of the reciter's discretionary stops are valid ─
        matched = 0
        for seg in mid_pause_segs:
            waqf_entries = _get_waqf_at_boundary(
                surah_number, ayah_number, seg['end_word'], [ver]
            )
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
            # No discretionary stops → precision is vacuously satisfied (100%);
            # the frontend renders this case as "no optional stops".
            'score': round(matched / pause_count * 100) if pause_count > 0 else 100,
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

    def _match_positions(a_list, b_list):
        """1-to-1 match of each position in a_list to a position in b_list within
        ±1 word. Each b-position can satisfy only ONE a-position, so adjacent
        stops can't be double-counted. Exact matches are claimed first (globally)
        so a ±1 neighbour never steals a b-position an exact match needs.
        Returns (matched_count, set_of_matched_a_positions)."""
        b_sorted = sorted(b_list)
        b_used = [False] * len(b_sorted)
        matched_a = set()
        a_sorted = sorted(a_list)
        remaining = []
        for w in a_sorted:  # pass 1: exact
            j = next((i for i, bw in enumerate(b_sorted) if not b_used[i] and bw == w), None)
            if j is not None:
                b_used[j] = True
                matched_a.add(w)
            else:
                remaining.append(w)
        for w in remaining:  # pass 2: ±1
            j = next((i for i, bw in enumerate(b_sorted) if not b_used[i] and abs(bw - w) <= 1), None)
            if j is not None:
                b_used[j] = True
                matched_a.add(w)
        return len(matched_a), matched_a

    comparisons = {}
    # Accumulate every other reciter's mid-verse pause positions so we can tell
    # which of the subject's stops are his alone (انفرد القارئ بهذا الوقف).
    other_mid_positions = set()
    other_reciter_count = 0
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
        a_list = [s['end_word'] for s in a_segs]
        b_list = [s['end_word'] for s in b_segs]
        a_total, b_total = len(a_list), len(b_list)

        other_reciter_count += 1
        other_mid_positions.update(b_list)

        a_matched, a_matched_set = _match_positions(a_list, b_list)
        b_matched, b_matched_set = _match_positions(b_list, a_list)
        # Empty side → fraction is vacuously 1.0 (nothing to disagree on); the
        # similarity below collapses to 0 via the harmonic mean, and the frontend
        # labels one-sided cases as "can't evaluate".
        a_frac = (a_matched / a_total) if a_total else 1.0
        b_frac = (b_matched / b_total) if b_total else 1.0

        # Unmatched segments for the diff view — same greedy matching as the score,
        # so the diff list length always agrees with (total - matched).
        only_in_a = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in a_segs
            if s['end_word'] not in a_matched_set
        ]
        only_in_b = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in b_segs
            if s['end_word'] not in b_matched_set
        ]

        comparisons[other_reciter] = {
            'a_to_b_score':   round(a_frac * 100),
            'a_to_b_matched': a_matched,
            'a_to_b_total':   a_total,
            'b_to_a_score':   round(b_frac * 100),
            'b_to_a_matched': b_matched,
            'b_to_a_total':   b_total,
            # Combined similarity: harmonic mean (F1) of the two directions.
            # Only meaningful when both reciters have mid-verse stops.
            'comparable': a_total > 0 and b_total > 0,
            'similarity': round(
                2 * a_frac * b_frac / (a_frac + b_frac) * 100
                if (a_frac + b_frac) > 0 else 0
            ),
            'diff': {'only_in_a': only_in_a, 'only_in_b': only_in_b},
        }

    # ── Solo waqfs ───────────────────────────────────────────────────────────
    # Positions where the subject stopped but NO other reciter did (within ±1).
    # Only clean stop-and-continue waqfs qualify: mid-verse, the segment itself did
    # not back up, and the reciter resumed forward from the stop (no repetition).
    unique_pauses = []
    if other_reciter_count > 0:
        high_water = 0
        for k, seg in enumerate(subject_pauses):
            end_w = seg['end_word']
            backed_up = seg['start_word'] < high_water
            if end_w > high_water:
                high_water = end_w
            if end_w == verse_end_word or backed_up:
                continue
            nxt = subject_pauses[k + 1] if k + 1 < len(subject_pauses) else None
            if nxt is None or nxt['start_word'] < end_w:
                continue  # reciter backed up after this stop → it was repeated
            if not any((end_w + d) in other_mid_positions for d in (-1, 0, 1)):
                unique_pauses.append(end_w)

    return jsonify({
        'has_data': bool(comparisons),
        'subject_mid_count': len(subject_mid_segs),
        'other_reciter_count': other_reciter_count,
        'unique_pauses': unique_pauses,
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

@app.route('/api/tajweed/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_tajweed(surah_number, ayah_number):
    """Return tajweed-annotated HTML for one ayah from local data.

    Served from data/tajweed_local.db (built offline by
    pipeline/build_tajweed_local.py from cpfair/quran-tajweed, CC-BY 4.0). The
    HTML uses the same `<tajweed class="…">` shape the front-end already parses,
    so this is a drop-in replacement for the former quran.com call.
    """
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in _tajweed_cache:
        resp = jsonify(_tajweed_cache[verse_key])
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    try:
        conn = sqlite3.connect(TAJWEED_DATABASE)
        try:
            row = conn.execute(
                "SELECT html FROM tajweed WHERE verse_key = ?", (verse_key,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        app.logger.error(f"Tajweed DB error for {verse_key}: {e}")
        return jsonify({"error": "Failed to load tajweed data"}), 502

    if row is None:
        return jsonify({"error": "Verse not found"}), 404

    _tajweed_cache[verse_key] = {"html": row[0]}
    resp = jsonify(_tajweed_cache[verse_key])
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


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


@app.route('/memorize')
def memorize():
    """Page-by-page visual memorization on the Digital Khatt (Madinah) mushaf
    layout, with synced Husary audio. See templates/mushaf_memorize.html."""
    return render_template('mushaf_memorize.html', enable_vercel_analytics=_IS_SERVERLESS)


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


# ── Memorization mode (Circular Segmented Repetition) ───────────────────────────
# Uses the per-surah Husary timestamps (mahmoud_khalil_al_husary_mp3quran). Word
# timestamps are surah-absolute (one MP3 per surah), so any [start,end] range —
# a single word, a natural phrase, a verse, or a cumulative run of verses — maps
# to a direct seek in the surah audio. Phrases are derived from the silence gaps
# in the alignment itself, i.e. where the reciter actually paused.
_MEMORIZATION_DIR = os.path.join(_BASE_DIR, 'reciters', 'mahmoud_khalil_al_husary_mp3quran')
_MEMORIZATION_AUDIO_TMPL = 'https://server13.mp3quran.net/husr/{surah:03d}.mp3'

# ── Memorization reciters ────────────────────────────────────────────────
# Each reciter needs a QUL `word_timestamps.json.gz` (from
# Wider-Community/quranic-universal-audio — the same format as Husary above) in
# its `dir`, plus a per-surah audio URL template. Reciters whose data file is
# present are offered in the UI; the rest are ignored until imported.
# To add one: drop <reciter>/word_timestamps.json.gz under reciters/ and add an
# entry here with its mp3 URL (see scripts/import_qul_reciters.py).
MEMORIZATION_RECITERS = {
    'husary': {
        'name_ar': 'محمود خليل الحصري', 'name_en': 'Mahmoud Khalil al-Husary',
        'dir': _MEMORIZATION_DIR,
        'audio_tmpl': _MEMORIZATION_AUDIO_TMPL,
    },
    'ahmed_amer': {
        'name_ar': 'أحمد محمد عامر', 'name_en': 'Ahmed Mohamed Amer',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_amer_tvquran'),
        'audio_tmpl': 'https://download.tvquran.com/download/recitations/197/143/{surah:03d}.mp3',
    },
    'minshawi': {
        'name_ar': 'محمد صديق المنشاوي', 'name_en': 'Mohamed Siddiq al-Minshawi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'minshawi_murattal_qul'),
        'audio_tmpl': 'https://server10.mp3quran.net/minsh/{surah:03d}.mp3',
    },
    'abdulbasit': {
        'name_ar': 'عبد الباسط عبد الصمد', 'name_en': 'AbdulBaset AbdulSamad',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'abdulbasit_murattal_qul'),
        'audio_tmpl': 'https://server7.mp3quran.net/basit/{surah:03d}.mp3',
    },
    'afasy': {
        'name_ar': 'مشاري راشد العفاسي', 'name_en': 'Mishary Rashid al-Afasy',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'afasy_qul'),
        'audio_tmpl': 'https://server8.mp3quran.net/afs/{surah:03d}.mp3',
    },
    'banna': {
        'name_ar': 'محمود علي البنا', 'name_en': 'Mahmoud Ali Al-Banna',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mahmoud_ali_al_banna_qdc'),
        # QUL v1.1.0 timestamps were aligned to these QuranicAudio per-surah files,
        # so use the same source (CBR 128 → accurate seeking, supports HTTP range).
        'audio_tmpl': 'https://download.quranicaudio.com/quran/mahmood_ali_albana/{surah:03d}.mp3',
    },
    'maher': {
        'name_ar': 'ماهر المعيقلي', 'name_en': 'Maher Al-Muaiqly',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'maher_al_muaiqly_qdc'),
        'audio_tmpl': 'https://download.quranicaudio.com/quran/maher_almu3aiqly/year1440/{surah:03d}.mp3',
    },
    'shuraim': {
        'name_ar': 'سعود الشريم', 'name_en': 'Saud Al-Shuraim',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'saud_al_shuraim_mp3quran'),
        'audio_tmpl': 'https://server7.mp3quran.net/shur/{surah:03d}.mp3',
    },
    'qatami': {
        'name_ar': 'ناصر القطامي', 'name_en': 'Nasser Al-Qatami',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'nasser_al_qatami_mp3quran'),
        'audio_tmpl': 'https://server6.mp3quran.net/qtm/{surah:03d}.mp3',
    },
    'burhaji': {
        'name_ar': 'محمد برهجي', 'name_en': 'Mohammed Burhaji',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_burhaji_yt'),
        'audio_tmpl': None,  # YouTube source — no streamable per-surah MP3
    },
    # Abdullah Al-Buaijan (عبد الله البعيجان) is in QUL v1.1.0 but its audio is a
    # 2025 YouTube recording: surahs 3–114 are only YouTube video URLs (no
    # streamable per-surah MP3), so the timestamps can't drive seek-based playback
    # here. Excluded until an aligned per-surah MP3 source exists.
}
_DEFAULT_MEMO_RECITER = 'husary'

def _memo_reciter_cfg(reciter_id):
    return MEMORIZATION_RECITERS.get(reciter_id) or MEMORIZATION_RECITERS[_DEFAULT_MEMO_RECITER]

def _memo_reciter_installed(reciter_id):
    cfg = MEMORIZATION_RECITERS.get(reciter_id)
    if not cfg or not cfg.get('audio_tmpl'):
        return False
    return bool(os.path.exists(os.path.join(cfg['dir'], 'word_timestamps.json.gz')))
# Husary mushaf-waqf phrase boundaries (sub-verse segments). Used by the
# 'waqf' segmentation mode, snapped to real pauses in the mp3quran audio.
_MEMORIZATION_WAQF_DB = os.path.join(_BASE_DIR, 'reciters', 'husary',
                                     'mahmoud_khalil_al_husari_0_1_positions.db')
_memorization_word_ts = {}      # reciter_id -> word-timestamps dict (cached)
_memorization_waqf_bounds = None
_memorization_lock = threading.Lock()


def _load_memorization_word_ts(reciter_id=_DEFAULT_MEMO_RECITER):
    """Lazy-load + cache a reciter's surah-absolute word timestamps."""
    if reciter_id in _memorization_word_ts:
        return _memorization_word_ts[reciter_id]
    with _memorization_lock:
        if reciter_id not in _memorization_word_ts:
            cfg = _memo_reciter_cfg(reciter_id)
            path = os.path.join(cfg['dir'], 'word_timestamps.json.gz')
            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                _memorization_word_ts[reciter_id] = json.load(fh)
    return _memorization_word_ts[reciter_id]


def _segment_phrases(words, gap_ms):
    """Split a verse's word list into phrases at silence gaps > gap_ms.

    `words` is the source's [[word_index, start_ms, end_ms], ...]. A run of words
    spoken without a meaningful pause becomes one phrase. Returns a list of
    {start, end, first_word, last_word} in milliseconds. Repeated-phrase verses
    (where word_index resets) simply yield extra phrases for the repeated audio,
    which is faithful to what is actually recited.
    """
    phrases = []
    if not words:
        return phrases
    run_start = words[0][1]
    run_first = words[0][0]
    prev_end = words[0][2]
    prev_idx = words[0][0]
    for idx, s, e in words[1:]:
        if s - prev_end > gap_ms:
            phrases.append({'start': run_start, 'end': prev_end,
                            'first_word': run_first, 'last_word': prev_idx})
            run_start = s
            run_first = idx
        prev_end = e
        prev_idx = idx
    phrases.append({'start': run_start, 'end': prev_end,
                    'first_word': run_first, 'last_word': prev_idx})
    return phrases


def _load_waqf_boundaries():
    """Lazy-load per-verse mushaf-waqf phrase boundaries (0-based start_word)
    from the Husary positions DB. Returns {verse_key: [start_word, ...]}."""
    global _memorization_waqf_bounds
    if _memorization_waqf_bounds is not None:
        return _memorization_waqf_bounds
    with _memorization_lock:
        if _memorization_waqf_bounds is None:
            bounds = defaultdict(list)
            try:
                con = sqlite3.connect(_MEMORIZATION_WAQF_DB)
                for s, a, w in con.execute(
                    "SELECT start_sura, start_aya, start_word FROM positions "
                    "WHERE index_type='sura' AND start_sura IS NOT NULL "
                    "AND start_aya IS NOT NULL AND start_word IS NOT NULL"
                ):
                    bounds[f"{int(s)}:{int(a)}"].append(int(w))
                con.close()
                bounds = {vk: sorted(set(v)) for vk, v in bounds.items()}
            except sqlite3.Error as e:
                app.logger.error(f"Waqf boundaries load failed: {e}")
                bounds = {}
            _memorization_waqf_bounds = bounds
    return _memorization_waqf_bounds


def _waqf_aligned_phrases(words, boundaries, snap_floor, snap_window=3):
    """Phrases from mushaf-waqf word boundaries, each snapped to the nearest
    real silence (>= snap_floor ms) within +/- snap_window words so audio cuts
    land on a pause when one is close. If no pause is nearby, the cut stays at
    the waqf boundary (honouring the mark even mid-flow). This absorbs the small
    word-index offsets between the waqf DB and the mp3quran source."""
    n = len(words)
    if not words:
        return []
    starts = [w[1] for w in words]
    ends = [w[2] for w in words]
    cuts = {0}
    for b in boundaries:
        if b <= 0 or b >= n:
            continue
        best_pos, best_gap = b, -1
        lo, hi = max(1, b - snap_window), min(n - 1, b + snap_window)
        for pos in range(lo, hi + 1):
            g = starts[pos] - ends[pos - 1]
            if g >= snap_floor and g > best_gap:
                best_gap, best_pos = g, pos
        cuts.add(best_pos if best_gap >= snap_floor else b)
    cut_list = sorted(cuts)
    phrases = []
    for i, cp in enumerate(cut_list):
        end_pos = (cut_list[i + 1] - 1) if i + 1 < len(cut_list) else n - 1
        if end_pos < cp:
            continue
        phrases.append({'start': words[cp][1], 'end': words[end_pos][2],
                        'first_word': words[cp][0], 'last_word': words[end_pos][0]})
    return phrases


_memorization_breathing_cache = {}


def _forward_waqf_stops(words, gap_ms):
    """Split a reciter's verse pauses into genuine FORWARD waqfs vs. 'pause
    then go back to repeat' artifacts.

    A pause after a phrase is a real waqf only if recitation then continues
    FORWARD. If the next phrase resumes at or before the word we paused on
    (first_word <= last_word), the reciter stopped to re-recite (a correction /
    repeat), not to breathe at a stopping point — so it isn't a waqf. Those
    repeats are returned separately so the UI can show "this reciter repeated
    from word X" instead of mistaking it for a stop.

    Returns (stops, repeats):
      stops   = {word_idx: end_ms_from_verse_start}  (1-based word_idx)
      repeats = [(paused_after_word_idx, resumed_at_word_idx), ...]  (1-based)"""
    stops, repeats = {}, []
    if not words:
        return stops, repeats
    phrases = _segment_phrases(words, gap_ms)
    vstart = words[0][1]
    for i in range(len(phrases) - 1):
        cur, nxt = phrases[i], phrases[i + 1]
        if nxt['first_word'] <= cur['last_word']:
            repeats.append((cur['last_word'], nxt['first_word']))
            continue  # reciter went back to repeat — not a forward waqf
        w = cur['last_word']
        dur = cur['end'] - vstart
        if w not in stops or dur < stops[w]:
            stops[w] = dur
    return stops, repeats


def _build_breathing_guide(surah_number, gap_ms=250):
    """Per-verse 'breathing guide': word positions where at least one of the
    installed reciters makes a real FORWARD pause (a waqf), with how many
    reciters pause there, WHICH reciters do, and the average cumulative
    duration (seconds from verse start) to that point.

    These are real, attested reciter stops — never algorithmically invented,
    and 'pause-to-repeat' artifacts are filtered out (see _forward_waqf_stops)
    — so a memorizer can pick the latest one within their own breath capacity
    and stop there, the way a professional reciter would. Stops only one
    reciter makes (انفرد) are flagged so the user knows they're uncommon."""
    reciter_ids = tuple(sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid)))
    cache_key = (surah_number, gap_ms, reciter_ids)
    if cache_key in _memorization_breathing_cache:
        return _memorization_breathing_cache[cache_key]

    per_reciter_ts = {}
    for rid in reciter_ids:
        try:
            per_reciter_ts[rid] = _load_memorization_word_ts(rid)
        except Exception as e:
            app.logger.error(f"Breathing guide: failed to load {rid}: {e}")

    verses = {}
    ayah = 1
    while True:
        vk = f"{surah_number}:{ayah}"
        present = [(rid, wts[vk]) for rid, wts in per_reciter_ts.items() if vk in wts]
        if not present:
            break
        word_reciters = defaultdict(list)   # word_idx -> [reciter_id, ...] (who pauses)
        word_durs = defaultdict(list)       # word_idx -> [cumulative seconds, ...]
        repeats = []                        # [{reciter_id, from_wpos, to_wpos}]
        verse_durs = []
        for rid, entry in present:
            words = entry[1]
            if not words:
                continue
            verse_durs.append((words[-1][2] - words[0][1]) / 1000.0)
            r_stops, r_repeats = _forward_waqf_stops(words, gap_ms)
            for w, dur_ms in r_stops.items():
                word_reciters[w].append(rid)
                word_durs[w].append(dur_ms / 1000.0)
            for frm, to in r_repeats:
                repeats.append({'reciter_id': rid, 'from_wpos': frm - 1, 'to_wpos': to - 1})

        stops = []
        for word_idx in sorted(word_reciters):
            who = word_reciters[word_idx]
            durs = word_durs[word_idx]
            stops.append({
                'wpos': word_idx - 1,
                'duration': round(sum(durs) / len(durs), 2),
                'reciters': len(who),
                'reciter_ids': who,
                'solo': len(who) == 1,   # انفرد — only this one reciter pauses here
            })
        verses[ayah] = {
            'full_duration': round(sum(verse_durs) / len(verse_durs), 2) if verse_durs else None,
            'reciters_total': len(verse_durs),
            'stops': stops,
            'repeats': repeats,
        }
        ayah += 1

    result = {
        'surah_number': surah_number,
        'gap_ms': gap_ms,
        'reciters': [
            {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')}
            for rid in reciter_ids
        ],
        'verses': verses,
    }
    _memorization_breathing_cache[cache_key] = result
    return result


@app.route('/api/memorization/<int:surah_number>/breathing', methods=['GET'])
def get_memorization_breathing(surah_number):
    """Validated 'breathing guide' for a surah: per verse, word positions where
    at least one installed reciter actually pauses, with consensus count and
    average cumulative duration — so a user with a shorter or longer breath can
    pick a real, attested stopping point instead of guessing where to pause."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    gap_ms = request.args.get('gap', 250, type=int)
    if gap_ms < 0 or gap_ms > 5000:
        gap_ms = 250
    try:
        data = _build_breathing_guide(surah_number, gap_ms)
    except Exception as e:
        app.logger.error(f"Breathing guide failed for surah {surah_number}: {e}")
        return jsonify({"error": "Breathing guide unavailable"}), 503
    if not data['verses']:
        return jsonify({"error": "No memorization data for this surah."}), 404
    return jsonify(data)


_ARABIC_INDIC_DIGITS = set('٠١٢٣٤٥٦٧٨٩')


def _has_arabic_letter(tok):
    """True if a token contains an actual Arabic letter (so it is a recited
    word, not an ornament like the rub‑el‑hizb ۞, a sajda ۩, or an ayah number)."""
    return any(0x0621 <= ord(ch) <= 0x064A or 0x0671 <= ord(ch) <= 0x06D3 for ch in tok)


def _verse_word_texts(verse_key):
    """Per-word text for a verse, aligned to the QUL/reciter word indices
    (words[i] = recited word i+1).

    Uses the qpc_hafs (Uthmanic) text. `text.split()` also yields NON-word
    tokens — the trailing ayah number and ornaments such as the rub‑el‑hizb ۞ —
    which the reciters do NOT count as words, so they must be dropped or the
    reciter stops shift out of alignment with the mushaf marks (e.g. 2:26).

    Returns (text, words, raw_to_wpos) where raw_to_wpos[i] maps a raw split
    index (the basis the printed-mushaf waqf DB token_index uses, which DOES
    count ornaments) to the stripped word index, or None for a dropped token."""
    td = qpc_hafs_data_normalized.get(verse_key)
    text = (td.get('text', '') if isinstance(td, dict) else '') or ''
    words, raw_to_wpos = [], []
    for tok in text.split():
        if _has_arabic_letter(tok):
            raw_to_wpos.append(len(words))
            words.append(tok)
        else:
            raw_to_wpos.append(None)
    return text, words, raw_to_wpos


def _build_verse_waqf_detail(surah, ayah, gap_ms=250):
    """Full per-reciter waqf detail for ONE verse, for the comparison page.

    Returns the verse text/words plus, for every installed reciter, their own
    forward-waqf stops (with each reciter's cumulative time) and repeats, and a
    union view (which reciters align at each stop, and which stops are solo)."""
    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    vk = f"{surah}:{ayah}"
    text, words, raw_to_wpos = _verse_word_texts(vk)

    per_reciter = {}
    union = defaultdict(lambda: {'reciters': [], 'durs': []})
    verse_durs = []
    for rid in reciter_ids:
        try:
            wts = _load_memorization_word_ts(rid)
        except Exception:
            continue
        if vk not in wts:
            continue
        w = wts[vk][1]
        if not w:
            continue
        full = (w[-1][2] - w[0][1]) / 1000.0
        verse_durs.append(full)
        stops, repeats = _forward_waqf_stops(w, gap_ms)
        cfg = MEMORIZATION_RECITERS[rid]
        vstart = w[0][1]
        # The reciter's actual recited phrases IN ORDER (incl. back-ups where
        # they paused then re-read). Lets the UI render each phrase — repeats
        # included — as its own card, faithfully and in recitation order.
        phrases = [
            {'first_wpos': ph['first_word'] - 1, 'last_wpos': ph['last_word'] - 1,
             'start': round((ph['start'] - vstart) / 1000.0, 2),
             'end': round((ph['end'] - vstart) / 1000.0, 2)}
            for ph in _segment_phrases(w, gap_ms)
        ]
        per_reciter[rid] = {
            'name_ar': cfg.get('name_ar', ''),
            'stops': [{'wpos': k - 1, 'time': round(v / 1000.0, 2)} for k, v in sorted(stops.items())],
            'repeats': [{'from_wpos': f - 1, 'to_wpos': t - 1} for f, t in repeats],
            'phrases': phrases,
            'duration': round(full, 2),
            # absolute seek info for in-page segment playback
            'audio_url': cfg['audio_tmpl'].format(surah=surah) if cfg.get('audio_tmpl') else None,
            'verse_start': round(w[0][1] / 1000.0, 3),
        }
        for k, v in stops.items():
            union[k - 1]['reciters'].append(rid)
            union[k - 1]['durs'].append(v / 1000.0)

    union_stops = []
    for wpos in sorted(union):
        u = union[wpos]
        union_stops.append({
            'wpos': wpos,
            'reciters': u['reciters'],
            'count': len(u['reciters']),
            'solo': len(u['reciters']) == 1,
            'avg_duration': round(sum(u['durs']) / len(u['durs']), 2),
        })

    # Reference timeline: a single reciter's cumulative time at EVERY word, so
    # the breath recommendation can size any chosen segment consistently (the
    # per-stop averages mix different reciters). Pick the cleanest reciter —
    # fewest repeats, then pace closest to the group average.
    ref_times, ref_full, ref_reciter = _reference_timeline(per_reciter, words, vk, verse_durs)

    # Mushaf waqf marks (المدينة / الأزهر / الشمرلي): the *prescribed* stops, so
    # we can compare how closely the reciters follow each printed mushaf.
    mushafs = []
    for ver in _WAQF_COMPARE_MUSHAFS:
        marks = []
        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
            ti = r.get('token_index')   # 0-based in the raw-split basis (counts ornaments)
            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                continue
            wpos = raw_to_wpos[ti]
            if wpos is not None:
                marks.append({'wpos': wpos, 'symbol': r['symbols']})
        if marks:
            mushafs.append({'id': ver, 'name': ver, 'marks': marks})

    return {
        'surah': surah,
        'ayah': ayah,
        'verse_key': vk,
        'gap_ms': gap_ms,
        'text': text,
        'words': words,
        'reciters_total': len(per_reciter),
        'full_duration': round(sum(verse_durs) / len(verse_durs), 2) if verse_durs else None,
        'ref_times': ref_times,
        'ref_full': ref_full,
        'ref_reciter': ref_reciter,
        'reciters': [
            {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')}
            for rid in reciter_ids if rid in per_reciter
        ],
        'per_reciter': per_reciter,
        'union_stops': union_stops,
        'mushafs': mushafs,
    }


# Printed mushafs whose waqf marks we compare the reciters against.
_WAQF_COMPARE_MUSHAFS = ('المدينة', 'الأزهر', 'الشمرلي')


def _reference_timeline(per_reciter, words, vk, verse_durs):
    """Cumulative seconds to the end of each word for one representative
    reciter, used to size breath segments consistently. Returns
    (ref_times[wpos], ref_full_seconds, reciter_id)."""
    if not per_reciter or not words:
        return None, None, None
    avg = (sum(verse_durs) / len(verse_durs)) if verse_durs else 0
    # rank: fewest repeats first, then closest pace to the average
    ranked = sorted(
        per_reciter.keys(),
        key=lambda rid: (len(per_reciter[rid]['repeats']), abs(per_reciter[rid]['duration'] - avg)),
    )
    ref_rid = ranked[0]
    try:
        w = _load_memorization_word_ts(ref_rid)[vk][1]
    except Exception:
        return None, None, None
    vstart = w[0][1]
    times = [None] * len(words)
    for idx, _s, e in w:                       # first (forward) occurrence per word
        i = idx - 1
        if 0 <= i < len(times) and times[i] is None:
            times[i] = round((e - vstart) / 1000.0, 2)
    # fill any gaps (shouldn't happen) by carrying the previous value forward
    last = 0.0
    for i in range(len(times)):
        if times[i] is None:
            times[i] = last
        else:
            last = times[i]
    return times, times[-1] if times else None, ref_rid


@app.route('/api/waqf/<int:surah>/<int:ayah>', methods=['GET'])
def get_verse_waqf(surah, ayah):
    """Per-verse reciter-waqf comparison: how each installed reciter stops in
    this verse, who aligns vs. who is alone (انفرد), and where they repeat."""
    if not (1 <= surah <= 114) or ayah < 1:
        return jsonify({"error": "Invalid verse."}), 400
    gap_ms = request.args.get('gap', 250, type=int)
    if gap_ms < 0 or gap_ms > 5000:
        gap_ms = 250
    try:
        data = _build_verse_waqf_detail(surah, ayah, gap_ms)
    except Exception as e:
        app.logger.error(f"Waqf detail failed for {surah}:{ayah}: {e}")
        return jsonify({"error": "Waqf data unavailable"}), 503
    if not data['per_reciter']:
        return jsonify({"error": "No data for this verse."}), 404
    return jsonify(data)


@app.route('/waqf')
def waqf_guide():
    return render_template('waqf_guide.html', enable_vercel_analytics=_IS_SERVERLESS)


@app.route('/api/memorization/<int:surah_number>', methods=['GET'])
def get_memorization(surah_number):
    """Per-surah memorization data: audio URL + per-verse timing and phrases.

    All times are returned in SECONDS (audio.currentTime units).
      ?gap=<ms>  silence threshold (default 250): a break in 'acoustic' mode,
                 the snap floor in 'waqf' mode.
      ?mode=acoustic|waqf  acoustic = split at the reciter's pauses (default);
                 waqf = split at mushaf-waqf marks, snapped to nearby pauses."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    mode = (request.args.get('mode', 'acoustic') or 'acoustic').lower()
    if mode not in ('acoustic', 'waqf'):
        mode = 'acoustic'
    # 250ms default: validated against the Husary waqf DB
    # (mahmoud_khalil_al_husari_0_1_positions.db). At 250ms the silence-gap
    # split matches that DB's phrase boundaries on the verses where Husary
    # actually pauses (e.g. the 319ms micro-pause before "يَعْلَمُ" in Ayat
    # al-Kursi → 7 phrases like the DB), while still NOT cutting at the ~65% of
    # DB boundaries that are meaning-only stops with no audible pause here.
    gap_ms = request.args.get('gap', 250, type=int)
    if gap_ms < 0 or gap_ms > 5000:
        gap_ms = 250

    reciter_id = (request.args.get('reciter', _DEFAULT_MEMO_RECITER) or _DEFAULT_MEMO_RECITER)
    if not _memo_reciter_installed(reciter_id):
        reciter_id = _DEFAULT_MEMO_RECITER
    reciter_cfg = _memo_reciter_cfg(reciter_id)

    try:
        word_ts = _load_memorization_word_ts(reciter_id)
    except Exception as e:
        app.logger.error(f"Memorization data load failed for {reciter_id}: {e}")
        return jsonify({"error": "Memorization data unavailable"}), 503

    waqf_bounds = _load_waqf_boundaries() if mode == 'waqf' else {}
    font_type = normalize_source(request.args.get('font_type', 'qpc_hafs') or 'qpc_hafs')
    text_data = get_quran_text_data_by_source(font_type)

    verses = []
    ayah = 1
    while True:
        vk = f"{surah_number}:{ayah}"
        if vk not in word_ts:
            break
        entry = word_ts[vk]
        verse_range, words = entry[0], entry[1]
        if mode == 'waqf':
            phrases = _waqf_aligned_phrases(words, waqf_bounds.get(vk, []), gap_ms)
            if not phrases:                       # verse missing from waqf DB
                phrases = _segment_phrases(words, gap_ms)
        else:
            phrases = _segment_phrases(words, gap_ms)
        text = ''
        td = text_data.get(vk) if isinstance(text_data, dict) else None
        if isinstance(td, dict):
            text = td.get('text', '') or ''
        verses.append({
            'ayah': ayah,
            'verse_key': vk,
            'start': round(verse_range[0] / 1000.0, 3),
            'end': round(verse_range[1] / 1000.0, 3),
            'text': text,
            'phrases': [
                {'start': round(p['start'] / 1000.0, 3),
                 'end': round(p['end'] / 1000.0, 3)}
                for p in phrases
            ],
            'words': [
                [w[0] - 1, round(w[1] / 1000.0, 3), round(w[2] / 1000.0, 3)]
                for w in words
            ],
        })
        ayah += 1

    if not verses:
        return jsonify({"error": "No memorization data for this surah."}), 404

    return jsonify({
        'surah_number': surah_number,
        'reciter': reciter_cfg.get('name_en', 'Mahmoud Khalil al-Husary'),
        'reciter_id': reciter_id,
        'reciter_name_ar': reciter_cfg.get('name_ar', ''),
        'audio_url': reciter_cfg['audio_tmpl'].format(surah=surah_number),
        'gap_ms': gap_ms,
        'mode': mode,
        'verses': verses,
    })


@app.route('/api/memorization-reciters', methods=['GET'])
def get_memorization_reciters():
    """List the memorization reciters whose timestamp data is installed."""
    out = []
    for rid, cfg in MEMORIZATION_RECITERS.items():
        if _memo_reciter_installed(rid):
            out.append({'id': rid, 'name_ar': cfg.get('name_ar', ''), 'name_en': cfg.get('name_en', '')})
    return jsonify(out)


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
        allowed_domains = {'audio.qurancdn.com', 'audio-cdn.tarteel.ai', 'everyayah.com', 'server13.mp3quran.net'}
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

        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM words WHERE surah = ? AND ayah = ? ORDER BY word_index ASC", (surah_number, ayah_number))
        words = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'mushaf_layout_inferred.db'))
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
                WHERE line_type IN ('ayah', 'basmallah')
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
        
        glyph_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'glyph_mappings.db'))
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
            glyph_page = None

            # Only substitute a page-local glyph when the verse's page actually
            # has a Shemrly-PageNNN.ttf font loaded in the browser. The old
            # "legacy" fallback emitted Elgharib glyph codepoints (U+FB50 range)
            # for pages WITHOUT a font, but no Elgharib font is shipped, so they
            # rendered as garbage. For those pages we keep the plain verse text
            # (readable in the UthmanicHafs fallback) instead.
            if shemrly_pages_with_fonts:
                for page in shemrly_pages_with_fonts:
                    glyph_char = _get_shamarly_glyph_char_for_word(page, int(word['word_index']))
                    if glyph_char:
                        glyph_page = page
                        break

            if glyph_char:
                word['glyph_char'] = glyph_char
                word['text'] = glyph_char
                # Glyph codepoints are PAGE-LOCAL: the same U+FB51 means a different
                # word in each page font. A verse that spans two font pages must
                # render each word with the font of the page its glyph came from,
                # otherwise the second page's words draw the first page's glyphs.
                word['glyph_page'] = glyph_page
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
@lru_cache(maxsize=1024)
def _get_shamarly_page_ayah_word_bounds(page_number):
    """Return (first_word_id, last_word_id) covering the real words printed on a page.

    The per-page Shemrly font indexes glyph base+1 to the FIRST words-table row
    physically on the page, in word_index order. We therefore must anchor on the
    first actual word, not the first 'ayah' line: on the Al-Fatiha page the basmala
    IS verse 1:1 and its words live in the words table BELOW the first ayah line, so
    an ayah-only floor shifted every glyph by 5 (basmala rendered as fallback text,
    later words ran off the end). We take the page's full layout word span (every
    word-bearing line, incl. basmallah/surah_name reserved slots) and clamp it to
    the words table — reserved slots and non-Fatiha basmalas (absent from words)
    drop out automatically, leaving the exact range the font's glyphs cover.
    """
    try:
        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        layout_cursor.execute(
            '''
            SELECT MIN(first_word_id) AS lo, MAX(last_word_id) AS hi
            FROM pages
            WHERE page_number = ?
              AND first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ''',
            (int(page_number),)
        )
        span = layout_cursor.fetchone()
        layout_conn.close()
        if not span or span['lo'] is None or span['hi'] is None:
            return (None, None)

        words_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db'))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT MIN(word_index) AS first_word_id, MAX(word_index) AS last_word_id
            FROM words
            WHERE word_index BETWEEN ? AND ?
            ''',
            (int(span['lo']), int(span['hi']))
        )
        row = words_cursor.fetchone()
        words_conn.close()
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
    font_path = os.path.join(os.path.dirname(__file__), 'static', 'fonts', f'{font_name}.ttf')
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
    """Return {word_index: codepoint} for a Shemrly page by aligning glyphs to words.

    Each per-page Shemrly font holds exactly one glyph per distinct word printed on
    the page, in word_index order. Crucially the cmap RESERVES a gap wherever the page
    has a standalone mark (e.g. the ۛ after رَيۡبَۛ فِيهِۛ on the Al-Baqarah page): those
    mark codepoints are absent from the font, so a naive base+(word-first+1) formula
    drifts by one for every word after a mark — rendering each following word with the
    previous word's glyph (the reported "verse 2 wrong, verses 3-4 words shifted onto
    the next line"). We instead zip the sorted present codepoints with the sorted word
    indices 1:1: cmap gaps line up with the marks, so every word keeps its own glyph.
    On mark-free pages the cmap is contiguous and this reduces to the simple formula.
    """
    first_word_id, last_word_id = _get_shamarly_page_ayah_word_bounds(page_number)
    if first_word_id is None or last_word_id is None:
        return {}

    font_name = f"Shemrly-Page{int(page_number):03d}"
    supported_codepoints = _get_shamarly_font_supported_codepoints(font_name)
    if not supported_codepoints:
        return {}
    present = sorted(c for c in supported_codepoints if c > SHEMRLY_CODEPOINT_BASE)

    try:
        words_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db'))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            'SELECT word_index FROM words WHERE word_index BETWEEN ? AND ? ORDER BY word_index ASC',
            (int(first_word_id), int(last_word_id))
        )
        word_indices = [int(r['word_index']) for r in words_cursor.fetchall()]
        words_conn.close()
    except Exception:
        return {}

    # The 1:1 alignment only holds when the font carries exactly one glyph per word.
    # If they disagree (missing font, data drift), bail so the caller can fall back.
    if not word_indices or len(present) != len(word_indices):
        return {}

    return dict(zip(word_indices, present))


def _get_shamarly_glyph_char_for_word(page_number, word_position):
    """Map a global word index to its Shemrly page-local glyph char."""
    codepoint_map = _get_shamarly_page_word_codepoint_map(page_number)
    wp = int(word_position)
    if wp in codepoint_map:
        return chr(codepoint_map[wp])

    # Fallback for pages where the glyph/word counts could not be aligned (e.g. the
    # font is absent): use the contiguous local-index formula.
    first_word_id, last_word_id = _get_shamarly_page_ayah_word_bounds(page_number)
    if first_word_id is None or last_word_id is None:
        return None
    if wp < first_word_id or wp > last_word_id:
        return None
    local_index = wp - first_word_id + 1
    if local_index <= 0:
        return None

    codepoint = SHEMRLY_CODEPOINT_BASE + local_index
    supported_codepoints = _get_shamarly_font_supported_codepoints(f"Shemrly-Page{int(page_number):03d}")
    if supported_codepoints is None or codepoint in supported_codepoints:
        return chr(codepoint)
    return None


def _get_preferred_legacy_glyph_font_for_range(min_word_id, max_word_id):
    """Pick the dominant legacy Elgharib font for a word range.

    Some ranges span multiple legacy font buckets; using a single dominant bucket
    avoids mixing incompatible glyph codepoint sets in one rendered page.
    """
    if min_word_id is None or max_word_id is None:
        return None

    try:
        glyph_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'glyph_mappings.db'))
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
    layout_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'mushaf_layout_inferred.db')))
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
            glyph_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'glyph_mappings.db')))
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

    # Collect the EXACT set of word_index values for the focus ayah rather than a
    # MIN/MAX range. Some verses in quran_script.db are stored with non-contiguous
    # word_index (a verse's tail words live after a neighbouring verse, e.g. 59:19,
    # 60:1, 2:285, 3:7, 38:79, 39:5). A MIN/MAX range for those verses swallows the
    # neighbour's words, so a line-overlap highlight test lit up the wrong verse.
    # An exact-set membership test highlights only lines that truly hold the verse.
    focus_word_indices = set()
    if focus_surah is not None and focus_ayah is not None:
        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db')))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT word_index
            FROM words
            WHERE surah = ? AND ayah = ?
            ''',
            (focus_surah, focus_ayah)
        )
        focus_word_indices = {int(row['word_index']) for row in words_cursor.fetchall()}
        words_conn.close()

    page_word_rows = []
    page_word_by_index = {}
    if min_word_id is not None and max_word_id is not None:
        words_conn = _track(sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db')))
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
                src_word = page_word_by_index.get(word_pos, {})
                line_words.append({
                    'word_index': word_pos,
                    'text': rendered_word,
                    'surah': src_word.get('surah'),
                    'ayah': src_word.get('ayah'),
                    'waqf_symbols': waqf_by_word_index.get(word_pos, '')
                })

            if chars:
                glyph_text = ' '.join(chars)

            if focus_word_indices:
                contains_focus_ayah = any(
                    word_pos in focus_word_indices
                    for word_pos in range(first_word_id, last_word_id + 1)
                )

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
        words_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'quran_script.db'))
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

        layout_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), 'data', 'mushaf_layout_inferred.db'))
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


_DK_LAYOUT_WORD_MAP = None


def _get_dk_layout_word_map():
    """Authoritative ``layout_word_id -> token`` map for the Digital Khatt and
    QPC-v1 15-line layouts (both share the identical 1..83668 word numbering).

    Built from the native Digital Khatt text (`digital_khatt_data`) anchored
    per-surah on the layout's OWN surah spans (the word ranges between
    consecutive ``surah_name`` lines). This deliberately does NOT use
    `quran_script.db.word_index`: that column is non-contiguous (preserved gaps
    from the Shemrly rebuild) so the old constant-offset mapping drifted by up to
    ~8 pages toward the end of the mushaf. Anchoring per surah resets any
    tokenisation drift at every surah boundary, so all 114 surahs land on the
    right page and each page renders its true words.

    Returns a dict:
        'id2tok'  : {layout_id: {'surah', 'ayah', 'text'}}
        'first_id': {(surah, ayah): layout_id}   # first word id of the verse
        'last_id' : {(surah, ayah): layout_id}
    Empty dicts if the source text or layout DB is unavailable.
    """
    global _DK_LAYOUT_WORD_MAP
    if _DK_LAYOUT_WORD_MAP is not None:
        return _DK_LAYOUT_WORD_MAP

    result = {'id2tok': {}, 'first_id': {}, 'last_id': {}}
    try:
        if not digital_khatt_data or not os.path.exists(DIGITAL_KHATT_LAYOUT_DATABASE):
            _DK_LAYOUT_WORD_MAP = result
            return result

        # Per-surah word-id span from the layout's surah_name partition.
        conn = sqlite3.connect(DIGITAL_KHATT_LAYOUT_DATABASE)
        rows = conn.execute(
            'SELECT line_type, surah_number, first_word_id, last_word_id '
            'FROM pages ORDER BY page_number, line_number'
        ).fetchall()
        conn.close()

        span = {}
        current_surah = None
        for line_type, surah_number, fw, lw in rows:
            if line_type == 'surah_name' and surah_number:
                current_surah = int(surah_number)
            if line_type == 'ayah' and current_surah and fw not in (None, '') and lw not in (None, ''):
                fw, lw = int(fw), int(lw)
                if current_surah not in span:
                    span[current_surah] = [fw, lw]
                else:
                    span[current_surah][0] = min(span[current_surah][0], fw)
                    span[current_surah][1] = max(span[current_surah][1], lw)

        # Group verses by surah, in ayah order.
        by_surah = {}
        for entry in digital_khatt_data.values():
            try:
                s, a = map(int, entry['verse_key'].split(':'))
            except (KeyError, ValueError, AttributeError):
                continue
            by_surah.setdefault(s, []).append((a, entry.get('text', '')))

        id2tok = result['id2tok']
        for s in sorted(by_surah):
            if s not in span:
                continue
            cid, cap = span[s]
            for a, text in sorted(by_surah[s]):
                tokens = [w for w in re.split(r'\s+', (text or '').strip()) if w]
                first = None
                for tok in tokens:
                    if cid > cap:
                        break  # clamp to the surah's span — drift never crosses a surah
                    if first is None:
                        first = cid
                    id2tok[cid] = {'surah': s, 'ayah': a, 'text': tok}
                    cid += 1
                if first is not None:
                    result['first_id'][(s, a)] = first
                    result['last_id'][(s, a)] = cid - 1
    except Exception as e:
        app.logger.error(f'Failed to build Digital Khatt layout word map: {e}')

    _DK_LAYOUT_WORD_MAP = result
    return result


def _layout_page_resolve(layout_db, surah_number, ayah_number):
    """Return the page number that first displays (surah, ayah) in a 15-line
    layout DB, using the authoritative word map. None if unresolved."""
    wmap = _get_dk_layout_word_map()
    layout_id = wmap['first_id'].get((surah_number, ayah_number))
    if layout_id is None:
        return None
    conn = sqlite3.connect(layout_db)
    try:
        row = conn.execute(
            'SELECT page_number FROM pages '
            'WHERE first_word_id IS NOT NULL AND first_word_id <> \'\' '
            'AND CAST(first_word_id AS INTEGER) <= ? AND CAST(last_word_id AS INTEGER) >= ? '
            'ORDER BY page_number ASC LIMIT 1',
            (layout_id, layout_id)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _assemble_layout_page(lines, info_row, page_number, focus_surah, focus_ayah,
                          source, font_name_default, include_advance, mushaf_version=''):
    """Shared page-payload assembler for the Digital Khatt / QPC-v1 layouts.
    Words come from the authoritative Digital Khatt word map keyed on the
    layout's word ids, so the rendered text always matches the page.

    `mushaf_version` (str or list) selects which print's waqf symbols to attach
    per word — same mechanism the main app uses."""
    id2tok = _get_dk_layout_word_map()['id2tok']

    def to_int_or_none(value):
        try:
            if value is None or str(value).strip() == '':
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    bismillah = 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ'
    anchor_surah_number = None
    anchor_ayah_number = None
    output_lines = []
    page_word_rows = []  # flat, for waqf matching (grouped by verse internally)
    for line in lines:
        first_word_id = to_int_or_none(line.get('first_word_id'))
        last_word_id = to_int_or_none(line.get('last_word_id'))
        line_type = line.get('line_type')
        line_surah = line.get('surah_number')

        display_text = ''
        line_words = []
        contains_focus_ayah = False
        if first_word_id is not None and last_word_id is not None:
            for word_id in range(first_word_id, last_word_id + 1):
                tok = id2tok.get(word_id)
                if not tok:
                    continue
                word = {
                    'word_index': word_id,
                    'text': tok['text'],
                    'surah': tok['surah'],
                    'ayah': tok['ayah'],
                    'waqf_symbols': ''
                }
                line_words.append(word)
                page_word_rows.append(word)
                if anchor_surah_number is None:
                    anchor_surah_number = tok['surah']
                    anchor_ayah_number = tok['ayah']
                if focus_surah is not None and tok['surah'] == focus_surah and tok['ayah'] == focus_ayah:
                    contains_focus_ayah = True
            display_text = ' '.join(w['text'] for w in line_words)
        elif line_type == 'surah_name':
            surah_name = _get_surah_name_ar(line_surah)
            display_text = f"سورة {surah_name}" if surah_name else ''
        elif line_type == 'basmallah':
            display_text = bismillah

        out_line = {
            'line_number': to_int_or_none(line.get('line_number')),
            'line_type': line_type,
            'is_centered': bool(line.get('is_centered')),
            'surah_number': line_surah,
            'first_word_id': first_word_id,
            'last_word_id': last_word_id,
            'display_text': display_text,
            'contains_focus_ayah': contains_focus_ayah,
            'words': line_words,
        }
        if include_advance:
            out_line['total_advance'] = line.get('total_advance')
            out_line['x_offset'] = line.get('x_offset', 0)
        else:
            out_line['total_advance'] = None
            out_line['x_offset'] = 0
        output_lines.append(out_line)

    # Attach per-word waqf symbols for the selected mushaf version(s). The word
    # dicts are shared with output_lines, so backfilling updates them in place.
    if mushaf_version:
        waqf_by_word_index = _build_page_waqf_map(page_word_rows, mushaf_version)
        if waqf_by_word_index:
            for word in page_word_rows:
                entries = waqf_by_word_index.get(word['word_index'])
                if entries:
                    word['waqf_symbols'] = entries

    # Page content width (justified lines only) for frontend per-line scaling.
    page_content_width = None
    if include_advance:
        justified = [l.get('total_advance') for l in output_lines
                     if l.get('total_advance') and not l.get('x_offset')]
        if justified:
            justified.sort()
            page_content_width = justified[len(justified) // 2]

    def info_get(key, default=None):
        if info_row is not None:
            try:
                if key in info_row.keys():
                    return info_row[key]
            except AttributeError:
                pass
        return default

    return {
        'source': source,
        'page_number': int(page_number),
        'font_name': info_get('font_name', font_name_default) or font_name_default,
        'layout_name': info_get('name', font_name_default),
        'lines_per_page': (int(info_get('lines_per_page')) if info_get('lines_per_page') else 15),
        'page_content_width': page_content_width,
        'focus_surah': focus_surah,
        'focus_ayah': focus_ayah,
        'lines': output_lines,
        'anchor_surah_number': anchor_surah_number,
        'anchor_ayah_number': anchor_ayah_number,
    }


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
        SELECT page_number, line_number, line_type, is_centered, first_word_id, last_word_id, surah_number
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

    payload = _assemble_layout_page(
        lines, info_row, page_number, focus_surah, focus_ayah,
        source='digital_khatt', font_name_default='Digital Khatt', include_advance=False,
        mushaf_version=mushaf_version
    )
    payload['font_name'] = 'Digital Khatt'  # rendered with the Digital Khatt webfont regardless of layout
    payload['mushaf_version'] = (
        mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or '')
    )
    return payload


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

        page_number = _layout_page_resolve(DIGITAL_KHATT_LAYOUT_DATABASE, surah_number, ayah_number)
        if page_number is None:
            return jsonify({'error': 'Page not found for ayah'}), 404

        payload = _build_digital_khatt_page_payload(
            page_number,
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


def _build_qpc_v1_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    """Build a page payload from the QPC V1 (Old Madinah 1405) layout database.

    Shares the Digital Khatt word numbering and word map; the only differences are
    the font and the absence of total_advance / x_offset (page_content_width is
    left None so the frontend falls back to DOM-measurement justification).
    """
    if not os.path.exists(QPC_V1_LAYOUT_DATABASE):
        return None

    layout_conn = sqlite3.connect(QPC_V1_LAYOUT_DATABASE)
    try:
        layout_conn.row_factory = sqlite3.Row
        lc = layout_conn.cursor()
        lc.execute(
            'SELECT page_number, line_number, line_type, is_centered, first_word_id, last_word_id, surah_number '
            'FROM pages WHERE page_number = ? ORDER BY line_number ASC',
            (page_number,)
        )
        lines = [dict(row) for row in lc.fetchall()]
        lc.execute('SELECT font_name, number_of_pages, lines_per_page, name FROM info LIMIT 1')
        info_row = lc.fetchone()
    finally:
        layout_conn.close()

    if not lines:
        return None

    payload = _assemble_layout_page(
        lines, info_row, page_number, focus_surah, focus_ayah,
        source='qpc_v1', font_name_default='Old Madina', include_advance=False,
        mushaf_version=mushaf_version
    )
    payload['font_name'] = 'Old Madina'
    payload['layout_name'] = (info_row['name'] if info_row else 'مصحف المدينة القديم ١٤٠٥')
    payload['mushaf_version'] = (
        mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or '')
    )
    return payload


@app.route('/api/qpc-v1/page/<int:page_number>', methods=['GET'])
def get_qpc_v1_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_qpc_v1_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching QPC V1 page {page_number}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/qpc-v1/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_qpc_v1_page_by_ayah(surah_number, ayah_number):
    try:
        if not os.path.exists(QPC_V1_LAYOUT_DATABASE):
            return jsonify({'error': 'QPC V1 layout DB not found'}), 404

        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        page_number = _layout_page_resolve(QPC_V1_LAYOUT_DATABASE, surah_number, ayah_number)
        if page_number is None:
            return jsonify({'error': 'Page not found for ayah'}), 404

        payload = _build_qpc_v1_page_payload(page_number, focus_surah=surah_number, focus_ayah=ayah_number,
                                             mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as e:
        app.logger.error(f"Error fetching QPC V1 page by ayah {surah_number}:{ayah_number}: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
