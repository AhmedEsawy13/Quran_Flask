from flask import Flask, jsonify, request, redirect
import sqlite3
import os
import logging
import re
import threading

import gzip
from io import BytesIO

from core.loader import (
    load_json_cdn_or_local as _load_json_cdn_or_local,
)

app = Flask(__name__, static_folder='static')

# Feature blueprints. Routes are attached to these below (one per feature area)
# so each feature can be enabled/disabled per deployment via the FEATURES env
# var — and the write-capable editor can be gated to localhost only.
#   core      — shared Quran text, search, and mushaf page-rendering (read-only)
#   reading   — main mushaf reading page + tafseer/tajweed/eerab aids
#   memorize  — repeat-verses player
#   breathing — reciter-validated waqf stops (دليل التنفس)
#   editor    — /mushaf-editor click-to-edit waqf tool (the ONLY writer)
from core.blueprints import core_bp, reading_bp, memorize_bp, breathing_bp, editor_bp

# (Flask-Compress is not installed/initialised here — the previous
# COMPRESS_* config keys had no effect and were removed. JSON gzip is
# handled inline in after_request below.)

# Configure logging
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# Auto cache-busting: hash the file contents so browsers always fetch the
# latest version after a deploy — no more manual ?v=N bumps.
import hashlib as _hashlib
_static_hash_cache: dict[str, str] = {}

@app.template_global()
def static_hash(filename: str) -> str:
    """Return /static/<filename>?h=<8-char content hash>."""
    h = _static_hash_cache.get(filename)
    if h is None:
        path = os.path.join(app.static_folder, filename)
        try:
            with open(path, 'rb') as f:
                h = _hashlib.md5(f.read()).hexdigest()[:8]
        except OSError:
            h = '0'
        _static_hash_cache[filename] = h
    return f'/static/{filename}?h={h}'

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
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://vercel.live https://va.vercel-scripts.com https://www.youtube.com; "
        "worker-src 'self' blob:; "
        "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # *.mp3quran.net → the memorize/reciter audio (server7/8/10/13/…).
        # *.googlevideo.com → YouTube audio streams (IFrame Player API).
        # drive.usercontent.google.com → Google Drive direct-download MP3s (_gd_ reciters).
        # huggingface.co → HuggingFace direct MP3s (_gd_ reciters).
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com https://*.mp3quran.net https://download.tvquran.com https://download.quranicaudio.com https://*.googlevideo.com https://drive.usercontent.google.com https://huggingface.co https://*.huggingface.co; "
        # huggingface.co (+ LFS redirect hosts) → ASR model fallback when /static can't serve the 132MB file.
        "connect-src 'self' https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co https://*.hf.co https://cdn-lfs.huggingface.co https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com https://www.youtube.com https://www.googleapis.com;"
    )
    
    # Cache control for API responses.
    if request.path.startswith('/api/'):
        # Waqf overlays can be adjusted at runtime and are sensitive to
        # matching logic updates. Avoid stale browser cache for these requests.
        # /api/mushaf-editor/* is a live editing tool (spread/progress reads
        # reflect edits made seconds earlier via /api/mushaf-editor/waqf) — a
        # 1-hour cache made just-saved marks appear to "not save" on reload.
        if request.args.get('mushaf_version') or request.path.startswith('/api/mushaf-editor/'):
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        elif request.path.startswith('/api/waqf-research/'):
            # Heavy Quran-wide analyses are cached SERVER-side (instant after the
            # first build), so don't pin them in the browser for an hour — a
            # redeploy that changes the computation must show up immediately
            # instead of serving a stale aggregate.
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        elif response.status_code >= 400:
            # Never cache error responses: a transient 404/500/503 (e.g. during a
            # deploy, or the breathing guide's 503) must not be pinned in the
            # browser/CDN for an hour and shadow the endpoint once it recovers.
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

from core.config import (
    DATABASE, WAQF_DATABASE, MAX_AYAH_NUMBER,
    MUSHAF_WAQF_DATABASE,  # noqa: F401 — tests reach this via app.MUSHAF_WAQF_DATABASE
    _BASE_DIR,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app._BASE_DIR
)
from core.text import (
    _normalize_for_search,
)
from core.mushaf_waqf import (
    _get_mushaf_version_whitelist,
)


import modules.editor  # noqa: F401 — attaches editor routes to editor_bp
from modules.layouts import (  # noqa: F401 — importing also registers layout routes
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)
import modules.breathing        # noqa: F401 — attaches breathing routes to breathing_bp
import modules.waqf_research    # noqa: F401 — attaches waqf-research routes to breathing_bp
from modules.breathing import _verse_word_texts, _mark_word_context  # noqa: F401 — tests reach these via app.<name>
from modules.waqf_research import (  # noqa: F401 — tests/pipeline reach these via app.<name>
    _RESEARCH_CACHE_DIR, _build_reciter_clustering, _build_mushaf_similarity,
    _build_mushaf_agreement_index, _build_ibtidaa_index,
)
import modules.reading          # noqa: F401 — attaches reading routes to reading_bp
from modules.reading import get_waqf_symbols, get_word_meanings_ordered  # noqa: F401 — needed by the surviving get_ayah_text
import modules.memorize         # noqa: F401 — attaches memorize routes to memorize_bp
from core.datasets import (
    digital_khatt_data, qpc_hafs_data, indopak_nastaleeq_data,
    indopak_nastaleeq_2_data, transliteration_data, surahs_data,
    normalize_source, get_quran_text_data_by_source, get_quran_text_data,
    qpc_hafs_data_normalized,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app.<name>
)
from core.memorization import (
    _YT_CHAPTER_URLS,
)



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






@core_bp.route('/api/mushaf-versions', methods=['GET'])
def get_mushaf_versions():
    """Returns available Mushaf versions from the waqf database."""
    return jsonify(sorted(_get_mushaf_version_whitelist()))






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


# Database helper functions (moved to core.db so feature blueprints can share
# the per-request connection without importing the main app module).
from core.db import get_db, close_connection
app.teardown_appcontext(close_connection)




@core_bp.route('/api/health', methods=['GET'])
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

@core_bp.route('/api/surahs', methods=['GET'])
def get_surahs():
    """Get list of surahs with their names (local data, no external API dependency)"""
    if surahs_data:
        return jsonify(surahs_data)
    
    # Fallback to extracting surah numbers from text data
    quran_text_data = get_quran_text_data()
    surahs = {int(vk.split(':')[0]) for vk in quran_text_data.keys()}
    return jsonify(sorted(surahs))

@core_bp.route('/api/surahs/<int:surah_number>/ayahs', methods=['GET'])
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

@core_bp.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>', methods=['GET'])
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




@core_bp.route('/api/reciters/<reciter>/ayahs/<int:ayah_number>/audio', methods=['GET'])
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

@core_bp.route('/api/quran-text', methods=['GET'])
def get_quran_text():
    quran_text_data = get_quran_text_data()
    return jsonify(quran_text_data)

@core_bp.route('/api/transliteration', methods=['GET'])
def get_transliteration():
    return jsonify(transliteration_data)



# yt-dlp stream URL cache: (reciter_id, surah) -> {'url': str, 'expires': float}
# YouTube direct-stream URLs are typically valid for ~6 h; we cache for 4 h.
import time as _time
_YT_STREAM_CACHE: dict = {}
_YT_STREAM_LOCK = threading.Lock()
_YT_STREAM_TTL = 4 * 3600  # seconds

try:
    import yt_dlp as _yt_dlp
    _YT_DLP_AVAILABLE = True
except ImportError:
    _yt_dlp = None  # type: ignore
    _YT_DLP_AVAILABLE = False
    app.logger.warning('yt-dlp not installed — YouTube-sourced reciters will be unavailable.')


@core_bp.route('/api/audio-proxy')
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


@core_bp.route('/api/yt-audio')
def yt_audio():
    """Resolve a YouTube watch URL to a direct audio-stream URL via yt-dlp,
    cache the result for up to 4 hours (stream URLs expire ~6 h), and redirect
    the browser to the stream so it can seek normally with Range requests.

    Only YouTube URLs stored in _YT_CHAPTER_URLS are accepted; arbitrary
    YouTube URLs cannot be submitted.
    """
    if not _YT_DLP_AVAILABLE:
        return jsonify({'error': 'yt-dlp is not installed on this server'}), 503

    from urllib.parse import urlparse, unquote

    raw_url = request.args.get('url', '').strip()
    if not raw_url:
        return jsonify({'error': 'Missing url parameter'}), 400

    # Decode if percent-encoded (e.g. from _yt_audio_url helper)
    yt_url = unquote(raw_url)

    # Security: only allow URLs that are actually in our YT chapter-URL catalogs.
    allowed_yt_urls = {
        url
        for chapter_map in _YT_CHAPTER_URLS.values()
        for url in chapter_map.values()
    }
    if yt_url not in allowed_yt_urls:
        return jsonify({'error': 'URL not in approved reciter catalog'}), 403

    # Additional structural check
    parsed = urlparse(yt_url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.youtube.com', 'youtube.com', 'youtu.be'):
        return jsonify({'error': 'Only YouTube URLs are allowed'}), 400

    # Check cache first (keyed by the watch URL itself)
    now = _time.time()
    with _YT_STREAM_LOCK:
        cached = _YT_STREAM_CACHE.get(yt_url)
        if cached and cached['expires'] > now:
            return redirect(cached['url'], code=307)

    # Resolve with yt-dlp (runs synchronously; typically < 1 s)
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
    }
    try:
        with _yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_url, download=False)
        # Prefer the top-level url; fall back to the last format's url.
        stream_url = info.get('url')
        if not stream_url:
            formats = info.get('formats') or []
            stream_url = formats[-1].get('url') if formats else None
        if not stream_url:
            return jsonify({'error': 'yt-dlp could not extract a stream URL'}), 502
    except Exception as exc:
        app.logger.error(f'yt-dlp extraction failed for {yt_url}: {exc}')
        return jsonify({'error': 'Failed to resolve YouTube audio stream'}), 502

    with _YT_STREAM_LOCK:
        _YT_STREAM_CACHE[yt_url] = {'url': stream_url, 'expires': now + _YT_STREAM_TTL}

    return redirect(stream_url, code=307)


@core_bp.route('/api/search', methods=['GET'])
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

@core_bp.route('/api/word-search', methods=['GET'])
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



# ---------------------------------------------------------------------------
# Blueprint registration / app factory
#
# Each Heroku app (or domain) can serve a subset of features by setting the
# FEATURES env var, e.g. FEATURES="reading" or FEATURES="memorize,breathing".
# 'core' is always included (shared text/search/page-rendering the others need).
# The write-capable 'editor' is OFF by default and only mounts when
# ENABLE_EDITOR is set — keep that to localhost so production stays read-only.
# ---------------------------------------------------------------------------
ALL_BLUEPRINTS = {
    'core': core_bp,
    'reading': reading_bp,
    'memorize': memorize_bp,
    'breathing': breathing_bp,
    'editor': editor_bp,
}
_DEFAULT_FEATURES = {'core', 'reading', 'memorize', 'breathing'}


def enabled_features():
    """Resolve the feature set for this process from the environment."""
    raw = os.environ.get('FEATURES', '').strip()
    feats = {f.strip() for f in raw.split(',') if f.strip()} if raw else set(_DEFAULT_FEATURES)
    feats.add('core')  # shared foundation is always required
    if os.environ.get('ENABLE_EDITOR'):
        feats.add('editor')
    else:
        feats.discard('editor')  # never expose the writer unless explicitly enabled
    return feats


def register_blueprints(flask_app, features=None):
    features = features if features is not None else enabled_features()
    for name, bp in ALL_BLUEPRINTS.items():
        # Idempotent: skip blueprints already mounted (create_app may be called
        # after the module-level registration below).
        if name in features and name not in flask_app.blueprints:
            flask_app.register_blueprint(bp)
    flask_app.logger.info(f"Enabled features: {sorted(features)}")
    return flask_app


def create_app(features=None):
    """Return the configured application, mounting the selected features.

    Exposed for WSGI entrypoints / future per-feature deployments. The module
    also configures the shared ``app`` object at import for ``gunicorn app:app``.
    """
    return register_blueprints(app, features)


# Configure the default module-level app (used by `gunicorn app:app`).
register_blueprints(app)


if __name__ == '__main__':
    os.environ.setdefault('ENABLE_EDITOR', '1')
    register_blueprints(app)
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
