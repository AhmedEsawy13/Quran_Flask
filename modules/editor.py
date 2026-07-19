"""محرّر المصحف — the click-to-edit waqf tool (the ONLY writer).

Routes for the editor page, the spread payloads (Qatar layout right page /
QPC-v1 left page), and reading/writing a single word's waqf symbol in
mushaf_waqf.db. Gated behind ENABLE_EDITOR at registration time (app.py).
"""
import logging
import sqlite3

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.config import EDITOR_EDITIONS, MUSHAF_WAQF_DATABASE
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core.db import connect as _sqlite_connect
from core.mushaf_waqf import _mushaf_waqf_cache
from modules.breathing import _verse_waqf_cache
from modules.layouts import (
    _build_qatar_page_payload,
    _build_qpc_v1_page_payload,
    _get_dk_layout_word_map,
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)

logger = logging.getLogger(__name__)

_MAX_MUSHAF_PAGE = 604
_MAX_MUSHAF_SPREAD = 302
_EDITOR_SYMBOLS = {'', 'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع', 'ركوع'}
# Full reference mushafs shown as peer hints in the editor (not writable here).
_EDITOR_PEER_VERSIONS = (
    'المدينة الجديد',
    'المدينة القديم',
    'الأزهر',
    'الشمرلي',
)


def _ayah_word_list_for_editor(surah_number, ayah_number):
    """Ordered list of {'word_id', 'text'} for every layout word in an ayah,
    using the same authoritative Digital Khatt / QPC-v1 word numbering as the
    page payloads (so word_id lines up with first_word_id/last_word_id)."""
    wmap = _get_dk_layout_word_map()
    first_id = wmap['first_id'].get((surah_number, ayah_number))
    last_id = wmap['last_id'].get((surah_number, ayah_number))
    if first_id is None or last_id is None:
        return []
    id2tok = wmap['id2tok']
    words = []
    for word_id in range(first_id, last_id + 1):
        tok = id2tok.get(word_id)
        if tok:
            words.append({'word_id': word_id, 'text': tok['text']})
    return words


def _get_or_set_word_waqf(global_word_id, edition, symbol):
    """Read or write the mushaf_waqf.db waqf symbol for one word/edition.

    `symbol`: None reads the current value without writing; '' clears the
    mark; any other string sets it. Returns the resulting symbol (possibly
    None), or None if the word/edition cannot be resolved.

    Rows in `waqf` are sparse (only words with a mark in *some* edition have a
    row). If the targeted word has no row yet and `symbol` is non-empty, a new
    row is inserted with token_index/word_index computed from the layout word
    map — the same scheme `migrate_mushaf_waqf_token_index.py` used, so the
    existing match-by-word_index logic keeps working for renders.
    """
    if edition not in EDITOR_EDITIONS:
        return None

    wmap = _get_dk_layout_word_map()
    tok = wmap['id2tok'].get(global_word_id)
    if not tok:
        return None
    surah_number, ayah_number = tok['surah'], tok['ayah']
    first_id = wmap['first_id'].get((surah_number, ayah_number))
    if first_id is None:
        return None
    target_index = global_word_id - first_id

    words = _ayah_word_list_for_editor(surah_number, ayah_number)
    if not (0 <= target_index < len(words)):
        return None

    quoted_col = f'"{edition}"'
    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f'SELECT rowid, "الكلمة" AS word, token_index, word_index, {quoted_col} AS current '
            'FROM waqf WHERE "السورة" = ? AND "الآية" = ? ORDER BY rowid ASC',
            (surah_number, ayah_number)
        )
        rows = [dict(r) for r in cur.fetchall()]

        matched_row = None
        search_start = 0
        for row in rows:
            idx = _find_mushaf_row_match_index(words, row, search_start)
            if idx == target_index:
                matched_row = row
                break
            if idx is not None:
                search_start = idx + 1

        if symbol is None:
            return matched_row['current'] if matched_row else None

        clean_symbol = (symbol or '').strip() or None

        if matched_row is not None:
            cur.execute(f'UPDATE waqf SET {quoted_col} = ? WHERE rowid = ?', (clean_symbol, matched_row['rowid']))
            conn.commit()
            _mushaf_waqf_cache.pop((surah_number, ayah_number, edition), None)
            _verse_waqf_cache.pop((surah_number, ayah_number), None)
            return clean_symbol

        if clean_symbol is None:
            return None  # nothing to clear — no row covers this word in any edition

        word_index_hint = 1 + sum(
            1 for w in words[:target_index] if _normalize_mushaf_word_token(w['text'])
        )
        used_token_indexes = {r['token_index'] for r in rows if r.get('token_index') is not None}
        token_index = target_index + 1
        while token_index in used_token_indexes:
            token_index += 1

        cur.execute(
            f'INSERT INTO waqf ("السورة","الآية","الكلمة",token_index,word_index,{quoted_col}) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (surah_number, ayah_number, words[target_index]['text'], token_index, word_index_hint, clean_symbol)
        )
        conn.commit()
        _mushaf_waqf_cache.pop((surah_number, ayah_number, edition), None)
        _verse_waqf_cache.pop((surah_number, ayah_number), None)
        return clean_symbol
    finally:
        conn.close()




@editor_bp.route('/mushaf-editor')
def mushaf_editor_page():
    return render_template('mushaf_editor.html', enable_vercel_analytics=_IS_SERVERLESS)


@editor_bp.route('/api/mushaf-editor/spread/<int:spread_number>', methods=['GET'])
def get_mushaf_editor_spread(spread_number):
    """Two facing pages of the Madinah v1 layout, carrying the selected
    edition's marks, the المدينة baseline (for diffing), and peer mushafs
    (الأزهر / الشمرلي / المدينتان) for forget-me-not hints."""
    edition = (request.args.get('edition') or '').strip()
    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    if not (1 <= spread_number <= _MAX_MUSHAF_SPREAD):
        return jsonify({'error': f'spread_number must be between 1 and {_MAX_MUSHAF_SPREAD}'}), 400
    try:
        right_page = spread_number * 2 - 1
        left_page = right_page + 1
        versions = [edition]
        for peer in _EDITOR_PEER_VERSIONS:
            if peer not in versions:
                versions.append(peer)
        build_page = _build_qatar_page_payload if edition == 'قطر' else _build_qpc_v1_page_payload
        right = build_page(right_page, mushaf_version=versions)
        left = build_page(left_page, mushaf_version=versions) if left_page <= _MAX_MUSHAF_PAGE else None
        return jsonify({
            'spread_number': spread_number,
            'edition': edition,
            'right': right,
            'left': left,
            'max_spread': _MAX_MUSHAF_SPREAD,
            'peer_versions': list(_EDITOR_PEER_VERSIONS),
        })
    except Exception as e:
        logger.error(f"Error fetching mushaf-editor spread {spread_number}: {e}")
        return jsonify({'error': str(e)}), 500


@editor_bp.route('/api/mushaf-editor/waqf', methods=['POST'])
def set_mushaf_editor_waqf():
    """Set or clear the waqf mark for one word in one edition.

    Body: {"word_id": <global layout word id>, "edition": "قطر"|"الكويت",
           "symbol": "<one of م لا ق ص ج س ع>" | "" (clear)}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        word_id = int(data.get('word_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid word_id'}), 400
    edition = data.get('edition') or ''
    if not isinstance(edition, str):
        return jsonify({'error': 'invalid edition'}), 400
    edition = edition.strip()
    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    symbol = data.get('symbol')
    symbol = '' if symbol is None else str(symbol).strip()
    if symbol not in _EDITOR_SYMBOLS:
        return jsonify({'error': 'invalid symbol'}), 400

    result = _get_or_set_word_waqf(word_id, edition, symbol)
    if result is None and symbol:
        return jsonify({'error': 'word not found'}), 404
    return jsonify({'word_id': word_id, 'edition': edition, 'symbol': result or ''})


@editor_bp.route('/api/mushaf-editor/progress', methods=['GET', 'POST'])
def mushaf_editor_progress():
    """Track which spreads of the 604-page layout have been manually reviewed
    for each new edition, so the comparison work can be paused/resumed."""
    if request.method == 'GET':
        edition = (request.args.get('edition') or '').strip()
    else:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'JSON object required'}), 400
        edition = body.get('edition', '')
        if not isinstance(edition, str):
            return jsonify({'error': 'invalid edition'}), 400
        edition = (edition or '').strip()

    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400

    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        if request.method == 'GET':
            cur.execute(
                'SELECT page_number FROM mushaf_editor_progress WHERE edition = ? AND reviewed = 1',
                (edition,)
            )
            pages = sorted(row[0] for row in cur.fetchall())
            return jsonify({'edition': edition, 'reviewed_pages': pages})

        try:
            page_number = int(body.get('page_number'))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid page_number'}), 400
        if not (1 <= page_number <= _MAX_MUSHAF_PAGE):
            return jsonify({'error': f'page_number must be between 1 and {_MAX_MUSHAF_PAGE}'}), 400
        reviewed = 1 if body.get('reviewed') else 0
        cur.execute(
            'INSERT INTO mushaf_editor_progress (page_number, edition, reviewed, updated_at) '
            'VALUES (?, ?, ?, datetime("now")) '
            'ON CONFLICT(page_number, edition) DO UPDATE SET reviewed = excluded.reviewed, updated_at = excluded.updated_at',
            (page_number, edition, reviewed)
        )
        conn.commit()
        return jsonify({'ok': True, 'page_number': page_number, 'edition': edition, 'reviewed': bool(reviewed)})
    except Exception as e:
        logger.error(f"Error in mushaf-editor progress: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
