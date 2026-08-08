"""Plan A — phone checklist to revise printed mushaf waqf marks page-by-page.

Start mushaf-by-mushaf with الشمرلي: Shemrly page geometry, Quran font for
words, and real stop glyphs (ۘۗۖ…) instead of letter stand-ins (م/ص/ق).
"""
from __future__ import annotations

import logging
import sqlite3

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.config import MUSHAF_WAQF_DATABASE
from core.db import connect as _sqlite_connect
from core.errors import PersistenceError
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core import supabase_editor as sb
from core.datasets import qpc_hafs_data_normalized, surahs_data
from modules.editor import (
    _find_mushaf_row_match_index,
)
from modules.editor_auth import current_editor, require_editor
from modules.layouts import _build_shamarly_page_payload

logger = logging.getLogger(__name__)

# Review decisions/notes/progress live here locally (same file as marks by default).
# Tests may point this at a temp DB without breaking mark lookups.
MARK_REVIEW_STORE_DATABASE = MUSHAF_WAQF_DATABASE

# Mushaf-by-mushaf rollout — only الشمرلي for now.
REVIEW_EDITIONS = (
    {
        'id': 'الشمرلي',
        'label': 'مصحف الشمرلي',
        'builder': 'shamarly',
        'max_page': 522,
        'min_page': 2,
    },
)

_REVIEW_BY_ID = {e['id']: e for e in REVIEW_EDITIONS}

# Letter codes stored in mushaf_waqf.db → printed stop glyphs (Hafs system).
_WAQF_GLYPH_MAP = {
    'م': 'ۘ', 'قلى': 'ۗ', 'قلي': 'ۗ', 'ق': 'ۗ',
    'صلى': 'ۖ', 'صلي': 'ۖ', 'ص': 'ۖ', 'ج': 'ۚ',
    'لا': 'ۙ', 'س': 'ۜ', 'ع': 'ۛ',
    'ۘ': 'ۘ', 'ۗ': 'ۗ', 'ۖ': 'ۖ', 'ۚ': 'ۚ', 'ۙ': 'ۙ', 'ۛ': 'ۛ', 'ۜ': 'ۜ',
}

_SYMBOL_META = (
    ('م', 'ۘ', 'لازم'),
    ('لا', 'ۙ', 'لا وقف'),
    ('ق', 'ۗ', 'الوقف أولى'),
    ('ص', 'ۖ', 'الوصل أولى'),
    ('ج', 'ۚ', 'جائز'),
    ('س', 'ۜ', 'سكتة'),
    ('ع', 'ۛ', 'معانقة'),
)

# Letter codes → how reviewers write them on paper (صلى / قلى / ج …).
_MARK_WRITE_FORM = {
    'ص': 'صلى',
    'صلي': 'صلى',
    'صلى': 'صلى',
    'ق': 'قلى',
    'قلي': 'قلى',
    'قلى': 'قلى',
    'م': 'م',
    'ج': 'ج',
    'لا': 'لا',
    'س': 'س',
    'ع': 'ع',
}

_SYMBOL_CHOICES = tuple(code for code, _glyph, _name in _SYMBOL_META)

# Madina-style juz page starts (mirrors static/js/athar-page-chrome.js JUZ_START_PAGE).
JUZ_START_PAGE = (
    1, 22, 42, 62, 82, 102, 121, 142, 162, 182,
    201, 222, 242, 262, 282, 302, 322, 342, 362, 382,
    402, 422, 442, 462, 482, 502, 522, 542, 562, 582,
)

# Print packs: 10 juz each (phase 1 validates density on pack 1).
PRINT_PACKS = {
    1: {'juz_from': 1, 'juz_to': 10, 'label': 'الأجزاء ١–١٠'},
    2: {'juz_from': 11, 'juz_to': 20, 'label': 'الأجزاء ١١–٢٠'},
    3: {'juz_from': 21, 'juz_to': 30, 'label': 'الأجزاء ٢١–٣٠'},
}

# A print sheet has two side-by-side columns.  Keep the chunk size explicit so
# the browser cannot paginate the two long columns independently: the right
# column continues into the left column, then the next sheet starts cleanly.
PRINT_ROWS_PER_COLUMN = 28

_AR_DIGITS = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')


def to_ar_digits(value) -> str:
    return str(value).translate(_AR_DIGITS)


def pack_page_range(juz_from: int, juz_to: int, *, min_page: int = 2, max_page: int = 522) -> tuple[int, int]:
    """Inclusive mushaf page range for a juz span."""
    if not (1 <= juz_from <= juz_to <= 30):
        raise ValueError('invalid juz range')
    start = JUZ_START_PAGE[juz_from - 1]
    if juz_to >= 30:
        end = max_page
    else:
        end = JUZ_START_PAGE[juz_to] - 1
    return max(min_page, start), min(max_page, end)


def _build_print_pack(pack_id: int) -> dict:
    """Build a printable checklist pack (page-blocks of marked words only)."""
    meta = PRINT_PACKS.get(pack_id)
    if not meta:
        raise ValueError('invalid pack')
    edition = 'الشمرلي'
    edition_meta = _REVIEW_BY_ID[edition]
    page_from, page_to = pack_page_range(
        meta['juz_from'],
        meta['juz_to'],
        min_page=edition_meta['min_page'],
        max_page=edition_meta['max_page'],
    )

    pages = []
    rows = []
    mark_total = 0
    for page_number in range(page_from, page_to + 1):
        checklist = _build_shamarly_checklist(page_number)
        items = checklist.get('items') or []
        if not items:
            continue
        mark_total += len(items)
        page_label = to_ar_digits(page_number)
        page_marks = []
        for idx, item in enumerate(items):
            row = {
                **item,
                'page_number': page_number,
                'page_label': page_label,
                'line_label': to_ar_digits(item.get('line') or ''),
                'ayah_ref': f"{to_ar_digits(item['surah'])}:{to_ar_digits(item['ayah'])}",
                'mark_write': waqf_write_form(item.get('mark') or ''),
                'is_page_start': idx == 0,
            }
            page_marks.append(row)
            rows.append(row)
        pages.append({
            'page_number': page_number,
            'page_label': page_label,
            'item_count': len(items),
            'marks': page_marks,
        })

    mid = (len(rows) + 1) // 2
    sheets = []
    sheet_size = PRINT_ROWS_PER_COLUMN * 2
    for start in range(0, len(rows), sheet_size):
        right_rows = rows[start:start + PRINT_ROWS_PER_COLUMN]
        left_start = start + PRINT_ROWS_PER_COLUMN
        left_rows = rows[left_start:left_start + PRINT_ROWS_PER_COLUMN]
        sheets.append({
            'number': len(sheets) + 1,
            # The template is RTL, so the first column is rendered on the
            # right and the second is rendered on the left.
            'columns': [right_rows, left_rows],
        })

    return {
        'pack_id': pack_id,
        'label': meta['label'],
        'juz_from': meta['juz_from'],
        'juz_to': meta['juz_to'],
        'edition': edition,
        'page_from': page_from,
        'page_to': page_to,
        'page_from_label': to_ar_digits(page_from),
        'page_to_label': to_ar_digits(page_to),
        'page_count': len(pages),
        'mark_total': mark_total,
        'pages': pages,
        'rows': rows,
        'columns': [rows[:mid], rows[mid:]],
        'print_sheets': sheets,
        'symbols': [
            {
                'code': code,
                'glyph': glyph,
                'name': name,
                'write': waqf_write_form(code),
            }
            for code, glyph, name in _SYMBOL_META
        ],
    }


def waqf_glyph(symbol: str) -> str:
    raw = (symbol or '').strip()
    if not raw or raw == 'ركوع':
        return raw
    parts = []
    for token in raw.replace('،', ',').split(','):
        token = token.replace(' ', '').strip()
        if token:
            parts.append(_WAQF_GLYPH_MAP.get(token, token))
    return ''.join(parts)


def waqf_write_form(symbol: str) -> str:
    """Human-written mark label for print packs (صلى / قلى / ج …)."""
    raw = (symbol or '').strip()
    if not raw or raw == 'ركوع':
        return raw
    parts = []
    for token in raw.replace('،', ',').split(','):
        token = token.replace(' ', '').strip()
        if not token:
            continue
        parts.append(_MARK_WRITE_FORM.get(token, token))
    return '،'.join(parts)


_QURAN_DIGITS = frozenset('0123456789٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹')


def _azhar_quran_words(surah: int, ayah: int) -> list[str]:
    """Return clean Quran words for one ayah, excluding its printed number."""
    entry = qpc_hafs_data_normalized.get(f'{surah}:{ayah}') or {}
    text = entry.get('clean_text') or entry.get('text') or ''
    words = str(text).replace('\u00a0', ' ').split()
    if words and words[-1] and all(char in _QURAN_DIGITS for char in words[-1]):
        words.pop()
    return words


def _build_azhar_surah_table(surah_number: int) -> dict:
    """Build a review table containing every ayah and its current Azhar marks."""
    surah_meta = next(
        (item for item in surahs_data if int(item.get('number', 0)) == surah_number),
        {},
    )
    ayah_numbers = sorted(
        int(key.split(':', 1)[1])
        for key in qpc_hafs_data_normalized
        if key.startswith(f'{surah_number}:')
    )
    marks_by_ayah: dict[int, list[dict]] = {}

    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT "الآية" AS ayah, "الكلمة" AS source_word, '
            'token_index, word_index, "الأزهر" AS symbol '
            'FROM waqf '
            'WHERE "السورة" = ? AND "الأزهر" IS NOT NULL '
            'AND TRIM("الأزهر") != "" '
            'ORDER BY "الآية", COALESCE(word_index, token_index), rowid',
            (surah_number,),
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        ayah = int(row['ayah'])
        try:
            word_index = int(row['word_index'] or row['token_index'])
        except (TypeError, ValueError):
            continue
        words = _azhar_quran_words(surah_number, ayah)
        if not (1 <= word_index <= len(words)):
            continue
        symbol = (row['symbol'] or '').strip()
        if not symbol:
            continue
        mark = {
            'word_index': word_index,
            'word': words[word_index - 1],
            'source_word': row['source_word'] or '',
            'mark': symbol,
            'glyph': waqf_glyph(symbol),
            'write': waqf_write_form(symbol),
            'context': ' '.join(words[max(0, word_index - 2):word_index + 1]),
        }
        marks_by_ayah.setdefault(ayah, []).append(mark)

    table_rows = []
    for ayah in ayah_numbers:
        words = _azhar_quran_words(surah_number, ayah)
        marks = marks_by_ayah.get(ayah, [])
        mark_by_index = {mark['word_index']: mark for mark in marks}
        table_rows.append({
            'ayah': ayah,
            'text': ' '.join(words),
            'words': [
                {
                    'word_index': index,
                    'text': word,
                    'mark': mark_by_index.get(index, {}).get('mark', ''),
                    'glyph': mark_by_index.get(index, {}).get('glyph', ''),
                    'write': mark_by_index.get(index, {}).get('write', ''),
                }
                for index, word in enumerate(words, 1)
            ],
            'marks': marks,
            'mark_count': len(marks),
        })

    mark_count = sum(row['mark_count'] for row in table_rows)
    return {
        'edition': 'الأزهر',
        'surah': surah_number,
        'surah_name': surah_meta.get('name', ''),
        'ayah_count': len(table_rows),
        'mark_count': mark_count,
        'ayahs_with_marks': sum(1 for row in table_rows if row['mark_count']),
        'rows': table_rows,
    }


def _script_ayah_words(surah: int, ayah: int) -> list[dict]:
    """Ordered words for an ayah in quran_script.db (Shemrly word space)."""
    from core.config import QURAN_SCRIPT_DATABASE
    conn = _sqlite_connect(QURAN_SCRIPT_DATABASE)
    try:
        rows = conn.execute(
            'SELECT word_index, text FROM words '
            'WHERE surah = ? AND ayah = ? ORDER BY word_index ASC',
            (surah, ayah),
        ).fetchall()
        return [{'word_id': int(r[0]), 'text': r[1] or ''} for r in rows]
    finally:
        conn.close()


def _local_edition_marks_map(edition: str, ayah_keys: list[tuple[int, int]]) -> dict[tuple[int, int, int], str]:
    """Map (surah, ayah, script_word_id) → letter code from local mushaf_waqf.db."""
    if not ayah_keys or edition not in _REVIEW_BY_ID:
        return {}
    quoted = f'"{edition}"'
    out: dict[tuple[int, int, int], str] = {}
    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for surah, ayah in ayah_keys:
            cur.execute(
                f'SELECT "الكلمة" AS word, token_index, word_index, {quoted} AS symbol '
                'FROM waqf WHERE "السورة" = ? AND "الآية" = ? '
                f'AND {quoted} IS NOT NULL AND {quoted} != "" ORDER BY rowid ASC',
                (surah, ayah),
            )
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                continue
            words = _script_ayah_words(surah, ayah)
            if not words:
                continue
            search_start = 0
            for row in rows:
                matched = _find_mushaf_row_match_index(words, {
                    'clean_token': row.get('word') or '',
                    'word_index': row.get('word_index'),
                    'token_index': None,
                }, search_start)
                if matched is None:
                    ti = row.get('token_index')
                    try:
                        # waqf token_index is 1-based within the ayah word list
                        ti = int(ti) - 1 if ti is not None else None
                    except (TypeError, ValueError):
                        ti = None
                    if ti is None or not (0 <= ti < len(words)):
                        continue
                    matched = ti
                search_start = matched + 1
                symbol = (row.get('symbol') or '').strip()
                if symbol:
                    out[(surah, ayah, int(words[matched]['word_id']))] = symbol
    finally:
        conn.close()
    return out


def _uthmani_by_word_ids(word_ids: list[int]) -> dict[int, str]:
    if not word_ids:
        return {}
    from core.config import QURAN_SCRIPT_DATABASE
    conn = _sqlite_connect(QURAN_SCRIPT_DATABASE)
    try:
        qmarks = ','.join('?' * len(word_ids))
        rows = conn.execute(
            f'SELECT word_index, text FROM words WHERE word_index IN ({qmarks})',
            word_ids,
        ).fetchall()
        return {int(r[0]): (r[1] or '') for r in rows}
    finally:
        conn.close()


def _build_shamarly_checklist(page_number: int) -> dict:
    edition = 'الشمرلي'
    meta = _REVIEW_BY_ID[edition]
    payload = _build_shamarly_page_payload(page_number, mushaf_version=[])
    if not payload:
        return {
            'edition': edition,
            'page_number': page_number,
            'item_count': 0,
            'items': [],
            'error': 'page not found',
        }

    page_words = []
    ayah_keys: set[tuple[int, int]] = set()
    word_ids = []
    for line in payload.get('lines') or []:
        line_no = line.get('line_number')
        word_on_line = 0
        for word in line.get('words') or []:
            if word.get('surah') is None or word.get('ayah') is None:
                continue
            surah = int(word['surah'])
            ayah = int(word['ayah'])
            word_id = int(word['word_index'])
            word_on_line += 1
            ayah_keys.add((surah, ayah))
            word_ids.append(word_id)
            page_words.append((line_no, word_on_line, word, surah, ayah, word_id))

    marks = _local_edition_marks_map(edition, sorted(ayah_keys))
    uthmani = _uthmani_by_word_ids(word_ids)
    use_page_font = payload.get('glyph_mapping_mode') == 'shemrly-page-local'
    font_name = payload.get('font_name') or ''

    items = []
    for line_no, word_on_line, word, surah, ayah, word_id in page_words:
        mark_code = marks.get((surah, ayah, word_id), '')
        if not mark_code:
            continue
        text_uthmani = uthmani.get(word_id) or ''
        glyph_text = (word.get('text') or '') if use_page_font else ''
        items.append({
            'word_id': word_id,
            'surah': surah,
            'ayah': ayah,
            'text': text_uthmani or glyph_text,
            'text_glyph': glyph_text if use_page_font else '',
            'mark': mark_code,
            'mark_glyph': waqf_glyph(mark_code),
            'line': line_no,
            'word_on_line': word_on_line,
        })

    return {
        'edition': edition,
        'page_number': page_number,
        'min_page': meta['min_page'],
        'max_page': meta['max_page'],
        'anchor_surah': payload.get('anchor_surah_number'),
        'anchor_ayah': payload.get('anchor_ayah_number'),
        'font_name': font_name,
        'use_page_font': use_page_font,
        'item_count': len(items),
        'items': items,
        'symbols': [
            {'code': code, 'glyph': glyph, 'name': name}
            for code, glyph, name in _SYMBOL_META
        ],
    }


@editor_bp.route('/waqf-mark-review')
def waqf_mark_review_page():
    """Phone-first checklist — currently الشمرلي only."""
    return render_template(
        'waqf_mark_review.html',
        enable_vercel_analytics=_IS_SERVERLESS,
        editions=REVIEW_EDITIONS,
        symbols=[
            {'code': code, 'glyph': glyph, 'name': name}
            for code, glyph, name in _SYMBOL_META
        ],
        default_edition='الشمرلي',
        min_page=2,
        max_page=522,
        print_packs=[
            {
                'id': pack_id,
                'label': meta['label'],
                'juz_from': meta['juz_from'],
                'juz_to': meta['juz_to'],
                'href': f'/waqf-mark-review/print?pack={pack_id}',
            }
            for pack_id, meta in PRINT_PACKS.items()
        ],
    )


@editor_bp.route('/azhar-waqf-review')
def azhar_waqf_review_page():
    """Read-only, surah-by-surah checklist for the printed Azhar mushaf."""
    return render_template(
        'azhar_waqf_review.html',
        enable_vercel_analytics=_IS_SERVERLESS,
        surahs=surahs_data,
    )


@editor_bp.route('/api/azhar-waqf-review/surah/<int:surah_number>', methods=['GET'])
def azhar_waqf_review_surah(surah_number):
    """Return every ayah and the currently stored Azhar marks for one surah."""
    if not (1 <= surah_number <= 114):
        return jsonify({'error': 'invalid surah'}), 400
    try:
        return jsonify(_build_azhar_surah_table(surah_number))
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل مراجعة سورة الأزهر') from exc


@editor_bp.route('/waqf-mark-review/print')
def waqf_mark_review_print_page():
    """Printable 10-juz review pack (pen checklist against physical mushaf)."""
    try:
        pack_id = int(request.args.get('pack') or '1')
    except (TypeError, ValueError):
        pack_id = 0
    if pack_id not in PRINT_PACKS:
        return (
            render_template(
                'waqf_mark_review_print.html',
                error='حزمة غير صالحة. استخدم pack=1 أو 2 أو 3.',
                pack=None,
                enable_vercel_analytics=_IS_SERVERLESS,
            ),
            400,
        )
    try:
        pack = _build_print_pack(pack_id)
    except Exception as exc:
        logger.exception('waqf-mark-review print pack %s failed', pack_id)
        return (
            render_template(
                'waqf_mark_review_print.html',
                error='تعذّر إعداد حزمة الطباعة. راجع سجل الخادم للتفاصيل.',
                pack=None,
                enable_vercel_analytics=_IS_SERVERLESS,
            ),
            500,
        )
    return render_template(
        'waqf_mark_review_print.html',
        pack=pack,
        error=None,
        enable_vercel_analytics=_IS_SERVERLESS,
    )


@editor_bp.route('/api/waqf-mark-review/page/<int:page_number>', methods=['GET'])
def waqf_mark_review_page_data(page_number):
    """Checklist rows for one mushaf page (readable without login for the demo)."""
    edition = (request.args.get('edition') or 'الشمرلي').strip()
    meta = _REVIEW_BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'invalid edition'}), 400
    if not (meta['min_page'] <= page_number <= meta['max_page']):
        return jsonify({
            'error': 'invalid page',
            'min_page': meta['min_page'],
            'max_page': meta['max_page'],
        }), 400
    try:
        if meta['builder'] == 'shamarly':
            return jsonify(_build_shamarly_checklist(page_number))
        return jsonify({'error': 'unsupported builder'}), 400
    except Exception as exc:
        raise PersistenceError('تعذّر تحميل صفحة مراجعة علامات الوقف') from exc


_DECISIONS = frozenset({'ok', 'wrong', 'extra'})


def _ensure_local_review_tables(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS mushaf_editor_progress (
            page_number INTEGER NOT NULL,
            edition TEXT NOT NULL,
            reviewed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (page_number, edition)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS waqf_mark_review_decisions (
            edition TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            word_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            our_mark TEXT,
            correct_mark TEXT,
            surah INTEGER,
            ayah INTEGER,
            word_text TEXT,
            updated_at TEXT,
            PRIMARY KEY (edition, page_number, word_id)
        )"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS waqf_mark_review_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edition TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            note TEXT NOT NULL,
            updated_at TEXT
        )"""
    )
    conn.commit()


def _decisions_payload(edition: str) -> dict:
    """Build frontend-shaped {page: {word_id: decision}, _missing: {page: [notes]}}."""
    out: dict = {}
    missing: dict = {}
    if sb.is_configured():
        try:
            for row in sb.list_mark_review_decisions(edition):
                page = str(int(row['page_number']))
                out.setdefault(page, {})[str(int(row['word_id']))] = {
                    'decision': row['decision'],
                    'our_mark': row.get('our_mark') or '',
                    'correct_mark': row.get('correct_mark') or '',
                    'word_id': int(row['word_id']),
                    'surah': row.get('surah'),
                    'ayah': row.get('ayah'),
                    'text': row.get('word_text') or '',
                }
            for row in sb.list_mark_review_notes(edition):
                page = str(int(row['page_number']))
                missing.setdefault(page, []).append({
                    'id': row.get('id'),
                    'text': row.get('note') or '',
                    'at': row.get('updated_at') or '',
                })
        except sb.SupabaseEditorError as exc:
            logger.error('cloud mark-review load failed: %s', exc)
            raise
    else:
        conn = _sqlite_connect(MARK_REVIEW_STORE_DATABASE)
        try:
            _ensure_local_review_tables(conn)
            cur = conn.cursor()
            cur.execute(
                'SELECT page_number, word_id, decision, our_mark, correct_mark, '
                'surah, ayah, word_text FROM waqf_mark_review_decisions '
                'WHERE edition = ? ORDER BY page_number, word_id',
                (edition,),
            )
            for page_number, word_id, decision, our_mark, correct_mark, surah, ayah, word_text in cur.fetchall():
                page = str(int(page_number))
                out.setdefault(page, {})[str(int(word_id))] = {
                    'decision': decision,
                    'our_mark': our_mark or '',
                    'correct_mark': correct_mark or '',
                    'word_id': int(word_id),
                    'surah': surah,
                    'ayah': ayah,
                    'text': word_text or '',
                }
            cur.execute(
                'SELECT id, page_number, note, updated_at FROM waqf_mark_review_notes '
                'WHERE edition = ? ORDER BY page_number, id',
                (edition,),
            )
            for note_id, page_number, note, updated_at in cur.fetchall():
                page = str(int(page_number))
                missing.setdefault(page, []).append({
                    'id': note_id,
                    'text': note or '',
                    'at': updated_at or '',
                })
        finally:
            conn.close()
    if missing:
        out['_missing'] = missing
    return out


def _save_decision_local(edition, page_number, word_id, decision, our_mark,
                         correct_mark, surah, ayah, word_text) -> None:
    conn = _sqlite_connect(MARK_REVIEW_STORE_DATABASE)
    try:
        _ensure_local_review_tables(conn)
        conn.execute(
            'INSERT INTO waqf_mark_review_decisions '
            '(edition, page_number, word_id, decision, our_mark, correct_mark, '
            'surah, ayah, word_text, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime("now")) '
            'ON CONFLICT(edition, page_number, word_id) DO UPDATE SET '
            'decision=excluded.decision, our_mark=excluded.our_mark, '
            'correct_mark=excluded.correct_mark, surah=excluded.surah, '
            'ayah=excluded.ayah, word_text=excluded.word_text, '
            'updated_at=excluded.updated_at',
            (edition, page_number, word_id, decision, our_mark or '',
             correct_mark if correct_mark is not None else '',
             surah, ayah, word_text or ''),
        )
        conn.commit()
    finally:
        conn.close()


def _delete_decision_local(edition, page_number, word_id) -> None:
    conn = _sqlite_connect(MARK_REVIEW_STORE_DATABASE)
    try:
        _ensure_local_review_tables(conn)
        conn.execute(
            'DELETE FROM waqf_mark_review_decisions '
            'WHERE edition=? AND page_number=? AND word_id=?',
            (edition, page_number, word_id),
        )
        conn.commit()
    finally:
        conn.close()


def _add_note_local(edition, page_number, note) -> dict:
    conn = _sqlite_connect(MARK_REVIEW_STORE_DATABASE)
    try:
        _ensure_local_review_tables(conn)
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO waqf_mark_review_notes (edition, page_number, note, updated_at) '
            'VALUES (?, ?, ?, datetime("now"))',
            (edition, page_number, note),
        )
        conn.commit()
        return {'id': cur.lastrowid, 'text': note, 'at': ''}
    finally:
        conn.close()


@editor_bp.route('/api/waqf-mark-review/decisions', methods=['GET', 'POST', 'DELETE'])
@require_editor
def waqf_mark_review_decisions():
    """Load / upsert / clear per-word review decisions (server-backed)."""
    user = current_editor()
    actor = user['id'] if user else None

    if request.method == 'GET':
        edition = (request.args.get('edition') or '').strip()
        meta = _REVIEW_BY_ID.get(edition)
        if not meta:
            return jsonify({'error': 'invalid edition'}), 400
        try:
            return jsonify({
                'edition': edition,
                'decisions': _decisions_payload(edition),
                'storage': 'cloud' if sb.is_configured() else 'local',
            })
        except sb.SupabaseEditorError:
            return jsonify({'error': 'cloud unavailable'}), 503

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    edition = (body.get('edition') or '').strip()
    meta = _REVIEW_BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'invalid edition'}), 400
    try:
        page_number = int(body.get('page_number'))
        word_id = int(body.get('word_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number/word_id'}), 400
    if not (meta['min_page'] <= page_number <= meta['max_page']):
        return jsonify({'error': 'invalid page_number'}), 400

    if request.method == 'DELETE':
        try:
            if sb.is_configured():
                sb.delete_mark_review_decision(
                    edition=edition, page_number=page_number, word_id=word_id,
                )
            else:
                _delete_decision_local(edition, page_number, word_id)
        except sb.SupabaseEditorError as exc:
            logger.error('delete decision failed: %s', exc)
            return jsonify({'error': 'cloud write failed'}), 503
        return jsonify({'ok': True})

    decision = (body.get('decision') or '').strip()
    if decision not in _DECISIONS:
        return jsonify({'error': 'invalid decision'}), 400
    our_mark = body.get('our_mark')
    correct_mark = body.get('correct_mark')
    surah = body.get('surah')
    ayah = body.get('ayah')
    word_text = body.get('text') or body.get('word_text') or ''
    try:
        surah_i = int(surah) if surah is not None else None
        ayah_i = int(ayah) if ayah is not None else None
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid surah/ayah'}), 400

    try:
        if sb.is_configured():
            sb.upsert_mark_review_decision(
                edition=edition, page_number=page_number, word_id=word_id,
                decision=decision, our_mark=our_mark, correct_mark=correct_mark,
                surah=surah_i, ayah=ayah_i, word_text=word_text, updated_by=actor,
            )
            sb.append_audit(
                actor_id=actor,
                actor_name=(user or {}).get('name') if user else None,
                action='mark_review_decision',
                edition=edition,
                page_number=page_number,
                word_id=word_id,
                surah=surah_i,
                ayah=ayah_i,
                old_symbol=our_mark,
                new_symbol=correct_mark if decision == 'wrong' else decision,
                meta={'decision': decision, 'word_text': word_text},
            )
        else:
            _save_decision_local(
                edition, page_number, word_id, decision, our_mark,
                correct_mark, surah_i, ayah_i, word_text,
            )
    except sb.SupabaseEditorError as exc:
        logger.error('save decision failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'storage': 'cloud' if sb.is_configured() else 'local'})


@editor_bp.route('/api/waqf-mark-review/notes', methods=['POST'])
@require_editor
def waqf_mark_review_notes():
    """Append a «ناقص» note for a page."""
    user = current_editor()
    actor = user['id'] if user else None
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    edition = (body.get('edition') or '').strip()
    meta = _REVIEW_BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'invalid edition'}), 400
    try:
        page_number = int(body.get('page_number'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number'}), 400
    note = (body.get('note') or body.get('text') or '').strip()
    if not note:
        return jsonify({'error': 'empty note'}), 400
    if not (meta['min_page'] <= page_number <= meta['max_page']):
        return jsonify({'error': 'invalid page_number'}), 400
    try:
        if sb.is_configured():
            row = sb.add_mark_review_note(
                edition=edition, page_number=page_number, note=note, updated_by=actor,
            )
            saved = {
                'id': row.get('id'),
                'text': row.get('note') or note,
                'at': row.get('updated_at') or '',
            }
            sb.append_audit(
                actor_id=actor,
                actor_name=(user or {}).get('name') if user else None,
                action='mark_review_note',
                edition=edition,
                page_number=page_number,
                meta={'note': note[:240]},
            )
        else:
            saved = _add_note_local(edition, page_number, note)
    except sb.SupabaseEditorError as exc:
        logger.error('save note failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'note': saved, 'storage': 'cloud' if sb.is_configured() else 'local'})


@editor_bp.route('/api/waqf-mark-review/progress', methods=['GET', 'POST'])
@require_editor
def waqf_mark_review_progress():
    """Page-reviewed flags — cloud editor_progress when configured, else SQLite."""
    user = current_editor()
    if request.method == 'GET':
        edition = (request.args.get('edition') or '').strip()
        body = None
    else:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'JSON object required'}), 400
        edition = (body.get('edition') or '').strip()

    meta = _REVIEW_BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'invalid edition'}), 400

    if sb.is_configured():
        try:
            if request.method == 'GET':
                pages = sb.list_reviewed_pages(edition)
                return jsonify({
                    'edition': edition,
                    'reviewed_pages': pages,
                    'min_page': meta['min_page'],
                    'max_page': meta['max_page'],
                    'storage': 'cloud',
                })
            try:
                page_number = int(body.get('page_number'))
            except (TypeError, ValueError):
                return jsonify({'error': 'invalid page_number'}), 400
            if not (meta['min_page'] <= page_number <= meta['max_page']):
                return jsonify({'error': 'invalid page_number'}), 400
            reviewed = bool(body.get('reviewed'))
            sb.upsert_progress(
                edition=edition, page_number=page_number, reviewed=reviewed,
                updated_by=user['id'] if user else None,
            )
            sb.append_audit(
                actor_id=user['id'] if user else None,
                actor_name=user.get('name') if user else None,
                action='mark_review_page',
                edition=edition,
                page_number=page_number,
                meta={'reviewed': reviewed},
            )
            return jsonify({
                'ok': True, 'page_number': page_number,
                'edition': edition, 'reviewed': reviewed, 'storage': 'cloud',
            })
        except sb.SupabaseEditorError as exc:
            logger.error('cloud progress failed: %s', exc)
            return jsonify({'error': 'cloud progress failed'}), 503

    conn = _sqlite_connect(MARK_REVIEW_STORE_DATABASE)
    try:
        _ensure_local_review_tables(conn)
        cur = conn.cursor()
        if request.method == 'GET':
            cur.execute(
                'SELECT page_number FROM mushaf_editor_progress '
                'WHERE edition = ? AND reviewed = 1',
                (edition,),
            )
            pages = sorted(row[0] for row in cur.fetchall())
            return jsonify({
                'edition': edition,
                'reviewed_pages': pages,
                'min_page': meta['min_page'],
                'max_page': meta['max_page'],
                'storage': 'local',
            })

        try:
            page_number = int(body.get('page_number'))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid page_number'}), 400
        if not (meta['min_page'] <= page_number <= meta['max_page']):
            return jsonify({'error': 'invalid page_number'}), 400
        reviewed = 1 if body.get('reviewed') else 0
        cur.execute(
            'INSERT INTO mushaf_editor_progress (page_number, edition, reviewed, updated_at) '
            'VALUES (?, ?, ?, datetime("now")) '
            'ON CONFLICT(page_number, edition) DO UPDATE SET '
            'reviewed = excluded.reviewed, updated_at = excluded.updated_at',
            (page_number, edition, reviewed),
        )
        conn.commit()
        return jsonify({
            'ok': True, 'page_number': page_number,
            'edition': edition, 'reviewed': bool(reviewed), 'storage': 'local',
        })
    finally:
        conn.close()
