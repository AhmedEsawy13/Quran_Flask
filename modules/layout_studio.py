"""Layout Studio — edition-parameterized mushaf layout writer.

Routes:
  GET  /layout-studio              → default edition (azhar)
  GET  /layout-studio/<edition_id>
  GET  /api/layout-studio/editions
  GET  /api/layout-studio/<id>/page/<n>
  POST /api/layout-studio/<id>/line-break|merge-line|undo
  GET  /api/layout-studio/<id>/undo-status
  GET/POST /api/layout-studio/<id>/progress

Legacy /azhar-layout* aliases live in modules.azhar_layout.
"""
from __future__ import annotations

import logging
import os
import sqlite3

from flask import jsonify, redirect, render_template, request, url_for

from core.blueprints import editor_bp
from core.db import connect as _sqlite_connect
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules import layout_engine as engine
from modules.layout_editions import (
    LayoutEdition,
    default_edition,
    get_edition,
    public_editions,
)
from modules.layouts import _build_azhar_page_payload

logger = logging.getLogger(__name__)


def _edition_or_404(edition_id: str):
    edition = get_edition(edition_id)
    if edition is None:
        return None, (jsonify({'error': f'unknown edition: {edition_id}'}), 404)
    return edition, None


def _build_page_payload(edition: LayoutEdition, page_number: int):
    if edition.payload_kind == 'azhar':
        return _build_azhar_page_payload(
            page_number, mushaf_version=[edition.mushaf_version],
        )
    return None


def _page_in_range(edition: LayoutEdition, page_number: int) -> bool:
    return edition.min_page <= int(page_number) <= edition.max_page


def _all_script_word_ids(edition: LayoutEdition):
    return engine.all_script_word_ids(edition.script_db)


def _expand_ayah_words(edition: LayoutEdition, line, universe=None):
    return engine.expand_ayah_words(
        line, universe=universe, script_db=edition.script_db,
    )


def _word_texts(edition: LayoutEdition, word_ids):
    return engine.word_texts(edition.script_db, word_ids)


def _closed_ayah_words(edition: LayoutEdition, page_number: int, universe=None):
    rule = edition.closed_rule_for(page_number)
    if not rule:
        return []
    return engine.existing_word_ids_between(
        rule.ayah_first, rule.ayah_last,
        universe=universe, script_db=edition.script_db,
    )


def _page_is_closed(edition: LayoutEdition, page_number: int) -> bool:
    return edition.closed_rule_for(page_number) is not None


def _cascade_from(edition, lines, start_idx, head_words, text_map, universe=None, page_scope=None):
    closed_stream = None
    if page_scope is not None and _page_is_closed(edition, page_scope):
        closed_stream = _closed_ayah_words(edition, page_scope, universe=universe)
    return engine.cascade_from(
        lines, start_idx, head_words, text_map,
        universe=universe, page_scope=page_scope, closed_stream=closed_stream,
    )


def _undo_range(edition: LayoutEdition, page_number: int, cascade_page_from: int,
                cascade_page_to: int | None = None):
    """Pages to snapshot before an edit (cascade + closed-page seal side effects)."""
    rule = edition.closed_rule_for(page_number)
    if rule:
        return rule.page, rule.next_page
    page_to = int(cascade_page_to) if cascade_page_to is not None else int(cascade_page_from)
    return int(cascade_page_from), page_to


def _push_undo(edition, cur, label, page_number, cascade_page_from, cascade_page_to=None):
    page_from, page_to = _undo_range(
        edition, page_number, cascade_page_from, cascade_page_to,
    )
    engine.push_undo(
        cur, label, page_number, page_from, page_to,
        undo_table=edition.undo_table,
    )


def _undo_available(edition, cur, page_number=None):
    return engine.undo_available(
        cur, page_number, undo_table=edition.undo_table,
    )


def _segment_persist_indices(lines, cascade_idx, page_scope=None):
    """Ayah indices cascade may rewrite — stop at surah separator / page scope."""
    return engine.ayah_segment_slots(lines, cascade_idx, page_scope=page_scope)


def _neighbor_ayah(edition, lines, from_idx, *, direction, universe=None):
    """Next/prev ayah with words, or None if a surah separator blocks the path."""
    step = 1 if direction > 0 else -1
    i = from_idx + step
    while 0 <= i < len(lines):
        line = lines[i]
        if engine.is_surah_separator(line):
            return None, 'لا يمكن عبور فاصل السورة (اسم السورة / البسملة)'
        if line['line_type'] == 'ayah':
            words = _expand_ayah_words(edition, line, universe=universe)
            if words:
                return i, None
        i += step
    return None, 'لا يوجد سطر آيات مجاور'


def _purge_closed_spill(edition, lines, text_map, page_number, universe=None):
    rule = edition.closed_rule_for(page_number)
    if not rule:
        return []
    changed = []
    for i, line in enumerate(lines):
        if int(line['page_number']) <= rule.page or line['line_type'] != 'ayah':
            continue
        words = _expand_ayah_words(edition, line, universe=universe)
        kept = [w for w in words if w < rule.ayah_first or w > rule.ayah_last]
        if kept != words:
            engine.assign_words_to_line(line, kept, text_map)
            changed.append(i)
    return changed


def _restore_seed_page(edition: LayoutEdition, cur, page_number: int) -> bool:
    src_path = edition.seed_source_db
    if not src_path or not os.path.exists(src_path):
        return False
    src = sqlite3.connect(src_path)
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
        # Re-apply Azhar short-page reshape if the restored page is itself short.
        rule = edition.closed_rule_for(page_number)
        if rule:
            engine.reshape_page_line_count(
                cur, page_number, rule.target_lines,
                script_db=edition.script_db,
            )
        return True
    finally:
        src.close()


def _seal_closed_page(edition, cur, lines, text_map, page_number, universe=None):
    rule = edition.closed_rule_for(page_number)
    if not rule:
        return
    spilled = _purge_closed_spill(edition, lines, text_map, page_number, universe=universe)
    for i in spilled:
        engine.persist_line(cur, lines[i])

    next_ayah = next(
        (
            line for line in lines
            if int(line['page_number']) == rule.next_page and line['line_type'] == 'ayah'
        ),
        None,
    )
    need_restore = False
    if next_ayah is None:
        need_restore = True
    else:
        words = _expand_ayah_words(edition, next_ayah, universe=universe)
        if not words or words[0] != rule.next_page_first_word:
            need_restore = True
    if need_restore or spilled:
        if _restore_seed_page(edition, cur, rule.next_page):
            lines[:] = engine.load_all_lines(cur)


def _find_word_line(edition, lines, word_id, universe=None):
    for i, line in enumerate(lines):
        if line['line_type'] != 'ayah':
            continue
        words = _expand_ayah_words(edition, line, universe=universe)
        if word_id in words:
            return i, words
    return None, None


def render_studio(edition: LayoutEdition):
    return render_template(
        'layout_studio.html',
        edition=edition,
        edition_config=edition.client_config(),
        enable_vercel_analytics=_IS_SERVERLESS,
    )


# ── HTML ──────────────────────────────────────────────────────────────

@editor_bp.route('/layout-studio')
def layout_studio_default():
    return redirect(url_for('editor.layout_studio_edition', edition_id=default_edition().id))


@editor_bp.route('/layout-studio/<edition_id>')
def layout_studio_edition(edition_id):
    edition = get_edition(edition_id)
    if edition is None:
        return jsonify({'error': f'unknown edition: {edition_id}'}), 404
    return render_studio(edition)


# ── API ───────────────────────────────────────────────────────────────

@editor_bp.route('/api/layout-studio/editions', methods=['GET'])
def layout_studio_editions():
    return jsonify({'editions': public_editions(), 'default': default_edition().id})


@editor_bp.route('/api/layout-studio/<edition_id>/page/<int:page_number>', methods=['GET'])
def layout_studio_page(edition_id, page_number):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    if not _page_in_range(edition, page_number):
        return jsonify({
            'error': f'page_number must be between {edition.min_page} and {edition.max_page}'
        }), 400
    payload = _build_page_payload(edition, page_number)
    if not payload:
        return jsonify({'error': 'Page not found'}), 404
    return jsonify(payload)


@editor_bp.route('/api/layout-studio/<edition_id>/line-break', methods=['POST'])
def layout_studio_line_break(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
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
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400

    conn = _sqlite_connect(edition.layout_db)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
        universe = _all_script_word_ids(edition)
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
        words = _expand_ayah_words(edition, target, universe=universe)
        if word_id not in words:
            found_idx, words = _find_word_line(edition, lines, word_id, universe=universe)
            if found_idx is None:
                return jsonify({'error': 'word_id not on an ayah line'}), 400
            target_idx = found_idx
            target = lines[target_idx]

        if role == 'end':
            if word_id == words[-1]:
                payload = _build_page_payload(edition, page_number)
                return jsonify({
                    'ok': True, 'unchanged': True, 'role': role, 'page': payload,
                    'undo_available': _undo_available(edition, cur, page_number),
                    'reason': 'already_line_end',
                })
            cut = words.index(word_id) + 1
            head = words[:cut]
            cascade_idx = target_idx
        else:
            if word_id == words[0]:
                payload = _build_page_payload(edition, page_number)
                return jsonify({
                    'ok': True, 'unchanged': True, 'role': role, 'page': payload,
                    'undo_available': _undo_available(edition, cur, page_number),
                    'reason': 'already_line_start',
                })
            pos = words.index(word_id)
            prev_ayah_idx, neighbor_err = _neighbor_ayah(
                edition, lines, target_idx, direction=-1, universe=universe,
            )
            if prev_ayah_idx is None:
                return jsonify({'error': neighbor_err or 'لا يوجد سطر سابق لبدء السطر هنا'}), 400
            prev_words = _expand_ayah_words(edition, lines[prev_ayah_idx], universe=universe)
            head = prev_words + words[:pos]
            cascade_idx = prev_ayah_idx

        page_scope = page_number if _page_is_closed(edition, page_number) else None
        slots = _segment_persist_indices(lines, cascade_idx, page_scope=page_scope)
        if not slots:
            return jsonify({'error': 'cascade failed'}), 400

        needed = set()
        if page_scope is not None:
            needed.update(_closed_ayah_words(edition, page_scope, universe=universe))
        for i in slots:
            needed.update(_expand_ayah_words(edition, lines[i], universe=universe))
        text_map = _word_texts(edition, sorted(needed))
        if not _cascade_from(
            edition, lines, cascade_idx, head, text_map,
            universe=universe, page_scope=page_scope,
        ):
            return jsonify({
                'error': (
                    'لا يمكن كسر السطر هنا — لا يوجد سطر تالٍ في السورة '
                    'لاستيعاب بقية الكلمات (لا يُسمح بعبور اسم السورة/البسملة)'
                ),
            }), 400

        page_from, page_to = engine.segment_page_bounds(
            lines, cascade_idx, page_scope=page_scope,
        )
        _push_undo(edition, cur, f'line-{role}', page_number, page_from, page_to)
        for i in slots:
            engine.persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_closed_page(edition, cur, lines, text_map, page_scope, universe=universe)
        conn.commit()
        payload = _build_page_payload(edition, page_number)
        return jsonify({
            'ok': True,
            'role': role,
            'page': payload,
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except Exception as e:
        logger.error(f'layout-studio line-break failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/merge-line', methods=['POST'])
def layout_studio_merge_line(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        page_number = int(data.get('page_number'))
        line_number = int(data.get('line_number'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number or line_number'}), 400

    conn = _sqlite_connect(edition.layout_db)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
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

        next_idx, neighbor_err = _neighbor_ayah(
            edition, lines, target_idx, direction=1,
        )
        if next_idx is None:
            return jsonify({
                'error': neighbor_err or 'no following ayah line',
            }), 400

        if _page_is_closed(edition, page_number) and int(lines[next_idx]['page_number']) != page_number:
            return jsonify({'error': 'لا يمكن الدمج خارج الصفحة المغلقة'}), 400

        a = _expand_ayah_words(edition, lines[target_idx])
        b = _expand_ayah_words(edition, lines[next_idx])
        merged = a + b
        if not merged:
            return jsonify({'error': 'nothing to merge'}), 400

        page_scope = page_number if _page_is_closed(edition, page_number) else None
        universe = _all_script_word_ids(edition)
        slots = _segment_persist_indices(lines, target_idx, page_scope=page_scope)
        needed = set(merged)
        if page_scope is not None:
            needed.update(_closed_ayah_words(edition, page_scope, universe=universe))
        for i in slots:
            needed.update(_expand_ayah_words(edition, lines[i], universe=universe))
        text_map = _word_texts(edition, sorted(needed))

        engine.assign_words_to_line(lines[target_idx], merged, text_map)

        if page_scope is not None:
            canonical = _closed_ayah_words(edition, page_scope, universe=universe)
            if canonical[:len(merged)] != merged:
                return jsonify({'error': 'merge cascade failed'}), 400
            following = canonical[len(merged):]
        else:
            # Words that remain after the merged target+next line, still in-segment.
            following = []
            for i in slots:
                if i > next_idx:
                    following.extend(_expand_ayah_words(edition, lines[i], universe=universe))

        ayah_from_next = [i for i in slots if i >= next_idx]
        if not following:
            for i in ayah_from_next:
                engine.assign_words_to_line(lines[i], [], text_map)
        else:
            # Put the remainder on next_idx and clear later slots so cascade_from
            # does not double-count words still sitting on those lines.
            engine.assign_words_to_line(lines[next_idx], following, text_map)
            for i in ayah_from_next[1:]:
                engine.assign_words_to_line(lines[i], [], text_map)
            head = [following[0]]
            if not _cascade_from(
                edition, lines, next_idx, head, text_map,
                universe=universe, page_scope=page_scope,
            ):
                engine.assign_words_to_line(lines[next_idx], following, text_map)
                for i in ayah_from_next[1:]:
                    engine.assign_words_to_line(lines[i], [], text_map)

        page_from, page_to = engine.segment_page_bounds(
            lines, target_idx, page_scope=page_scope,
        )
        _push_undo(edition, cur, 'merge', page_number, page_from, page_to)
        for i in slots:
            engine.persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_closed_page(edition, cur, lines, text_map, page_scope, universe=universe)
        conn.commit()
        payload = _build_page_payload(edition, page_number)
        return jsonify({
            'ok': True,
            'page': payload,
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except Exception as e:
        logger.error(f'layout-studio merge-line failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/undo', methods=['POST'])
def layout_studio_undo(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    try:
        page_number = int(body.get('page_number') or 0)
    except (TypeError, ValueError):
        page_number = 0

    conn = _sqlite_connect(edition.layout_db)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        popped = engine.pop_undo(
            cur, page_number if page_number else None,
            undo_table=edition.undo_table,
        )
        if not popped and page_number:
            popped = engine.pop_undo(cur, None, undo_table=edition.undo_table)
        if not popped:
            return jsonify({'error': 'لا يوجد تعديل للتراجع عنه', 'undo_available': 0}), 400
        conn.commit()

        view_page = page_number or int(popped.get('page_number') or edition.min_page)
        if not _page_in_range(edition, view_page):
            view_page = edition.min_page
        payload = _build_page_payload(edition, view_page)
        return jsonify({
            'ok': True,
            'undone': popped.get('label'),
            'page': payload,
            'page_number': view_page,
            'undo_available': _undo_available(edition, cur, view_page),
        })
    except Exception as e:
        logger.error(f'layout-studio undo failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/undo-status', methods=['GET'])
def layout_studio_undo_status(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    page_raw = request.args.get('page_number')
    page_number = None
    if page_raw is not None:
        try:
            page_number = int(page_raw)
        except (TypeError, ValueError):
            page_number = None
    conn = _sqlite_connect(edition.layout_db)
    try:
        cur = conn.cursor()
        return jsonify({
            'undo_available': _undo_available(edition, cur, page_number),
            'page_number': page_number,
            'edition': edition.id,
        })
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/progress', methods=['GET', 'POST'])
def layout_studio_progress(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    table = edition.progress_table
    if not all(c.isalnum() or c == '_' for c in table):
        return jsonify({'error': 'invalid progress table'}), 500

    conn = _sqlite_connect(edition.layout_db)
    try:
        cur = conn.cursor()
        cur.execute(
            f'''
            CREATE TABLE IF NOT EXISTS {table} (
                page_number INTEGER PRIMARY KEY,
                reviewed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
            '''
        )
        if request.method == 'GET':
            cur.execute(f'SELECT page_number FROM {table} WHERE reviewed = 1')
            pages = sorted(row[0] for row in cur.fetchall())
            return jsonify({
                'reviewed_pages': pages,
                'min_page': edition.min_page,
                'max_page': edition.max_page,
                'edition': edition.id,
            })

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'JSON object required'}), 400
        try:
            page_number = int(body.get('page_number'))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid page_number'}), 400
        if not _page_in_range(edition, page_number):
            return jsonify({'error': 'page_number out of range'}), 400
        reviewed = 1 if body.get('reviewed') else 0
        cur.execute(
            f'''
            INSERT INTO {table} (page_number, reviewed, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(page_number) DO UPDATE SET
                reviewed = excluded.reviewed,
                updated_at = excluded.updated_at
            ''',
            (page_number, reviewed),
        )
        conn.commit()
        return jsonify({
            'ok': True,
            'page_number': page_number,
            'reviewed': bool(reviewed),
            'edition': edition.id,
        })
    except Exception as e:
        logger.error(f'layout-studio progress failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
