"""Mushaf page rendering: layout-DB page payloads + their API routes.

Covers the four page sources — الشمرلي (page-local glyph fonts), Digital
Khatt / "المدينة الجديد" (QPC v4 15-line layout), QPC v1 "المدينة ١٤٠٥",
and مصحف قطر — plus the word-matching helpers that attach printed waqf
marks (any mushaf edition) onto layout words. No app import: routes attach
to core_bp from core.blueprints.
"""
import logging
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from functools import lru_cache

from flask import jsonify, request

from core.blueprints import core_bp
from core.config import (
    DIGITAL_KHATT_LAYOUT_DATABASE,
    QPC_V1_LAYOUT_DATABASE, QATAR_LAYOUT_DATABASE,
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

logger = logging.getLogger(__name__)

# Tanzil Uthmani (surah|ayah|text) — script source for مصحف قطر editor pages.
QATAR_UTHMANI_TEXT_PATH = os.path.join(_BASE_DIR, 'data', 'quran_text', 'quran-uthmani.txt')
_ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
_AYAH_NUM_CHARS = set('٠١٢٣٤٥٦٧٨٩0123456789')


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
        
        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
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
            'font_pages': shemrly_pages_with_fonts,
            'font_name': font_name,
            'waqf_symbols': waqf_symbols,
            'mushaf_version': (mushaf_version[0] if isinstance(mushaf_version, list) and mushaf_version else (mushaf_version or ''))
        })
    except Exception as e:
        logger.error(f"Error fetching shamarly data: {e}")
        return jsonify({"error": str(e)}), 500


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
    0) Explicit 0-based token_index (cloud published marks / layout offset).
    1) Optional DB word_index hint (within-ayah content-word position).
    2) Exact token matching (only whitespace removed).
    3) Normalized fallback (diacritics/waqf removed) for script variance.
    """
    if not words:
        return None

    # Cloud marks store 0-based offset within the full ayah. When the word list
    # is a page slice, resolve via global word_index = first_of_ayah + token.
    raw_ti = row.get('token_index')
    if raw_ti is not None:
        try:
            ti = int(raw_ti)
        except (TypeError, ValueError):
            ti = None
        if ti is not None and ti >= 0:
            if words and words[0].get('word_index') is not None and words[0].get('surah') and words[0].get('ayah') is not None:
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
            elif 0 <= ti < len(words):
                return ti

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
        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
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

        words_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db'))
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
        words_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db'))
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

    page_word_rows = []
    page_word_by_index = {}
    if min_word_id is not None and max_word_id is not None:
        words_conn = _track(sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db')))
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
    except OSError as e:
        logger.error(f"Error listing Shemrly fonts: {e}")
        return jsonify({"error": str(e)}), 500
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
    except Exception as e:
        logger.error(f"Error fetching Shamarly page {page_number}: {e}")
        return jsonify({"error": str(e)}), 500


@core_bp.route('/api/shamarly/page-by-ayah/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_shamarly_page_by_ayah(surah_number, ayah_number):
    try:
        mushaf_version = request.args.getlist('mushaf_version') or [request.args.get('mushaf_version', '').strip()]
        words_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'quran_script.db'))
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

        layout_conn = sqlite3.connect(os.path.join(_BASE_DIR, 'data', 'mushaf_layout_inferred.db'))
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
        logger.error(f"Error fetching Shamarly page by ayah {surah_number}:{ayah_number}: {e}")
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
        logger.error(f'Failed to build Digital Khatt layout word map: {e}')

    _DK_LAYOUT_WORD_MAP = result
    return result


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
    result = {'id2tok': {}, 'first_id': dk_map['first_id'], 'last_id': dk_map['last_id']}
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
    except Exception as e:
        logger.error(f'Failed to build QPC Hafs layout word map: {e}')
        return dk_map

    _QPC_HAFS_LAYOUT_WORD_MAP = result
    return result


def _to_arabic_digits(value):
    return ''.join(_ARABIC_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(value))


def _is_ayah_number_token(tok):
    cleaned = (tok or '').replace('\u00a0', '').replace('۝', '')
    return bool(cleaned) and all(ch in _AYAH_NUM_CHARS for ch in cleaned)


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
    result = {'id2tok': {}, 'first_id': dk_map['first_id'], 'last_id': dk_map['last_id']}
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
    id2tok = (word_map or _get_dk_layout_word_map())['id2tok']

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
    except Exception as e:
        logger.error(f"Error fetching Digital Khatt page {page_number}: {e}")
        return jsonify({'error': str(e)}), 500


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
    except Exception as e:
        logger.error(f"Error fetching Digital Khatt page by ayah {surah_number}:{ayah_number}: {e}")
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
    except Exception as e:
        logger.error(f"Error fetching QPC V1 page {page_number}: {e}")
        return jsonify({'error': str(e)}), 500


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
    except Exception as e:
        logger.error(f"Error fetching QPC V1 page by ayah {surah_number}:{ayah_number}: {e}")
        return jsonify({'error': str(e)}), 500


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

    word_ranges = [
        (line.get('first_word_id'), line.get('last_word_id'))
        for line in lines
        if line.get('first_word_id') is not None and line.get('last_word_id') is not None
    ]
    min_word_id = min((int(rng[0]) for rng in word_ranges), default=None)
    max_word_id = max((int(rng[1]) for rng in word_ranges), default=None)

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

    page_word_by_index = {}
    if min_word_id is not None and max_word_id is not None:
        words_conn = _track(sqlite3.connect(QURAN_SCRIPT_DATABASE))
        words_conn.row_factory = sqlite3.Row
        words_cursor = words_conn.cursor()
        words_cursor.execute(
            '''
            SELECT word_index, surah, ayah, text
            FROM words
            WHERE word_index BETWEEN ? AND ?
            ORDER BY word_index ASC
            ''',
            (min_word_id, max_word_id),
        )
        for row in words_cursor.fetchall():
            page_word_by_index[int(row['word_index'])] = {
                'word_index': int(row['word_index']),
                'surah': int(row['surah']),
                'ayah': int(row['ayah']),
                'text': row['text'] or '',
            }
        words_conn.close()

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

        if first_word_id is not None and last_word_id is not None:
            # Walk only ids present in quran_script (Shemrly gaps are skipped).
            for word_pos in sorted(
                wid for wid in page_word_by_index
                if int(first_word_id) <= wid <= int(last_word_id)
            ):
                src = page_word_by_index.get(word_pos)
                if not src or not src.get('text'):
                    continue
                word = {
                    'word_index': word_pos,
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
        elif line_type == 'surah_name':
            surah_name = _get_surah_name_ar(line_surah)
            display_text = f'سورة {surah_name}' if surah_name else (line.get('line_text') or '')
        elif line_type == 'basmallah':
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

    # Per-page line count (Fatiha is 5; most pages are 15). Editor font
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
    words_conn = sqlite3.connect(QURAN_SCRIPT_DATABASE)
    try:
        words_conn.row_factory = sqlite3.Row
        cur = words_conn.cursor()
        cur.execute(
            'SELECT word_index FROM words WHERE surah = ? AND ayah = ?',
            (surah_number, ayah_number),
        )
        indices = [int(r['word_index']) for r in cur.fetchall()]
    finally:
        words_conn.close()
    if not indices:
        return []

    layout_conn = sqlite3.connect(AZHAR_LAYOUT_DATABASE)
    try:
        layout_conn.row_factory = sqlite3.Row
        cur = layout_conn.cursor()
        pages = set()
        for word_id in indices:
            cur.execute(
                '''
                SELECT DISTINCT page_number FROM pages
                WHERE first_word_id IS NOT NULL AND last_word_id IS NOT NULL
                  AND first_word_id <= ? AND last_word_id >= ?
                ''',
                (word_id, word_id),
            )
            for row in cur.fetchall():
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
    except Exception as e:
        logger.error(f'Error fetching Azhar page {page_number}: {e}')
        return jsonify({'error': str(e)}), 500


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
    except Exception as e:
        logger.error(f'Error fetching Azhar page by ayah {surah_number}:{ayah_number}: {e}')
        return jsonify({'error': str(e)}), 500
