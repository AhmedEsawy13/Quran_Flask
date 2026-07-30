"""Load edition marks from mushaf_waqf.db and map onto layout word_ids.

Kept Flask-free so the OpenCV venv does not need the web stack.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

from core.config import MUSHAF_WAQF_DATABASE

# Waqf / ornament codepoints stripped for fuzzy token compare.
_STRIP_MARKS = re.compile(
    r'[\u0614\u0615\u0617\u06D6-\u06ED\u06E9\u08F0-\u08FF]'
)
_DIACRITICS = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED]')


def _compact(token: str) -> str:
    return re.sub(r'\s+', '', token or '')


def _normalize(token: str) -> str:
    text = unicodedata.normalize('NFKC', token or '')
    text = _STRIP_MARKS.sub('', text)
    text = _DIACRITICS.sub('', text)
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    text = text.replace('ى', 'ي').replace('ة', 'ه')
    return _compact(text)


def ayah_words(script_db: str, surah: int, ayah: int) -> list[dict]:
    conn = sqlite3.connect(script_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            'SELECT word_index AS word_id, word_index, text '
            'FROM words WHERE surah=? AND ayah=? ORDER BY word_index ASC',
            (surah, ayah),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _match_row_index(words: list[dict], row: dict, search_start: int = 0) -> int | None:
    """Map a mushaf_waqf row onto an ayah word list index."""
    if not words:
        return None
    target_raw = _compact(row.get('clean_token') or row.get('word') or '')
    target_norm = _normalize(row.get('clean_token') or row.get('word') or '')
    hinted = _word_index_hint(words, row.get('word_index'))

    if not target_raw and not target_norm:
        if hinted is not None:
            return hinted
        return None

    if hinted is not None:
        hinted_text = words[hinted].get('text') or ''
        if (target_raw and _compact(hinted_text) == target_raw) or (
            target_norm and _normalize(hinted_text) == target_norm
        ):
            return hinted

    ranges = [range(search_start, len(words)), range(0, search_start)]
    if target_raw:
        for rng in ranges:
            for idx in rng:
                if _compact(words[idx].get('text') or '') == target_raw:
                    return idx
    if target_norm:
        for rng in ranges:
            for idx in rng:
                if _normalize(words[idx].get('text') or '') == target_norm:
                    return idx
    return hinted


def _word_index_hint(words: list[dict], raw) -> int | None:
    """``mushaf_waqf.word_index`` is 1-based within-ayah content-word position."""
    if raw is None:
        return None
    try:
        hinted_pos = int(raw)
    except (TypeError, ValueError):
        return None
    if hinted_pos <= 0:
        return None
    current = 0
    for idx, word in enumerate(words):
        if _normalize(word.get('text') or ''):
            current += 1
            if current == hinted_pos:
                return idx
    return None


def edition_marks_for_ayahs(
    edition: str,
    ayah_keys: list[tuple[int, int]],
    script_db: str,
) -> dict[tuple[int, int, int], str]:
    """Map (surah, ayah, layout_word_id) → letter code."""
    if not ayah_keys:
        return {}
    quoted = '"' + edition.replace('"', '""') + '"'
    out: dict[tuple[int, int, int], str] = {}
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        for surah, ayah in ayah_keys:
            rows = conn.execute(
                f'SELECT "الكلمة" AS word, token_index, word_index, '
                f'{quoted} AS symbol FROM waqf '
                f'WHERE "السورة"=? AND "الآية"=? '
                f'AND {quoted} IS NOT NULL AND {quoted}!="" '
                f'ORDER BY rowid ASC',
                (surah, ayah),
            ).fetchall()
            if not rows:
                continue
            words = ayah_words(script_db, surah, ayah)
            if not words:
                continue
            search_start = 0
            for row in rows:
                matched = _match_row_index(words, {
                    'word': row['word'] or '',
                    'word_index': row['word_index'],
                }, search_start)
                if matched is None:
                    ti = row['token_index']
                    try:
                        ti = int(ti) - 1 if ti is not None else None
                    except (TypeError, ValueError):
                        ti = None
                    if ti is None or not (0 <= ti < len(words)):
                        continue
                    matched = ti
                search_start = matched + 1
                symbol = _normalize_symbol((row['symbol'] or '').strip())
                if symbol:
                    out[(surah, ayah, int(words[matched]['word_id']))] = symbol
    finally:
        conn.close()
    return out


def _normalize_symbol(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw or raw == 'ركوع':
        return raw
    for code in ('قلى', 'قلي', 'صلى', 'صلي', 'لا', 'م', 'ق', 'ص', 'ج', 'س', 'ع'):
        if code in raw.replace(' ', ''):
            if code in ('قلى', 'قلي'):
                return 'ق'
            if code in ('صلى', 'صلي'):
                return 'ص'
            return code
    glyph_map = {
        'ۘ': 'م', 'ۗ': 'ق', 'ۖ': 'ص', 'ۚ': 'ج',
        'ۙ': 'لا', 'ۛ': 'ع', 'ۜ': 'س',
    }
    for ch, code in glyph_map.items():
        if ch in raw:
            return code
    return raw.split(',')[0].strip()


def within_ayah_token_index(
    script_db: str, word_id: int,
) -> tuple[int, int, int, str] | None:
    """Return (surah, ayah, 0-based token_index, text) for a layout word_id."""
    conn = sqlite3.connect(script_db)
    try:
        row = conn.execute(
            'SELECT surah, ayah, text FROM words WHERE word_index=?',
            (word_id,),
        ).fetchone()
        if not row:
            return None
        surah, ayah, text = int(row[0]), int(row[1]), row[2] or ''
        ids = [
            int(r[0]) for r in conn.execute(
                'SELECT word_index FROM words WHERE surah=? AND ayah=? '
                'ORDER BY word_index ASC',
                (surah, ayah),
            )
        ]
        if word_id not in ids:
            return None
        return surah, ayah, ids.index(word_id), text
    finally:
        conn.close()
