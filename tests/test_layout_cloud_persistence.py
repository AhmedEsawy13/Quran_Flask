from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from core import layout_persistence


def _layout_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            '''
            CREATE TABLE pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number INTEGER NOT NULL,
                line_number INTEGER NOT NULL,
                line_type TEXT NOT NULL,
                is_centered INTEGER NOT NULL DEFAULT 0,
                first_word_id INTEGER,
                last_word_id INTEGER,
                surah_number INTEGER,
                line_text TEXT,
                UNIQUE(page_number, line_number)
            );
            CREATE TABLE test_undo (
                id INTEGER PRIMARY KEY,
                snapshot TEXT NOT NULL
            );
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (10, 1, 'ayah', 0, 100, 102, 2, 'old');
            INSERT INTO test_undo (id, snapshot) VALUES (1, '{}');
            '''
        )


def test_cloud_page_overlay_replaces_baseline_and_invalidates_undo(
    tmp_path, monkeypatch,
):
    path = tmp_path / 'layout.db'
    _layout_db(path)
    edition = SimpleNamespace(
        id='bahrain',
        layout_db=str(path),
        undo_table='test_undo',
    )
    remote = [{
        'edition': 'bahrain',
        'page_number': 10,
        'updated_at': '2026-07-28T10:00:00Z',
        'updated_by': None,
        'lines': [{
            'line_number': 1,
            'line_type': 'ayah',
            'is_centered': 1,
            'first_word_id': 100,
            'last_word_id': 101,
            'surah_number': 2,
            'line_text': 'cloud',
        }, {
            'line_number': 2,
            'line_type': 'ayah',
            'is_centered': 0,
            'first_word_id': 102,
            'last_word_id': 102,
            'surah_number': 2,
            'line_text': 'second',
        }],
    }]

    monkeypatch.setattr(layout_persistence.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_page_index',
        lambda **_kwargs: [
            {
                'page_number': row['page_number'],
                'updated_at': row['updated_at'],
            }
            for row in remote
        ],
    )
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_pages',
        lambda **_kwargs: remote,
    )
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_profile',
        lambda **_kwargs: None,
    )
    layout_persistence.reset_runtime_state()

    assert layout_persistence.working_db_path(edition) == str(path)
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            '''
            SELECT line_number, is_centered, first_word_id, last_word_id,
                   line_text
            FROM pages WHERE page_number = 10 ORDER BY line_number
            '''
        ).fetchall()
        undo_count = conn.execute('SELECT COUNT(*) FROM test_undo').fetchone()[0]
    assert rows == [
        (1, 1, 100, 101, 'cloud'),
        (2, 0, 102, 102, 'second'),
    ]
    assert undo_count == 0


def test_matching_cloud_snapshot_does_not_rewrite_sqlite_rows(
    tmp_path, monkeypatch,
):
    path = tmp_path / 'layout.db'
    _layout_db(path)
    edition = SimpleNamespace(
        id='bahrain',
        layout_db=str(path),
        undo_table='test_undo',
    )
    remote = [{
        'edition': 'bahrain',
        'page_number': 10,
        'updated_at': '2026-07-28T10:00:00Z',
        'lines': [{
            'line_number': 1,
            'line_type': 'ayah',
            'is_centered': 0,
            'first_word_id': 100,
            'last_word_id': 102,
            'surah_number': 2,
            'line_text': 'old',
        }],
    }]
    monkeypatch.setattr(layout_persistence.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_page_index',
        lambda **_kwargs: [{
            'page_number': 10,
            'updated_at': remote[0]['updated_at'],
        }],
    )
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_pages',
        lambda **_kwargs: remote,
    )
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_profile',
        lambda **_kwargs: None,
    )
    layout_persistence.reset_runtime_state()

    layout_persistence.working_db_path(edition)
    with sqlite3.connect(path) as conn:
        row_id = conn.execute(
            'SELECT id FROM pages WHERE page_number = 10'
        ).fetchone()[0]
        undo_count = conn.execute('SELECT COUNT(*) FROM test_undo').fetchone()[0]
    assert row_id == 1
    assert undo_count == 1


def test_save_pages_uploads_complete_affected_page(tmp_path, monkeypatch):
    path = tmp_path / 'layout.db'
    _layout_db(path)
    edition = SimpleNamespace(
        id='bahrain',
        layout_db=str(path),
        undo_table='test_undo',
    )
    captured = {}
    cloud_rows = []

    monkeypatch.setattr(layout_persistence.sb, 'is_configured', lambda: True)

    def upsert(**kwargs):
        captured.update(kwargs)
        cloud_rows[:] = [
            {
                'edition': kwargs['edition'],
                'page_number': page['page_number'],
                'lines': page['lines'],
                'updated_at': '2026-07-28T11:00:00Z',
                'updated_by': kwargs['updated_by'],
            }
            for page in kwargs['pages']
        ]
        return cloud_rows

    monkeypatch.setattr(layout_persistence.sb, 'upsert_layout_pages', upsert)
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_page_index',
        lambda **_kwargs: [
            {
                'page_number': row['page_number'],
                'updated_at': row['updated_at'],
            }
            for row in cloud_rows
        ],
    )
    monkeypatch.setattr(
        layout_persistence.sb, 'fetch_layout_pages',
        lambda **_kwargs: list(cloud_rows),
    )
    layout_persistence.reset_runtime_state()

    with sqlite3.connect(path) as conn:
        conn.execute(
            'UPDATE pages SET last_word_id = 101, line_text = ? '
            'WHERE page_number = 10 AND line_number = 1',
            ('edited',),
        )
        saved = layout_persistence.save_pages(
            edition,
            conn.cursor(),
            page_from=10,
            page_to=10,
            updated_by='editor-1',
        )

    assert saved is True
    assert captured['edition'] == 'bahrain'
    assert captured['updated_by'] == 'editor-1'
    assert [page['page_number'] for page in captured['pages']] == [10]
    assert captured['pages'][0]['lines'][0]['line_text'] == 'edited'
    assert captured['pages'][0]['lines'][0]['last_word_id'] == 101


def test_layout_schema_is_service_role_only():
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / 'pipeline'
        / 'supabase_layout_schema.sql'
    ).read_text(encoding='utf-8').lower()
    assert 'create table if not exists public.editor_layout_pages' in sql
    assert 'primary key (edition, page_number)' in sql
    assert 'enable row level security' in sql
    assert 'no anon/authenticated policies' in sql
