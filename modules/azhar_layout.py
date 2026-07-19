"""Azhar layout workspace — reshape 15-line pages seeded from الشمرلي.

ENABLE_EDITOR-only writer for data/mushaf-azhar-layout.db. Reads go through
/api/azhar/page* on core_bp (modules/layouts.py).
"""
from __future__ import annotations

import bisect
import json
import logging
import sqlite3

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.config import (
    AZHAR_LAYOUT_DATABASE,
    AZHAR_LAYOUT_MAX_PAGE,
    AZHAR_LAYOUT_MIN_PAGE,
    QURAN_SCRIPT_DATABASE,
    SHAMARLY_LAYOUT_DATABASE,
)
from core.db import connect as _sqlite_connect
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules.layouts import _build_azhar_page_payload

logger = logging.getLogger(__name__)

_UNDO_LIMIT = 40

# سورة الفاتحة — closed page 2. Ayah words must never leave this page.
FATIHA_PAGE = 2
FATIHA_AYAH_FIRST = 8
FATIHA_AYAH_LAST = 38
# First real البقرة word after Shemrly reserved surah/basmala slots.
BAQARAH_FIRST_WORD = 45


def _ensure_undo_table(cur):
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS azhar_layout_undo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            page_number INTEGER,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        '''
    )


def _snapshot_pages(cur):
    cur.execute(
        '''
        SELECT id, first_word_id, last_word_id, line_text
        FROM pages
        ORDER BY id ASC
        '''
    )
    return [
        {
            'id': int(r[0]),
            'first_word_id': r[1],
            'last_word_id': r[2],
            'line_text': r[3] or '',
        }
        for r in cur.fetchall()
    ]


def _push_undo(cur, label, page_number):
    _ensure_undo_table(cur)
    cur.execute(
        'INSERT INTO azhar_layout_undo (label, page_number, snapshot) VALUES (?, ?, ?)',
        (label, page_number, json.dumps(_snapshot_pages(cur), ensure_ascii=False)),
    )
    cur.execute(
        '''
        DELETE FROM azhar_layout_undo
        WHERE id NOT IN (
            SELECT id FROM azhar_layout_undo ORDER BY id DESC LIMIT ?
        )
        ''',
        (_UNDO_LIMIT,),
    )


def _undo_available(cur):
    _ensure_undo_table(cur)
    row = cur.execute('SELECT COUNT(*) FROM azhar_layout_undo').fetchone()
    return int(row[0] or 0)


def _restore_snapshot(cur, snapshot):
    rows = json.loads(snapshot)
    for row in rows:
        cur.execute(
            '''
            UPDATE pages
            SET first_word_id = ?, last_word_id = ?, line_text = ?
            WHERE id = ?
            ''',
            (row.get('first_word_id'), row.get('last_word_id'), row.get('line_text') or '', row['id']),
        )


def _word_texts(word_ids):
    """Map word_index → text for a list of ids (missing ids omitted)."""
    if not word_ids:
        return {}
    conn = _sqlite_connect(QURAN_SCRIPT_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        out = {}
        # Chunk to stay under SQLite variable limits.
        for i in range(0, len(word_ids), 400):
            chunk = word_ids[i:i + 400]
            placeholders = ','.join('?' * len(chunk))
            cur.execute(
                f'SELECT word_index, text FROM words WHERE word_index IN ({placeholders})',
                chunk,
            )
            for row in cur.fetchall():
                out[int(row['word_index'])] = row['text'] or ''
        return out
    finally:
        conn.close()


def _load_all_lines(cur):
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        ORDER BY page_number ASC, line_number ASC
        '''
    )
    return [dict(r) for r in cur.fetchall()]


_SCRIPT_WORD_IDS = None


def _all_script_word_ids():
    """Sorted word_index list from quran_script (cached for cascade speed)."""
    global _SCRIPT_WORD_IDS
    if _SCRIPT_WORD_IDS is not None:
        return _SCRIPT_WORD_IDS
    conn = _sqlite_connect(QURAN_SCRIPT_DATABASE)
    try:
        cur = conn.cursor()
        cur.execute('SELECT word_index FROM words ORDER BY word_index ASC')
        _SCRIPT_WORD_IDS = [int(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()
    return _SCRIPT_WORD_IDS


def _existing_word_ids_between(first, last, universe=None):
    """Real word_index values in [first, last] (skips Shemrly gaps)."""
    if first is None or last is None:
        return []
    first, last = int(first), int(last)
    if last < first:
        return []
    ids = universe if universe is not None else _all_script_word_ids()
    lo = bisect.bisect_left(ids, first)
    hi = bisect.bisect_right(ids, last)
    return ids[lo:hi]


def _expand_ayah_words(line, universe=None):
    """Words on an ayah line — only indices that exist in quran_script.db."""
    return _existing_word_ids_between(
        line.get('first_word_id'), line.get('last_word_id'), universe=universe
    )


def _assign_words_to_line(line, word_ids, text_map):
    if not word_ids:
        line['first_word_id'] = None
        line['last_word_id'] = None
        line['line_text'] = ''
        return
    line['first_word_id'] = int(word_ids[0])
    line['last_word_id'] = int(word_ids[-1])
    line['line_text'] = ' '.join(
        text_map.get(w, '') for w in word_ids if text_map.get(w)
    ).strip()


def _persist_line(cur, line):
    cur.execute(
        '''
        UPDATE pages
        SET first_word_id = ?, last_word_id = ?, line_text = ?
        WHERE id = ?
        ''',
        (line['first_word_id'], line['last_word_id'], line.get('line_text') or '', line['id']),
    )


def _fatiha_ayah_words(universe=None):
    """All script word ids that belong on Fatiha ayah lines (never leave page 2)."""
    return _existing_word_ids_between(FATIHA_AYAH_FIRST, FATIHA_AYAH_LAST, universe=universe)


def _cascade_from(lines, start_idx, head_words, text_map, universe=None, page_scope=None):
    """Rewrite ayah lines from start_idx onward.

    `head_words` must be an exact prefix of the combined word stream from
    start_idx (gap-safe script ids). Later ayah lines keep prior word counts
    when possible; the last slot absorbs the remainder.

    When `page_scope` is the Fatiha page, the stream is the *full* Fatiha ayah
    word range (8–38), not whatever currently sits on the page — so spilled
    words are pulled back and cannot escape onto البقرة.
    """
    ayah_slots = [
        i for i in range(start_idx, len(lines))
        if lines[i]['line_type'] == 'ayah'
        and (page_scope is None or int(lines[i]['page_number']) == int(page_scope))
    ]
    if not ayah_slots or not head_words:
        return False

    head = list(head_words)
    closed = page_scope is not None and _page_is_closed(page_scope)

    if closed:
        # Words on earlier ayah lines of the same page stay put; remainder of
        # the canonical Fatiha range is redistributed from start_idx onward.
        page_ayah = [
            i for i, line in enumerate(lines)
            if line['line_type'] == 'ayah' and int(line['page_number']) == int(page_scope)
        ]
        prefix = []
        for i in page_ayah:
            if i < start_idx:
                prefix.extend(_expand_ayah_words(lines[i], universe=universe))
            else:
                break
        canonical = _fatiha_ayah_words(universe=universe)
        start = prefix + head
        if canonical[:len(start)] != start:
            return False
        stream_from_start = canonical[len(prefix):]
    else:
        stream_from_start = []
        for line_i in ayah_slots:
            stream_from_start.extend(_expand_ayah_words(lines[line_i], universe=universe))

    capacities = []
    for slot_i, line_i in enumerate(ayah_slots):
        words = _expand_ayah_words(lines[line_i], universe=universe)
        capacities.append(max(1, len(head) if slot_i == 0 else len(words) or 1))

    if stream_from_start[:len(head)] != head:
        return False
    rest = stream_from_start[len(head):]

    assignments = [head]
    cursor = 0
    for slot_i in range(1, len(ayah_slots)):
        is_last = slot_i == len(ayah_slots) - 1
        if is_last:
            chunk = rest[cursor:]
        else:
            n = capacities[slot_i]
            chunk = rest[cursor:cursor + n]
            cursor += len(chunk)
        assignments.append(chunk)

    if len(ayah_slots) > 1:
        used = sum(len(a) for a in assignments[1:-1])
        assignments[-1] = rest[used:]

    for slot_i, line_i in enumerate(ayah_slots):
        _assign_words_to_line(lines[line_i], assignments[slot_i], text_map)
    return True


def _page_is_closed(page_number):
    """Fatiha (page 2) is a closed short page — edits stay on that page."""
    return int(page_number) == FATIHA_PAGE


def _purge_fatiha_spill(lines, text_map, universe=None):
    """Remove any Fatiha ayah words (≤38) from pages after الفاتحة."""
    changed = []
    for i, line in enumerate(lines):
        if int(line['page_number']) <= FATIHA_PAGE or line['line_type'] != 'ayah':
            continue
        words = _expand_ayah_words(line, universe=universe)
        kept = [w for w in words if w > FATIHA_AYAH_LAST]
        if kept != words:
            _assign_words_to_line(line, kept, text_map)
            changed.append(i)
    return changed


def _restore_shamarly_page(cur, page_number):
    """Replace one page's rows from الشمرلي (used to repair البقرة after spill)."""
    import os
    if not os.path.exists(SHAMARLY_LAYOUT_DATABASE):
        return False
    src = sqlite3.connect(SHAMARLY_LAYOUT_DATABASE)
    try:
        src.row_factory = sqlite3.Row
        rows = src.execute(
            '''
            SELECT page_number, line_number, line_type, is_centered,
                   first_word_id, last_word_id, surah_number, line_text
            FROM pages WHERE page_number = ?
            ORDER BY line_number ASC
            ''',
            (page_number,),
        ).fetchall()
        if not rows:
            return False
        cur.execute('DELETE FROM pages WHERE page_number = ?', (page_number,))
        cur.executemany(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            [
                (
                    int(r['page_number']),
                    int(r['line_number']),
                    r['line_type'],
                    1 if r['is_centered'] else 0,
                    r['first_word_id'],
                    r['last_word_id'],
                    r['surah_number'],
                    r['line_text'] or '',
                )
                for r in rows
            ],
        )
        return True
    finally:
        src.close()


def _seal_fatiha_page(cur, lines, text_map, universe=None):
    """After a Fatiha edit: keep 8–38 on page 2; repair page 3 if words spilled."""
    spilled = _purge_fatiha_spill(lines, text_map, universe=universe)
    for i in spilled:
        _persist_line(cur, lines[i])

    # If البقرة's first ayah no longer starts at الم, restore that page.
    page3_ayah = next(
        (
            line for line in lines
            if int(line['page_number']) == 3 and line['line_type'] == 'ayah'
        ),
        None,
    )
    need_restore = False
    if page3_ayah is None:
        need_restore = True
    else:
        words = _expand_ayah_words(page3_ayah, universe=universe)
        if not words or words[0] != BAQARAH_FIRST_WORD:
            need_restore = True
    if need_restore or spilled:
        if _restore_shamarly_page(cur, 3):
            # Refresh in-memory page-3 rows so later persists don't stomp the restore.
            fresh = _load_all_lines(cur)
            lines[:] = fresh


def _find_word_line(lines, word_id, universe=None):
    """Return (line_index, words_on_line) for the ayah line holding word_id."""
    for i, line in enumerate(lines):
        if line['line_type'] != 'ayah':
            continue
        words = _expand_ayah_words(line, universe=universe)
        if word_id in words:
            return i, words
    return None, None


@editor_bp.route('/azhar-layout')
def azhar_layout_page():
    return render_template('azhar_layout.html', enable_vercel_analytics=_IS_SERVERLESS)


@editor_bp.route('/api/azhar-layout/page/<int:page_number>', methods=['GET'])
def get_azhar_layout_editor_page(page_number):
    """Editor read of one page (always overlays الأزهر)."""
    if not (AZHAR_LAYOUT_MIN_PAGE <= page_number <= AZHAR_LAYOUT_MAX_PAGE):
        return jsonify({
            'error': f'page_number must be between {AZHAR_LAYOUT_MIN_PAGE} and {AZHAR_LAYOUT_MAX_PAGE}'
        }), 400
    payload = _build_azhar_page_payload(page_number, mushaf_version=['الأزهر'])
    if not payload:
        return jsonify({'error': 'Page not found'}), 404
    return jsonify(payload)


@editor_bp.route('/api/azhar-layout/line-break', methods=['POST'])
def azhar_layout_line_break():
    """Set a line boundary at `word_id`, then cascade.

    Body: {
      page_number, line_number, word_id,
      role: "end" | "start"   # end = line ends after word (default)
                              # start = this word starts its line
                              #         (previous word ends the previous line)
    }

    Line start/end words are the critical anchors when matching the printed mushaf.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        page_number = int(data.get('page_number'))
        line_number = int(data.get('line_number'))
        word_id = int(data.get('word_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number, line_number, or word_id'}), 400
    role = (data.get('role') or 'end').strip().lower()
    if role not in {'end', 'start'}:
        return jsonify({'error': 'role must be end or start'}), 400
    if not (AZHAR_LAYOUT_MIN_PAGE <= page_number <= AZHAR_LAYOUT_MAX_PAGE):
        return jsonify({'error': 'page_number out of range'}), 400

    conn = _sqlite_connect(AZHAR_LAYOUT_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = _load_all_lines(cur)
        universe = _all_script_word_ids()
        target_idx = next(
            (
                i for i, line in enumerate(lines)
                if int(line['page_number']) == page_number
                and int(line['line_number']) == line_number
            ),
            None,
        )
        if target_idx is None:
            return jsonify({'error': 'line not found'}), 404
        target = lines[target_idx]
        if target['line_type'] != 'ayah':
            return jsonify({'error': 'line_break only applies to ayah lines'}), 400
        words = _expand_ayah_words(target, universe=universe)
        if word_id not in words:
            found_idx, words = _find_word_line(lines, word_id, universe=universe)
            if found_idx is None:
                return jsonify({'error': 'word_id not on an ayah line'}), 400
            target_idx = found_idx
            target = lines[target_idx]

        if role == 'end':
            if word_id == words[-1]:
                payload = _build_azhar_page_payload(page_number, mushaf_version=['الأزهر'])
                return jsonify({'ok': True, 'unchanged': True, 'role': role, 'page': payload})
            cut = words.index(word_id) + 1
            head = words[:cut]
            cascade_idx = target_idx
        else:
            # start: this word begins the line → prior words fold into previous line.
            if word_id == words[0]:
                payload = _build_azhar_page_payload(page_number, mushaf_version=['الأزهر'])
                return jsonify({'ok': True, 'unchanged': True, 'role': role, 'page': payload})
            pos = words.index(word_id)
            prev_ayah_idx = None
            for i in range(target_idx - 1, -1, -1):
                if lines[i]['line_type'] == 'ayah' and _expand_ayah_words(lines[i], universe=universe):
                    prev_ayah_idx = i
                    break
            if prev_ayah_idx is None:
                return jsonify({'error': 'لا يوجد سطر سابق لبدء السطر هنا'}), 400
            prev_words = _expand_ayah_words(lines[prev_ayah_idx], universe=universe)
            head = prev_words + words[:pos]
            cascade_idx = prev_ayah_idx

        page_scope = page_number if _page_is_closed(page_number) else None
        needed = set()
        if page_scope is not None:
            needed.update(_fatiha_ayah_words(universe=universe))
        for i in range(cascade_idx, len(lines)):
            if lines[i]['line_type'] != 'ayah':
                continue
            if page_scope is not None and int(lines[i]['page_number']) != int(page_scope):
                break
            needed.update(_expand_ayah_words(lines[i], universe=universe))
        text_map = _word_texts(sorted(needed))
        if not _cascade_from(
            lines, cascade_idx, head, text_map, universe=universe, page_scope=page_scope
        ):
            return jsonify({'error': 'cascade failed'}), 400

        _push_undo(cur, f'line-{role}', page_number)
        for i in range(cascade_idx, len(lines)):
            if lines[i]['line_type'] != 'ayah':
                continue
            if page_scope is not None and int(lines[i]['page_number']) != int(page_scope):
                break
            _persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_fatiha_page(cur, lines, text_map, universe=universe)
        conn.commit()
        payload = _build_azhar_page_payload(page_number, mushaf_version=['الأزهر'])
        return jsonify({
            'ok': True,
            'role': role,
            'page': payload,
            'undo_available': _undo_available(cur),
        })
    except Exception as e:
        logger.error(f'azhar line-break failed: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/azhar-layout/merge-line', methods=['POST'])
def azhar_layout_merge_line():
    """Merge an ayah line with the next ayah line (may be on the next page).

    Body: {page_number, line_number}
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        page_number = int(data.get('page_number'))
        line_number = int(data.get('line_number'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number or line_number'}), 400

    conn = _sqlite_connect(AZHAR_LAYOUT_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = _load_all_lines(cur)
        target_idx = next(
            (
                i for i, line in enumerate(lines)
                if int(line['page_number']) == page_number
                and int(line['line_number']) == line_number
            ),
            None,
        )
        if target_idx is None:
            return jsonify({'error': 'line not found'}), 404
        if lines[target_idx]['line_type'] != 'ayah':
            return jsonify({'error': 'merge only applies to ayah lines'}), 400

        next_idx = None
        for i in range(target_idx + 1, len(lines)):
            if lines[i]['line_type'] == 'ayah':
                next_idx = i
                break
        if next_idx is None:
            return jsonify({'error': 'no following ayah line'}), 400

        # Fatiha is a closed page — do not merge into البقرة.
        if _page_is_closed(page_number) and int(lines[next_idx]['page_number']) != page_number:
            return jsonify({'error': 'لا يمكن الدمج خارج صفحة الفاتحة'}), 400

        a = _expand_ayah_words(lines[target_idx])
        b = _expand_ayah_words(lines[next_idx])
        merged = a + b
        if not merged:
            return jsonify({'error': 'nothing to merge'}), 400

        page_scope = page_number if _page_is_closed(page_number) else None
        universe = _all_script_word_ids()
        needed = set(merged)
        if page_scope is not None:
            needed.update(_fatiha_ayah_words(universe=universe))
        for i in range(target_idx, len(lines)):
            if lines[i]['line_type'] != 'ayah':
                continue
            if page_scope is not None and int(lines[i]['page_number']) != int(page_scope):
                break
            needed.update(_expand_ayah_words(lines[i], universe=universe))
        text_map = _word_texts(sorted(needed))

        # Merge into target; redistribute what follows onto later slots.
        _assign_words_to_line(lines[target_idx], merged, text_map)

        if page_scope is not None:
            # Closed Fatiha: remaining canonical words after `merged` go on later
            # ayah lines of the same page (never onto البقرة).
            canonical = _fatiha_ayah_words(universe=universe)
            if canonical[:len(merged)] != merged:
                return jsonify({'error': 'merge cascade failed'}), 400
            following = canonical[len(merged):]
        else:
            following = []
            for i in range(next_idx + 1, len(lines)):
                if lines[i]['line_type'] == 'ayah':
                    following.extend(_expand_ayah_words(lines[i], universe=universe))

        ayah_from_next = [
            i for i in range(next_idx, len(lines))
            if lines[i]['line_type'] == 'ayah'
            and (page_scope is None or int(lines[i]['page_number']) == int(page_scope))
        ]
        if not following:
            for i in ayah_from_next:
                _assign_words_to_line(lines[i], [], text_map)
        else:
            head = [following[0]]
            _assign_words_to_line(lines[next_idx], following, text_map)
            if not _cascade_from(
                lines, next_idx, head, text_map, universe=universe, page_scope=page_scope
            ):
                _assign_words_to_line(lines[next_idx], following, text_map)
                for i in ayah_from_next[1:]:
                    _assign_words_to_line(lines[i], [], text_map)

        _push_undo(cur, 'merge', page_number)
        for i in range(target_idx, len(lines)):
            if lines[i]['line_type'] != 'ayah':
                continue
            if page_scope is not None and int(lines[i]['page_number']) != int(page_scope):
                break
            _persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_fatiha_page(cur, lines, text_map, universe=universe)
        conn.commit()
        payload = _build_azhar_page_payload(page_number, mushaf_version=['الأزهر'])
        return jsonify({
            'ok': True,
            'page': payload,
            'undo_available': _undo_available(cur),
        })
    except Exception as e:
        logger.error(f'azhar merge-line failed: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/azhar-layout/undo', methods=['POST'])
def azhar_layout_undo():
    """Revert the last line-break / merge (wrong word → تراجع)."""
    body = request.get_json(silent=True) or {}
    try:
        page_number = int(body.get('page_number') or 0)
    except (TypeError, ValueError):
        page_number = 0

    conn = _sqlite_connect(AZHAR_LAYOUT_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        _ensure_undo_table(cur)
        row = cur.execute(
            'SELECT id, label, page_number, snapshot FROM azhar_layout_undo ORDER BY id DESC LIMIT 1'
        ).fetchone()
        if not row:
            return jsonify({'error': 'لا يوجد تعديل للتراجع عنه', 'undo_available': 0}), 400

        _restore_snapshot(cur, row['snapshot'])
        cur.execute('DELETE FROM azhar_layout_undo WHERE id = ?', (row['id'],))
        conn.commit()

        view_page = page_number or int(row['page_number'] or AZHAR_LAYOUT_MIN_PAGE)
        if not (AZHAR_LAYOUT_MIN_PAGE <= view_page <= AZHAR_LAYOUT_MAX_PAGE):
            view_page = AZHAR_LAYOUT_MIN_PAGE
        payload = _build_azhar_page_payload(view_page, mushaf_version=['الأزهر'])
        return jsonify({
            'ok': True,
            'undone': row['label'],
            'page': payload,
            'page_number': view_page,
            'undo_available': _undo_available(cur),
        })
    except Exception as e:
        logger.error(f'azhar undo failed: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/azhar-layout/undo-status', methods=['GET'])
def azhar_layout_undo_status():
    conn = _sqlite_connect(AZHAR_LAYOUT_DATABASE)
    try:
        cur = conn.cursor()
        return jsonify({'undo_available': _undo_available(cur)})
    finally:
        conn.close()


@editor_bp.route('/api/azhar-layout/progress', methods=['GET', 'POST'])
def azhar_layout_progress():
    conn = _sqlite_connect(AZHAR_LAYOUT_DATABASE)
    try:
        cur = conn.cursor()
        if request.method == 'GET':
            cur.execute(
                'SELECT page_number FROM azhar_layout_progress WHERE reviewed = 1'
            )
            pages = sorted(row[0] for row in cur.fetchall())
            return jsonify({
                'reviewed_pages': pages,
                'min_page': AZHAR_LAYOUT_MIN_PAGE,
                'max_page': AZHAR_LAYOUT_MAX_PAGE,
            })

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'JSON object required'}), 400
        try:
            page_number = int(body.get('page_number'))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid page_number'}), 400
        if not (AZHAR_LAYOUT_MIN_PAGE <= page_number <= AZHAR_LAYOUT_MAX_PAGE):
            return jsonify({'error': 'page_number out of range'}), 400
        reviewed = 1 if body.get('reviewed') else 0
        cur.execute(
            '''
            INSERT INTO azhar_layout_progress (page_number, reviewed, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(page_number) DO UPDATE SET
                reviewed = excluded.reviewed,
                updated_at = excluded.updated_at
            ''',
            (page_number, reviewed),
        )
        conn.commit()
        return jsonify({'ok': True, 'page_number': page_number, 'reviewed': bool(reviewed)})
    except Exception as e:
        logger.error(f'azhar progress failed: {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
