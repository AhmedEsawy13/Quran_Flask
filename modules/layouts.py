"""Mushaf page rendering: layout-DB page payloads + their API routes.

Covers the page sources — الشمرلي (page-local glyph fonts), Madinah 1441
(QPC v4), Madinah 1421 (Digital Khatt / QPC v2), Madinah 1405 (QPC v1), and
مصحف قطر — plus the word-matching helpers that attach printed waqf
marks (any mushaf edition) onto layout words. No app import: routes attach
to core_bp from core.blueprints.
"""
import json
import logging
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from functools import lru_cache

from flask import jsonify, request

from core import layout_persistence
from core.blueprints import core_bp
from core.errors import PersistenceError
from core.config import (
    DIGITAL_KHATT_LAYOUT_DATABASE,
    QPC_V2_LAYOUT_DATABASE, QPC_V1_LAYOUT_DATABASE, QATAR_LAYOUT_DATABASE,
    BAHRAIN_LAYOUT_DATABASE,
    AZHAR_LAYOUT_DATABASE, QURAN_SCRIPT_DATABASE,
    AZHAR_LAYOUT_MIN_PAGE, AZHAR_LAYOUT_MAX_PAGE,
    SHEMRLY_CODEPOINT_BASE, ARABIC_DIACRITICS_STRIP_PATTERN,
    ARABIC_INDIC_DIGIT_PATTERN, _BASE_DIR,
)
from core.text import is_waqf_like_char
from core.datasets import digital_khatt_data, qpc_hafs_data, surahs_data
from core.mushaf_waqf import (
    get_mushaf_waqf_symbols,
)
from modules import layout_engine
from modules.layout_editions import BAHRAIN

logger = logging.getLogger(__name__)

# Tanzil Uthmani (surah|ayah|text) — script source for مصحف قطر editor pages.
QATAR_UTHMANI_TEXT_PATH = os.path.join(_BASE_DIR, 'data', 'quran_text', 'quran-uthmani.txt')
_ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
_AYAH_NUM_CHARS = set('٠١٢٣٤٥٦٧٨٩0123456789')


def _word_ids_in_map_span(word_map, first_word_id, last_word_id):
    """Expand endpoints inside the map's own ID namespace and reading order.

    Madinah layout DBs sometimes use a phantom ``last_word_id`` one past the
    final ayah marker at surah boundaries (e.g. 61191 after يس ۝٨٣). Those IDs
    are absent from the word map — clamp to tokens that exist in the span.
    """
    if first_word_id is None or last_word_id is None:
        return []
    first_word_id = int(first_word_id)
    last_word_id = int(last_word_id)
    id2tok = word_map.get('id2tok') or {}
    ordered_ids = word_map.get('ordered_ids')
    positions = word_map.get('position_by_id')
    if ordered_ids is not None and positions is not None:
        lo = positions.get(first_word_id)
        hi = positions.get(last_word_id)
        if lo is not None and hi is not None and hi >= lo:
            return ordered_ids[lo:hi + 1]
        # Missing endpoint(s): keep contiguous map tokens inside the span.
    if last_word_id < first_word_id:
        return []
    return [
        word_id
        for word_id in range(first_word_id, last_word_id + 1)
        if word_id in id2tok
    ]


@core_bp.route('/api/shamarly/ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_shamarly_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]

        conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM words WHERE surah = ? AND ayah = ? ORDER BY word_index ASC", (surah_number, ayah_number))
        words = [dict(row) for row in cursor.fetchall()]
        conn.close()
        script_word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
        
        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()

        # Fetch pages and verse-line rows in one connection to avoid re-opening.
        if words:
            layout_cursor.execute(
                '''
                SELECT page_number, line_number, line_type,
                       first_word_id, last_word_id
                FROM pages
                WHERE first_word_id IS NOT NULL
                  AND last_word_id IS NOT NULL
                ORDER BY page_number ASC, line_number ASC
                '''
            )
            target_ids = {int(word['word_index']) for word in words}
            matching_rows = [
                dict(row)
                for row in layout_cursor.fetchall()
                if target_ids.intersection(_word_ids_in_map_span(
                    script_word_map,
                    row['first_word_id'],
                    row['last_word_id'],
                ))
            ]
            pages = sorted({
                int(row['page_number']) for row in matching_rows
            })
            _prefetched_line_rows = [
                row for row in matching_rows
                if row['line_type'] in {'ayah', 'basmallah'}
            ]
        else:
            pages = []
            _prefetched_line_rows = []

        layout_conn.close()
        
        shemrly_pages_with_fonts = []
        for page in pages:
            candidate_font = f"Shemrly-Page{int(page):03d}"
            if _get_shamarly_font_supported_codepoints(candidate_font) is not None:
                shemrly_pages_with_fonts.append(int(page))

        # A verse can have a valid layout page without a bundled page-local font.
        # Only advertise fonts that actually exist; otherwise the browser attempts
        # a guaranteed 404 before falling back to the readable Uthmanic text.
        font_name = None
        if shemrly_pages_with_fonts:
            font_name = f"Shemrly-Page{int(shemrly_pages_with_fonts[0]):03d}"

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
            # has a Shemrly-PageNNN.woff2 font loaded in the browser. The old
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
                line_word_ids = set(_word_ids_in_map_span(
                    script_word_map,
                    line['first_word_id'],
                    line['last_word_id'],
                ))
                line_words = []
                for token_index, word in enumerate(words):
                    word_pos = int(word['word_index'])
                    if word_pos in line_word_ids:
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
            'font_pages': shemrly_pages_with_fonts,
            'font_name': font_name,
            'waqf_symbols': waqf_symbols,
            'mushaf_version': (mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or ''))
        })
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل بيانات مصحف الشمرلي') from exc


def _normalize_mushaf_word_token(value):
    text = (value or '').strip()
    if not text:
        return ''
    # NFD-decompose precomposed hamza letters (أ/إ/ؤ/آ) into base letter +
    # combining hamza/maddah so they strip down to the same skeleton as the
    # Digital Khatt source text, which spells those letters in decomposed form.
    text = unicodedata.normalize('NFD', text)
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
    """Map an explicit 1-based within-ayah word position to a list index.

    ``mushaf_waqf.word_index`` is retained as a legacy alias, but it must never
    be interpreted as a layout/global word ID.
    """
    index_space = row.get('index_space')
    if index_space not in (None, 'ayah-content-word-1based'):
        return None
    raw = row.get('word_position')
    if raw is None:
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


def _resolve_token_index_as_layout_offset(words, token_index):
    """Resolve a 0-based within-ayah token_index onto a page word list.

    Cloud published marks store token_index this way. SQLite mushaf_waqf
    token_index values are a different numbering and must not use this path.
    """
    try:
        ti = int(token_index)
    except (TypeError, ValueError):
        return None
    if ti < 0:
        return None

    if (
        words
        and words[0].get('word_id_space') == 'qpc-layout-global-v1'
        and words[0].get('word_index') is not None
        and words[0].get('surah')
        and words[0].get('ayah') is not None
    ):
        try:
            wmap = _get_dk_layout_word_map()
            first_id = wmap['first_id'].get((int(words[0]['surah']), int(words[0]['ayah'])))
        except Exception:
            first_id = None
        if first_id is not None:
            target_gid = first_id + ti
            for idx, word in enumerate(words):
                if int(word.get('word_index') or -1) == target_gid:
                    return idx

    # A partial ayah may occupy this page, so using ``words[ti]`` without a
    # known ID space can silently shift a cloud mark onto the wrong word.
    return None


def _find_mushaf_row_match_index(words, row, search_start=0):
    """Find best token index for a mushaf waqf row.

    Priority:
    1) Optional DB word_index hint (within-ayah content-word position).
    2) Exact token matching (only whitespace removed).
    3) Normalized fallback (diacritics/waqf removed) for script variance.
    4) Explicit 0-based token_index — only when word_index is absent (cloud).

    SQLite mushaf_waqf token_index is not a reliable layout offset (often
    off-by-one vs QPC page words). Prefer word_index + text first so peer
    marks from Madinah/etc. land on the correct word.
    """
    if not words:
        return None

    target_text = _get_row_match_text(row)
    target_raw = _compact_mushaf_word_token(target_text)
    target_norm = _normalize_mushaf_word_token(target_text)

    hinted_by_word_index = _word_index_hint_to_list_index(words, row)

    if not target_raw and not target_norm:
        # Some rows carry no "الكلمة" text at all (a data-entry gap) but do
        # have a usable word_index hint — trust it rather than dropping the
        # mark entirely.
        if hinted_by_word_index is not None and 0 <= hinted_by_word_index < len(words):
            return hinted_by_word_index
        # Cloud rows may have token_index only (no كلمة text, no word_index).
        if row.get('word_index') is None and row.get('token_index') is not None:
            return _resolve_token_index_as_layout_offset(words, row.get('token_index'))
        return None

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

    # Last resort for cloud-only rows (token_index is 0-based layout offset).
    if row.get('word_index') is None and row.get('token_index') is not None:
        return _resolve_token_index_as_layout_offset(words, row.get('token_index'))

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
def _get_shamarly_page_word_ids(page_number):
    """Exact printed word IDs for a page, in Quran reading order."""
    try:
        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        rows = layout_cursor.execute(
            '''
            SELECT first_word_id, last_word_id
            FROM pages
            WHERE page_number = ?
              AND first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ORDER BY line_number
            ''',
            (int(page_number),)
        ).fetchall()
        layout_conn.close()
        word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
        result = []
        seen = set()
        for row in rows:
            for word_id in _word_ids_in_map_span(
                word_map, row['first_word_id'], row['last_word_id'],
            ):
                if word_id not in seen:
                    seen.add(word_id)
                    result.append(word_id)
        return tuple(result)
    except Exception:
        return ()


@lru_cache(maxsize=1024)
def _get_shamarly_page_ayah_word_bounds(page_number):
    """Compatibility endpoints in reading order; do not treat as numeric bounds."""
    word_ids = _get_shamarly_page_word_ids(page_number)
    if not word_ids:
        return (None, None)
    return (word_ids[0], word_ids[-1])


@lru_cache(maxsize=1024)
def _get_shamarly_font_supported_codepoints(font_name):
    """Return supported unicode codepoints for a Shemrly font file.

    Returns:
        set[int] when loaded successfully,
        None when the font file does not exist or cannot be parsed.
    """
    font_path = os.path.join(_BASE_DIR, 'static', 'fonts', f'{font_name}.woff2')
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

    Most per-page fonts hold exactly one glyph per layout word. Exceptional pages
    are handled by the explicit canonical-key overrides loaded below; this fast path
    deliberately rejects a count mismatch instead of guessing and shifting glyphs.
    """
    word_indices = list(_get_shamarly_page_word_ids(page_number))
    if not word_indices:
        return {}

    font_name = f"Shemrly-Page{int(page_number):03d}"
    supported_codepoints = _get_shamarly_font_supported_codepoints(font_name)
    if not supported_codepoints:
        return {}
    present = sorted(c for c in supported_codepoints if c > SHEMRLY_CODEPOINT_BASE)

    # The 1:1 alignment only holds when the font carries exactly one glyph per word.
    # If they disagree (missing font, data drift), bail so the caller can fall back.
    if not word_indices or len(present) != len(word_indices):
        return {}

    return dict(zip(word_indices, present))


@lru_cache(maxsize=1)
def _get_shamarly_page_glyph_override_manifest():
    path = os.path.join(_BASE_DIR, 'data', 'shamarly_page_glyph_overrides.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)
    if int(payload.get('version') or 0) != 1 or not isinstance(payload.get('pages'), dict):
        raise ValueError('Unsupported Shemrly page-glyph override manifest')
    return payload['pages']


@lru_cache(maxsize=1024)
def _get_shamarly_page_glyph_overrides(page_number):
    """Resolve one exceptional page's canonical word keys to glyph strings.

    Values are glyph strings, ``None`` for a Unicode fallback ornament, or an
    empty string when a printed ligature already contains the following token.
    ``None`` as the function return value means the page has no override.
    """
    page = _get_shamarly_page_glyph_override_manifest().get(str(int(page_number)))
    if page is None:
        return None
    supported = _get_shamarly_font_supported_codepoints(
        f"Shemrly-Page{int(page_number):03d}"
    )
    if not supported:
        return None

    word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    key_to_id = word_map['key_to_id']
    resolved = {}
    for word_key, encoded in (page.get('glyphs') or {}).items():
        word_id = key_to_id.get(word_key)
        if word_id is None:
            raise ValueError(f'Unknown Shemrly override word key: {word_key}')
        resolved[int(word_id)] = ''.join(
            chr(int(part, 16)) for part in str(encoded).split()
        )
        if any(ord(char) not in supported for char in resolved[int(word_id)]):
            raise ValueError(f'Shemrly override glyph missing from page font: {word_key}')
    for word_key in page.get('fallback') or []:
        word_id = key_to_id.get(word_key)
        if word_id is None:
            raise ValueError(f'Unknown Shemrly fallback word key: {word_key}')
        resolved[int(word_id)] = None
    for word_key in page.get('suppressed') or []:
        word_id = key_to_id.get(word_key)
        if word_id is None:
            raise ValueError(f'Unknown Shemrly suppressed word key: {word_key}')
        resolved[int(word_id)] = ''
    return resolved


def _get_shamarly_glyph_char_for_word(page_number, word_position):
    """Map a global word index to its Shemrly page-local glyph char."""
    codepoint_map = _get_shamarly_page_word_codepoint_map(page_number)
    wp = int(word_position)
    if wp in codepoint_map:
        return chr(codepoint_map[wp])
    return None


def _get_preferred_legacy_glyph_font_for_range(min_word_id, max_word_id):
    """Pick the dominant legacy Elgharib font for a word range.

    Some ranges span multiple legacy font buckets; using a single dominant bucket
    avoids mixing incompatible glyph codepoint sets in one rendered page.
    """
    if min_word_id is None or max_word_id is None:
        return None

    try:
        glyph_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'glyph_mappings.db'))
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

    # One Supabase round-trip for cloud editions instead of N ayah calls.
    from core.mushaf_waqf import prefetch_cloud_published_for_ayahs
    prefetch_cloud_published_for_ayahs(list(grouped.keys()), versions)

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
    layout_conn = _track(sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db')))
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
    script_word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)

    word_ranges = [
        (line.get('first_word_id'), line.get('last_word_id'))
        for line in lines
        if line.get('first_word_id') is not None and line.get('last_word_id') is not None
    ]
    min_word_id = min((rng[0] for rng in word_ranges), default=None)
    max_word_id = max((rng[1] for rng in word_ranges), default=None)
    preferred_legacy_font = _get_preferred_legacy_glyph_font_for_range(min_word_id, max_word_id)
    shemrly_override = _get_shamarly_page_glyph_overrides(effective_page)
    if shemrly_override is not None:
        expected_override_ids = {
            word_id
            for line in lines
            if line.get('line_type') == 'ayah'
            for word_id in _word_ids_in_map_span(
                script_word_map,
                line.get('first_word_id'),
                line.get('last_word_id'),
            )
        }
        if set(shemrly_override) != expected_override_ids:
            raise ValueError(
                f'Incomplete Shemrly page-glyph override for page {effective_page}'
            )
    shemrly_codepoint_map = _get_shamarly_page_word_codepoint_map(effective_page)
    shemrly_font_available = (
        shemrly_override is not None or bool(shemrly_codepoint_map)
    )

    glyph_by_word_pos = {}
    fallback_word_positions = set()
    suppressed_word_positions = set()
    glyph_score_by_word_pos = {}
    if min_word_id is not None and max_word_id is not None:
        if shemrly_font_available:
            if shemrly_override is not None:
                for word_pos, glyph_text in shemrly_override.items():
                    if glyph_text is None:
                        fallback_word_positions.add(word_pos)
                    elif glyph_text == '':
                        suppressed_word_positions.add(word_pos)
                    else:
                        glyph_by_word_pos[word_pos] = glyph_text
            else:
                glyph_by_word_pos.update({
                    word_pos: chr(codepoint)
                    for word_pos, codepoint in shemrly_codepoint_map.items()
                })
        else:
            glyph_conn = _track(sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'glyph_mappings.db')))
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
        words_conn = _track(sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db')))
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

    page_word_by_index = script_word_map['id2tok']
    page_word_rows = []
    seen_page_words = set()
    for line in lines:
        for word_id in _word_ids_in_map_span(
            script_word_map,
            line.get('first_word_id'),
            line.get('last_word_id'),
        ):
            if word_id in seen_page_words:
                continue
            seen_page_words.add(word_id)
            source = page_word_by_index.get(word_id)
            if source:
                page_word_rows.append({
                    'word_index': word_id,
                    **source,
                })

    waqf_by_word_index = _build_page_waqf_map(page_word_rows, mushaf_version)

    anchor_surah_number = None
    anchor_ayah_number = None
    if page_word_rows:
        first = page_word_rows[0]
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
            line_word_ids = _word_ids_in_map_span(
                script_word_map, first_word_id, last_word_id,
            )
            for word_pos in line_word_ids:
                glyph_char = glyph_by_word_pos.get(word_pos, '')
                fallback_word = page_word_by_index.get(word_pos, {}).get('text') or ''
                suppressed = word_pos in suppressed_word_positions
                use_fallback = word_pos in fallback_word_positions
                rendered_word = '' if suppressed else (
                    fallback_word if use_fallback else (glyph_char or fallback_word)
                )
                if not rendered_word and not suppressed:
                    continue
                if rendered_word:
                    chars.append(rendered_word)
                src_word = page_word_by_index.get(word_pos, {})
                line_words.append({
                    'word_index': word_pos,
                    'word_id_space': script_word_map.get('id_space'),
                    'word_key': src_word.get('word_key') or '',
                    'text': rendered_word,
                    'surah': src_word.get('surah'),
                    'ayah': src_word.get('ayah'),
                    'waqf_symbols': waqf_by_word_index.get(word_pos, ''),
                    'suppress_render': suppressed,
                })

            if chars:
                glyph_text = ' '.join(chars)

            if focus_word_indices:
                contains_focus_ayah = any(
                    word_pos in focus_word_indices
                    for word_pos in line_word_ids
                )

        line_type = line['line_type']
        if (
            not line_words
            and line_type == 'ayah'
            and _looks_like_basmala_text(line.get('line_text'))
        ):
            line_type = 'basmallah'
            glyph_text = line.get('line_text') or ''

        output_lines.append({
            'line_number': line['line_number'],
            'line_type': line_type,
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


@core_bp.route('/api/shamarly/pages', methods=['GET'])
def get_shamarly_available_pages():
    """List mushaf page numbers that ship a real Shemrly-PageNNN.woff2 font.

    Scans static/fonts/ instead of a hardcoded list so newly-added font files
    are picked up automatically without touching frontend code.
    """
    fonts_dir = os.path.join(_BASE_DIR, 'static', 'fonts')
    pages = []
    try:
        for name in os.listdir(fonts_dir):
            m = re.match(r'^Shemrly-Page(\d+)\.woff2$', name)
            if m:
                pages.append(int(m.group(1)))
    except OSError as exc:
        raise PersistenceError('تعذّر تحميل قائمة خطوط الشمرلي') from exc
    pages.sort()
    return jsonify({'pages': pages})


@core_bp.route('/api/shamarly/page/<int:page_number>', methods=['GET'])
def get_shamarly_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_shamarly_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مصحف الشمرلي') from exc


@core_bp.route('/api/shamarly/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_shamarly_page_by_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
        target_ids = {
            word_id
            for word_id, word in word_map['id2tok'].items()
            if int(word['surah']) == int(surah_number)
            and int(word['ayah']) == int(ayah_number)
        }
        if not target_ids:
            return jsonify({'error': 'Ayah not found in script DB'}), 404

        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
        layout_conn.row_factory = sqlite3.Row
        layout_cursor = layout_conn.cursor()
        rows = layout_cursor.execute(
            '''
            SELECT page_number, first_word_id, last_word_id
            FROM pages
            WHERE first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ORDER BY page_number ASC, line_number ASC
            '''
        ).fetchall()
        layout_conn.close()
        row = next(
            (
                item for item in rows
                if target_ids.intersection(_word_ids_in_map_span(
                    word_map, item['first_word_id'], item['last_word_id'],
                ))
            ),
            None,
        )

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
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة الآية') from exc


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
        'append_after_id': {layout_id: [synthetic_id, ...]}
            Extra ayah-end markers when the layout surah span is one short of
            the Digital Khatt token count (e.g. الصافات ۝١٨٢).
    Empty dicts if the source text or layout DB is unavailable.
    """
    global _DK_LAYOUT_WORD_MAP
    if _DK_LAYOUT_WORD_MAP is not None:
        return _DK_LAYOUT_WORD_MAP

    result = {
        'id2tok': {},
        'first_id': {},
        'last_id': {},
        'append_after_id': {},
        'id_space': 'qpc-layout-global-v1',
    }
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
        append_after = result['append_after_id']
        for s in sorted(by_surah):
            if s not in span:
                continue
            cid, cap = span[s]
            for a, text in sorted(by_surah[s]):
                tokens = [w for w in re.split(r'\s+', (text or '').strip()) if w]
                first = None
                overflow = []
                for tok in tokens:
                    if cid > cap:
                        overflow.append(tok)
                        continue
                    if first is None:
                        first = cid
                    id2tok[cid] = {'surah': s, 'ayah': a, 'text': tok}
                    cid += 1
                if first is not None:
                    result['first_id'][(s, a)] = first
                    result['last_id'][(s, a)] = cid - 1
                # Layout span sometimes ends one id before the ayah-end marker
                # (الصافات 182). Keep those markers as synthetic ids appended
                # after the last real layout word on the closing line.
                if overflow:
                    if not all(_is_ayah_number_token(tok) for tok in overflow):
                        logger.warning(
                            'Digital Khatt surah %s ayah %s overflow is not only '
                            'ayah markers: %r', s, a, overflow,
                        )
                    else:
                        anchor = result['last_id'].get((s, a))
                        if anchor is not None:
                            for marker in overflow:
                                synthetic_id = _synthetic_ayah_marker_id(s, a)
                                id2tok[synthetic_id] = {
                                    'surah': s,
                                    'ayah': a,
                                    'text': marker,
                                }
                                append_after.setdefault(anchor, []).append(synthetic_id)
    except Exception as e:
        logger.error(f'Failed to build Digital Khatt layout word map: {e}')

    ordered_ids = sorted(result['id2tok'])
    result['ordered_ids'] = ordered_ids
    result['position_by_id'] = {
        word_id: position
        for position, word_id in enumerate(ordered_ids)
    }
    _DK_LAYOUT_WORD_MAP = result
    return result


# Synthetic layout ids for ayah-end markers that do not fit in the printed
# surah word span (kept outside 1..83668 so they never collide with QPC ids).
_SYNTHETIC_AYAH_MARKER_BASE = 90_000_000


def _synthetic_ayah_marker_id(surah: int, ayah: int) -> int:
    return _SYNTHETIC_AYAH_MARKER_BASE + int(surah) * 1000 + int(ayah)


def _to_arabic_digits(value):
    return ''.join(_ARABIC_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(value))


def _is_ayah_number_token(tok):
    cleaned = (tok or '').replace('\u00a0', '').replace('۝', '')
    return bool(cleaned) and all(ch in _AYAH_NUM_CHARS for ch in cleaned)


_BASMALA_LINE_RE = re.compile(r'^ب[\u0651\u0650]?\u0650?س')


def _looks_like_basmala_text(text: str | None) -> bool:
    """True for a standalone basmala line (not an ayah that merely starts with it)."""
    cleaned = re.sub(r'\s+', ' ', (text or '').strip())
    if not cleaned:
        return False
    if cleaned in (
        'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ',
        'بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ',
        'بِّسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ',
        'بِّسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ',
    ):
        return True
    # Compact form: basmala only (≤ 4 tokens).
    parts = cleaned.split(' ')
    return len(parts) <= 4 and bool(_BASMALA_LINE_RE.match(parts[0]))


_QPC_HAFS_LAYOUT_WORD_MAP = None


def _get_qpc_hafs_layout_word_map():
    """Like ``_get_dk_layout_word_map`` but with QPC Hafs (``qpc_hafs_data``)
    text — the script مصحف قطر's own layout is set in.

    Reuses the Digital Khatt map's word-id ranges per (surah, ayah) (the
    1..83668 numbering used by every 15-line layout DB), since switching text
    source must not move any word_id used by mushaf_waqf.db. QPC Hafs
    tokenises a small number of verses differently (e.g. a leading ۞ is its
    own token, vs glued to the next word in the Digital Khatt source) — for
    those verses we keep the Digital Khatt tokens so the per-verse word count
    still matches the layout's ranges.

    Unlike the Digital Khatt map, the ayah-end token here is the BARE digit
    string with no leading ۝ (U+06DD): in the Uthmanic Hafs font the digits
    already render inside their own end-of-ayah circle, and prefixing ۝ (which
    renders as its own empty circle in this font, unlike Old Madina where it
    ligates) produces two adjacent circles.
    """
    global _QPC_HAFS_LAYOUT_WORD_MAP
    if _QPC_HAFS_LAYOUT_WORD_MAP is not None:
        return _QPC_HAFS_LAYOUT_WORD_MAP

    dk_map = _get_dk_layout_word_map()
    result = {
        'id2tok': {},
        'first_id': dk_map['first_id'],
        'last_id': dk_map['last_id'],
        'append_after_id': dict(dk_map.get('append_after_id') or {}),
        'id_space': dk_map['id_space'],
        'ordered_ids': dk_map['ordered_ids'],
        'position_by_id': dk_map['position_by_id'],
    }
    id2tok = result['id2tok']
    dk_id2tok = dk_map['id2tok']

    try:
        for (s, a), first in dk_map['first_id'].items():
            last = dk_map['last_id'][(s, a)]
            count = last - first + 1
            entry = qpc_hafs_data.get(f'{s}:{a}')
            tokens = [w for w in re.split(r'\s+', (entry.get('text') or '').strip()) if w] if entry else []
            if len(tokens) == count:
                for i in range(count):
                    id2tok[first + i] = {'surah': s, 'ayah': a, 'text': tokens[i]}
            else:
                # Tokenisation mismatch (e.g. leading ۞ split differently) —
                # fall back to the Digital Khatt tokens for this verse.
                for wid in range(first, last + 1):
                    if wid in dk_id2tok:
                        tok = dk_id2tok[wid]
                        if wid == last and tok['text'].startswith('۝'):
                            tok = {**tok, 'text': tok['text'][1:]}
                        id2tok[wid] = tok
        # Preserve synthetic overflow ayah markers from the DK map.
        for anchor, syn_ids in (dk_map.get('append_after_id') or {}).items():
            for syn_id in syn_ids:
                tok = dk_id2tok.get(syn_id)
                if not tok:
                    continue
                text = tok['text']
                if text.startswith('۝'):
                    text = text[1:]
                id2tok[syn_id] = {**tok, 'text': text}
    except Exception as e:
        logger.error(f'Failed to build QPC Hafs layout word map: {e}')
        return dk_map

    _QPC_HAFS_LAYOUT_WORD_MAP = result
    return result


@lru_cache(maxsize=1)
def _load_tanzil_uthmani_ayahs():
    """Parse data/quran_text/quran-uthmani.txt → {(surah, ayah): text}."""
    out = {}
    if not os.path.exists(QATAR_UTHMANI_TEXT_PATH):
        logger.warning('Qatar Uthmani text missing: %s', QATAR_UTHMANI_TEXT_PATH)
        return out
    with open(QATAR_UTHMANI_TEXT_PATH, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|', 2)
            if len(parts) != 3:
                continue
            try:
                surah, ayah = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            out[(surah, ayah)] = parts[2]
    return out


def _uthmani_content_tokens(surah, ayah, text):
    """Space-split Tanzil Uthmani ayah text; drop leading basmala on surah starts.

    Also normalize markers that Tanzil emits as free tokens but layout word
    ranges attach to a neighboring word (hizb ۞, sajda ۩).
    """
    tokens = [w for w in re.split(r'\s+', (text or '').strip()) if w]
    # Tanzil prepends the basmala to ayah 1 of every surah except التوبة (and
    # الفاتحة where the basmala IS the ayah). Layout word ranges never include it.
    if ayah == 1 and surah not in (1, 9) and len(tokens) >= 5 and tokens[0].startswith('ب'):
        if 'بِسْم' in tokens[0] or 'بِّسْم' in tokens[0] or 'بِسۡم' in tokens[0]:
            tokens = tokens[4:]
    # ۞ is a separate token in Tanzil; QPC/DK glue it to the next word.
    merged = []
    i = 0
    while i < len(tokens):
        if tokens[i] == '۞' and i + 1 < len(tokens):
            merged.append('۞' + tokens[i + 1])
            i += 2
            continue
        merged.append(tokens[i])
        i += 1
    tokens = merged
    # Trailing standalone ۩ (sajda) is glued to the previous word in layouts.
    if len(tokens) >= 2 and tokens[-1] == '۩':
        tokens = tokens[:-2] + [tokens[-2] + '۩']
    # A few Tanzil splits that mushaf word maps keep as one token.
    glued = {
        ('لَّوْ', 'مَا'): 'لَّوْمَا',
        ('مَا', 'لِىَ'): 'مَالِيَ',
        ('وَمَا', 'لِىَ'): 'وَمَالِيَ',
    }
    out = []
    i = 0
    while i < len(tokens):
        pair = (tokens[i], tokens[i + 1]) if i + 1 < len(tokens) else None
        if pair in glued:
            out.append(glued[pair])
            i += 2
            continue
        out.append(tokens[i])
        i += 1
    return out


_QATAR_UTHMANI_LAYOUT_WORD_MAP = None


def _get_qatar_uthmani_layout_word_map():
    """Layout word map for مصحف قطر using Tanzil Uthmani text + KATypical Naskh.

    Keeps Digital Khatt word-id ranges (1..83668). For each ayah, prefer
    Tanzil tokens (+ trailing Arabic ayah digit) when the count matches;
    otherwise fall back to the QPC Hafs map so waqf indexing stays intact.
    """
    global _QATAR_UTHMANI_LAYOUT_WORD_MAP
    if _QATAR_UTHMANI_LAYOUT_WORD_MAP is not None:
        return _QATAR_UTHMANI_LAYOUT_WORD_MAP

    dk_map = _get_dk_layout_word_map()
    qpc_map = _get_qpc_hafs_layout_word_map()
    uthmani = _load_tanzil_uthmani_ayahs()
    result = {
        'id2tok': {},
        'first_id': dk_map['first_id'],
        'last_id': dk_map['last_id'],
        'append_after_id': dict(dk_map.get('append_after_id') or {}),
        'id_space': dk_map['id_space'],
        'ordered_ids': dk_map['ordered_ids'],
        'position_by_id': dk_map['position_by_id'],
    }
    id2tok = result['id2tok']
    matched = fallback = 0

    try:
        for (s, a), first in dk_map['first_id'].items():
            last = dk_map['last_id'][(s, a)]
            count = last - first + 1
            raw = uthmani.get((s, a), '')
            content = _uthmani_content_tokens(s, a, raw)
            # Layout ranges usually include a trailing ayah-number token.
            tokens = content + [_to_arabic_digits(a)] if content else []
            if len(tokens) != count and content and len(content) == count:
                # Rare: layout word range omits the ayah digit (e.g. 37:182).
                tokens = content
            if len(tokens) == count:
                matched += 1
                for i in range(count):
                    id2tok[first + i] = {'surah': s, 'ayah': a, 'text': tokens[i]}
            else:
                fallback += 1
                for wid in range(first, last + 1):
                    if wid in qpc_map['id2tok']:
                        id2tok[wid] = qpc_map['id2tok'][wid]
                    elif wid in dk_map['id2tok']:
                        tok = dk_map['id2tok'][wid]
                        if wid == last and tok['text'].startswith('۝'):
                            tok = {**tok, 'text': tok['text'][1:]}
                        id2tok[wid] = tok
        for anchor, syn_ids in (dk_map.get('append_after_id') or {}).items():
            for syn_id in syn_ids:
                tok = dk_map['id2tok'].get(syn_id) or qpc_map['id2tok'].get(syn_id)
                if not tok:
                    continue
                # Qatar/Uthmani ayah digits render without a leading ۝.
                text = tok['text'][1:] if tok['text'].startswith('۝') else tok['text']
                id2tok[syn_id] = {**tok, 'text': text}
        logger.info(
            'Qatar Uthmani word map: %d ayahs matched, %d fell back to QPC Hafs',
            matched, fallback,
        )
    except Exception as e:
        logger.error(f'Failed to build Qatar Uthmani layout word map: {e}')
        return qpc_map

    _QATAR_UTHMANI_LAYOUT_WORD_MAP = result
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
                          source, font_name_default, include_advance, mushaf_version='',
                          word_map=None):
    """Shared page-payload assembler for the Digital Khatt / QPC-v1 / قطر layouts.
    Words come from the authoritative Digital Khatt word map (or `word_map`,
    if given) keyed on the layout's word ids, so the rendered text always
    matches the page.

    `mushaf_version` (str or list) selects which print's waqf symbols to attach
    per word — same mechanism the main app uses."""
    effective_word_map = word_map or _get_dk_layout_word_map()
    id2tok = effective_word_map['id2tok']

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
            line_word_ids = list(_word_ids_in_map_span(
                effective_word_map, first_word_id, last_word_id,
            ))
            line_word_ids.extend(
                (effective_word_map.get('append_after_id') or {}).get(last_word_id, [])
            )
            for word_id in line_word_ids:
                tok = id2tok.get(word_id)
                if not tok:
                    continue
                word = {
                    'word_index': word_id,
                    'word_id_space': effective_word_map.get('id_space'),
                    'word_key': tok.get('word_key') or '',
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
            # Placeholder basmala rows sometimes keep line_type=ayah with
            # reserved word ids outside the map — promote them so the UI
            # still renders the basmala.
            if (
                not line_words
                and line_type == 'ayah'
                and _looks_like_basmala_text(line.get('line_text'))
            ):
                line_type = 'basmallah'
                display_text = bismillah
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
        justified = [line.get('total_advance') for line in output_lines
                     if line.get('total_advance') and not line.get('x_offset')]
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


@core_bp.route('/api/digital-khatt/page/<int:page_number>', methods=['GET'])
def get_digital_khatt_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_digital_khatt_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مصحف المدينة ١٤٢١هـ') from exc


@core_bp.route('/api/digital-khatt/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة الآية') from exc


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


def _build_qpc_v2_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    """Build Madinah 1421 from the Digital Khatt / QPC V2 layout database."""
    if not os.path.exists(QPC_V2_LAYOUT_DATABASE):
        return None

    layout_conn = sqlite3.connect(QPC_V2_LAYOUT_DATABASE)
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
        source='qpc_v2', font_name_default='Digital Khatt', include_advance=False,
        mushaf_version=mushaf_version
    )
    payload['font_name'] = 'Digital Khatt'
    # The upstream DB's info.name is truncated, so expose a stable complete name.
    payload['layout_name'] = 'Digital Khatt (KFGQPC V2 1421H print)'
    payload['mushaf_version'] = (
        mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or '')
    )
    return payload


def _build_bahrain_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    """Build مصحف البحرين from the Layout Studio project DB.

    Prefers ``mushaf-bahrain-layout.db`` so waqf-editor pages follow studio line
    edits. Falls back to shared QPC V2 when the project has not been seeded.
    """
    layout_db = layout_persistence.working_db_path(BAHRAIN)
    source = 'mushaf_bahrain'
    layout_name = 'مصحف البحرين · تخطيط المدينة ١٤٢١'
    if not os.path.exists(layout_db):
        layout_db = QPC_V2_LAYOUT_DATABASE
        source = 'qpc_v2'
        layout_name = 'Digital Khatt (KFGQPC V2 1421H print)'
        if not os.path.exists(layout_db):
            return None

    layout_conn = sqlite3.connect(layout_db)
    try:
        layout_conn.row_factory = sqlite3.Row
        lc = layout_conn.cursor()
        lc.execute(
            'SELECT page_number, line_number, line_type, is_centered, '
            'first_word_id, last_word_id, surah_number '
            'FROM pages WHERE page_number = ? ORDER BY line_number ASC',
            (page_number,)
        )
        lines = [dict(row) for row in lc.fetchall()]
        lc.execute(
            'SELECT font_name, number_of_pages, lines_per_page, name '
            'FROM info LIMIT 1'
        )
        info_row = lc.fetchone()
    finally:
        layout_conn.close()

    if not lines:
        return None

    # Same 1..83668 word ids as Digital Khatt / QPC V2.
    payload = _assemble_layout_page(
        lines, info_row, page_number, focus_surah, focus_ayah,
        source=source, font_name_default='Digital Khatt', include_advance=False,
        mushaf_version=mushaf_version,
    )
    payload['font_name'] = 'Digital Khatt'
    payload['layout_name'] = (
        (info_row['name'] if info_row and info_row['name'] else None) or layout_name
    )
    payload['mushaf_version'] = (
        mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or '')
    )
    return payload


def _build_qatar_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    """Build a page payload from مصحف قطر's own 15-line layout database,
    rendered with Tanzil Uthmani text (KATypical Naskh in the editor)."""
    if not os.path.exists(QATAR_LAYOUT_DATABASE):
        return None

    layout_conn = sqlite3.connect(QATAR_LAYOUT_DATABASE)
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
        source='mushaf_qatar', font_name_default='KATypical Naskh', include_advance=False,
        mushaf_version=mushaf_version, word_map=_get_qatar_uthmani_layout_word_map()
    )
    payload['layout_name'] = (info_row['name'] if info_row else 'مصحف قطر')
    payload['font_name'] = 'KATypical Naskh'
    payload['mushaf_version'] = (
        mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or '')
    )
    return payload


@core_bp.route('/api/qpc-v1/page/<int:page_number>', methods=['GET'])
def get_qpc_v1_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_qpc_v1_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مصحف المدينة القديم') from exc


@core_bp.route('/api/qpc-v2/page/<int:page_number>', methods=['GET'])
def get_qpc_v2_page(page_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        payload = _build_qpc_v2_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مصحف المدينة') from exc


@core_bp.route('/api/qpc-v1/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
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
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة الآية') from exc


@core_bp.route('/api/qpc-v2/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_qpc_v2_page_by_ayah(surah_number, ayah_number):
    try:
        if not os.path.exists(QPC_V2_LAYOUT_DATABASE):
            return jsonify({'error': 'QPC V2 layout DB not found'}), 404

        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        page_number = _layout_page_resolve(QPC_V2_LAYOUT_DATABASE, surah_number, ayah_number)
        if page_number is None:
            return jsonify({'error': 'Page not found for ayah'}), 404

        payload = _build_qpc_v2_page_payload(page_number, focus_surah=surah_number, focus_ayah=ayah_number,
                                             mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة الآية') from exc


def _build_azhar_page_payload(page_number, focus_surah=None, focus_ayah=None, mushaf_version=''):
    """Azhar page: Shemrly-seeded geometry + Amiri unicode text (no page glyphs)."""
    if not os.path.exists(AZHAR_LAYOUT_DATABASE):
        return None
    _open_conns = []

    def _track(c):
        _open_conns.append(c)
        return c

    try:
        return _build_azhar_page_payload_impl(
            page_number, focus_surah, focus_ayah, mushaf_version, _track
        )
    finally:
        for c in _open_conns:
            try:
                c.close()
            except Exception:
                pass


def _build_azhar_page_payload_impl(page_number, focus_surah, focus_ayah, mushaf_version, _track):
    layout_conn = _track(sqlite3.connect(AZHAR_LAYOUT_DATABASE))
    layout_conn.row_factory = sqlite3.Row
    layout_cursor = layout_conn.cursor()
    layout_cursor.execute(
        '''
        SELECT page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number ASC
        ''',
        (page_number,),
    )
    lines = [dict(row) for row in layout_cursor.fetchall()]
    layout_cursor.execute(
        'SELECT font_name, number_of_pages, lines_per_page, name FROM info LIMIT 1'
    )
    info_row = layout_cursor.fetchone()
    layout_conn.close()
    if not lines:
        return None

    focus_word_indices = set()
    if focus_surah is not None and focus_ayah is not None:
        words_conn = _track(sqlite3.connect(QURAN_SCRIPT_DATABASE))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            'SELECT word_index FROM words WHERE surah = ? AND ayah = ?',
            (focus_surah, focus_ayah),
        )
        focus_word_indices = {int(row['word_index']) for row in words_cursor.fetchall()}
        words_conn.close()

    script_word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    page_word_by_index = script_word_map['id2tok']

    bismillah = 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ'
    page_word_rows = []
    output_lines = []
    anchor_surah_number = None
    anchor_ayah_number = None

    for line in lines:
        first_word_id = line.get('first_word_id')
        last_word_id = line.get('last_word_id')
        line_type = line.get('line_type')
        line_surah = line.get('surah_number')
        line_words = []
        display_text = ''
        contains_focus_ayah = False

        if line_type in ('surah_name', 'surah_info', 'basmallah'):
            if line_type == 'surah_name':
                surah_name = _get_surah_name_ar(line_surah)
                display_text = f'سورة {surah_name}' if surah_name else (line.get('line_text') or '')
            elif line_type == 'surah_info':
                display_text = (line.get('line_text') or '').strip()
                if not display_text and line_surah:
                    from modules import layout_engine as _layout_engine
                    display_text = _layout_engine.surah_info_text(
                        int(line_surah), script_db=QURAN_SCRIPT_DATABASE,
                    )
            else:
                display_text = bismillah
        elif first_word_id is not None and last_word_id is not None:
            # Endpoints belong to quran_script's stable-ID namespace; expand
            # them in Quran reading order, not numeric-ID order.
            for word_pos in _word_ids_in_map_span(
                script_word_map, first_word_id, last_word_id,
            ):
                src = page_word_by_index.get(word_pos)
                if not src or not src.get('text'):
                    continue
                word = {
                    'word_index': word_pos,
                    'word_id_space': script_word_map.get('id_space'),
                    'word_key': src.get('word_key') or '',
                    'text': src['text'],
                    'surah': src['surah'],
                    'ayah': src['ayah'],
                    'waqf_symbols': '',
                    'is_line_start': False,
                    'is_line_end': False,
                }
                line_words.append(word)
                page_word_rows.append(word)
                if anchor_surah_number is None:
                    anchor_surah_number = src['surah']
                    anchor_ayah_number = src['ayah']
                if focus_word_indices and word_pos in focus_word_indices:
                    contains_focus_ayah = True
            if line_words:
                line_words[0]['is_line_start'] = True
                line_words[-1]['is_line_end'] = True
            display_text = ' '.join(w['text'] for w in line_words)
            if (
                not line_words
                and line_type == 'ayah'
                and _looks_like_basmala_text(line.get('line_text'))
            ):
                line_type = 'basmallah'
                display_text = bismillah

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
        })

    versions = mushaf_version if isinstance(mushaf_version, list) else ([mushaf_version] if mushaf_version else [])
    if not versions:
        versions = ['الأزهر']
    waqf_by_word_index = _build_page_waqf_map(page_word_rows, versions)
    if waqf_by_word_index:
        for word in page_word_rows:
            entries = waqf_by_word_index.get(word['word_index'])
            if entries:
                word['waqf_symbols'] = entries

    def info_get(key, default=None):
        if info_row is not None:
            try:
                if key in info_row.keys():
                    return info_row[key]
            except AttributeError:
                pass
        return default

    # Per-page line count (الفاتحة=6, أول البقرة=5; most pages=15). Editor font
    # sizing and short-page chrome key off this, not the mushaf-wide default.
    page_line_count = len(output_lines) if output_lines else int(info_get('lines_per_page') or 15)
    return {
        'source': 'azhar',
        'page_number': int(page_number),
        'font_name': 'Amiri Quran',
        'layout_name': info_get('name', 'مصحف الأزهر'),
        'lines_per_page': page_line_count,
        'default_lines_per_page': int(info_get('lines_per_page') or 15),
        'min_page': AZHAR_LAYOUT_MIN_PAGE,
        'max_page': AZHAR_LAYOUT_MAX_PAGE,
        'page_content_width': None,
        'focus_surah': focus_surah,
        'focus_ayah': focus_ayah,
        'lines': output_lines,
        'anchor_surah_number': anchor_surah_number,
        'anchor_ayah_number': anchor_ayah_number,
        'mushaf_version': (
            versions[0] if versions else 'الأزهر'
        ),
    }


def _azhar_pages_for_ayah(surah_number, ayah_number):
    """All Azhar layout pages that contain any word of the ayah (mid-ayah aware)."""
    if not os.path.exists(AZHAR_LAYOUT_DATABASE) or not os.path.exists(QURAN_SCRIPT_DATABASE):
        return []
    word_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    indices = {
        word_id
        for word_id, word in word_map['id2tok'].items()
        if int(word['surah']) == int(surah_number)
        and int(word['ayah']) == int(ayah_number)
    }
    if not indices:
        return []

    layout_conn = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        layout_conn.row_factory = sqlite3.Row
        cur = layout_conn.cursor()
        pages = set()
        rows = cur.execute(
            '''
            SELECT page_number, first_word_id, last_word_id
            FROM pages
            WHERE first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ORDER BY page_number, line_number
            '''
        ).fetchall()
        for row in rows:
            span = _word_ids_in_map_span(
                word_map, row['first_word_id'], row['last_word_id'],
            )
            if indices.intersection(span):
                pages.add(int(row['page_number']))
        return sorted(pages)
    finally:
        layout_conn.close()


@core_bp.route('/api/azhar/page/<int:page_number>', methods=['GET'])
def get_azhar_page(page_number):
    try:
        if not (AZHAR_LAYOUT_MIN_PAGE <= page_number <= AZHAR_LAYOUT_MAX_PAGE):
            return jsonify({
                'error': f'page_number must be between {AZHAR_LAYOUT_MIN_PAGE} and {AZHAR_LAYOUT_MAX_PAGE}'
            }), 400
        mushaf_version = request.args.getlist('mushaf_version') or [
            request.args.get('mushaf_version', 'الأزهر').strip() or 'الأزهر'
        ]
        payload = _build_azhar_page_payload(page_number, mushaf_version=mushaf_version)
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مصحف الأزهر') from exc


@core_bp.route('/api/azhar/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_azhar_page_by_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [
            request.args.get('mushaf_version', 'الأزهر').strip() or 'الأزهر'
        ]
        pages = _azhar_pages_for_ayah(surah_number, ayah_number)
        if not pages:
            return jsonify({'error': 'Page not found for ayah'}), 404
        page_number = pages[0]
        payload = _build_azhar_page_payload(
            page_number,
            focus_surah=surah_number,
            focus_ayah=ayah_number,
            mushaf_version=mushaf_version,
        )
        if not payload:
            return jsonify({'error': 'Page not found'}), 404
        payload['pages_for_ayah'] = pages
        return jsonify(payload)
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة الآية') from exc
