"""Read path for contemporary توجيه (د. أحمد صابر عبدالهادي).

Not a classical book. Production reads `public.tawjih` via the service_role
key. `data/tawjih.db` is an optional sqlite fallback for tests only.
"""
from __future__ import annotations

import logging
import os
import sqlite3

from core.config import TAWJIH_DATABASE
from core.datasets import qpc_hafs_data_normalized
from core.db import connect as _sqlite_connect
from core.memorization import _has_arabic_letter
from core import supabase_editor as sb

logger = logging.getLogger(__name__)

TAWJIH_SOURCE = {
    'name': 'توجيه',
    'title': 'توجيه معاصر',
    'author': 'د. أحمد صابر عبدالهادي',
    'url': 'https://x.com/Dr_ahmed21',
}

_POST_SELECT = 'tweet_id,url,posted_at'


def verse_is_valid(surah: int, ayah: int) -> bool:
    if not (1 <= surah <= 114) or ayah < 1:
        return False
    return f'{surah}:{ayah}' in qpc_hafs_data_normalized


def verse_words(surah: int, ayah: int) -> list[str]:
    """Recited-word list (ornaments dropped), same basis as `_verse_word_texts`."""
    td = qpc_hafs_data_normalized.get(f'{surah}:{ayah}')
    text = (td.get('text', '') if isinstance(td, dict) else '') or ''
    return [tok for tok in text.split() if _has_arabic_letter(tok)]


def _stop_word(surah: int, ayah: int, wpos: int) -> str:
    words = verse_words(surah, ayah)
    if 0 <= wpos < len(words):
        return words[wpos]
    return ''


def _shape_entry(row: dict, surah: int, ayah: int) -> dict | None:
    try:
        wpos = int(row['wpos'])
    except (TypeError, ValueError, KeyError):
        return None
    stop_word = _stop_word(surah, ayah, wpos)
    if not stop_word:
        return None
    created = row.get('created_at') or row.get('posted_at') or None
    return {
        'wpos': wpos,
        'stop_word': stop_word,
        'quote': row.get('quote') or '',
        'note': row.get('note') or '',
        'grade': row.get('grade') or None,
        'url': row.get('url') or '',
        'created_at': created,
    }


def _from_supabase(surah: int, ayah: int) -> list[dict]:
    rows = sb._request(
        'GET',
        'tawjih',
        params={
            'surah': f'eq.{surah}',
            'ayah': f'eq.{ayah}',
            'status': 'eq.published',
            'align_conf': 'eq.1',
            'select': 'tweet_id,wpos,quote,note,grade',
            'order': 'wpos.asc',
        },
    ) or []
    tweet_ids = sorted({str(r.get('tweet_id') or '') for r in rows if r.get('tweet_id')})
    posts = {}
    if tweet_ids:
        posted = sb._request(
            'GET',
            'dr_ahmed21_posts',
            params={
                'tweet_id': 'in.(' + ','.join(f'"{tid}"' for tid in tweet_ids) + ')',
                'select': _POST_SELECT,
            },
        ) or []
        posts = {str(p['tweet_id']): p for p in posted if p.get('tweet_id')}
    out = []
    for row in rows:
        post = posts.get(str(row.get('tweet_id') or ''), {})
        merged = dict(row)
        merged['url'] = post.get('url') or ''
        merged['posted_at'] = post.get('posted_at')
        shaped = _shape_entry(merged, surah, ayah)
        if shaped:
            out.append(shaped)
    return out


def _from_sqlite(surah: int, ayah: int, db_path: str | None = None) -> list[dict]:
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        return []
    conn = _sqlite_connect(path, readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT tweet_id, wpos, quote, note, grade, url, created_at '
            'FROM tawjih WHERE surah=? AND ayah=? AND status=? AND align_conf=1 '
            'ORDER BY wpos',
            (surah, ayah, 'published'),
        ).fetchall()
        out = []
        for row in rows:
            shaped = _shape_entry(dict(row), surah, ayah)
            if shaped:
                out.append(shaped)
        return out
    finally:
        conn.close()


def list_published(surah: int, ayah: int) -> list[dict]:
    """Published, uniquely-aligned توجيه for one verse.

    Supabase is the production store. Sqlite is used only when Supabase is
    not configured (tests / offline). A configured-but-empty cloud table is
    a real empty result, not a cue to mix in local rows.
    """
    if sb.is_configured():
        try:
            return _from_supabase(surah, ayah)
        except Exception:
            logger.exception('tawjih supabase read failed for %s:%s', surah, ayah)
            return []
    return _from_sqlite(surah, ayah)


def ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS tawjih (
            id INTEGER PRIMARY KEY,
            tweet_id TEXT NOT NULL,
            surah INTEGER,
            ayah INTEGER,
            wpos INTEGER,
            quote TEXT,
            note TEXT NOT NULL DEFAULT '',
            grade TEXT,
            status TEXT NOT NULL CHECK (status IN ('published','review','skipped')),
            align_conf INTEGER NOT NULL DEFAULT 0,
            skip_reason TEXT,
            locator TEXT,
            url TEXT,
            created_at TEXT
        )'''
    )
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS tawjih_span_uidx '
        'ON tawjih (tweet_id, surah, ayah, wpos)'
    )
