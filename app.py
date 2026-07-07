from flask import Flask, jsonify, render_template, request, g, redirect
import json
import sqlite3
import os
import logging
import re
import threading
from collections import defaultdict, Counter
from functools import lru_cache

import gzip
from io import BytesIO
import requests as http_requests
import concurrent.futures

from core.lru import _BoundedLRU
from core.loader import (
    _json_load,
    load_json_cdn_or_local as _load_json_cdn_or_local,
    IS_SERVERLESS as _IS_SERVERLESS,
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
    DATABASE, WAQF_DATABASE, MUSHAF_WAQF_DATABASE,
    _BASE_DIR, RECITER_GUIDE_CONFIG,
    TAJWEED_DATABASE, CLASSICAL_WAQF_DATABASE, MAX_AYAH_NUMBER,
    WAQF_SYMBOL_CHARS, QURAN_PHONEMES_JSON,
)
from core.text import (
    _normalize_for_search,
    normalize_quran_dataset,
    initialize_waqf_database,
)
from core.mushaf_waqf import (
    _get_mushaf_version_whitelist,
    _is_valid_mushaf_version,
    _get_waqf_at_boundary,
    get_mushaf_waqf_symbols,
    _fetch_single_mushaf_waqf,
)


import modules.editor  # noqa: F401 — attaches editor routes to editor_bp
from modules.layouts import (  # noqa: F401 — importing also registers layout routes
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)
from core.datasets import (
    digital_khatt_data, qpc_hafs_data, indopak_nastaleeq_data,
    indopak_nastaleeq_2_data, transliteration_data, surahs_data,
)

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






@core_bp.route('/api/mushaf-versions', methods=['GET'])
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



@breathing_bp.route('/api/recitation-guide/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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
    # to المدينة الجديد so unconfigured reciters still get a guide overlay.
    waqf_col = cfg.get('waqf_col', 'المدينة الجديد')
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


@breathing_bp.route('/api/pause-match/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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


@breathing_bp.route('/api/reciter-compare/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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


# Database helper functions (moved to core.db so feature blueprints can share
# the per-request connection without importing the main app module).
from core.db import get_db, close_connection, connect as _sqlite_connect
app.teardown_appcontext(close_connection)

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


@reading_bp.route('/api/surahs/<int:surah_number>/ayahs/<int:ayah_number>/waqf', methods=['GET'])
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

@reading_bp.route('/api/tafseer/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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

@reading_bp.route('/api/tajweed/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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


@reading_bp.route('/api/eerab/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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

@reading_bp.route('/')
def index():
    return render_template('index.html', enable_vercel_analytics=_IS_SERVERLESS)


@memorize_bp.route('/memorize')
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

# ── YouTube-sourced reciter catalogs ────────────────────────────────────────
# Some reciters have per-surah YouTube video URLs instead of direct MP3 URLs.
# Load their catalog.json at startup so we can map surah -> YouTube URL without
# touching the disk on every request.
#
# audio_tmpl for these entries is set to the sentinel '_yt_' so the helpers
# below know to call _yt_audio_url(reciter_id, surah) instead.

def _load_yt_chapter_urls(slug: str) -> dict:
    """Return {str(surah_number): youtube_url} from a reciter's catalog.json."""
    catalog_path = os.path.join(_BASE_DIR, 'reciters', slug, 'catalog.json')
    if not os.path.exists(catalog_path):
        return {}
    try:
        with open(catalog_path, encoding='utf-8') as fh:
            cat = json.load(fh)
        return cat.get('audio', {}).get('chapter_urls', {})
    except Exception as e:
        app.logger.warning(f'Could not load YT catalog for {slug}: {e}')
        return {}

# Map reciter_id -> {str(surah): yt_url} for YouTube-sourced reciters.
_YT_CHAPTER_URLS: dict = {}

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


def _yt_audio_url(reciter_id: str, surah: int) -> str | None:
    """Return the raw YouTube watch URL for a surah.

    The frontend (mushaf_memorize.js) detects youtube.com URLs and routes them
    through the YouTube IFrame Player API instead of a native <audio> element.
    This works on every deployment including Heroku (no server-side stream
    extraction; YouTube datacenter IP blocking is irrelevant).
    """
    chapter_urls = _YT_CHAPTER_URLS.get(reciter_id, {})
    return chapter_urls.get(str(surah))


# ── Google Drive / HuggingFace catalog-based reciters (_gd_ sentinel) ───────
# Some reciters have per-surah URLs that are a mix of:
#   • HuggingFace direct MP3 links (serve immediately, no conversion needed)
#   • Google Drive "view" pages  (must convert to download URL)
# audio_tmpl = '_gd_' tells the helpers below to call _gd_audio_url() which
# converts Drive view URLs to direct-download URLs and passes HF URLs through.

_GD_FILE_ID_RE = re.compile(r'/file/d/([A-Za-z0-9_-]+)')


# Map reciter_id -> {str(surah): url} for _gd_ sentinel reciters.
_GD_CHAPTER_URLS: dict = {}


def _gd_audio_url(reciter_id: str, surah: int) -> str | None:
    """Return a playable audio URL for a catalog-based (_gd_) reciter's surah.

    HuggingFace direct-MP3 URLs are returned as-is.
    Google Drive view URLs 403 on cross-origin requests, so we use the
    reciter's fallback_tmpl (an mp3quran per-surah URL) for those surahs.
    """
    raw = _GD_CHAPTER_URLS.get(reciter_id, {}).get(str(surah))
    if not raw:
        return None
    if 'drive.google.com' in raw:
        # Drive blocks cross-origin audio — fall back to the mp3quran URL.
        cfg = MEMORIZATION_RECITERS.get(reciter_id, {})
        fallback = cfg.get('fallback_tmpl')
        return fallback.format(surah=surah) if fallback else None
    return raw  # HuggingFace or other direct MP3

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
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_siddiq_al_minshawi_mp3quran'),
        'audio_tmpl': 'https://server10.mp3quran.net/minsh/{surah:03d}.mp3',
    },
    'abdulbasit': {
        'name_ar': 'عبد الباسط عبد الصمد', 'name_en': 'AbdulBaset AbdulSamad',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'abdulbasit_abdulsamad_tarteel'),
        # Timestamps are aligned to the Tarteel CDN murattal recording (not the
        # mp3quran one), so the audio source must match for accurate seeking.
        'audio_tmpl': 'https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/{surah:03d}.mp3',
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
    'sufi': {
        'name_ar': 'عبد الرشيد صوفي', 'name_en': 'Abdur-Rashid Sufi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'abdur_rashid_sufi_qdc'),
        'audio_tmpl': 'https://download.quranicaudio.com/quran/abdurrashid_sufi/{surah:03d}.mp3',
    },
    'maasaraawi': {
        'name_ar': 'أحمد عيسى المعصراوي', 'name_en': 'Ahmed Issa Al-Maasaraawi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_issa_al_maasaraawi_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/a_maasaraawi/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'abdulhakam': {
        'name_ar': 'محمود عبدالحكم', 'name_en': 'Mahmoud Abdul Hakam',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mahmoud_abdul_hakam_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/m_abdelhakam/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'burhaji': {
        'name_ar': 'محمد برهجي', 'name_en': 'Mohammed Burhaji',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_burhaji_yt'),
        'audio_tmpl': '_yt_',  # per-surah YouTube videos; resolved via _yt_audio_url()
    },
    'shaheen': {
        'name_ar': 'أحمد خليل شاهين', 'name_en': 'Ahmed Khalil Shaheen',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_shaheen_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/shaheen/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'huthaifi': {
        'name_ar': 'علي بن عبد الرحمن الحذيفي', 'name_en': 'Ali Al-Huthaifi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ali_al_huthaifi_mp3quran'),
        'audio_tmpl': 'https://server9.mp3quran.net/hthfi/{surah:03d}.mp3',
    },
    'akhdar': {
        'name_ar': 'إبراهيم الأخضر', 'name_en': 'Ibrahim Al-Akhdar',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ibrahim_al_akhdar_drive'),
        # Per-surah catalog: HuggingFace direct MP3 (71 surahs) + Google Drive
        # view pages (43 surahs). Drive URLs 403 on cross-origin audio requests;
        # fallback_tmpl is used for those surahs.
        'audio_tmpl': '_gd_',
        'fallback_tmpl': 'https://server6.mp3quran.net/akdr/{surah:03d}.mp3',
    },
    'ayyub': {
        'name_ar': 'محمد أيوب', 'name_en': 'Mohammed Ayyub',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_ayyub_drive'),
        # Same as akhdar: HF direct MP3 (71 surahs) + Drive view pages (43).
        'audio_tmpl': '_gd_',
        'fallback_tmpl': 'https://server8.mp3quran.net/ayyub/{surah:03d}.mp3',
    },
    'mustafa_ismail': {
        'name_ar': 'مصطفى إسماعيل', 'name_en': 'Mustafa Ismail',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mustafa_ismail_mp3quran'),
        'audio_tmpl': 'https://server8.mp3quran.net/mustafa/{surah:03d}.mp3',
    },
    # Abdullah Al-Buaijan (عبد الله البعيجان) is in QUL v1.1.0 but its audio is a
    # 2025 YouTube recording: surahs 3–114 are only YouTube video URLs (no
    # streamable per-surah MP3), so the timestamps can't drive seek-based playback
    # here. Excluded until an aligned per-surah MP3 source exists.
}

# Populate _YT_CHAPTER_URLS and _GD_CHAPTER_URLS at startup.
for _rid, _rcfg in MEMORIZATION_RECITERS.items():
    _slug = os.path.basename(_rcfg['dir'])
    if _rcfg.get('audio_tmpl') == '_yt_':
        _YT_CHAPTER_URLS[_rid] = _load_yt_chapter_urls(_slug)
    elif _rcfg.get('audio_tmpl') == '_gd_':
        _GD_CHAPTER_URLS[_rid] = _load_yt_chapter_urls(_slug)  # same catalog format

_DEFAULT_MEMO_RECITER = 'husary'

def _memo_reciter_cfg(reciter_id):
    return MEMORIZATION_RECITERS.get(reciter_id) or MEMORIZATION_RECITERS[_DEFAULT_MEMO_RECITER]

def _memo_reciter_installed(reciter_id):
    cfg = MEMORIZATION_RECITERS.get(reciter_id)
    if not cfg:
        return False
    tmpl = cfg.get('audio_tmpl')
    if not tmpl:
        return False
    # YouTube-sourced reciters only need chapter URLs to be loaded; yt-dlp is no
    # longer required because audio plays client-side via the IFrame Player API.
    if tmpl == '_yt_':
        if not _YT_CHAPTER_URLS.get(reciter_id):
            return False
    # Catalog-based (Drive/HF) reciters need their chapter URLs loaded.
    if tmpl == '_gd_':
        if not _GD_CHAPTER_URLS.get(reciter_id):
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
    """Split a verse's word list into phrases at silence gaps >= gap_ms.

    `words` is the source's [[word_index, start_ms, end_ms], ...]. A run of words
    spoken without a meaningful pause becomes one phrase. Returns a list of
    {start, end, first_word, last_word} in milliseconds. Repeated-phrase verses
    (where word_index resets) simply yield extra phrases for the repeated audio,
    which is faithful to what is actually recited."""
    phrases = []
    if not words:
        return phrases
    run_start = words[0][1]
    run_first = words[0][0]
    prev_end = words[0][2]
    prev_idx = words[0][0]
    for idx, s, e in words[1:]:
        if s - prev_end >= gap_ms:
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


# Cross-reciter consensus waqf detection (the /waqf comparison page and the
# memorization breathing guide) doesn't use a duration threshold at all: ANY
# nonzero forward gap counts as that reciter's phrase break. Empirically,
# gap==0 is the overwhelming default (~95% of reciter/word pairs across a
# 300-verse sample), so even a 10-40ms gap reflects a real, if brief, pause —
# and a verse-by-verse sweep showed gap_ms=1 reproduces the old 250ms+rescue
# results almost exactly (2/315 verses differed, each gaining one extra solo
# stop at a plausible phrase boundary). Consensus COUNT across reciters is
# what signals a genuine waqf, not how long any one of them paused.
_WAQF_CONSENSUS_GAP_MS = 1


def _build_breathing_guide(surah_number):
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
    cache_key = (surah_number, reciter_ids)
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
        raw = {}
        verse_durs = []
        for rid, entry in present:
            words = entry[1]
            if not words:
                continue
            verse_durs.append((words[-1][2] - words[0][1]) / 1000.0)
            stops_r, repeats_r = _forward_waqf_stops(words, _WAQF_CONSENSUS_GAP_MS)
            raw[rid] = {'stops': stops_r, 'repeats': repeats_r}

        word_reciters = defaultdict(list)   # word_idx -> [reciter_id, ...] (who pauses)
        word_durs = defaultdict(list)       # word_idx -> [cumulative seconds, ...]
        repeats = []                        # [{reciter_id, from_wpos, to_wpos}]
        for rid, info in raw.items():
            for w, dur_ms in info['stops'].items():
                word_reciters[w].append(rid)
                word_durs[w].append(dur_ms / 1000.0)
            for frm, to in info['repeats']:
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
        'reciters': [
            {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')}
            for rid in reciter_ids
        ],
        'verses': verses,
    }
    _memorization_breathing_cache[cache_key] = result
    return result


@memorize_bp.route('/api/memorization/<int:surah_number>/breathing', methods=['GET'])
def get_memorization_breathing(surah_number):
    """Validated 'breathing guide' for a surah: per verse, word positions where
    at least one installed reciter actually pauses, with consensus count and
    average cumulative duration — so a user with a shorter or longer breath can
    pick a real, attested stopping point instead of guessing where to pause."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    try:
        data = _build_breathing_guide(surah_number)
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


def _mark_word_context(verse_key, token_index, span=2):
    """Map a printed-mushaf 1-based DB token_index to the recited-word position
    and a small surrounding context snippet, the way the per-verse comparison
    view does it.

    The waqf DB's token_index is 1-based and COUNTS ornaments (rub‑el‑hizb, the
    ayah-end marker), whereas `_verse_word_texts` drops those — so the index must
    be mapped through raw_to_wpos rather than used directly as a word index, or
    the context lands a word or two past the actual mark. Returns (wpos, context)
    where wpos is the 0-based recited-word index (or None if it can't be mapped).
    """
    _, words, raw_to_wpos = _verse_word_texts(verse_key)
    if not words:
        return None, ''
    wpos = None
    if token_index is not None and 0 <= token_index - 1 < len(raw_to_wpos):
        wpos = raw_to_wpos[token_index - 1]
    if wpos is None:
        # Token mapped to a dropped ornament or fell out of range — clamp the
        # raw index into the recited-word range so context is still sensible.
        ti0 = (token_index - 1) if token_index else 0
        wpos = min(max(ti0, 0), len(words) - 1)
    lo, hi = max(0, wpos - span), min(len(words), wpos + span + 1)
    return wpos, ' '.join(words[lo:hi])


def _build_verse_waqf_detail(surah, ayah):
    """Full per-reciter waqf detail for ONE verse, for the comparison page.

    Returns the verse text/words plus, for every installed reciter, their own
    forward-waqf stops (with each reciter's cumulative time) and repeats, and a
    union view (which reciters align at each stop, and which stops are solo)."""
    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    vk = f"{surah}:{ayah}"
    text, words, raw_to_wpos = _verse_word_texts(vk)

    raw = {}
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
        stops, repeats = _forward_waqf_stops(w, _WAQF_CONSENSUS_GAP_MS)
        raw[rid] = {'w': w, 'stops': stops, 'repeats': repeats, 'full': full}

    per_reciter = {}
    union = defaultdict(lambda: {'reciters': [], 'durs': []})
    for rid, info in raw.items():
        w, stops, repeats = info['w'], info['stops'], info['repeats']
        cfg = MEMORIZATION_RECITERS[rid]
        vstart = w[0][1]
        # The reciter's actual recited phrases IN ORDER (incl. back-ups where
        # they paused then re-read). Lets the UI render each phrase — repeats
        # included — as its own card, faithfully and in recitation order.
        phrases = [
            {'first_wpos': ph['first_word'] - 1, 'last_wpos': ph['last_word'] - 1,
             'start': round((ph['start'] - vstart) / 1000.0, 2),
             'end': round((ph['end'] - vstart) / 1000.0, 2)}
            for ph in _segment_phrases(w, _WAQF_CONSENSUS_GAP_MS)
        ]
        per_reciter[rid] = {
            'name_ar': cfg.get('name_ar', ''),
            'stops': [{'wpos': k - 1, 'time': round(v / 1000.0, 2)} for k, v in sorted(stops.items())],
            'repeats': [{'from_wpos': f - 1, 'to_wpos': t - 1} for f, t in repeats],
            'phrases': phrases,
            'duration': round(info['full'], 2),
            # absolute seek info for in-page segment playback.
            # _yt_ reciters return their per-surah YouTube watch URL; the waqf
            # guide player routes youtube.com URLs through the IFrame adapter
            # (same as the memorize page) instead of a native <audio> element.
            # Catalog-based reciters (_gd_) use direct MP3/Drive-download URLs
            # which native <audio> can stream fine.
            'audio_url': (_gd_audio_url(rid, surah)
                          if cfg.get('audio_tmpl') == '_gd_'
                          else (_yt_audio_url(rid, surah)
                                if cfg.get('audio_tmpl') == '_yt_'
                                else (cfg['audio_tmpl'].format(surah=surah)
                                      if cfg.get('audio_tmpl') else None))),
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

    # Build a broad mushaf-mark lookup (wpos -> {mushaf_id: symbol}) across EVERY
    # printed mushaf we have, so a reciter's solo stop can be validated against
    # any edition's printed waqf — not just the three shown in the matrix.
    mushaf_mark_by_wpos = {}
    for ver in _WAQF_MATCH_MUSHAFS:
        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
            ti = r.get('token_index')
            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                continue
            wpos = raw_to_wpos[ti]
            if wpos is None:
                continue
            mushaf_mark_by_wpos.setdefault(wpos, {})[ver] = r['symbols']

    # Enrich per_reciter with derived fields used by the waqf guide UI:
    #  solo_stops_detail – this reciter's mid-verse stops that NO other reciter
    #                      made (انفرد), each tagged with any printed mushaf that
    #                      prescribes a waqf there (validates the lone stop).
    #  qasr_munfasil     – known Hafs bi-qasr al-munfasil reciters (config), whose
    #                      shorter disconnected madd makes their pace faster.
    for rid, det in per_reciter.items():
        solo_detail = []
        for s in det.get('stops', []):
            wpos = s['wpos']
            u = next((u for u in union_stops if u['wpos'] == wpos), None)
            if u and u['solo']:
                mm = [{'mushaf': mid, 'symbol': sym}
                      for mid, sym in mushaf_mark_by_wpos.get(wpos, {}).items()]
                solo_detail.append({
                    'wpos': wpos,
                    'time': s['time'],
                    'word': words[wpos] if 0 <= wpos < len(words) else '',
                    'mushaf_matches': mm,
                })
        det['solo_stops_detail'] = solo_detail
        det['qasr_munfasil'] = rid in QASR_MUNFASIL_RECITERS

    return {
        'surah': surah,
        'ayah': ayah,
        'verse_key': vk,
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


# Printed mushafs whose waqf marks we compare the reciters against (matrix view).
# ورش (North-African Warsh print) is included too — note its ص = صه = STOP, the
# opposite of the Hafs صلى; the agreement analysis handles that per-mushaf.
_WAQF_COMPARE_MUSHAFS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي', 'قطر', 'الكويت', 'ورش')
# Broader set used only to validate a reciter's *solo* stop against any printed
# waqf (e.g. "انفرد القارئ، لكنه يوافق علامة الأزهر").
_WAQF_MATCH_MUSHAFS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي', 'ورش', 'الهندي', 'قطر', 'الكويت')
# Reciters known to recite Hafs bi-qasr al-munfasil (short disconnected madd) —
# their pace is legitimately faster, surfaced as a badge so the timing reads
# correctly. Keyed by MEMORIZATION_RECITERS id.
QASR_MUNFASIL_RECITERS = {'banna', 'ahmed_amer', 'maasaraawi', 'burhaji', 'shaheen', 'mustafa_ismail'}


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


@breathing_bp.route('/api/waqf/<int:surah>/<int:ayah>', methods=['GET'])
def get_verse_waqf(surah, ayah):
    """Per-verse reciter-waqf comparison: how each installed reciter stops in
    this verse, who aligns vs. who is alone (انفرد), and where they repeat."""
    if not (1 <= surah <= 114) or ayah < 1:
        return jsonify({"error": "Invalid verse."}), 400
    try:
        data = _build_verse_waqf_detail(surah, ayah)
    except Exception as e:
        app.logger.error(f"Waqf detail failed for {surah}:{ayah}: {e}")
        return jsonify({"error": "Waqf data unavailable"}), 503
    if not data['per_reciter']:
        return jsonify({"error": "No data for this verse."}), 404
    return jsonify(data)


_solo_stops_index: dict | None = None


def _build_solo_stops_index():
    """Scan all 114 surahs and collect every reciter's solo stops.

    Returns {reciter_id: [{'surah', 'ayah', 'wpos', 'word', 'context', 'marks'}]}.
    Cached after first computation (data is static at runtime)."""
    global _solo_stops_index
    if _solo_stops_index is not None:
        return _solo_stops_index

    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    per_reciter = defaultdict(list)

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            vk = f"{surah}:{ayah}"
            _, words, raw_to_wpos = _verse_word_texts(vk)
            if not words:
                continue

            mushaf_marks = None
            for stop in vdata.get('stops', []):
                if not stop['solo'] or not stop.get('reciter_ids'):
                    continue
                rid = stop['reciter_ids'][0]
                wpos = stop['wpos']
                if not (0 <= wpos < len(words)):
                    continue

                if mushaf_marks is None:
                    mushaf_marks = {}
                    for ver in _WAQF_MATCH_MUSHAFS:
                        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                            ti = r.get('token_index')
                            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                                continue
                            wp = raw_to_wpos[ti]
                            if wp is not None:
                                mushaf_marks.setdefault(wp, {})[ver] = r['symbols']

                lo, hi = max(0, wpos - 2), min(len(words), wpos + 3)
                per_reciter[rid].append({
                    'surah': surah, 'ayah': ayah, 'wpos': wpos,
                    'word': words[wpos],
                    'context': ' '.join(words[lo:hi]),
                    'marks': mushaf_marks.get(wpos, {}),
                    'has_waqf': bool(mushaf_marks.get(wpos)),
                })

    _solo_stops_index = dict(per_reciter)
    return _solo_stops_index


@breathing_bp.route('/api/waqf-research/solos', methods=['GET'])
def waqf_research_solos():
    """Solo stops (انفرادات) per reciter across the entire Quran.

    GET /api/waqf-research/solos           → summary (counts per reciter)
    GET /api/waqf-research/solos?reciter=X → full list for reciter X"""
    idx = _build_solo_stops_index()
    rid = request.args.get('reciter', '').strip()
    if rid:
        if rid not in MEMORIZATION_RECITERS:
            return jsonify({'error': 'unknown reciter'}), 400
        stops = idx.get(rid, [])
        return jsonify({
            'reciter': {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')},
            'count': len(stops),
            'stops': stops,
        })

    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    return jsonify({
        'reciters': [
            {'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
             'solo_count': len(idx.get(r, []))}
            for r in reciter_ids
        ],
    })


_waqf_stats_cache: dict | None = None


def _build_waqf_stats():
    """Per-surah reciter-divergence stats + top consensus positions."""
    global _waqf_stats_cache
    if _waqf_stats_cache is not None:
        return _waqf_stats_cache

    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    surahs_out = []
    top_divergent = []
    top_consensus = []

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        s_cons, s_div, s_total = 0, 0, 0

        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            rt = vdata.get('reciters_total', 0)
            if rt < 2:
                continue
            v_cons, v_div = 0, 0
            for stop in vdata.get('stops', []):
                s_total += 1
                if stop['reciters'] == rt:
                    v_cons += 1
                else:
                    v_div += 1
            s_cons += v_cons
            s_div += v_div
            if v_div > 0:
                top_divergent.append({'surah': surah, 'ayah': ayah,
                                      'divergent': v_div, 'consensus': v_cons,
                                      'total': v_cons + v_div})
            if v_cons > 0:
                vk = f"{surah}:{ayah}"
                _, words, raw_to_wpos = _verse_word_texts(vk)
                if not words:
                    continue
                mm_by_wpos = {}
                for ver in _WAQF_COMPARE_MUSHAFS:
                    for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                        ti = r.get('token_index')
                        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                            continue
                        wp = raw_to_wpos[ti]
                        if wp is not None:
                            mm_by_wpos.setdefault(wp, {})[ver] = r['symbols']
                for stop in vdata.get('stops', []):
                    if stop['reciters'] == rt:
                        wpos = stop['wpos']
                        mm = mm_by_wpos.get(wpos, {})
                        if mm:
                            lo, hi = max(0, wpos - 2), min(len(words), wpos + 3)
                            top_consensus.append({
                                'surah': surah, 'ayah': ayah, 'wpos': wpos,
                                'word': words[wpos] if 0 <= wpos < len(words) else '',
                                'context': ' '.join(words[lo:hi]),
                                'marks': mm, 'reciters': rt,
                            })

        surahs_out.append({
            'surah': surah, 'name': surah_names.get(surah, ''),
            'consensus': s_cons, 'divergent': s_div, 'total': s_total,
        })

    top_divergent.sort(key=lambda v: v['divergent'], reverse=True)
    top_consensus.sort(key=lambda v: v['reciters'], reverse=True)

    _waqf_stats_cache = {
        'surahs': surahs_out,
        'top_divergent': top_divergent[:80],
        'top_consensus': top_consensus,
    }
    return _waqf_stats_cache


@breathing_bp.route('/api/waqf-research/stats', methods=['GET'])
def waqf_research_stats():
    """Surah-level reciter divergence stats + consensus positions."""
    data = _build_waqf_stats()
    view = request.args.get('view', '').strip()
    if view == 'consensus':
        return jsonify({'consensus': data['top_consensus']})
    return jsonify({'surahs': data['surahs'], 'top_divergent': data['top_divergent']})


_mandatory_cache: dict | None = None


def _build_mandatory_index():
    """All م (mandatory) and لا (forbidden) waqf positions across all mushafs."""
    global _mandatory_cache
    if _mandatory_cache is not None:
        return _mandatory_cache

    versions = list(_WAQF_COMPARE_MUSHAFS)
    cols_sql = ', '.join(f'"{v}"' for v in versions)
    where_m = ' OR '.join(f'"{v}" = ?' for v in versions)

    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        mandatory, forbidden = [], []

        for symbol, target_list in [('م', mandatory), ('لا', forbidden)]:
            cur.execute(
                f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} '
                f'FROM waqf WHERE {where_m} ORDER BY "السورة", "الآية", token_index',
                tuple(symbol for _ in versions)
            )
            for row in cur.fetchall():
                s, a, word, ti = row[0], row[1], row[2], row[3]
                marks = {}
                for i, ver in enumerate(versions):
                    val = row[4 + i]
                    if val:
                        marks[ver] = val
                vk = f"{s}:{a}"
                _, ctx = _mark_word_context(vk, ti)
                if not ctx:
                    ctx = word or ''
                all_same = len(set(marks.values())) == 1 and len(marks) == len(versions)
                target_list.append({
                    'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                    'marks': marks, 'agreement': 'full' if all_same else 'partial',
                })

        # وقف المعانقة (ع) — embracing stop pairs.
        where_ain = ' OR '.join(f'"{v}" = ?' for v in versions)
        cur.execute(
            f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} '
            f'FROM waqf WHERE {where_ain} ORDER BY "السورة", "الآية", token_index',
            tuple('ع' for _ in versions)
        )
        raw_ain = []
        for row in cur.fetchall():
            s, a, word, ti = row[0], row[1], row[2], row[3]
            marks = {}
            for i, ver in enumerate(versions):
                val = row[4 + i]
                if val:
                    marks[ver] = val
            vk = f"{s}:{a}"
            _, ctx = _mark_word_context(vk, ti)
            if not ctx:
                ctx = word or ''
            all_same = len(set(marks.values())) == 1 and len(marks) == len(versions)
            raw_ain.append({
                'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                'marks': marks, 'agreement': 'full' if all_same else 'partial',
            })

        # Group ع marks into pairs (consecutive marks in the same verse).
        embracing = []
        i_ain = 0
        while i_ain < len(raw_ain):
            a1 = raw_ain[i_ain]
            if i_ain + 1 < len(raw_ain) and raw_ain[i_ain + 1]['surah'] == a1['surah'] and raw_ain[i_ain + 1]['ayah'] == a1['ayah']:
                a2 = raw_ain[i_ain + 1]
                vk = f"{a1['surah']}:{a1['ayah']}"
                _, words, _ = _verse_word_texts(vk)
                embracing.append({
                    'surah': a1['surah'], 'ayah': a1['ayah'],
                    'pair': [
                        {'word': a1['word'], 'context': a1['context'], 'marks': a1['marks']},
                        {'word': a2['word'], 'context': a2['context'], 'marks': a2['marks']},
                    ],
                    'agreement': 'full' if a1['agreement'] == 'full' and a2['agreement'] == 'full' else 'partial',
                })
                i_ain += 2
            else:
                embracing.append({
                    'surah': a1['surah'], 'ayah': a1['ayah'],
                    'pair': [{'word': a1['word'], 'context': a1['context'], 'marks': a1['marks']}],
                    'agreement': a1['agreement'],
                })
                i_ain += 1
    finally:
        conn.close()

    _mandatory_cache = {'mandatory': mandatory, 'forbidden': forbidden, 'embracing': embracing}
    return _mandatory_cache


@breathing_bp.route('/api/waqf-research/mandatory', methods=['GET'])
def waqf_research_mandatory():
    """All م (وقف لازم) and لا (وقف ممنوع) positions with mushaf agreement."""
    return jsonify(_build_mandatory_index())


_cross_verse_cache: dict | None = None


def _build_cross_verse_patterns():
    """Find mushaf marks where editions systematically disagree on the same word."""
    global _cross_verse_cache
    if _cross_verse_cache is not None:
        return _cross_verse_cache

    versions = list(_WAQF_COMPARE_MUSHAFS)
    cols_sql = ', '.join(f'"{v}"' for v in versions)

    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        cur.execute(
            f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} FROM waqf '
            f'ORDER BY "السورة", "الآية", token_index'
        )
        # Track per-word-root how each mushaf marks it.
        # "Disagreement" = at least 2 mushafs give different non-empty symbols.
        disagree = []
        for row in cur.fetchall():
            s, a, word, ti = row[0], row[1], row[2], row[3]
            marks = {}
            for i, ver in enumerate(versions):
                val = row[4 + i]
                if val:
                    marks[ver] = val
            if len(marks) < 2:
                continue
            syms = set(marks.values())
            if len(syms) > 1:
                vk = f"{s}:{a}"
                _, ctx = _mark_word_context(vk, ti)
                if not ctx:
                    ctx = word or ''
                disagree.append({
                    'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                    'marks': marks,
                })
    finally:
        conn.close()

    _cross_verse_cache = {'disagreements': disagree, 'count': len(disagree)}
    return _cross_verse_cache


@breathing_bp.route('/api/waqf-research/patterns', methods=['GET'])
def waqf_research_patterns():
    """Cross-verse mushaf disagreement patterns."""
    return jsonify(_build_cross_verse_patterns())


# ── Precomputed research caches ─────────────────────────────────────────────
# The Quran-wide analyses (clustering, similarity, agreement, ibtidaa) cost
# seconds of CPU on first request. pipeline/precompute_research.py bakes them
# to data/research_cache/*.json at build time; the builders below load the
# baked file when present and only compute as a fallback (or when the
# precompute script itself runs, signalled by RESEARCH_PRECOMPUTE=1).
_RESEARCH_CACHE_DIR = os.path.join(_BASE_DIR, 'data', 'research_cache')


def _load_research_cache(name):
    if os.environ.get('RESEARCH_PRECOMPUTE'):
        return None                       # precompute run: always compute fresh
    path = os.path.join(_RESEARCH_CACHE_DIR, f'{name}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return _json_load(f)
    except Exception as e:
        app.logger.warning(f'research cache {name} unreadable, recomputing: {e}')
        return None


_clustering_cache: dict | None = None


def _build_reciter_clustering():
    """Cluster reciters by how similar their waqf patterns are.

    For each pair of installed reciters, compute a similarity score based on
    how often they breathe at the same word across all verses.  Returns a
    ranked list of pairs (most similar first) and per-reciter groups."""
    global _clustering_cache
    if _clustering_cache is not None:
        return _clustering_cache
    disk = _load_research_cache('clustering')
    if disk is not None:
        _clustering_cache = disk
        return disk

    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    # Build per-reciter breath set: all word positions where they breathe
    # (forward stop OR repeat from_wpos), keyed as "surah:ayah:wpos".
    breath_sets: dict[str, set] = {rid: set() for rid in reciter_ids}

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            for stop in vdata.get('stops', []):
                for rid in stop.get('reciter_ids', []):
                    breath_sets[rid].add(f"{surah}:{ayah_str}:{stop['wpos']}")
            for rp in vdata.get('repeats', []):
                rid = rp.get('reciter_id')
                if rid:
                    breath_sets[rid].add(f"{surah}:{ayah_str}:{rp['from_wpos']}")

    # Jaccard similarity for every pair → a full symmetric matrix.
    sim = {r: {r: 1.0 for r in reciter_ids} for r in reciter_ids}
    pairs = []
    for i, r1 in enumerate(reciter_ids):
        s1 = breath_sets[r1]
        for r2 in reciter_ids[i + 1:]:
            s2 = breath_sets[r2]
            inter = len(s1 & s2)
            union = len(s1 | s2)
            s = round(inter / union, 3) if union else 0.0
            sim[r1][r2] = sim[r2][r1] = s
            pairs.append({
                'r1': r1, 'r2': r2,
                'n1': MEMORIZATION_RECITERS[r1].get('name_ar', ''),
                'n2': MEMORIZATION_RECITERS[r2].get('name_ar', ''),
                'similarity': s, 'shared': inter, 'union': union,
            })
    pairs.sort(key=lambda p: p['similarity'], reverse=True)
    sim_values = [p['similarity'] for p in pairs]
    lo = min(sim_values) if sim_values else 0.0
    hi = max(sim_values) if sim_values else 1.0

    # Order reciters so similar ones sit next to each other (a greedy nearest-
    # neighbour chain seeded at the most "central" reciter). This turns the
    # matrix into a heat-map where clusters show up as bright blocks.
    avg_sim = {r: sum(sim[r][o] for o in reciter_ids if o != r) / max(1, len(reciter_ids) - 1)
               for r in reciter_ids}
    order = [max(reciter_ids, key=lambda r: avg_sim[r])]
    remaining = set(reciter_ids) - set(order)
    while remaining:
        last = order[-1]
        nxt = max(remaining, key=lambda r: sim[last][r])
        order.append(nxt)
        remaining.discard(nxt)

    # Clusters: union-find linking pairs whose similarity is in the top tier
    # (≥ mean + 0.5·std). Reveals the natural groupings across the whole Quran.
    mean = sum(sim_values) / len(sim_values) if sim_values else 0.0
    var = sum((x - mean) ** 2 for x in sim_values) / len(sim_values) if sim_values else 0.0
    thr = round(mean + 0.5 * (var ** 0.5), 3)
    parent = {r: r for r in reciter_ids}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        if p['similarity'] >= thr:
            parent[_find(p['r1'])] = _find(p['r2'])
    cluster_map = defaultdict(list)
    for r in reciter_ids:
        cluster_map[_find(r)].append(r)
    clusters = []
    for members in cluster_map.values():
        # intra-cluster average similarity (cohesion)
        if len(members) > 1:
            cs = [sim[a][b] for i, a in enumerate(members) for b in members[i + 1:]]
            cohesion = round(sum(cs) / len(cs), 3)
        else:
            cohesion = 0.0
        clusters.append({
            'members': [{'id': m, 'name_ar': MEMORIZATION_RECITERS[m].get('name_ar', '')} for m in members],
            'size': len(members), 'cohesion': cohesion,
        })
    clusters.sort(key=lambda c: (-c['size'], -c['cohesion']))

    # Per-reciter nearest & farthest peer (for the "who reads like whom" summary).
    profiles = []
    for r in reciter_ids:
        others = [(o, sim[r][o]) for o in reciter_ids if o != r]
        nearest = max(others, key=lambda t: t[1])
        farthest = min(others, key=lambda t: t[1])
        profiles.append({
            'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
            'total_breaths': len(breath_sets[r]),
            'qasr': r in QASR_MUNFASIL_RECITERS,
            'nearest': {'id': nearest[0], 'name_ar': MEMORIZATION_RECITERS[nearest[0]].get('name_ar', ''), 'similarity': nearest[1]},
            'farthest': {'id': farthest[0], 'name_ar': MEMORIZATION_RECITERS[farthest[0]].get('name_ar', ''), 'similarity': farthest[1]},
        })

    _clustering_cache = {
        'order': [{'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
                   'qasr': r in QASR_MUNFASIL_RECITERS} for r in order],
        'matrix': {r: sim[r] for r in reciter_ids},
        'range': {'min': lo, 'max': hi},
        'pairs': pairs[:12],
        'different': list(reversed(pairs[-8:])),
        'clusters': clusters,
        'cluster_threshold': thr,
        'profiles': profiles,
    }
    return _clustering_cache


@breathing_bp.route('/api/waqf-research/clustering', methods=['GET'])
def waqf_research_clustering():
    """Reciter similarity clustering based on waqf/breath patterns."""
    return jsonify(_build_reciter_clustering())


_mushaf_sim_cache: dict | None = None


def _mushaf_sem_class(version, raw):
    """Normalise a printed mushaf's raw waqf symbol to WHAT IT TELLS THE RECITER
    TO DO, so different notations can be compared by meaning rather than glyph.

    Key subtleties: ورش's ص is صه = STOP (the opposite of حفص's صلى = prefer to
    continue); ورش's lone ر is رأس آية (verse end), not a waqf ruling; الأزهر
    writes every discretionary stop as ج; الهندي uses the IndoPak glyph set."""
    raw = (raw or '').strip()
    if not raw:
        return None
    if 'ورش' in version:
        base = raw.split(',')[0].strip()
        if base in ('ر', '۝') and 'ص' not in raw:
            return None                      # رأس آية only — not a stop ruling
        return 'STOP'                        # صه = قف هنا
    if version == 'الهندي':
        return {
            'ۙ': 'NOSTOP', 'ۚ': 'CHOICE', 'ۘ': 'MUST',
            'ۗ': 'STOP', 'ۖ': 'CONT', 'ؕ': 'ABS',
            'ؗ': 'CHOICE', 'ۜ': 'SAKTA',
        }.get(raw[0])                        # leading IndoPak glyph; rare marks → None
    base = raw.split(',')[0].strip()
    return {'م': 'MUST', 'ق': 'STOP', 'ص': 'CONT', 'ج': 'CHOICE',
            'لا': 'NOSTOP', 'ع': 'EMBRACE', 'س': 'SAKTA'}.get(base)


# Canonical waqf marks (display order) → glyph + meaning. ورش/الهندي use their
# own systems and are compared by MEANING, not by these symbols.
_MARK_INFO = [
    ('م',  'ۘ', 'لازم — يجب الوقف، والوصل قد يُحيل المعنى'),
    ('ق',  'ۗ', 'الوقف أولى (قلى) — يُفضّل الوقف'),
    ('ص',  'ۖ', 'الوصل أولى (صلى) — يُفضّل الوصل'),
    ('ج',  'ۚ', 'جائز — يستوي الوقف والوصل'),
    ('لا', 'ۙ', 'لا وقف — لا يُوقف عليه (وقفٌ قبيح)'),
    ('ع',  'ۛ', 'المعانقة — يقف على أحد الموضعين فقط'),
    ('س',  'ۜ', 'سكتة — وقفة يسيرة بلا تنفّس'),
]
_MARK_SET = {m for m, _, _ in _MARK_INFO}
_AR_DIGITS = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')
_to_arabic_digits = lambda n: str(n).translate(_AR_DIGITS)
_mushaf_pos_data: dict | None = None   # per-position raw/sem/verse, for the diff endpoint


def _mushaf_base_mark(raw):
    """Leading canonical mark of a raw DB value ('ر,ص' → 'ر', 'قلى'→'ق' etc.)."""
    raw = (raw or '').strip()
    if not raw:
        return ''
    return raw.split(',')[0].strip()


def _build_mushaf_similarity(force_compute=False):
    """Compare the printed mushafs' waqf systems to each other across the whole
    Quran. Two lenses: PLACEMENT (do they put a stop at the same word at all) and
    MEANING (same word AND same ruling, after normalising notation). Returns the
    matrices, the ranked closest pairs, an average-linkage dendrogram, the
    per-mark consensus among the standard prints, and a 'what makes each special'
    profile."""
    global _mushaf_sim_cache, _mushaf_pos_data
    if force_compute and _mushaf_pos_data is None:
        _mushaf_sim_cache = None          # disk cache lacks the per-position data
    if _mushaf_sim_cache is not None:
        return _mushaf_sim_cache
    if not force_compute:
        disk = _load_research_cache('mushaf_similarity')
        if disk is not None:
            _mushaf_sim_cache = disk
            return disk

    versions = sorted(_get_mushaf_version_whitelist())
    place: dict[str, set] = {v: set() for v in versions}
    sem: dict[str, dict] = {v: {} for v in versions}
    raw_by: dict[str, dict] = {v: {} for v in versions}   # pos -> raw DB symbol
    verse_of: dict = {}                                    # pos -> (surah, ayah, word)

    if os.path.exists(MUSHAF_WAQF_DATABASE):
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        try:
            cols = ', '.join('"' + v.replace('"', '""') + '"' for v in versions)
            cur = conn.execute(
                f'SELECT token_index, word_index, "السورة", "الآية", "الكلمة", {cols} FROM waqf')
            col_names = [d[0] for d in cur.description]
            vi = {v: col_names.index(v) for v in versions}
            for row in cur.fetchall():
                # token_index/word_index reset every verse, so they are NOT unique
                # on their own — key each position by (surah, ayah, word_index).
                pos = (row[2], row[3], row[1])
                verse_of[pos] = (row[2], row[3], row[4])
                for v in versions:
                    raw = row[vi[v]]
                    if raw and str(raw).strip():
                        raw = str(raw).strip()
                        place[v].add(pos)
                        raw_by[v][pos] = raw
                        cls = _mushaf_sem_class(v, raw)
                        if cls:
                            sem[v][pos] = cls
        finally:
            conn.close()

    std = [v for v in versions if v not in ('ورش', 'الهندي')]   # standard Arabic-symbol prints
    _mushaf_pos_data = {'versions': versions, 'std': std, 'raw': raw_by, 'sem': sem,
                        'verse': verse_of}

    def jac(a, b):
        A, B = place[a], place[b]
        u = len(A | B)
        return round(len(A & B) / u, 3) if u else 0.0

    def meaning(a, b):
        A, B = set(sem[a]), set(sem[b])
        u = len(A | B)
        if not u:
            return 0.0
        same = sum(1 for p in (A & B) if sem[a][p] == sem[b][p])
        return round(same / u, 3)

    place_m = {a: {b: (1.0 if a == b else jac(a, b)) for b in versions} for a in versions}
    mean_m = {a: {b: (1.0 if a == b else meaning(a, b)) for b in versions} for a in versions}

    pairs = []
    for i, a in enumerate(versions):
        for b in versions[i + 1:]:
            pairs.append({'a': a, 'b': b, 'meaning': mean_m[a][b], 'place': place_m[a][b]})
    pairs.sort(key=lambda p: (p['meaning'], p['place']), reverse=True)

    # Average-linkage agglomerative clustering on the MEANING distance (1 − sim).
    dist = {(a, b): 1 - mean_m[a][b] for a in versions for b in versions}
    clusters = {v: {'type': 'leaf', 'id': v, 'name': v, 'members': [v]} for v in versions}

    def cdist(ca, cb):
        vals = [dist[(a, b)] for a in ca['members'] for b in cb['members']]
        return sum(vals) / len(vals)

    nid = 0
    while len(clusters) > 1:
        ks = list(clusters)
        best = None
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                d = cdist(clusters[ks[i]], clusters[ks[j]])
                if best is None or d < best[0]:
                    best = (d, ks[i], ks[j])
        d, ka, kb = best
        ca, cb = clusters.pop(ka), clusters.pop(kb)
        clusters[f'_n{nid}'] = {
            'type': 'node', 'height': round(d, 3), 'similarity': round(1 - d, 3),
            'children': [ca, cb], 'members': ca['members'] + cb['members'],
        }
        nid += 1
    tree = next(iter(clusters.values())) if clusters else None

    def leaf_order(node, out):
        if node is None:
            return
        if node['type'] == 'leaf':
            out.append(node['id'])
        else:
            for ch in node['children']:
                leaf_order(ch, out)
    order = []
    leaf_order(tree, order)

    # ── Per-mark consensus among the STANDARD prints ────────────────────────
    # Canonical mark per position for each standard print, then per position the
    # plurality mark + how many agree. Bucketed by mark → positions + agreement.
    std_mark = {v: {p: _mushaf_base_mark(r) for p, r in raw_by[v].items()
                    if _mushaf_base_mark(r) in _MARK_SET} for v in std}
    all_std_pos = set().union(*[set(std_mark[v]) for v in std]) if std else set()
    agg = {m: [0, 0.0] for m, _, _ in _MARK_INFO}
    for p in all_std_pos:
        votes = Counter(std_mark[v][p] for v in std if p in std_mark[v])
        if not votes:
            continue
        top, topn = votes.most_common(1)[0]
        agg[top][0] += 1
        agg[top][1] += topn / sum(votes.values())
    mark_consensus = []
    for m, glyph, desc in _MARK_INFO:
        npos, sa = agg[m]
        mark_consensus.append({
            'sym': m, 'glyph': glyph, 'desc': desc,
            'positions': npos,
            'agreement': round(sa / npos, 3) if npos else 0.0,
            'counts': {v: sum(1 for p in std_mark[v] if std_mark[v][p] == m) for v in std},
        })

    # ── What makes each mushaf special ──────────────────────────────────────
    profiles = []
    max_la = max((sum(1 for x in std_mark.get(v, {}).values() if x == 'لا') for v in std), default=0)
    max_q = max((sum(1 for x in std_mark.get(v, {}).values() if x == 'ق') for v in std), default=0)
    for v in versions:
        cnt = Counter()
        for p, r in raw_by[v].items():
            b = _mushaf_base_mark(r)
            cnt[b] += 1
        special = []
        system = 'standard'
        if v == 'ورش':
            system = 'warsh'
            special.append('رواية ورش — «ص» تعني صه أي «قِف» (عكس صلى عند حفص)، و«ر» رأس آية في عدّ ورش.')
            special.append('نظامٌ مختلف عن حفص؛ يضع الوقف في مواضع متقاربة لكنه يحكم عليها بحكمٍ آخر.')
        elif v == 'الهندي':
            system = 'indopak'
            special.append('النظام الباكستاني (IndoPak) برموزٍ مختلفة كليًّا (ؕ ۚ ۙ ؗ …) — لا يقارَن رمزًا برمز.')
        else:
            nb_la, nb_q, nb_s, nb_j = cnt.get('لا', 0), cnt.get('ق', 0), cnt.get('ص', 0), cnt.get('ج', 0)
            if nb_q == 0 and nb_s == 0 and nb_j > 0:
                special.append('يوحّد كل وقفٍ اختياري في علامة «ج» — لا يفرّق بين قلى (الوقف أولى) وصلى (الوصل أولى).')
            if nb_la == 0:
                special.append('أسقط علامة «لا وقف» تمامًا — لا يَسِمها في أي موضع.')
            else:
                extra = ' (أكثر المصاحف)' if nb_la == max_la and max_la > 0 else ''
                special.append(f'يحافظ على علامة «لا وقف» في {_to_arabic_digits(nb_la)} موضعًا{extra} — حيث أسقطها بعض المطبوعات.')
            if nb_q > 0 and nb_q == max_q and max_q > 0:
                special.append(f'أكثرها استعمالًا لـ«قلى» (الوقف أولى): {_to_arabic_digits(nb_q)} موضعًا.')
        # lone-dissenter positions (only among standard prints): where this print's
        # ruling differs from every other standard print that marks the same word.
        lone = 0
        if v in std_mark:
            for p, m in std_mark[v].items():
                others = [std_mark[o][p] for o in std if o != v and p in std_mark[o]]
                if others and all(o != m for o in others):
                    lone += 1
            if lone:
                special.append(f'ينفرد بحكمٍ يخالف بقيّة المصاحف القياسية في {_to_arabic_digits(lone)} موضعًا.')
        profiles.append({
            'id': v, 'system': system, 'total': len(place[v]), 'lone': lone,
            'counts': {m: cnt.get(m, 0) for m, _, _ in _MARK_INFO},
            'special': special,
        })

    _mushaf_sim_cache = {
        'mushafs': versions,
        'standard': std,
        'order': order or versions,
        'meaning_matrix': mean_m,
        'place_matrix': place_m,
        'counts': {v: len(place[v]) for v in versions},
        'pairs': pairs,
        'tree': tree,
        'marks': [m for m, _, _ in _MARK_INFO],
        'mark_consensus': mark_consensus,
        'profiles': profiles,
    }
    return _mushaf_sim_cache


def _mushaf_diff(a, b, limit=200):
    """Every word where two mushafs give a DIFFERENT waqf ruling, with verse refs
    for drill-down. Grouped by the kind of disagreement (a's mark → b's mark)."""
    _build_mushaf_similarity(force_compute=True)   # ensure per-position data exists
    d = _mushaf_pos_data or {}
    raw_by, sem, verse = d.get('raw', {}), d.get('sem', {}), d.get('verse', {})
    if a not in raw_by or b not in raw_by:
        return None
    positions = set(sem.get(a, {})) | set(sem.get(b, {}))
    items, groups = [], Counter()
    same = 0
    for p in positions:
        ca, cb = sem[a].get(p), sem[b].get(p)
        if ca and cb and ca == cb:
            same += 1
            continue
        sa_, ay, word = verse.get(p, (None, None, ''))
        ra = raw_by[a].get(p, '')
        rb = raw_by[b].get(p, '')
        groups[(ra or '∅', rb or '∅')] += 1
        items.append({'surah': sa_, 'ayah': ay, 'word': word,
                      'a_sym': ra, 'b_sym': rb, 'wpos_key': p})
    items.sort(key=lambda it: ((it['surah'] or 0), (it['ayah'] or 0)))
    union = len(positions)
    return {
        'a': a, 'b': b,
        'meaning': round(same / union, 3) if union else 0.0,
        'differences': len(items),
        'shown': min(limit, len(items)),
        'capped': len(items) > limit,
        'groups': [{'a_sym': k[0], 'b_sym': k[1], 'count': n}
                   for k, n in groups.most_common()],
        'verses': [{'surah': it['surah'], 'ayah': it['ayah'], 'word': it['word'],
                    'a_sym': it['a_sym'], 'b_sym': it['b_sym']} for it in items[:limit]],
    }


@breathing_bp.route('/api/waqf-research/mushaf-similarity', methods=['GET'])
def waqf_research_mushaf_similarity():
    """How close the printed mushafs' waqf systems are to one another."""
    return jsonify(_build_mushaf_similarity())


@breathing_bp.route('/api/waqf-research/mushaf-diff', methods=['GET'])
def waqf_research_mushaf_diff():
    """Word-by-word differences between two mushafs' waqf rulings."""
    a = request.args.get('a', '')
    b = request.args.get('b', '')
    if not (_is_valid_mushaf_version(a) and _is_valid_mushaf_version(b)) or a == b:
        return jsonify({'error': 'invalid mushaf pair'}), 400
    res = _mushaf_diff(a, b)
    if res is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify(res)


_ibtidaa_cache: dict | None = None


def _build_ibtidaa_index():
    """الابتداء — empirically-attested 'back-up and re-read' points.

    When a reciter pauses after a word and then RESUMES from an earlier word
    (rather than continuing forward), they are demonstrating ابتداء بما قبله:
    stopping on that word was improper enough (وقف قبيح / breaks the meaning) that
    they restart from before it. We harvest every such back-up across the Quran
    from the reciters' own audio (the `repeats` already computed by the breathing
    guide) and aggregate by position. Spots where SEVERAL reciters independently
    back up are the strongest evidence that الابتداء should be from before — a
    purely attested signal, never an invented rule."""
    global _ibtidaa_cache
    if _ibtidaa_cache is not None:
        return _ibtidaa_cache
    disk = _load_research_cache('ibtidaa')
    if disk is not None:
        _ibtidaa_cache = disk
        return disk

    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    # key (surah, ayah, from_wpos, to_wpos) -> set of reciter ids
    agg: dict[tuple, set] = defaultdict(set)

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            for rp in vdata.get('repeats', []):
                rid = rp.get('reciter_id')
                frm, to = rp.get('from_wpos'), rp.get('to_wpos')
                if rid is None or frm is None or to is None or to > frm:
                    continue
                agg[(surah, ayah, frm, to)].add(rid)

    items = []
    for (surah, ayah, frm, to), rids in agg.items():
        vk = f"{surah}:{ayah}"
        _, words, raw_to_wpos = _verse_word_texts(vk)
        if not words or not (0 <= to <= frm < len(words)):
            continue
        lo, hi = max(0, to - 1), min(len(words), frm + 2)
        # Is there ANY printed mushaf that marks a waqf on the word they paused
        # at? token_index is in the raw-split basis (counts ornaments), so map it
        # through raw_to_wpos before comparing to the recited-word position frm.
        stop_marked = False
        for ver in _WAQF_MATCH_MUSHAFS:
            for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                ti = r.get('token_index')
                if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                    continue
                if raw_to_wpos[ti] == frm:
                    stop_marked = True
                    break
            if stop_marked:
                break
        items.append({
            'surah': surah, 'ayah': ayah,
            'name': surah_names.get(surah, ''),
            'stop_word': words[frm],
            'resume_word': words[to],
            'back_distance': frm - to,
            'context': ' '.join(words[lo:hi]),
            'reciters': sorted(MEMORIZATION_RECITERS[r].get('name_ar', r) for r in rids),
            'count': len(rids),
            'stop_marked': stop_marked,
        })

    # Multi-reciter back-ups first (strongest ابتداء-بما-قبله evidence), then by
    # how far back they go, then mushaf order.
    items.sort(key=lambda x: (-x['count'], -x['back_distance'], x['surah'], x['ayah']))
    multi = sum(1 for x in items if x['count'] >= 2)
    _ibtidaa_cache = {'count': len(items), 'multi_reciter': multi, 'items': items}
    return _ibtidaa_cache


@breathing_bp.route('/api/waqf-research/ibtidaa', methods=['GET'])
def waqf_research_ibtidaa():
    """الابتداء: attested 'back-up and re-read' points harvested from reciter audio."""
    return jsonify(_build_ibtidaa_index())


# السكتات (obligatory brief pauses-without-breath) in Hafs ʿan ʿAsim. Unlike a
# waqf these are FIXED, well-established positions — not derived from audio — so
# they are a curated reference. The four السكتات الواجبة come from the
# Shāṭibiyyah; «مَالِيَهۡ هَلَكَ» is the fifth, read by Hafs with two valid wajh
# (السكت with iẓhār, or idghām). Each carries the riwāyah's reason for the sakta.
HAFS_SAKTAT = [
    {
        'surah': 18, 'ayah': 1, 'wpos': 10, 'on_word': 'عِوَجَا',
        'next': {'surah': 18, 'ayah': 2, 'wpos': 0}, 'next_word': 'قَيِّمٗا',
        'category': 'واجبة', 'cross_verse': True,
        'reason': 'لئلّا يُتوهَّم أنّ «قَيِّمٗا» صفةٌ لـ«عِوَجَا»؛ فالسكتة تُبيّن أنّ '
                  'الكلام تمّ عند نفي العِوَج، و«قَيِّمٗا» حالٌ مستأنفة.',
    },
    {
        'surah': 36, 'ayah': 52, 'wpos': 5, 'on_word': 'مَّرۡقَدِنَا',
        'next': {'surah': 36, 'ayah': 52, 'wpos': 6}, 'next_word': 'هَٰذَا',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'للفصل بين كلام الكفّار «مَن بَعَثَنَا مِن مَّرۡقَدِنَا» وجواب '
                  'الملائكة والمؤمنين «هَٰذَا مَا وَعَدَ ٱلرَّحۡمَٰنُ».',
    },
    {
        'surah': 75, 'ayah': 27, 'wpos': 1, 'on_word': 'مَنۡ',
        'next': {'surah': 75, 'ayah': 27, 'wpos': 2}, 'next_word': 'رَاقٖ',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'لإظهار النون ومنع إدغامها في الراء؛ إذ لو وُصِلت لأُدغمت «مَن رَاقٍ» '
                  'فالتبس بيان الكلمتين.',
    },
    {
        'surah': 83, 'ayah': 14, 'wpos': 1, 'on_word': 'بَلۡ',
        'next': {'surah': 83, 'ayah': 14, 'wpos': 2}, 'next_word': 'رَانَ',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'لإظهار اللام ومنع إدغامها في الراء «بَلۡ رَانَ»، حفاظًا على بيان «بَلۡ».',
    },
    {
        'surah': 69, 'ayah': 28, 'wpos': 3, 'on_word': 'مَالِيَهۡ',
        'next': {'surah': 69, 'ayah': 29, 'wpos': 0}, 'next_word': 'هَلَكَ',
        'category': 'جائزة', 'cross_verse': True,
        'reason': 'بإظهار هاء السكت ومنع إدغامها في الهاء بعدها. وفيها لحفص وجهان: '
                  'السكت (مع الإظهار) والإدغام، وكلاهما صحيح.',
    },
]


@breathing_bp.route('/api/waqf-research/saktat', methods=['GET'])
def waqf_research_saktat():
    """السكتات: the fixed obligatory (and one optional) saktat in Hafs ʿan ʿAsim,
    each with the verse context and the riwāyah's reason for the pause."""
    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    out = []
    for sk in HAFS_SAKTAT:
        vk = f"{sk['surah']}:{sk['ayah']}"
        _, words, _ = _verse_word_texts(vk)
        lo, hi = max(0, sk['wpos'] - 2), min(len(words), sk['wpos'] + 2)
        context = ' '.join(words[lo:hi]) if words else ''
        out.append({**sk, 'name': surah_names.get(sk['surah'], ''), 'context': context})
    return jsonify({
        'count': len(out),
        'obligatory': sum(1 for x in out if x['category'] == 'واجبة'),
        'saktat': out,
    })


_mushaf_agreement_cache: dict | None = None


# Per-mushaf waqf-mark systems (directive + display glyph). Most follow the Hafs
# Sajāwandī set. ورش (the North-African Warsh print) uses ص = صه = STOP — the
# OPPOSITE of the Hafs صلى — and الأزهر marks every discretionary stop with ج
# (no قلى/صلى), so the columns differ per mushaf. dir: 'stop' ⇒ the reciter
# agrees by stopping; 'nostop' ⇒ agrees by continuing; 'choice' (ج, جائز) ⇒ no
# right/wrong — we instead measure his STOP-RATE, which reveals whether he
# treats the جائز like قلى (often stops) or like صلى (usually connects).
_JAIZ_MARK = {'sym': 'ج', 'dir': 'choice', 'name': 'جائز', 'glyph': 'ۚ'}
_HAFS_AGREE_MARKS = [
    {'sym': 'م',  'dir': 'stop',   'name': 'لازم',   'glyph': 'ۘ'},
    {'sym': 'ق',  'dir': 'stop',   'name': 'قلى',    'glyph': 'ۗ'},
    {'sym': 'ص',  'dir': 'nostop', 'name': 'صلى',    'glyph': 'ۖ'},
    {'sym': 'لا', 'dir': 'nostop', 'name': 'لا وقف', 'glyph': 'ۙ'},
    _JAIZ_MARK,
]
MUSHAF_AGREE_MARKS = {
    'المدينة الجديد': _HAFS_AGREE_MARKS,
    'المدينة القديم': _HAFS_AGREE_MARKS,
    'الشمرلي': _HAFS_AGREE_MARKS,
    'قطر':     _HAFS_AGREE_MARKS,
    'الكويت':  _HAFS_AGREE_MARKS,
    'الأزهر': [
        {'sym': 'م',  'dir': 'stop',   'name': 'لازم',   'glyph': 'ۘ'},
        {'sym': 'لا', 'dir': 'nostop', 'name': 'لا وقف', 'glyph': 'ۙ'},
        _JAIZ_MARK,
    ],
    'ورش': [
        {'sym': 'ص', 'dir': 'stop', 'name': 'صه', 'glyph': 'ۖ'},
    ],
}
_AGREE_CASE_CAP = 400   # max disagreement verses stored per (mushaf, reciter, mark)


def _agree_canonical_mark(ver, sym):
    """Map a raw DB symbol to this mushaf's canonical mark sym, or None to skip."""
    sym = (sym or '').strip()
    if ver == 'ورش':
        # ر = رأس آية (verse-end marker in the Warsh riwāyah), not a waqf
        # directive — skip it (and the 'ر,ص' verse-end cells). Only صه counts.
        if 'ر' in sym:
            return None
        return 'ص' if 'ص' in sym else None
    if sym == 'ج':
        return 'ج'
    return sym if sym in ('م', 'ق', 'ص', 'لا') else None


def _build_mushaf_agreement_index():
    """اتفاق القرّاء مع المصاحف — how each reciter's actual stopping behaviour
    agrees with each printed mushaf's waqf marks, Quran-wide.

    Directive is PER MUSHAF (see MUSHAF_AGREE_MARKS): a reciter "agrees" at a mark
    when his behaviour matches that mark's directive. Tallied per mark type, not
    blended, because م/ق are honoured almost universally while ص is where reciters
    genuinely differ and لا surfaces rare violations. Also records, per cell, the
    verses where the reciter DISAGREED (خالف العلامة) for drill-down, capped.

    "Stops here" uses the breathing guide's per-reciter forward stops at
    _WAQF_CONSENSUS_GAP_MS = 1 ms (same as the reciter cards)."""
    global _mushaf_agreement_cache
    if _mushaf_agreement_cache is not None:
        return _mushaf_agreement_cache
    disk = _load_research_cache('mushaf_agreement')
    if disk is not None:
        _mushaf_agreement_cache = disk
        return disk

    versions = list(_WAQF_COMPARE_MUSHAFS)
    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    cfg_of = {v: MUSHAF_AGREE_MARKS.get(v, _HAFS_AGREE_MARKS) for v in versions}
    dir_of = {v: {m['sym']: m['dir'] for m in cfg_of[v]} for v in versions}

    # [ver][rid][sym] = [agree, total]; cases[ver][rid][sym] = [vk, ...]
    agree = {v: {r: {m['sym']: [0, 0] for m in cfg_of[v]} for r in reciter_ids} for v in versions}
    cases = {v: {r: {m['sym']: [] for m in cfg_of[v]} for r in reciter_ids} for v in versions}
    jaiz = {v: 0 for v in versions}

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        present = [r['id'] for r in guide.get('reciters', [])]
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            stoppers = defaultdict(set)   # wpos → reciters who forward-stop there
            for st in vdata.get('stops', []):
                for rid in st.get('reciter_ids', []):
                    stoppers[st['wpos']].add(rid)
            vk = f"{surah}:{ayah}"
            _, words, raw_to_wpos = _verse_word_texts(vk)
            if not words:
                continue
            for ver in versions:
                for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                    ti = r.get('token_index')
                    if ti is None or not (0 <= ti < len(raw_to_wpos)):
                        continue
                    wp = raw_to_wpos[ti]
                    if wp is None:
                        continue
                    csym = _agree_canonical_mark(ver, r.get('symbols'))
                    if csym is None or csym not in dir_of[ver]:
                        continue
                    directive = dir_of[ver][csym]
                    here = stoppers.get(wp, ())
                    if csym == 'ج':
                        jaiz[ver] += 1
                    if directive == 'choice':
                        # ج: no right/wrong — cell[0] counts how often he STOPS
                        # (his stop-rate), and the cases list his stop choices.
                        for rid in present:
                            cell = agree[ver][rid][csym]
                            cell[1] += 1
                            if rid in here:
                                cell[0] += 1
                                lst = cases[ver][rid][csym]
                                if len(lst) < _AGREE_CASE_CAP and (not lst or lst[-1] != vk):
                                    lst.append(vk)
                        continue
                    want_stop = directive == 'stop'
                    for rid in present:
                        cell = agree[ver][rid][csym]
                        cell[1] += 1
                        if (rid in here) == want_stop:
                            cell[0] += 1
                        else:
                            lst = cases[ver][rid][csym]
                            # de-dup consecutive (a verse with >1 same-type mark)
                            if len(lst) < _AGREE_CASE_CAP and (not lst or lst[-1] != vk):
                                lst.append(vk)

    _mushaf_agreement_cache = {
        'mushafs': versions,
        'mark_config': {v: cfg_of[v] for v in versions},
        'gap_ms': _WAQF_CONSENSUS_GAP_MS,
        'reciters': [{'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', r),
                      'qasr': r in QASR_MUNFASIL_RECITERS} for r in reciter_ids],
        'agreement': agree,
        'jaiz': jaiz,
        '_cases': cases,
    }
    return _mushaf_agreement_cache


@breathing_bp.route('/api/waqf-research/mushaf-agreement', methods=['GET'])
def waqf_research_mushaf_agreement():
    """اتفاق القرّاء مع المصاحف: per-reciter, per-mushaf agreement by mark type."""
    data = _build_mushaf_agreement_index()
    return jsonify({k: v for k, v in data.items() if k != '_cases'})


@breathing_bp.route('/api/waqf-research/mushaf-agreement/cases', methods=['GET'])
def waqf_research_mushaf_agreement_cases():
    """The verses where a reciter خالف a mushaf's waqf mark (drill-down).
    Params: mushaf, reciter, mark (one of م/ق/ص/لا)."""
    data = _build_mushaf_agreement_index()
    ver = request.args.get('mushaf', '')
    rid = request.args.get('reciter', '')
    mark = request.args.get('mark', '')
    try:
        vks = data['_cases'][ver][rid][mark]
    except KeyError:
        return jsonify({'error': 'unknown mushaf/reciter/mark'}), 400
    cell = data['agreement'][ver][rid][mark]
    directive = next((m['dir'] for m in data['mark_config'][ver] if m['sym'] == mark), None)
    # ج (choice): the recorded cases are his STOP choices (cell[0]); for the
    # other marks they are disagreements (total − agreed).
    total = cell[0] if directive == 'choice' else cell[1] - cell[0]
    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    verses = []
    for vk in vks:
        s, a = vk.split(':')
        verses.append({'surah': int(s), 'ayah': int(a), 'name': surah_names.get(int(s), '')})
    return jsonify({
        'mushaf': ver, 'reciter': rid, 'mark': mark,
        'directive': directive,
        'disagreed': total, 'shown': len(verses), 'capped': total > len(verses),
        'verses': verses,
    })


_waqf_research_cache: _BoundedLRU = _BoundedLRU(maxsize=256)


def _before_word_marks(s, a, i, words, marks_by_wpos):
    """Resolve waqf marks for the word preceding position *i*.

    When i > 0, uses the same verse's marks map.  When i == 0, loads the
    last word of the previous ayah (same surah) so cross-verse boundaries
    are covered — essential for interrogatives at verse start."""
    if i > 0:
        bw = words[i - 1]
        bmarks = marks_by_wpos.get(i - 1, {})
        bwsym = ''.join(c for c in bw if c in WAQF_SYMBOL_CHARS)
        return bw, bmarks, bwsym

    if a <= 1:
        return '', {}, ''

    prev_vk = f"{s}:{a - 1}"
    _, prev_words, prev_r2w = _verse_word_texts(prev_vk)
    if not prev_words:
        return '', {}, ''

    prev_marks = {}
    for ver in _WAQF_MATCH_MUSHAFS:
        for r in get_mushaf_waqf_symbols(s, a - 1, ver):
            ti = r.get('token_index')
            if ti is None or not r.get('symbols') or not (0 <= ti < len(prev_r2w)):
                continue
            wp = prev_r2w[ti]
            if wp is not None:
                prev_marks.setdefault(wp, {})[ver] = r['symbols']

    last_i = len(prev_words) - 1
    bw = prev_words[last_i]
    return bw, prev_marks.get(last_i, {}), ''.join(c for c in bw if c in WAQF_SYMBOL_CHARS)


@breathing_bp.route('/api/waqf-research', methods=['GET'])
def waqf_research():
    """Research tool: every verse where a given word occurs, with the exact
    vocalised form, the printed Madinah waqf symbol embedded on it, and a small
    context snippet. Diacritic-insensitive match (so كَلَّا and كُلّاً both come
    back) but each occurrence keeps its exact form, plus a form breakdown, so the
    researcher can isolate the particle they want. Reciter waqf + the full mushaf
    comparison are shown by clicking through to the verse."""
    word = request.args.get('word', '').strip()
    if not word:
        return jsonify({'error': "query parameter 'word' is required"}), 400
    # exact=1: pre-select the form matching the (vocalised) query, so a preset
    # like كَلَّا lands on the 33 particle occurrences, not كُلّاً.
    exact = request.args.get('exact') in ('1', 'true', 'yes')
    # mode=before: show waqf marks on the word BEFORE the searched word
    # (useful for studying waqf before interrogatives like هل/كيف).
    before = request.args.get('mode') == 'before'
    nt = _normalize_for_search(word)
    if not nt:
        return jsonify({'word': word, 'normalized': '', 'count': 0, 'forms': [], 'occurrences': [], 'active_form': None})

    cache_key = (nt, exact, before)
    cached = _waqf_research_cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    def _form_key(token):
        """Coarse form: drop waqf symbols and fold alef/hamza variants, but KEEP
        harakat — so كَلَّا/كَلَّآ/كَلَّاۖ collapse to one form while كُلّٗا (each)
        stays distinct from كَلَّا (the particle)."""
        # drop: waqf symbols, tatweel, maddah, both sukun glyphs (ْ / ۡ); keep the
        # short vowels (fatha/damma/kasra/shadda) that carry the meaning.
        drop = set(WAQF_SYMBOL_CHARS) | {'ـ', 'ٓ', 'ْ', 'ۡ', 'ۤ'}
        out = ''.join(c for c in token if c not in drop)
        for a in ('آ', 'أ', 'إ', 'ٱ'):
            out = out.replace(a, 'ا')
        return out

    occ = []
    forms = Counter()
    for vk in qpc_hafs_data_normalized:
        text, words, raw_to_wpos = _verse_word_texts(vk)
        if not words or nt not in _normalize_for_search(text):
            continue  # quick reject — most verses don't contain the word
        s, a = vk.split(':')
        s, a = int(s), int(a)
        marks_by_wpos = None  # built lazily — only for verses that actually match
        for i, w in enumerate(words):
            if _normalize_for_search(w) != nt:
                continue
            if marks_by_wpos is None:
                marks_by_wpos = {}
                for ver in _WAQF_MATCH_MUSHAFS:
                    for r in get_mushaf_waqf_symbols(s, a, ver):
                        ti = r.get('token_index')
                        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                            continue
                        wp = raw_to_wpos[ti]
                        if wp is not None:
                            marks_by_wpos.setdefault(wp, {})[ver] = r['symbols']
            fk = _form_key(w)
            if before:
                bw, bmarks, bwsym = _before_word_marks(
                    s, a, i, words, marks_by_wpos)
                marks, wsym = bmarks, bwsym
                lo, hi = max(0, i - 2), min(len(words), i + 2)
                ctx = ' '.join(words[lo:hi])
                if i == 0 and bw:
                    ctx = bw + ' ۞ ' + ctx
            else:
                wsym = ''.join(c for c in w if c in WAQF_SYMBOL_CHARS)
                marks = marks_by_wpos.get(i, {})
                lo, hi = max(0, i - 1), min(len(words), i + 3)
                ctx = ' '.join(words[lo:hi])
            occ.append({
                'surah': s, 'ayah': a, 'wpos': i,
                'word': w, 'form': fk, 'waqf': wsym,
                'marks': marks, 'has_waqf': bool(marks or wsym),
                'context': ctx,
            })
            forms[fk] += 1

    # For a preset (exact=1) default to the dominant form — which for these
    # particles is the waqf-relevant one (كَلَّا not كُلّاً، نَعَم not نِعْمَ).
    active_form = forms.most_common(1)[0][0] if (exact and forms) else None
    result = {
        'word': word,
        'normalized': nt,
        'count': len(occ),
        'forms': [{'word': w, 'count': c} for w, c in forms.most_common()],
        'occurrences': occ,
        'active_form': active_form,
    }
    _waqf_research_cache[cache_key] = result
    return jsonify(result)


_CLASSICAL_SOURCES = {
    'muktafa': {
        'name': 'الداني',
        'title': 'المكتفى في الوقف والابتدا',
        'author': 'أبو عمرو عثمان بن سعيد الداني (ت 444هـ)',
        'edition': 'تحقيق محيي الدين عبد الرحمن رمضان، دار عمار، ط1 1422هـ/2001م',
        'via': 'OpenITI (Shamela 0026461)',
    },
    'manar': {
        'name': 'الأشموني',
        'title': 'منار الهدى في بيان الوقف والابتدا',
        'author': 'أحمد بن محمد بن عبد الكريم الأشموني (ق 11هـ)',
        'edition': 'ضبط شريف أبو العلا العدوي، دار الكتب العلمية',
        'via': 'OpenITI (Shamela 0006496)',
    },
    'nahhas': {
        'name': 'النحاس',
        'title': 'القطع والائتناف',
        'author': 'أبو جعفر أحمد بن محمد النحاس (ت 338هـ)',
        'edition': 'تحقيق عبد الرحمن بن إبراهيم المطرودي، دار عالم الكتب، ط1 1413هـ/1992م',
        'via': 'OpenITI (Shamela 0020966)',
    },
    'anbari': {
        'name': 'ابن الأنباري',
        'title': 'إيضاح الوقف والابتداء',
        'author': 'أبو بكر محمد بن القاسم الأنباري (ت 328هـ)',
        'edition': 'تحقيق محيي الدين عبد الرحمن رمضان، مجمع اللغة العربية بدمشق',
        'via': 'OpenITI (Shamela 0014255)',
    },
}


@breathing_bp.route('/api/classical-waqf/<int:surah>/<int:ayah>', methods=['GET'])
def classical_waqf(surah, ayah):
    """Classical graded stops (الداني's المكتفى + الأشموني's منار الهدى) for one
    verse, aligned to recited-word positions by pipeline/build_classical_waqf.py.
    Only high-confidence alignments are returned — comparative citations the
    books quote from elsewhere stay in the DB flagged conf=0."""
    if not (1 <= surah <= 114) or ayah < 1:
        return jsonify({'error': 'invalid verse'}), 400
    entries = []
    if os.path.exists(CLASSICAL_WAQF_DATABASE):
        conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
        try:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    'SELECT source, wpos, stop_word, quote, grade, grade_raw, note '
                    'FROM classical WHERE surah=? AND ayah=? AND conf=1 '
                    'ORDER BY wpos, source, seq', (surah, ayah)):
                entries.append({
                    'source': r['source'],
                    'wpos': r['wpos'], 'stop_word': r['stop_word'],
                    'quote': r['quote'], 'grade': r['grade'],
                    'grade_raw': r['grade_raw'], 'note': r['note'] or '',
                })
        finally:
            conn.close()
    return jsonify({'surah': surah, 'ayah': ayah, 'sources': _CLASSICAL_SOURCES,
                    'count': len(entries), 'entries': entries})


@breathing_bp.route('/waqf')
def waqf_guide():
    return render_template('waqf_guide.html', enable_vercel_analytics=_IS_SERVERLESS)


# ── تدريب الوقف (waqf practice + grading) ──────────────────────────────────────
# Grade WHERE a memoriser chose to stop against the printed mushaf marks and the
# classical rulings (الداني + الأشموني). No audio/ASR — the learner marks their
# own stops; this scores them and explains each one. The stop verdicts, best
# (most encouraging) first:
_PRACTICE_RANK = {'excellent': 5, 'good': 4, 'ok': 3, 'unmarked': 2, 'caution': 1, 'error': 0}
# «ok» verdicts are PERMITTED-but-not-endorsed (ص صلى = continuing is better,
# س sakta) — they tolerate a stop but do NOT rescue a spot another authority
# forbids. Only strong verdicts (excellent/good) are real endorsements.
_STRONG = ('excellent', 'good')
# Printed-mushaf symbol → (verdict, label) for stopping THERE.
_MARK_STOP_VERDICT = {
    'م':  ('excellent', 'وقف لازم'),
    'ق':  ('good',      'الوقف أولى (قلى)'),
    'ص':  ('ok',        'الوصل أولى (صلى)'),
    'ج':  ('good',      'وقف جائز'),
    'لا': ('error',     'لا وقف — لا يُوقف عليه'),
    'ع':  ('good',      'وقف المعانقة'),
    'س':  ('ok',        'سكتة — بلا تنفّس'),
}
# Classical grade → (verdict, label).
_CLASSICAL_STOP_VERDICT = {
    'تام':  ('excellent', 'وقف تام'),
    'كاف':  ('good',      'وقف كافٍ'),
    'حسن':  ('ok',        'وقف حسن'),
    'جائز': ('good',      'وقف جائز'),
    'صالح': ('ok',        'وقف صالح'),
    'قبيح': ('error',     'وقف قبيح'),
    'لا':   ('error',     'ليس بوقف'),
}
_CLASSICAL_NAME = {'muktafa': 'الداني', 'manar': 'الأشموني', 'nahhas': 'النحاس',
                   'anbari': 'ابن الأنباري'}


def _mushaf_marks_by_wpos(surah, ayah, mushaf, raw_to_wpos):
    """{wpos: canonical_symbol} for one printed mushaf at one verse. Takes the
    verse's raw_to_wpos so the caller's _verse_word_texts result is reused."""
    out = {}
    for r in get_mushaf_waqf_symbols(surah, ayah, mushaf):
        ti = r.get('token_index')
        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
            continue
        wpos = raw_to_wpos[ti]
        if wpos is not None:
            out[wpos] = str(r['symbols']).split(',')[0].strip()
    return out


def _classical_grades_for_range(surah, from_ayah, to_ayah):
    """{(ayah, wpos): [{'source','name','grade'}]} for a verse range in ONE
    query/connection (the practice grader walks a whole passage)."""
    out = defaultdict(list)
    if os.path.exists(CLASSICAL_WAQF_DATABASE):
        conn = _sqlite_connect(CLASSICAL_WAQF_DATABASE)
        try:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    'SELECT ayah, source, wpos, grade FROM classical '
                    'WHERE surah=? AND ayah BETWEEN ? AND ? AND conf=1 AND wpos IS NOT NULL',
                    (surah, from_ayah, to_ayah)):
                out[(r['ayah'], r['wpos'])].append({
                    'source': r['source'],
                    'name': _CLASSICAL_NAME.get(r['source'], r['source']),
                    'grade': r['grade']})
        finally:
            conn.close()
    return out


def _grade_one_stop(mushaf_sym, classical, is_verse_end):
    """Classify a stop at a word given its rulings. Returns (verdict, label,
    sources[]). رأس آية is always a permitted stop (سنة). The chosen mushaf's
    «لا» forbids outright. Otherwise: a real endorsement (تام/كاف/م/ق…) stands;
    a forbid (قبيح/ليس بوقف) with only weak toleration (ص/سكتة) is a خلاف
    (caution), and with none is an error."""
    sources, verdicts = [], []
    if mushaf_sym in _MARK_STOP_VERDICT:
        v, lbl = _MARK_STOP_VERDICT[mushaf_sym]
        sources.append({'kind': 'mushaf', 'label': lbl, 'verdict': v})
        verdicts.append(v)
    for c in classical:
        v, lbl = _CLASSICAL_STOP_VERDICT.get(c['grade'], ('ok', c['grade']))
        sources.append({'kind': 'classical', 'name': c['name'], 'label': lbl, 'verdict': v})
        verdicts.append(v)
    if is_verse_end:
        verdicts.append('good')
        if not sources:
            sources.append({'kind': 'verse_end', 'label': 'رأس آية', 'verdict': 'good'})
    if mushaf_sym == 'لا' and not is_verse_end:
        return 'error', 'لا وقف — لا يُوقف عليه', sources

    strong = [v for v in verdicts if v in _STRONG]
    weak = [v for v in verdicts if v == 'ok']
    has_error = 'error' in verdicts
    if strong:
        return max(strong, key=lambda v: _PRACTICE_RANK[v]), None, sources
    if has_error:
        if weak:
            return 'caution', 'موضع خلاف — أجازه بعضهم ومنعه آخرون', sources
        return 'error', None, sources
    if weak:
        return 'ok', None, sources
    return 'unmarked', 'ليس موضعَ وقفٍ منصوصًا عليه', sources


def _grade_waqf_practice(surah, from_ayah, to_ayah, mushaf, stops):
    stop_set = {(s['ayah'], s['wpos']) for s in stops}
    graded, broken_lazim, ideal = [], [], []
    counts = {'excellent': 0, 'good': 0, 'ok': 0, 'unmarked': 0, 'caution': 0, 'error': 0}

    classical_all = _classical_grades_for_range(surah, from_ayah, to_ayah)
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            continue
        _, words, raw_to_wpos = _verse_word_texts(vk)
        if not words:
            continue
        last = len(words) - 1
        marks = _mushaf_marks_by_wpos(surah, ayah, mushaf, raw_to_wpos)

        for wpos in range(len(words)):
            here = (ayah, wpos)
            sym = marks.get(wpos, '')
            cls = classical_all.get((ayah, wpos), [])
            is_end = wpos == last
            if here in stop_set:
                verdict, label, sources = _grade_one_stop(sym, cls, is_end)
                counts[verdict] += 1
                graded.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos],
                               'verdict': verdict, 'label': label, 'sources': sources})
            else:
                # مواضع فاتها: broken لازم (error) and ideal تام the learner ran past.
                if sym == 'م':
                    broken_lazim.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos]})
                elif not is_end and (sym in ('ق',) or any(c['grade'] == 'تام' for c in cls)):
                    ideal.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos]})

    errors = counts['error'] + len(broken_lazim)
    score = max(0, 100 - errors * 15 - counts['caution'] * 7 - counts['unmarked'] * 4)
    return {
        'surah': surah, 'from_ayah': from_ayah, 'to_ayah': to_ayah, 'mushaf': mushaf,
        'score': score,
        'summary': {'good': counts['excellent'] + counts['good'] + counts['ok'],
                    'notes': counts['unmarked'] + counts['caution'], 'errors': errors},
        'counts': counts,
        'stops': graded,
        'broken_lazim': broken_lazim,
        'ideal': ideal[:12],
    }


@breathing_bp.route('/api/waqf-practice/passage/<int:surah>/<int:from_ayah>/<int:to_ayah>')
def waqf_practice_passage(surah, from_ayah, to_ayah):
    """Word lists for a range, for the practice UI to render as tappable words."""
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah:
        return jsonify({'error': 'invalid range'}), 400
    if to_ayah - from_ayah > 20:
        return jsonify({'error': 'range too large (max 21 verses)'}), 400
    verses = []
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            break
        _, words, _ = _verse_word_texts(vk)
        if words:
            verses.append({'ayah': ayah, 'words': words})
    return jsonify({'surah': surah, 'verses': verses})


# ── phoneme reference (zipformer recite-follow) ────────────────────────────
_QURAN_PHONEMES = None
_PH_KEEP = set('ءابتثجحخدذرزسشصضطظعغفقكلمنهوي')

def _load_quran_phonemes():
    """Lazy-load surah:ayah → {aya_phonemes_list} (ReciteQuran ordered set)."""
    global _QURAN_PHONEMES
    if _QURAN_PHONEMES is None:
        try:
            with open(QURAN_PHONEMES_JSON, encoding='utf-8') as fh:
                _QURAN_PHONEMES = json.load(fh)
        except Exception:
            _QURAN_PHONEMES = {}
    return _QURAN_PHONEMES

def _ph_skel(s):
    """Consonant skeleton (drop vowels/diacritics/alef, collapse repeats) for
    aligning phoneme entries to words regardless of orthography."""
    out = []
    for c in (s or '').replace('ٱ', 'ا').replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي'):
        if c in _PH_KEEP and (not out or out[-1] != c):
            out.append(c)
    return ''.join(out)

def _edit_dist(a, b):
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]

def _align_entries_to_words(entries, words):
    """DP-tile N phoneme entries over M words (each entry → a contiguous word
    group; idghaam/waṣl merges two words into one entry). Returns, per entry,
    the index of the LAST word it covers — where a stop after it is attributed."""
    N, M = len(entries), len(words)
    if N == 0 or M == 0:
        return []
    if N == M:
        return list(range(N))
    es = [_ph_skel(e) for e in entries]
    ws = [_ph_skel(w) for w in words]
    INF = float('inf')
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    bk = [[0] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0
    for i in range(1, N + 1):
        for j in range(i, M - (N - i) + 1):          # each entry ≥ 1 word
            for a in range(i - 1, j):
                c = dp[i - 1][a] + _edit_dist(es[i - 1], ''.join(ws[a:j]))
                if c < dp[i][j]:
                    dp[i][j] = c
                    bk[i][j] = a
    res = [0] * N
    j = M
    for i in range(N, 0, -1):
        res[i - 1] = j - 1
        j = bk[i][j]
    return res


@breathing_bp.route('/api/waqf-practice/phonemes/<int:surah>/<int:from_ayah>/<int:to_ayah>')
def waqf_practice_phonemes(surah, from_ayah, to_ayah):
    """Reference phoneme entries for a range, each tagged with the (ayah, wpos)
    of the word it ends on — the zipformer glue DP-aligns the recited phoneme
    stream to these to follow position and attribute stops."""
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    ph = _load_quran_phonemes()
    entries = []
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            break
        _, words, _ = _verse_word_texts(vk)
        rec = ph.get(vk)
        if not words or not rec:
            continue
        plist = rec.get('aya_phonemes_list') or []
        ends = _align_entries_to_words(plist, words)
        for i, p in enumerate(plist):
            entries.append({'ph': p, 'ayah': ayah, 'wpos': ends[i] if i < len(ends) else len(words) - 1})
    return jsonify({'surah': surah, 'entries': entries})


# ── tajweed error detection (obadx/quran-transcript) ───────────────────────
_QT_MOSHAF = None

def _qt_moshaf():
    """Standard Ḥafṣ moshaf attributes (madd lengths matching the reference
    phonetization). Lazy so quran_transcript is only imported on demand."""
    global _QT_MOSHAF
    if _QT_MOSHAF is None:
        import quran_transcript as qt
        _QT_MOSHAF = qt.MoshafAttributes(
            rewaya='hafs', madd_monfasel_len=4, madd_mottasel_len=4,
            madd_mottasel_waqf=4, madd_aared_len=4)
    return _QT_MOSHAF


def _split_predicted_by_verse(predicted, verse_refs):
    """Split the full recited phoneme string into per-verse segments by char-level
    alignment (Needleman-Wunsch) to the concatenated reference — precise at the
    verse boundaries where a per-entry skeleton split leaks a letter."""
    ref = ''.join(r for _, r in verse_refs)
    vtag = []
    for vi, (_, r) in enumerate(verse_refs):
        vtag.extend([vi] * len(r))
    m, n = len(predicted), len(ref)
    if not m or not n:
        return [''] * len(verse_refs)
    prev = list(range(n + 1))
    back = [[0] * (n + 1) for _ in range(m + 1)]   # 0=diag 1=up(del pred) 2=left(ins ref)
    for j in range(n + 1):
        back[0][j] = 2
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        back[i][0] = 1
        pi = predicted[i - 1]
        for j in range(1, n + 1):
            diag = prev[j - 1] + (0 if pi == ref[j - 1] else 1)
            up = prev[j] + 1
            left = cur[j - 1] + 1
            best = diag; b = 0
            if up < best:
                best = up; b = 1
            if left < best:
                best = left; b = 2
            cur[j] = best; back[i][j] = b
        prev = cur
    # backtrace: assign each predicted char to the verse of its aligned ref char
    segs = [''] * len(verse_refs)
    i, j = m, n
    while i > 0 or j > 0:
        b = back[i][j]
        if i > 0 and (j == 0 or b == 1):        # predicted char with no ref → nearest verse
            vi = vtag[j - 1] if j > 0 else 0
            segs[vi] = predicted[i - 1] + segs[vi]
            i -= 1
        elif j > 0 and (i == 0 or b == 2):      # ref char, no predicted
            j -= 1
        else:
            segs[vtag[j - 1]] = predicted[i - 1] + segs[vtag[j - 1]]
            i -= 1; j -= 1
    return segs


@breathing_bp.route('/api/waqf-practice/tajweed', methods=['POST'])
def waqf_practice_tajweed():
    """Detect tajweed/pronunciation errors: split the recited phoneme stream per
    verse, phonetize each reference (quran_transcript) and diff against it —
    returning rule-named errors (Madd length, Qalqalah, Ghonnah, wrong letter…)
    mapped to the word (wpos) they occur on."""
    try:
        import quran_transcript as qt
    except Exception:
        return jsonify({'available': False, 'errors': []})
    data = request.get_json(silent=True) or {}
    surah = int(data.get('surah') or 0)
    from_ayah = int(data.get('from_ayah') or 0)
    to_ayah = int(data.get('to_ayah') or 0)
    predicted = (data.get('phonemes') or '').strip()
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    if not predicted:
        return jsonify({'available': True, 'errors': []})
    moshaf = _qt_moshaf()

    def rule_names(rules):
        out = []
        for r in (rules or []):
            nm = getattr(r, 'name', None)
            out.append(getattr(nm, 'ar', None) or getattr(nm, 'en', None) or str(nm))
        return out

    # phonetize each verse's reference, then split the recited stream to match
    verse_refs = []                              # (ayah, ut, ref_out)
    for ayah in range(from_ayah, to_ayah + 1):
        try:
            ut = qt.Aya(surah, ayah).get().uthmani
            ref = qt.quran_phonetizer(ut, moshaf)
        except Exception:
            continue
        verse_refs.append((ayah, ut, ref))
    if not verse_refs:
        return jsonify({'available': True, 'errors': []})
    segs = _split_predicted_by_verse(predicted, [(a, r.phonemes) for a, _, r in verse_refs])

    errors = []
    for (ayah, ut, ref), pred in zip(verse_refs, segs):
        pred = (pred or '').strip()
        if not pred:
            continue
        try:
            errs = qt.explain_error(ut, ref.phonemes, pred, ref.mappings)
        except Exception:
            continue
        nwords = ut.count(' ') + 1
        for e in errs:
            try:
                wpos = min(ut[:e.uthmani_pos[0]].count(' '), nwords - 1)
            except Exception:
                wpos = 0
            rules = rule_names(getattr(e, 'ref_tajweed_rules', None)) or \
                rule_names(getattr(e, 'missing_tajweed_rules', None)) or \
                rule_names(getattr(e, 'replaced_tajweed_rules', None))
            errors.append({
                'ayah': ayah, 'wpos': wpos,
                'type': e.error_type, 'op': e.speech_error_type,
                'expected': e.expected_ph, 'got': e.preditected_ph,
                'exp_len': e.expected_len, 'got_len': e.predicted_len,
                'rules': rules,
            })
    return jsonify({'available': True, 'errors': errors})


@breathing_bp.route('/api/waqf-practice/grade', methods=['POST'])
def waqf_practice_grade():
    """Grade the learner's chosen stops against the mushaf + classical rulings."""
    data = request.get_json(silent=True) or {}
    try:
        surah = int(data.get('surah'))
        from_ayah = int(data.get('from_ayah'))
        to_ayah = int(data.get('to_ayah'))
    except (TypeError, ValueError):
        return jsonify({'error': 'surah/from_ayah/to_ayah required'}), 400
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    mushaf = data.get('mushaf') or 'المدينة الجديد'
    if not _is_valid_mushaf_version(mushaf):
        mushaf = 'المدينة الجديد'
    stops = []
    for s in (data.get('stops') or []):
        try:
            stops.append({'ayah': int(s['ayah']), 'wpos': int(s['wpos'])})
        except (TypeError, ValueError, KeyError):
            continue
    return jsonify(_grade_waqf_practice(surah, from_ayah, to_ayah, mushaf, stops))


@breathing_bp.route('/waqf-practice')
def waqf_practice_page():
    return render_template('waqf_practice.html', enable_vercel_analytics=_IS_SERVERLESS)


@memorize_bp.route('/api/memorization/<int:surah_number>', methods=['GET'])
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
                phrases = _segment_phrases(words, _WAQF_CONSENSUS_GAP_MS)
        else:
            # Acoustic mode: use the same consensus gap (1 ms) as the مكث guide
            # so phrase boundaries match exactly what مكث shows — any forward
            # pause in the reciter's audio is a real stop point.
            phrases = _segment_phrases(words, _WAQF_CONSENSUS_GAP_MS)
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

    tmpl = reciter_cfg.get('audio_tmpl', '')
    if tmpl == '_yt_':
        audio_url = _yt_audio_url(reciter_id, surah_number)
    elif tmpl == '_gd_':
        audio_url = _gd_audio_url(reciter_id, surah_number)
    else:
        audio_url = tmpl.format(surah=surah_number) if tmpl else None

    return jsonify({
        'surah_number': surah_number,
        'reciter': reciter_cfg.get('name_en', 'Mahmoud Khalil al-Husary'),
        'reciter_id': reciter_id,
        'reciter_name_ar': reciter_cfg.get('name_ar', ''),
        'audio_url': audio_url,
        'gap_ms': gap_ms,
        'mode': mode,
        'verses': verses,
    })


@memorize_bp.route('/api/memorization-reciters', methods=['GET'])
def get_memorization_reciters():
    """List the memorization reciters whose timestamp data is installed."""
    out = []
    for rid, cfg in MEMORIZATION_RECITERS.items():
        if _memo_reciter_installed(rid):
            out.append({'id': rid, 'name_ar': cfg.get('name_ar', ''), 'name_en': cfg.get('name_en', '')})
    return jsonify(out)


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


# ── المتشابهات (similar verses) ───────────────────────────────────────────────
# A memorization aid: given a verse, find OTHER verses that share a long
# contiguous run of words with it — the near-identical passages that huffāẓ
# most often confuse (e.g. the repeated قصص openings, "فَبِأَيِّ آلَآءِ
# رَبِّكُمَا تُكَذِّبَانِ", the وَيۡل / مُكَذِّبِين refrains). Words are folded to a
# diacritic-free skeleton (the same fold as search) so رغدا/رَغَدٗا match, then a
# word-level diff surfaces exactly where the two verses diverge.
import difflib

_mutashabihat_index = None
_mutashabihat_lock = threading.Lock()
_MUTASHABIHAT_NGRAM = 3   # prefilter shingle size; any run >= this shares a shingle


def _build_mutashabihat_index():
    """Lazy-build the similar-verse index: per-verse normalized + display word
    lists, plus an inverted n-gram index for candidate prefiltering."""
    global _mutashabihat_index
    if _mutashabihat_index is not None:
        return _mutashabihat_index
    with _mutashabihat_lock:
        if _mutashabihat_index is not None:
            return _mutashabihat_index
        norm_words, disp_words = {}, {}
        ngram_index = defaultdict(set)
        n = _MUTASHABIHAT_NGRAM
        for vk, td in qpc_hafs_data_normalized.items():
            text = (td.get('text', '') if isinstance(td, dict) else '') or ''
            disp, norm = [], []
            for tok in text.split():
                if not _has_arabic_letter(tok):  # drop the trailing ayah number / ornaments
                    continue
                folded = _normalize_for_search(tok)
                if not folded:
                    continue
                disp.append(tok)
                norm.append(folded)
            if not norm:
                continue
            norm_words[vk] = norm
            disp_words[vk] = disp
            for i in range(len(norm) - n + 1):
                ngram_index[tuple(norm[i:i + n])].add(vk)
        _mutashabihat_index = {
            'norm': norm_words, 'disp': disp_words, 'ngram': dict(ngram_index),
        }
    return _mutashabihat_index


# A shared run only makes two verses genuinely متشابهين (confusable for a
# memorizer) if it is DISTINCTIVE — sharing a ubiquitous formula like
# «يَٰأَيُّهَا ٱلَّذِينَ ءَامَنُوا» (≈90 verses) is not a متشابه. We measure the
# rarity of the shared run by its corpus document-frequency (how many verses
# contain that exact word-sequence): real متشابهات share runs found in just a
# handful of verses (DF≈2–3), the generic openers in dozens. The one exception
# is near-DUPLICATE verses (the فبأي آلاء / ويل يومئذ refrains): their run is
# common precisely because the whole verse repeats, so a high coverage ratio
# keeps them even when the run itself isn't rare.
_MUTASHABIHAT_DISTINCT_DF = 18   # shared run in ≤ this many verses ⇒ distinctive
_MUTASHABIHAT_HIGH_COVERAGE = 0.66  # ≥ this share of the verse matches ⇒ near-duplicate


@lru_cache(maxsize=2048)
def _find_mutashabihat(verse_key, min_run, limit):
    """Verses genuinely متشابهة (confusable) with verse_key.

    Candidates share a contiguous run of ≥ min_run words; a candidate is kept
    only if that shared run is DISTINCTIVE (rare across the corpus) or the verses
    are near-duplicates (high coverage), so generic-formula matches are dropped.
    Returns the candidate's display words, the diff opcodes aligning the query
    (i) to the candidate (j), the longest shared run, total shared words, the
    coverage ratio, and the rarity (document-frequency) of the shared run."""
    idx = _build_mutashabihat_index()
    q_norm = idx['norm'].get(verse_key)
    if not q_norm or len(q_norm) < min_run:
        return []
    ngram = idx['ngram']
    n = _MUTASHABIHAT_NGRAM

    candidates = set()
    for i in range(len(q_norm) - n + 1):
        candidates |= ngram.get(tuple(q_norm[i:i + n]), set())
    candidates.discard(verse_key)

    out = []
    for cvk in candidates:
        c_norm = idx['norm'][cvk]
        sm = difflib.SequenceMatcher(a=q_norm, b=c_norm, autojunk=False)
        blocks = sm.get_matching_blocks()
        longest = max((b.size for b in blocks), default=0)
        if longest < min_run:
            continue
        shared = sum(b.size for b in blocks)
        coverage = shared / min(len(q_norm), len(c_norm))

        # Rarest 3-gram lying inside any shared run of length ≥ n: the
        # document-frequency of the most distinctive thing the two verses share.
        run_df = None
        for b in blocks:
            for i in range(b.a, b.a + b.size - n + 1):
                d = len(ngram.get(tuple(q_norm[i:i + n]), ()))
                run_df = d if run_df is None else min(run_df, d)

        distinctive = run_df is not None and run_df <= _MUTASHABIHAT_DISTINCT_DF
        near_duplicate = coverage >= _MUTASHABIHAT_HIGH_COVERAGE
        if not (distinctive or near_duplicate):
            continue  # only a generic formula in common — not a real متشابه

        cs, ca = cvk.split(':')
        out.append({
            'surah': int(cs), 'ayah': int(ca), 'verse_key': cvk,
            'words': idx['disp'][cvk],
            'longest_run': longest, 'shared': shared,
            'coverage': round(coverage, 2),
            'run_df': run_df if run_df is not None else 0,
            'near_duplicate': near_duplicate,
            # opcodes align query word indices (i1,i2) to candidate (j1,j2);
            # tag is 'equal' | 'replace' | 'delete' | 'insert'.
            'opcodes': [[t, i1, i2, j1, j2] for t, i1, i2, j1, j2 in sm.get_opcodes()],
        })

    # Best matches first: longest shared run, then most overlap, then the most
    # distinctive (rarest) run.
    out.sort(key=lambda m: (-m['longest_run'], -m['shared'], m['run_df'], m['surah'], m['ayah']))
    return out[:limit]


@reading_bp.route('/api/mutashabihat/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_mutashabihat(surah_number, ayah_number):
    """المتشابهات: other verses sharing a long contiguous run of words with this
    one — the look-alike passages huffāẓ confuse. Query params: min_run (shared
    run length threshold, default 3, clamped 3..8), limit (default 30, max 60)."""
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400
    vk = f"{surah_number}:{ayah_number}"
    if vk not in qpc_hafs_data_normalized:
        return jsonify({'error': 'unknown verse'}), 404
    min_run = max(3, min(8, request.args.get('min_run', 3, type=int)))
    limit = max(1, min(60, request.args.get('limit', 30, type=int)))
    idx = _build_mutashabihat_index()
    matches = _find_mutashabihat(vk, min_run, limit)
    return jsonify({
        'surah': surah_number, 'ayah': ayah_number, 'verse_key': vk,
        'words': idx['disp'].get(vk, []),
        'min_run': min_run,
        'count': len(matches),
        'matches': matches,
    })






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
