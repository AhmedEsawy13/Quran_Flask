"""Durable cloud persistence for Layout Studio working databases.

The repository SQLite file is the baseline. Supabase stores complete snapshots
only for pages that have been edited, and those snapshots are overlaid onto the
working database before reads or writes. Serverless deployments use a writable
copy under /tmp; local development keeps the existing editable SQLite workflow.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

from core import supabase_editor as sb
from core.loader import IS_SERVERLESS

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_applied_pages: dict[str, str] = {}
_applied_profiles: dict[str, str] = {}

_LINE_COLUMNS = (
    'line_number',
    'line_type',
    'is_centered',
    'first_word_id',
    'last_word_id',
    'surah_number',
    'line_text',
)


def is_cloud_layout(edition) -> bool:
    # ``bahrain`` fallback keeps lightweight test/legacy edition objects
    # working; registered LayoutEdition instances declare this explicitly.
    enabled = getattr(
        edition, 'cloud_enabled', getattr(edition, 'id', '') == 'bahrain',
    )
    return bool(enabled) and sb.is_configured()


def _runtime_copy(base_path: str) -> str:
    base = Path(base_path)
    stat = base.stat()
    name = (
        f'athar-{base.stem}-{stat.st_size}-{stat.st_mtime_ns}'
        f'{base.suffix}'
    )
    target = Path(tempfile.gettempdir()) / name
    if not target.exists():
        shutil.copy2(base, target)
    return str(target)


def _working_path(edition) -> str:
    return _runtime_copy(edition.layout_db) if IS_SERVERLESS else edition.layout_db


def _pages_signature(rows: list[dict]) -> str:
    return json.dumps(
        [
            (
                int(row['page_number']),
                row.get('updated_at') or '',
            )
            for row in sorted(rows, key=lambda item: int(item['page_number']))
        ],
        ensure_ascii=True,
        separators=(',', ':'),
    )


def _profile_signature(row: dict | None) -> str:
    if not row:
        return ''
    return json.dumps(
        {
            'updated_at': row.get('updated_at') or '',
            'profile': row.get('profile') or {},
        },
        sort_keys=True,
        ensure_ascii=True,
        separators=(',', ':'),
    )


def _replace_page(cur, page_number: int, lines: list[dict]) -> None:
    cur.execute('DELETE FROM pages WHERE page_number = ?', (int(page_number),))
    cur.executemany(
        '''
        INSERT INTO pages (
            page_number, line_number, line_type, is_centered,
            first_word_id, last_word_id, surah_number, line_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        [
            (
                int(page_number),
                int(line.get('line_number') or index),
                line['line_type'],
                1 if line.get('is_centered') else 0,
                line.get('first_word_id'),
                line.get('last_word_id'),
                line.get('surah_number'),
                line.get('line_text') or '',
            )
            for index, line in enumerate(lines, 1)
        ],
    )


def _page_matches(cur, page_number: int, lines: list[dict]) -> bool:
    current = cur.execute(
        f'''
        SELECT {", ".join(_LINE_COLUMNS)}
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number
        ''',
        (int(page_number),),
    ).fetchall()
    expected = [
        (
            int(line.get('line_number') or index),
            line['line_type'],
            1 if line.get('is_centered') else 0,
            line.get('first_word_id'),
            line.get('last_word_id'),
            line.get('surah_number'),
            line.get('line_text') or '',
        )
        for index, line in enumerate(lines, 1)
    ]
    return current == expected


def _validate_page_word_space(edition, page_number: int, lines: list[dict]) -> None:
    """Reject cloud rows whose endpoints do not belong to this edition's DB.

    Numeric overlap between ID spaces is common, so membership alone is not
    enough. Ayah rows must also resolve to their declared surah in the
    edition's own script database and progress forward in its reading order.
    """
    script_db = getattr(edition, 'script_db', None)
    word_id_space = getattr(edition, 'word_id_space', None)
    if not script_db or not word_id_space:
        return

    from modules import layout_engine

    word_map = layout_engine.script_word_map(script_db)
    positions = word_map['position_by_id']
    id2tok = word_map['id2tok']
    for line in lines:
        if line.get('line_type') != 'ayah':
            continue
        first = line.get('first_word_id')
        last = line.get('last_word_id')
        if first is None and last is None:
            continue
        try:
            first = int(first)
            last = int(last)
        except (TypeError, ValueError) as exc:
            raise sb.SupabaseEditorError(
                f'Invalid word IDs for {edition.id} page {page_number}'
            ) from exc
        lo = positions.get(first)
        hi = positions.get(last)
        if lo is None or hi is None or hi < lo:
            raise sb.SupabaseEditorError(
                f'Word IDs outside {word_id_space} for '
                f'{edition.id} page {page_number}'
            )
        declared_surah = line.get('surah_number')
        if declared_surah is None:
            continue
        actual_surahs = {
            int(id2tok[word_id]['surah'])
            for word_id in word_map['ordered_ids'][lo:hi + 1]
        }
        if actual_surahs != {int(declared_surah)}:
            raise sb.SupabaseEditorError(
                f'Word-ID namespace mismatch for {edition.id} page '
                f'{page_number}: declared surah {declared_surah}, '
                f'resolved {sorted(actual_surahs)}'
            )


def _cloud_lines_with_word_keys(
    edition,
    page_number: int,
    lines: list[dict],
) -> list[dict]:
    """Attach portable endpoint keys to a page before cloud persistence."""
    script_db = getattr(edition, 'script_db', None)
    word_id_space = getattr(edition, 'word_id_space', None)
    if not script_db or not word_id_space:
        return [dict(line) for line in lines]

    from modules import layout_engine

    word_map = layout_engine.script_word_map(script_db)
    annotated = []
    for source in lines:
        line = dict(source)
        first = line.get('first_word_id')
        last = line.get('last_word_id')
        if first is None and last is None:
            annotated.append(line)
            continue
        first_token = word_map['id2tok'].get(int(first)) if first is not None else None
        last_token = word_map['id2tok'].get(int(last)) if last is not None else None
        if first_token is None or last_token is None:
            if line.get('line_type') == 'ayah':
                raise sb.SupabaseEditorError(
                    f'Cannot create canonical word keys for '
                    f'{edition.id} page {page_number}'
                )
            annotated.append(line)
            continue
        line['word_id_space'] = word_id_space
        line['first_word_key'] = first_token['word_key']
        line['last_word_key'] = last_token['word_key']
        annotated.append(line)
    return annotated


def _normalize_cloud_word_keys(
    edition,
    page_number: int,
    lines: list[dict],
) -> list[dict]:
    """Validate or translate cloud endpoints into the edition's local IDs."""
    script_db = getattr(edition, 'script_db', None)
    target_space = getattr(edition, 'word_id_space', None)
    if not script_db or not target_space:
        return [dict(line) for line in lines]

    from modules import layout_engine

    word_map = layout_engine.script_word_map(script_db)
    normalized = []
    for source in lines:
        line = dict(source)
        if line.get('line_type') != 'ayah':
            normalized.append(line)
            continue
        declared_space = str(line.get('word_id_space') or '').strip()
        first_key = str(line.get('first_word_key') or '').strip()
        last_key = str(line.get('last_word_key') or '').strip()
        if bool(first_key) != bool(last_key):
            raise sb.SupabaseEditorError(
                f'Incomplete canonical endpoints for '
                f'{edition.id} page {page_number}'
            )
        keys_present = bool(first_key and last_key)
        if declared_space and not keys_present:
            raise sb.SupabaseEditorError(
                f'Cannot use declared word space {declared_space} for '
                f'{edition.id} page {page_number}: canonical keys missing'
            )

        if declared_space and declared_space != target_space:
            first = word_map['key_to_id'].get(first_key)
            last = word_map['key_to_id'].get(last_key)
            if first is None or last is None:
                raise sb.SupabaseEditorError(
                    f'Canonical word key unavailable in {target_space} for '
                    f'{edition.id} page {page_number}'
                )
            line['first_word_id'] = int(first)
            line['last_word_id'] = int(last)
            line['word_id_space'] = target_space
        elif keys_present:
            expected_first = word_map['key_to_id'].get(first_key)
            expected_last = word_map['key_to_id'].get(last_key)
            try:
                actual = (
                    int(line.get('first_word_id')),
                    int(line.get('last_word_id')),
                )
            except (TypeError, ValueError) as exc:
                raise sb.SupabaseEditorError(
                    f'Invalid canonical endpoints for '
                    f'{edition.id} page {page_number}'
                ) from exc
            if (
                expected_first is None
                or expected_last is None
                or actual != (int(expected_first), int(expected_last))
            ):
                raise sb.SupabaseEditorError(
                    f'Canonical key/ID mismatch for '
                    f'{edition.id} page {page_number}'
                )
            line['word_id_space'] = target_space
        normalized.append(line)

    _validate_page_word_space(edition, page_number, normalized)
    return normalized


def _apply_profile(cur, profile: dict) -> None:
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS layout_studio_profile (
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
        '''
        INSERT INTO layout_studio_profile (
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
            int(profile['lines_per_page']),
            str(profile['page_end_mode']),
            int(profile['surah_name_lines']),
            int(profile['surah_info_lines']),
            int(profile['basmallah_lines']),
        ),
    )


def working_db_path(edition, *, force: bool = False) -> str:
    """Return a writable, cloud-hydrated Layout Studio database path."""
    if not is_cloud_layout(edition):
        return edition.layout_db

    path = _working_path(edition)
    try:
        cloud_index = sb.fetch_layout_page_index(
            edition=edition.id, force=force,
        )
        cloud_profile = sb.fetch_layout_profile(
            edition=edition.id, force=force,
        )
    except sb.SupabaseEditorError as exc:
        # Reads remain available from the last synchronized working copy.
        # Mutations still fail during their mandatory cloud save.
        logger.warning(
            'Layout cloud refresh failed for %s; using working copy: %s',
            edition.id, exc,
        )
        return path

    page_signature = _pages_signature(cloud_index)
    profile_signature = _profile_signature(cloud_profile)
    with _lock:
        pages_changed = _applied_pages.get(path) != page_signature
        profile_changed = _applied_profiles.get(path) != profile_signature
        if not pages_changed and not profile_changed:
            return path

        conn = sqlite3.connect(path)
        try:
            cur = conn.cursor()
            if pages_changed:
                cloud_pages = sb.fetch_layout_pages(
                    edition=edition.id, force=True,
                )
                database_changed = False
                for row in cloud_pages:
                    lines = row.get('lines')
                    if not isinstance(lines, list) or not lines:
                        logger.warning(
                            'Ignoring empty cloud layout page %s:%s',
                            edition.id, row.get('page_number'),
                        )
                        continue
                    lines = _normalize_cloud_word_keys(
                        edition, int(row['page_number']), lines,
                    )
                    if _page_matches(cur, int(row['page_number']), lines):
                        continue
                    _replace_page(cur, int(row['page_number']), lines)
                    database_changed = True
                # Undo IDs are process-local. Once an outside cloud revision is
                # applied, old snapshots may reference rows that no longer exist.
                table = edition.undo_table
                if (
                    database_changed
                    and table
                    and all(c.isalnum() or c == '_' for c in table)
                ):
                    cur.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                    if cur.fetchone():
                        cur.execute(f'DELETE FROM {table}')
            if profile_changed and cloud_profile:
                profile = cloud_profile.get('profile')
                if isinstance(profile, dict):
                    _apply_profile(cur, profile)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _applied_pages[path] = page_signature
        _applied_profiles[path] = profile_signature
    return path


def _page_payload(edition, cur, page_number: int) -> dict[str, Any]:
    rows = cur.execute(
        f'''
        SELECT {", ".join(_LINE_COLUMNS)}
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number
        ''',
        (int(page_number),),
    ).fetchall()
    lines = [
        {
            column: (
                int(value)
                if column in {'line_number', 'is_centered'} and value is not None
                else value
            )
            for column, value in zip(_LINE_COLUMNS, row)
        }
        for row in rows
    ]
    return {
        'page_number': int(page_number),
        'lines': _cloud_lines_with_word_keys(
            edition, int(page_number), lines,
        ),
    }


_LAYOUT_OP_AR = {
    'line-break': 'كسر سطر',
    'merge-line': 'دمج سطر',
    'pull-next-word': 'سحب كلمة',
    'push-last-word': 'دفع كلمة',
    'transfer-line': 'ترحيل سطر',
    'line-center': 'توسيط سطر',
    'header-move': 'نقل عنوان',
    'header-down-cascade': 'خفض عنوان',
    'undo': 'تراجع',
}


def _ayah_endpoint_rows(lines: list[dict] | None) -> list[tuple]:
    rows = []
    for line in lines or []:
        if (line.get('line_type') or '') != 'ayah':
            continue
        first = line.get('first_word_key')
        last = line.get('last_word_key')
        if first is None and last is None:
            first = line.get('first_word_id')
            last = line.get('last_word_id')
        rows.append((
            int(line.get('line_number') or 0),
            str(first) if first is not None else '',
            str(last) if last is not None else '',
        ))
    return rows


def build_layout_audit_meta(
    pages: list[dict],
    *,
    before_by_page: dict[int, list] | None = None,
    op: str | None = None,
) -> dict[str, Any]:
    """Compact forensics for one layout cloud save (Option 1 history)."""
    before_by_page = before_by_page or {}
    page_summaries = []
    changed_lines = 0
    first_key = None
    last_key = None
    ayah_line_count = 0

    for page in pages:
        pn = int(page['page_number'])
        lines = list(page.get('lines') or [])
        after_rows = _ayah_endpoint_rows(lines)
        before_rows = _ayah_endpoint_rows(before_by_page.get(pn))
        ayah_line_count += len(after_rows)
        if after_rows:
            if first_key is None:
                first_key = after_rows[0][1] or None
            last_key = after_rows[-1][2] or after_rows[-1][1] or last_key
        before_map = {ln: (fk, lk) for ln, fk, lk in before_rows}
        after_map = {ln: (fk, lk) for ln, fk, lk in after_rows}
        page_changed = []
        for ln in sorted(set(before_map) | set(after_map)):
            old = before_map.get(ln)
            new = after_map.get(ln)
            if old == new:
                continue
            changed_lines += 1
            page_changed.append({
                'line': ln,
                'before': (
                    {'first': old[0], 'last': old[1]} if old else None
                ),
                'after': (
                    {'first': new[0], 'last': new[1]} if new else None
                ),
            })
        page_summaries.append({
            'page': pn,
            'ayah_lines': len(after_rows),
            'first_key': after_rows[0][1] if after_rows else None,
            'last_key': after_rows[-1][2] if after_rows else None,
            'changed': page_changed[:12],
        })

    page_from = int(pages[0]['page_number']) if pages else None
    page_to = int(pages[-1]['page_number']) if pages else page_from
    bits = []
    if op:
        bits.append(_LAYOUT_OP_AR.get(op, op))
    if page_from is not None:
        if page_to != page_from:
            bits.append(f'ص {page_from}–{page_to}')
        else:
            bits.append(f'ص {page_from}')
    bits.append(f'{ayah_line_count} سطر آية')
    if changed_lines:
        bits.append(f'تغيّر {changed_lines} سطر')
    elif before_by_page:
        bits.append('بلا فرق ظاهري في الحدود')
    if first_key and last_key:
        bits.append(f'{first_key} ← {last_key}')

    return {
        'page_from': page_from,
        'page_to': page_to,
        'op': op,
        'line_count': ayah_line_count,
        'first_key': first_key,
        'last_key': last_key,
        'changed_lines': changed_lines,
        'change_summary': ' · '.join(bits),
        'pages': page_summaries,
    }


def audit_meta_for_pages(
    edition,
    cur,
    page_from: int,
    page_to: int | None = None,
    *,
    before_by_page: dict[int, list] | None = None,
    op: str | None = None,
) -> dict[str, Any]:
    end = int(page_to) if page_to is not None else int(page_from)
    pages = [
        _page_payload(edition, cur, page)
        for page in range(int(page_from), end + 1)
    ]
    return build_layout_audit_meta(
        pages, before_by_page=before_by_page, op=op,
    )


def save_pages(
    edition,
    cur,
    *,
    page_from: int,
    page_to: int | None = None,
    updated_by: str | None,
) -> bool:
    """Save the current SQLite transaction's affected pages to Supabase."""
    if not is_cloud_layout(edition):
        return False
    end = int(page_to) if page_to is not None else int(page_from)
    pages = [
        _page_payload(edition, cur, page)
        for page in range(int(page_from), end + 1)
    ]
    empty = [page['page_number'] for page in pages if not page['lines']]
    if empty:
        raise sb.SupabaseEditorError(
            f'Cannot save empty layout page(s): {empty}'
        )
    for page in pages:
        _validate_page_word_space(
            edition, page['page_number'], page['lines'],
        )
    sb.upsert_layout_pages(
        edition=edition.id,
        pages=pages,
        updated_by=updated_by,
    )
    # The local transaction already contains this exact state. Mark the current
    # cache signature as applied so response rendering does not rewrite it and
    # erase the undo entry created by this operation.
    cached = sb.fetch_layout_page_index(edition=edition.id)
    with _lock:
        _applied_pages[_working_path(edition)] = _pages_signature(cached)
    return True


def save_profile(
    edition,
    profile: dict,
    *,
    updated_by: str | None,
) -> bool:
    if not is_cloud_layout(edition):
        return False
    row = sb.upsert_layout_profile(
        edition=edition.id,
        profile=profile,
        updated_by=updated_by,
    )
    with _lock:
        _applied_profiles[_working_path(edition)] = _profile_signature(row)
    return True


def reset_runtime_state() -> None:
    """Test/helper hook; does not delete local or cloud data."""
    with _lock:
        _applied_pages.clear()
        _applied_profiles.clear()
