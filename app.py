from flask import Flask, jsonify, render_template, request, redirect
import sqlite3
import os
import logging
import re
import threading
from collections import defaultdict
from functools import lru_cache

import gzip
from io import BytesIO
import requests as http_requests
import concurrent.futures

from core.lru import _BoundedLRU
from core.loader import (
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
    DATABASE, WAQF_DATABASE, _BASE_DIR, TAJWEED_DATABASE, MAX_AYAH_NUMBER,
    MUSHAF_WAQF_DATABASE,  # noqa: F401 — tests reach this via app.MUSHAF_WAQF_DATABASE
)
from core.text import (
    _normalize_for_search,
)
from core.mushaf_waqf import (
    _get_mushaf_version_whitelist,
    get_mushaf_waqf_symbols,
)


import modules.editor  # noqa: F401 — attaches editor routes to editor_bp
from modules.layouts import (  # noqa: F401 — importing also registers layout routes
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)
import modules.breathing        # noqa: F401 — attaches breathing routes to breathing_bp
import modules.waqf_research    # noqa: F401 — attaches waqf-research routes to breathing_bp
from modules.breathing import _verse_word_texts, _mark_word_context  # noqa: F401 — tests reach these via app.<name>
from modules.waqf_research import _RESEARCH_CACHE_DIR                # noqa: F401 — same
from core.datasets import (
    digital_khatt_data, qpc_hafs_data, indopak_nastaleeq_data,
    indopak_nastaleeq_2_data, transliteration_data, surahs_data,
    digital_khatt_data_normalized, qpc_hafs_data_normalized,
    indopak_nastaleeq_data_normalized, indopak_nastaleeq_2_data_normalized,
    amiri_quran_data_normalized,
)
from core.memorization import (
    MEMORIZATION_RECITERS, _memo_reciter_cfg, _memo_reciter_installed,
    _load_memorization_word_ts, _memorization_lock, _yt_audio_url,
    _gd_audio_url, _build_breathing_guide, _has_arabic_letter,
    _WAQF_CONSENSUS_GAP_MS, _DEFAULT_MEMO_RECITER, _segment_phrases,
    _YT_CHAPTER_URLS,
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

# Husary mushaf-waqf phrase boundaries (sub-verse segments). Used by the
# 'waqf' segmentation mode, snapped to real pauses in the mp3quran audio.
_MEMORIZATION_WAQF_DB = os.path.join(_BASE_DIR, 'reciters', 'husary',
                                     'mahmoud_khalil_al_husari_0_1_positions.db')
_memorization_waqf_bounds = None
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
