#!/usr/bin/env python3
"""Populate waqf.token_index and waqf.word_index per ayah.

This migration aligns rows in QUL_data/mushaf_waqf.db::waqf to words in
QUL_data/quran_script.db::words (ordered by word_index) and stores:
- 1-based token index in waqf.token_index
- 1-based within-ayah content-word index in waqf.word_index
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import List, Optional


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MUSHAF_WAQF_DB = os.path.join(ROOT_DIR, "QUL_data", "mushaf_waqf.db")
QURAN_SCRIPT_DB = os.path.join(ROOT_DIR, "QUL_data", "quran_script.db")

ARABIC_DIACRITICS_STRIP_PATTERN = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")


def compact_token(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return "".join(ch for ch in text if not ch.isspace())


def normalized_token(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = ARABIC_DIACRITICS_STRIP_PATTERN.sub("", text)
    return "".join(ch for ch in text if not ch.isspace())


def is_content_word_token(value: str) -> bool:
    return bool(normalized_token(value))


def find_match_index(words: List[str], target: str, search_start: int) -> Optional[int]:
    target_raw = compact_token(target)
    target_norm = normalized_token(target)

    if not target_raw and not target_norm:
        return None

    ranges = [range(search_start, len(words)), range(0, search_start)]

    if target_raw:
        for rng in ranges:
            for idx in rng:
                if compact_token(words[idx]) == target_raw:
                    return idx

    if target_norm:
        for rng in ranges:
            for idx in rng:
                if normalized_token(words[idx]) == target_norm:
                    return idx

    return None


def ensure_position_columns(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute('PRAGMA table_info(waqf)')
    cols = [row[1] for row in cur.fetchall()]
    if 'token_index' not in cols:
        cur.execute('ALTER TABLE waqf ADD COLUMN token_index INTEGER')
    if 'word_index' not in cols:
        cur.execute('ALTER TABLE waqf ADD COLUMN word_index INTEGER')
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_waqf_surah_ayah_token_index '
        'ON waqf("السورة", "الآية", token_index)'
    )
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_waqf_surah_ayah_word_index '
        'ON waqf("السورة", "الآية", word_index)'
    )


def main() -> int:
    if not os.path.exists(MUSHAF_WAQF_DB):
        print(f"ERROR: mushaf waqf db not found: {MUSHAF_WAQF_DB}")
        return 1
    if not os.path.exists(QURAN_SCRIPT_DB):
        print(f"ERROR: quran script db not found: {QURAN_SCRIPT_DB}")
        return 1

    mushaf_conn = sqlite3.connect(MUSHAF_WAQF_DB)
    mushaf_conn.row_factory = sqlite3.Row
    script_conn = sqlite3.connect(QURAN_SCRIPT_DB)
    script_conn.row_factory = sqlite3.Row

    try:
        ensure_position_columns(mushaf_conn)

        mcur = mushaf_conn.cursor()
        scur = script_conn.cursor()

        mcur.execute('SELECT DISTINCT "السورة" AS surah, "الآية" AS ayah FROM waqf ORDER BY surah, ayah')
        ayah_keys = mcur.fetchall()

        updated = 0
        unmatched = 0
        unmatched_samples = []

        mcur.execute('BEGIN')

        for key in ayah_keys:
            surah = int(key['surah'])
            ayah = int(key['ayah'])

            scur.execute(
                'SELECT word_index, text_original, text FROM words WHERE surah = ? AND ayah = ? ORDER BY word_index ASC',
                (surah, ayah),
            )
            script_rows = scur.fetchall()
            script_words = [row['text_original'] or row['text'] or '' for row in script_rows]
            content_positions = []
            current_pos = 0
            for token in script_words:
                if is_content_word_token(token):
                    current_pos += 1
                content_positions.append(current_pos)

            if not script_words:
                mcur.execute(
                    'UPDATE waqf SET token_index = NULL, word_index = NULL WHERE "السورة" = ? AND "الآية" = ?',
                    (surah, ayah)
                )
                continue

            mcur.execute(
                'SELECT rowid, "الكلمة" AS word FROM waqf WHERE "السورة" = ? AND "الآية" = ? ORDER BY rowid ASC',
                (surah, ayah),
            )
            waqf_rows = mcur.fetchall()

            search_start = 0
            for row in waqf_rows:
                idx = find_match_index(script_words, row['word'] or '', search_start)
                if idx is None:
                    mcur.execute('UPDATE waqf SET token_index = NULL, word_index = NULL WHERE rowid = ?', (row['rowid'],))
                    unmatched += 1
                    if len(unmatched_samples) < 20:
                        unmatched_samples.append((surah, ayah, row['word'] or ''))
                    continue

                verse_word_index = content_positions[idx] if idx < len(content_positions) else None
                # Store 1-based token index and 1-based within-ayah word index.
                mcur.execute(
                    'UPDATE waqf SET token_index = ?, word_index = ? WHERE rowid = ?',
                    (idx + 1, int(verse_word_index) if verse_word_index else None, row['rowid'])
                )
                updated += 1
                search_start = idx + 1

        mushaf_conn.commit()

        print(f"Updated token_index rows: {updated}")
        print(f"Unmatched rows: {unmatched}")
        if unmatched_samples:
            print("Unmatched samples (surah, ayah, word):")
            for sample in unmatched_samples:
                print(sample)

        return 0
    finally:
        mushaf_conn.close()
        script_conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
