"""Rows whose ruling holds only under a reading other than Hafs's are marked
(pipeline/review/reading_side.json → classical.reading = 'other') and the API
returns the mark, so the app can label them «على غير قراءة حفص»."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'classical_waqf.db'
sys.path.insert(0, str(ROOT / 'pipeline'))
import audit_reading_side  # noqa: E402


def marked():
    con = sqlite3.connect(DB)
    try:
        return {(s, i) for s, i in con.execute("SELECT source, id FROM classical WHERE reading='other'")}
    finally:
        con.close()


def test_every_listed_row_is_marked_and_nothing_else():
    assert marked() == audit_reading_side.other_ids()


def test_listed_rows_carry_a_reading_condition():
    con = sqlite3.connect(DB)
    try:
        notes = [n or '' for (n,) in con.execute("SELECT note FROM classical WHERE reading='other'")]
    finally:
        con.close()
    assert notes and all(any(w in n for w in ('قرأ', 'قراءة', 'قرئ', 'القراء')) for n in notes)


def test_both_sides_spot_checks():
    rows = marked()
    assert ('muktafa', 175) in rows          # 2:119 «ولا تسأل» بالجزم — Hafs «ولا تُسْـَٔلُ»
    assert ('manar', 51026) in rows          # 10:5 «نفصل» بالنون — Hafs «يُفَصِّلُ»
    assert ('manar', 48200) not in rows      # 3:114 «بالتحتية فيهما» is Hafs's «يفعلوا … يكفروه»
    assert ('manar', 59215) not in rows      # 73:8 «ربُّ» بالرفع is Hafs's «رَّبُّ ٱلۡمَشۡرِقِ»
    data = json.load(open(ROOT / 'pipeline' / 'review' / 'reading_side.json', encoding='utf-8'))
    assert sum(len(v) for v in data['other'].values()) == len(rows)


def test_api_returns_the_reading_mark(client):
    payload = client.get('/api/classical-waqf/2/119').get_json()
    other = [e for e in payload['entries'] if e.get('reading') == 'other']
    assert other and all(e['source'] in ('muktafa', 'manar') for e in other)
    assert all('reading' in e for e in payload['entries'])
