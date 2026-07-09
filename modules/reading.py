"""Main reading page (المصحف): tafseer, tajweed, i'rab, waqf symbols,
word meanings, and المتشابهات (memorization aid — verses sharing a long
run of identical words). Also the / and mutashabihat routes.
"""
import difflib
import logging
import os
import sqlite3
import threading
from collections import defaultdict
from functools import lru_cache

import concurrent.futures
import requests as http_requests
from flask import jsonify, render_template, request

from core.blueprints import reading_bp
from core.config import WAQF_DATABASE, TAJWEED_DATABASE, MAX_AYAH_NUMBER
from core.text import _normalize_for_search
from core.mushaf_waqf import get_mushaf_waqf_symbols
from core.datasets import (
    qpc_hafs_data_normalized, get_quran_text_data_by_source, normalize_source,
)
from core.memorization import _has_arabic_letter
from core.db import get_db
from core.lru import _BoundedLRU
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules.layouts import _find_mushaf_row_match_index, _normalize_mushaf_word_token

logger = logging.getLogger(__name__)


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
        logger.error(f"Failed to read waqf symbols: {e}")
        return []

def get_word_meanings_ordered(surah_number, ayah_number):
    """Return word meanings as an ordered list for stable verse-order rendering on frontend."""
    db = get_db()
    if db is None:
        logger.warning("Database not available for ordered word meanings")
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
        logger.error(f"Database ordered query error: {e}")
        return []

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
            logger.error(f"Tafseer API error for {name} {verse_key}: {e}")
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
            logger.error(f"Tafseer (quranenc) API error for {name} {verse_key}: {e}")
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
        logger.error(f"Tajweed DB error for {verse_key}: {e}")
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
        logger.error(f"SurahApp eerab API error for {surah_number}:{ayah_number}: {e}")
        return jsonify({"content": ""}), 500

@reading_bp.route('/')
def index():
    return render_template('index.html', enable_vercel_analytics=_IS_SERVERLESS)

# ── المتشابهات (similar verses) ───────────────────────────────────────────────
# A memorization aid: given a verse, find OTHER verses that share a long
# contiguous run of words with it — the near-identical passages that huffāẓ
# most often confuse (e.g. the repeated قصص openings, "فَبِأَيِّ آلَآءِ
# رَبِّكُمَا تُكَذِّبَانِ", the وَيۡل / مُكَذِّبِين refrains). Words are folded to a
# diacritic-free skeleton (the same fold as search) so رغدا/رَغَدٗا match, then a
# word-level diff surfaces exactly where the two verses diverge.
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
