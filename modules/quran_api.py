"""Shared Quran data API (core_bp): surah/ayah text + waqf-symbol lookup,
mushaf-version listing, health check, quran-text/transliteration by source,
audio streaming (proxy + YouTube via yt-dlp), and full-text/word-meaning
search. The foundational routes every other module builds on top of.

Reciter audio is served by core/memorization.py's per-surah system (same
one مُكْث/تثبيت use — see /api/memorization, /api/memorization-reciters,
/api/waqf) — this module no longer carries its own per-ayah audio data.
"""
import logging
import os
import sqlite3
import threading

from flask import jsonify, request, redirect

from core.blueprints import core_bp
from core.config import DATABASE, WAQF_DATABASE, MAX_AYAH_NUMBER
from core.text import _normalize_for_search
from core.mushaf_waqf import _get_mushaf_version_whitelist
from core.datasets import (
    digital_khatt_data, qpc_hafs_data, indopak_nastaleeq_data,
    transliteration_data, surahs_data,
    normalize_source, get_quran_text_data_by_source, get_quran_text_data,
)
from core.memorization import _YT_CHAPTER_URLS
from core.db import get_db
from modules.reading import get_waqf_symbols, get_word_meanings_ordered

logger = logging.getLogger(__name__)


@core_bp.route('/api/mushaf-versions', methods=['GET'])
def get_mushaf_versions():
    """Returns available Mushaf versions from the waqf database."""
    return jsonify(sorted(_get_mushaf_version_whitelist()))


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
            "transliteration_loaded": bool(transliteration_data),
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
        # Reciter audio is served separately by /api/memorization (per-surah,
        # same system مُكْث/تثبيت use) — not carried in this payload.

        # Fetch word meanings from the SQLite database (single query)
        ordered_meanings = get_word_meanings_ordered(surah_number, ayah_number)
        ayah_data['word_meanings_ordered'] = ordered_meanings
        ayah_data['word_meanings'] = {r['word']: r['meaning'] for r in ordered_meanings}
        ayah_data['waqf_symbols'] = get_waqf_symbols(surah_number, ayah_number, source)
        
        return jsonify(ayah_data)
    return jsonify({"error": "Ayah not found"}), 404


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
    logger.warning('yt-dlp not installed — YouTube-sourced reciters will be unavailable.')


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
        logger.error(f"URL validation error: {e}")
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
        logger.error(f'yt-dlp extraction failed for {yt_url}: {exc}')
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
        logger.error(f"Database search error: {e}")
        return jsonify({"error": "Search failed"}), 500
