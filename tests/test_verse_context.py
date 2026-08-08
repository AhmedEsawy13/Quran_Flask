"""Tests for Bahouth-derived contiguous thematic context in تثبيت."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pipeline.harvest_bahouth_topics import contiguous_run, score_span
from modules import memorize as memorize_mod


def test_score_span_prefers_same_surah_mid_length_runs():
    mid = score_span(
        length=5,
        verse_surah=2,
        start_surah=2,
        end_surah=2,
        title='الفاحشة والزنى:في المال:الربا',
    )
    single = score_span(
        length=1,
        verse_surah=2,
        start_surah=2,
        end_surah=2,
        title='الفاحشة والزنى:في المال:الربا',
    )
    cross = score_span(
        length=40,
        verse_surah=74,
        start_surah=74,
        end_surah=75,
        title='توحيد الله تعالى:الوعد والوعيد',
    )
    assert mid > single
    assert mid > cross


def test_contiguous_run_finds_maximal_block():
    id_to_sa = {
        10: (2, 10),
        11: (2, 11),
        12: (2, 12),
        20: (2, 20),
    }
    run = contiguous_run([10, 11, 12, 20], 11, id_to_sa)
    assert run == {
        'start_surah': 2,
        'start_ayah': 10,
        'end_surah': 2,
        'end_ayah': 12,
        'run_length': 3,
    }


def test_memorization_context_api_reads_local_db(client, tmp_path, monkeypatch):
    db = tmp_path / 'verse_topics.db'
    conn = sqlite3.connect(db)
    conn.executescript(
        '''
        CREATE TABLE context_spans (
            surah INTEGER NOT NULL,
            ayah INTEGER NOT NULL,
            topic_id INTEGER,
            title_raw TEXT NOT NULL,
            start_surah INTEGER NOT NULL,
            start_ayah INTEGER NOT NULL,
            end_surah INTEGER NOT NULL,
            end_ayah INTEGER NOT NULL,
            run_length INTEGER NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (surah, ayah)
        );
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        '''
    )
    conn.execute(
        '''
        INSERT INTO context_spans VALUES (2, 255, 465, 'أسماء الله الحسنى',
                                          2, 255, 2, 257, 3, 35.0)
        '''
    )
    conn.execute(
        "INSERT INTO metadata VALUES ('attribution', 'باحوث · مركز تفسير للدراسات القرآنية')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(memorize_mod, 'VERSE_TOPICS_DATABASE', str(db))

    missing = client.get('/api/memorization/context/2/254')
    assert missing.status_code == 404
    assert missing.get_json()['found'] is False

    ok = client.get('/api/memorization/context/2/255')
    assert ok.status_code == 200
    payload = ok.get_json()
    assert payload['found'] is True
    assert payload['from'] == {'surah': 2, 'ayah': 255}
    assert payload['to'] == {'surah': 2, 'ayah': 257}
    assert payload['run_length'] == 3
    assert payload['same_surah'] is True
    assert 'أسماء الله' in payload['title']
    assert 'باحوث' in payload['attribution']


def test_memorize_page_exposes_context_chip(client):
    page = client.get('/memorize').get_data(as_text=True)
    assert 'id="mz-context"' in page
    assert 'id="mz-tb-context"' in page
    assert 'وسّع للنطاق' in page
    js = client.get('/static/js/mushaf_memorize.js').get_data(as_text=True)
    assert '/api/memorization/context/' in js
    assert 'expandToContextSpan' in js


def test_live_verse_topics_db_has_yusuf_and_khidr_spans():
    """Regression against the harvested Bahouth DB when present in the checkout."""
    from core.config import VERSE_TOPICS_DATABASE

    if not Path(VERSE_TOPICS_DATABASE).is_file():
        return
    conn = sqlite3.connect(f'file:{VERSE_TOPICS_DATABASE}?mode=ro', uri=True)
    try:
        yusuf = conn.execute(
            'SELECT start_ayah, end_ayah, run_length, title_raw '
            'FROM context_spans WHERE surah=12 AND ayah=4'
        ).fetchone()
        khidr = conn.execute(
            'SELECT start_ayah, end_ayah, run_length, title_raw '
            'FROM context_spans WHERE surah=18 AND ayah=60'
        ).fetchone()
    finally:
        conn.close()
    assert yusuf is not None
    assert yusuf[2] >= 2
    assert yusuf[0] <= 4 <= yusuf[1]
    assert 'يوسف' in yusuf[3]
    assert khidr is not None
    assert khidr[0] == 60 and khidr[1] == 82
    assert khidr[2] == 23
