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

CLOUD_LAYOUT_EDITIONS = frozenset({'bahrain'})
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
    return edition.id in CLOUD_LAYOUT_EDITIONS and sb.is_configured()


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


def _page_payload(cur, page_number: int) -> dict[str, Any]:
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
    return {'page_number': int(page_number), 'lines': lines}


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
        _page_payload(cur, page)
        for page in range(int(page_from), end + 1)
    ]
    empty = [page['page_number'] for page in pages if not page['lines']]
    if empty:
        raise sb.SupabaseEditorError(
            f'Cannot save empty layout page(s): {empty}'
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
