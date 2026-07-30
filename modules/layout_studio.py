"""Layout Studio — edition-parameterized mushaf layout writer.

Routes:
  GET  /layout-studio              → default edition (azhar)
  GET  /layout-studio/<edition_id>
  GET  /api/layout-studio/editions
  GET  /api/layout-studio/<id>/page/<n>
  GET/POST /api/layout-studio/<id>/profile
  POST /api/layout-studio/<id>/line-break|pull-next-word|push-last-word
       |transfer-line|merge-line|line-center|header-move|undo
  GET  /api/layout-studio/<id>/undo-status
  GET/POST /api/layout-studio/<id>/progress

Legacy /azhar-layout* aliases live in modules.azhar_layout.
"""
from __future__ import annotations

import logging
import os
import sqlite3

from flask import jsonify, redirect, render_template, request, send_file, url_for

from core import layout_persistence
from core import supabase_editor as sb
from core.blueprints import editor_bp
from core.db import connect as _sqlite_connect
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules import layout_engine as engine
from modules.editor_auth import current_editor, require_editor
from modules.layout_editions import (
    LayoutEdition,
    LayoutProfile,
    default_edition,
    get_edition,
    list_editions,
    public_editions,
    public_profile_presets,
)
from modules.editor import _bahrain_ref_jpeg
from modules.layouts import _assemble_layout_page, _build_azhar_page_payload

logger = logging.getLogger(__name__)

_PROFILE_TABLE = 'layout_studio_profile'
_PAGE_END_MODES = frozenset({'ayah', 'continuous'})


def _layout_db(edition: LayoutEdition) -> str:
    return layout_persistence.working_db_path(edition)


def _cloud_actor_id() -> str | None:
    user = current_editor() if sb.is_configured() else None
    return str(user['id']) if user and user.get('id') else None


def _commit_layout_pages(
    edition: LayoutEdition,
    conn,
    cur,
    page_from: int,
    page_to: int | None = None,
    *,
    audit_action: str = 'layout_save',
    op: str | None = None,
) -> bool:
    end = int(page_to) if page_to is not None else int(page_from)
    before_by_page: dict[int, list] = {}
    if sb.is_configured() and layout_persistence.is_cloud_layout(edition):
        try:
            for row in sb.fetch_layout_pages(edition=edition.id):
                pn = int(row['page_number'])
                if int(page_from) <= pn <= end:
                    before_by_page[pn] = list(row.get('lines') or [])
        except sb.SupabaseEditorError as exc:
            logger.warning('layout audit before-fetch failed: %s', exc)

    cloud_saved = layout_persistence.save_pages(
        edition,
        cur,
        page_from=page_from,
        page_to=page_to,
        updated_by=_cloud_actor_id(),
    )
    conn.commit()
    if cloud_saved and sb.is_configured():
        user = current_editor()
        meta = layout_persistence.audit_meta_for_pages(
            edition,
            cur,
            int(page_from),
            end,
            before_by_page=before_by_page,
            op=op or (
                'undo' if audit_action == 'layout_undo' else None
            ),
        )
        sb.append_audit(
            actor_id=user['id'] if user else None,
            actor_name=user.get('name') if user else None,
            action=audit_action if audit_action in sb.AUDIT_ACTIONS else 'layout_save',
            edition=edition.id,
            page_number=int(page_from),
            meta=meta,
        )
    return cloud_saved


def _profile_from_mapping(edition: LayoutEdition, values) -> LayoutProfile:
    """Validate a client/database profile against safe editor bounds."""
    source = values or {}

    def integer(name, default, *, minimum, maximum):
        raw = source.get(name, default)
        if isinstance(raw, bool):
            raise ValueError(f'{name} must be an integer')
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'{name} must be an integer') from None
        if value < minimum or value > maximum:
            raise ValueError(f'{name} must be between {minimum} and {maximum}')
        return value

    lines_per_page = integer(
        'lines_per_page', edition.profile.lines_per_page,
        minimum=3, maximum=40,
    )
    page_end_mode = str(
        source.get('page_end_mode', edition.profile.page_end_mode)
    ).strip().lower()
    if page_end_mode not in _PAGE_END_MODES:
        raise ValueError('page_end_mode must be ayah or continuous')
    surah_name_lines = integer(
        'surah_name_lines', edition.profile.surah_name_lines,
        minimum=1, maximum=4,
    )
    surah_info_lines = integer(
        'surah_info_lines', edition.profile.surah_info_lines,
        minimum=0, maximum=4,
    )
    basmallah_lines = integer(
        'basmallah_lines', edition.profile.basmallah_lines,
        minimum=0, maximum=4,
    )
    header_total = surah_name_lines + surah_info_lines + basmallah_lines
    if header_total >= lines_per_page:
        raise ValueError(
            'surah header slots must leave at least one ayah line on the page'
        )
    return LayoutProfile(
        lines_per_page=lines_per_page,
        page_end_mode=page_end_mode,
        surah_name_lines=surah_name_lines,
        surah_info_lines=surah_info_lines,
        basmallah_lines=basmallah_lines,
    )


def _profile_table_exists(cur) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (_PROFILE_TABLE,),
    ).fetchone() is not None


def _load_profile(edition: LayoutEdition, cur=None) -> LayoutProfile:
    """Read an edition override without creating schema during ordinary GETs."""
    owns_connection = cur is None
    conn = None
    if owns_connection:
        conn = _sqlite_connect(_layout_db(edition))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
    try:
        if not _profile_table_exists(cur):
            return edition.profile
        row = cur.execute(
            f'''
            SELECT lines_per_page, page_end_mode, surah_name_lines,
                   surah_info_lines, basmallah_lines
            FROM {_PROFILE_TABLE}
            WHERE id = 1
            '''
        ).fetchone()
        if row is None:
            return edition.profile
        return _profile_from_mapping(edition, dict(row))
    except (sqlite3.DatabaseError, ValueError) as exc:
        logger.warning(
            'Ignoring invalid layout profile for %s: %s', edition.id, exc,
        )
        return edition.profile
    finally:
        if conn is not None:
            conn.close()


def _save_profile(cur, profile: LayoutProfile) -> None:
    cur.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {_PROFILE_TABLE} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            lines_per_page INTEGER NOT NULL,
            page_end_mode TEXT NOT NULL
                CHECK (page_end_mode IN ('ayah', 'continuous')),
            surah_name_lines INTEGER NOT NULL,
            surah_info_lines INTEGER NOT NULL,
            basmallah_lines INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        '''
    )
    cur.execute(
        f'''
        INSERT INTO {_PROFILE_TABLE} (
            id, lines_per_page, page_end_mode, surah_name_lines,
            surah_info_lines, basmallah_lines, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            lines_per_page = excluded.lines_per_page,
            page_end_mode = excluded.page_end_mode,
            surah_name_lines = excluded.surah_name_lines,
            surah_info_lines = excluded.surah_info_lines,
            basmallah_lines = excluded.basmallah_lines,
            updated_at = excluded.updated_at
        ''',
        (
            profile.lines_per_page,
            profile.page_end_mode,
            profile.surah_name_lines,
            profile.surah_info_lines,
            profile.basmallah_lines,
        ),
    )


def _profile_payload(edition: LayoutEdition, profile: LayoutProfile) -> dict:
    return {
        'edition_id': edition.id,
        'profile': profile.as_client_dict(),
        'defaults': edition.profile.as_client_dict(),
        'presets': public_profile_presets(),
        'short_pages': {
            **{
                str(page): int(lines)
                for page, lines in edition.line_count_overrides
            },
            **{
                str(rule.page): int(rule.target_lines)
                for rule in edition.closed_pages
            },
        },
    }


def _page_scope_for_edit(
    edition: LayoutEdition,
    profile: LayoutProfile,
    page_number: int,
) -> int | None:
    if _page_is_closed(edition, page_number):
        return int(page_number)
    if profile.page_end_mode == 'ayah':
        return int(page_number)
    return None


def _page_ayah_words(edition, lines, page_number, universe=None) -> list[int]:
    words: list[int] = []
    for line in lines:
        if (
            int(line['page_number']) == int(page_number)
            and line['line_type'] == 'ayah'
        ):
            words.extend(
                _expand_ayah_words(edition, line, universe=universe)
            )
    return words


def _scope_word_stream(
    edition,
    lines,
    page_scope,
    *,
    start_idx,
    universe=None,
) -> list[int] | None:
    if page_scope is None:
        return None
    if _page_is_closed(edition, page_scope):
        return _closed_ayah_words(edition, page_scope, universe=universe)
    left = int(start_idx)
    while left > 0:
        previous = lines[left - 1]
        if int(previous['page_number']) != int(page_scope):
            break
        if engine.is_surah_separator(previous):
            break
        left -= 1
    right = int(start_idx)
    while right < len(lines):
        line = lines[right]
        if int(line['page_number']) != int(page_scope):
            break
        if right != int(start_idx) and engine.is_surah_separator(line):
            break
        right += 1
    words: list[int] = []
    for index in range(left, right):
        if lines[index]['line_type'] == 'ayah':
            words.extend(
                _expand_ayah_words(
                    edition, lines[index], universe=universe,
                )
            )
    return words


def _strict_word_order(word_ids, universe=None) -> bool:
    ids = [int(word_id) for word_id in word_ids]
    if len(ids) != len(set(ids)):
        return False
    if universe is None:
        return all(left < right for left, right in zip(ids, ids[1:]))
    positions = {
        int(word_id): position
        for position, word_id in enumerate(universe)
    }
    sequence = [positions.get(word_id) for word_id in ids]
    return (
        all(position is not None for position in sequence)
        and all(left < right for left, right in zip(sequence, sequence[1:]))
    )


def _fixed_page_stream_or_error(
    edition, lines, page_scope, *, universe=None,
):
    if page_scope is None:
        return None, None
    stream = _page_ayah_words(
        edition, lines, page_scope, universe=universe,
    )
    if not _strict_word_order(stream, universe=universe):
        return None, (
            'توجد كلمات مكررة أو غير مرتبة في هذه الصفحة؛ '
            'أصلح الصفحة قبل إجراء تعديل جديد'
        )
    return stream, None


def _edition_or_404(edition_id: str):
    edition = get_edition(edition_id)
    if edition is None:
        return None, (jsonify({'error': f'unknown edition: {edition_id}'}), 404)
    return edition, None


def _project_word_map(edition: LayoutEdition) -> dict:
    """Word map scoped to this edition's script database and ID namespace."""
    return {
        **engine.script_word_map(edition.script_db),
        'id_space': edition.word_id_space,
    }


def _build_project_payload(
    edition: LayoutEdition,
    page_number: int,
):
    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = [
            dict(row) for row in cur.execute(
                '''
                SELECT page_number, line_number, line_type, is_centered,
                       first_word_id, last_word_id, surah_number
                FROM pages
                WHERE page_number = ?
                ORDER BY line_number
                ''',
                (int(page_number),),
            ).fetchall()
        ]
        info_row = cur.execute(
            '''
            SELECT font_name, number_of_pages, lines_per_page, name
            FROM info LIMIT 1
            '''
        ).fetchone()
    finally:
        conn.close()
    if not lines:
        return None
    payload = _assemble_layout_page(
        lines,
        info_row,
        page_number,
        None,
        None,
        source=f'layout_studio_{edition.id}',
        font_name_default=edition.font_name,
        include_advance=False,
        mushaf_version=edition.mushaf_version,
        word_map=_project_word_map(edition),
    )
    payload['font_name'] = edition.font_name
    payload['mushaf_version'] = edition.mushaf_version
    payload['min_page'] = edition.min_page
    payload['max_page'] = edition.max_page
    return payload


def _page_line_budget(
    edition: LayoutEdition,
    profile: LayoutProfile,
    page_number: int,
) -> int:
    rule = edition.closed_rule_for(page_number)
    if rule:
        return int(rule.target_lines)
    special = next(
        (
            int(lines) for page, lines in edition.line_count_overrides
            if int(page) == int(page_number)
        ),
        None,
    )
    return int(special if special is not None else profile.lines_per_page)


def _build_page_payload(edition: LayoutEdition, page_number: int):
    if edition.payload_kind == 'azhar':
        payload = _build_azhar_page_payload(
            page_number, mushaf_version=[edition.mushaf_version],
        )
    elif edition.payload_kind in {'canonical_qpc', 'canonical_script'}:
        payload = _build_project_payload(edition, page_number)
    else:
        payload = None
    if not payload:
        return payload
    payload['word_id_space'] = edition.word_id_space
    profile = _load_profile(edition)
    span_by_type = {
        'surah_name': profile.surah_name_lines,
        'surah_info': profile.surah_info_lines,
        'basmallah': profile.basmallah_lines,
    }
    occupied = 0
    for line in payload.get('lines') or []:
        span = int(span_by_type.get(line.get('line_type'), 1))
        line['slot_span'] = span
        occupied += span
    payload['lines_per_page'] = _page_line_budget(
        edition, profile, page_number,
    )
    payload['default_lines_per_page'] = int(profile.lines_per_page)
    payload['occupied_line_slots'] = occupied
    payload['layout_profile'] = profile.as_client_dict()
    conn = _sqlite_connect(_layout_db(edition))
    try:
        has_confidence = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='layout_import_confidence'"
        ).fetchone()
        confidence = (
            conn.execute(
                '''
                SELECT score, status, matched_lines, anchored_lines,
                       estimated_line_ends, notes
                FROM layout_import_confidence
                WHERE page_number = ?
                ''',
                (int(page_number),),
            ).fetchone()
            if has_confidence else None
        )
    finally:
        conn.close()
    if confidence:
        payload['import_confidence'] = {
            'score': float(confidence[0]),
            'status': confidence[1],
            'matched_lines': int(confidence[2]),
            'anchored_lines': int(confidence[3]),
            'estimated_line_ends': int(confidence[4]),
            'notes': confidence[5] or '',
        }
    return payload


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


def _cascade_from(
    edition, lines, start_idx, head_words, text_map, universe=None,
    page_scope=None, scope_stream=None,
):
    closed_stream = scope_stream
    if closed_stream is None and page_scope is not None and _page_is_closed(
        edition, page_scope,
    ):
        closed_stream = _closed_ayah_words(
            edition, page_scope, universe=universe,
        )
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


def _structural_page_rows(cur, page_number: int) -> list[dict]:
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number
        ''',
        (int(page_number),),
    )
    columns = [item[0] for item in cur.description]
    return [
        dict(zip(columns, row))
        for row in cur.fetchall()
    ]


def _structural_word_stream(
    edition: LayoutEdition,
    rows: list[dict],
    *,
    universe,
) -> list[int]:
    return [
        word_id
        for row in rows
        if row['line_type'] == 'ayah'
        for word_id in _expand_ayah_words(
            edition, row, universe=universe,
        )
    ]


def _persist_structural_pages(
    cur,
    pages: dict[int, list[dict]],
    *,
    deleted_ids: set[int],
) -> None:
    page_numbers = sorted(int(page) for page in pages)
    placeholders = ','.join('?' * len(page_numbers))
    cur.execute(
        f'UPDATE pages SET line_number = -id '
        f'WHERE page_number IN ({placeholders})',
        page_numbers,
    )
    if deleted_ids:
        delete_placeholders = ','.join('?' * len(deleted_ids))
        cur.execute(
            f'DELETE FROM pages WHERE id IN ({delete_placeholders})',
            tuple(sorted(deleted_ids)),
        )
    for page_number in page_numbers:
        for line_number, row in enumerate(pages[page_number], 1):
            values = (
                int(page_number),
                int(line_number),
                row['line_type'],
                int(bool(row.get('is_centered'))),
                row.get('first_word_id'),
                row.get('last_word_id'),
                row.get('surah_number'),
                row.get('line_text') or '',
            )
            if row.get('id') is None:
                cur.execute(
                    '''
                    INSERT INTO pages (
                        page_number, line_number, line_type, is_centered,
                        first_word_id, last_word_id, surah_number, line_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    values,
                )
                row['id'] = int(cur.lastrowid)
            else:
                cur.execute(
                    '''
                    UPDATE pages
                    SET page_number = ?, line_number = ?, line_type = ?,
                        is_centered = ?, first_word_id = ?,
                        last_word_id = ?, surah_number = ?, line_text = ?
                    WHERE id = ?
                    ''',
                    (*values, int(row['id'])),
                )


def _shift_rows_down_one_slot(
    edition: LayoutEdition,
    cur,
    page_number: int,
    insert_index: int,
    *,
    profile: LayoutProfile,
    universe,
    allow_protected_source: bool = False,
) -> dict:
    """Insert one blank slot and cascade the remaining physical rows down.

    A full source page spills its last row to the top of the next page. The
    destination consumes an existing empty row when possible; otherwise its
    final adjacent ayah pair is merged. Quran word order is verified before
    any rows are persisted.
    """
    page_number = int(page_number)
    next_page = page_number + 1
    source_rows = _structural_page_rows(cur, page_number)
    if not source_rows:
        raise ValueError(f'page {page_number} has no lines')
    protected_source_count = edition.protected_trailing_count_for(page_number)
    if protected_source_count and not allow_protected_source:
        raise ValueError(
            f'آخر {protected_source_count} سطر في الصفحة {page_number} '
            'محفوظة معاً كما في المطبوع ولا يمكن فصلها بترحيل سطر واحد'
        )
    source_limit = _page_line_budget(edition, profile, page_number)
    if len(source_rows) != source_limit:
        raise ValueError(
            f'الصفحة {page_number} تحتوي {len(source_rows)} سطراً '
            f'بدلاً من {source_limit}؛ صحّح عدد السطور أولاً'
        )
    if insert_index < 0 or insert_index >= len(source_rows):
        raise ValueError('موضع الترحيل خارج الصفحة')

    will_spill = len(source_rows) + 1 > source_limit
    if will_spill and not _page_in_range(edition, next_page):
        raise ValueError('لا توجد صفحة تالية لاستقبال السطر')
    destination_rows = (
        _structural_page_rows(cur, next_page) if will_spill else []
    )
    destination_limit = (
        _page_line_budget(edition, profile, next_page)
        if will_spill else 0
    )
    if will_spill and not destination_rows:
        raise ValueError('الصفحة التالية لا تحتوي سطوراً')

    before_stream = _structural_word_stream(
        edition, source_rows + destination_rows, universe=universe,
    )
    blank_surah = source_rows[insert_index].get('surah_number')
    if blank_surah is None and insert_index:
        blank_surah = source_rows[insert_index - 1].get('surah_number')
    blank = {
        'id': None,
        'page_number': page_number,
        'line_number': 0,
        'line_type': 'ayah',
        'is_centered': 0,
        'first_word_id': None,
        'last_word_id': None,
        'surah_number': blank_surah,
        'line_text': '',
    }
    def protected_trailing_ids(rows, page):
        protected_count = edition.protected_trailing_count_for(page)
        if not protected_count:
            return ()
        if len(rows) < protected_count:
            raise ValueError(
                f'الصفحة {page} لا تحتوي مواضع كافية للأسطر المحفوظة'
            )
        return tuple(
            int(row['id'])
            for row in rows[-protected_count:]
            if row.get('id') is not None
        )

    protected_destination_tail_ids = (
        protected_trailing_ids(destination_rows, next_page)
        if will_spill else ()
    )
    source_rows.insert(insert_index, blank)
    spill = None
    if len(source_rows) > source_limit:
        spill = source_rows.pop()
    if spill is not None:
        destination_rows.insert(0, spill)

    deleted_ids: set[int] = set()
    removed_empty = 0
    merged_lines = 0
    protected_destination_ids = set(protected_destination_tail_ids)
    while len(destination_rows) > destination_limit:
        empty_index = next(
            (
                index
                for index in range(len(destination_rows) - 1, -1, -1)
                if destination_rows[index]['line_type'] == 'ayah'
                and (
                    destination_rows[index].get('id') is None
                    or int(destination_rows[index]['id'])
                    not in protected_destination_ids
                )
                and not _expand_ayah_words(
                    edition, destination_rows[index], universe=universe,
                )
            ),
            None,
        )
        if empty_index is not None:
            removed = destination_rows.pop(empty_index)
            if removed.get('id') is not None:
                deleted_ids.add(int(removed['id']))
            removed_empty += 1
            continue

        pairs = [
            index for index in range(len(destination_rows) - 2, -1, -1)
            if destination_rows[index]['line_type'] == 'ayah'
            and destination_rows[index + 1]['line_type'] == 'ayah'
            and _expand_ayah_words(
                edition, destination_rows[index], universe=universe,
            )
            and _expand_ayah_words(
                edition, destination_rows[index + 1], universe=universe,
            )
            and (
                destination_rows[index].get('surah_number')
                == destination_rows[index + 1].get('surah_number')
            )
            and (
                destination_rows[index].get('id') is None
                or int(destination_rows[index]['id'])
                not in protected_destination_ids
            )
            and (
                destination_rows[index + 1].get('id') is None
                or int(destination_rows[index + 1]['id'])
                not in protected_destination_ids
            )
        ]
        if not pairs:
            raise ValueError(
                'لا يمكن استيعاب السطر في الصفحة التالية دون عبور فاصل سورة'
            )
        pair_index = pairs[0]
        kept = destination_rows[pair_index]
        removed = destination_rows.pop(pair_index + 1)
        merged_words = (
            _expand_ayah_words(edition, kept, universe=universe)
            + _expand_ayah_words(edition, removed, universe=universe)
        )
        text_map = _word_texts(edition, merged_words)
        engine.assign_words_to_line(kept, merged_words, text_map)
        kept['is_centered'] = int(
            bool(kept.get('is_centered'))
            and bool(removed.get('is_centered'))
        )
        if removed.get('id') is not None:
            deleted_ids.add(int(removed['id']))
        merged_lines += 1

    pages = {page_number: source_rows}
    if will_spill:
        pages[next_page] = destination_rows
    after_stream = _structural_word_stream(
        edition,
        [
            row
            for affected_rows in pages.values()
            for row in affected_rows
        ],
        universe=universe,
    )
    if after_stream != before_stream:
        raise ValueError(
            'أُلغي الترحيل لأنه كان سيكرر كلمات أو يفقدها'
        )
    if protected_destination_tail_ids:
        current_tail_ids = protected_trailing_ids(
            destination_rows, next_page,
        )
        if current_tail_ids != protected_destination_tail_ids:
            raise ValueError(
                f'أُلغي الترحيل لحماية آخر '
                f'{len(protected_destination_tail_ids)} سطر في الصفحة '
                f'{next_page}'
            )
    _persist_structural_pages(
        cur, pages, deleted_ids=deleted_ids,
    )
    return {
        'page_from': page_number,
        'page_to': next_page if will_spill else page_number,
        'spilled_row_id': (
            int(spill['id'])
            if spill is not None and spill.get('id') is not None else None
        ),
        'removed_empty_line': bool(removed_empty),
        'merged_lines': merged_lines,
    }


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
    profile = _load_profile(edition)
    return render_template(
        'layout_studio.html',
        edition=edition,
        studio_editions=list_editions(),
        edition_config=edition.client_config(profile),
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


@editor_bp.route(
    '/api/layout-studio/<edition_id>/profile',
    methods=['GET', 'POST'],
)
@require_editor
def layout_studio_profile(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    if request.method == 'GET':
        return jsonify(_profile_payload(edition, _load_profile(edition)))

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    values = data.get('profile', data)
    if not isinstance(values, dict):
        return jsonify({'error': 'profile must be an object'}), 400
    try:
        profile = _profile_from_mapping(edition, values)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        _save_profile(conn.cursor(), profile)
        cloud_saved = layout_persistence.save_profile(
            edition,
            profile.as_client_dict(),
            updated_by=_cloud_actor_id(),
        )
        conn.commit()
        if cloud_saved and sb.is_configured():
            user = current_editor()
            sb.append_audit(
                actor_id=user['id'] if user else None,
                actor_name=user.get('name') if user else None,
                action='layout_profile',
                edition=edition.id,
            )
    except sb.SupabaseEditorError as exc:
        conn.rollback()
        logger.error(
            'layout-studio profile cloud save failed (%s): %s',
            edition_id, exc,
        )
        return jsonify({'error': 'تعذّر حفظ إعدادات التخطيط في Supabase'}), 503
    except Exception as exc:
        conn.rollback()
        logger.error('layout-studio profile save failed (%s): %s', edition_id, exc)
        return jsonify({'error': str(exc)}), 500
    finally:
        conn.close()
    return jsonify({
        'ok': True,
        'cloud_saved': cloud_saved,
        **_profile_payload(edition, profile),
        'meta_label': (
            f'{edition.mushaf_version} · {profile.lines_per_page} سطراً · '
            f'{edition.font_name}'
        ),
    })


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


@editor_bp.route(
    '/api/layout-studio/<edition_id>/reference/<int:page_number>.jpg',
    methods=['GET'],
)
def layout_studio_reference(edition_id, page_number):
    """Read-only printed reference used beside a Layout Studio project."""
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400
    if edition.id != 'bahrain':
        return jsonify({'error': 'local reference unavailable'}), 404
    try:
        width = int(request.args.get('w') or 1024)
    except (TypeError, ValueError):
        width = 1024
    width = max(480, min(width, 1400))
    path = _bahrain_ref_jpeg(page_number, width=width)
    if not path:
        return jsonify({
            'error': 'bahrain reference unavailable',
            'hint': 'Run: python pipeline/fetch_bahrain_ref_pdf.py',
        }), 404
    return send_file(
        path, mimetype='image/jpeg', max_age=86400, conditional=True,
    )


@editor_bp.route(
    '/api/layout-studio/<edition_id>/page-by-ayah/'
    '<int:surah_number>/<int:ayah_number>',
    methods=['GET'],
)
def layout_studio_page_by_ayah(edition_id, surah_number, ayah_number):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    conn = _sqlite_connect(edition.script_db)
    try:
        first_word = conn.execute(
            '''
            SELECT word_index
            FROM words
            WHERE surah = ? AND ayah = ?
            ORDER BY word_index
            LIMIT 1
            ''',
            (int(surah_number), int(ayah_number)),
        ).fetchone()
    finally:
        conn.close()
    if not first_word or first_word[0] is None:
        return jsonify({'error': 'ayah not found'}), 404

    target_word_id = int(first_word[0])
    universe = _all_script_word_ids(edition)
    conn = _sqlite_connect(_layout_db(edition))
    try:
        rows = conn.execute(
            '''
            SELECT page_number, first_word_id, last_word_id
            FROM pages
            WHERE first_word_id IS NOT NULL
              AND last_word_id IS NOT NULL
            ORDER BY page_number, line_number
            ''',
        ).fetchall()
    finally:
        conn.close()
    row = next(
        (
            item for item in rows
            if target_word_id in engine.existing_word_ids_between(
                item[1], item[2],
                universe=universe, script_db=edition.script_db,
            )
        ),
        None,
    )
    if row is None:
        return jsonify({'error': 'page not found for ayah'}), 404
    return jsonify({
        'edition_id': edition.id,
        'surah': int(surah_number),
        'ayah': int(ayah_number),
        'page_number': int(row[0]),
    })


@editor_bp.route('/api/layout-studio/<edition_id>/line-break', methods=['POST'])
@require_editor
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

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
        universe = _all_script_word_ids(edition)
        profile = _load_profile(edition, cur)
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

        page_scope = _page_scope_for_edit(edition, profile, page_number)
        if (
            page_scope is not None
            and int(lines[cascade_idx]['page_number']) != int(page_scope)
        ):
            return jsonify({
                'error': 'لا يمكن نقل بداية السطر عبر حدود الصفحة الثابتة',
            }), 400
        fixed_page_stream, stream_err = _fixed_page_stream_or_error(
            edition, lines, page_scope, universe=universe,
        )
        if stream_err:
            return jsonify({'error': stream_err}), 409
        scope_stream = _scope_word_stream(
            edition, lines, page_scope,
            start_idx=cascade_idx, universe=universe,
        )
        slots = _segment_persist_indices(lines, cascade_idx, page_scope=page_scope)
        if not slots:
            return jsonify({'error': 'cascade failed'}), 400

        needed = set()
        if scope_stream is not None:
            needed.update(scope_stream)
        for i in slots:
            needed.update(_expand_ayah_words(edition, lines[i], universe=universe))
        text_map = _word_texts(edition, sorted(needed))
        if not _cascade_from(
            edition, lines, cascade_idx, head, text_map,
            universe=universe, page_scope=page_scope,
            scope_stream=scope_stream,
        ):
            return jsonify({
                'error': (
                    'لا يمكن كسر السطر هنا — لا يوجد سطر تالٍ في السورة '
                    'لاستيعاب بقية الكلمات (لا يُسمح بعبور اسم السورة/البسملة)'
                ),
            }), 400
        if (
            fixed_page_stream is not None
            and _page_ayah_words(
                edition, lines, page_scope, universe=universe,
            ) != fixed_page_stream
        ):
            return jsonify({
                'error': 'أُلغي التعديل لأنه كان سيكرر كلمات الصفحة أو يفقدها',
            }), 409

        page_from, page_to = engine.segment_page_bounds(
            lines, cascade_idx, page_scope=page_scope,
        )
        _push_undo(edition, cur, f'line-{role}', page_number, page_from, page_to)
        for i in slots:
            engine.persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_closed_page(edition, cur, lines, text_map, page_scope, universe=universe)
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_from, page_to, op='line-break',
        )
        payload = _build_page_payload(edition, page_number)
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'role': role,
            'page': payload,
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio line-break cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(f'layout-studio line-break failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/merge-line', methods=['POST'])
@require_editor
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

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
        profile = _load_profile(edition, cur)
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

        page_scope = _page_scope_for_edit(edition, profile, page_number)
        if (
            page_scope is not None
            and int(lines[next_idx]['page_number']) != int(page_scope)
        ):
            return jsonify({
                'error': 'لا يمكن الدمج عبر حدود الصفحة الثابتة',
            }), 400
        universe = _all_script_word_ids(edition)
        fixed_page_stream, stream_err = _fixed_page_stream_or_error(
            edition, lines, page_scope, universe=universe,
        )
        if stream_err:
            return jsonify({'error': stream_err}), 409

        a = _expand_ayah_words(edition, lines[target_idx])
        b = _expand_ayah_words(edition, lines[next_idx])
        merged = a + b
        if not merged:
            return jsonify({'error': 'nothing to merge'}), 400

        scope_stream = _scope_word_stream(
            edition, lines, page_scope,
            start_idx=target_idx, universe=universe,
        )
        slots = _segment_persist_indices(lines, target_idx, page_scope=page_scope)
        needed = set(merged)
        if scope_stream is not None:
            needed.update(scope_stream)
        for i in slots:
            needed.update(_expand_ayah_words(edition, lines[i], universe=universe))
        text_map = _word_texts(edition, sorted(needed))

        engine.assign_words_to_line(lines[target_idx], merged, text_map)

        if page_scope is not None:
            canonical = scope_stream or []
            try:
                canonical_start = canonical.index(a[0])
            except (ValueError, IndexError):
                canonical_start = -1
            if (
                canonical_start < 0
                or canonical[
                    canonical_start:canonical_start + len(merged)
                ] != merged
            ):
                return jsonify({'error': 'merge cascade failed'}), 400
            following = canonical[canonical_start + len(merged):]
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
                scope_stream=scope_stream,
            ):
                engine.assign_words_to_line(lines[next_idx], following, text_map)
                for i in ayah_from_next[1:]:
                    engine.assign_words_to_line(lines[i], [], text_map)

        if (
            fixed_page_stream is not None
            and _page_ayah_words(
                edition, lines, page_scope, universe=universe,
            ) != fixed_page_stream
        ):
            return jsonify({
                'error': 'أُلغي الدمج لأنه كان سيكرر كلمات الصفحة أو يفقدها',
            }), 409

        page_from, page_to = engine.segment_page_bounds(
            lines, target_idx, page_scope=page_scope,
        )
        _push_undo(edition, cur, 'merge', page_number, page_from, page_to)
        for i in slots:
            engine.persist_line(cur, lines[i])
        if page_scope is not None:
            _seal_closed_page(edition, cur, lines, text_map, page_scope, universe=universe)
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_from, page_to, op='merge-line',
        )
        payload = _build_page_payload(edition, page_number)
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'page': payload,
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio merge-line cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(f'layout-studio merge-line failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/pull-next-word', methods=['POST'])
@require_editor
def layout_studio_pull_next_word(edition_id):
    """Move one word from the following ayah line into the selected line.

    Unlike drag-and-drop, this also works when the following line is on the
    next page, which lets a reviewer pull an accidental spill back while
    viewing the previous page.
    """
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
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
        universe = _all_script_word_ids(edition)
        profile = _load_profile(edition, cur)
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
            return jsonify({'error': 'pull-next-word only applies to ayah lines'}), 400

        current_words = _expand_ayah_words(
            edition, target, universe=universe,
        )
        next_idx, neighbor_err = _neighbor_ayah(
            edition, lines, target_idx, direction=1, universe=universe,
        )
        if next_idx is None:
            return jsonify({
                'error': neighbor_err or 'لا يوجد سطر آيات تالٍ',
            }), 400
        next_page = int(lines[next_idx]['page_number'])
        cross_page = next_page != int(page_number)
        page_scope = _page_scope_for_edit(edition, profile, page_number)
        # Ayah-fixed pages normally keep their word set. Crossing the page
        # boundary is an intentional print correction (pull spill back).
        boundary_correction = (
            page_scope is not None and cross_page
        )
        edit_scope = None if boundary_correction else page_scope
        fixed_page_stream, stream_err = _fixed_page_stream_or_error(
            edition, lines, edit_scope, universe=universe,
        )
        if stream_err:
            return jsonify({'error': stream_err}), 409

        next_words = _expand_ayah_words(
            edition, lines[next_idx], universe=universe,
        )
        if not next_words:
            return jsonify({'error': 'السطر التالي فارغ'}), 400

        moved_word_id = int(next_words[0])
        needed = set(current_words) | set(next_words)
        text_map = _word_texts(edition, sorted(needed))

        if boundary_correction:
            engine.assign_words_to_line(
                target, current_words + [moved_word_id], text_map,
            )
            engine.assign_words_to_line(
                lines[next_idx], next_words[1:], text_map,
            )
            persist_idxs = [target_idx, next_idx]
            page_from, page_to = int(page_number), next_page
        else:
            scope_stream = _scope_word_stream(
                edition, lines, edit_scope,
                start_idx=target_idx, universe=universe,
            )
            slots = _segment_persist_indices(
                lines, target_idx, page_scope=edit_scope,
            )
            if scope_stream is not None:
                needed.update(scope_stream)
            for i in slots:
                needed.update(_expand_ayah_words(
                    edition, lines[i], universe=universe,
                ))
            text_map = _word_texts(edition, sorted(needed))
            if not _cascade_from(
                edition,
                lines,
                target_idx,
                current_words + [moved_word_id],
                text_map,
                universe=universe,
                page_scope=edit_scope,
                scope_stream=scope_stream,
            ):
                return jsonify({
                    'error': 'تعذّر سحب الكلمة من السطر التالي دون فقد كلمات',
                }), 400
            if (
                fixed_page_stream is not None
                and _page_ayah_words(
                    edition, lines, edit_scope, universe=universe,
                ) != fixed_page_stream
            ):
                return jsonify({
                    'error': 'أُلغي النقل لأنه كان سيكرر كلمات الصفحة أو يفقدها',
                }), 409
            persist_idxs = slots
            page_from, page_to = engine.segment_page_bounds(
                lines, target_idx, page_scope=edit_scope,
            )

        _push_undo(
            edition, cur, 'pull-next-word',
            page_number, page_from, page_to,
        )
        for i in persist_idxs:
            engine.persist_line(cur, lines[i])
        if edit_scope is not None:
            _seal_closed_page(
                edition, cur, lines, text_map, edit_scope, universe=universe,
            )
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_from, page_to, op='pull-next-word',
        )
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'moved_word_id': moved_word_id,
            'from_page': next_page,
            'crossed_page': cross_page,
            'page': _build_page_payload(edition, page_number),
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio pull-next-word cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(
            f'layout-studio pull-next-word failed ({edition_id}): {e}'
        )
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/push-last-word', methods=['POST'])
@require_editor
def layout_studio_push_last_word(edition_id):
    """Move the last word of this ayah line onto the following ayah line.

    Across page boundaries this corrects a fixed (ayah-mode) page end so the
    printed mushaf's first word of the next page can leave the previous page
    without switching the whole edition to continuous flow.
    """
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
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = engine.load_all_lines(cur)
        universe = _all_script_word_ids(edition)
        profile = _load_profile(edition, cur)
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
            return jsonify({'error': 'push-last-word only applies to ayah lines'}), 400

        current_words = _expand_ayah_words(
            edition, target, universe=universe,
        )
        if len(current_words) < 2:
            return jsonify({
                'error': 'لا يمكن دفع آخر كلمة — السطر يحتاج كلمة واحدة على الأقل تبقى فيه',
            }), 400

        next_idx, neighbor_err = _neighbor_ayah(
            edition, lines, target_idx, direction=1, universe=universe,
        )
        if next_idx is None:
            return jsonify({
                'error': neighbor_err or 'لا يوجد سطر آيات تالٍ',
            }), 400

        next_page = int(lines[next_idx]['page_number'])
        cross_page = next_page != int(page_number)
        page_scope = _page_scope_for_edit(edition, profile, page_number)
        boundary_correction = page_scope is not None and cross_page
        edit_scope = None if boundary_correction else page_scope
        fixed_page_stream, stream_err = _fixed_page_stream_or_error(
            edition, lines, edit_scope, universe=universe,
        )
        if stream_err:
            return jsonify({'error': stream_err}), 409

        next_words = _expand_ayah_words(
            edition, lines[next_idx], universe=universe,
        )
        moved_word_id = int(current_words[-1])
        kept = current_words[:-1]
        needed = set(current_words) | set(next_words)
        if not boundary_correction:
            scope_stream = _scope_word_stream(
                edition, lines, edit_scope,
                start_idx=target_idx, universe=universe,
            )
            slots = _segment_persist_indices(
                lines, target_idx, page_scope=edit_scope,
            )
            if scope_stream is not None:
                needed.update(scope_stream)
            for i in slots:
                needed.update(_expand_ayah_words(
                    edition, lines[i], universe=universe,
                ))
        text_map = _word_texts(edition, sorted(needed))

        if boundary_correction or cross_page:
            # Direct boundary transfer — do not reflow the whole next page.
            engine.assign_words_to_line(target, kept, text_map)
            engine.assign_words_to_line(
                lines[next_idx], [moved_word_id] + next_words, text_map,
            )
            persist_idxs = [target_idx, next_idx]
            page_from, page_to = sorted((int(page_number), next_page))
        else:
            if not _cascade_from(
                edition,
                lines,
                target_idx,
                kept,
                text_map,
                universe=universe,
                page_scope=edit_scope,
                scope_stream=scope_stream,
            ):
                return jsonify({
                    'error': 'تعذّر دفع الكلمة إلى السطر التالي دون فقد كلمات',
                }), 400
            if (
                fixed_page_stream is not None
                and _page_ayah_words(
                    edition, lines, edit_scope, universe=universe,
                ) != fixed_page_stream
            ):
                return jsonify({
                    'error': 'أُلغي النقل لأنه كان سيكرر كلمات الصفحة أو يفقدها',
                }), 409
            persist_idxs = slots
            page_from, page_to = engine.segment_page_bounds(
                lines, target_idx, page_scope=edit_scope,
            )

        _push_undo(
            edition, cur, 'push-last-word',
            page_number, page_from, page_to,
        )
        for i in persist_idxs:
            engine.persist_line(cur, lines[i])
        if edit_scope is not None:
            _seal_closed_page(
                edition, cur, lines, text_map, edit_scope, universe=universe,
            )
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_from, page_to, op='push-last-word',
        )
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'moved_word_id': moved_word_id,
            'to_page': next_page,
            'crossed_page': cross_page,
            'page': _build_page_payload(edition, page_number),
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio push-last-word cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(
            f'layout-studio push-last-word failed ({edition_id}): {e}'
        )
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/transfer-line', methods=['POST'])
@require_editor
def layout_studio_transfer_line(edition_id):
    """Move the final physical row intact to the top of the next page."""
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    if not edition.line_page_transfer:
        return jsonify({
            'error': 'ترحيل السطر الكامل غير مفعّل لهذه الطبعة',
        }), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        page_number = int(data.get('page_number'))
        line_number = int(data.get('line_number'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page_number or line_number'}), 400
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400
    if edition.closed_rule_for(page_number):
        return jsonify({
            'error': 'لا يمكن ترحيل سطر كامل من الصفحة الافتتاحية الثابتة',
        }), 400
    if not _page_in_range(edition, page_number + 1):
        return jsonify({'error': 'لا توجد صفحة تالية'}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        profile = _load_profile(edition, cur)
        expected_last = _page_line_budget(edition, profile, page_number)
        if line_number != expected_last:
            return jsonify({
                'error': 'ترحيل السطر الكامل متاح لآخر سطر في الصفحة فقط',
            }), 400
        target = cur.execute(
            '''
            SELECT id, line_type, first_word_id, last_word_id
            FROM pages
            WHERE page_number = ? AND line_number = ?
            ''',
            (page_number, line_number),
        ).fetchone()
        if target is None:
            return jsonify({'error': 'line not found'}), 404
        if target['line_type'] != 'ayah':
            return jsonify({
                'error': 'ترحيل السطر الكامل متاح لأسطر الآيات فقط',
            }), 400
        if target['first_word_id'] is None or target['last_word_id'] is None:
            return jsonify({'error': 'السطر الأخير فارغ بالفعل'}), 400

        universe = _all_script_word_ids(edition)
        _push_undo(
            edition, cur, 'transfer-line',
            page_number, page_number, page_number + 1,
        )
        shifted = _shift_rows_down_one_slot(
            edition,
            cur,
            page_number,
            line_number - 1,
            profile=profile,
            universe=universe,
            allow_protected_source=True,
        )
        if shifted['spilled_row_id'] != int(target['id']):
            raise ValueError('لم يصل السطر المحدد إلى الصفحة التالية')
        cloud_saved = _commit_layout_pages(
            edition,
            conn,
            cur,
            shifted['page_from'],
            shifted['page_to'],
            op='transfer-line',
        )
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'from_page': page_number,
            'to_page': page_number + 1,
            'moved_line_id': int(target['id']),
            'crossed_page': True,
            'removed_empty_line': shifted['removed_empty_line'],
            'merged_lines': shifted['merged_lines'],
            'page': _build_page_payload(edition, page_number),
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except ValueError as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio transfer-line cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(
            'layout-studio transfer-line failed (%s): %s', edition_id, e,
        )
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/line-center', methods=['POST'])
@require_editor
def layout_studio_line_center(edition_id):
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
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400
    centered = data.get('is_centered')
    if not isinstance(centered, bool):
        return jsonify({'error': 'is_centered must be a boolean'}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            '''
            SELECT id, line_type, is_centered
            FROM pages
            WHERE page_number = ? AND line_number = ?
            ''',
            (page_number, line_number),
        ).fetchone()
        if row is None:
            return jsonify({'error': 'line not found'}), 404
        if row['line_type'] != 'ayah':
            return jsonify({'error': 'line-center only applies to ayah lines'}), 400
        if bool(row['is_centered']) == centered:
            return jsonify({
                'ok': True,
                'unchanged': True,
                'page': _build_page_payload(edition, page_number),
                'undo_available': _undo_available(edition, cur, page_number),
            })

        _push_undo(
            edition, cur, 'line-center', page_number, page_number, page_number,
        )
        cur.execute(
            'UPDATE pages SET is_centered = ? WHERE id = ?',
            (1 if centered else 0, int(row['id'])),
        )
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_number, page_number, op='line-center',
        )
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'is_centered': centered,
            'page': _build_page_payload(edition, page_number),
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio line-center cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(f'layout-studio line-center failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/header-move', methods=['POST'])
@require_editor
def layout_studio_header_move(edition_id):
    """Move one surah header row by one slot or across a page boundary."""
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
    direction = str(data.get('direction') or '').strip().lower()
    if direction not in {'up', 'down'}:
        return jsonify({'error': 'direction must be up or down'}), 400
    if not _page_in_range(edition, page_number):
        return jsonify({'error': 'page_number out of range'}), 400

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        target = cur.execute(
            '''
            SELECT id, page_number, line_number, line_type
            FROM pages
            WHERE page_number = ? AND line_number = ?
            ''',
            (page_number, line_number),
        ).fetchone()
        if target is None:
            return jsonify({'error': 'line not found'}), 404
        if target['line_type'] not in engine.SURAH_HEADER_TYPES:
            return jsonify({
                'error': 'header-move only applies to surah header lines',
            }), 400

        if (
            direction == 'down'
            and edition.header_down_cascade
            and edition.closed_rule_for(page_number) is None
        ):
            profile = _load_profile(edition, cur)
            page_to = min(page_number + 1, edition.max_page)
            _push_undo(
                edition, cur, 'header-down-cascade',
                page_number, page_number, page_to,
            )
            shifted = _shift_rows_down_one_slot(
                edition,
                cur,
                page_number,
                line_number - 1,
                profile=profile,
                universe=_all_script_word_ids(edition),
            )
            cloud_saved = _commit_layout_pages(
                edition,
                conn,
                cur,
                shifted['page_from'],
                shifted['page_to'],
                op='header-down-cascade',
            )
            moved = cur.execute(
                '''
                SELECT page_number, line_number
                FROM pages WHERE id = ?
                ''',
                (int(target['id']),),
            ).fetchone()
            return jsonify({
                'ok': True,
                'cloud_saved': cloud_saved,
                'direction': direction,
                'cascaded': True,
                'moved_to_page': int(moved['page_number']),
                'moved_to_line': int(moved['line_number']),
                'crossed_page': (
                    int(moved['page_number']) != int(page_number)
                ),
                'removed_empty_line': shifted['removed_empty_line'],
                'merged_lines': shifted['merged_lines'],
                'page': _build_page_payload(edition, page_number),
                'undo_available': _undo_available(
                    edition, cur, page_number,
                ),
            })

        if direction == 'up':
            neighbor = cur.execute(
                '''
                SELECT id, page_number, line_number, line_type
                FROM pages
                WHERE page_number < ?
                   OR (page_number = ? AND line_number < ?)
                ORDER BY page_number DESC, line_number DESC
                LIMIT 1
                ''',
                (page_number, page_number, line_number),
            ).fetchone()
        else:
            neighbor = cur.execute(
                '''
                SELECT id, page_number, line_number, line_type
                FROM pages
                WHERE page_number > ?
                   OR (page_number = ? AND line_number > ?)
                ORDER BY page_number ASC, line_number ASC
                LIMIT 1
                ''',
                (page_number, page_number, line_number),
            ).fetchone()
        if neighbor is None:
            return jsonify({
                'error': (
                    'لا يوجد سطر سابق لنقل العنوان'
                    if direction == 'up'
                    else 'لا يوجد سطر تالٍ لنقل العنوان'
                ),
            }), 400
        neighbor_page = int(neighbor['page_number'])
        if not _page_in_range(edition, neighbor_page):
            return jsonify({'error': 'cannot move beyond edition pages'}), 400

        page_from = min(page_number, neighbor_page)
        page_to = max(page_number, neighbor_page)
        _push_undo(
            edition, cur, f'header-{direction}',
            page_number, page_from, page_to,
        )

        crossed_page = neighbor_page != page_number
        removed_empty = False
        if not crossed_page:
            # Inside one page, moving one slot is an ordinary adjacent reorder.
            cur.execute(
                'UPDATE pages SET line_number = ? WHERE id = ?',
                (-int(target['id']), int(target['id'])),
            )
            cur.execute(
                'UPDATE pages SET line_number = ? WHERE id = ?',
                (int(target['line_number']), int(neighbor['id'])),
            )
            cur.execute(
                'UPDATE pages SET line_number = ? WHERE id = ?',
                (int(neighbor['line_number']), int(target['id'])),
            )
        else:
            # Across pages, do not exchange the header with the adjacent row.
            # The printed Bahrain layout includes deliberately short pages
            # (548 has 14 rows, while 549 begins name + basmallah). Remove the
            # header from the source page and insert it into the neighboring
            # page's leading/trailing banner in canonical order.
            def page_rows(page):
                return [
                    dict(row) for row in cur.execute(
                        '''
                        SELECT id, page_number, line_number, line_type,
                               is_centered, first_word_id, last_word_id,
                               surah_number, line_text
                        FROM pages
                        WHERE page_number = ?
                        ORDER BY line_number
                        ''',
                        (int(page),),
                    ).fetchall()
                ]

            source_rows = page_rows(page_number)
            destination_rows = page_rows(neighbor_page)
            moving = next(
                row for row in source_rows
                if int(row['id']) == int(target['id'])
            )
            source_rows = [
                row for row in source_rows
                if int(row['id']) != int(target['id'])
            ]
            header_order = {
                'surah_name': 0,
                'surah_info': 1,
                'basmallah': 2,
            }
            moving_order = header_order[moving['line_type']]

            if direction == 'down':
                header_end = 0
                while (
                    header_end < len(destination_rows)
                    and destination_rows[header_end]['line_type']
                    in engine.SURAH_HEADER_TYPES
                ):
                    header_end += 1
                insert_at = header_end
                for index in range(header_end):
                    existing_order = header_order.get(
                        destination_rows[index]['line_type'], 99,
                    )
                    if existing_order > moving_order:
                        insert_at = index
                        break
            else:
                header_start = len(destination_rows)
                while (
                    header_start > 0
                    and destination_rows[header_start - 1]['line_type']
                    in engine.SURAH_HEADER_TYPES
                ):
                    header_start -= 1
                insert_at = len(destination_rows)
                for index in range(header_start, len(destination_rows)):
                    existing_order = header_order.get(
                        destination_rows[index]['line_type'], 99,
                    )
                    if existing_order > moving_order:
                        insert_at = index
                        break
            destination_rows.insert(insert_at, moving)

            profile = _load_profile(edition, cur)
            destination_limit = _page_line_budget(
                edition, profile, neighbor_page,
            )
            if len(destination_rows) > destination_limit:
                empty_indices = [
                    index for index, row in enumerate(destination_rows)
                    if row['line_type'] == 'ayah'
                    and row.get('first_word_id') in (None, '')
                    and row.get('last_word_id') in (None, '')
                ]
                if empty_indices:
                    empty_index = (
                        empty_indices[-1]
                        if direction == 'down'
                        else empty_indices[0]
                    )
                    empty_row = destination_rows.pop(empty_index)
                    cur.execute(
                        'DELETE FROM pages WHERE id = ?',
                        (int(empty_row['id']),),
                    )
                    removed_empty = True

            # Free all old positions before renumbering; Bahrain has a unique
            # (page_number, line_number) index.
            cur.execute(
                '''
                UPDATE pages SET line_number = -id
                WHERE page_number IN (?, ?)
                ''',
                (int(page_number), int(neighbor_page)),
            )
            for new_line, row in enumerate(source_rows, 1):
                cur.execute(
                    '''
                    UPDATE pages SET page_number = ?, line_number = ?
                    WHERE id = ?
                    ''',
                    (int(page_number), new_line, int(row['id'])),
                )
            for new_line, row in enumerate(destination_rows, 1):
                cur.execute(
                    '''
                    UPDATE pages SET page_number = ?, line_number = ?
                    WHERE id = ?
                    ''',
                    (int(neighbor_page), new_line, int(row['id'])),
                )

            # Moving a structural row must not change either physical page's
            # slot budget. Rebalance minimally: split one source ayah row and
            # merge one adjacent destination pair when needed.
            for affected_page in sorted({page_number, neighbor_page}):
                engine.rebalance_page_line_count(
                    cur,
                    affected_page,
                    _page_line_budget(edition, profile, affected_page),
                    script_db=edition.script_db,
                )
        cloud_saved = _commit_layout_pages(
            edition, conn, cur, page_from, page_to, op='header-move',
        )
        moved_page = int(neighbor['page_number'])
        moved_line = (
            int(cur.execute(
                'SELECT line_number FROM pages WHERE id = ?',
                (int(target['id']),),
            ).fetchone()[0])
            if crossed_page
            else int(neighbor['line_number'])
        )
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'direction': direction,
            'moved_to_page': moved_page,
            'moved_to_line': moved_line,
            'crossed_page': crossed_page,
            'removed_empty_line': removed_empty,
            'page': _build_page_payload(edition, page_number),
            'undo_available': _undo_available(edition, cur, page_number),
        })
    except ValueError as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio header-move cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تعديل التخطيط في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(
            'layout-studio header-move failed (%s): %s', edition_id, e,
        )
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/layout-studio/<edition_id>/undo', methods=['POST'])
@require_editor
def layout_studio_undo(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    try:
        page_number = int(body.get('page_number') or 0)
    except (TypeError, ValueError):
        page_number = 0

    conn = _sqlite_connect(_layout_db(edition))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        popped = engine.pop_undo(
            cur, page_number if page_number else None,
            undo_table=edition.undo_table,
        )
        if not popped:
            return jsonify({'error': 'لا يوجد تعديل للتراجع عنه', 'undo_available': 0}), 400
        profile = _load_profile(edition, cur)
        restored_from = popped.get('page_from')
        restored_to = popped.get('page_to')
        if restored_from is None:
            restored_from = popped.get('page_number')
        if restored_to is None:
            restored_to = restored_from
        if restored_from is not None and restored_to is not None:
            for restored_page in range(
                int(restored_from), int(restored_to) + 1,
            ):
                if _page_in_range(edition, restored_page):
                    engine.rebalance_page_line_count(
                        cur,
                        restored_page,
                        _page_line_budget(
                            edition, profile, restored_page,
                        ),
                        script_db=edition.script_db,
                    )
        cloud_saved = _commit_layout_pages(
            edition,
            conn,
            cur,
            int(restored_from),
            int(restored_to),
            audit_action='layout_undo',
            op='undo',
        )

        view_page = page_number or int(popped.get('page_number') or edition.min_page)
        if not _page_in_range(edition, view_page):
            view_page = edition.min_page
        payload = _build_page_payload(edition, view_page)
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'undone': popped.get('label'),
            'page': payload,
            'page_number': view_page,
            'undo_available': _undo_available(edition, cur, view_page),
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio undo cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ التراجع في Supabase'}), 503
    except Exception as e:
        conn.rollback()
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
    conn = _sqlite_connect(_layout_db(edition))
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
@require_editor
def layout_studio_progress(edition_id):
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    table = edition.progress_table
    if not all(c.isalnum() or c == '_' for c in table):
        return jsonify({'error': 'invalid progress table'}), 500

    conn = _sqlite_connect(_layout_db(edition))
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
            if layout_persistence.is_cloud_layout(edition):
                pages = sb.list_reviewed_pages(f'layout:{edition.id}')
            else:
                cur.execute(
                    f'SELECT page_number FROM {table} WHERE reviewed = 1'
                )
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
        cloud_saved = False
        if layout_persistence.is_cloud_layout(edition):
            sb.upsert_progress(
                edition=f'layout:{edition.id}',
                page_number=page_number,
                reviewed=bool(reviewed),
                updated_by=_cloud_actor_id(),
            )
            cloud_saved = True
        conn.commit()
        return jsonify({
            'ok': True,
            'cloud_saved': cloud_saved,
            'page_number': page_number,
            'reviewed': bool(reviewed),
            'edition': edition.id,
        })
    except sb.SupabaseEditorError as e:
        conn.rollback()
        logger.error(
            'layout-studio progress cloud save failed (%s): %s',
            edition_id, e,
        )
        return jsonify({'error': 'تعذّر حفظ تقدم المراجعة في Supabase'}), 503
    except Exception as e:
        conn.rollback()
        logger.error(f'layout-studio progress failed ({edition_id}): {e}')
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route(
    '/api/layout-studio/<edition_id>/import-confidence',
    methods=['GET'],
)
def layout_studio_import_confidence(edition_id):
    """Return the generated seed's review priority without trusting its text."""
    edition, err = _edition_or_404(edition_id)
    if err:
        return err
    conn = _sqlite_connect(_layout_db(edition))
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='layout_import_confidence'"
        ).fetchone()
        if not exists:
            return jsonify({
                'available': False,
                'pages': [],
                'edition': edition.id,
            })
        rows = conn.execute(
            '''
            SELECT page_number, score, status
            FROM layout_import_confidence
            ORDER BY
                CASE status WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                page_number
            '''
        ).fetchall()
        pages = [
            {
                'page_number': int(page),
                'score': float(score),
                'status': status,
            }
            for page, score, status in rows
        ]
        counts = {'high': 0, 'medium': 0, 'low': 0}
        for page in pages:
            status = page['status']
            counts[status] = counts.get(status, 0) + 1
        return jsonify({
            'available': True,
            'pages': pages,
            'counts': counts,
            'edition': edition.id,
        })
    finally:
        conn.close()
