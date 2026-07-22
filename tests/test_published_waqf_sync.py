"""Published Supabase → versioned SQLite synchronization safety."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pipeline.sync_published_waqf import (
    SyncError,
    apply_plan,
    build_plan,
    finalize_plan,
    load_local_state,
    research_subprocess_env,
    render_markdown,
)


WORDS = {
    (1, 1): [
        {'word_id': 1, 'text': 'أَلِف'},
        {'word_id': 2, 'text': 'بَاء'},
        {'word_id': 3, 'text': 'جِيم'},
    ],
}


def word_provider(surah: int, ayah: int) -> list[dict]:
    return [dict(row) for row in WORDS.get((surah, ayah), [])]


@pytest.fixture
def sync_db(tmp_path):
    path = tmp_path / 'mushaf_waqf.db'
    conn = sqlite3.connect(path)
    conn.executescript(
        '''
        CREATE TABLE waqf (
            السورة INTEGER NOT NULL,
            الآية INTEGER NOT NULL,
            الكلمة TEXT,
            token_index INTEGER,
            word_index INTEGER,
            "قطر" TEXT,
            "الكويت" TEXT,
            UNIQUE(السورة, الآية, token_index)
        );
        INSERT INTO waqf VALUES (1, 1, 'أَلِف', 1, 1, 'م', NULL);
        INSERT INTO waqf VALUES (1, 1, 'بَاء', 2, 2, 'ص', 'ج');
        '''
    )
    conn.commit()
    conn.close()
    return path


def cloud_snapshot():
    return [
        {
            'edition': 'قطر', 'surah': 1, 'ayah': 1, 'token_index': 0,
            'symbol': 'ق', 'word_text': 'أَلِف',
            'updated_at': '2026-07-22T12:00:00Z',
        },
        {
            'edition': 'قطر', 'surah': 1, 'ayah': 1, 'token_index': 2,
            'symbol': 'س', 'word_text': 'جِيم',
            'updated_at': '2026-07-22T12:01:00Z',
        },
        {
            'edition': 'الكويت', 'surah': 1, 'ayah': 1, 'token_index': 1,
            'symbol': 'ج', 'word_text': 'بَاء',
            'updated_at': '2026-07-22T12:02:00Z',
        },
    ]


def make_plan(sync_db, rows=None):
    return build_plan(
        database=sync_db,
        cloud_rows=cloud_snapshot() if rows is None else rows,
        editions=['قطر', 'الكويت'],
        source='test-supabase',
        word_provider=word_provider,
    )


def test_plan_reports_add_update_delete_and_unchanged(sync_db):
    plan = make_plan(sync_db)
    assert plan['valid'] is True
    assert plan['summary']['قطر'] == {
        'local_marks': 2,
        'cloud_marks': 2,
        'cloud_coverage': 1.0,
        'add': 1,
        'update': 1,
        'delete': 1,
        'unchanged': 0,
    }
    assert plan['summary']['الكويت']['unchanged'] == 1
    assert {row['action'] for row in plan['changes']} == {'add', 'update', 'delete'}
    report = render_markdown(plan)
    assert 'PASS — safe to apply' in report
    assert '| ADD | قطر | 1:1 | 3 |' in report
    assert '| DELETE | قطر | 1:1 | 2 |' in report


def test_apply_is_atomic_and_matches_cloud_snapshot(sync_db):
    plan = make_plan(sync_db)
    result = apply_plan(
        plan, database=sync_db, word_provider=word_provider, backup=False,
    )
    assert result['changes_applied'] == 3

    state = load_local_state(
        sync_db, ['قطر', 'الكويت'], word_provider=word_provider,
    )
    qatar = state['marks']['قطر']
    assert qatar[(1, 1, 0)]['symbol'] == 'ق'
    assert (1, 1, 1) not in qatar
    assert qatar[(1, 1, 2)]['symbol'] == 'س'
    assert state['marks']['الكويت'][(1, 1, 1)]['symbol'] == 'ج'

    second_plan = make_plan(sync_db)
    assert second_plan['valid'] is True
    assert second_plan['changes'] == []


def test_plan_blocks_word_mismatch_and_incomplete_snapshot(sync_db):
    bad_word = cloud_snapshot()
    bad_word[0] = {**bad_word[0], 'word_text': 'كَلِمَة أُخْرَى'}
    mismatch = make_plan(sync_db, bad_word)
    assert mismatch['valid'] is False
    assert any('word mismatch' in error for error in mismatch['validation']['errors'])

    incomplete = make_plan(sync_db, [])
    assert incomplete['valid'] is False
    assert any('safety floor' in error for error in incomplete['validation']['errors'])


def test_apply_rejects_tampered_or_stale_plan(sync_db):
    plan = make_plan(sync_db)
    plan['changes'][0]['new_symbol'] = 'ع'
    with pytest.raises(SyncError, match='digest mismatch'):
        apply_plan(plan, database=sync_db, word_provider=word_provider, backup=False)

    plan = make_plan(sync_db)
    conn = sqlite3.connect(sync_db)
    conn.execute('UPDATE waqf SET "قطر" = "ج" WHERE word_index = 1')
    conn.commit()
    conn.close()
    with pytest.raises(SyncError, match='changed after planning'):
        apply_plan(plan, database=sync_db, word_provider=word_provider, backup=False)


def test_apply_rolls_back_every_change_on_failure(sync_db):
    plan = make_plan(sync_db)
    plan['changes'][1]['edition'] = 'غير مدعوم'
    finalize_plan(plan)

    with pytest.raises(SyncError, match='unsupported edition'):
        apply_plan(plan, database=sync_db, word_provider=word_provider, backup=False)

    conn = sqlite3.connect(sync_db)
    try:
        marks = conn.execute(
            'SELECT word_index, "قطر" FROM waqf ORDER BY word_index'
        ).fetchall()
    finally:
        conn.close()
    assert marks == [(1, 'م'), (2, 'ص')]


def test_research_rebuild_cannot_read_cloud(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'secret')
    monkeypatch.setenv('KEEP_ME', 'yes')
    env = research_subprocess_env()
    assert 'SUPABASE_URL' not in env
    assert 'SUPABASE_SERVICE_ROLE_KEY' not in env
    assert env['KEEP_ME'] == 'yes'


def test_sync_workflow_is_review_only_and_never_pushes_main():
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / '.github' / 'workflows' / 'propose-published-waqf-sync.yml'
    ).read_text(encoding='utf-8')

    assert 'schedule:' in workflow
    assert 'workflow_dispatch:' in workflow
    assert 'SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}' in workflow
    assert workflow.count('SUPABASE_SERVICE_ROLE_KEY:') == 1
    assert '--apply "$RUNNER_TEMP/published-waqf-sync/plan.json"' in workflow
    assert 'python3 -m pytest -q' in workflow
    assert 'uses: actions/upload-artifact@v4' in workflow
    assert 'branch="automation/published-waqf-sync"' in workflow
    assert 'gh pr create' in workflow
    assert 'HEAD:refs/heads/$branch' in workflow
    assert 'git push origin main' not in workflow
