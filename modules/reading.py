"""Main reading page (المصحف): tafseer, tajweed, i'rab, waqf symbols,
word meanings, and المتشابهات (memorization aid — verses sharing a long
run of words, curated phrase corpus + live-computed fallback). Also the
/ and mutashabihat routes.
"""
import difflib
import json
import logging
import os
import sqlite3
import threading
from collections import defaultdict
from functools import lru_cache

import requests as http_requests
from flask import jsonify, render_template, request

from core.blueprints import reading_bp
from core.config import (
    WAQF_DATABASE, TAJWEED_DATABASE, TAJWEED_NOTES_DATABASE, ASBAB_DATABASE,
    TAFSEER_LOCAL_DATABASE,
    MAX_AYAH_NUMBER,
    MUTASHABIHAT_PHRASES_JSON, MUTASHABIHAT_PHRASE_VERSES_JSON,
)
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


# The 5 Arabic tafsirs shown on the reading page — served from local data
# (data/tafseer_local.db, built offline by pipeline/build_tafseer_local.py
# from QUL exports; see that file's docstring for the source/schema). Names
# must match the SOURCES keys there.
TAFSEER_NAMES = (
    'تفسير السعدي',
    'تفسير القرطبي',
    'تفسير البغوي',
    'التفسير الميسر',
    'المختصر في التفسير',
)

# In-process cache: (tafseer_name, verse_key) → {text: "..."}
# Bounded so long-running processes don't accumulate every tafseer ever read.
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
        if (source == 'indopak_nastaleeq'
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
    if source != 'indopak_nastaleeq':
        return []

    if not os.path.exists(WAQF_DATABASE):
        # If mushaf_version data was fetched above, still return it
        return []

    try:
        conn = sqlite3.connect(WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        waqf_source = source
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

def get_local_tafseer(verse_key):
    """Look up all 5 tafsirs for verse_key from data/tafseer_local.db.

    Two-step lookup: tafseer_verse maps every ayah to its group's
    representative verse_key (a tafsir discussing several ayat under one
    heading, e.g. Baghawi's 1:1-1:7, stores the text once on the
    representative row; every other member ayah just points at it), and
    tafseer_group holds each group's text exactly once. Missing entries
    (Saadi has ~1% gaps with no source text) come back as an empty string.
    """
    result = {n: {'text': ''} for n in TAFSEER_NAMES}
    try:
        conn = sqlite3.connect(TAFSEER_LOCAL_DATABASE)
        try:
            rows = conn.execute(
                'SELECT tv.name, tg.text FROM tafseer_verse tv '
                'JOIN tafseer_group tg ON tg.name = tv.name AND tg.group_key = tv.group_key '
                'WHERE tv.verse_key = ?',
                (verse_key,)
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Tafseer DB error for {verse_key}: {e}")
        return result

    for name, text in rows:
        result[name] = {'text': text}
    return result


@reading_bp.route('/api/tafseer/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_tafseer(surah_number, ayah_number):
    """Return all 5 Arabic tafsirs for a single ayah, from local data."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"
    if all((n, verse_key) in _tafseer_cache for n in TAFSEER_NAMES):
        return jsonify({n: _tafseer_cache[(n, verse_key)] for n in TAFSEER_NAMES})

    result = get_local_tafseer(verse_key)
    for name, entry in result.items():
        _tafseer_cache[(name, verse_key)] = entry
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


_tajweed_notes_cache: _BoundedLRU = _BoundedLRU(maxsize=4096)
_TAJWEED_NOTES_DEFAULT_ATTR = (
    'بيان تجويد — مركز تفسير للدراسات القرآنية (Tafsir MCP / mcp.tafsir.net)'
)


def get_local_tajweed_note(verse_key):
    """Return {text, attribution} for verse_key from tajweed_notes_local.db, or None."""
    if not os.path.isfile(TAJWEED_NOTES_DATABASE):
        return None
    try:
        conn = sqlite3.connect(TAJWEED_NOTES_DATABASE)
        try:
            row = conn.execute(
                'SELECT text, attribution FROM tajweed_notes WHERE verse_key = ?',
                (verse_key,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Tajweed notes DB error for {verse_key}: {e}")
        return None
    if not row or not (row[0] or '').strip():
        return None
    return {
        'text': row[0],
        'attribution': row[1] or _TAJWEED_NOTES_DEFAULT_ATTR,
    }


@reading_bp.route('/api/tajweed-notes/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_tajweed_notes(surah_number, ayah_number):
    """Return the Arabic tajweed explanation for one ayah (companion to coloring).

    Served from data/tajweed_notes_local.db (built offline by
    pipeline/build_tajweed_notes_local.py from Tafsir Center MCP).
    """
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in _tajweed_notes_cache:
        resp = jsonify(_tajweed_notes_cache[verse_key])
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    note = get_local_tajweed_note(verse_key)
    if note is None:
        return jsonify({"error": "Note not found", "verse_key": verse_key}), 404

    payload = {
        'verse_key': verse_key,
        'text': note['text'],
        'attribution': note['attribution'],
    }
    _tajweed_notes_cache[verse_key] = payload
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


_asbab_cache: _BoundedLRU = _BoundedLRU(maxsize=4096)


def get_local_asbab(verse_key):
    """Return list of {source, text, attribution} for verse_key, or []."""
    if not os.path.isfile(ASBAB_DATABASE):
        return []
    try:
        conn = sqlite3.connect(ASBAB_DATABASE)
        try:
            rows = conn.execute(
                'SELECT source, text, attribution FROM asbab '
                'WHERE verse_key = ? ORDER BY source',
                (verse_key,),
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Asbab DB error for {verse_key}: {e}")
        return []
    out = []
    for source, text, attribution in rows:
        if not (text or '').strip():
            continue
        out.append({
            'source': source,
            'text': text,
            'attribution': attribution or source,
        })
    return out


@reading_bp.route('/api/asbab/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_asbab(surah_number, ayah_number):
    """Return أسباب النزول entries for one ayah (local sparse DB), if any."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    if ayah_number < 1 or ayah_number > MAX_AYAH_NUMBER:
        return jsonify({"error": "Invalid ayah number."}), 400

    verse_key = f"{surah_number}:{ayah_number}"
    if verse_key in _asbab_cache:
        resp = jsonify(_asbab_cache[verse_key])
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp

    entries = get_local_asbab(verse_key)
    if not entries:
        return jsonify({
            "verse_key": verse_key,
            "available": False,
            "entries": [],
            "message": "لم يثبت سبب نزول لهذه الآية في المصادر المحمّلة.",
        }), 404

    payload = {
        "verse_key": verse_key,
        "available": True,
        "entries": entries,
    }
    _asbab_cache[verse_key] = payload
    resp = jsonify(payload)
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

@reading_bp.route('/read')
def index():
    return render_template('index.html', enable_vercel_analytics=_IS_SERVERLESS)

@reading_bp.route('/')
def landing():
    return render_template('landing.html', enable_vercel_analytics=_IS_SERVERLESS)


# ── المتشابهات (similar verses) ───────────────────────────────────────────────
# A memorization aid: given a verse, find OTHER verses sharing a long run of
# words with it — the near-identical passages that huffāẓ most often confuse.
# Hybrid source: the curated "Mutashabihat ul Quran" phrase corpus
# (data/mutashabihat/) is tried FIRST — real curated phrase boundaries beat a
# heuristic wherever it has data. It only covers ~2,232 of 6,236 verses though
# (whole late-Meccan surahs and even famous refrains like سورة الرحمن's «فَبِأَيِّ
# آلَآءِ رَبِّكُمَا تُكَذِّبَانِ» are outside its scope), so a verse with no
# corpus matches falls back to a live n-gram/diff computation over the actual
# Quran text, which uniformly covers all 6,236 verses.
_mutashabihat_index = None
_mutashabihat_lock = threading.Lock()
_MUTASHABIHAT_NGRAM = 3   # computed fallback's prefilter shingle size


def _build_mutashabihat_index():
    """Lazy-build both sources: the curated phrase corpus (+ a per-verse
    display-word cache, built from qpc_hafs_data_normalized with the same
    token filtering as the corpus's own tokenization: drop trailing
    ayah-number ornaments so word indices line up), and the computed
    fallback's normalized-word + inverted n-gram index."""
    global _mutashabihat_index
    if _mutashabihat_index is not None:
        return _mutashabihat_index
    with _mutashabihat_lock:
        if _mutashabihat_index is not None:
            return _mutashabihat_index
        with open(MUTASHABIHAT_PHRASES_JSON, encoding='utf-8') as f:
            phrases = json.load(f)
        with open(MUTASHABIHAT_PHRASE_VERSES_JSON, encoding='utf-8') as f:
            phrase_verses = json.load(f)

        disp_words, norm_words = {}, {}
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
            if not disp:
                continue
            disp_words[vk] = disp
            norm_words[vk] = norm
            for i in range(len(norm) - n + 1):
                ngram_index[tuple(norm[i:i + n])].add(vk)

        _mutashabihat_index = {
            'phrases': phrases, 'phrase_verses': phrase_verses, 'disp': disp_words,
            'norm': norm_words, 'ngram': dict(ngram_index),
        }
    return _mutashabihat_index


# A shared run only makes two verses genuinely متشابهين (confusable for a
# memorizer) if it is DISTINCTIVE — a ubiquitous formula like «مِن دُونِ ٱللَّهِ»
# (70 verses) or «قَالُوا۟ سَمِعۡنَا وَأَطَعۡنَا» is not a متشابه on its own. We
# measure rarity by document-frequency: the corpus source by the shared
# phrase's own ayahs count, the computed fallback by the rarest shingle inside
# the shared run. The one exception is near-DUPLICATE verses: their shared
# coverage is high precisely because the whole verse repeats, so that keeps
# them even when the run itself isn't rare. Coverage alone would also flag two
# SHORT verses that merely happen to share scattered fragments summing to a
# high ratio without ever really running together — so near-duplicate ALSO
# requires the single longest run to itself cover a majority of the shorter
# verse (a real repeated verse like سورة الرحمن's 4-word refrain has ONE run
# spanning the whole thing, not several small coincidental ones).
_MUTASHABIHAT_DISTINCT_DF = 18       # shared run/phrase in ≤ this many verses ⇒ distinctive
_MUTASHABIHAT_HIGH_COVERAGE = 0.66   # ≥ this share of the verse matches ⇒ near-duplicate…
_MUTASHABIHAT_DUP_RUN_SHARE = 0.5    # …and the longest single run covers ≥ this share of it


@lru_cache(maxsize=2048)
def _find_mutashabihat_corpus(verse_key, min_run, limit):
    """Verses متشابهة with verse_key per the curated phrase corpus. See
    _find_mutashabihat for the field meanings (shared shape with the computed
    fallback: surah, ayah, verse_key, words, longest_run, shared, coverage,
    run_df, near_duplicate, opcodes)."""
    idx = _build_mutashabihat_index()
    q_words = idx['disp'].get(verse_key)
    if not q_words:
        return []
    phrases, phrase_verses = idx['phrases'], idx['phrase_verses']

    # candidate verse_key -> list of (length, ayahs_df, cand_ranges[(from,to)])
    by_candidate = defaultdict(list)
    for pid in phrase_verses.get(verse_key, []):
        p = phrases[str(pid)]
        length = p['source']['to'] - p['source']['from'] + 1
        if length < min_run:
            continue
        for cvk, ranges in p['ayah'].items():
            if cvk == verse_key:
                continue
            by_candidate[cvk].append((length, p['ayahs'], ranges))

    out = []
    for cvk, shares in by_candidate.items():
        c_words = idx['disp'].get(cvk)
        if not c_words:
            continue
        longest = max(s[0] for s in shares)
        best_df = min(s[1] for s in shares)
        covered = set()
        for _length, _df, ranges in shares:
            for frm, to in ranges:
                covered.update(range(frm - 1, min(to, len(c_words))))  # 1-based inclusive -> 0-based
        shared = len(covered)
        shorter_len = min(len(q_words), len(c_words))
        coverage = shared / shorter_len

        distinctive = best_df <= _MUTASHABIHAT_DISTINCT_DF
        near_duplicate = (coverage >= _MUTASHABIHAT_HIGH_COVERAGE
                           and longest / shorter_len >= _MUTASHABIHAT_DUP_RUN_SHARE)
        if not (distinctive or near_duplicate):
            continue  # only a generic formula in common — not a real متشابه

        # Synthetic opcodes: candidate words inside a shared phrase render
        # plain ('equal'); everything else is flagged as a divergence.
        opcodes, j = [], 0
        for j2 in sorted(set(covered) | {len(c_words)}):
            if j2 > j:
                tag = 'equal' if j in covered else 'replace'
                opcodes.append([tag, 0, 0, j, j2])
            j = j2

        cs, ca = cvk.split(':')
        out.append({
            'surah': int(cs), 'ayah': int(ca), 'verse_key': cvk,
            'words': c_words,
            'longest_run': longest, 'shared': shared,
            'coverage': round(coverage, 2),
            'run_df': best_df,
            'near_duplicate': near_duplicate,
            'opcodes': opcodes,
        })

    out.sort(key=lambda m: (-m['longest_run'], -m['shared'], m['run_df'], m['surah'], m['ayah']))
    return out[:limit]


@lru_cache(maxsize=2048)
def _find_mutashabihat_computed(verse_key, min_run, limit):
    """Verses متشابهة with verse_key, computed live from the Quran text —
    fallback for verses the curated corpus doesn't cover. Candidates share a
    contiguous run of ≥ min_run words; kept only if that run is DISTINCTIVE
    (rare across the corpus) or the verses are near-duplicates (see the
    _MUTASHABIHAT_* thresholds above). Returns the candidate's display words,
    the diff opcodes aligning the query (i) to the candidate (j), the longest
    shared run, total shared words, the coverage ratio, and the rarity
    (document-frequency) of the shared run."""
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
        shorter_len = min(len(q_norm), len(c_norm))
        coverage = shared / shorter_len

        # Rarest shingle lying inside any shared run of length ≥ n: the
        # document-frequency of the most distinctive thing the two verses share.
        run_df = None
        for b in blocks:
            for i in range(b.a, b.a + b.size - n + 1):
                d = len(ngram.get(tuple(q_norm[i:i + n]), ()))
                run_df = d if run_df is None else min(run_df, d)

        distinctive = run_df is not None and run_df <= _MUTASHABIHAT_DISTINCT_DF
        near_duplicate = (coverage >= _MUTASHABIHAT_HIGH_COVERAGE
                           and longest / shorter_len >= _MUTASHABIHAT_DUP_RUN_SHARE)
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


def _find_mutashabihat(verse_key, min_run, limit):
    """Curated corpus first; live computation only if the corpus has no
    qualifying match for this verse (no phrase coverage, or nothing distinctive
    enough survived the filter)."""
    matches = _find_mutashabihat_corpus(verse_key, min_run, limit)
    if matches:
        return matches
    return _find_mutashabihat_computed(verse_key, min_run, limit)


@reading_bp.route('/api/mutashabihat/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_mutashabihat(surah_number, ayah_number):
    """المتشابهات: other verses sharing a curated repeated phrase with this
    one — the look-alike passages huffāẓ confuse. Query params: min_run (shared
    phrase length threshold, default 3, clamped 3..8), limit (default 30, max 60)."""
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
